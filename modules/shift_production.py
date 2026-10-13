from flask import Blueprint, render_template, request, redirect, abort, send_file, session
from db import get_db
from datetime import date, timedelta
from db import fetch_active_machines
import io
import csv

shift_bp = Blueprint("shift", __name__, url_prefix="/shift")


def admin_required():
    if session.get("role") != "Admin":
        abort(403)


def has_shift_production_setup_no(db):
    cols = db.execute("PRAGMA table_info(shift_production)").fetchall()
    return any((col["name"] if hasattr(col, "keys") else col[1]) == "setup_no" for col in cols)


def row_to_dict(row):
    if not row:
        return {}
    return {key: row[key] for key in row.keys()}


def pad_rows(rows, minimum):
    result = [row_to_dict(row) for row in rows]
    while len(result) < minimum:
        result.append({})
    return result


def int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def load_shift_form_options(db):
    return {
        "machines": fetch_active_machines(db),
        "item_codes": db.execute("""
            SELECT item_code
            FROM item_code_master
            ORDER BY item_code
        """).fetchall(),
    }


def shift_form_context(db, *, mode="add", header=None, production=None, setup=None, attendance=None, downtime=None):
    options = load_shift_form_options(db)
    header_values = row_to_dict(header)
    if not header_values:
        header_values = {
            "shift_date": date.today().isoformat(),
            "shift": "",
            "shift_incharge": "",
            "remarks": "",
        }

    return {
        **options,
        "mode": mode,
        "today": date.today().isoformat(),
        "header": header_values,
        "production_rows": pad_rows(production or [], 6),
        "setup_rows": pad_rows(setup or [], 3),
        "attendance_rows": pad_rows(attendance or [], 5),
        "downtime_rows": pad_rows(downtime or [], 3),
    }


def save_shift_children(db, shift_id, *, replace=False):
    if replace:
        for table in ("shift_production", "shift_setup", "shift_attendance", "shift_downtime"):
            db.execute(f"DELETE FROM {table} WHERE shift_id=?", (shift_id,))

    # ================= PRODUCTION =================
    items = request.form.getlist("item_code[]")
    setup_nos = request.form.getlist("setup_no[]")
    machine_codes = request.form.getlist("machine_code[]")
    operators = request.form.getlist("operator[]")
    oks = request.form.getlist("ok_qty[]")
    rejs = request.form.getlist("rej_qty[]")

    n = min(len(items), len(setup_nos), len(machine_codes), len(operators), len(oks), len(rejs))

    for i in range(n):
        item = (items[i] or "").strip()
        if not item:
            continue

        ok = int_or_zero(oks[i])
        rej = int_or_zero(rejs[i])

        if ok == 0 and rej == 0:
            continue

        db.execute("""
            INSERT INTO shift_production
            (shift_id, item_code, setup_no, machine, operator, ok_qty, rej_qty)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            shift_id,
            item,
            (setup_nos[i] or "").strip(),
            (machine_codes[i] or "").strip(),
            (operators[i] or "").strip(),
            ok,
            rej
        ))

    # ================= SETUP CHANGE =================
    setup_job = request.form.getlist("setup_job[]")
    setup_change_time = request.form.getlist("setup_change_time[]")
    setup_machine = request.form.getlist("setup_machine[]")
    setup_start_time = request.form.getlist("setup_start_time[]")

    n = min(len(setup_job), len(setup_change_time), len(setup_machine), len(setup_start_time))

    for i in range(n):
        job = (setup_job[i] or "").strip()
        change_time = (setup_change_time[i] or "").strip()
        machine = (setup_machine[i] or "").strip()
        start_time = (setup_start_time[i] or "").strip()

        if not any((job, change_time, machine, start_time)):
            continue

        db.execute("""
            INSERT INTO shift_setup
            (shift_id, machine, from_item, to_item, remarks)
            VALUES (?, ?, ?, ?, ?)
        """, (
            shift_id,
            machine,
            job,
            change_time,
            start_time
        ))

    # ================= ATTENDANCE =================
    att_operator = request.form.getlist("att_operator[]")
    att_status = request.form.getlist("att_status[]")

    n = min(len(att_operator), len(att_status))

    for i in range(n):
        operator = (att_operator[i] or "").strip()
        if not operator:
            continue

        db.execute("""
            INSERT INTO shift_attendance
            (shift_id, operator, status)
            VALUES (?, ?, ?)
        """, (
            shift_id,
            operator,
            (att_status[i] or "Present").strip()
        ))

    # ================= DOWNTIME =================
    down_machine_code = request.form.getlist("down_machine_code[]")
    dt_reason = request.form.getlist("dt_reason[]")
    dt_minutes = request.form.getlist("dt_minutes[]")

    n = min(len(down_machine_code), len(dt_reason), len(dt_minutes))

    for i in range(n):
        machine = (down_machine_code[i] or "").strip()
        if not machine:
            continue

        db.execute("""
            INSERT INTO shift_downtime
            (shift_id, machine, reason, minutes)
            VALUES (?, ?, ?, ?)
        """, (
            shift_id,
            machine,
            (dt_reason[i] or "").strip(),
            int_or_zero(dt_minutes[i])
        ))


def resolve_machine_report_filters(args):
    today = date.today()
    date_range = (args.get("date_range") or "last_7").strip()

    if date_range == "today":
        from_date = today.isoformat()
        to_date = today.isoformat()
    elif date_range == "last_15":
        from_date = (today - timedelta(days=14)).isoformat()
        to_date = today.isoformat()
    elif date_range == "last_30":
        from_date = (today - timedelta(days=29)).isoformat()
        to_date = today.isoformat()
    elif date_range == "this_month":
        from_date = today.replace(day=1).isoformat()
        to_date = today.isoformat()
    elif date_range == "custom":
        from_date = (args.get("from_date") or (today - timedelta(days=6)).isoformat()).strip()
        to_date = (args.get("to_date") or today.isoformat()).strip()
    else:
        date_range = "last_7"
        from_date = (today - timedelta(days=6)).isoformat()
        to_date = today.isoformat()

    return {
        "date_range": date_range,
        "from_date": from_date,
        "to_date": to_date,
        "shift": (args.get("shift") or "").strip(),
        "machine_code": (args.get("machine_code") or "").strip(),
    }


def load_machine_report_data(db, filters):
    setup_expr = (
        "GROUP_CONCAT(DISTINCT NULLIF(TRIM(COALESCE(sp.setup_no, '')), ''))"
        if has_shift_production_setup_no(db)
        else "''"
    )
    query = """
        SELECT
            sh.shift_date,
            sh.shift,
            sp.machine AS machine_code,
            COALESCE(mm.machine_name, '') AS machine_name,
            GROUP_CONCAT(DISTINCT sp.item_code) AS item_codes,
            {setup_expr} AS setup_nos,
            SUM(COALESCE(sp.ok_qty, 0)) AS ok_qty,
            SUM(COALESCE(sp.rej_qty, 0)) AS rej_qty,
            SUM(COALESCE(sp.ok_qty, 0) + COALESCE(sp.rej_qty, 0)) AS total_qty
        FROM shift_production sp
        JOIN shift_header sh ON sh.id = sp.shift_id
        LEFT JOIN machine_master mm ON mm.machine_code = sp.machine
        WHERE sp.machine IS NOT NULL
          AND sp.machine != ''
          AND date(sh.shift_date) BETWEEN date(?) AND date(?)
    """
    params = [filters["from_date"], filters["to_date"]]

    if filters["shift"]:
        query += " AND sh.shift = ?"
        params.append(filters["shift"])

    if filters["machine_code"]:
        query += " AND sp.machine = ?"
        params.append(filters["machine_code"])

    query += """
        GROUP BY sh.shift_date, sh.shift, sp.machine, mm.machine_name
        ORDER BY date(sh.shift_date) DESC, sh.shift, sp.machine
    """
    query = query.format(setup_expr=setup_expr)

    rows = db.execute(query, params).fetchall()

    summary = db.execute("""
        SELECT
            COALESCE(SUM(ok_qty), 0) AS ok_qty,
            COALESCE(SUM(rej_qty), 0) AS rej_qty,
            COALESCE(SUM(total_qty), 0) AS total_qty
        FROM (
            SELECT
                SUM(COALESCE(sp.ok_qty, 0)) AS ok_qty,
                SUM(COALESCE(sp.rej_qty, 0)) AS rej_qty,
                SUM(COALESCE(sp.ok_qty, 0) + COALESCE(sp.rej_qty, 0)) AS total_qty
            FROM shift_production sp
            JOIN shift_header sh ON sh.id = sp.shift_id
            WHERE sp.machine IS NOT NULL
              AND sp.machine != ''
              AND date(sh.shift_date) BETWEEN date(?) AND date(?)
              AND (? = '' OR sh.shift = ?)
              AND (? = '' OR sp.machine = ?)
            GROUP BY sh.shift_date, sh.shift, sp.machine
        ) x
    """, (
        filters["from_date"],
        filters["to_date"],
        filters["shift"],
        filters["shift"],
        filters["machine_code"],
        filters["machine_code"],
    )).fetchone()

    return rows, summary

# ================= LIST / LANDING =================

@shift_bp.route("/")
def shift_home():
    return redirect("/shift/add")

# ================= ADD SHIFT =================

@shift_bp.route("/add", methods=["GET", "POST"])
def shift_add():
    db = get_db()

    if request.method == "POST":
        shift_date = request.form["shift_date"]
        shift = request.form["shift"]
        incharge = request.form["shift_incharge"]
        remarks = request.form.get("remarks", "")

        if not shift_date or not shift or not incharge:
            abort(400, "Missing header fields")

        # ---- create shift header ----
        row = db.execute("""
            SELECT id FROM shift_header
            WHERE shift_date=? AND shift=?
        """, (shift_date, shift)).fetchone()

        if row:
            abort(400, "Shift already exists")

        db.execute("""
            INSERT INTO shift_header
            (shift_date, shift, shift_incharge, remarks)
            VALUES (?, ?, ?, ?)
        """, (shift_date, shift, incharge, remarks))

        shift_id = db.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        save_shift_children(db, shift_id)

        db.commit()
        return redirect("/shift/view")

    return render_template(
        "shift/shift_entry.html",
        **shift_form_context(db, mode="add")
    )


@shift_bp.route("/edit/<int:shift_id>", methods=["GET", "POST"])
def shift_edit(shift_id):
    admin_required()
    db = get_db()

    header = db.execute("""
        SELECT * FROM shift_header
        WHERE id=?
    """, (shift_id,)).fetchone()

    if not header:
        abort(404)

    if request.method == "POST":
        shift_date = request.form["shift_date"]
        shift = request.form["shift"]
        incharge = request.form["shift_incharge"]
        remarks = request.form.get("remarks", "")

        if not shift_date or not shift or not incharge:
            abort(400, "Missing header fields")

        row = db.execute("""
            SELECT id FROM shift_header
            WHERE shift_date=? AND shift=? AND id<>?
        """, (shift_date, shift, shift_id)).fetchone()

        if row:
            abort(400, "Shift already exists")

        db.execute("""
            UPDATE shift_header
            SET shift_date=?, shift=?, shift_incharge=?, remarks=?
            WHERE id=?
        """, (shift_date, shift, incharge, remarks, shift_id))

        save_shift_children(db, shift_id, replace=True)

        db.commit()
        return redirect(f"/shift/view/{shift_id}")

    production = db.execute("""
        SELECT * FROM shift_production
        WHERE shift_id=?
        ORDER BY id
    """, (shift_id,)).fetchall()

    setup = db.execute("""
        SELECT * FROM shift_setup
        WHERE shift_id=?
        ORDER BY id
    """, (shift_id,)).fetchall()

    attendance = db.execute("""
        SELECT * FROM shift_attendance
        WHERE shift_id=?
        ORDER BY id
    """, (shift_id,)).fetchall()

    downtime = db.execute("""
        SELECT * FROM shift_downtime
        WHERE shift_id=?
        ORDER BY id
    """, (shift_id,)).fetchall()

    return render_template(
        "shift/shift_entry.html",
        **shift_form_context(
            db,
            mode="edit",
            header=header,
            production=production,
            setup=setup,
            attendance=attendance,
            downtime=downtime
        )
    )

# ================= VIEW (SUPERVISOR) =================

@shift_bp.route("/view")
def shift_view():
    db = get_db()

    rows = db.execute("""
        SELECT id, shift_date, shift, shift_incharge
        FROM shift_header
        ORDER BY shift_date DESC, shift
    """).fetchall()

    return render_template("shift/shift_list.html", rows=rows)

@shift_bp.route("/view/<int:shift_id>")
def shift_detail(shift_id):
    db = get_db()

    header = db.execute("""
        SELECT * FROM shift_header
        WHERE id=?
    """, (shift_id,)).fetchone()

    if not header:
        abort(404)

    production = db.execute("""
        SELECT * FROM shift_production
        WHERE shift_id=?
    """, (shift_id,)).fetchall()

    setup = db.execute("""
        SELECT * FROM shift_setup
        WHERE shift_id=?
    """, (shift_id,)).fetchall()

    attendance = db.execute("""
        SELECT * FROM shift_attendance
        WHERE shift_id=?
    """, (shift_id,)).fetchall()

    downtime = db.execute("""
        SELECT * FROM shift_downtime
        WHERE shift_id=?
    """, (shift_id,)).fetchall()

    return render_template(
        "shift/shift_detail.html",
        header=header,
        production=production,
        setup=setup,
        attendance=attendance,
        downtime=downtime
    )
@shift_bp.route("/view/")
def shift_view_slash_redirect():
    return redirect("/shift/view")


# ================= MACHINE WORK REPORT =================

@shift_bp.route("/report")
def shift_machine_report():
    db = get_db()
    filters = resolve_machine_report_filters(request.args)
    rows, summary = load_machine_report_data(db, filters)

    machines = fetch_active_machines(db)

    return render_template(
        "shift/shift_report.html",
        rows=rows,
        machines=machines,
        summary=summary,
        date_range=filters["date_range"],
        from_date=filters["from_date"],
        to_date=filters["to_date"],
        shift=filters["shift"],
        machine_code=filters["machine_code"]
    )


@shift_bp.route("/report/excel")
def shift_machine_report_excel():
    db = get_db()
    filters = resolve_machine_report_filters(request.args)
    rows, _ = load_machine_report_data(db, filters)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date",
        "Shift",
        "Machine",
        "Machine Name",
        "Item Codes",
        "Setup Nos",
        "OK Qty",
        "Reject Qty",
        "Total Qty",
    ])
    for r in rows:
        writer.writerow([
            r["shift_date"],
            r["shift"],
            r["machine_code"],
            r["machine_name"],
            r["item_codes"] or "",
            r["setup_nos"] or "",
            r["ok_qty"],
            r["rej_qty"],
            r["total_qty"],
        ])

    data = output.getvalue().encode("utf-8-sig")
    buf = io.BytesIO(data)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name="machine_work_report.csv",
        mimetype="text/csv; charset=utf-8",
    )

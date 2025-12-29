from flask import Blueprint, render_template, request, redirect, abort
from db import get_db
from datetime import date
from db import fetch_active_machines

shift_bp = Blueprint("shift", __name__, url_prefix="/shift")

# ================= LIST / LANDING =================

@shift_bp.route("/")
def shift_home():
    return redirect("/shift/add")

# ================= ADD SHIFT =================

@shift_bp.route("/add", methods=["GET", "POST"])
def shift_add():
    db = get_db()
    machines = fetch_active_machines(db)

    item_codes = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()

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

        # ================= PRODUCTION =================
        items = request.form.getlist("item_code[]")
        machine_codes = request.form.getlist("machine_code[]")
        operators = request.form.getlist("operator[]")
        oks = request.form.getlist("ok_qty[]")
        rejs = request.form.getlist("rej_qty[]")

        n = min(len(items), len(machine_codes), len(operators), len(oks), len(rejs))

        for i in range(n):
            item = (items[i] or "").strip()
            if not item:
                continue

            ok = int(oks[i] or 0)
            rej = int(rejs[i] or 0)

            if ok == 0 and rej == 0:
                continue

            db.execute("""
                INSERT INTO shift_production
                (shift_id, item_code, machine, operator, ok_qty, rej_qty)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                shift_id,
                item,
                (machine_codes[i] or "").strip(),   # machine_code stored in 'machine'
                (operators[i] or "").strip(),
                ok,
                rej
            ))

        # ================= SETUP CHANGE =================
        setup_job = request.form.getlist("setup_job[]")
        setup_change_time = request.form.getlist("setup_change_time[]")
        setup_machine = request.form.getlist("setup_machine[]")
        setup_start_time = request.form.getlist("setup_start_time[]")

        for i in range(len(setup_job)):
            if not setup_job[i]:
                continue

            db.execute("""
                INSERT INTO shift_setup
                (shift_id, machine, from_item, to_item, remarks)
                VALUES (?, ?, ?, ?, ?)
            """, (
                shift_id,
                setup_machine[i],
                setup_job[i],              #- store Job & Setup No. here
                setup_change_time[i],      #-- store Change Time
                setup_start_time[i]        #-- store Production Start Time
            ))

        # ================= ATTENDANCE =================
        att_operator = request.form.getlist("att_operator[]")
        att_status = request.form.getlist("att_status[]")

        for i in range(len(att_operator)):
            if not att_operator[i]:
                continue

            db.execute("""
                INSERT INTO shift_attendance
                (shift_id, operator, status)
                VALUES (?, ?, ?)
            """, (
                shift_id,
                att_operator[i],
                att_status[i]
            ))

        # ================= DOWNTIME =================
        down_machine_code = request.form.getlist("down_machine_code[]")
        dt_reason = request.form.getlist("dt_reason[]")
        dt_minutes = request.form.getlist("dt_minutes[]")

        for i in range(len(down_machine_code)):
            if not down_machine_code[i]:
                continue

            db.execute("""
                INSERT INTO shift_downtime
                (shift_id, machine, reason, minutes)
                VALUES (?, ?, ?, ?)
            """, (
                shift_id,
                down_machine_code[i],
                dt_reason[i],
                int(dt_minutes[i] or 0)
            ))

        db.commit()
        return redirect("/shift/view")

    return render_template(
        "shift/shift_entry.html",
        machines=machines,
        today=date.today(),
        item_codes=item_codes
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

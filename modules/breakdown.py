from flask import Blueprint, render_template, request, redirect, abort
from datetime import date, datetime
from flask import current_app
from db import get_db, fetch_active_machines

breakdown_bp = Blueprint("breakdown", __name__, url_prefix="/breakdown")


def check_pin(pin: str) -> bool:
    return (pin or "").strip() == current_app.config.get("ADMIN_PIN", "")


def _parse_time_hhmm(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        datetime.strptime(s, "%H:%M")
        return s
    except Exception:
        return None


def _calc_minutes(start_hhmm: str, end_hhmm: str) -> int:
    """Assumes same-day times. If end < start, treat as 0 (avoid negative)."""
    st = datetime.strptime(start_hhmm, "%H:%M")
    en = datetime.strptime(end_hhmm, "%H:%M")
    mins = int((en - st).total_seconds() // 60)
    return max(mins, 0)


@breakdown_bp.route("/")
def bd_home():
    return redirect("/breakdown/list")


# ================= LIST =================
@breakdown_bp.route("/list")
def bd_list():
    db = get_db()
    machines = fetch_active_machines(db)

    machine_code = (request.args.get("machine_code") or "").strip()
    status = (request.args.get("status") or "").strip()
    from_date = (request.args.get("from_date") or "").strip()
    to_date = (request.args.get("to_date") or "").strip()

    query = """
        SELECT
            b.id,
            b.breakdown_date,
            b.machine_code,
            mm.machine_name,
            b.start_time,
            b.end_time,
            b.downtime_min,
            b.problem,
            b.status,
            b.handled_by
        FROM breakdown_log b
        LEFT JOIN machine_master mm ON mm.machine_code = b.machine_code
        WHERE 1=1
    """
    params = []

    if machine_code:
        query += " AND b.machine_code=?"
        params.append(machine_code)

    if status:
        query += " AND b.status=?"
        params.append(status)

    if from_date:
        query += " AND date(b.breakdown_date) >= date(?)"
        params.append(from_date)

    if to_date:
        query += " AND date(b.breakdown_date) <= date(?)"
        params.append(to_date)

    query += """
        ORDER BY
            CASE b.status WHEN 'OPEN' THEN 1 ELSE 2 END,
            date(b.breakdown_date) DESC,
            b.start_time DESC
    """

    rows = db.execute(query, params).fetchall()

    counts = db.execute("""
        SELECT
            SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) AS open_cnt,
            SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed_cnt
        FROM breakdown_log
    """).fetchone()

    return render_template(
        "breakdown/bd_list.html",
        rows=rows,
        machines=machines,
        counts=counts,
        today=date.today().isoformat()
    )


# ================= ADD =================
@breakdown_bp.route("/add", methods=["GET", "POST"])
def bd_add():
    db = get_db()
    machines = fetch_active_machines(db)

    if request.method == "POST":
        f = request.form
        machine_code = (f.get("machine_code") or "").strip()
        bd_date = (f.get("breakdown_date") or "").strip()
        start_time = _parse_time_hhmm(f.get("start_time"))
        problem = (f.get("problem") or "").strip()
        handled_by = (f.get("handled_by") or "").strip()

        if not machine_code or not bd_date or not start_time or not problem:
            abort(400, "Machine, date, start time and problem are required")

        db.execute("""
            INSERT INTO breakdown_log
            (machine_code, breakdown_date, start_time, problem, handled_by, status)
            VALUES (?, ?, ?, ?, ?, 'OPEN')
        """, (machine_code, bd_date, start_time, problem, handled_by))

        db.commit()
        return redirect("/breakdown/list")

    return render_template(
        "breakdown/bd_add.html",
        machines=machines,
        today=date.today().isoformat()
    )


# ================= DETAIL =================
@breakdown_bp.route("/view/<int:bd_id>")
def bd_view(bd_id: int):
    db = get_db()
    row = db.execute("""
        SELECT
            b.*,
            mm.machine_name
        FROM breakdown_log b
        LEFT JOIN machine_master mm ON mm.machine_code=b.machine_code
        WHERE b.id=?
    """, (bd_id,)).fetchone()

    if not row:
        abort(404)

    return render_template("breakdown/bd_view.html", row=row, today=date.today().isoformat())


# ================= CLOSE =================
@breakdown_bp.route("/close/<int:bd_id>", methods=["GET", "POST"])
def bd_close(bd_id: int):
    db = get_db()

    row = db.execute("""
        SELECT * FROM breakdown_log WHERE id=?
    """, (bd_id,)).fetchone()

    if not row:
        abort(404)

    if request.method == "POST":
        f = request.form
        pin = (f.get("pin") or "").strip()
        if not check_pin(pin):
            abort(403, "Invalid PIN")

        end_time = _parse_time_hhmm(f.get("end_time"))
        root_cause = (f.get("root_cause") or "").strip()
        action_taken = (f.get("action_taken") or "").strip()
        handled_by = (f.get("handled_by") or "").strip()

        if not end_time:
            abort(400, "End time required (HH:MM)")

        mins = _calc_minutes(row["start_time"], end_time)

        db.execute("""
            UPDATE breakdown_log
            SET end_time=?,
                downtime_min=?,
                root_cause=?,
                action_taken=?,
                handled_by=?,
                status='CLOSED'
            WHERE id=?
        """, (end_time, mins, root_cause, action_taken, handled_by, bd_id))

        db.commit()
        return redirect(f"/breakdown/view/{bd_id}")

    return render_template("breakdown/bd_close.html", row=row)


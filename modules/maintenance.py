from flask import Blueprint, render_template, request, redirect, abort
from datetime import date, datetime, timedelta
from flask import current_app
from db import get_db, fetch_active_machines

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/maintenance")


def check_pin(pin: str) -> bool:
    return (pin or "").strip() == current_app.config.get("ADMIN_PIN", "")


def _to_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _status_for(next_due: date, due_soon_days: int = 7) -> str:
    today = date.today()
    if next_due < today:
        return "OVERDUE"
    if next_due <= (today + timedelta(days=due_soon_days)):
        return "DUE"
    return "OK"


def _refresh_pm_statuses(db):
    """Update status in DB based on next_due_date."""
    rows = db.execute("""
        SELECT id, next_due_date
        FROM pm_schedule
    """).fetchall()

    for r in rows:
        nd = _to_date(r["next_due_date"])
        if not nd:
            continue
        st = _status_for(nd)
        db.execute("UPDATE pm_schedule SET status=? WHERE id=?", (st, r["id"]))
    db.commit()


@maintenance_bp.route("/")
def maintenance_home():
    return redirect("/maintenance/pm")


# =========================
# PM DASHBOARD
# =========================
@maintenance_bp.route("/pm")
def pm_list():
    db = get_db()
    _refresh_pm_statuses(db)

    # Optional filters
    machine_code = (request.args.get("machine_code") or "").strip()
    status = (request.args.get("status") or "").strip()

    query = """
        SELECT
            ps.id AS schedule_id,
            mm.machine_code,
            mm.machine_name,
            pm.pm_name,
            pm.frequency_days,
            pm.responsibility,
            ps.last_done_date,
            ps.next_due_date,
            ps.status
        FROM pm_schedule ps
        JOIN pm_master pm ON pm.id = ps.pm_id
        LEFT JOIN machine_master mm ON mm.machine_code = pm.machine_code
        WHERE pm.active = 1
    """
    params = []

    if machine_code:
        query += " AND pm.machine_code = ?"
        params.append(machine_code)

    if status:
        query += " AND ps.status = ?"
        params.append(status)

    query += """
        ORDER BY
            CASE ps.status
                WHEN 'OVERDUE' THEN 1
                WHEN 'DUE' THEN 2
                ELSE 3
            END,
            date(ps.next_due_date) ASC,
            pm.machine_code,
            pm.pm_name
    """

    rows = db.execute(query, params).fetchall()

    machines = fetch_active_machines(db)

    # counts for header tiles
    counts = db.execute("""
        SELECT
            SUM(CASE WHEN status='OVERDUE' THEN 1 ELSE 0 END) AS overdue,
            SUM(CASE WHEN status='DUE' THEN 1 ELSE 0 END) AS due,
            SUM(CASE WHEN status='OK' THEN 1 ELSE 0 END) AS ok
        FROM pm_schedule ps
        JOIN pm_master pm ON pm.id = ps.pm_id
        WHERE pm.active = 1
    """).fetchone()

    return render_template(
        "maintenance/pm_list.html",
        rows=rows,
        machines=machines,
        counts=counts
    )


# =========================
# ADD PM PLAN
# =========================
@maintenance_bp.route("/pm/add", methods=["GET", "POST"])
def pm_add():
    db = get_db()
    machines = fetch_active_machines(db)

    if request.method == "POST":
        f = request.form
        machine_code = (f.get("machine_code") or "").strip()
        pm_name = (f.get("pm_name") or "").strip()
        frequency_days = int(f.get("frequency_days") or 0)
        responsibility = (f.get("responsibility") or "").strip()
        checklist = (f.get("checklist") or "").strip()

        if not machine_code or not pm_name or frequency_days <= 0:
            abort(400, "Machine, PM Name, Frequency are required")

        # Create PM master
        db.execute("""
            INSERT INTO pm_master
            (machine_code, pm_name, frequency_days, responsibility, checklist, active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (machine_code, pm_name, frequency_days, responsibility, checklist))

        pm_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Create initial schedule: next_due = today + frequency
        today = date.today()
        next_due = today + timedelta(days=frequency_days)
        status = _status_for(next_due)

        db.execute("""
            INSERT INTO pm_schedule
            (pm_id, last_done_date, next_due_date, status)
            VALUES (?, ?, ?, ?)
        """, (pm_id, None, next_due.isoformat(), status))

        db.commit()
        return redirect("/maintenance/pm")

    return render_template("maintenance/pm_add.html", machines=machines, today=date.today())


# =========================
# MARK PM DONE
# =========================
@maintenance_bp.route("/pm/done/<int:schedule_id>", methods=["GET", "POST"])
def pm_done(schedule_id: int):
    db = get_db()

    row = db.execute("""
        SELECT
            ps.id AS schedule_id,
            ps.pm_id,
            ps.last_done_date,
            ps.next_due_date,
            ps.status,
            pm.machine_code,
            pm.pm_name,
            pm.frequency_days
        FROM pm_schedule ps
        JOIN pm_master pm ON pm.id = ps.pm_id
        WHERE ps.id = ?
    """, (schedule_id,)).fetchone()

    if not row:
        abort(404)

    if request.method == "POST":
        f = request.form
        pin = (f.get("pin") or "").strip()
        if not check_pin(pin):
            abort(403, "Invalid PIN")

        done_date = _to_date(f.get("done_date")) or date.today()
        done_by = (f.get("done_by") or "").strip()
        remarks = (f.get("remarks") or "").strip()

        # history
        db.execute("""
            INSERT INTO pm_history (pm_id, done_date, done_by, remarks)
            VALUES (?, ?, ?, ?)
        """, (row["pm_id"], done_date.isoformat(), done_by, remarks))

        # schedule update: last_done = done_date, next_due = done_date + freq
        next_due = done_date + timedelta(days=int(row["frequency_days"]))
        status = _status_for(next_due)

        db.execute("""
            UPDATE pm_schedule
            SET last_done_date = ?,
                next_due_date = ?,
                status = ?
            WHERE id = ?
        """, (done_date.isoformat(), next_due.isoformat(), status, schedule_id))

        db.commit()
        return redirect("/maintenance/pm")

    return render_template("maintenance/pm_done.html", row=row, today=date.today())


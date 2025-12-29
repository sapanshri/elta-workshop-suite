from flask import Blueprint, render_template, request, abort
from datetime import date, datetime, timedelta
from db import get_db, fetch_active_machines

machine_history_bp = Blueprint("machine_history", __name__, url_prefix="/machine-history")


def _to_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


@machine_history_bp.route("/")
def mh_list():
    db = get_db()

    # Filters
    status = (request.args.get("status") or "ACTIVE").strip()  # default ACTIVE
    machine_type = (request.args.get("machine_type") or "").strip()
    q = (request.args.get("q") or "").strip()

    # Get machine types for dropdown
    types = db.execute("""
        SELECT DISTINCT machine_type
        FROM machine_master
        WHERE machine_type IS NOT NULL AND machine_type != ''
        ORDER BY machine_type
    """).fetchall()

    query = """
        SELECT
            mm.machine_code,
            mm.machine_name,
            mm.machine_type,
            mm.controller,
            mm.location,
            mm.status
        FROM machine_master mm
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND mm.status=?"
        params.append(status)

    if machine_type:
        query += " AND mm.machine_type=?"
        params.append(machine_type)

    if q:
        query += " AND (mm.machine_code LIKE ? OR mm.machine_name LIKE ? OR mm.controller LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like])

    query += " ORDER BY mm.machine_code"

    machines = db.execute(query, params).fetchall()

    return render_template(
        "machine_history/mh_list.html",
        machines=machines,
        types=types
    )


@machine_history_bp.route("/<machine_code>")
def mh_detail(machine_code: str):
    db = get_db()

    mm = db.execute("""
        SELECT *
        FROM machine_master
        WHERE machine_code=?
    """, (machine_code,)).fetchone()

    if not mm:
        abort(404)

    # ---------- PM SUMMARY ----------
    pm_counts = db.execute("""
        SELECT
            SUM(CASE WHEN ps.status='OVERDUE' THEN 1 ELSE 0 END) AS overdue,
            SUM(CASE WHEN ps.status='DUE' THEN 1 ELSE 0 END) AS due,
            SUM(CASE WHEN ps.status='OK' THEN 1 ELSE 0 END) AS ok,
            COUNT(*) AS total
        FROM pm_schedule ps
        JOIN pm_master pm ON pm.id = ps.pm_id
        WHERE pm.active=1 AND pm.machine_code=?
    """, (machine_code,)).fetchone()

    next_pm = db.execute("""
        SELECT
            pm.pm_name,
            ps.status,
            ps.next_due_date,
            ps.last_done_date,
            pm.frequency_days,
            ps.id AS schedule_id
        FROM pm_schedule ps
        JOIN pm_master pm ON pm.id = ps.pm_id
        WHERE pm.active=1 AND pm.machine_code=?
        ORDER BY
            CASE ps.status WHEN 'OVERDUE' THEN 1 WHEN 'DUE' THEN 2 ELSE 3 END,
            date(ps.next_due_date) ASC
        LIMIT 1
    """, (machine_code,)).fetchone()

    last_pm_done = db.execute("""
        SELECT
            h.done_date,
            h.done_by,
            h.remarks,
            pm.pm_name
        FROM pm_history h
        JOIN pm_master pm ON pm.id = h.pm_id
        WHERE pm.machine_code=?
        ORDER BY date(h.done_date) DESC, h.id DESC
        LIMIT 5
    """, (machine_code,)).fetchall()

    # ---------- BREAKDOWN SUMMARY ----------
    open_breakdowns = db.execute("""
        SELECT COUNT(*) AS cnt
        FROM breakdown_log
        WHERE machine_code=? AND status='OPEN'
    """, (machine_code,)).fetchone()["cnt"]

    # downtime last 30 days (closed only)
    from_30 = (date.today() - timedelta(days=30)).isoformat()
    downtime_30 = db.execute("""
        SELECT COALESCE(SUM(downtime_min), 0) AS mins
        FROM breakdown_log
        WHERE machine_code=?
          AND status='CLOSED'
          AND date(breakdown_date) >= date(?)
    """, (machine_code, from_30)).fetchone()["mins"]

    last_breakdowns = db.execute("""
        SELECT
            id,
            breakdown_date,
            start_time,
            end_time,
            downtime_min,
            problem,
            status
        FROM breakdown_log
        WHERE machine_code=?
        ORDER BY
            CASE status WHEN 'OPEN' THEN 1 ELSE 2 END,
            date(breakdown_date) DESC,
            start_time DESC
        LIMIT 8
    """, (machine_code,)).fetchall()

    return render_template(
        "machine_history/mh_detail.html",
        mm=mm,
        pm_counts=pm_counts,
        next_pm=next_pm,
        last_pm_done=last_pm_done,
        open_breakdowns=open_breakdowns,
        downtime_30=downtime_30,
        last_breakdowns=last_breakdowns,
        from_30=from_30
    )


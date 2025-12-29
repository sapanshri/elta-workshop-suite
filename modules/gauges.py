from flask import Blueprint, render_template, request, redirect
from db import get_db
from datetime import date, timedelta
from db import fetch_active_machines

gauges_bp = Blueprint("gauges", __name__, url_prefix="/gauges")

# ================= UTILITIES =================

PREFIX_MAP = {
    "Vernier Caliper": "VER",
    "Micrometer": "MIC",
    "Bore Gauge": "BG",
    "Height Gauge": "HG",
    "Dial Indicator": "DI",
    "Slip Gauge": "SG",
    "Snap Gauge": "SNAP",
    "Plain Plug Gauge": "PPG",
    "Thread Plug Gauge": "TPG",
    "Thread Ring Gauge": "TRG",
    "Air Plug Gauge": "APG",
    "Air Ring Gauge": "ARG",
    "Qualifying Gauge": "QG",
    "Wear Check Ring": "WCR",
    "Wear Check Plug": "WCP",
    "Custom": "CUS"
}

def generate_gauge_code(db, subtype):
    prefix = PREFIX_MAP.get(subtype, "CUS")
    row = db.execute("""
        SELECT gauge_code FROM gauges
        WHERE gauge_code LIKE ?
        ORDER BY gauge_code DESC LIMIT 1
    """, (f"{prefix}-%",)).fetchone()

    if row:
        last_num = int(row[0].split("-")[1])
        return f"{prefix}-{last_num + 1:03d}"
    else:
        return f"{prefix}-001"


def update_gauge_status(row):
    if not row["next_calibration"]:
        return "OK"

    today = date.today()
    next_cal = date.fromisoformat(row["next_calibration"])

    if today > next_cal:
        return "OVERDUE"
    elif today + timedelta(days=30) >= next_cal:
        return "DUE"
    return "OK"


# ================= MASTER LIST =================
@gauges_bp.route("/")
def gauges():
    db = get_db()
    rows = db.execute("SELECT * FROM gauges").fetchall()

    # Update status based on calibration date
    updated = False
    for r in rows:
        new_status = update_gauge_status(r)
        if new_status != r["status"]:
            db.execute(
                "UPDATE gauges SET status=? WHERE id=?",
                (new_status, r["id"])
            )
            updated = True

    if updated:
        db.commit()
        rows = db.execute("SELECT * FROM gauges").fetchall()

    # ---- AUTO SORT: OVERDUE → DUE → OK ----
    status_order = {
        "OVERDUE": 1,
        "DUE": 2,
        "OK": 3,
        "DAMAGED": 4
    }

    rows = sorted(
        rows,
        key=lambda r: (
            status_order.get(r["status"], 99),
            r["next_calibration"] or "9999-12-31"
        )
    )

    return render_template(
        "gauges.html",
        gauges=rows,
        today=date.today()
    )


# ================= ADD GAUGE =================

@gauges_bp.route("/add", methods=["GET", "POST"])
def add_gauge():
    db = get_db()

    if request.method == "POST":
        subtype = request.form["subtype"]
        gauge_code = generate_gauge_code(db, subtype)

        last_cal = request.form.get("last_calibration") or None
        freq = int(request.form.get("calibration_freq", 365))

        next_cal = None
        if last_cal:
            next_cal = (
                date.fromisoformat(last_cal) +
                timedelta(days=freq)
            )

        db.execute("""
            INSERT INTO gauges
            (gauge_code, category, subtype, mechanism, range,
             least_count, make, serial_no, location,
             calibration_freq, last_calibration, next_calibration, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            gauge_code,
            request.form["category"],
            subtype,
            request.form["mechanism"],
            request.form["range"],
            request.form.get("least_count"),
            request.form.get("make"),
            request.form.get("serial_no"),
            request.form.get("location"),
            freq,
            last_cal,
            next_cal,
            request.form.get("remarks")
        ))

        db.commit()
        return redirect("/gauges")

    return render_template("gauge_add.html")


# ================= ISSUE =================

@gauges_bp.route("/issue", methods=["GET", "POST"])
def issue_gauge():
    db = get_db()

    if request.method == "POST":
        db.execute("""
            INSERT INTO gauge_issue_txn
            (gauge_id, action, operator, machine, job, shift, txn_date)
            VALUES (?, 'ISSUE', ?, ?, ?, ?, ?)
        """, (
            request.form["gauge_id"],
            request.form["operator"],
            request.form["machine"],
            request.form["job"],
            request.form["shift"],
            request.form["issue_date"]
        ))
        db.commit()
        return redirect("/gauges")

    rows = db.execute("""
        SELECT * FROM gauges
        WHERE status IN ('OK', 'DUE')
    """).fetchall()

    return render_template(
        "gauge_issue.html",
        gauges=rows,
        today=date.today()
    )


# ================= RETURN =================

@gauges_bp.route("/return", methods=["GET", "POST"])
def return_gauge():
    db = get_db()

    if request.method == "POST":
        db.execute("""
            INSERT INTO gauge_issue_txn
            (gauge_id, action, operator, shift,
             condition_on_return, remarks, txn_date)
            VALUES (?, 'RETURN', ?, ?, ?, ?, ?)
        """, (
            request.form["gauge_id"],
            request.form["operator"],
            request.form["shift"],
            request.form["condition"],
            request.form.get("remarks"),
            request.form["return_date"]
        ))

        if request.form["condition"] == "DAMAGED":
            db.execute(
                "UPDATE gauges SET status='DAMAGED' WHERE id=?",
                (request.form["gauge_id"],)
            )

        db.commit()
        return redirect("/gauges")

    rows = db.execute("SELECT * FROM gauges").fetchall()
    return render_template(
        "gauge_return.html",
        gauges=rows,
        today=date.today()
    )


# ================= CALIBRATION =================

@gauges_bp.route("/calibrate", methods=["GET", "POST"])
def calibrate_gauge():
    db = get_db()

    if request.method == "POST":
        cal_date = date.fromisoformat(request.form["calibration_date"])
        freq = int(request.form.get("calibration_freq", 365))
        next_cal = cal_date + timedelta(days=freq)

        db.execute("""
            INSERT INTO gauge_calibration_txn
            (gauge_id, calibration_date, calibrated_by,
             result, certificate_no, remarks)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            request.form["gauge_id"],
            cal_date,
            request.form["calibrated_by"],
            request.form["result"],
            request.form.get("certificate_no"),
            request.form.get("remarks")
        ))

        db.execute("""
            UPDATE gauges
            SET last_calibration=?,
                next_calibration=?,
                status='OK'
            WHERE id=?
        """, (cal_date, next_cal, request.form["gauge_id"]))

        db.commit()
        return redirect("/gauges")

    rows = db.execute("SELECT * FROM gauges").fetchall()
    return render_template(
        "gauge_calibration.html",
        gauges=rows,
        today=date.today()
    )


# ================= HISTORY =================

@gauges_bp.route("/history")
def gauge_history():
    db = get_db()
    rows = db.execute("""
        SELECT g.gauge_code, g.subtype,
               t.action, t.operator, t.machine,
               t.job, t.shift, t.condition_on_return, t.txn_date
        FROM gauge_issue_txn t
        JOIN gauges g ON g.id = t.gauge_id
        ORDER BY t.txn_date DESC
    """).fetchall()

    return render_template("gauge_history.html", rows=rows)


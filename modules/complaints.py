from flask import Blueprint, render_template, request, redirect, abort, current_app
from datetime import date, datetime
from db import get_db
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io


complaints_bp = Blueprint("complaints", __name__, url_prefix="/complaints")

# -------------------------
# Config / constants
# -------------------------

ISSUE_CATEGORIES = [
    "Dimensional",
    "Burr",
    "Surface Finish",
    "Thread",
    "Hardness",
    "Mix-up / Wrong Part",
    "Damage",
    "Rust / Corrosion",
    "Other",
]

SEVERITIES = ["LOW", "MED", "HIGH"]

STATUSES = [
    "OPEN",
    "UNDER_INVESTIGATION",
    "WAITING_CUSTOMER",
    "CAPA_IMPLEMENTED",
    "CLOSED",
    "REJECTED",
]

LOG_TYPES = ["NOTE", "CONTAINMENT", "RCA", "CAPA", "CUSTOMER_REPLY", "CLOSE"]


def check_two_pins(pin1, pin2) -> bool:
    """
    Uses same pattern as Materials Manage.
    Set these in app.py:
        app.config["ADMIN_PIN_1"] = "7091"
        app.config["ADMIN_PIN_2"] = "8588"
    """
    return (
        (pin1 or "").strip() == str(current_app.config.get("ADMIN_PIN_1", "")).strip()
        and (pin2 or "").strip() == str(current_app.config.get("ADMIN_PIN_2", "")).strip()
    )


def _next_complaint_no(db) -> str:
    """
    CC-YYYY-###  (resets every year)
    """
    year = date.today().year
    prefix = f"CC-{year}-"

    row = db.execute(
        """
        SELECT complaint_no
        FROM customer_complaint
        WHERE complaint_no LIKE ?
        ORDER BY complaint_no DESC
        LIMIT 1
        """,
        (prefix + "%",),
    ).fetchone()

    if not row:
        return f"{prefix}001"

    last = row["complaint_no"]  # e.g. CC-2025-014
    try:
        last_num = int(last.split("-")[-1])
    except Exception:
        last_num = 0

    return f"{prefix}{last_num + 1:03d}"


# -------------------------
# List
# -------------------------

@complaints_bp.route("/")
def list_complaints():
    db = get_db()

    customer_id = request.args.get("customer_id", "")
    item_code = request.args.get("item_code", "")
    status = request.args.get("status", "")
    severity = request.args.get("severity", "")
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")

    query = """
        SELECT
            cc.id,
            cc.complaint_no,
            cc.complaint_date,
            c.customer_name,
            cc.item_code,
            cc.issue_category,
            cc.severity,
            cc.status,
            cc.assigned_to
        FROM customer_complaint cc
        JOIN customer_master c ON c.id = cc.customer_id
        WHERE 1=1
    """
    params = []

    if customer_id:
        query += " AND cc.customer_id=?"
        params.append(customer_id)

    if item_code:
        query += " AND cc.item_code=?"
        params.append(item_code)

    if status:
        query += " AND cc.status=?"
        params.append(status)

    if severity:
        query += " AND cc.severity=?"
        params.append(severity)

    if from_date:
        query += " AND date(cc.complaint_date) >= date(?)"
        params.append(from_date)

    if to_date:
        query += " AND date(cc.complaint_date) <= date(?)"
        params.append(to_date)

    query += " ORDER BY date(cc.complaint_date) DESC, cc.id DESC"

    rows = db.execute(query, params).fetchall()

    customers = db.execute("""
        SELECT id, customer_name
        FROM customer_master
        ORDER BY customer_name
    """).fetchall()

    item_codes = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()

    return render_template(
        "complaints/complaints.html",
        rows=rows,
        customers=customers,
        item_codes=item_codes,
        statuses=STATUSES,
        severities=SEVERITIES
    )


# -------------------------
# Add complaint
# -------------------------

@complaints_bp.route("/add", methods=["GET", "POST"])
def add_complaint():
    db = get_db()

    customers = db.execute("""
        SELECT id, customer_name
        FROM customer_master
        ORDER BY customer_name
    """).fetchall()

    item_codes = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()

    machines = db.execute("""
        SELECT machine_code, machine_name
        FROM machine_master
        WHERE status='ACTIVE'
        ORDER BY machine_code
    """).fetchall()

    complaint_no = _next_complaint_no(db)

    if request.method == "POST":
        complaint_date = request.form.get("complaint_date") or ""
        customer_id = request.form.get("customer_id") or ""
        customer_ref_no = (request.form.get("customer_ref_no") or "").strip()

        item_code = (request.form.get("item_code") or "").strip()
        batch_no = (request.form.get("batch_no") or "").strip()
        qty_affected = int(request.form.get("qty_affected") or 0)

        issue_category = request.form.get("issue_category") or ""
        issue_description = (request.form.get("issue_description") or "").strip()

        severity = request.form.get("severity") or "MED"

        machine_code = (request.form.get("machine_code") or "").strip()
        job_no = (request.form.get("job_no") or "").strip()
        shift_date = (request.form.get("shift_date") or "").strip()
        shift = (request.form.get("shift") or "").strip()

        assigned_to = (request.form.get("assigned_to") or "").strip()
        containment_action = (request.form.get("containment_action") or "").strip()

        if not complaint_date:
            abort(400, "Complaint date required")
        if not customer_id:
            abort(400, "Customer required")
        if not item_code:
            abort(400, "Item code required")
        if issue_category not in ISSUE_CATEGORIES:
            abort(400, "Invalid category")
        if not issue_description:
            abort(400, "Issue description required")
        if severity not in SEVERITIES:
            abort(400, "Invalid severity")

        # allocate complaint_no at save time (in case multiple users add simultaneously)
        complaint_no_final = _next_complaint_no(db)

        db.execute("""
            INSERT INTO customer_complaint
            (complaint_no, complaint_date, customer_id, customer_ref_no,
             item_code, batch_no, qty_affected,
             issue_category, issue_description, severity,
             status, machine_code, job_no, shift_date, shift,
             assigned_to, containment_action, updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            complaint_no_final,
            complaint_date,
            customer_id,
            customer_ref_no,
            item_code,
            batch_no,
            qty_affected,
            issue_category,
            issue_description,
            severity,
            "OPEN",
            machine_code,
            job_no,
            shift_date,
            shift,
            assigned_to,
            containment_action,
            datetime.now().isoformat(timespec="seconds")
        ))

        complaint_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # auto-log creation
        db.execute("""
            INSERT INTO complaint_action_log
            (complaint_id, action_date, action_type, notes, by_user)
            VALUES (?,?,?,?,?)
        """, (
            complaint_id,
            complaint_date,
            "NOTE",
            f"Complaint registered: {issue_category}",
            assigned_to or ""
        ))

        db.commit()
        return redirect(f"/complaints/view/{complaint_id}")

    return render_template(
        "complaints/complaint_add.html",
        today=date.today().isoformat(),
        complaint_no=complaint_no,
        customers=customers,
        item_codes=item_codes,
        machines=machines,
        categories=ISSUE_CATEGORIES,
        severities=SEVERITIES
    )


# -------------------------
# View detail
# -------------------------

@complaints_bp.route("/view/<int:cid>")
def view_complaint(cid: int):
    db = get_db()

    header = db.execute("""
        SELECT
            cc.*,
            c.customer_name
        FROM customer_complaint cc
        JOIN customer_master c ON c.id = cc.customer_id
        WHERE cc.id=?
    """, (cid,)).fetchone()

    if not header:
        abort(404)

    logs = db.execute("""
        SELECT *
        FROM complaint_action_log
        WHERE complaint_id=?
        ORDER BY date(action_date) DESC, id DESC
    """, (cid,)).fetchall()

    customers = db.execute("""
        SELECT id, customer_name
        FROM customer_master
        ORDER BY customer_name
    """).fetchall()

    item_codes = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()

    machines = db.execute("""
        SELECT machine_code, machine_name
        FROM machine_master
        WHERE status='ACTIVE'
        ORDER BY machine_code
    """).fetchall()

    return render_template(
        "complaints/complaint_view.html",
        header=header,
        logs=logs,
        customers=customers,
        item_codes=item_codes,
        machines=machines,
        categories=ISSUE_CATEGORIES,
        severities=SEVERITIES,
        statuses=STATUSES,
        log_types=LOG_TYPES,
        today=date.today().isoformat()
    )


@complaints_bp.route("/view/<int:cid>/pdf")
@complaints_bp.route("/view/<int:cid>/pdf")
def complaint_pdf(cid: int):
    db = get_db()

    header = db.execute("""
        SELECT
            cc.*,
            c.customer_name
        FROM customer_complaint cc
        JOIN customer_master c ON c.id = cc.customer_id
        WHERE cc.id=?
    """, (cid,)).fetchone()

    if not header:
        abort(404)

    logs = db.execute("""
        SELECT *
        FROM complaint_action_log
        WHERE complaint_id=?
        ORDER BY date(action_date) DESC, id DESC
    """, (cid,)).fetchall()

    # ---- sqlite3.Row safe getter ----
    def rget(row, key, default=""):
        try:
            return row[key]
        except Exception:
            return default

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    def wrap_text(text, max_width, font="Helvetica", size=9):
        pdf.setFont(font, size)
        if text is None or str(text).strip() == "":
            return ["-"]
        words = str(text).split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if pdf.stringWidth(test, font, size) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Customer Complaint Report")
    y -= 18
    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, y, f"Generated on: {date.today().isoformat()}")
    y -= 18
    pdf.line(40, y, width - 40, y)
    y -= 18

    # Header fields
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, f"Complaint ID: {rget(header, 'id')}")
    y -= 16

    fields = [
        ("Customer", rget(header, "customer_name")),
        ("Complaint Date", rget(header, "complaint_date")),
        ("Status", rget(header, "status")),
        ("Category", rget(header, "issue_category")),
        ("Severity", rget(header, "severity")),
        ("Assigned To", rget(header, "assigned_to")),
        ("Machine", rget(header, "machine_code")),
        ("Item Code", rget(header, "item_code")),
        ("ELTA Ref / Challan", rget(header, "elta_ref") or rget(header, "elta_challan_no") or ""),
    ]

    pdf.setFont("Helvetica", 9)
    for k, v in fields:
        if y < 80:
            pdf.showPage()
            y = height - 60
            pdf.setFont("Helvetica", 9)

        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(40, y, f"{k}:")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(160, y, (str(v) if v else "-"))
        y -= 14

    y -= 6
    pdf.line(40, y, width - 40, y)
    y -= 18

    # Long text sections
    problem = rget(header, "problem_desc") or rget(header, "problem_description")
    sections = [
        ("Problem Description", problem),
        ("Root Cause", rget(header, "root_cause")),
        ("Corrective Action", rget(header, "corrective_action")),
        ("Preventive Action", rget(header, "preventive_action")),
        ("Remarks", rget(header, "remarks")),
    ]

    for title, text in sections:
        if y < 120:
            pdf.showPage()
            y = height - 60

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, title)
        y -= 14
        pdf.setFont("Helvetica", 9)

        for line in wrap_text(text, max_width=width - 80):
            if y < 60:
                pdf.showPage()
                y = height - 60
                pdf.setFont("Helvetica", 9)
            pdf.drawString(40, y, line)
            y -= 12

        y -= 8

    # Logs section
    if y < 120:
        pdf.showPage()
        y = height - 60

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, "Action Log")
    y -= 16

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(40, y, "Date")
    pdf.drawString(120, y, "Type")
    pdf.drawString(200, y, "By")
    pdf.drawString(290, y, "Notes")
    y -= 12
    pdf.setFont("Helvetica", 9)

    for r in logs:
        if y < 60:
            pdf.showPage()
            y = height - 60
            pdf.setFont("Helvetica", 9)

        action_date = (rget(r, "action_date") or "")[:10]
        action_type = (rget(r, "action_type") or rget(r, "log_type") or "-")[:12]
        action_by = (rget(r, "action_by") or rget(r, "owner") or "-")[:12]
        notes = rget(r, "notes") or rget(r, "remark") or ""

        pdf.drawString(40, y, action_date or "-")
        pdf.drawString(120, y, action_type)
        pdf.drawString(200, y, action_by)

        note_lines = wrap_text(notes, max_width=width - 290 - 40)
        pdf.drawString(290, y, note_lines[0] if note_lines else "-")
        y -= 12

        for extra in note_lines[1:]:
            if y < 60:
                pdf.showPage()
                y = height - 60
                pdf.setFont("Helvetica", 9)
            pdf.drawString(290, y, extra)
            y -= 12

        y -= 2

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"complaint_{rget(header, 'id')}.pdf",
        mimetype="application/pdf"
    )



# -------------------------
# Update complaint (2-PIN)
# -------------------------

@complaints_bp.route("/update/<int:cid>", methods=["POST"])
def update_complaint(cid: int):
    db = get_db()

    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    # fields
    complaint_date = request.form.get("complaint_date") or ""
    customer_id = request.form.get("customer_id") or ""
    customer_ref_no = (request.form.get("customer_ref_no") or "").strip()

    item_code = (request.form.get("item_code") or "").strip()
    batch_no = (request.form.get("batch_no") or "").strip()
    qty_affected = int(request.form.get("qty_affected") or 0)

    issue_category = request.form.get("issue_category") or ""
    issue_description = (request.form.get("issue_description") or "").strip()

    severity = request.form.get("severity") or "MED"
    status = request.form.get("status") or "OPEN"

    machine_code = (request.form.get("machine_code") or "").strip()
    job_no = (request.form.get("job_no") or "").strip()
    shift_date = (request.form.get("shift_date") or "").strip()
    shift = (request.form.get("shift") or "").strip()

    assigned_to = (request.form.get("assigned_to") or "").strip()
    containment_action = (request.form.get("containment_action") or "").strip()
    root_cause_5why = (request.form.get("root_cause_5why") or "").strip()
    corrective_action = (request.form.get("corrective_action") or "").strip()
    preventive_action = (request.form.get("preventive_action") or "").strip()

    closure_date = (request.form.get("closure_date") or "").strip()
    closure_remarks = (request.form.get("closure_remarks") or "").strip()

    if not complaint_date:
        abort(400, "Complaint date required")
    if not customer_id:
        abort(400, "Customer required")
    if not item_code:
        abort(400, "Item code required")
    if issue_category not in ISSUE_CATEGORIES:
        abort(400, "Invalid category")
    if not issue_description:
        abort(400, "Issue description required")
    if severity not in SEVERITIES:
        abort(400, "Invalid severity")
    if status not in STATUSES:
        abort(400, "Invalid status")

    # If closing, enforce closure_date
    if status == "CLOSED" and not closure_date:
        abort(400, "Closure date required to close complaint")

    db.execute("""
        UPDATE customer_complaint
        SET complaint_date=?,
            customer_id=?,
            customer_ref_no=?,
            item_code=?,
            batch_no=?,
            qty_affected=?,
            issue_category=?,
            issue_description=?,
            severity=?,
            status=?,
            machine_code=?,
            job_no=?,
            shift_date=?,
            shift=?,
            assigned_to=?,
            containment_action=?,
            root_cause_5why=?,
            corrective_action=?,
            preventive_action=?,
            closure_date=?,
            closure_remarks=?,
            updated_ts=?
        WHERE id=?
    """, (
        complaint_date,
        customer_id,
        customer_ref_no,
        item_code,
        batch_no,
        qty_affected,
        issue_category,
        issue_description,
        severity,
        status,
        machine_code,
        job_no,
        shift_date,
        shift,
        assigned_to,
        containment_action,
        root_cause_5why,
        corrective_action,
        preventive_action,
        closure_date,
        closure_remarks,
        datetime.now().isoformat(timespec="seconds"),
        cid
    ))

    # auto-log status changes (optional simple log)
    db.execute("""
        INSERT INTO complaint_action_log
        (complaint_id, action_date, action_type, notes, by_user)
        VALUES (?,?,?,?,?)
    """, (
        cid,
        date.today().isoformat(),
        "NOTE",
        f"Updated complaint. Status: {status}",
        assigned_to or ""
    ))

    db.commit()
    return redirect(f"/complaints/view/{cid}")


# -------------------------
# Add log line (2-PIN)
# -------------------------

@complaints_bp.route("/log/add/<int:cid>", methods=["POST"])
def add_log(cid: int):
    db = get_db()

    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    action_date = request.form.get("action_date") or date.today().isoformat()
    action_type = request.form.get("action_type") or "NOTE"
    notes = (request.form.get("notes") or "").strip()
    by_user = (request.form.get("by_user") or "").strip()

    if action_type not in LOG_TYPES:
        abort(400, "Invalid log type")
    if not notes:
        abort(400, "Notes required")

    # ensure complaint exists
    exists = db.execute("SELECT id FROM customer_complaint WHERE id=?", (cid,)).fetchone()
    if not exists:
        abort(404)

    db.execute("""
        INSERT INTO complaint_action_log
        (complaint_id, action_date, action_type, notes, by_user)
        VALUES (?,?,?,?,?)
    """, (cid, action_date, action_type, notes, by_user))

    db.commit()
    return redirect(f"/complaints/view/{cid}")


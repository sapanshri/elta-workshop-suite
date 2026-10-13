from flask import Blueprint, render_template, request, redirect, abort, current_app, send_file
from db import get_db
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io
import csv
from flask import jsonify


materials_bp = Blueprint("materials", __name__, url_prefix="/materials")


# ================= SECURITY =================

def check_two_pins(pin1, pin2):
    return (
        (pin1 or "").strip() == str(current_app.config.get("ADMIN_PIN_1", "")).strip()
        and
        (pin2 or "").strip() == str(current_app.config.get("ADMIN_PIN_2", "")).strip()
    )


# ================= UTIL =================

def calc_total_dispatch(form):
    return (
        int(form.get("ok_qty", 0) or 0) +
        int(form.get("rej_qty", 0) or 0) +
        int(form.get("cd_qty", 0) or 0) +
        int(form.get("nd_qty", 0) or 0) +
        int(form.get("nd_pw_qty", 0) or 0)
    )


def update_challan_status(db, challan_id):
    if not challan_id:
        return

    remaining = db.execute("""
        SELECT COUNT(*) AS cnt
        FROM material_inward
        WHERE challan_id=? AND available_qty > 0
    """, (challan_id,)).fetchone()["cnt"]

    status = "CLOSED" if remaining == 0 else "OPEN"
    db.execute("UPDATE customer_challan SET status=? WHERE id=?", (status, challan_id))


def load_dispatch_rows_by_elta(db, elta_challan_no):
    return db.execute("""
        SELECT
            md.id,
            COALESCE(md.source_type, 'INWARD') AS source_type,
            CASE
                WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN 'IN-HOUSE'
                ELSE c.customer_name
            END AS customer_name,
            CASE
                WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN COALESCE(ih.batch_no, 'In-house')
                ELSE ch.customer_challan_no
            END AS customer_challan_no,
            CASE
                WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN ih.stock_date
                ELSE ch.customer_challan_date
            END AS customer_challan_date,
            md.elta_challan_no,
            md.dispatch_date,
            COALESCE(mi.item_code, ih.item_code) AS item_code,
            COALESCE(mi.process, ih.process, '') AS process,
            md.ok_qty, md.rej_qty, md.cd_qty, md.nd_qty, md.nd_pw_qty, md.total_qty
        FROM material_dispatch md
        LEFT JOIN material_inward mi ON mi.id = md.inward_id
        LEFT JOIN customer_challan ch ON ch.id = md.challan_id
        LEFT JOIN customer_master c ON c.id = ch.customer_id
        LEFT JOIN material_inhouse_stock ih
            ON COALESCE(md.source_type, 'INWARD') = 'INHOUSE'
           AND ih.id = md.source_id
        WHERE md.elta_challan_no=?
        ORDER BY date(md.dispatch_date) DESC, md.id DESC
    """, (elta_challan_no,)).fetchall()


def db_table_exists(db, table_name):
    row = db.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name=?
    """, (table_name,)).fetchone()
    return row is not None


def db_has_column(db, table_name, column_name):
    try:
        cols = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    except Exception:
        return False
    return any((c["name"] if hasattr(c, "keys") else c[1]) == column_name for c in cols)


def load_inventory_rows(db, customer_id="", item_code="", status="", from_date="", to_date=""):
    closed_mode = (status == "CLOSED")
    source_dispatch_supported = (
        closed_mode
        and db_has_column(db, "material_dispatch", "source_type")
        and db_has_column(db, "material_dispatch", "source_id")
        and db_table_exists(db, "material_inhouse_stock")
    )

    if closed_mode and source_dispatch_supported:
        query = """
            SELECT
                CASE
                    WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN 'IN-HOUSE'
                    ELSE c.customer_name
                END AS customer_name,
                CASE
                    WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN COALESCE(ih.batch_no, 'In-house')
                    ELSE ch.customer_challan_no
                END AS customer_challan_no,
                CASE
                    WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN 'CLOSED'
                    ELSE ch.status
                END AS status,
                md.dispatch_date,
                md.elta_challan_no,
                COALESCE(mi.item_code, ih.item_code) AS item_code,
                COALESCE(mi.process, ih.process, '') AS process,
                COALESCE(mi.inward_qty, ih.produced_qty, 0) AS inward_qty,
                COALESCE(mi.available_qty, ih.available_qty, 0) AS available_qty,
                md.ok_qty,
                md.rej_qty,
                md.cd_qty,
                md.nd_qty,
                md.nd_pw_qty,
                md.total_qty
            FROM material_dispatch md
            LEFT JOIN material_inward mi ON mi.id = md.inward_id
            LEFT JOIN customer_challan ch ON ch.id = md.challan_id
            LEFT JOIN customer_master c ON c.id = ch.customer_id
            LEFT JOIN material_inhouse_stock ih
                ON COALESCE(md.source_type, 'INWARD') = 'INHOUSE'
               AND ih.id = md.source_id
            WHERE 1=1
        """
    elif closed_mode:
        query = """
            SELECT
                c.customer_name,
                ch.customer_challan_no,
                ch.status,
                md.dispatch_date,
                md.elta_challan_no,
                mi.item_code,
                mi.process,
                mi.inward_qty,
                mi.available_qty,
                md.ok_qty,
                md.rej_qty,
                md.cd_qty,
                md.nd_qty,
                md.nd_pw_qty,
                md.total_qty
            FROM material_dispatch md
            JOIN material_inward mi ON mi.id = md.inward_id
            JOIN customer_challan ch ON ch.id = md.challan_id
            JOIN customer_master c ON c.id = ch.customer_id
            WHERE 1=1
        """
    else:
        query = """
            SELECT
                c.customer_name,
                ch.customer_challan_no,
                ch.status,
                NULL AS dispatch_date,
                '' AS elta_challan_no,
                mi.item_code,
                mi.process,
                mi.inward_qty,
                mi.available_qty,
                0 AS ok_qty,
                0 AS rej_qty,
                0 AS cd_qty,
                0 AS nd_qty,
                0 AS nd_pw_qty,
                0 AS total_qty
            FROM material_inward mi
            JOIN customer_challan ch ON ch.id = mi.challan_id
            JOIN customer_master c ON c.id = ch.customer_id
            WHERE 1=1
        """

    params = []

    if customer_id:
        query += " AND c.id=?"
        params.append(customer_id)

    if item_code:
        if source_dispatch_supported:
            query += " AND COALESCE(mi.item_code, ih.item_code)=?"
        else:
            query += " AND mi.item_code=?"
        params.append(item_code)

    if status:
        if source_dispatch_supported:
            query += """
                AND (CASE
                    WHEN COALESCE(md.source_type, 'INWARD') = 'INHOUSE' THEN 'CLOSED'
                    ELSE ch.status
                END)=?
            """
        else:
            query += " AND ch.status=?"
        params.append(status)

        if closed_mode and from_date and to_date:
            query += " AND md.dispatch_date BETWEEN ? AND ?"
            params.extend([from_date, to_date])

    if closed_mode:
        query += """
            ORDER BY c.customer_name, ch.customer_challan_no, md.dispatch_date DESC, mi.item_code
        """
    else:
        query += """
            ORDER BY c.customer_name, ch.customer_challan_no, mi.item_code
        """

    rows = db.execute(query, params).fetchall()
    return rows, closed_mode


# ================= INWARD ENTRY =================

@materials_bp.route("/inward", methods=["GET", "POST"])
def inward_entry():
    db = get_db()

    customers = db.execute("""
        SELECT id, customer_name
        FROM customer_master
        ORDER BY customer_name
    """).fetchall()

    item_codes_master = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()
    
    if request.method == "POST":
        customer_id = request.form["customer_id"]
        challan_no = (request.form["customer_challan_no"] or "").strip()
        challan_date = request.form["customer_challan_date"]

        if not challan_no:
            abort(400, "Customer challan number required")

        # ---- create or fetch challan header ----
        row = db.execute("""
            SELECT id FROM customer_challan
            WHERE customer_id=? AND customer_challan_no=?
        """, (customer_id, challan_no)).fetchone()

        if row:
            challan_id = row["id"]
        else:
            db.execute("""
                INSERT INTO customer_challan
                (customer_id, customer_challan_no, customer_challan_date, status)
                VALUES (?, ?, ?, 'OPEN')
            """, (customer_id, challan_no, challan_date))
            challan_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # ---- multiple line items ----
        item_codes = request.form.getlist("item_code[]")
        processes = request.form.getlist("process[]")
        qtys = request.form.getlist("qty[]")
        boxes = request.form.getlist("box_tray[]")

        for i in range(len(item_codes)):
            item = (item_codes[i] or "").strip()
            process = (processes[i] or "").strip()
            qty_raw = (qtys[i] or "").strip()

            # skip empty rows safely
            if not item or not qty_raw:
                continue

            qty = int(qty_raw)
            if qty <= 0:
                continue

            existing = db.execute("""
                SELECT id
                FROM material_inward
                WHERE challan_id=? AND item_code=? AND process=?
            """, (challan_id, item, process)).fetchone()

            if existing:
                db.execute("""
                    UPDATE material_inward
                    SET inward_qty = inward_qty + ?,
                        available_qty = available_qty + ?
                    WHERE id=?
                """, (qty, qty, existing["id"]))
            else:
                db.execute("""
                    INSERT INTO material_inward
                    (challan_id, item_code, process, inward_qty, available_qty, box_tray)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (challan_id, item, process, qty, qty, boxes[i] if i < len(boxes) else ""))

        db.commit()
        return redirect("/materials/inventory")

    return render_template("material_inward.html", customers=customers, item_codes=item_codes_master, today=date.today())


# ================= IN-HOUSE STOCK =================

@materials_bp.route("/inhouse-stock", methods=["GET", "POST"])
def inhouse_stock():
    db = get_db()

    item_codes = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()

    if request.method == "POST":
        item_code = (request.form.get("item_code") or "").strip()
        process = (request.form.get("process") or "").strip()
        stock_date = request.form.get("stock_date") or ""
        batch_no = (request.form.get("batch_no") or "").strip()
        remarks = (request.form.get("remarks") or "").strip()
        qty = int(request.form.get("produced_qty") or 0)

        if not item_code:
            abort(400, "Item code required")
        if not stock_date:
            abort(400, "Stock date required")
        if qty <= 0:
            abort(400, "Produced quantity must be > 0")

        db.execute("""
            INSERT INTO material_inhouse_stock
            (item_code, process, stock_date, batch_no, produced_qty, available_qty, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (item_code, process, stock_date, batch_no, qty, qty, remarks))
        db.commit()
        return redirect("/materials/inhouse-stock")

    rows = db.execute("""
        SELECT *
        FROM material_inhouse_stock
        ORDER BY date(stock_date) DESC, id DESC
    """).fetchall()

    return render_template(
        "material_inhouse_stock.html",
        rows=rows,
        item_codes=item_codes,
        today=date.today(),
    )


# ================= DISPATCH =================

@materials_bp.route("/dispatch", methods=["GET", "POST"])
def dispatch_material():
    db = get_db()

    if request.method == "POST":
        work_type = (request.form.get("work_type") or "").strip().upper()
        source_id = request.form.get("source_id") or request.form.get("inward_id")

        elta_challan = (request.form.get("elta_challan_no") or "").strip()
        dispatch_date = request.form.get("dispatch_date") or ""

        if work_type not in ("JOBWORK", "PRODUCT", "INHOUSE"):
            abort(400, "Invalid work type")

        if not source_id:
            abort(400, "Select an item to dispatch")

        if not elta_challan:
            abort(400, "ELTA challan number required")

        total = calc_total_dispatch(request.form)
        if total <= 0:
            abort(400, "Dispatch total must be > 0")

        if work_type == "INHOUSE":
            stock = db.execute("""
                SELECT id, available_qty
                FROM material_inhouse_stock
                WHERE id=?
            """, (source_id,)).fetchone()

            if not stock:
                abort(404, "Selected in-house stock line not found")

            if total > int(stock["available_qty"] or 0):
                abort(400, "Invalid dispatch quantity (exceeds in-house stock)")

            db.execute("""
                INSERT INTO material_dispatch
                (challan_id, inward_id, source_type, source_id, elta_challan_no, dispatch_date,
                 ok_qty, rej_qty, cd_qty, nd_qty, nd_pw_qty, total_qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                None,
                None,
                "INHOUSE",
                stock["id"],
                elta_challan,
                dispatch_date,
                int(request.form.get("ok_qty", 0) or 0),
                int(request.form.get("rej_qty", 0) or 0),
                int(request.form.get("cd_qty", 0) or 0),
                int(request.form.get("nd_qty", 0) or 0),
                int(request.form.get("nd_pw_qty", 0) or 0),
                total,
            ))

            db.execute("""
                UPDATE material_inhouse_stock
                SET available_qty = available_qty - ?
                WHERE id=?
            """, (total, stock["id"]))
        else:
            inward = db.execute("""
                SELECT id, challan_id, available_qty
                FROM material_inward
                WHERE id=?
            """, (source_id,)).fetchone()

            if not inward:
                abort(404, "Selected inward line not found")

            if total > int(inward["available_qty"] or 0):
                abort(400, "Invalid dispatch quantity (exceeds available)")

            db.execute("""
                INSERT INTO material_dispatch
                (challan_id, inward_id, source_type, source_id, elta_challan_no, dispatch_date,
                 ok_qty, rej_qty, cd_qty, nd_qty, nd_pw_qty, total_qty)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                inward["challan_id"],
                inward["id"],
                "INWARD",
                inward["id"],
                elta_challan,
                dispatch_date,
                int(request.form.get("ok_qty", 0) or 0),
                int(request.form.get("rej_qty", 0) or 0),
                int(request.form.get("cd_qty", 0) or 0),
                int(request.form.get("nd_qty", 0) or 0),
                int(request.form.get("nd_pw_qty", 0) or 0),
                total,
            ))

            db.execute("""
                UPDATE material_inward
                SET available_qty = available_qty - ?
                WHERE id=?
            """, (total, inward["id"]))

            update_challan_status(db, inward["challan_id"])

        db.commit()
        return redirect("/materials/inventory")

    challans = db.execute("""
        SELECT
            ch.id AS challan_id,
            c.customer_name,
            ch.customer_challan_no,
            ch.customer_challan_date
        FROM customer_challan ch
        JOIN customer_master c ON c.id = ch.customer_id
        WHERE EXISTS (
            SELECT 1
            FROM material_inward mi
            WHERE mi.challan_id = ch.id
              AND mi.available_qty > 0
        )
        ORDER BY ch.customer_challan_date DESC, ch.customer_challan_no DESC
    """).fetchall()

    item_codes = db.execute("""
        SELECT item_code
        FROM item_code_master
        ORDER BY item_code
    """).fetchall()

    return render_template(
        "material_dispatch.html",
        challans=challans,
        item_codes=item_codes,
        today=date.today()
    )


@materials_bp.get("/dispatch/items/<int:challan_id>")
def dispatch_items_for_challan(challan_id):
    db = get_db()
    rows = db.execute("""
        SELECT
            mi.id AS source_id,
            mi.item_code,
            mi.process,
            mi.available_qty
        FROM material_inward mi
        WHERE mi.challan_id = ?
          AND mi.available_qty > 0
        ORDER BY mi.item_code, mi.process
    """, (challan_id,)).fetchall()

    return jsonify([
        {
            "source_id": r["source_id"],
            "item_code": r["item_code"],
            "process": r["process"] or "",
            "available_qty": int(r["available_qty"] or 0),
            "source_label": "Customer Inward",
        }
        for r in rows
    ])


@materials_bp.get("/dispatch/product-items")
def dispatch_product_items():
    db = get_db()

    rows = db.execute("""
        SELECT
            mi.id AS source_id,
            mi.item_code,
            mi.process,
            mi.available_qty
        FROM material_inward mi
        WHERE mi.available_qty > 0
        ORDER BY mi.item_code
    """).fetchall()

    return jsonify([
        {
            "source_id": r["source_id"],
            "item_code": r["item_code"],
            "process": r["process"] or "",
            "available_qty": int(r["available_qty"] or 0),
            "source_label": "Customer Inward",
        }
        for r in rows
    ])


@materials_bp.get("/dispatch/inhouse-items")
def dispatch_inhouse_items():
    db = get_db()

    rows = db.execute("""
        SELECT
            id AS source_id,
            item_code,
            process,
            batch_no,
            stock_date,
            available_qty
        FROM material_inhouse_stock
        WHERE available_qty > 0
        ORDER BY item_code, date(stock_date) DESC, id DESC
    """).fetchall()

    return jsonify([
        {
            "source_id": r["source_id"],
            "item_code": r["item_code"],
            "process": r["process"] or "",
            "available_qty": int(r["available_qty"] or 0),
            "batch_no": r["batch_no"] or "",
            "stock_date": r["stock_date"] or "",
            "source_label": "In-house Stock",
        }
        for r in rows
    ])

# ================= INVENTORY DISPLAY =================

@materials_bp.route("/inventory")
def inventory():
    db = get_db()

    customer_id = request.args.get("customer_id", "")
    item_code = request.args.get("item_code", "")
    status = request.args.get("status", "")
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")


    rows, _ = load_inventory_rows(db, customer_id, item_code, status, from_date, to_date)

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
        "material_inventory.html",
        rows=rows,
        customers=customers,
        item_codes=item_codes
    )


# ================= PDF EXPORT (MUST MATCH FILTERS) =================

@materials_bp.route("/inventory/pdf")
def inventory_pdf():
    db = get_db()

    customer_id = request.args.get("customer_id", "")
    item_code = request.args.get("item_code", "")
    status = request.args.get("status", "")
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")

    rows, closed_mode = load_inventory_rows(db, customer_id, item_code, status, from_date, to_date)

    def pdf_text(value, max_len=26):
        # ReportLab drawString requires text; normalize None/numeric values safely.
        if value is None:
            return ""
        text = str(value)
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, height - 40, "Material Inventory Report")

    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, height - 60, f"Generated on: {date.today()}")

    y = height - 90

    if closed_mode:
        headers = ["Customer", "ELTA Ch.", "Date", "Item", "Proc", "OK", "REJ", "C/D", "N/D", "N/D PW", "Total"]
        x = [30, 90, 145, 200, 255, 295, 330, 365, 400, 435, 490]
    else:
        headers = ["Customer", "Challan", "Status", "Item", "Process", "Inward", "Available"]
        x = [40, 140, 220, 280, 350, 420, 470]

    pdf.setFont("Helvetica-Bold", 9)
    for i, h in enumerate(headers):
        pdf.drawString(x[i], y, h)

    y -= 15
    pdf.setFont("Helvetica", 9)

    for r in rows:
        if y < 50:
            pdf.showPage()
            pdf.setFont("Helvetica", 9)
            y = height - 50

        if closed_mode:
            pdf.drawString(x[0], y, pdf_text(r["customer_name"], 10))
            pdf.drawString(x[1], y, pdf_text(r["elta_challan_no"], 8))
            pdf.drawString(x[2], y, pdf_text(r["dispatch_date"], 10))
            pdf.drawString(x[3], y, pdf_text(r["item_code"], 8))
            pdf.drawString(x[4], y, pdf_text(r["process"], 6))
            pdf.drawString(x[5], y, pdf_text(r["ok_qty"], 4))
            pdf.drawString(x[6], y, pdf_text(r["rej_qty"], 4))
            pdf.drawString(x[7], y, pdf_text(r["cd_qty"], 4))
            pdf.drawString(x[8], y, pdf_text(r["nd_qty"], 4))
            pdf.drawString(x[9], y, pdf_text(r["nd_pw_qty"], 5))
            pdf.drawString(x[10], y, pdf_text(r["total_qty"], 5))
        else:
            pdf.drawString(x[0], y, pdf_text(r["customer_name"], 18))
            pdf.drawString(x[1], y, pdf_text(r["customer_challan_no"], 14))
            pdf.drawString(x[2], y, pdf_text(r["status"], 10))
            pdf.drawString(x[3], y, pdf_text(r["item_code"], 12))
            pdf.drawString(x[4], y, pdf_text(r["process"], 12))
            pdf.drawString(x[5], y, pdf_text(r["inward_qty"], 8))
            pdf.drawString(x[6], y, pdf_text(r["available_qty"], 8))
        y -= 14

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="material_inventory.pdf",
        mimetype="application/pdf"
    )


@materials_bp.route("/inventory/excel")
def inventory_excel():
    db = get_db()

    customer_id = request.args.get("customer_id", "")
    item_code = request.args.get("item_code", "")
    status = request.args.get("status", "")
    from_date = request.args.get("from_date", "")
    to_date = request.args.get("to_date", "")

    rows, closed_mode = load_inventory_rows(db, customer_id, item_code, status, from_date, to_date)

    output = io.StringIO()
    writer = csv.writer(output)

    if closed_mode:
        writer.writerow([
            "Customer",
            "Customer Challan",
            "Status",
            "ELTA Challan",
            "Dispatch Date",
            "Item Code",
            "Process",
            "Inward Qty",
            "Available Qty",
            "OK Qty",
            "Reject Qty",
            "C/D Qty",
            "N/D Qty",
            "N/D PW Qty",
            "Total Dispatch Qty",
        ])
        for r in rows:
            writer.writerow([
                r["customer_name"],
                r["customer_challan_no"],
                r["status"],
                r["elta_challan_no"],
                r["dispatch_date"],
                r["item_code"],
                r["process"],
                r["inward_qty"],
                r["available_qty"],
                r["ok_qty"],
                r["rej_qty"],
                r["cd_qty"],
                r["nd_qty"],
                r["nd_pw_qty"],
                r["total_qty"],
            ])
    else:
        writer.writerow([
            "Customer",
            "Customer Challan",
            "Status",
            "Item Code",
            "Process",
            "Inward Qty",
            "Available Qty",
        ])
        for r in rows:
            writer.writerow([
                r["customer_name"],
                r["customer_challan_no"],
                r["status"],
                r["item_code"],
                r["process"],
                r["inward_qty"],
                r["available_qty"],
            ])

    data = output.getvalue().encode("utf-8-sig")
    buf = io.BytesIO(data)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name="material_inventory.csv",
        mimetype="text/csv; charset=utf-8"
    )


# ================= MANAGE (PIN) =================

@materials_bp.route("/manage", methods=["GET"])
def manage_page():
    return render_template("material_manage.html")


@materials_bp.route("/manage/load", methods=["POST"])
def manage_load():
    db = get_db()
    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    inward_rows = db.execute("""
        SELECT
            mi.id,
            c.customer_name,
            ch.customer_challan_no,
            ch.customer_challan_date,
            mi.item_code,
            mi.process,
            mi.inward_qty,
            mi.available_qty,
            mi.box_tray,
            ch.status
        FROM material_inward mi
        JOIN customer_challan ch ON ch.id = mi.challan_id
        JOIN customer_master c ON c.id = ch.customer_id
        WHERE ch.status='OPEN'
        ORDER BY ch.customer_challan_date DESC, ch.customer_challan_no DESC
    """).fetchall()

    elta_challans = db.execute("""
        SELECT DISTINCT elta_challan_no
        FROM material_dispatch
        ORDER BY elta_challan_no DESC
    """).fetchall()

    return render_template(
        "material_manage.html",
        inward_rows=inward_rows,
        elta_challans=elta_challans,
        pin1=pin1,
        pin2=pin2,
        loaded=True
    )


@materials_bp.route("/manage/dispatch-load", methods=["POST"])
def manage_dispatch_load():
    db = get_db()
    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    elta = (request.form.get("elta_challan_no") or "").strip()
    if not elta:
        abort(400, "ELTA challan required")

    rows = load_dispatch_rows_by_elta(db, elta)

    return render_template("material_manage_dispatch_table.html", rows=rows, pin1=pin1, pin2=pin2)


@materials_bp.route("/manage/inward/edit/<int:inward_id>", methods=["POST"])
def manage_inward_edit(inward_id):
    db = get_db()
    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    item_code = (request.form.get("item_code") or "").strip()
    process = (request.form.get("process") or "").strip()
    box_tray = (request.form.get("box_tray") or "").strip()

    inward_qty = int(request.form.get("inward_qty") or 0)
    available_qty = int(request.form.get("available_qty") or 0)

    if not item_code:
        abort(400, "Item code required")
    if inward_qty < 0 or available_qty < 0:
        abort(400, "Invalid qty")
    if available_qty > inward_qty:
        abort(400, "Available cannot exceed inward")

    db.execute("""
        UPDATE material_inward
        SET item_code=?, process=?, inward_qty=?, available_qty=?, box_tray=?
        WHERE id=?
    """, (item_code, process, inward_qty, available_qty, box_tray, inward_id))

    db.commit()
    return redirect("/materials/manage")


@materials_bp.route("/manage/inward/delete/<int:inward_id>", methods=["POST"])
def manage_inward_delete(inward_id):
    db = get_db()
    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    used = db.execute("""
        SELECT COUNT(*) AS cnt
        FROM material_dispatch
        WHERE inward_id=?
    """, (inward_id,)).fetchone()["cnt"]

    if used > 0:
        abort(400, "Cannot delete: dispatch exists for this inward line")

    db.execute("DELETE FROM material_inward WHERE id=?", (inward_id,))
    db.commit()
    return redirect("/materials/manage")


@materials_bp.route("/manage/dispatch/edit/<int:dispatch_id>", methods=["POST"])
def manage_dispatch_edit(dispatch_id):
    db = get_db()

    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    elta_challan_no = (request.form.get("elta_challan_no") or "").strip()
    dispatch_date = request.form.get("dispatch_date") or ""

    ok_qty = int(request.form.get("ok_qty") or 0)
    rej_qty = int(request.form.get("rej_qty") or 0)
    cd_qty = int(request.form.get("cd_qty") or 0)
    nd_qty = int(request.form.get("nd_qty") or 0)
    nd_pw_qty = int(request.form.get("nd_pw_qty") or 0)

    if not elta_challan_no:
        abort(400, "ELTA challan required")

    if any(x < 0 for x in [ok_qty, rej_qty, cd_qty, nd_qty, nd_pw_qty]):
        abort(400, "Qty cannot be negative")

    new_total = ok_qty + rej_qty + cd_qty + nd_qty + nd_pw_qty
    if new_total <= 0:
        abort(400, "Total dispatch must be > 0")

    old = db.execute("""
        SELECT id, challan_id, inward_id, source_type, source_id, total_qty
        FROM material_dispatch
        WHERE id=?
    """, (dispatch_id,)).fetchone()
    if not old:
        abort(404)

    source_type = (old["source_type"] or "INWARD").upper()
    old_total = int(old["total_qty"] or 0)
    delta = new_total - old_total

    if source_type == "INHOUSE":
        stock = db.execute("""
            SELECT id, available_qty
            FROM material_inhouse_stock
            WHERE id=?
        """, (old["source_id"],)).fetchone()
        if not stock:
            abort(400, "Linked in-house stock row missing")
        if delta > 0 and int(stock["available_qty"] or 0) < delta:
            abort(400, f"Not enough in-house stock to increase dispatch. Need {delta}, available {stock['available_qty']}")
    else:
        inward = db.execute("""
            SELECT id, available_qty
            FROM material_inward
            WHERE id=?
        """, (old["inward_id"],)).fetchone()
        if not inward:
            abort(400, "Linked inward row missing")
        if delta > 0 and int(inward["available_qty"] or 0) < delta:
            abort(400, f"Not enough stock to increase dispatch. Need {delta}, available {inward['available_qty']}")

    db.execute("""
        UPDATE material_dispatch
        SET elta_challan_no=?, dispatch_date=?,
            ok_qty=?, rej_qty=?, cd_qty=?, nd_qty=?, nd_pw_qty=?,
            total_qty=?
        WHERE id=?
    """, (
        elta_challan_no, dispatch_date,
        ok_qty, rej_qty, cd_qty, nd_qty, nd_pw_qty,
        new_total,
        dispatch_id
    ))

    if source_type == "INHOUSE":
        db.execute("""
            UPDATE material_inhouse_stock
            SET available_qty = available_qty - ?
            WHERE id=?
        """, (delta, old["source_id"]))
    else:
        db.execute("""
            UPDATE material_inward
            SET available_qty = available_qty - ?
            WHERE id=?
        """, (delta, old["inward_id"]))
        update_challan_status(db, old["challan_id"])

    db.commit()

    rows = load_dispatch_rows_by_elta(db, elta_challan_no)
    return render_template("material_manage_dispatch_table.html", rows=rows, pin1=pin1, pin2=pin2)


# ================= DISPATCH DELETE (ROLLBACK STOCK) =================

@materials_bp.route("/manage/dispatch/delete/<int:dispatch_id>", methods=["POST"])
def manage_dispatch_delete(dispatch_id):
    db = get_db()

    pin1 = request.form.get("pin1")
    pin2 = request.form.get("pin2")
    if not check_two_pins(pin1, pin2):
        abort(403, "Invalid PINs")

    d = db.execute("""
        SELECT id, challan_id, inward_id, source_type, source_id, total_qty, elta_challan_no
        FROM material_dispatch
        WHERE id=?
    """, (dispatch_id,)).fetchone()
    if not d:
        abort(404)

    rollback_qty = int(d["total_qty"] or 0)
    source_type = (d["source_type"] or "INWARD").upper()

    if source_type == "INHOUSE":
        db.execute("""
            UPDATE material_inhouse_stock
            SET available_qty = available_qty + ?
            WHERE id=?
        """, (rollback_qty, d["source_id"]))
    else:
        db.execute("""
            UPDATE material_inward
            SET available_qty = available_qty + ?
            WHERE id=?
        """, (rollback_qty, d["inward_id"]))

    db.execute("DELETE FROM material_dispatch WHERE id=?", (dispatch_id,))

    if source_type != "INHOUSE":
        update_challan_status(db, d["challan_id"])

    db.commit()

    rows = load_dispatch_rows_by_elta(db, d["elta_challan_no"])
    return render_template("material_manage_dispatch_table.html", rows=rows, pin1=pin1, pin2=pin2)

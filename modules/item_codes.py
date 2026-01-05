from flask import Blueprint, render_template, request, redirect, abort, current_app, send_from_directory
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import uuid

from db import get_db

item_codes_bp = Blueprint("item_codes", __name__, url_prefix="/item-codes")


# ================= SECURITY =================

def check_pin(pin):
    return (pin or "").strip() == str(current_app.config.get("ADMIN_PIN", "")).strip()


# ================= UPLOAD SETTINGS =================

ALLOWED_EXT = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".png", ".jpg", ".jpeg"}

def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in ALLOWED_EXT


# ================= LIST =================

@item_codes_bp.route("/")
def item_codes():
    db = get_db()
    rows = db.execute("""
        SELECT i.*,
               (SELECT COUNT(*) FROM item_code_ppap_docs d WHERE d.item_code_id = i.id) AS ppap_count
        FROM item_code_master i
        ORDER BY i.item_code
    """).fetchall()
    return render_template("item_codes.html", item_codes=rows)


# ================= ADD =================

@item_codes_bp.route("/add", methods=["GET", "POST"])
def add_item_code():
    db = get_db()

    if request.method == "POST":
        code = (request.form.get("item_code") or "").strip()
        desc = request.form.get("description", "")
        remarks = request.form.get("remarks", "")

        if not code:
            abort(400, "Item code required")

        db.execute("""
            INSERT INTO item_code_master (item_code, description, remarks)
            VALUES (?, ?, ?)
        """, (code, desc, remarks))

        db.commit()
        return redirect("/item-codes")

    return render_template("item_code_add.html")


# ================= EDIT (PIN PROTECTED) =================

@item_codes_bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_item_code(id):
    db = get_db()

    row = db.execute("""
        SELECT * FROM item_code_master
        WHERE id=?
    """, (id,)).fetchone()

    if not row:
        abort(404)

    if request.method == "POST":
        if not check_pin(request.form.get("pin")):
            abort(403, "Invalid PIN")

        db.execute("""
            UPDATE item_code_master
            SET item_code=?, description=?, remarks=?
            WHERE id=?
        """, (
            request.form.get("item_code", "").strip(),
            request.form.get("description", ""),
            request.form.get("remarks", ""),
            id
        ))

        db.commit()
        return redirect("/item-codes")

    return render_template("item_code_edit.html", item=row)


# ================= PPAP PAGE (VIEW + UPLOAD) =================

@item_codes_bp.route("/ppap/<int:item_code_id>")
def ppap_page(item_code_id):
    db = get_db()

    item = db.execute("""
        SELECT * FROM item_code_master WHERE id=?
    """, (item_code_id,)).fetchone()
    if not item:
        abort(404)

    ppap_docs = db.execute("""
        SELECT id, doc_name, doc_type, notes, uploaded_at, version_no, is_current
        FROM item_code_ppap_docs
        WHERE item_code_id=? AND doc_category='PPAP'
        ORDER BY version_no DESC, uploaded_at DESC
    """, (item_code_id,)).fetchall()

    drawing_docs = db.execute("""
        SELECT id, doc_name, doc_type, notes, uploaded_at, version_no, is_current
        FROM item_code_ppap_docs
        WHERE item_code_id=? AND doc_category='DRAWING'
        ORDER BY version_no DESC, uploaded_at DESC
    """, (item_code_id,)).fetchall()

    return render_template("item_code_ppap.html", item=item, ppap_docs=ppap_docs, drawing_docs=drawing_docs)


# ================= PPAP UPLOAD =================

@item_codes_bp.route("/ppap/<int:item_code_id>/upload", methods=["POST"])
def upload_ppap(item_code_id):
    db = get_db()

    item = db.execute("SELECT id FROM item_code_master WHERE id=?", (item_code_id,)).fetchone()
    if not item:
        abort(404)

    file = request.files.get("ppap_file")
    doc_type = (request.form.get("doc_type") or "PPAP").strip()
    notes = (request.form.get("notes") or "").strip()
    
    # AUTO category based on doc_type
    doc_category = "DRAWING" if doc_type.lower() == "drawing" else "PPAP"
    if doc_category not in ("PPAP", "DRAWING"):
        abort(400, "Invalid doc category")

    if not file or not file.filename:
        abort(400, "No file selected")

    filename = secure_filename(file.filename)
    if not allowed_file(filename):
        abort(400, "Unsupported file type")

    upload_dir = current_app.config.get("PPAP_UPLOAD_DIR")
    if not upload_dir:
        abort(500, "PPAP_UPLOAD_DIR not configured")
    os.makedirs(upload_dir, exist_ok=True)

    # --- versioning: next version per item + category ---
    row = db.execute("""
        SELECT COALESCE(MAX(version_no), 0) AS maxv
        FROM item_code_ppap_docs
        WHERE item_code_id = ? AND doc_category = ?
    """, (item_code_id, doc_category)).fetchone()

    next_ver = int(row["maxv"] if row and row["maxv"] is not None else 0) + 1

    # mark previous current -> not current
    db.execute("""
        UPDATE item_code_ppap_docs
        SET is_current = 0
        WHERE item_code_id = ? AND doc_category = ? AND is_current = 1
    """, (item_code_id, doc_category))

    ext = os.path.splitext(filename)[1].lower()
    stored_name = f"{item_code_id}_{doc_category}_V{next_ver}_{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(upload_dir, stored_name)
    file.save(save_path)

    db.execute("""
        INSERT INTO item_code_ppap_docs
        (item_code_id, doc_name, stored_name, doc_type, notes, uploaded_at, version_no, is_current, doc_category)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        item_code_id,
        filename,
        stored_name,
        doc_type,
        notes,
        datetime.now().isoformat(timespec="seconds"),
        next_ver,
        doc_category
    ))

    db.commit()
    return redirect(f"/item-codes/ppap/{item_code_id}")


# ================= PPAP DOWNLOAD =================

@item_codes_bp.route("/ppap-doc/<int:doc_id>/download")
def download_ppap(doc_id):
    db = get_db()
    row = db.execute("""
        SELECT doc_name, stored_name
        FROM item_code_ppap_docs
        WHERE id=?
    """, (doc_id,)).fetchone()

    if not row:
        abort(404)

    upload_dir = current_app.config.get("PPAP_UPLOAD_DIR")
    if not upload_dir:
        abort(500, "PPAP_UPLOAD_DIR not configured")

    # sqlite Row supports dict-style keys if row_factory is set
    return send_from_directory(
        upload_dir,
        row["stored_name"],
        as_attachment=True,
        download_name=row["doc_name"]
    )


# ================= PPAP DELETE =================

@item_codes_bp.route("/ppap-doc/<int:doc_id>/delete", methods=["POST"])
def delete_ppap(doc_id):
    db = get_db()
    row = db.execute("""
        SELECT item_code_id, stored_name
        FROM item_code_ppap_docs
        WHERE id=?
    """, (doc_id,)).fetchone()

    if not row:
        abort(404)

    upload_dir = current_app.config.get("PPAP_UPLOAD_DIR")
    if not upload_dir:
        abort(500, "PPAP_UPLOAD_DIR not configured")

    try:
        os.remove(os.path.join(upload_dir, row["stored_name"]))
    except FileNotFoundError:
        pass

    db.execute("DELETE FROM item_code_ppap_docs WHERE id=?", (doc_id,))
    db.commit()

    return redirect(f"/item-codes/ppap/{row['item_code_id']}")


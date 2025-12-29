from flask import Blueprint, render_template, request, redirect, abort, current_app
from db import get_db
from db import fetch_active_machines

item_codes_bp = Blueprint("item_codes", __name__, url_prefix="/item-codes")

def check_pin(pin):
    return pin == current_app.config["ADMIN_PIN"]

# ================= LIST =================

@item_codes_bp.route("/")
def item_codes():
    db = get_db()
    rows = db.execute("""
        SELECT * FROM item_code_master
        ORDER BY item_code
    """).fetchall()
    return render_template("item_codes.html", item_codes=rows)

# ================= ADD =================

@item_codes_bp.route("/add", methods=["GET", "POST"])
def add_item_code():
    db = get_db()

    if request.method == "POST":
        code = request.form["item_code"].strip()
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
            request.form["item_code"],
            request.form.get("description"),
            request.form.get("remarks"),
            id
        ))

        db.commit()
        return redirect("/item-codes")

    return render_template("item_code_edit.html", item=row)


from flask import Blueprint, render_template, request, redirect, abort
from db import get_db

customers_bp = Blueprint("customers", __name__, url_prefix="/customers")

ADMIN_PIN = "1234"   # 🔐 change later or move to config

# ================= LIST =================

@customers_bp.route("/")
def customers():
    db = get_db()
    rows = db.execute("""
        SELECT * FROM customer_master
        ORDER BY customer_name
    """).fetchall()
    return render_template("customers.html", customers=rows)

# ================= ADD =================

@customers_bp.route("/add", methods=["GET", "POST"])
def add_customer():
    db = get_db()

    if request.method == "POST":
        name = request.form["customer_name"].strip()
        short = request.form.get("short_code", "").strip()
        remarks = request.form.get("remarks", "")

        if not name:
            abort(400, "Customer name required")

        db.execute("""
            INSERT INTO customer_master
            (customer_name, short_code, remarks)
            VALUES (?, ?, ?)
        """, (name, short, remarks))

        db.commit()
        return redirect("/customers")

    return render_template("customer_add.html")

# ================= EDIT =================

@customers_bp.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_customer(id):
    db = get_db()

    row = db.execute(
        "SELECT * FROM customer_master WHERE id=?",
        (id,)
    ).fetchone()

    if not row:
        abort(404)

    if request.method == "POST":
        if request.form.get("pin") != ADMIN_PIN:
            abort(403, "Invalid PIN")

        db.execute("""
            UPDATE customer_master
            SET customer_name=?, short_code=?, remarks=?
            WHERE id=?
        """, (
            request.form["customer_name"],
            request.form.get("short_code"),
            request.form.get("remarks"),
            id
        ))

        db.commit()
        return redirect("/customers")

    return render_template("customer_edit.html", customer=row)

# ================= DELETE =================

@customers_bp.route("/delete/<int:id>", methods=["POST"])
def delete_customer(id):
    db = get_db()

    if request.form.get("pin") != ADMIN_PIN:
        abort(403, "Invalid PIN")

    # 🔒 Prevent delete if used in challans
    used = db.execute("""
        SELECT 1 FROM customer_challan
        WHERE customer_id=?
        LIMIT 1
    """, (id,)).fetchone()

    if used:
        abort(400, "Customer has transactions")

    db.execute("DELETE FROM customer_master WHERE id=?", (id,))
    db.commit()
    return redirect("/customers")


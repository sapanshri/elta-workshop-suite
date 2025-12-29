from flask import Blueprint, render_template, request, redirect
from db import get_db
from datetime import date
from db import fetch_active_machines

collets_bp = Blueprint("collets", __name__, url_prefix="/collets")

# ================= INVENTORY =================

@collets_bp.route("/")
def collets():
    db = get_db()
    rows = db.execute("SELECT * FROM collets").fetchall()
    return render_template("collets.html", collets=rows)

@collets_bp.route("/add", methods=["POST"])
def add_collet():
    db = get_db()

    data = (
        request.form["collet_type"],
        request.form["interface"],
        request.form["size_range"],
        request.form["location"],
        int(request.form["total_qty"]),
        int(request.form["reorder_level"]),
        request.form.get("remarks", "")
    )

    db.execute("""
        INSERT INTO collets
        (collet_type, interface, size_range, location,
         total_qty, reorder_level, remarks, available_qty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(collet_type, interface, size_range, location)
        DO UPDATE SET
            total_qty = total_qty + excluded.total_qty,
            available_qty = available_qty + excluded.total_qty
    """, (*data, data[4]))

    db.commit()
    return redirect("/collets")

# ================= ISSUE =================

@collets_bp.route("/issue", methods=["GET", "POST"])
def issue_collet():
    db = get_db()

    if request.method == "POST":
        db.execute("""
            INSERT INTO collet_txn
            (collet_id, action, qty, operator, machine, shift, txn_date)
            VALUES (?, 'ISSUE', ?, ?, ?, ?, ?)
        """, (
            request.form["collet_id"],
            request.form["qty"],
            request.form["operator"],
            request.form["machine"],
            request.form["shift"],
            request.form["issue_date"]
        ))

        db.execute("""
            UPDATE collets SET available_qty = available_qty - ?
            WHERE id = ?
        """, (request.form["qty"], request.form["collet_id"]))

        db.commit()
        return redirect("/collets")

    rows = db.execute("SELECT * FROM collets WHERE available_qty > 0").fetchall()
    return render_template("collet_issue.html", collets=rows, today=date.today())

# ================= RETURN =================

@collets_bp.route("/return", methods=["GET", "POST"])
def return_collet():
    db = get_db()

    if request.method == "POST":
        db.execute("""
            INSERT INTO collet_txn
            (collet_id, action, qty, operator, shift, txn_date)
            VALUES (?, 'RETURN', ?, ?, ?, ?)
        """, (
            request.form["collet_id"],
            request.form["qty"],
            request.form["operator"],
            request.form["shift"],
            request.form["return_date"]
        ))

        db.execute("""
            UPDATE collets SET available_qty = available_qty + ?
            WHERE id = ?
        """, (request.form["qty"], request.form["collet_id"]))

        db.commit()
        return redirect("/collets")

    rows = db.execute("SELECT * FROM collets").fetchall()
    return render_template("collet_return.html", collets=rows, today=date.today())

# ================= HISTORY =================

@collets_bp.route("/history")
def collet_history():
    db = get_db()
    rows = db.execute("""
        SELECT c.collet_type, c.interface, c.size_range,
               t.action, t.qty, t.operator, t.machine, t.shift, t.txn_date
        FROM collet_txn t
        JOIN collets c ON c.id = t.collet_id
        ORDER BY t.txn_date DESC
    """).fetchall()

    return render_template("collet_history.html", rows=rows)


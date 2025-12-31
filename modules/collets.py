from flask import Blueprint, render_template, request, redirect, abort
from datetime import date
from db import get_db, fetch_active_machines

collets_bp = Blueprint("collets", __name__, url_prefix="/collets")


# ================= INVENTORY =================

@collets_bp.route("/")
def collets():
    db = get_db()
    rows = db.execute("""
        SELECT
            id,
            collet_type,
            interface,
            size_range,
            location,
            total_qty,
            available_qty,
            reorder_level,
            remarks
        FROM collets
        ORDER BY collet_type, interface, size_range
    """).fetchall()
    return render_template("collets.html", collets=rows)


@collets_bp.route("/add", methods=["POST"])
def add_collet():
    db = get_db()

    collet_type = request.form["collet_type"]
    interface = request.form.get("interface", "")
    size_range = request.form.get("size_range", "")
    location = request.form.get("location", "")
    total_qty = int(request.form.get("total_qty") or 0)
    reorder_level = int(request.form.get("reorder_level") or 0)
    remarks = request.form.get("remarks", "")

    if total_qty <= 0:
        abort(400, "Total Qty must be > 0")

    available_qty = total_qty

    db.execute("""
        INSERT INTO collets
        (collet_type, interface, size_range, location,
         total_qty, available_qty, reorder_level, remarks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(collet_type, interface, size_range, location)
        DO UPDATE SET
            total_qty = total_qty + excluded.total_qty,
            available_qty = available_qty + excluded.total_qty,
            reorder_level = excluded.reorder_level,
            remarks = excluded.remarks
    """, (collet_type, interface, size_range, location,
          total_qty, available_qty, reorder_level, remarks))

    db.commit()
    return redirect("/collets")


# ================= ISSUE =================

@collets_bp.route("/issue", methods=["GET", "POST"])
def issue_collet():
    db = get_db()

    if request.method == "POST":
        collet_id = request.form["collet_id"]
        qty = int(request.form.get("qty") or 0)

        if qty <= 0:
            abort(400, "Quantity must be > 0")

        # ---- HARD CHECK: qty must be <= available_qty ----
        row = db.execute(
            "SELECT available_qty FROM collets WHERE id = ?",
            (collet_id,)
        ).fetchone()

        available = int(row[0]) if row and row[0] is not None else 0

        if qty > available:
            abort(400, f"Insufficient stock. Available: {available}")

        # log txn
        db.execute("""
            INSERT INTO collet_txn
            (collet_id, action, qty, operator, machine, shift, txn_date)
            VALUES (?, 'ISSUE', ?, ?, ?, ?, ?)
        """, (
            collet_id,
            qty,
            request.form.get("operator", ""),
            request.form.get("machine", ""),
            request.form.get("shift", ""),
            request.form.get("issue_date", str(date.today()))
        ))

        # safe stock update (extra guard in WHERE)
        cur = db.execute("""
            UPDATE collets
            SET available_qty = available_qty - ?
            WHERE id = ? AND available_qty >= ?
        """, (qty, collet_id, qty))

        if cur.rowcount == 0:
            abort(400, "Stock changed. Try again.")

        db.commit()
        return redirect("/collets")

    rows = db.execute("""
        SELECT
            id,
            collet_type,
            interface,
            size_range,
            location,
            total_qty,
            available_qty,
            reorder_level,
            remarks
        FROM collets
        WHERE available_qty > 0
        ORDER BY collet_type, interface, size_range
    """).fetchall()

    return render_template("collet_issue.html", collets=rows, today=date.today())


# ================= RETURN =================

@collets_bp.route("/return", methods=["GET", "POST"])
def return_collet():
    db = get_db()

    if request.method == "POST":
        collet_id = request.form["collet_id"]
        qty = int(request.form.get("qty") or 0)

        if qty <= 0:
            abort(400, "Quantity must be > 0")

        db.execute("""
            INSERT INTO collet_txn
            (collet_id, action, qty, operator, shift, txn_date)
            VALUES (?, 'RETURN', ?, ?, ?, ?)
        """, (
            collet_id,
            qty,
            request.form.get("operator", ""),
            request.form.get("shift", ""),
            request.form.get("return_date", str(date.today()))
        ))

        db.execute("""
            UPDATE collets
            SET available_qty = available_qty + ?
            WHERE id = ?
        """, (qty, collet_id))

        db.commit()
        return redirect("/collets")

    rows = db.execute("""
        SELECT
            id,
            collet_type,
            interface,
            size_range,
            location,
            total_qty,
            available_qty,
            reorder_level,
            remarks
        FROM collets
        ORDER BY collet_type, interface, size_range
    """).fetchall()

    return render_template("collet_return.html", collets=rows, today=date.today())


# ================= HISTORY =================

@collets_bp.route("/history")
def collet_history():
    db = get_db()
    rows = db.execute("""
        SELECT
            c.collet_type,
            c.interface,
            c.size_range,
            t.action,
            t.qty,
            t.operator,
            t.machine,
            t.shift,
            t.txn_date
        FROM collet_txn t
        JOIN collets c ON c.id = t.collet_id
        ORDER BY t.txn_date DESC
    """).fetchall()

    return render_template("collet_history.html", rows=rows)


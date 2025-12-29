from flask import Blueprint, render_template, request, redirect
from db import get_db
from datetime import date
from db import fetch_active_machines

holders_bp = Blueprint("holders", __name__, url_prefix="/holders")


@holders_bp.route("/")
def holders():
    con = get_db()
    rows = con.execute("""
        SELECT *,
               (total_qty - issued_qty) AS available
        FROM holders
        ORDER BY holder_type, interface
    """).fetchall()
    con.close()

    return render_template("holders.html", holders=rows)


@holders_bp.route("/add", methods=["POST"])
def add_holder():
    f = request.form
    con = get_db()

    con.execute("""
        INSERT INTO holders
        (holder_type, interface, size, projection, location, remarks,
         total_qty, reorder_level)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(holder_type, interface, size, projection)
        DO UPDATE SET
            total_qty = total_qty + excluded.total_qty,
            reorder_level = excluded.reorder_level,
            location = excluded.location,
            remarks = excluded.remarks
    """, (
        f["holder_type"],
        f["interface"],
        f["size"],
        f["projection"],
        f["location"],
        f.get("remarks",""),
        int(f["total_qty"]),
        int(f["reorder_level"])
    ))

    con.commit()
    con.close()
    return redirect("/holders")


@holders_bp.route("/issue", methods=["GET", "POST"])
def holder_issue():
    con = get_db()

    if request.method == "POST":
        f = request.form
        qty = int(f["qty"])
        holder_id = int(f["holder_id"])

        con.execute("""
            UPDATE holders
            SET issued_qty = issued_qty + ?
            WHERE id=?
        """, (qty, holder_id))

        con.execute("""
            INSERT INTO holder_txn
            (holder_id, action, qty, operator, machine, shift, ts)
            VALUES (?, 'ISSUE', ?, ?, ?, ?, ?)
        """, (
            holder_id, qty,
            f["operator"],
            f["machine"],
            f["shift"],
            f["issue_date"]
        ))

        con.commit()
        con.close()
        return redirect("/holders")

    holders = con.execute("""
        SELECT id, holder_type, interface, size, projection
        FROM holders
        WHERE total_qty > issued_qty
    """).fetchall()
    con.close()

    return render_template(
        "holder_issue.html",
        holders=holders,
        today=date.today().isoformat()
    )


@holders_bp.route("/return", methods=["GET", "POST"])
def holder_return():
    con = get_db()

    if request.method == "POST":
        f = request.form
        qty = int(f["qty"])
        holder_id = int(f["holder_id"])

        con.execute("""
            UPDATE holders
            SET issued_qty = issued_qty - ?
            WHERE id=?
        """, (qty, holder_id))

        con.execute("""
            INSERT INTO holder_txn
            (holder_id, action, qty, operator, shift, remarks, ts)
            VALUES (?, 'RETURN', ?, ?, ?, ?, ?)
        """, (
            holder_id, qty,
            f["operator"],
            f["shift"],
            f.get("remarks",""),
            f["return_date"]
        ))

        con.commit()
        con.close()
        return redirect("/holders")

    holders = con.execute("""
        SELECT id, holder_type, interface, size, projection
        FROM holders
        WHERE issued_qty > 0
    """).fetchall()
    con.close()

    return render_template(
        "holder_return.html",
        holders=holders,
        today=date.today().isoformat()
    )


@holders_bp.route("/history")
def holder_history():
    con = get_db()
    rows = con.execute("""
        SELECT h.holder_type, h.interface, h.size, h.projection,
               t.action, t.qty, t.operator, t.machine, t.shift, t.ts
        FROM holder_txn t
        JOIN holders h ON h.id = t.holder_id
        ORDER BY t.ts DESC
    """).fetchall()
    con.close()

    return render_template("holder_history.html", rows=rows)


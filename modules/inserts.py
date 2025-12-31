from flask import Blueprint, render_template, request, redirect
from db import get_db
from datetime import date
from db import fetch_active_machines

inserts_bp = Blueprint("inserts", __name__, url_prefix="/inserts")

# ================= INVENTORY =================

@inserts_bp.route("/")
def inserts():
    db = get_db()
    rows = db.execute("""
        SELECT
            id,
            insert_type,
            size,
            grade,
            edges,
            total_qty,
            available_qty,
            reorder_level,
            remarks
        FROM inserts
        ORDER BY insert_type, size, grade
    """).fetchall()
    return render_template("inserts.html", inserts=rows)


@inserts_bp.route("/add", methods=["POST"])
def add_insert():
    db = get_db()

    insert_type = request.form["insert_type"]
    size = request.form["size"]
    grade = request.form["grade"]
    edges = int(request.form["edges"] or 0)
    total_qty = int(request.form["total_qty"] or 0)
    reorder_level = int(request.form.get("reorder_level", 0) or 0)
    remarks = request.form.get("remarks", "")

    # available_qty should start same as total_qty for a new add
    available_qty = total_qty

    db.execute("""
        INSERT INTO inserts
        (insert_type, size, grade, edges,
         total_qty, available_qty, reorder_level, remarks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(insert_type, size, grade)
        DO UPDATE SET
            total_qty = total_qty + excluded.total_qty,
            available_qty = available_qty + excluded.total_qty,
            reorder_level = excluded.reorder_level,
            edges = excluded.edges,
            remarks = excluded.remarks
    """, (insert_type, size, grade, edges, total_qty, available_qty, reorder_level, remarks))

    db.commit()
    return redirect("/inserts")


# ================= ISSUE =================

@inserts_bp.route("/issue", methods=["GET", "POST"])
def issue_insert():
    db = get_db()

    if request.method == "POST":
        db.execute("""
            INSERT INTO insert_txn
            (insert_id, action, qty, operator, machine, job, shift, txn_date)
            VALUES (?, 'ISSUE', ?, ?, ?, ?, ?, ?)
        """, (
            request.form["insert_id"],
            request.form["qty"],
            request.form["operator"],
            request.form["machine"],
            request.form["job"],
            request.form["shift"],
            request.form["issue_date"]
        ))

        db.execute("""
            UPDATE inserts
            SET available_qty = available_qty - ?
            WHERE id = ?
        """, (request.form["qty"], request.form["insert_id"]))

        db.commit()
        return redirect("/inserts")

    rows = db.execute("SELECT * FROM inserts WHERE available_qty > 0").fetchall()
    return render_template("insert_issue.html", inserts=rows, today=date.today())

# ================= EDGE USED =================

@inserts_bp.route("/edge", methods=["POST"])
def edge_used():
    db = get_db()

    db.execute("""
        INSERT INTO insert_txn
        (insert_id, action, edges_used, operator, machine, job, shift, txn_date)
        VALUES (?, 'EDGE_USED', ?, ?, ?, ?, ?, ?)
    """, (
        request.form["insert_id"],
        request.form["edges_used"],
        request.form["operator"],
        request.form["machine"],
        request.form["job"],
        request.form["shift"],
        request.form["date"]
    ))

    db.commit()
    return redirect("/inserts")

# ================= SCRAP =================

@inserts_bp.route("/scrap", methods=["GET", "POST"])
def scrap_insert():
    db = get_db()

    if request.method == "POST":
        db.execute("""
            INSERT INTO insert_txn
            (insert_id, action, qty, operator, machine, job, shift, txn_date)
            VALUES (?, 'SCRAP', ?, ?, ?, ?, ?, ?)
        """, (
            request.form["insert_id"],
            request.form["qty"],
            request.form["operator"],
            request.form["machine"],
            request.form["job"],
            request.form["shift"],
            request.form["scrap_date"]
        ))

        db.execute("""
            UPDATE inserts
            SET available_qty = available_qty - ?
            WHERE id = ?
        """, (request.form["qty"], request.form["insert_id"]))

        db.commit()
        return redirect("/inserts")

    rows = db.execute("SELECT * FROM inserts").fetchall()
    return render_template("insert_scrap.html", inserts=rows, today=date.today())

# ================= HISTORY =================

@inserts_bp.route("/history")
def insert_history():
    db = get_db()
    rows = db.execute("""
        SELECT i.insert_type, i.size, i.grade,
               t.action, t.qty, t.edges_used,
               t.operator, t.machine, t.job, t.shift, t.txn_date
        FROM insert_txn t
        JOIN inserts i ON i.id = t.insert_id
        ORDER BY t.txn_date DESC
    """).fetchall()

    return render_template("insert_history.html", rows=rows)


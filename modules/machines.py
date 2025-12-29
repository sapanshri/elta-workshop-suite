from flask import Blueprint, render_template, request, redirect, abort
from datetime import date
from db import get_db
from flask import current_app
from db import fetch_active_machines

machines_bp = Blueprint("machines", __name__, url_prefix="/machines")


def check_pin(pin: str) -> bool:
    return pin == current_app.config.get("ADMIN_PIN", "")


def _norm(s: str) -> str:
    return (s or "").strip()


@machines_bp.route("/", methods=["GET"])
def machines_list():
    db = get_db()

    machine_type = _norm(request.args.get("machine_type", ""))
    status = _norm(request.args.get("status", ""))

    query = """
        SELECT *
        FROM machine_master
        WHERE 1=1
    """
    params = []

    if machine_type:
        query += " AND machine_type = ?"
        params.append(machine_type)

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY machine_code"

    rows = db.execute(query, params).fetchall()

    types = db.execute("""
        SELECT DISTINCT machine_type
        FROM machine_master
        ORDER BY machine_type
    """).fetchall()

    return render_template(
        "machines/machines_list.html",
        rows=rows,
        types=types
    )


@machines_bp.route("/add", methods=["GET", "POST"])
def machine_add():
    db = get_db()

    if request.method == "POST":
        f = request.form

        machine_code = _norm(f.get("machine_code"))
        machine_name = _norm(f.get("machine_name"))
        machine_type = _norm(f.get("machine_type"))
        controller = _norm(f.get("controller"))
        location = _norm(f.get("location"))
        status = _norm(f.get("status") or "ACTIVE")
        install_date = _norm(f.get("install_date"))
        notes = _norm(f.get("notes"))

        if not machine_code or not machine_name or not machine_type:
            abort(400, "Machine Code, Name, Type are required")

        try:
            db.execute("""
                INSERT INTO machine_master
                (machine_code, machine_name, machine_type, controller, location, status, install_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (machine_code, machine_name, machine_type, controller, location, status, install_date, notes))
            db.commit()
        except Exception as e:
            # common: UNIQUE constraint on machine_code
            abort(400, f"Could not add machine: {e}")

        return redirect("/machines/")

    return render_template("machines/machine_add.html", today=date.today())


@machines_bp.route("/edit/<int:machine_id>", methods=["GET", "POST"])
def machine_edit(machine_id: int):
    db = get_db()

    row = db.execute("""
        SELECT * FROM machine_master WHERE id=?
    """, (machine_id,)).fetchone()

    if not row:
        abort(404)

    if request.method == "POST":
        f = request.form

        # PIN protection
        pin = _norm(f.get("pin"))
        if not check_pin(pin):
            abort(403, "Invalid PIN")

        machine_code = _norm(f.get("machine_code"))
        machine_name = _norm(f.get("machine_name"))
        machine_type = _norm(f.get("machine_type"))
        controller = _norm(f.get("controller"))
        location = _norm(f.get("location"))
        status = _norm(f.get("status") or "ACTIVE")
        install_date = _norm(f.get("install_date"))
        notes = _norm(f.get("notes"))

        if not machine_code or not machine_name or not machine_type:
            abort(400, "Machine Code, Name, Type are required")

        try:
            db.execute("""
                UPDATE machine_master
                SET machine_code=?,
                    machine_name=?,
                    machine_type=?,
                    controller=?,
                    location=?,
                    status=?,
                    install_date=?,
                    notes=?
                WHERE id=?
            """, (
                machine_code, machine_name, machine_type,
                controller, location, status, install_date, notes,
                machine_id
            ))
            db.commit()
        except Exception as e:
            abort(400, f"Could not update machine: {e}")

        return redirect("/machines/")

    return render_template("machines/machine_edit.html", row=row)


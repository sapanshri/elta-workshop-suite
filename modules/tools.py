from flask import Blueprint, render_template, request, redirect
from db import get_db
from datetime import date
from constants import TOOL_TYPES
from db import fetch_active_machines

tools_bp = Blueprint("tools", __name__, url_prefix="/tools")

@tools_bp.route("/")
def tools():
    con = get_db()
    rows = con.execute("""
       SELECT
           id,                 -- 0
           tool_type,          -- 1
           tool_subtype,       -- 2
           cutting_diameter,   -- 3
           cutting_length,     -- 4
           overall_length,     -- 5
           shank_type,         -- 6
           shank_diameter,     -- 7
           material,           -- 8
           location,           -- 9
           remarks,            -- 10
           total_qty,          -- 11
           reorder_level,      -- 12
           (total_qty - issued_qty - broken_qty) AS available_qty  -- 13
       FROM cutting_tools
       ORDER BY tool_type, material, cutting_diameter
   """).fetchall()

    con.close()

    return render_template(
        "tools.html",
        tools=rows,
        tool_types=TOOL_TYPES
    )
@tools_bp.route("/search")
def search():
    q = request.args
    con = get_db()

    rows = con.execute("""
        SELECT *,
        (total_qty - issued_qty - broken_qty) AS available_qty
        FROM cutting_tools
        WHERE tool_type = ?
          AND cutting_diameter = ?
          AND material = ?
          AND cutting_length = ?
    """, (
        q["tool_type"],
        q["cutting_diameter"],
        q["material"],
        q["cutting_length"]
    )).fetchall()

    con.close()
    return render_template("search.html", results=rows)


@tools_bp.post("/add")
def add_tool():
    f = request.form
    con = get_db()

    con.execute("""
    INSERT INTO cutting_tools (
        tool_type, tool_subtype,
        cutting_diameter, cutting_length, overall_length,
        shank_type, shank_diameter,
        material, location, remarks,
        total_qty, reorder_level
    )
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT (
        tool_type, cutting_diameter, cutting_length,
        shank_type, shank_diameter, material
    )
    DO UPDATE SET
        total_qty = total_qty + excluded.total_qty,
        reorder_level = excluded.reorder_level
""", (
    f["tool_type"],
    f["tool_subtype"],
    f["cutting_diameter"],
    f["cutting_length"],
    f["overall_length"],
    f["shank_type"],
    f["shank_diameter"],
    f["material"],
    f["location"],
    f["remarks"],
    int(f["total_qty"]),
    int(f.get("reorder_level", 2))
))

    con.commit()
    con.close()
    return redirect("/tools/")

@tools_bp.route("/issue", methods=["GET", "POST"])
def tool_issue_page():
    con = get_db()
    machines = fetch_active_machines(con)
    
    if request.method == "POST":
        f = request.form
        qty = int(f["qty"])
        tool_id = int(f["tool_id"])

        available = con.execute("""
            SELECT (total_qty - issued_qty - broken_qty)
            FROM cutting_tools WHERE id=?
        """, (tool_id,)).fetchone()[0]

        if qty > available:
            con.close()
            return "Not enough stock", 400

        con.execute("""
            UPDATE cutting_tools
            SET issued_qty = issued_qty + ?
            WHERE id=?
        """, (qty, tool_id))
        con.execute("""
            INSERT INTO tool_issue_txn
            (tool_id, action, qty, operator, machine, shift, job_name, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tool_id,
            "ISSUE",
            qty,
            f["operator"],
            f["machine_code"],
            f["shift"],
            f["job_name"],
            f["issue_date"]
        ))

        con.commit()
        con.close()
        return redirect("/tools")

    # GET
    tools = con.execute("""
        SELECT id, tool_type, material, cutting_diameter, cutting_length
        FROM cutting_tools
        ORDER BY tool_type
    """).fetchall()

    #machines = fetch_active_machines(con)

    con.close()

    return render_template(
        "tool_issue.html",
        tools=tools,
        machines=machines,
        today=date.today().isoformat()
    )

@tools_bp.route("/return", methods=["GET", "POST"])
def tool_return_page():
    con = get_db()
    machines = fetch_active_machines(con)
    if request.method == "POST":
        f = request.form
        qty = int(f["qty"])
        tool_id = int(f["tool_id"])
        condition = f["condition"]

        if condition == "Good":
            con.execute("""
                UPDATE cutting_tools
                SET issued_qty = issued_qty - ?
                WHERE id=?
            """, (qty, tool_id))

        elif condition == "Blunt":
            con.execute("""
                UPDATE cutting_tools
                SET issued_qty = issued_qty - ?
                WHERE id=?
            """, (qty, tool_id))

        elif condition == "Broken":
            con.execute("""
                UPDATE cutting_tools
                SET issued_qty = issued_qty - ?,
                    broken_qty = broken_qty + ?
                WHERE id=?
            """, (qty, qty, tool_id))

        con.execute("""
           INSERT INTO tool_issue_txn
           (tool_id, action, qty, operator, machine, shift, condition, remarks, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
           tool_id,
           "RETURN",
           qty,
           f["operator"],
           f.get("machine_code", ""),   # optional
           f["shift"],
           condition,
           f.get("remarks", ""),
           f["return_date"]
        ))
        con.commit()
        con.close()
        return redirect("/tools")

    tools = con.execute("""
        SELECT id, tool_type, material, cutting_diameter, cutting_length
        FROM cutting_tools
        WHERE issued_qty > 0
    """).fetchall()
    con.close()

    return render_template("tool_return.html", tools=tools,  machines=machines, today=date.today().isoformat())

@tools_bp.route("/history")
def tool_history():
    con = get_db()

    # Filters (optional)
    tool_id = request.args.get("tool_id", "")
    action = request.args.get("action", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    query = """
        SELECT
            tx.ts,
            ct.tool_type,
            ct.material,
            ct.cutting_diameter,
            ct.cutting_length,
            tx.action,
            tx.qty,
            tx.operator,
            tx.machine,
            tx.shift,
            tx.job_name,
            tx.condition,
            tx.remarks
        FROM tool_issue_txn tx
        JOIN cutting_tools ct ON ct.id = tx.tool_id
        WHERE 1=1
    """
    params = []

    if tool_id:
        query += " AND tx.tool_id=?"
        params.append(tool_id)

    if action:
        query += " AND tx.action=?"
        params.append(action)

    if date_from:
        query += " AND date(tx.ts) >= date(?)"
        params.append(date_from)

    if date_to:
        query += " AND date(tx.ts) <= date(?)"
        params.append(date_to)

    query += " ORDER BY tx.ts DESC"

    rows = con.execute(query, params).fetchall()

    tools = con.execute("""
        SELECT id, tool_type, cutting_diameter, material
        FROM cutting_tools
        ORDER BY tool_type
    """).fetchall()

    con.close()

    return render_template(
        "tool_history.html",
        rows=rows,
        tools=tools
    )
@tools_bp.route("/regrind", methods=["GET", "POST"])
def tool_regrind_page():
    con = get_db()

    if request.method == "POST":
        f = request.form
        qty = int(f["qty"])
        tool_id = int(f["tool_id"])

        con.execute("""
            UPDATE cutting_tools
            SET issued_qty = issued_qty - ?
            WHERE id=?
        """, (qty, tool_id))

        con.execute("""
            INSERT INTO tool_issue_txn
            (tool_id, action, qty, operator, remarks)
            VALUES (?, 'REGRIND', ?, ?, ?)
        """, (
            tool_id, qty,
            f["operator"],
            f.get("remarks", "")
        ))

        con.commit()
        con.close()
        return redirect("/tools")

    tools = con.execute("""
        SELECT id, tool_type, material, cutting_diameter
        FROM cutting_tools
        WHERE issued_qty > 0
    """).fetchall()
    con.close()

    return render_template("tool_regrind.html", tools=tools)


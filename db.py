# db.py  (ELTA Workshop Suite)
# --------------------------------------------
# Single-file SQLite DB helper + schema init
# Works in normal python AND PyInstaller EXE (onefile/onedir)
# --------------------------------------------

import os
import sys
import sqlite3
import shutil
from pathlib import Path

# ================= PATH HELPERS =================

def app_data_dir(app_name: str = "ELTA_Workshop_Suite") -> str:
    """
    User-writable data directory.
    - Windows: %APPDATA%\\ELTA_Workshop_Suite
    - Linux/Mac: ~/.ELTA_Workshop_Suite
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        p = Path(base) / app_name
    else:
        p = Path.home() / f".{app_name}"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def resource_path(rel_path: str) -> str:
    """
    Works for PyInstaller (onefile/onedir) and normal python.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.abspath("."), rel_path)


def get_db_path():
    data_dir = app_data_dir()
    target = os.path.join(data_dir, "workshop.db")

    # Option A: never copy a bundled DB, always create/use user DB
    if not os.path.exists(target):
        open(target, "a").close()

    return target



DB_PATH = get_db_path()

# ================= CONNECTION =================

def get_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    # IMPORTANT: enforce FK constraints (needed for ON DELETE CASCADE)
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def fetch_active_machines(db: sqlite3.Connection | None = None):
    """
    If db not supplied, creates a connection internally.
    This keeps compatibility with modules that call fetch_active_machines()
    and modules that call fetch_active_machines(db).
    """
    close_me = False
    if db is None:
        db = get_db()
        close_me = True

    rows = db.execute("""
        SELECT machine_code, machine_name
        FROM machine_master
        WHERE status='ACTIVE'
        ORDER BY machine_code
    """).fetchall()

    if close_me:
        db.close()
    return rows


# ================= SCHEMA INIT =================

def init_db():
    con = get_db()
    try:
        # 1) Create all tables (safe for new DB; no-op for existing tables)
        con.executescript("""
        /* ================= CUTTING TOOL SPECS ================= */
        CREATE TABLE IF NOT EXISTS cutting_tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_type TEXT,
            tool_subtype TEXT,
            cutting_diameter REAL,
            cutting_length REAL,
            overall_length REAL,
            shank_type TEXT,
            shank_diameter REAL,
            material TEXT,
            location TEXT,
            remarks TEXT,
            total_qty INTEGER DEFAULT 0,
            issued_qty INTEGER DEFAULT 0,
            broken_qty INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 2,
            UNIQUE (tool_type, cutting_diameter, cutting_length, shank_type, shank_diameter, material)
        );

        CREATE TABLE IF NOT EXISTS tool_issue_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_id INTEGER,
            action TEXT,
            qty INTEGER,
            operator TEXT,
            machine TEXT,
            shift TEXT,
            job_name TEXT,
            condition TEXT,
            remarks TEXT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        /* ================= HOLDERS ================= */
        CREATE TABLE IF NOT EXISTS holders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holder_type TEXT,
            interface TEXT,
            size TEXT,
            projection REAL,
            location TEXT,
            remarks TEXT,
            total_qty INTEGER DEFAULT 0,
            issued_qty INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 1,
            UNIQUE (holder_type, interface, size, projection)
        );

        CREATE TABLE IF NOT EXISTS holder_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holder_id INTEGER,
            action TEXT,
            qty INTEGER,
            operator TEXT,
            machine TEXT,
            shift TEXT,
            remarks TEXT,
            ts DATE
        );

        /* ================= INSERTS ================= */
        CREATE TABLE IF NOT EXISTS inserts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insert_type TEXT,
            size TEXT,
            grade TEXT,
            edges INTEGER,
            total_qty INTEGER,
            available_qty INTEGER,
            reorder_level INTEGER,
            remarks TEXT,
            UNIQUE(insert_type, size, grade)
        );

        CREATE TABLE IF NOT EXISTS insert_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insert_id INTEGER,
            action TEXT,
            qty INTEGER,
            edges_used INTEGER,
            operator TEXT,
            machine TEXT,
            job TEXT,
            shift TEXT,
            txn_date DATE
        );

        /* ================= COLLETS ================= */
        CREATE TABLE IF NOT EXISTS collets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collet_type TEXT,
            interface TEXT,
            size_range TEXT,
            location TEXT,
            total_qty INTEGER DEFAULT 0,
            available_qty INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 2,
            remarks TEXT,
            UNIQUE (collet_type, interface, size_range, location)
        );

        CREATE TABLE IF NOT EXISTS collet_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collet_id INTEGER,
            action TEXT,
            qty INTEGER,
            operator TEXT,
            machine TEXT,
            shift TEXT,
            txn_date DATE
        );

        /* ================= GAUGES ================= */
        CREATE TABLE IF NOT EXISTS gauges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gauge_code TEXT UNIQUE,
            category TEXT,
            subtype TEXT,
            mechanism TEXT,
            range TEXT,
            least_count TEXT,
            make TEXT,
            serial_no TEXT,
            location TEXT,
            calibration_freq INTEGER DEFAULT 365,
            last_calibration DATE,
            next_calibration DATE,
            status TEXT DEFAULT 'OK',
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS gauge_issue_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gauge_id INTEGER,
            action TEXT,
            operator TEXT,
            machine TEXT,
            job TEXT,
            shift TEXT,
            condition_on_return TEXT,
            remarks TEXT,
            txn_date DATE
        );

        CREATE TABLE IF NOT EXISTS gauge_calibration_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gauge_id INTEGER,
            calibration_date DATE,
            calibrated_by TEXT,
            result TEXT,
            certificate_no TEXT,
            remarks TEXT
        );

        /* ================= CUSTOMER / MATERIAL ================= */
        CREATE TABLE IF NOT EXISTS customer_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT UNIQUE NOT NULL,
            short_code TEXT,
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS customer_challan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            customer_challan_no TEXT NOT NULL,
            customer_challan_date DATE NOT NULL,
            status TEXT DEFAULT 'OPEN',
            remarks TEXT,
            UNIQUE (customer_id, customer_challan_no)
        );

        CREATE TABLE IF NOT EXISTS material_inward (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challan_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            process TEXT,
            inward_qty INTEGER NOT NULL,
            available_qty INTEGER NOT NULL,
            box_tray TEXT,
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS material_dispatch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challan_id INTEGER NOT NULL,
            inward_id INTEGER NOT NULL,
            elta_challan_no TEXT NOT NULL,
            dispatch_date DATE NOT NULL,
            ok_qty INTEGER DEFAULT 0,
            rej_qty INTEGER DEFAULT 0,
            cd_qty INTEGER DEFAULT 0,
            nd_qty INTEGER DEFAULT 0,
            nd_pw_qty INTEGER DEFAULT 0,
            total_qty INTEGER NOT NULL,
            remarks TEXT
        );

        /* ================= ITEM CODE MASTER ================= */
        CREATE TABLE IF NOT EXISTS item_code_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT UNIQUE NOT NULL,
            description TEXT,
            remarks TEXT
        );

        /* ================= SHIFT ================= */
        CREATE TABLE IF NOT EXISTS shift_header (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_date DATE NOT NULL,
            shift TEXT NOT NULL,
            shift_incharge TEXT NOT NULL,
            remarks TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (shift_date, shift)
        );

        CREATE TABLE IF NOT EXISTS shift_production (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            machine TEXT,
            operator TEXT,
            ok_qty INTEGER DEFAULT 0,
            rej_qty INTEGER DEFAULT 0,
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS shift_setup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL,
            machine TEXT,
            from_item TEXT,
            to_item TEXT,
            setup_time_min INTEGER,
            remarks TEXT
        );

        CREATE TABLE IF NOT EXISTS shift_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL,
            operator TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS shift_downtime (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL,
            machine TEXT,
            reason TEXT,
            minutes INTEGER
        );

        /* ================= MACHINE ================= */
        CREATE TABLE IF NOT EXISTS machine_master (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_code    TEXT UNIQUE NOT NULL,
            machine_name    TEXT NOT NULL,
            machine_type    TEXT NOT NULL,
            controller      TEXT,
            location        TEXT,
            status          TEXT NOT NULL DEFAULT 'ACTIVE',
            install_date    DATE,
            notes           TEXT,
            created_ts      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        /* ================= PM ================= */
        CREATE TABLE IF NOT EXISTS pm_master (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_code      TEXT NOT NULL,
            pm_name           TEXT NOT NULL,
            frequency_days    INTEGER NOT NULL,
            responsibility    TEXT,
            checklist         TEXT,
            active            INTEGER DEFAULT 1,
            created_ts        DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(machine_code) REFERENCES machine_master(machine_code)
        );

        CREATE TABLE IF NOT EXISTS pm_schedule (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            pm_id             INTEGER NOT NULL,
            last_done_date    DATE,
            next_due_date     DATE NOT NULL,
            status            TEXT NOT NULL DEFAULT 'DUE',
            FOREIGN KEY(pm_id) REFERENCES pm_master(id)
        );

        CREATE TABLE IF NOT EXISTS pm_history (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            pm_id             INTEGER NOT NULL,
            done_date         DATE NOT NULL,
            done_by           TEXT,
            remarks           TEXT,
            FOREIGN KEY(pm_id) REFERENCES pm_master(id)
        );

        /* ================= BREAKDOWN ================= */
        CREATE TABLE IF NOT EXISTS breakdown_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_code    TEXT NOT NULL,
            breakdown_date  DATE NOT NULL,
            start_time      TEXT NOT NULL,
            end_time        TEXT,
            downtime_min    INTEGER NOT NULL DEFAULT 0,
            problem         TEXT NOT NULL,
            root_cause      TEXT,
            action_taken    TEXT,
            handled_by      TEXT,
            status          TEXT NOT NULL DEFAULT 'OPEN',
            created_ts      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(machine_code) REFERENCES machine_master(machine_code)
        );

        /* ================= COMPLAINTS ================= */
        CREATE TABLE IF NOT EXISTS customer_complaint (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_no         TEXT UNIQUE NOT NULL,
            complaint_date       TEXT NOT NULL,
            customer_id          INTEGER NOT NULL,
            customer_ref_no      TEXT,
            item_code            TEXT NOT NULL,
            batch_no             TEXT,
            qty_affected         INTEGER DEFAULT 0,
            issue_category       TEXT NOT NULL,
            issue_description    TEXT NOT NULL,
            severity             TEXT NOT NULL DEFAULT 'MED',
            status               TEXT NOT NULL DEFAULT 'OPEN',
            machine_code         TEXT,
            job_no               TEXT,
            shift_date           TEXT,
            shift                TEXT,
            assigned_to          TEXT,
            containment_action   TEXT,
            root_cause_5why      TEXT,
            corrective_action    TEXT,
            preventive_action    TEXT,
            closure_date         TEXT,
            closure_remarks      TEXT,
            created_ts           TEXT NOT NULL DEFAULT (datetime('now')),
            updated_ts           TEXT
        );

        CREATE TABLE IF NOT EXISTS complaint_action_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id    INTEGER NOT NULL,
            action_date     TEXT NOT NULL,
            action_type     TEXT NOT NULL,
            notes           TEXT NOT NULL,
            by_user         TEXT,
            created_ts      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        /* ================= INDEXES ================= */
        CREATE INDEX IF NOT EXISTS idx_cc_customer ON customer_complaint(customer_id);
        CREATE INDEX IF NOT EXISTS idx_cc_status   ON customer_complaint(status);
        CREATE INDEX IF NOT EXISTS idx_cc_item     ON customer_complaint(item_code);
        CREATE INDEX IF NOT EXISTS idx_cc_date     ON customer_complaint(complaint_date);
        CREATE INDEX IF NOT EXISTS idx_cc_log_complaint ON complaint_action_log(complaint_id);

        CREATE INDEX IF NOT EXISTS idx_breakdown_machine ON breakdown_log(machine_code);
        CREATE INDEX IF NOT EXISTS idx_breakdown_status  ON breakdown_log(status);
        CREATE INDEX IF NOT EXISTS idx_breakdown_date    ON breakdown_log(breakdown_date);

        CREATE INDEX IF NOT EXISTS idx_pm_schedule_status ON pm_schedule(status);
        CREATE INDEX IF NOT EXISTS idx_pm_master_machine  ON pm_master(machine_code);

        CREATE INDEX IF NOT EXISTS idx_machine_master_type   ON machine_master(machine_type);
        CREATE INDEX IF NOT EXISTS idx_machine_master_status ON machine_master(status);

        /* ================= ITEM CODE PPAP / DRAWING DOCS (VERSIONED) ================= */
        CREATE TABLE IF NOT EXISTS item_code_ppap_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code_id INTEGER NOT NULL,
            doc_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            doc_type TEXT DEFAULT 'PPAP',
            notes TEXT DEFAULT '',
            uploaded_at TEXT NOT NULL,
            doc_category TEXT DEFAULT 'PPAP',
            version_no INTEGER DEFAULT 1,
            is_current INTEGER DEFAULT 1,
            FOREIGN KEY(item_code_id) REFERENCES item_code_master(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_ppap_item_code_id
            ON item_code_ppap_docs(item_code_id);
        """)

        # 2) Safe upgrades: add missing columns (older DBs)
        def add_column_safe(sql: str):
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                # duplicate column name / table missing etc.
                pass
            except Exception:
                pass

        add_column_safe("ALTER TABLE item_code_ppap_docs ADD COLUMN doc_category TEXT DEFAULT 'PPAP'")
        add_column_safe("ALTER TABLE item_code_ppap_docs ADD COLUMN version_no INTEGER DEFAULT 1")
        add_column_safe("ALTER TABLE item_code_ppap_docs ADD COLUMN is_current INTEGER DEFAULT 1")

        # 3) Fix wrong FK (item_codes -> item_code_master)
        # IMPORTANT: _fix_ppap_fk(con) must NOT close/commit the connection
        _fix_ppap_fk(con)

        # 4) Indexes that depend on new columns (create after columns exist)
        try:
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_ppap_item_code_cat
                ON item_code_ppap_docs(item_code_id, doc_category)
            """)
        except Exception:
            pass

        try:
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_ppap_item_code_current
                ON item_code_ppap_docs(item_code_id, doc_category, is_current)
            """)
        except Exception:
            pass

        con.commit()

    finally:
        con.close()
    

def _fix_ppap_fk(con):
    cur = con.cursor()

    fk = cur.execute(
        "PRAGMA foreign_key_list(item_code_ppap_docs)"
    ).fetchall()

    if fk and fk[0]["table"] == "item_codes":
        print("🔧 Fixing PPAP foreign key (item_codes → item_code_master)")

        con.executescript("""
        PRAGMA foreign_keys=OFF;

        ALTER TABLE item_code_ppap_docs RENAME TO item_code_ppap_docs_old;

        CREATE TABLE item_code_ppap_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code_id INTEGER NOT NULL,
            doc_name TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            doc_type TEXT DEFAULT 'PPAP',
            notes TEXT DEFAULT '',
            uploaded_at TEXT NOT NULL,
            doc_category TEXT DEFAULT 'PPAP',
            version_no INTEGER DEFAULT 1,
            is_current INTEGER DEFAULT 1,
            FOREIGN KEY(item_code_id) REFERENCES item_code_master(id) ON DELETE CASCADE
        );

        INSERT INTO item_code_ppap_docs
        (id, item_code_id, doc_name, stored_name, doc_type, notes, uploaded_at, doc_category, version_no, is_current)
        SELECT
            id, item_code_id, doc_name, stored_name, doc_type, notes, uploaded_at,
            COALESCE(doc_category,'PPAP'),
            COALESCE(version_no,1),
            COALESCE(is_current,1)
        FROM item_code_ppap_docs_old;

        DROP TABLE item_code_ppap_docs_old;

        CREATE INDEX IF NOT EXISTS idx_ppap_item_code_id
            ON item_code_ppap_docs(item_code_id);

        CREATE INDEX IF NOT EXISTS idx_ppap_item_code_cat
            ON item_code_ppap_docs(item_code_id, doc_category);

        CREATE INDEX IF NOT EXISTS idx_ppap_item_code_current
            ON item_code_ppap_docs(item_code_id, doc_category, is_current);

        PRAGMA foreign_keys=ON;
        """)

        print("✅ PPAP FK fixed")

   


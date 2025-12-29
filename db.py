import sqlite3

#DB_PATH = "workshop.db"


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row   # 🔥 THIS LINE FIXES EVERYTHING
    return con
    
def fetch_active_machines(db):
    return db.execute("""
        SELECT machine_code, machine_name
        FROM machine_master
        WHERE status='ACTIVE'
        ORDER BY machine_code
    """).fetchall()

import os
import sys
from pathlib import Path

def app_data_dir(app_name="ELTA_Workshop_Suite"):
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        p = Path(base) / app_name
    else:
        p = Path.home() / f".{app_name}"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)

def resource_path(rel_path: str) -> str:
    # Works for PyInstaller (onefile/onedir) and normal python
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.abspath("."), rel_path)

def get_db_path():
    data_dir = app_data_dir()
    target = os.path.join(data_dir, "workshop.db")
    if not os.path.exists(target):
        bundled = resource_path("workshop.db")
        if os.path.exists(bundled):
            shutil.copy2(bundled, target)
        else:
            # first run in dev (no bundled db) -> create empty file later via init_db()
            open(target, "a").close()
    return target

DB_PATH = get_db_path()

def init_db():
    con = get_db()
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

    
    UNIQUE (
        tool_type,
        cutting_diameter,
        cutting_length,
        shank_type,
        shank_diameter,
        material
        )
    );
    CREATE TABLE IF NOT EXISTS tool_issue_txn (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_id INTEGER,
        action TEXT,              -- ISSUE / RETURN / BLUNT / BROKEN
        qty INTEGER,

        operator TEXT,
        machine TEXT,
        shift TEXT,
        job_name TEXT,

        condition TEXT,           -- Good / Blunt / Broken (RETURN only)
        remarks TEXT,

        ts DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS holders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        holder_type TEXT,
        interface TEXT,          -- BT40 / HSK63 / CAT40
        size TEXT,               -- ER32 / ER16 / MT3
        projection REAL,         -- mm
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
        action TEXT,             -- ISSUE / RETURN
        qty INTEGER,
        operator TEXT,
        machine TEXT,
        shift TEXT,
        remarks TEXT,
        ts DATE
    );
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
        action TEXT,              -- ISSUE / EDGE_USED / SCRAP
        qty INTEGER,
        edges_used INTEGER,
        operator TEXT,
        machine TEXT,
        job TEXT,
        shift TEXT,
        txn_date DATE
    );
    CREATE TABLE IF NOT EXISTS collets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    collet_type TEXT,           -- ER / DA
    interface TEXT,             -- ER16 / ER20 / ER32
    size_range TEXT,            -- 1-10 / 6-12 etc

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

    action TEXT,                -- ISSUE / RETURN
    qty INTEGER,

    operator TEXT,
    machine TEXT,
    shift TEXT,

    txn_date DATE
);
/* ================= GAUGES / INSPECTION INSTRUMENTS ================= */

CREATE TABLE IF NOT EXISTS gauges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    gauge_code TEXT UNIQUE,              -- VER-001, MIC-004, WCR-002

    category TEXT,                       -- DIM / THREAD / AIR / QUAL / WEAR / CUSTOM
    subtype TEXT,                        -- Vernier Caliper, Micrometer, WCR
    mechanism TEXT,                     -- Analog / Digital / Dial / Lever / Plunger / Air

    range TEXT,                          -- 0–150mm / M10x1.5
    least_count TEXT,                   -- 0.01mm

    make TEXT,
    serial_no TEXT,

    location TEXT,

    calibration_freq INTEGER DEFAULT 365,
    last_calibration DATE,
    next_calibration DATE,

    status TEXT DEFAULT 'OK',            -- OK / DUE / OVERDUE / DAMAGED
    remarks TEXT
);

CREATE TABLE IF NOT EXISTS gauge_issue_txn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gauge_id INTEGER,

    action TEXT,                         -- ISSUE / RETURN
    operator TEXT,
    machine TEXT,
    job TEXT,
    shift TEXT,

    condition_on_return TEXT,            -- OK / DAMAGED
    remarks TEXT,

    txn_date DATE
);

CREATE TABLE IF NOT EXISTS gauge_calibration_txn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gauge_id INTEGER,

    calibration_date DATE,
    calibrated_by TEXT,
    result TEXT,                         -- PASS / FAIL
    certificate_no TEXT,

    remarks TEXT
);
/* ================= CUSTOMER MASTER ================= */

CREATE TABLE IF NOT EXISTS customer_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT UNIQUE NOT NULL,
    short_code TEXT,
    remarks TEXT
);

/* ================= CUSTOMER CHALLAN (HEADER) ================= */

CREATE TABLE IF NOT EXISTS customer_challan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    customer_id INTEGER NOT NULL,
    customer_challan_no TEXT NOT NULL,
    customer_challan_date DATE NOT NULL,

    status TEXT DEFAULT 'OPEN',     -- OPEN / CLOSED
    remarks TEXT,

    UNIQUE (customer_id, customer_challan_no)
);

/* ================= MATERIAL INWARD (LINE ITEMS) ================= */

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

/* ================= MATERIAL DISPATCH ================= */

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
CREATE TABLE IF NOT EXISTS item_code_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code TEXT UNIQUE NOT NULL,
    description TEXT,
    remarks TEXT
);
-- ================= SHIFT HEADER =================
CREATE TABLE IF NOT EXISTS shift_header (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shift_date DATE NOT NULL,
    shift TEXT NOT NULL,              -- A / B / C
    shift_incharge TEXT NOT NULL,

    remarks TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (shift_date, shift)
);

-- ================= PRODUCTION =================
CREATE TABLE IF NOT EXISTS shift_production (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shift_id INTEGER NOT NULL,
    item_code TEXT NOT NULL,          -- from item_code_master (MANDATORY)
    machine TEXT,
    operator TEXT,

    ok_qty INTEGER DEFAULT 0,
    rej_qty INTEGER DEFAULT 0,

    remarks TEXT
);

-- ================= SETUP CHANGE =================
CREATE TABLE IF NOT EXISTS shift_setup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shift_id INTEGER NOT NULL,
    machine TEXT,
    from_item TEXT,
    to_item TEXT,
    setup_time_min INTEGER,
    remarks TEXT
);

-- ================= ATTENDANCE =================
CREATE TABLE IF NOT EXISTS shift_attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shift_id INTEGER NOT NULL,
    operator TEXT NOT NULL,
    status TEXT NOT NULL              -- Present / Absent / Half
);

-- ================= DOWNTIME =================
CREATE TABLE IF NOT EXISTS shift_downtime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    shift_id INTEGER NOT NULL,
    machine TEXT,
    reason TEXT,
    minutes INTEGER
);
/* ================= MACHINE MASTER ================= */

CREATE TABLE IF NOT EXISTS machine_master (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_code    TEXT UNIQUE NOT NULL,          -- CNC-01, VMC-02
    machine_name    TEXT NOT NULL,                 -- Cincinnati Lamb 550i
    machine_type    TEXT NOT NULL,                 -- VMC / HMC / LATHE / GRINDER / OTHER
    controller      TEXT,                          -- Fanuc 18iM / Siemens
    location        TEXT,                          -- Bay / Line / Area
    status          TEXT NOT NULL DEFAULT 'ACTIVE',-- ACTIVE / INACTIVE / SCRAP
    install_date    DATE,
    notes           TEXT,
    created_ts      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- PREVENTIVE MAINTENANCE MASTER
-- =========================

CREATE TABLE IF NOT EXISTS pm_master (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_code      TEXT NOT NULL,
    pm_name           TEXT NOT NULL,        -- e.g. Spindle lubrication
    frequency_days    INTEGER NOT NULL,     -- e.g. 7 / 30 / 90
    responsibility    TEXT,                 -- Operator / Maintenance / Vendor
    checklist         TEXT,                 -- free-text or bullet points
    active            INTEGER DEFAULT 1,
    created_ts        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(machine_code) REFERENCES machine_master(machine_code)
);

-- =========================
-- PM SCHEDULE
-- =========================

CREATE TABLE IF NOT EXISTS pm_schedule (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pm_id             INTEGER NOT NULL,
    last_done_date    DATE,
    next_due_date     DATE NOT NULL,
    status            TEXT NOT NULL DEFAULT 'DUE', -- OK / DUE / OVERDUE
    FOREIGN KEY(pm_id) REFERENCES pm_master(id)
);

-- =========================
-- PM HISTORY
-- =========================

CREATE TABLE IF NOT EXISTS pm_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pm_id             INTEGER NOT NULL,
    done_date         DATE NOT NULL,
    done_by           TEXT,
    remarks           TEXT,
    FOREIGN KEY(pm_id) REFERENCES pm_master(id)
);
/* =========================
   BREAKDOWN MAINTENANCE
   ========================= */

CREATE TABLE IF NOT EXISTS breakdown_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_code    TEXT NOT NULL,
    breakdown_date  DATE NOT NULL,                 -- date of breakdown
    start_time      TEXT NOT NULL,                 -- HH:MM
    end_time        TEXT,                          -- HH:MM (optional until closed)
    downtime_min    INTEGER NOT NULL DEFAULT 0,     -- auto calculated on close
    problem         TEXT NOT NULL,                 -- what happened
    root_cause      TEXT,                          -- why it happened (optional)
    action_taken    TEXT,                          -- what was done (optional)
    handled_by      TEXT,                          -- technician/operator/vendor
    status          TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN / CLOSED
    created_ts      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(machine_code) REFERENCES machine_master(machine_code)
);

/* ================= CUSTOMER COMPLAINTS ================= */

CREATE TABLE IF NOT EXISTS customer_complaint (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_no         TEXT UNIQUE NOT NULL,      -- CC-2025-001
    complaint_date       TEXT NOT NULL,             -- YYYY-MM-DD

    customer_id          INTEGER NOT NULL,
    customer_ref_no      TEXT,                      -- optional: customer complaint ref / PO / challan

    item_code            TEXT NOT NULL,             -- from item_code_master
    batch_no             TEXT,
    qty_affected         INTEGER DEFAULT 0,

    issue_category       TEXT NOT NULL,             -- fixed + Other
    issue_description    TEXT NOT NULL,

    severity             TEXT NOT NULL DEFAULT 'MED',  -- LOW/MED/HIGH
    status               TEXT NOT NULL DEFAULT 'OPEN', -- OPEN/UNDER_INVESTIGATION/WAITING_CUSTOMER/CAPA_IMPLEMENTED/CLOSED/REJECTED

    machine_code         TEXT,                      -- machine_master.machine_code (optional)
    job_no               TEXT,
    shift_date           TEXT,
    shift                TEXT,                      -- A/B/C

    assigned_to          TEXT,                      -- free text
    containment_action   TEXT,
    root_cause_5why      TEXT,
    corrective_action    TEXT,
    preventive_action    TEXT,

    closure_date         TEXT,
    closure_remarks      TEXT,

    created_ts           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_ts           TEXT
);

CREATE INDEX IF NOT EXISTS idx_cc_customer ON customer_complaint(customer_id);
CREATE INDEX IF NOT EXISTS idx_cc_status   ON customer_complaint(status);
CREATE INDEX IF NOT EXISTS idx_cc_item     ON customer_complaint(item_code);
CREATE INDEX IF NOT EXISTS idx_cc_date     ON customer_complaint(complaint_date);

CREATE TABLE IF NOT EXISTS complaint_action_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id    INTEGER NOT NULL,
    action_date     TEXT NOT NULL,          -- YYYY-MM-DD
    action_type     TEXT NOT NULL,          -- NOTE / CONTAINMENT / RCA / CAPA / CUSTOMER_REPLY / CLOSE
    notes           TEXT NOT NULL,
    by_user         TEXT,
    created_ts      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cc_log_complaint ON complaint_action_log(complaint_id);

CREATE INDEX IF NOT EXISTS idx_breakdown_machine
    ON breakdown_log(machine_code);

CREATE INDEX IF NOT EXISTS idx_breakdown_status
    ON breakdown_log(status);

CREATE INDEX IF NOT EXISTS idx_breakdown_date
    ON breakdown_log(breakdown_date);

CREATE INDEX IF NOT EXISTS idx_pm_schedule_status
    ON pm_schedule(status);

CREATE INDEX IF NOT EXISTS idx_pm_master_machine
    ON pm_master(machine_code);



CREATE INDEX IF NOT EXISTS idx_machine_master_type
    ON machine_master(machine_type);

CREATE INDEX IF NOT EXISTS idx_machine_master_status
    ON machine_master(status);

    """)
    con.commit()
    con.close()


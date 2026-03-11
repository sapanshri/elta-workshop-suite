import gzip
import json
import os
import shutil
import sqlite3
import csv
import io
from pathlib import Path

from flask import Blueprint, current_app, render_template, request, send_file

from db import app_data_dir
from modules.materials import load_inventory_rows
from modules.shift_production import load_machine_report_data, resolve_machine_report_filters


public_inventory_bp = Blueprint("public_inventory", __name__)

PUBLIC_HOSTS = {"eltaengineering.com", "www.eltaengineering.com"}
BACKUP_PATTERN = "workshop_*.db.gz"


def is_public_host(host: str) -> bool:
    hostname = (host or "").split(":", 1)[0].lower()
    return hostname in PUBLIC_HOSTS


def _load_backup_config() -> dict:
    candidates = [
        Path(app_data_dir()) / "backup_config.json",
        Path(__file__).resolve().parent.parent / "backup_config.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return {}


def _backup_source_dir() -> Path | None:
    override = (current_app.config.get("PUBLIC_INVENTORY_BACKUP_DIR") or "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None

    env_path = (os.environ.get("ELTA_PUBLIC_BACKUP_DIR") or "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        return path if path.exists() else None

    cfg = _load_backup_config()
    remote_dir = (cfg.get("remote_backup_dir") or "").strip()
    if remote_dir:
        path = Path(remote_dir).expanduser()
        if path.exists():
            return path

    local_dir = Path(app_data_dir()) / "db_backups"
    if local_dir.exists():
        return local_dir

    return None


def _latest_backup_file() -> Path | None:
    source_dir = _backup_source_dir()
    if source_dir is None:
        return None

    backups = [p for p in source_dir.glob(BACKUP_PATTERN) if p.is_file()]
    if not backups:
        return None
    return max(backups, key=lambda p: p.stat().st_mtime)


def _public_cache_dir() -> Path:
    cache_dir = Path(app_data_dir()) / "public_inventory_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _restore_latest_backup() -> tuple[Path | None, Path | None]:
    backup_file = _latest_backup_file()
    if backup_file is None:
        return None, None

    cache_dir = _public_cache_dir()
    restored_db = cache_dir / "latest_public_inventory.db"
    stamp_file = cache_dir / "latest_public_inventory.stamp"
    current_stamp = f"{backup_file.name}:{int(backup_file.stat().st_mtime)}"

    cached_stamp = ""
    if stamp_file.exists():
        try:
            cached_stamp = stamp_file.read_text(encoding="utf-8").strip()
        except Exception:
            cached_stamp = ""

    if restored_db.exists() and cached_stamp == current_stamp:
        return restored_db, backup_file

    tmp_db = cache_dir / "latest_public_inventory.tmp"
    with gzip.open(backup_file, "rb") as src, tmp_db.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp_db.replace(restored_db)
    stamp_file.write_text(current_stamp, encoding="utf-8")
    return restored_db, backup_file


def _open_public_db() -> tuple[sqlite3.Connection | None, Path | None]:
    restored_db, backup_file = _restore_latest_backup()
    if restored_db is None:
        return None, None

    con = sqlite3.connect(f"file:{restored_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con, backup_file


@public_inventory_bp.route("/material-inventory")
@public_inventory_bp.route("/public/material-inventory")
def public_material_inventory():
    db, backup_file = _open_public_db()
    if db is None:
        return render_template(
            "public_material_inventory.html",
            rows=[],
            customers=[],
            item_codes=[],
            backup_name="",
            backup_updated_at="",
            load_error="No uploaded backup file was found for public inventory display.",
        )

    try:
        customer_id = request.args.get("customer_id", "")
        item_code = request.args.get("item_code", "")
        status = request.args.get("status", "")
        from_date = request.args.get("from_date", "")
        to_date = request.args.get("to_date", "")

        rows, closed_mode = load_inventory_rows(
            db, customer_id, item_code, status, from_date, to_date
        )
        customers = db.execute(
            """
            SELECT id, customer_name
            FROM customer_master
            ORDER BY customer_name
            """
        ).fetchall()
        item_codes = db.execute(
            """
            SELECT item_code
            FROM item_code_master
            ORDER BY item_code
            """
        ).fetchall()

        updated_at = ""
        if backup_file is not None:
            updated_at = backup_file.stat().st_mtime

        return render_template(
            "public_material_inventory.html",
            rows=rows,
            customers=customers,
            item_codes=item_codes,
            closed_mode=closed_mode,
            backup_name=backup_file.name if backup_file else "",
            backup_updated_at=updated_at,
            load_error="",
        )
    finally:
        db.close()


@public_inventory_bp.route("/machine-report")
def public_machine_report():
    db, backup_file = _open_public_db()
    if db is None:
        return render_template(
            "public_machine_report.html",
            rows=[],
            machines=[],
            summary={"ok_qty": 0, "rej_qty": 0, "total_qty": 0},
            date_range="last_7",
            from_date="",
            to_date="",
            shift="",
            machine_code="",
            backup_name="",
            backup_updated_at="",
            load_error="No uploaded backup file was found for public machine report display.",
        )

    try:
        filters = resolve_machine_report_filters(request.args)
        rows, summary = load_machine_report_data(db, filters)
        machines = db.execute(
            """
            SELECT machine_code, machine_name
            FROM machine_master
            WHERE status='ACTIVE'
            ORDER BY machine_code
            """
        ).fetchall()

        updated_at = ""
        if backup_file is not None:
            updated_at = backup_file.stat().st_mtime

        return render_template(
            "public_machine_report.html",
            rows=rows,
            machines=machines,
            summary=summary,
            date_range=filters["date_range"],
            from_date=filters["from_date"],
            to_date=filters["to_date"],
            shift=filters["shift"],
            machine_code=filters["machine_code"],
            backup_name=backup_file.name if backup_file else "",
            backup_updated_at=updated_at,
            load_error="",
        )
    finally:
        db.close()


@public_inventory_bp.route("/machine-report/excel")
def public_machine_report_excel():
    db, _ = _open_public_db()
    if db is None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date",
            "Shift",
            "Machine",
            "Machine Name",
            "Item Codes",
            "OK Qty",
            "Reject Qty",
            "Total Qty",
        ])
        data = output.getvalue().encode("utf-8-sig")
        buf = io.BytesIO(data)
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name="public_machine_report.csv",
            mimetype="text/csv; charset=utf-8",
        )

    try:
        filters = resolve_machine_report_filters(request.args)
        rows, _ = load_machine_report_data(db, filters)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date",
            "Shift",
            "Machine",
            "Machine Name",
            "Item Codes",
            "OK Qty",
            "Reject Qty",
            "Total Qty",
        ])
        for r in rows:
            writer.writerow([
                r["shift_date"],
                r["shift"],
                r["machine_code"],
                r["machine_name"],
                r["item_codes"] or "",
                r["ok_qty"],
                r["rej_qty"],
                r["total_qty"],
            ])

        data = output.getvalue().encode("utf-8-sig")
        buf = io.BytesIO(data)
        buf.seek(0)

        return send_file(
            buf,
            as_attachment=True,
            download_name="public_machine_report.csv",
            mimetype="text/csv; charset=utf-8",
        )
    finally:
        db.close()

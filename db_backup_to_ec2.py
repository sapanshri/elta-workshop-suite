import argparse
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from db import app_data_dir, get_db_path


CONFIG_FILE = Path(__file__).with_name("backup_config.json")
CONFIG_EXAMPLE_FILE = Path(__file__).with_name("backup_config.json.example")
DEFAULT_PATTERN = "workshop_*.db.gz"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_config() -> dict:
    # Prefer app-data config so packaged desktop app can be configured per machine.
    app_cfg = Path(app_data_dir()) / "backup_config.json"
    candidates = [app_cfg, CONFIG_FILE]

    cfg_path = None
    for p in candidates:
        if p.exists():
            cfg_path = p
            break

    if cfg_path is None:
        # Auto-place template in app-data for easier first-time setup.
        if CONFIG_EXAMPLE_FILE.exists():
            app_cfg.parent.mkdir(parents=True, exist_ok=True)
            if not app_cfg.exists():
                shutil.copy2(CONFIG_EXAMPLE_FILE, app_cfg)
        raise FileNotFoundError(
            f"Missing backup config. Create/update: {app_cfg}"
        )

    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


def make_sqlite_snapshot(src_db: Path, out_db: Path) -> None:
    src = sqlite3.connect(str(src_db))
    dst = sqlite3.connect(str(out_db))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def gzip_file(src_file: Path, dst_gz: Path) -> None:
    with src_file.open("rb") as fi, gzip.open(dst_gz, "wb") as fo:
        shutil.copyfileobj(fi, fo)


def remove_old_local(local_dir: Path, keep_days: int, pattern: str = DEFAULT_PATTERN) -> int:
    if keep_days < 0:
        return 0
    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    removed = 0
    for p in local_dir.glob(pattern):
        if not p.is_file():
            continue
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def run_cmd(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def check_ssh_tools() -> None:
    for tool in ("ssh", "scp"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"Required tool not found in PATH: {tool}")


def ensure_remote_dir(host: str, user: str, key_file: str, port: int, remote_dir: str) -> None:
    run_cmd([
        "ssh",
        "-i",
        key_file,
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        f"mkdir -p '{remote_dir}'",
    ])


def upload_backup(host: str, user: str, key_file: str, port: int, local_file: Path, remote_dir: str) -> None:
    run_cmd([
        "scp",
        "-i",
        key_file,
        "-P",
        str(port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        str(local_file),
        f"{user}@{host}:{remote_dir}/",
    ])


def remove_old_remote(
    host: str,
    user: str,
    key_file: str,
    port: int,
    remote_dir: str,
    keep_days: int,
    pattern: str = DEFAULT_PATTERN,
) -> None:
    if keep_days < 0:
        return
    cmd = f"find '{remote_dir}' -type f -name '{pattern}' -mtime +{keep_days} -delete"
    run_cmd([
        "ssh",
        "-i",
        key_file,
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        cmd,
    ])


def build_local_dir(cfg: dict) -> Path:
    p = (cfg.get("local_backup_dir") or "").strip()
    if p:
        local_dir = Path(p).expanduser()
    else:
        local_dir = Path(app_data_dir()) / "db_backups"
    local_dir.mkdir(parents=True, exist_ok=True)
    return local_dir


def run_backup(dry_run: bool = False) -> int:
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 6

    if not cfg.get("enabled", True):
        print("Backup is disabled in backup_config.json (enabled=false).")
        return 0

    db_path = Path(get_db_path())
    if not db_path.exists():
        print(f"Database file not found: {db_path}", file=sys.stderr)
        return 2

    local_dir = build_local_dir(cfg)
    keep_local_days = int(cfg.get("keep_local_days", 7))
    keep_remote_days = int(cfg.get("keep_remote_days", 30))

    stamp = now_stamp()
    backup_name = f"workshop_{stamp}.db.gz"
    backup_path = local_dir / backup_name

    with tempfile.TemporaryDirectory(prefix="elta_db_backup_") as td:
        snap_db = Path(td) / "snapshot.db"
        make_sqlite_snapshot(db_path, snap_db)
        gzip_file(snap_db, backup_path)

    local_removed = remove_old_local(local_dir, keep_local_days)
    print(f"Local backup created: {backup_path}")
    print(f"Local old backups removed: {local_removed}")

    if dry_run:
        print("Dry run: skipped EC2 upload and remote cleanup.")
        return 0

    host = (cfg.get("ec2_host") or "").strip()
    user = (cfg.get("ec2_user") or "").strip()
    key_file = os.path.expanduser((cfg.get("ssh_key_file") or "").strip())
    remote_dir = (cfg.get("remote_backup_dir") or "").strip()
    port = int(cfg.get("ssh_port", 22))

    if not all([host, user, key_file, remote_dir]):
        print("Missing EC2/SSH config in backup_config.json.", file=sys.stderr)
        return 3
    if not Path(key_file).exists():
        print(f"SSH key file not found: {key_file}", file=sys.stderr)
        return 4

    try:
        check_ssh_tools()
        ensure_remote_dir(host, user, key_file, port, remote_dir)
        upload_backup(host, user, key_file, port, backup_path, remote_dir)
        remove_old_remote(host, user, key_file, port, remote_dir, keep_remote_days)
    except subprocess.CalledProcessError as e:
        print("Backup upload failed.", file=sys.stderr)
        if e.stdout:
            print(e.stdout, file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 5

    print("EC2 upload completed.")
    print(f"Remote cleanup done (kept last {keep_remote_days} days).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily DB backup and push to AWS EC2")
    parser.add_argument("--dry-run", action="store_true", help="Create local backup only, skip EC2 upload/cleanup")
    args = parser.parse_args()
    return run_backup(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

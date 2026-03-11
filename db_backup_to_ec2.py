import argparse
import gzip
import json
import os
import fnmatch
import shutil
import sqlite3
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


def status_file() -> Path:
    return Path(app_data_dir()) / "backup_status.json"


def log_file() -> Path:
    return Path(app_data_dir()) / "backup.log"


def write_status(code: int, message: str, extra: dict | None = None) -> None:
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "code": code,
        "message": message,
    }
    if extra:
        payload.update(extra)

    p = status_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with log_file().open("a", encoding="utf-8") as f:
        f.write(f"[{payload['timestamp']}] code={code} {message}\n")


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
                cfg_path = app_cfg

    if cfg_path is None:
        raise FileNotFoundError(f"Missing backup config. Create/update: {app_cfg}")

    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg


def resolve_ssh_key_file(cfg: dict) -> str:
    raw = (cfg.get("ssh_key_file") or "").strip()
    candidates = []

    if raw:
        candidates.append(Path(os.path.expanduser(raw)))

    app_dir = Path(app_data_dir())
    candidates.append(app_dir / "elta-ec2.pem")
    candidates.append(app_dir / ".ssh" / "elta-ec2.pem")

    runtime_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    candidates.append(runtime_dir / "elta-ec2.pem")
    candidates.append(Path.home() / ".ssh" / "elta-ec2.pem")

    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return str(path)

    return os.path.expanduser(raw) if raw else ""


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


def _sftp_mkdir_p(sftp, remote_dir: str) -> None:
    parts = [p for p in remote_dir.split("/") if p]
    cur = "/" if remote_dir.startswith("/") else "."
    for p in parts:
        cur = f"{cur.rstrip('/')}/{p}" if cur != "/" else f"/{p}"
        try:
            sftp.stat(cur)
        except Exception:
            sftp.mkdir(cur)


def _upload_and_cleanup_remote(
    host: str,
    user: str,
    key_file: str,
    port: int,
    local_file: Path,
    remote_dir: str,
    keep_days: int,
    pattern: str = DEFAULT_PATTERN,
) -> None:
    try:
        import paramiko
    except Exception as e:
        raise RuntimeError(
            "Paramiko not installed. Install with: pip install paramiko"
        ) from e

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            key_filename=key_file,
            look_for_keys=False,
            allow_agent=False,
            timeout=20,
        )
        sftp = client.open_sftp()
        try:
            _sftp_mkdir_p(sftp, remote_dir)

            remote_file = f"{remote_dir.rstrip('/')}/{local_file.name}"
            sftp.put(str(local_file), remote_file)

            if keep_days >= 0:
                cutoff = datetime.now().timestamp() - (keep_days * 86400)
                for entry in sftp.listdir_attr(remote_dir):
                    if not fnmatch.fnmatch(entry.filename, pattern):
                        continue
                    if entry.st_mtime < cutoff:
                        old_path = f"{remote_dir.rstrip('/')}/{entry.filename}"
                        try:
                            sftp.remove(old_path)
                        except Exception:
                            pass
        finally:
            sftp.close()
    finally:
        client.close()


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
        write_status(6, str(e))
        return 6

    if not cfg.get("enabled", True):
        print("Backup is disabled in backup_config.json (enabled=false).")
        write_status(0, "Backup skipped because enabled=false")
        return 0

    db_path = Path(get_db_path())
    if not db_path.exists():
        print(f"Database file not found: {db_path}", file=sys.stderr)
        write_status(2, f"Database file not found: {db_path}")
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
        write_status(
            0,
            "Dry run completed",
            {"local_backup": str(backup_path), "local_removed": local_removed},
        )
        return 0

    host = (cfg.get("ec2_host") or "").strip()
    user = (cfg.get("ec2_user") or "").strip()
    key_file = resolve_ssh_key_file(cfg)
    remote_dir = (cfg.get("remote_backup_dir") or "").strip()
    port = int(cfg.get("ssh_port", 22))

    if not all([host, user, key_file, remote_dir]):
        print("Missing EC2/SSH config in backup_config.json.", file=sys.stderr)
        write_status(3, "Missing EC2/SSH config in backup_config.json.")
        return 3
    if not Path(key_file).exists():
        print(f"SSH key file not found: {key_file}", file=sys.stderr)
        write_status(4, f"SSH key file not found: {key_file}")
        return 4

    try:
        _upload_and_cleanup_remote(
            host=host,
            user=user,
            key_file=key_file,
            port=port,
            local_file=backup_path,
            remote_dir=remote_dir,
            keep_days=keep_remote_days,
        )
    except Exception as e:
        print("Backup upload failed.", file=sys.stderr)
        print(str(e), file=sys.stderr)
        write_status(
            5,
            f"Backup upload failed: {e}",
            {"local_backup": str(backup_path), "ssh_key_file": key_file},
        )
        return 5

    print("EC2 upload completed.")
    print(f"Remote cleanup done (kept last {keep_remote_days} days).")
    write_status(
        0,
        "EC2 upload completed.",
        {
            "local_backup": str(backup_path),
            "remote_backup_dir": remote_dir,
            "ssh_key_file": key_file,
            "local_removed": local_removed,
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily DB backup and push to AWS EC2")
    parser.add_argument("--dry-run", action="store_true", help="Create local backup only, skip EC2 upload/cleanup")
    args = parser.parse_args()
    return run_backup(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

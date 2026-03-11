import threading
import time
import socket
import sys
import json
import os
from datetime import date
from pathlib import Path

from app import app
from db import app_data_dir

# pywebview winforms backend may access this key directly.
# Ensure it exists to avoid KeyError in packaged Windows runs.
os.environ.setdefault("WEBVIEW2_RUNTIME_PATH", "")

import webview

HOST = "127.0.0.1"


def get_free_port(host=HOST):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))  # 0 => any free port
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for_port(host, port, timeout=10.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def ensure_single_instance(host="127.0.0.1", port=45454):
    """
    Prevent double-launch.
    Keep returned socket open for app lifetime.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return s
    except OSError:
        sys.exit(0)


def run_server(host, port):
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


def start_webview_safe():
    """
    Prefer Edge Chromium backend, but avoid hard crash if backend/env is broken.
    """
    try:
        webview.start(gui="edgechromium")
    except KeyError as e:
        if str(e).strip("'") == "WEBVIEW2_RUNTIME_PATH":
            os.environ["WEBVIEW2_RUNTIME_PATH"] = ""
            webview.start()
        else:
            raise
    except Exception:
        webview.start()


def _backup_state_file() -> Path:
    return Path(app_data_dir()) / "backup_state.json"


def _already_backed_up_today() -> bool:
    p = _backup_state_file()
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("last_success_date") == date.today().isoformat()


def _mark_backup_success_today() -> None:
    p = _backup_state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"last_success_date": date.today().isoformat()}, indent=2),
        encoding="utf-8",
    )


def _run_daily_backup_async():
    def _worker():
        try:
            from db_backup_to_ec2 import run_backup
            code = run_backup(dry_run=False)
            if code == 0:
                _mark_backup_success_today()
            else:
                print(
                    f"[backup] failed with code={code}. "
                    f"See {Path(app_data_dir()) / 'backup_status.json'}",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[backup] failed: {e}", file=sys.stderr)

    if _already_backed_up_today():
        return
    threading.Thread(target=_worker, daemon=True).start()


if __name__ == "__main__":
    _lock = ensure_single_instance()
    PORT = get_free_port()
    _run_daily_backup_async()

    # ✅ REQUIRED FOR PDF / CSV / EXCEL DOWNLOADS
    # Do not replace settings dict (pywebview expects other keys to exist).
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["WEBVIEW2_RUNTIME_PATH"] = os.environ.get("WEBVIEW2_RUNTIME_PATH", "")

    t = threading.Thread(target=run_server, args=(HOST, PORT), daemon=True)
    t.start()

    if not wait_for_port(HOST, PORT, timeout=15.0):
        webview.create_window(
            "ELTA Workshop Suite",
            html="<h3>Server failed to start.</h3>"
        )
        start_webview_safe()
    else:
        webview.create_window(
            "ELTA Workshop Suite",
            f"http://{HOST}:{PORT}",
            width=1200,
            height=800,
        )
        start_webview_safe()

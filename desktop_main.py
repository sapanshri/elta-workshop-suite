import threading
import time
import socket
import sys
import webview

from app import app

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


if __name__ == "__main__":
    _lock = ensure_single_instance()
    PORT = get_free_port()

    # ✅ REQUIRED FOR PDF / CSV / EXCEL DOWNLOADS
    webview.settings = {
        "ALLOW_DOWNLOADS": True,
    }

    t = threading.Thread(target=run_server, args=(HOST, PORT), daemon=True)
    t.start()

    if not wait_for_port(HOST, PORT, timeout=15.0):
        webview.create_window(
            "ELTA Workshop Suite",
            html="<h3>Server failed to start.</h3>"
        )
        webview.start(gui="edgechromium")
    else:
        webview.create_window(
            "ELTA Workshop Suite",
            f"http://{HOST}:{PORT}",
            width=1200,
            height=800,
        )
        webview.start(gui="edgechromium")


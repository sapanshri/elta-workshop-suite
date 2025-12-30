import threading
import time
import socket

import webview
from waitress import serve

# Import your Flask app object
from app import app  # <-- change if your file is named differently


def wait_for_port(host: str, port: int, timeout=10.0):
    """Wait until the server is accepting TCP connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run_server():
    # IMPORTANT: waitress is stable for EXEs
    serve(app, host="127.0.0.1", port=5000, threads=8)


if __name__ == "__main__":
    # Start server in background
    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    # Wait until server is live
    ok = wait_for_port("127.0.0.1", 5000, timeout=15.0)
    url = "http://127.0.0.1:5000"

    # Create desktop window (no external browser)
    # If server didn't start, show a simple error page instead of blank window.
    if ok:
        webview.create_window("ELTA Workshop Suite", url, width=1200, height=800)
    else:
        webview.create_window(
            "ELTA Workshop Suite - Error",
            html="<h2>Server did not start</h2><p>Port 5000 may be busy or app crashed.</p>",
            width=900,
            height=500,
        )

    webview.start()


import threading
import time
import socket
import webview

from app import app  # imports your Flask "app" instance

HOST = "127.0.0.1"
PORT = 5000

def wait_for_port(host, port, timeout=15.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False

def run_server():
    # Use waitress for stable EXE behavior (no Flask dev server quirks)
    from waitress import serve
    serve(app, host=HOST, port=PORT, threads=8)

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    if not wait_for_port(HOST, PORT, timeout=15.0):
        webview.create_window(
            "ELTA Workshop Suite",
            html="<h3>Server failed to start.</h3><p>Port may be busy or app crashed.</p>"
        )
        webview.start()
    else:
        webview.create_window(
            "ELTA Workshop Suite",
            f"http://{HOST}:{PORT}",
            width=1200,
            height=800
        )
        webview.start()


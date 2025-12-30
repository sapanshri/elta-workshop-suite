import os, sys, webbrowser
from threading import Timer
from license import load_license
from app import app
import traceback, os
from datetime import datetime

def log_crash(e):
    logdir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ELTA_Workshop_Suite")
    os.makedirs(logdir, exist_ok=True)
    with open(os.path.join(logdir, "crash.log"), "a", encoding="utf-8") as f:
        f.write("\n" + "="*60 + "\n")
        f.write(str(datetime.now()) + "\n")
        f.write(traceback.format_exc() + "\n")

if __name__ == "__main__":
    try:
        from app import app
        app.run(host="127.0.0.1", port=5000)
    except Exception as e:
        log_crash(e)
        raise


def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

lic, err = load_license()
if err:
    app.config["LICENSE_ERROR"] = err
else:
    app.config["LICENSE_OK"] = True

Timer(1, open_browser).start()
app.run(host="127.0.0.1", port=5000)


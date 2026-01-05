import webbrowser
import threading
import time
from flask import Flask, render_template, request, redirect
from db import init_db
from modules.tools import tools_bp
from modules.holders import holders_bp
from modules.collets import collets_bp
from modules.inserts import inserts_bp
from modules.gauges import gauges_bp
from modules.customers import customers_bp
from modules.materials import materials_bp
from modules.item_codes import item_codes_bp
from modules.shift_production import shift_bp
from modules.machines import machines_bp
from modules.maintenance import maintenance_bp
from modules.breakdown import breakdown_bp
from modules.machine_history import machine_history_bp
from modules.complaints import complaints_bp

import config
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "uploads" / "ppap"   # change if you want

os.makedirs(UPLOAD_ROOT, exist_ok=True)

app = Flask(__name__)

import os
from pathlib import Path
from appdirs import user_data_dir

APP_NAME = "ELTA_Workshop"
data_dir = Path(user_data_dir(APP_NAME))
UPLOAD_ROOT = data_dir / "uploads" / "ppap"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

app.config["PPAP_UPLOAD_DIR"] = str(UPLOAD_ROOT)


app.config["PPAP_UPLOAD_DIR"] = str(UPLOAD_ROOT)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

app.config["ADMIN_PIN"] = config.ADMIN_PIN
app.config["ADMIN_PIN_1"] = config.ADMIN_PIN_1
app.config["ADMIN_PIN_2"] = config.ADMIN_PIN_2

ALLOWED_EXT = {".pdf", ".xlsx", ".xls", ".docx", ".doc", ".png", ".jpg", ".jpeg"}

def allowed_file(filename: str) -> bool:
    from pathlib import Path
    return Path(filename).suffix.lower() in ALLOWED_EXT

init_db()

@app.route("/")
def home():
    if app.config.get("LICENSE_ERROR"):
        return render_template("license.html", error=app.config["LICENSE_ERROR"])
    return render_template("home.html")

def open_browser():
    time.sleep(1.5)  # give Flask time to start
    webbrowser.open("http://127.0.0.1:5000", new=2)

app.register_blueprint(tools_bp)
app.register_blueprint(holders_bp)
app.register_blueprint(collets_bp)
app.register_blueprint(inserts_bp)
app.register_blueprint(gauges_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(item_codes_bp)
app.register_blueprint(shift_bp)
app.register_blueprint(machines_bp)
app.register_blueprint(maintenance_bp)
app.register_blueprint(breakdown_bp)
app.register_blueprint(machine_history_bp)
app.register_blueprint(complaints_bp)

if __name__ == "__main__":
    # Start browser in a background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Run Flask (NO debug mode in EXE)
    app.run(host="127.0.0.1", port=5000, debug=False)


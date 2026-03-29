#app.py
import os
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, render_template, request, redirect, session, url_for
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
from modules.public_inventory import public_inventory_bp, is_public_host, render_public_home

import config
from db import app_data_dir
from auth_manager import verify_user, role_can_access, module_for_path

app = Flask(__name__)
app.secret_key = os.environ.get("ELTA_SECRET_KEY", "elta-change-me-secret")

UPLOAD_ROOT = Path(app_data_dir()) / "uploads" / "ppap"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

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

PUBLIC_PATHS = {
    "/login",
    "/material-inventory",
    "/public/material-inventory",
    "/machine-report",
    "/machine-report/excel",
    "/client-dashboard",
    "/rfq-submit",
    "/robots.txt",
    "/sitemap.xml",
}
PUBLIC_PREFIXES = ("/services/",)


@app.before_request
def enforce_auth():
    path = request.path or "/"

    if path.startswith("/static/"):
        return
    if path == "/" and is_public_host(request.host):
        return
    if any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
        return
    if path in PUBLIC_PATHS:
        return

    username = session.get("username")
    role = session.get("role")

    if not username or not role:
        return redirect(url_for("login", next=path))

    module_key = module_for_path(path)
    if module_key and not role_can_access(role, module_key):
        return render_template("access_denied.html", module_key=module_key), 403


@app.context_processor
def inject_auth_context():
    role = session.get("role")
    return {
        "current_user": session.get("username"),
        "current_role": role,
        "can_access": lambda module_key: role_can_access(role, module_key),
    }


@app.template_filter("datetimeformat")
def datetimeformat_filter(value):
    if not value:
        return ""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(value)).strftime("%d-%m-%Y %I:%M %p")
    except Exception:
        return str(value)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and session.get("username"):
        return redirect("/")

    error = ""
    next_url = request.values.get("next", "/")
    if not next_url.startswith("/"):
        next_url = "/"
    if urlparse(next_url).netloc:
        next_url = "/"

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = verify_user(username, password)
        if user:
            session.clear()
            session["username"] = username
            session["role"] = user.get("role")
            return redirect(next_url or "/")
        error = "Invalid username or password"

    return render_template("login.html", error=error, next_url=next_url)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def home():
    if is_public_host(request.host):
        return render_public_home()
    if app.config.get("LICENSE_ERROR"):
        return render_template("license.html", error=app.config["LICENSE_ERROR"])
    return render_template("home.html")

#def open_browser():
#    time.sleep(1.5)  # give Flask time to start
#    webbrowser.open("http://127.0.0.1:5000", new=2)

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
app.register_blueprint(public_inventory_bp)

if __name__ == "__main__":
    # Start browser in a background thread
    #threading.Thread(target=open_browser, daemon=True).start()

    # Run Flask (NO debug mode in EXE)
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

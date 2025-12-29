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

app = Flask(__name__)

app.config["ADMIN_PIN"] = config.ADMIN_PIN
app.config["ADMIN_PIN_1"] = config.ADMIN_PIN_1
app.config["ADMIN_PIN_2"] = config.ADMIN_PIN_2

init_db()

@app.route("/")
def home():
    if app.config.get("LICENSE_ERROR"):
        return render_template("license.html", error=app.config["LICENSE_ERROR"])
    return render_template("home.html")

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


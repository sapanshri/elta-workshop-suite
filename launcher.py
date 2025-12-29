import os, sys, webbrowser
from threading import Timer
from license import load_license
from app import app

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

lic, err = load_license()
if err:
    app.config["LICENSE_ERROR"] = err
else:
    app.config["LICENSE_OK"] = True

Timer(1, open_browser).start()
app.run(host="127.0.0.1", port=5000)


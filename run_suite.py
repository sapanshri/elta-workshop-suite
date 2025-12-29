
import sys, os
from app import app

if __name__ == "__main__":
    # IMPORTANT: host=0.0.0.0 lets LAN access if needed
    app.run(host="127.0.0.1", port=5000, debug=False)


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static")
)


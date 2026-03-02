import json
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash


AUTH_FILE = Path(__file__).with_name("auth_roles.json")

_CACHE: dict[str, Any] = {"mtime": None, "data": None}


PATH_MODULE_MAP = [
    ("/tools", "tool_crib"),
    ("/holders", "tool_crib"),
    ("/collets", "tool_crib"),
    ("/inserts", "tool_crib"),
    ("/gauges", "quality"),
    ("/complaints", "quality"),
    ("/materials", "material"),
    ("/shift", "production"),
    ("/maintenance", "maintenance"),
    ("/breakdown", "maintenance"),
    ("/machine-history", "maintenance"),
    ("/customers", "masters"),
    ("/item-codes", "masters"),
    ("/machines", "masters"),
]


def _default_auth_data() -> dict[str, Any]:
    return {
        "roles": {
            "Admin": ["*"],
            "Production": ["dashboard", "tool_crib", "material", "production", "maintenance"],
            "Quality": ["dashboard", "quality", "masters"],
            "Management": [
                "dashboard",
                "tool_crib",
                "quality",
                "material",
                "production",
                "maintenance",
                "masters",
            ],
        },
        "users": {
            "admin": {"password": "admin123", "role": "Admin"},
            "production": {"password": "prod123", "role": "Production"},
            "quality": {"password": "quality123", "role": "Quality"},
            "management": {"password": "mgmt123", "role": "Management"},
        },
    }


def load_auth_data() -> dict[str, Any]:
    if not AUTH_FILE.exists():
        data = _default_auth_data()
        AUTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _CACHE["mtime"] = AUTH_FILE.stat().st_mtime
        _CACHE["data"] = data
        return data

    mtime = AUTH_FILE.stat().st_mtime
    if _CACHE["data"] is not None and _CACHE["mtime"] == mtime:
        return _CACHE["data"]

    with AUTH_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("roles", {})
    data.setdefault("users", {})

    _CACHE["mtime"] = mtime
    _CACHE["data"] = data
    return data


def get_user(username: str) -> dict[str, Any] | None:
    data = load_auth_data()
    users = data.get("users", {})
    if isinstance(users, dict):
        return users.get(username)
    return None


def verify_user(username: str, password: str) -> dict[str, Any] | None:
    user = get_user(username)
    if not user:
        return None

    pwd_hash = (user.get("password_hash") or "").strip()
    plain_pwd = (user.get("password") or "").strip()
    ok = False

    if pwd_hash:
        ok = check_password_hash(pwd_hash, password)
    else:
        ok = plain_pwd == password

    if not ok:
        return None

    return user


def role_can_access(role: str | None, module_key: str) -> bool:
    if not role:
        return False
    roles = load_auth_data().get("roles", {})
    allowed = roles.get(role, [])
    return "*" in allowed or module_key in allowed


def module_for_path(path: str) -> str | None:
    if path == "/":
        return "dashboard"
    for prefix, module_key in PATH_MODULE_MAP:
        if path == prefix or path.startswith(prefix + "/"):
            return module_key
    return None

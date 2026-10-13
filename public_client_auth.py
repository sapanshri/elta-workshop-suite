import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, session, url_for

from db import app_data_dir


public_client_auth_bp = Blueprint("public_client_auth", __name__)

CONFIG_FILE_NAME = "public_client_auth.json"
CONFIG_EXAMPLE_FILE = Path(__file__).with_name("public_client_auth.json.example")
PROTECTED_CLIENT_PATHS = {
    "/client-dashboard",
    "/material-inventory",
    "/public/material-inventory",
    "/machine-report",
    "/machine-report/excel",
}


def _default_config() -> dict:
    return {
        "enabled": True,
        "google_client_id": "",
        "google_client_secret": "",
        "redirect_uri": "https://www.eltaengineering.com/client-auth/google/callback",
        "allowed_emails": ["sapanshri@gmail.com"],
    }


def public_client_config_path() -> Path:
    return Path(app_data_dir()) / CONFIG_FILE_NAME


def load_public_client_auth_config() -> dict:
    path = public_client_config_path()
    if not path.exists():
        data = _default_config()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = _default_config()

    defaults = _default_config()
    for key, value in defaults.items():
        data.setdefault(key, value)
    if not isinstance(data.get("allowed_emails"), list):
        data["allowed_emails"] = defaults["allowed_emails"]
    return data


def _allowed_emails(config: dict | None = None) -> set[str]:
    config = config or load_public_client_auth_config()
    return {
        str(email).strip().lower()
        for email in config.get("allowed_emails", [])
        if str(email).strip()
    }


def public_client_email() -> str:
    return (session.get("public_client_email") or "").strip().lower()


def public_client_is_authenticated() -> bool:
    email = public_client_email()
    if not email:
        return False
    return email in _allowed_emails()


def public_client_auth_is_configured(config: dict | None = None) -> bool:
    config = config or load_public_client_auth_config()
    return bool(
        config.get("enabled")
        and str(config.get("google_client_id") or "").strip()
        and str(config.get("google_client_secret") or "").strip()
    )


def _safe_next_url(value: str | None) -> str:
    next_url = (value or "/client-dashboard").strip()
    parsed = urllib.parse.urlparse(next_url)
    if parsed.netloc or not next_url.startswith("/"):
        return "/client-dashboard"
    return next_url


def _redirect_uri(config: dict) -> str:
    configured = (config.get("redirect_uri") or "").strip()
    if configured:
        return configured
    scheme = "https" if request.host.split(":", 1)[0] in {"eltaengineering.com", "www.eltaengineering.com"} else request.scheme
    return url_for("public_client_auth.google_callback", _external=True, _scheme=scheme)


def _exchange_code_for_token(config: dict, code: str) -> dict:
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": config["google_client_id"],
            "client_secret": config["google_client_secret"],
            "redirect_uri": _redirect_uri(config),
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_google_userinfo(access_token: str) -> dict:
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


@public_client_auth_bp.route("/client-login")
def client_login():
    next_url = _safe_next_url(request.args.get("next"))
    if public_client_is_authenticated():
        return redirect(next_url)

    config = load_public_client_auth_config()
    return render_template(
        "public_client_login.html",
        next_url=next_url,
        config_ready=public_client_auth_is_configured(config),
        config_path=str(public_client_config_path()),
        error=request.args.get("error", ""),
    )


@public_client_auth_bp.route("/client-auth/google/start")
def google_start():
    next_url = _safe_next_url(request.args.get("next"))
    config = load_public_client_auth_config()
    if not public_client_auth_is_configured(config):
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="Google login is not configured yet."))

    state = secrets.token_urlsafe(32)
    session["public_client_oauth_state"] = state
    session["public_client_oauth_next"] = next_url

    params = urllib.parse.urlencode(
        {
            "client_id": config["google_client_id"],
            "redirect_uri": _redirect_uri(config),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@public_client_auth_bp.route("/client-auth/google/callback")
def google_callback():
    expected_state = session.pop("public_client_oauth_state", "")
    next_url = _safe_next_url(session.pop("public_client_oauth_next", "/client-dashboard"))
    received_state = request.args.get("state", "")
    if not expected_state or received_state != expected_state:
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="Google login state check failed."))

    if request.args.get("error"):
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="Google login was cancelled."))

    code = request.args.get("code", "")
    if not code:
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="Google did not return an authorization code."))

    config = load_public_client_auth_config()
    try:
        token_data = _exchange_code_for_token(config, code)
        userinfo = _load_google_userinfo(token_data.get("access_token", ""))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, KeyError):
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="Google login could not be completed."))

    email = (userinfo.get("email") or "").strip().lower()
    verified = userinfo.get("email_verified")
    if verified not in (True, "true", "True", "1", 1):
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="Google email is not verified."))

    if email not in _allowed_emails(config):
        return redirect(url_for("public_client_auth.client_login", next=next_url, error="This Google account is not allowed for the client dashboard."))

    session["public_client_email"] = email
    session["public_client_name"] = userinfo.get("name", "")
    return redirect(next_url)


@public_client_auth_bp.route("/client-logout")
def client_logout():
    for key in ("public_client_email", "public_client_name", "public_client_oauth_state", "public_client_oauth_next"):
        session.pop(key, None)
    return redirect("/")

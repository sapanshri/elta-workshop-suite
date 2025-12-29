import json, os, hashlib, datetime, uuid

def get_license_path():
    if os.name == "nt":  # Windows
        base = os.getenv("PROGRAMDATA", "C:\\ProgramData")
    else:  # Linux / macOS
        base = os.path.expanduser("~/.local/share")
    return os.path.join(base, "EltaWorkshop", "license.key")

LICENSE_PATH = get_license_path()

def machine_hash():
    return hashlib.sha256(
        (str(uuid.getnode())).encode()
    ).hexdigest()

def load_license():
    if not os.path.exists(LICENSE_PATH):
        return None, "License file missing"

    with open(LICENSE_PATH) as f:
        lic = json.load(f)

    if lic["machine_hash"] != machine_hash():
        return None, "License not valid for this machine"

    expiry = datetime.date.fromisoformat(lic["expiry"])
    if datetime.date.today() > expiry:
        return None, "License expired"

    return lic, None


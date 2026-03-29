import csv
import gzip
import io
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import smtplib

from flask import Blueprint, Response, abort, current_app, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from db import app_data_dir
from modules.materials import load_inventory_rows
from modules.shift_production import load_machine_report_data, resolve_machine_report_filters


public_inventory_bp = Blueprint("public_inventory", __name__)

PUBLIC_HOSTS = {"eltaengineering.com", "www.eltaengineering.com"}
BACKUP_PATTERN = "workshop_*.db.gz"
RFQ_EMAIL_CONFIG_FILE = Path(__file__).resolve().parent.parent / "rfq_email_config.json"
RFQ_EMAIL_CONFIG_EXAMPLE = Path(__file__).resolve().parent.parent / "rfq_email_config.json.example"
RFQ_ALLOWED_EXTS = {
    ".pdf",
    ".step",
    ".stp",
    ".igs",
    ".iges",
    ".dxf",
    ".dwg",
    ".zip",
    ".rar",
    ".png",
    ".jpg",
    ".jpeg",
}

SITE_CONTACT = {
    "company_name": "ELTA Engineering Services Pvt. Ltd.",
    "email": "info@eltaengineering.com",
    "phone": "0253-2988608",
    "whatsapp_number": "+91 8698778608",
    "whatsapp_url": "https://wa.me/918698778608?text=Hello%20ELTA%20Engineering%2C%20I%20need%20a%20machining%20quote.",
    "linkedin_url": "https://www.linkedin.com/company/elta-engineering-services-pvt-ltd-/",
    "address_line_1": "Plot No-16, Gat No. 466/A/2 Shinde Village Industrial Area",
    "address_line_2": "Nashik - 422102, MH, India",
    "map_query": "ELTA Engineering Nashik",
    "city": "Nashik",
    "region": "Maharashtra",
    "postal_code": "422102",
    "country": "IN",
}

HOME_CONTENT = {
    "nav_links": [
        {"label": "Home", "href": "#top"},
        {"label": "Services", "href": "#services"},
        {"label": "Capabilities", "href": "#capabilities"},
        {"label": "Industries", "href": "#industries"},
        {"label": "About", "href": "#about"},
        {"label": "Contact", "href": "#contact"},
        {"label": "Client Dashboard", "href": "/client-dashboard"},
    ],
    "trust_badges": [
        "CNC Machining",
        "CAD / CAE Support",
        "Prototype to Production",
        "Quality-Focused Delivery",
    ],
    "why_choose": [
        {
            "title": "Engineering-first execution",
            "copy": "Drawing review, manufacturability input, and practical machining decisions are built into the job from the start.",
        },
        {
            "title": "Prototype to production support",
            "copy": "We support development parts, validation batches, and repeat production with the same engineering focus.",
        },
        {
            "title": "Cost-aware manufacturing",
            "copy": "Customers use ELTA when they need machining support that balances quality, lead time, and commercial practicality.",
        },
        {
            "title": "Reliable industrial response",
            "copy": "Clear communication, requirement tracking, and delivery accountability matter as much as spindle time.",
        },
    ],
    "services": [
        {
            "title": "Precision CNC Milling",
            "copy": "Machined components for industrial assemblies, fixtures, tooling, and precision development work.",
            "href": "/services/precision-cnc-machining",
        },
        {
            "title": "Heavy Machining Support",
            "copy": "Capability aligned to larger and tougher parts where rigidity, planning, and process control matter.",
            "href": "/services/heavy-machining",
        },
        {
            "title": "CAD / CAE Engineering Support",
            "copy": "Upstream support for drawing preparation, design interpretation, engineering coordination, and manufacturability review.",
            "href": "/services/cad-cae-support",
        },
        {
            "title": "Prototype Development Components",
            "copy": "Fast-turn parts for product development, fitment trials, and engineering validation.",
            "href": "/services/prototype-development",
        },
        {
            "title": "Production Machined Parts",
            "copy": "Repeatable production support for industrial customers who need dependable supply of machined parts.",
            "href": "/services/production-components",
        },
        {
            "title": "Cost-down Manufacturing Assistance",
            "copy": "Support for material, process, and machining-route decisions aimed at practical cost efficiency.",
            "href": "/services/cost-effective-engineering-support",
        },
    ],
    "capabilities": [
        "Precision CNC machining for development and production components",
        "Engineering-led drawing review and machining planning",
        "Support for ferrous and non-ferrous industrial materials",
        "Part families ranging from prototype work to repeat batch requirements",
        "Fixture, tooling, and special application component support",
        "Coordinated response for RFQs, technical clarifications, and delivery planning",
    ],
    "industries": [
        "Industrial Equipment",
        "Automotive & Ancillaries",
        "Process Plant & Utility Systems",
        "Pumps, Valves & Flow Control",
        "Special Purpose Machines",
        "Energy & Infrastructure",
    ],
    "featured_work": [
        {
            "title": "Development Components",
            "copy": "Tight-timeline machined parts for design validation, test rigs, and pre-production learning cycles.",
            "alt": "Prototype machined component on a CNC machine table",
        },
        {
            "title": "Production Support Parts",
            "copy": "Repeat batch machining for industrial customers who need stable process execution and dependable response.",
            "alt": "Precision machined production parts arranged after manufacturing",
        },
        {
            "title": "Heavy Machined Industrial Parts",
            "copy": "Larger-format machined components where rigidity, setup discipline, and machining strategy drive results.",
            "alt": "Heavy industrial machining setup with metal workpiece",
        },
    ],
    "about_points": [
        "Based in Nashik, India, ELTA Engineering Services Pvt. Ltd. supports industrial customers with machining and engineering-focused manufacturing assistance.",
        "The company’s public positioning combines precision CNC capability, CAD / CAE support, heavy machining readiness, and practical cost-effective execution.",
        "ELTA works with customers who value clear technical response, manufacturability thinking, and dependable part delivery from prototype to production.",
    ],
    "seo_intro": "ELTA Engineering Services Pvt. Ltd. is a precision CNC machining company in Nashik supporting industrial customers with CNC milling, heavy machining, CAD / CAE support, prototype development, and production machined components.",
    "seo_support_points": [
        "Precision CNC machining services in Nashik for industrial customers",
        "Prototype machining services and production machined components from one engineering-focused partner",
        "CAD / CAE engineering support tied to machining feasibility and industrial manufacturing response",
    ],
    "faq": [
        {
            "question": "What machining services does ELTA Engineering provide?",
            "answer": "ELTA Engineering provides precision CNC machining services, prototype machining support, production machined components, heavy machining support, and engineering-led CAD / CAE support for industrial customers.",
        },
        {
            "question": "Can ELTA support prototype to production requirements?",
            "answer": "Yes. ELTA positions itself for prototype development components, validation parts, and repeat production machined components with engineering-focused manufacturing support.",
        },
        {
            "question": "Where is ELTA Engineering located?",
            "answer": "ELTA Engineering Services Pvt. Ltd. is based in Nashik, Maharashtra, India and supports industrial machining and engineering requirements from this manufacturing base.",
        },
    ],
}

SERVICE_PAGES = {
    "precision-cnc-machining": {
        "title": "Precision CNC Machining Services",
        "meta_title": "Precision CNC Machining Services | ELTA Engineering",
        "meta_description": "ELTA Engineering provides precision CNC machining services for industrial customers needing development parts, machined components, and production support from Nashik, India.",
        "primary_keyword": "precision CNC machining services",
        "secondary_keywords": [
            "CNC machining services in Nashik",
            "precision machined components",
            "industrial CNC milling services",
        ],
        "eyebrow": "Precision CNC Machining",
        "headline": "Precision CNC machining support for industrial parts that need dependable execution",
        "intro": "ELTA Engineering supports customers who need machined components with engineering understanding, practical process planning, and accountable execution from requirement review through final part delivery.",
        "points": [
            "Machining support for development parts, fixtures, tooling, and industrial components",
            "Engineering-oriented review before machining starts",
            "Support for low volume, repeat batches, and production planning",
            "Focus on dimensional discipline, finish expectations, and machining practicality",
        ],
        "faq": [
            {
                "question": "What kinds of precision CNC machining services does ELTA provide?",
                "answer": "ELTA provides precision CNC machining services for industrial parts, development components, tooling, fixtures, and production machined components where process control and engineering review matter.",
            },
            {
                "question": "Does ELTA support low volume and batch CNC machining?",
                "answer": "Yes. ELTA supports low volume machining, prototype batches, and production-oriented batch quantities depending on the customer requirement.",
            },
        ],
    },
    "cad-cae-support": {
        "title": "CAD / CAE Engineering Support",
        "meta_title": "CAD / CAE Engineering Support | ELTA Engineering",
        "meta_description": "ELTA Engineering provides CAD / CAE engineering support tied to machining feasibility, drawing interpretation, and engineering-led component development.",
        "primary_keyword": "CAD / CAE engineering support",
        "secondary_keywords": [
            "engineering design support Nashik",
            "manufacturability support",
            "CAD CAE support for machining",
        ],
        "eyebrow": "CAD / CAE Support",
        "headline": "Engineering support that helps manufacturing decisions happen earlier",
        "intro": "ELTA combines machining awareness with CAD / CAE oriented support so customers can move from drawing intent to manufacturable outcomes with fewer surprises later in the cycle.",
        "points": [
            "Drawing review and engineering coordination support",
            "Manufacturability-oriented thinking before machining release",
            "Support for development-stage and production-stage technical communication",
            "Closer alignment between design intent and machining execution",
        ],
        "faq": [
            {
                "question": "How does ELTA’s CAD / CAE support connect with machining?",
                "answer": "ELTA’s CAD / CAE engineering support is positioned around manufacturability understanding, drawing clarity, and coordination that helps machining decisions happen earlier and more cleanly.",
            },
            {
                "question": "Is this only design support or also manufacturing support?",
                "answer": "It is engineering support linked to manufacturing. The value is in aligning design intent, technical communication, and machining practicality.",
            },
        ],
    },
    "heavy-machining": {
        "title": "Heavy Machining Support",
        "meta_title": "Heavy Machining Support | ELTA Engineering",
        "meta_description": "ELTA Engineering supports heavy machining requirements where setup planning, rigidity, and industrial process control are critical.",
        "primary_keyword": "heavy machining services",
        "secondary_keywords": [
            "heavy machined components",
            "industrial heavy machining Nashik",
            "large component machining support",
        ],
        "eyebrow": "Heavy Machining",
        "headline": "Heavy machining support for larger and more demanding industrial components",
        "intro": "Heavy machining jobs demand more planning, setup discipline, and process stability. ELTA positions itself for customers who need practical response on these tougher machining requirements.",
        "points": [
            "Setup-oriented planning for larger industrial parts",
            "Support where rigidity and machining strategy matter",
            "Practical communication on route, sequencing, and execution",
            "Suitable for industrial sectors with rugged component needs",
        ],
        "faq": [
            {
                "question": "What is included in ELTA’s heavy machining support?",
                "answer": "ELTA’s heavy machining support focuses on larger industrial parts where setup planning, rigidity, sequencing, and practical machining strategy are important to execution.",
            },
            {
                "question": "Which industries typically need heavy machining?",
                "answer": "Heavy machining support is relevant to industrial equipment, process systems, infrastructure, special purpose machine, and rugged engineering applications.",
            },
        ],
    },
    "prototype-development": {
        "title": "Prototype Development Components",
        "meta_title": "Prototype Development Components | ELTA Engineering",
        "meta_description": "ELTA Engineering manufactures prototype development components for fitment trials, validation, testing, and pre-production engineering work.",
        "primary_keyword": "prototype machining services",
        "secondary_keywords": [
            "prototype development components",
            "machined prototype parts India",
            "development component machining",
        ],
        "eyebrow": "Prototype Development",
        "headline": "Prototype development components for validation, testing, and design learning",
        "intro": "ELTA supports prototype and development-stage machining where speed, engineering interpretation, and communication are essential to keep product development moving.",
        "points": [
            "Fast-turn support for development and validation components",
            "Suitable for test fixtures, validation parts, and pre-production learning",
            "Engineering-led response where requirements evolve quickly",
            "Bridge support from early development into production planning",
        ],
        "faq": [
            {
                "question": "Can ELTA support prototype machining with evolving requirements?",
                "answer": "Yes. ELTA’s prototype machining support is positioned for development-stage requirements where design learning and technical clarifications continue through the cycle.",
            },
            {
                "question": "What are prototype development components used for?",
                "answer": "Prototype development components are typically used for fitment trials, testing, design validation, pre-production learning, and engineering review.",
            },
        ],
    },
    "production-components": {
        "title": "Production Machined Components",
        "meta_title": "Production Machined Components | ELTA Engineering",
        "meta_description": "ELTA Engineering supports production machined components for industrial customers needing repeat supply, machining consistency, and accountable delivery.",
        "primary_keyword": "production machined components",
        "secondary_keywords": [
            "batch machining services",
            "industrial component manufacturing support",
            "repeat production machining",
        ],
        "eyebrow": "Production Components",
        "headline": "Production machined components with repeatability and practical industrial response",
        "intro": "Production customers need more than one-off machining. ELTA supports repeat batches and production-oriented part supply with attention to continuity, response, and commercial practicality.",
        "points": [
            "Repeat batch support for industrial component supply",
            "Consistent machining approach across production cycles",
            "Support for ongoing customer schedules and quantity planning",
            "Suitable for customers scaling from validation into production",
        ],
        "faq": [
            {
                "question": "Does ELTA support repeat production machined components?",
                "answer": "Yes. ELTA positions itself for repeat production machined components where continuity, process consistency, and reliable industrial response are important.",
            },
            {
                "question": "Can ELTA handle transition from prototype to production?",
                "answer": "Yes. One of ELTA’s strengths is supporting customers as they move from prototype development components into production machined components.",
            },
        ],
    },
    "cost-effective-engineering-support": {
        "title": "Cost-Effective Engineering Support",
        "meta_title": "Cost-Effective Engineering & Manufacturing Support | ELTA Engineering",
        "meta_description": "ELTA Engineering supports customers with cost-effective engineering and manufacturing decisions tied to machining practicality, material choice, and process route review.",
        "primary_keyword": "cost-effective engineering support",
        "secondary_keywords": [
            "cost effective manufacturing support",
            "machining cost-down support",
            "engineering manufacturing support",
        ],
        "eyebrow": "Cost-Effective Support",
        "headline": "Cost-effective engineering and manufacturing support without losing practical quality",
        "intro": "Customers often need support that helps control cost while keeping the part manufacturable and reliable. ELTA positions itself to help with practical decisions around machining route, materials, and execution.",
        "points": [
            "Support for machining-route and process simplification discussions",
            "Material and requirement review with practical manufacturing context",
            "Useful for customers trying to improve commercial viability",
            "Engineering-led thinking aimed at reliable, not superficial, cost reduction",
        ],
        "faq": [
            {
                "question": "What does cost-effective engineering support mean at ELTA?",
                "answer": "It means helping customers review machining route, material choice, and execution decisions so manufacturing remains practical and commercially sensible without superficial cost cutting.",
            },
            {
                "question": "Is this useful only for large production volumes?",
                "answer": "No. Cost-effective engineering support can help both development and production requirements where better planning improves commercial viability.",
            },
        ],
    },
}


def is_public_host(host: str) -> bool:
    hostname = (host or "").split(":", 1)[0].lower()
    return hostname in PUBLIC_HOSTS


def _load_backup_config() -> dict:
    candidates = [
        Path(app_data_dir()) / "backup_config.json",
        Path(__file__).resolve().parent.parent / "backup_config.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return {}


def _backup_source_dir() -> Path | None:
    override = (current_app.config.get("PUBLIC_INVENTORY_BACKUP_DIR") or "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None

    env_path = (os.environ.get("ELTA_PUBLIC_BACKUP_DIR") or "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        return path if path.exists() else None

    cfg = _load_backup_config()
    remote_dir = (cfg.get("remote_backup_dir") or "").strip()
    if remote_dir:
        path = Path(remote_dir).expanduser()
        if path.exists():
            return path

    local_dir = Path(app_data_dir()) / "db_backups"
    if local_dir.exists():
        return local_dir

    return None


def _latest_backup_file() -> Path | None:
    source_dir = _backup_source_dir()
    if source_dir is None:
        return None

    backups = [p for p in source_dir.glob(BACKUP_PATTERN) if p.is_file()]
    if not backups:
        return None
    return max(backups, key=lambda p: p.stat().st_mtime)


def _public_cache_dir() -> Path:
    cache_dir = Path(app_data_dir()) / "public_inventory_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _restore_latest_backup() -> tuple[Path | None, Path | None]:
    backup_file = _latest_backup_file()
    if backup_file is None:
        return None, None

    cache_dir = _public_cache_dir()
    restored_db = cache_dir / "latest_public_inventory.db"
    stamp_file = cache_dir / "latest_public_inventory.stamp"
    current_stamp = f"{backup_file.name}:{int(backup_file.stat().st_mtime)}"

    cached_stamp = ""
    if stamp_file.exists():
        try:
            cached_stamp = stamp_file.read_text(encoding="utf-8").strip()
        except Exception:
            cached_stamp = ""

    if restored_db.exists() and cached_stamp == current_stamp:
        return restored_db, backup_file

    tmp_db = cache_dir / "latest_public_inventory.tmp"
    with gzip.open(backup_file, "rb") as src, tmp_db.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp_db.replace(restored_db)
    stamp_file.write_text(current_stamp, encoding="utf-8")
    return restored_db, backup_file


def _open_public_db() -> tuple[sqlite3.Connection | None, Path | None]:
    restored_db, backup_file = _restore_latest_backup()
    if restored_db is None:
        return None, None

    con = sqlite3.connect(f"file:{restored_db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con, backup_file


def _rfq_upload_dir() -> Path:
    path = Path(app_data_dir()) / "uploads" / "rfq"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _rfq_submission_file() -> Path:
    path = Path(app_data_dir()) / "rfq_submissions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _rfq_notification_log_file() -> Path:
    path = Path(app_data_dir()) / "rfq_notification.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _rfq_allowed(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in RFQ_ALLOWED_EXTS


def _load_rfq_email_config() -> dict:
    app_cfg = Path(app_data_dir()) / "rfq_email_config.json"
    for candidate in (app_cfg, RFQ_EMAIL_CONFIG_FILE):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                return {}

    if RFQ_EMAIL_CONFIG_EXAMPLE.exists() and not app_cfg.exists():
        try:
            shutil.copy2(RFQ_EMAIL_CONFIG_EXAMPLE, app_cfg)
        except Exception:
            pass
    return {}


def _log_rfq_notification(message: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with _rfq_notification_log_file().open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def _send_rfq_email_notification(payload: dict) -> tuple[str, str]:
    cfg = _load_rfq_email_config()
    if not cfg.get("enabled"):
        return "skipped", "Email notification disabled"

    host = (cfg.get("smtp_host") or "").strip()
    port = int(cfg.get("smtp_port", 0) or 0)
    username = (cfg.get("smtp_username") or "").strip()
    password = (cfg.get("smtp_password") or "").strip()
    from_email = (cfg.get("from_email") or username or SITE_CONTACT["email"]).strip()
    to_emails = cfg.get("to_emails") or [SITE_CONTACT["email"]]
    if isinstance(to_emails, str):
        to_emails = [to_emails]
    to_emails = [x.strip() for x in to_emails if str(x).strip()]

    if not host or not port or not from_email or not to_emails:
        return "failed", "Missing SMTP configuration"

    subject = f"{cfg.get('subject_prefix', 'ELTA RFQ')} | {payload.get('company', '')} | {payload.get('requirement_type', '')}"
    body = "\n".join([
        "New RFQ received from the website.",
        "",
        f"Submitted At: {payload.get('submitted_at', '')}",
        f"Name: {payload.get('name', '')}",
        f"Company: {payload.get('company', '')}",
        f"Email: {payload.get('email', '')}",
        f"Phone: {payload.get('phone', '')}",
        f"Requirement Type: {payload.get('requirement_type', '')}",
        f"Material: {payload.get('material', '')}",
        f"Quantity: {payload.get('quantity', '')}",
        f"Message: {payload.get('message', '')}",
        f"Uploaded Drawing: {payload.get('drawing_original_name', '')}",
        f"Stored File: {payload.get('drawing_saved_name', '')}",
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(to_emails)
    msg.set_content(body)

    use_ssl = bool(cfg.get("use_ssl"))
    use_tls = bool(cfg.get("use_tls", not use_ssl))
    timeout = int(cfg.get("timeout_seconds", 25) or 25)

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            if not use_ssl and use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
        return "sent", f"Notification sent to {', '.join(to_emails)}"
    except Exception as exc:
        return "failed", str(exc)


def _homepage_context(form_data=None, errors=None):
    success = (request.args.get("rfq") or "").strip().lower() == "success"
    host = (request.host or "").split(":", 1)[0]
    if is_public_host(request.host):
        site_url = f"https://{host}"
    else:
        site_url = request.url_root.rstrip("/")
    og_image = site_url + url_for("static", filename="img/cnc-bg.jpg")
    schema = {
        "@context": "https://schema.org",
        "@type": ["Organization", "LocalBusiness"],
        "name": SITE_CONTACT["company_name"],
        "url": site_url,
        "image": og_image,
        "email": SITE_CONTACT["email"],
        "telephone": SITE_CONTACT["phone"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": f"{SITE_CONTACT['address_line_1']}, {SITE_CONTACT['address_line_2']}",
            "addressLocality": SITE_CONTACT["city"],
            "addressRegion": SITE_CONTACT["region"],
            "postalCode": SITE_CONTACT["postal_code"],
            "addressCountry": SITE_CONTACT["country"],
        },
    }
    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["answer"],
                },
            }
            for item in HOME_CONTENT["faq"]
        ],
    }
    return {
        "contact": SITE_CONTACT,
        "content": HOME_CONTENT,
        "rfq_success": success,
        "rfq_errors": errors or [],
        "rfq_form": form_data or {},
        "meta_title": "ELTA Engineering | Precision CNC Machining & Engineering Services",
        "meta_description": "ELTA Engineering Services Pvt. Ltd. offers precision CNC machining, prototype development, production components, and engineering support from Nashik, India. Send your RFQ today.",
        "og_image": og_image,
        "canonical_url": site_url + "/",
        "schema_json": json.dumps(schema),
        "faq_schema_json": json.dumps(faq_schema),
    }


def render_public_home(form_data=None, errors=None):
    return render_template(
        "public_home.html",
        **_homepage_context(form_data=form_data, errors=errors),
    )


def keyword_map_rows():
    rows = [
        {
            "page": "/",
            "primary_keyword": "precision CNC machining company in Nashik",
            "secondary_keywords": [
                "precision CNC machining services",
                "engineering services company Nashik",
                "prototype to production machining",
                "CAD / CAE engineering support",
            ],
        }
    ]
    for slug, service in SERVICE_PAGES.items():
        rows.append(
            {
                "page": f"/services/{slug}",
                "primary_keyword": service["primary_keyword"],
                "secondary_keywords": service["secondary_keywords"],
            }
        )
    rows.extend(
        [
            {
                "page": "/client-dashboard",
                "primary_keyword": "client dashboard",
                "secondary_keywords": ["material inventory access", "machine report access"],
            },
            {
                "page": "/material-inventory",
                "primary_keyword": "material inventory dashboard",
                "secondary_keywords": ["customer material inventory", "challan inventory report"],
            },
            {
                "page": "/machine-report",
                "primary_keyword": "machine work report",
                "secondary_keywords": ["machine production report", "shiftwise machine report"],
            },
        ]
    )
    return rows


def _public_site_root() -> str:
    host = (request.host or "").split(":", 1)[0]
    if is_public_host(request.host):
        return f"https://{host}"
    return request.url_root.rstrip("/")


def _save_rfq_submission(form_data, upload_file):
    saved_name = ""
    original_name = ""
    if upload_file and upload_file.filename:
        if not _rfq_allowed(upload_file.filename):
            return None, "Unsupported file type. Upload PDF, STEP, DWG, DXF, IGES, ZIP, PNG, or JPG files."

        original_name = upload_file.filename
        suffix = Path(upload_file.filename).suffix.lower()
        stored_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}{suffix}"
        upload_path = _rfq_upload_dir() / secure_filename(stored_name)
        upload_file.save(upload_path)
        saved_name = upload_path.name

    payload = {
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        "name": form_data.get("name", ""),
        "company": form_data.get("company", ""),
        "email": form_data.get("email", ""),
        "phone": form_data.get("phone", ""),
        "requirement_type": form_data.get("requirement_type", ""),
        "material": form_data.get("material", ""),
        "quantity": form_data.get("quantity", ""),
        "message": form_data.get("message", ""),
        "drawing_original_name": original_name,
        "drawing_saved_name": saved_name,
    }

    notify_status, notify_message = _send_rfq_email_notification(payload)
    payload["notification_status"] = notify_status
    payload["notification_message"] = notify_message
    _log_rfq_notification(f"{notify_status.upper()} | {payload['company']} | {notify_message}")

    with _rfq_submission_file().open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    return payload, ""


def _load_rfq_submissions() -> list[dict]:
    path = _rfq_submission_file()
    if not path.exists():
        return []

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    rows.sort(key=lambda item: item.get("submitted_at", ""), reverse=True)
    return rows


@public_inventory_bp.route("/rfq-submit", methods=["POST"])
def public_rfq_submit():
    form_data = {
        "name": (request.form.get("name") or "").strip(),
        "company": (request.form.get("company") or "").strip(),
        "email": (request.form.get("email") or "").strip(),
        "phone": (request.form.get("phone") or "").strip(),
        "requirement_type": (request.form.get("requirement_type") or "").strip(),
        "material": (request.form.get("material") or "").strip(),
        "quantity": (request.form.get("quantity") or "").strip(),
        "message": (request.form.get("message") or "").strip(),
    }

    errors = []
    for field in ("name", "company", "email", "requirement_type"):
        if not form_data[field]:
            errors.append(f"{field.replace('_', ' ').title()} is required.")

    upload_file = request.files.get("drawing_file")
    if upload_file and upload_file.filename and not _rfq_allowed(upload_file.filename):
        errors.append("Unsupported file type. Upload PDF, STEP, DWG, DXF, IGES, ZIP, PNG, or JPG files.")

    if errors:
        return render_public_home(form_data=form_data, errors=errors), 400

    _, save_error = _save_rfq_submission(form_data, upload_file)
    if save_error:
        return render_public_home(form_data=form_data, errors=[save_error]), 400

    return redirect("/?rfq=success#rfq")


@public_inventory_bp.route("/client-dashboard")
def public_client_dashboard():
    return render_template("public_client_dashboard.html", contact=SITE_CONTACT)


@public_inventory_bp.route("/services/<slug>")
def public_service_page(slug):
    service = SERVICE_PAGES.get(slug)
    if not service:
        abort(404)

    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["answer"],
                },
            }
            for item in service["faq"]
        ],
    }

    return render_template(
        "public_service_page.html",
        service=service,
        contact=SITE_CONTACT,
        canonical_url=_public_site_root() + request.path,
        og_image=_public_site_root() + url_for("static", filename="img/cnc-bg.jpg"),
        faq_schema_json=json.dumps(faq_schema),
    )


@public_inventory_bp.route("/robots.txt")
def public_robots():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /client-dashboard",
        "Disallow: /material-inventory",
        "Disallow: /public/material-inventory",
        "Disallow: /machine-report",
        "Disallow: /admin/",
        f"Sitemap: {_public_site_root()}/sitemap.xml",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@public_inventory_bp.route("/sitemap.xml")
def public_sitemap():
    site_root = _public_site_root()
    urls = [
        "/",
        "/services/precision-cnc-machining",
        "/services/cad-cae-support",
        "/services/heavy-machining",
        "/services/prototype-development",
        "/services/production-components",
        "/services/cost-effective-engineering-support",
    ]
    xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in urls:
        xml.append("  <url>")
        xml.append(f"    <loc>{site_root}{path}</loc>")
        xml.append(f"    <lastmod>{datetime.utcnow().date().isoformat()}</lastmod>")
        xml.append("    <changefreq>weekly</changefreq>")
        xml.append("    <priority>0.8</priority>")
        xml.append("  </url>")
    xml.append("</urlset>")
    return Response("\n".join(xml), mimetype="application/xml")


@public_inventory_bp.route("/admin/rfqs")
def admin_rfq_list():
    if not session.get("username") or not session.get("role"):
        return redirect(url_for("login", next=request.path))

    rows = _load_rfq_submissions()
    return render_template(
        "admin_rfq_list.html",
        rows=rows,
        contact=SITE_CONTACT,
        config_hint=str(Path(app_data_dir()) / "rfq_email_config.json"),
        log_hint=str(_rfq_notification_log_file()),
    )


@public_inventory_bp.route("/admin/rfqs/uploads/<path:filename>")
def admin_rfq_upload(filename):
    if not session.get("username") or not session.get("role"):
        return redirect(url_for("login", next=request.path))

    base = _rfq_upload_dir().resolve()
    target = (base / filename).resolve()
    if base not in target.parents and target != base:
        abort(404)
    if not target.exists() or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=target.name)


@public_inventory_bp.route("/material-inventory")
@public_inventory_bp.route("/public/material-inventory")
def public_material_inventory():
    db, backup_file = _open_public_db()
    if db is None:
        return render_template(
            "public_material_inventory.html",
            rows=[],
            customers=[],
            item_codes=[],
            backup_name="",
            backup_updated_at="",
            load_error="No uploaded backup file was found for public inventory display.",
        )

    try:
        customer_id = request.args.get("customer_id", "")
        item_code = request.args.get("item_code", "")
        status = request.args.get("status", "")
        from_date = request.args.get("from_date", "")
        to_date = request.args.get("to_date", "")

        rows, closed_mode = load_inventory_rows(
            db, customer_id, item_code, status, from_date, to_date
        )
        customers = db.execute(
            """
            SELECT id, customer_name
            FROM customer_master
            ORDER BY customer_name
            """
        ).fetchall()
        item_codes = db.execute(
            """
            SELECT item_code
            FROM item_code_master
            ORDER BY item_code
            """
        ).fetchall()

        updated_at = backup_file.stat().st_mtime if backup_file is not None else ""

        return render_template(
            "public_material_inventory.html",
            rows=rows,
            customers=customers,
            item_codes=item_codes,
            closed_mode=closed_mode,
            backup_name=backup_file.name if backup_file else "",
            backup_updated_at=updated_at,
            load_error="",
            contact=SITE_CONTACT,
        )
    finally:
        db.close()


@public_inventory_bp.route("/machine-report")
def public_machine_report():
    db, backup_file = _open_public_db()
    if db is None:
        return render_template(
            "public_machine_report.html",
            rows=[],
            machines=[],
            summary={"ok_qty": 0, "rej_qty": 0, "total_qty": 0},
            date_range="last_7",
            from_date="",
            to_date="",
            shift="",
            machine_code="",
            backup_name="",
            backup_updated_at="",
            load_error="No uploaded backup file was found for public machine report display.",
            contact=SITE_CONTACT,
        )

    try:
        filters = resolve_machine_report_filters(request.args)
        rows, summary = load_machine_report_data(db, filters)
        machines = db.execute(
            """
            SELECT machine_code, machine_name
            FROM machine_master
            WHERE status='ACTIVE'
            ORDER BY machine_code
            """
        ).fetchall()

        updated_at = backup_file.stat().st_mtime if backup_file is not None else ""

        return render_template(
            "public_machine_report.html",
            rows=rows,
            machines=machines,
            summary=summary,
            date_range=filters["date_range"],
            from_date=filters["from_date"],
            to_date=filters["to_date"],
            shift=filters["shift"],
            machine_code=filters["machine_code"],
            backup_name=backup_file.name if backup_file else "",
            backup_updated_at=updated_at,
            load_error="",
            contact=SITE_CONTACT,
        )
    finally:
        db.close()


@public_inventory_bp.route("/machine-report/excel")
def public_machine_report_excel():
    db, _ = _open_public_db()
    if db is None:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date",
            "Shift",
            "Machine",
            "Machine Name",
            "Item Codes",
            "OK Qty",
            "Reject Qty",
            "Total Qty",
        ])
        data = output.getvalue().encode("utf-8-sig")
        buf = io.BytesIO(data)
        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name="public_machine_report.csv",
            mimetype="text/csv; charset=utf-8",
        )

    try:
        filters = resolve_machine_report_filters(request.args)
        rows, _ = load_machine_report_data(db, filters)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Date",
            "Shift",
            "Machine",
            "Machine Name",
            "Item Codes",
            "OK Qty",
            "Reject Qty",
            "Total Qty",
        ])
        for r in rows:
            writer.writerow([
                r["shift_date"],
                r["shift"],
                r["machine_code"],
                r["machine_name"],
                r["item_codes"] or "",
                r["ok_qty"],
                r["rej_qty"],
                r["total_qty"],
            ])

        data = output.getvalue().encode("utf-8-sig")
        buf = io.BytesIO(data)
        buf.seek(0)

        return send_file(
            buf,
            as_attachment=True,
            download_name="public_machine_report.csv",
            mimetype="text/csv; charset=utf-8",
        )
    finally:
        db.close()

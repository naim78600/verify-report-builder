"""Constants and user settings (never stores the password)."""
from __future__ import annotations

import json
from pathlib import Path

APP_NAME = "Verify Report Builder"

# Production server (taken from the HAR files).
PRODUCTION = {"web": "https://verify.bmapsbd.com", "api": "https://api.verify.bmapsbd.com"}

# Server choices shown in the window. Staging URLs are entered once in the window
# and remembered in the settings file.
SERVER_PRODUCTION = "মূল সাইট (Production)"
SERVER_STAGING = "স্টেজিং (Staging)"
SERVER_CUSTOM = "অন্য সার্ভার (Custom)"
SERVER_CHOICES = [SERVER_PRODUCTION, SERVER_STAGING, SERVER_CUSTOM]

DEFAULT_ORG = "Prime Bank PLC"
DEFAULT_DAYS = 90
DEFAULT_WORKERS = 6      # concurrent detail requests (hard limit MAX_WORKERS)
MAX_WORKERS = 8
PAGE_SIZE_HINT = 50      # the server decides; used only for messages

# File (application) status codes. Labels follow the bank's own report wording.
FILE_STATUS = {
    1: "Created",
    2: "On Going",
    3: "Hold",
    4: "Finished",
    5: "Canceled",
    6: "Submitted",
    7: "Partially Submitted",
    8: "Withdrawn",
}
ALL_FILE_STATUS_CODES = list(FILE_STATUS)

TRIP_STATUS = {
    1: "Created",
    2: "Allocated",
    3: "Started",
    4: "Hold",
    5: "Finished",
    6: "Canceled",
    7: "Inactive",
    8: "Withdrawn",
}

APPLICATION_TYPE = {1: "Loan", 2: "Card", 3: "Merchant", 4: "Case"}

TRIP_TYPE = {
    "HOUSE": "House",
    "OFFICE": "Office",
    "GUARANTOR_HOUSE": "Guarantor House",
    "GUARANTOR_OFFICE": "Guarantor Office",
    "BANK": "Bank",
    "DOCUMENT": "Document",
    "RENTAL": "Rental",
    "CAR_QUATATION": "Car Quatation",
    "PROPERTY": "Property",
    "DOC_SERVICE": "Document Service",
    "DOC_DRCHAMBER": "Dr. Chamber",
    "DOC_TUITION": "Tuition",
}

APPOINTMENT_TYPE = {"PHONE_CALL": "Phone Call", "VISIT_PLACE": "Visit"}

SETTINGS_DIR = Path.home() / ".verify_report_builder"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return base / "VerifyReports"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


SECRET_WORDS = ("password", "passwd", "secret", "token", "pass_")


def save_settings(data: dict) -> None:
    """Persist non-secret settings (merged into what is already saved).  Passwords / tokens are never written."""
    merged = load_settings()
    merged.update(data)
    merged = {k: v for k, v in merged.items() if not any(w in k.lower() for w in SECRET_WORDS)}
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def derive_api_url(web_url: str) -> str:
    """https://host -> https://api.host (the pattern used by the production site)."""
    web_url = web_url.rstrip("/")
    scheme, _, host = web_url.partition("://")
    bare = host.split("/")[0].split(":")[0]
    if bare == "localhost" or bare.replace(".", "").isdigit() or host.startswith("api."):
        return web_url                      # IP / localhost / already an api host: use as is
    return f"{scheme}://api.{host}"

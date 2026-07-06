"""
services/db_helpers.py  –  Small DB session + serialization utilities reused
across multiple route blueprints.
"""

import os
import re
from datetime import date, datetime

from flask import current_app
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import joinedload

from auth import Role
from database import Report, ReportStatus, User, db
from services.audit import audit_logger

# Date input formats we accept at the form boundary. The HTML
# <input type="date"> control always submits ISO (%Y-%m-%d); the other
# formats are kept so the legacy admin form / API clients keep working.
_DOB_INPUT_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y")


def parse_dob(value: str | None) -> date | None:
    """Parse a date-of-birth string into a `datetime.date`, else None.

    Returns None for empty input and silently rejects values in the
    future (`dob > today` is never a valid birthdate).
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in _DOB_INPUT_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
            if parsed > date.today():
                return None
            return parsed
        except ValueError:
            continue
    return None


def compute_age(dob: date | None) -> int | None:
    """Return integer age in years from a date-of-birth, or None."""
    if dob is None:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

# Free-text fields rendered into HTML or sent to the LLM must reject control
# characters (which can break the audit log format or inject prompt-shaped
# tokens). Allow common punctuation and unicode letters/digits.
_PRINTABLE_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Tokens used by LLMs to mark role boundaries — stripping them from user
# input prevents the simplest prompt-injection payloads from re-roling the
# conversation. Not a complete defence; pair with structured prompts.
_PROMPT_INJECTION_TOKENS = re.compile(
    r"^\s*(system|assistant|user)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


PASSWORD_MIN_LEN = 4


def sanitize_log_value(value: str) -> str:
    """Collapse newlines/control chars so a hostile value can't fake a log line."""
    return _PRINTABLE_RE.sub("", str(value)).replace("\n", "\\n").replace("\r", "\\r")


def sanitize_chat_message(message: str, max_len: int = 1000) -> str:
    """Light-weight defence against prompt injection in /api/chat.

    Removes control characters and role-boundary tokens, then truncates.
    Real defence-in-depth requires sending the user turn as a separate
    structured message to the model — this just stops the cheapest attacks.
    """
    if not message:
        return ""
    cleaned = _PRINTABLE_RE.sub("", message)
    cleaned = _PROMPT_INJECTION_TOKENS.sub("", cleaned)
    cleaned = cleaned.strip()
    return cleaned[:max_len]


_DIAGNOSIS_ALLOWED = re.compile(r"^[\w\s,.\-?!:;()/%+]+$", re.UNICODE)


def validate_final_diagnosis(text: str, max_len: int = 500) -> tuple[str | None, str | None]:
    """Validate doctor-supplied diagnosis text.

    Returns (cleaned_value, error_message). Either may be None: success
    yields (cleaned, None); failure yields (None, error).
    """
    cleaned = _PRINTABLE_RE.sub("", text or "").strip()
    if not cleaned:
        return "", None
    if len(cleaned) > max_len:
        return None, f"Diagnosis text must be {max_len} characters or fewer."
    if not _DIAGNOSIS_ALLOWED.match(cleaned):
        return None, (
            "Diagnosis text contains unsupported characters. "
            "Use letters, numbers, and basic punctuation only."
        )
    return cleaned, None


def validate_password(password: str) -> str | None:
    """Return an error message if the password is too weak, else None.

    Policy: ≥4 chars and at least one each of upper, lower, digit. A
    deliberate balance between security and usability for a medical app
    where staff will type these passwords every shift.
    """
    if len(password) < PASSWORD_MIN_LEN:
        return f"Password must be at least {PASSWORD_MIN_LEN} characters long."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one digit."
    return None


def safe_commit(context: str = "") -> bool:
    """Commit the current SQLAlchemy session, rolling back on any failure.

    Returns True on success, False if the commit was rolled back.
    """
    try:
        db.session.commit()
        return True
    except Exception as exc:
        db.session.rollback()
        audit_logger.error(f"DB commit failed{(' – ' + context) if context else ''}: {exc}")
        return False


def reports_query_with_patient():
    """Base Report query with the patient relationship eager-loaded.

    Use this anywhere you intend to render `report.patient.*` — it turns the
    classic N+1 (1 query for reports + 1 per row for the patient) into a
    single SELECT with a JOIN.
    """
    return Report.query.options(joinedload(Report.patient))


def serialize_reports(reports) -> list[dict]:
    """Project a list of Report rows into dicts with patient `full_name` joined."""
    out = []
    for r in reports:
        d = r.to_dict()
        d["full_name"] = r.patient.full_name if r.patient else r.patient_name
        out.append(d)
    return out


def _escape_like(term: str) -> str:
    r"""Escape LIKE wildcards in user-supplied search terms.

    Pairs with `ilike(..., escape="\\")` to keep `%`, `_`, and `\` from
    matching unintended rows or driving a regex-DoS-style pattern.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_user_search(query, term: str):
    """Apply a free-text filter across user fields. Returns the modified query."""
    if not term:
        return query
    term = term[:100]  # cap input length to bound the LIKE pattern cost
    pattern = f"%{_escape_like(term)}%"
    return query.filter(
        db.or_(
            User.full_name.ilike(pattern, escape="\\"),
            User.username.ilike(pattern, escape="\\"),
            User.email.ilike(pattern, escape="\\"),
            User.phone.ilike(pattern, escape="\\"),
            User.role.ilike(pattern, escape="\\"),
        )
    )


def apply_report_search(query, term: str):
    """Apply a free-text / numeric-id filter to a Report query."""
    if not term:
        return query
    term = term[:100]
    pattern = f"%{_escape_like(term)}%"
    if term.isdigit():
        return query.filter(db.or_(
            Report.id == int(term),
            Report.patient_name.ilike(pattern, escape="\\"),
            Report.patient.has(User.full_name.ilike(pattern, escape="\\")),
        ))
    return query.filter(db.or_(
        Report.patient_name.ilike(pattern, escape="\\"),
        Report.patient.has(User.full_name.ilike(pattern, escape="\\")),
    ))


def allowed_file(filename: str) -> bool:
    allowed = current_app.config.get(
        "ALLOWED_EXTENSIONS",
        {"png", "jpg", "jpeg", "bmp", "gif", "tiff", "webp", "dcm"},
    )
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


# Pillow format names → the canonical extensions we accept. Used to confirm
# that the *content* of the upload matches the declared extension and is
# actually an image (not an SVG, HTML doc, or other polyglot file).
_PILLOW_FORMAT_TO_EXT = {
    "JPEG":  {"jpg", "jpeg"},
    "PNG":   {"png"},
    "BMP":   {"bmp"},
    "GIF":   {"gif"},
    "TIFF":  {"tiff"},
    "MPO":   {"jpg", "jpeg"},  # multi-picture JPEG variants
    "WEBP":  {"webp"},
}


def validate_image_file(file_path: str, declared_ext: str) -> str | None:
    """Verify the file parses as an image and matches the claimed extension.

    Returns an error message string on failure, or None on success.
    Pillow's `.verify()` reads headers and a small amount of content; it
    does not fully decode the image, so it's cheap to run on every upload.
    """
    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return "Uploaded file is empty."
    try:
        with Image.open(file_path) as img:
            img.verify()
            detected_format = img.format
    except UnidentifiedImageError:
        return "File is not a recognised image format."
    except Exception:
        # Pillow raises a grab-bag of subclasses for truncation, syntax
        # errors, etc. Treat all of them as "not a usable image".
        return "Uploaded file could not be parsed as an image."

    declared = declared_ext.lower().lstrip(".")
    allowed_for_format = _PILLOW_FORMAT_TO_EXT.get((detected_format or "").upper())
    if not allowed_for_format or declared not in allowed_for_format:
        return (
            "Uploaded file does not match its declared extension "
            f"(got format={detected_format!r}, extension={declared!r})."
        )
    return None


def can_view_report(report, role: str | None, user_id: int | None) -> bool:
    """Authoritative access-control check for medical reports and their images.

    - Patient: only own reports.
    - Doctor:  reports currently in the review queue (PRELIMINARY) plus any
      report the doctor personally approved (history).
    - Secretary / Admin: all reports (job function).
    - Anyone else / unauthenticated: denied.
    """
    if report is None or role is None or user_id is None:
        return False
    if role == Role.PATIENT:
        return report.patient_id == user_id
    if role == Role.DOCTOR:
        return (
            report.status in (ReportStatus.PRELIMINARY, ReportStatus.ERROR)
            or report.approved_by_id == user_id
        )
    if role in (Role.SECRETARY, Role.ADMIN):
        return True
    return False

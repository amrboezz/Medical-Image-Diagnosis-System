"""
seed.py  –  Idempotent demo seeding for MediDiagnostic.

Sets known passwords on the four role accounts (admin / doc / sec / pat),
creating any that are missing, and tops up the demo patient with a few sample
reports (each with a generated placeholder X-ray image) so the patient history
page and chatbot context look populated for a live demo.

SAFE TO RE-RUN. This script never drops tables and never deletes rows:
  * Account passwords are upserted to fixed, known values.
  * Sample reports are only added if the demo patient has fewer than
    TARGET_PATIENT_REPORTS, so re-running does not pile up duplicates.

Writes to the same database the app uses (the live medidiagnostic.db).

Run:  python seed.py
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

from app import create_app
from database import Report, ReportStatus, User, db

# Known demo credentials. They satisfy the app's password policy (>=4 chars,
# at least one upper, one lower, one digit) so they could also be created via
# the admin form.  (username, role, full_name, password)
DEMO_ACCOUNTS = [
    ("admin", "admin",     "System Admin",    "Admin1234"),
    ("doc",   "doctor",    "Dr. Demo Doctor", "Doctor1234"),
    ("sec",   "secretary", "Demo Secretary",  "Secretary1234"),
    ("pat",   "patient",   "Demo Patient",    "Patient1234"),
]

DEMO_PATIENT_USERNAME = "pat"
TARGET_PATIENT_REPORTS = 4

# Interleaved approved/preliminary so a partial top-up still yields a mix.
# (scan_type, ai_result, confidence, status, doctor_notes, age_days)
_SAMPLE_REPORTS = [
    ("Fracture Detection", "No fracture detected", 96.4, ReportStatus.APPROVED,
     "Reviewed: no acute fracture. Findings consistent with a normal study.", 21),
    ("Fracture Detection", "Possible fracture detected", 81.7,
     ReportStatus.PRELIMINARY, None, 2),
    ("Degenerative Knee Diseases", "Osteoarthritis: KL Grade 2. Osteoporosis: Normal.",
     88.1, ReportStatus.APPROVED,
     "Mild osteoarthritis confirmed. Recommend follow-up imaging in 6 months.", 9),
    ("Tumor Detection", "No tumor detected", 93.2, ReportStatus.PRELIMINARY, None, 1),
]


def _placeholder_image(abs_path: str, label: str) -> None:
    """Create a small grayscale placeholder 'X-ray' PNG so the thumbnail and
    image viewer have something to render. Uses Pillow's built-in font."""
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    img = Image.new("RGB", (512, 512), (26, 30, 36))
    draw = ImageDraw.Draw(img)
    draw.ellipse((150, 80, 362, 440), outline=(120, 132, 144), width=6)
    draw.line((256, 110, 256, 410), fill=(150, 162, 174), width=10)
    draw.text((140, 468), f"SAMPLE X-RAY - {label}", fill=(176, 186, 196))
    img.save(abs_path, format="PNG")


def _upsert_accounts() -> list[tuple]:
    """Create-or-update the four role accounts with known passwords."""
    results = []
    for username, role, full_name, password in DEMO_ACCOUNTS:
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(full_name=full_name, username=username, role=role)
            user.set_password(password)
            db.session.add(user)
            action = "created"
        else:
            # Preserve the existing role/name; only (re)set a known password.
            user.set_password(password)
            action = "password reset"
        results.append((role, username, password, action))
    db.session.commit()
    return results


def _top_up_patient_reports(upload_folder: str, doctor_id: int | None) -> tuple[int, int]:
    """Ensure the demo patient has up to TARGET_PATIENT_REPORTS reports."""
    patient = User.query.filter_by(username=DEMO_PATIENT_USERNAME).first()
    if patient is None:
        return 0, 0

    existing = patient.reports.count()
    if existing >= TARGET_PATIENT_REPORTS:
        return existing, 0

    added = 0
    for scan_type, ai_result, conf, status, notes, age_days in (
        _SAMPLE_REPORTS[: TARGET_PATIENT_REPORTS - existing]
    ):
        unique = f"{uuid.uuid4().hex}.png"
        rel_path = f"{patient.id}/{unique}"
        abs_path = os.path.join(upload_folder, str(patient.id), unique)
        _placeholder_image(abs_path, scan_type)

        created = datetime.now(timezone.utc) - timedelta(days=age_days)
        report = Report(
            patient_id=patient.id,
            patient_name=patient.full_name,
            scan_type=scan_type,
            image_path=rel_path,
            ai_result=ai_result,
            ai_confidence=conf,
            status=status,
            doctor_notes=notes,
            created_at=created,
        )
        if status == ReportStatus.APPROVED:
            report.approved_by_id = doctor_id
            report.approved_at = created + timedelta(hours=3)
        db.session.add(report)
        added += 1

    db.session.commit()
    return existing + added, added


def main() -> None:
    app = create_app(preload=False)
    with app.app_context():
        db.create_all()  # creates missing tables only; never drops
        accounts = _upsert_accounts()
        doctor = User.query.filter_by(username="doc").first()
        total, added = _top_up_patient_reports(
            app.config["UPLOAD_FOLDER"], doctor.id if doctor else None
        )

    bar = "=" * 60
    print("\n" + bar)
    print(" MediDiagnostic - demo login credentials")
    print(bar)
    for role, username, password, action in accounts:
        print(f"  {role:10s} username: {username:6s} password: {password:14s} [{action}]")
    print(bar)
    print(
        f"  Demo patient '{DEMO_PATIENT_USERNAME}' now has {total} report(s) "
        f"({added} added this run)."
    )
    print("  Idempotent: safe to run again.")
    print(bar + "\n")


if __name__ == "__main__":
    main()

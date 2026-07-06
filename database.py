"""
database.py  –  Flask-SQLAlchemy models for the MediDiagnostic platform.

The `db` instance is owned by extensions.py and re-exported here so existing
`from database import db` imports continue to work unchanged.
"""

from datetime import datetime, timezone
from enum import Enum

from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db  # noqa: F401 — re-exported for backwards compat


class ReportStatus(str, Enum):
    """Lifecycle states for a Report row.

    Inherits from `str` so existing comparisons against literal strings
    (`report.status == "PRELIMINARY"`, `filter_by(status="APPROVED")`)
    continue to work — the enum members ARE their string values.
    """

    PRELIMINARY = "PRELIMINARY"   # AI ran, awaiting human sign-off
    APPROVED    = "APPROVED"      # Doctor has reviewed and confirmed
    ERROR       = "ERROR"         # AI inference failed; needs manual review


class User(db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    full_name     = db.Column(db.String(120), nullable=False)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20),  nullable=False)   # admin | doctor | secretary | patient
    email         = db.Column(db.String(120), unique=True, nullable=True)
    phone         = db.Column(db.String(30),  nullable=True)
    gender        = db.Column(db.String(20),  nullable=True)
    dob           = db.Column(db.Date,        nullable=True)


    reports = db.relationship("Report", back_populates="patient", lazy="dynamic",
                              foreign_keys="Report.patient_id")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "full_name": self.full_name,
            "username":  self.username,
            "role":      self.role,
            "email":     self.email or "",
            "phone":     self.phone or "",
            "gender":    self.gender or "",
            "dob":       self.dob.isoformat() if self.dob else "",
        }

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


class Report(db.Model):
    __tablename__ = "reports"

    id            = db.Column(db.Integer, primary_key=True)
    patient_id    = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    patient_name  = db.Column(db.String(120), nullable=False)
    scan_type     = db.Column(db.String(80),  nullable=False)
    image_path    = db.Column(db.String(256), nullable=False)
    ai_result     = db.Column(db.String(120), nullable=True)
    ai_confidence = db.Column(db.Float,       nullable=True, default=0.0)
    doctor_notes  = db.Column(db.Text,        nullable=True)
    # native_enum=False emits a VARCHAR(+CHECK) on every backend (SQLite has
    # no native ENUM type). SQLAlchemy still validates the value against
    # ReportStatus at the ORM layer, so a typo like "APROVED" raises.
    status        = db.Column(
        db.Enum(
            ReportStatus,
            name="report_status",
            native_enum=False,    # no native ENUM type on SQLite anyway
            length=30,
            validate_strings=True,  # reject typos like "APROVED" at write time
        ),
        nullable=False,
        default=ReportStatus.PRELIMINARY,
    )
    created_at    = db.Column(db.DateTime,    nullable=False, default=lambda: datetime.now(timezone.utc))

    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at    = db.Column(db.DateTime, nullable=True)

    # Relationship back to the patient User row
    patient = db.relationship("User", back_populates="reports",
                              foreign_keys=[patient_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])

    @property
    def image_basename(self) -> str:
        """Filename portion of image_path (e.g. 'abc123.png' from '5/abc123.png').

        Used by templates building `/uploads_view/<patient_id>/<filename>`
        URLs without having to know the on-disk layout.
        """
        return self.image_path.rsplit("/", 1)[-1] if self.image_path else ""

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "patient_id":     self.patient_id,
            "patient_name":   self.patient_name,
            "scan_type":      self.scan_type,
            "image_path":     self.image_path,
            "image_basename": self.image_basename,
            "ai_result":      self.ai_result,
            "ai_confidence":  round(self.ai_confidence or 0.0, 2),
            "doctor_notes":   self.doctor_notes,
            # status may come out of SQLAlchemy as a ReportStatus member; force
            # the plain string value into the JSON / template payload.
            "status":         self.status.value if isinstance(self.status, ReportStatus) else self.status,
            "created_at":     self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
            "approved_by_id": self.approved_by_id,
            "approved_at":    self.approved_at.strftime("%Y-%m-%d %H:%M") if self.approved_at else "",
        }

    def __repr__(self) -> str:
        return f"<Report #{self.id} patient={self.patient_id} type={self.scan_type} status={self.status}>"

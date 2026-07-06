"""
routes/patient_bp.py  –  Patient dashboard (own reports).
"""

from flask import Blueprint, render_template, session
from flask.typing import ResponseReturnValue

from auth import Role, role_required
from database import Report, User

patient_bp = Blueprint("patient_bp", __name__)


@patient_bp.route("/patient")
@role_required(Role.PATIENT)
def patient_dashboard() -> ResponseReturnValue:
    """Render the patient's own report list and chat widget.

    Access: patient role only. Patients see only their own reports.
    """
    user_id = session["user_id"]
    user = User.query.get(user_id)
    reports = [
        r.to_dict()
        for r in Report.query.filter_by(patient_id=user_id)
                              .order_by(Report.id.desc()).all()
    ]
    latest_report = reports[0] if reports else None
    return render_template(
        "patient.html",
        reports=reports,
        latest_report=latest_report,
        user_name=user.full_name if user else "Patient",
    )

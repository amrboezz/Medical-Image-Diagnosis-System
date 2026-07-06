"""
routes/doctor_bp.py  –  Doctor dashboard and diagnosis approval.
"""

from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue

from auth import Role, role_required
from database import Report, ReportStatus
from services.audit import audit_logger
from services.db_helpers import safe_commit, validate_final_diagnosis

doctor_bp = Blueprint("doctor_bp", __name__)


@doctor_bp.route("/doctor")
@role_required(Role.DOCTOR)
def doctor_dashboard() -> ResponseReturnValue:
    """Render the doctor review queue: PRELIMINARY and ERROR reports.

    Access: doctor role only.
    """

    reports = [
        r.to_dict()
        for r in Report.query.filter(
            Report.status.in_((ReportStatus.PRELIMINARY, ReportStatus.ERROR))
        ).order_by(Report.id.desc()).all()
    ]
    return render_template("doctor.html", reports=reports)


@doctor_bp.route("/update_report", methods=["POST"])
@role_required(Role.DOCTOR)
def update_report() -> ResponseReturnValue:
    """Sign off on a preliminary report.

    POST form: ``report_id``, ``doctor_notes``, optional ``final_diagnosis``
    override, plus the CSRF token. Reports that are not in PRELIMINARY
    status are rejected (already-approved reports cannot be overwritten).

    Access: doctor role only.
    """
    report_id = request.form.get("report_id", type=int)
    doctor_notes = request.form.get("doctor_notes", "").strip()[:2000]
    final_diagnosis_raw = request.form.get("final_diagnosis", "")

    cleaned_diagnosis, diag_error = validate_final_diagnosis(final_diagnosis_raw)
    if diag_error:
        flash(diag_error, "error")
        return redirect(url_for("doctor_bp.doctor_dashboard"))

    report = Report.query.get(report_id)
    if not report:
        flash("Report not found.", "error")
        return redirect(url_for("doctor_bp.doctor_dashboard"))


    if report.status != ReportStatus.PRELIMINARY:
        audit_logger.warning(
            f"SECURITY – doctor_id={session.get('user_id')} attempted to modify "
            f"non-preliminary report_id={report_id} status={report.status}"
        )
        flash("This report has already been approved and cannot be modified.", "error")
        return redirect(url_for("doctor_bp.doctor_dashboard"))

    report.doctor_notes = doctor_notes
    report.status = ReportStatus.APPROVED
    report.approved_by_id = session.get("user_id")
    report.approved_at = datetime.now(timezone.utc)

    if cleaned_diagnosis:
        report.ai_result = cleaned_diagnosis

    if not safe_commit(f"update_report id={report_id}"):
        flash("Could not save the diagnosis due to a database error.", "error")
        return redirect(url_for("doctor_bp.doctor_dashboard"))

    audit_logger.info(
        f"MEDICAL – report_id={report_id} approved by "
        f"doctor_id={report.approved_by_id} (notes_len={len(doctor_notes)}, "
        f"diagnosis_overridden={bool(cleaned_diagnosis)})"
    )
    flash("Diagnosis confirmed and report approved.", "success")
    return redirect(url_for("doctor_bp.doctor_dashboard"))

"""
routes/secretary_bp.py  –  Secretary dashboard (all reports + patient list).
"""

from flask import Blueprint, render_template, request
from flask.typing import ResponseReturnValue

from auth import Role, role_required
from database import Report, User
from services.db_helpers import reports_query_with_patient

secretary_bp = Blueprint("secretary_bp", __name__)

REPORTS_PER_PAGE = 50
PATIENTS_PER_PAGE = 100


@secretary_bp.route("/secretary")
@role_required(Role.SECRETARY)
def secretary_dashboard() -> ResponseReturnValue:
    """Render the secretary console: paginated reports + patient roster.

    Access: secretary role only. Pagination via ``reports_page`` /
    ``patients_page`` query params.
    """
    reports_page = max(1, request.args.get("reports_page", default=1, type=int))
    patients_page = max(1, request.args.get("patients_page", default=1, type=int))

    reports_pagination = (
        reports_query_with_patient()
        .order_by(Report.id.desc())
        .paginate(page=reports_page, per_page=REPORTS_PER_PAGE, error_out=False)
    )
    reports = [r.to_dict() for r in reports_pagination.items]

    patients_pagination = (
        User.query.filter_by(role=Role.PATIENT)
        .order_by(User.id)
        .paginate(page=patients_page, per_page=PATIENTS_PER_PAGE, error_out=False)
    )
    patients = [u.to_dict() for u in patients_pagination.items]

    return render_template(
        "secretary.html",
        reports=reports,
        patients=patients,
        reports_page=reports_page,
        reports_pages=reports_pagination.pages,
        reports_total=reports_pagination.total,
        patients_page=patients_page,
        patients_pages=patients_pagination.pages,
        patients_total=patients_pagination.total,
    )

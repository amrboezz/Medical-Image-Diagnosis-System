"""
routes/admin_bp.py  –  Admin dashboard, user CRUD, and live-search JSON APIs.
"""

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from auth import ALL_ROLES, Role, role_required
from database import Report, ReportStatus, User, db
from services.audit import audit_logger, mem_handler
from services.db_helpers import (
    apply_report_search,
    apply_user_search,
    parse_dob,
    reports_query_with_patient,
    safe_commit,
    serialize_reports,
    validate_password,
)

_ALLOWED_ROLES = ALL_ROLES

# Page sizes are capped server-side; a hostile / curious client cannot
# request 100k rows in one go.
USERS_PER_PAGE = 50
REPORTS_PER_PAGE = 50
MAX_PER_PAGE = 100


def _bounded_per_page(default: int) -> int:
    raw = request.args.get("per_page", type=int) or default
    return max(1, min(raw, MAX_PER_PAGE))

admin_bp = Blueprint("admin_bp", __name__)


@admin_bp.route("/admin")
@role_required(Role.ADMIN)
def admin_dashboard() -> ResponseReturnValue:
    """Render the admin console: paginated users, recent reports, live audit log.

    Query params: ``search`` (user filter), ``reports_search`` (report filter),
    ``users_page`` and ``reports_page`` for pagination.

    Access: admin role only.
    """
    search_query = request.args.get("search", "").strip()
    reports_search = request.args.get("reports_search", "").strip()
    users_page = max(1, request.args.get("users_page", default=1, type=int))
    reports_page = max(1, request.args.get("reports_page", default=1, type=int))

    user_q = apply_user_search(User.query, search_query).order_by(User.id)
    users_pagination = user_q.paginate(
        page=users_page, per_page=USERS_PER_PAGE, error_out=False
    )
    users = [u.to_dict() for u in users_pagination.items]

    report_q = apply_report_search(
        reports_query_with_patient(), reports_search
    ).order_by(Report.id.desc())
    reports_pagination = report_q.paginate(
        page=reports_page, per_page=REPORTS_PER_PAGE, error_out=False
    )
    recent_reports = serialize_reports(reports_pagination.items)

    stats = {
        "total_patients":     User.query.filter_by(role=Role.PATIENT).count(),
        "total_scans":        Report.query.count(),
        "pending_scans":      Report.query.filter_by(status=ReportStatus.PRELIMINARY).count(),
        "completed_scans":    Report.query.filter_by(status=ReportStatus.APPROVED).count(),
        "total_doctors":      User.query.filter_by(role=Role.DOCTOR).count(),
        "total_secretaries":  User.query.filter_by(role=Role.SECRETARY).count(),
        "total_admins":       User.query.filter_by(role=Role.ADMIN).count(),
        "total_processed":    Report.query.count(),
    }

    logs = list(reversed(mem_handler.entries))

    return render_template(
        "admin.html",
        users=users,
        recent_reports=recent_reports,
        stats=stats,
        logs=logs,
        search_query=search_query,
        reports_search=reports_search,
        users_page=users_page,
        users_pages=users_pagination.pages,
        users_total=users_pagination.total,
        reports_page=reports_page,
        reports_pages=reports_pagination.pages,
        reports_total=reports_pagination.total,
    )


@admin_bp.route("/api/admin/logs")
@role_required(Role.ADMIN)
def api_admin_logs() -> ResponseReturnValue:
    """Return the in-memory audit ring (newest first) as JSON for live polling.

    Access: admin role only.
    """
    return jsonify(logs=list(reversed(mem_handler.entries)))


@admin_bp.route("/api/admin/reports")
@role_required(Role.ADMIN)
def api_admin_reports() -> ResponseReturnValue:
    """Return a filtered, paginated report list as JSON for live-search.

    Query params: ``search``, ``page``, ``per_page`` (capped at MAX_PER_PAGE).

    Access: admin role only.
    """
    search_query = request.args.get("search", "").strip()
    page = max(1, request.args.get("page", default=1, type=int))
    per_page = _bounded_per_page(REPORTS_PER_PAGE)

    report_q = apply_report_search(
        reports_query_with_patient(), search_query
    ).order_by(Report.id.desc())
    pagination = report_q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(
        reports=serialize_reports(pagination.items),
        query=search_query,
        page=page,
        pages=pagination.pages,
        total=pagination.total,
    )


@admin_bp.route("/api/admin/users")
@role_required(Role.ADMIN)
def api_admin_users() -> ResponseReturnValue:
    """Return a filtered, paginated user list as JSON for live-search.

    Query params: ``search``, ``page``, ``per_page`` (capped at MAX_PER_PAGE).

    Access: admin role only.
    """
    search_query = request.args.get("search", "").strip()
    page = max(1, request.args.get("page", default=1, type=int))
    per_page = _bounded_per_page(USERS_PER_PAGE)

    user_q = apply_user_search(User.query, search_query).order_by(User.id)
    pagination = user_q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(
        users=[u.to_dict() for u in pagination.items],
        query=search_query,
        page=page,
        pages=pagination.pages,
        total=pagination.total,
    )


@admin_bp.route("/add_user", methods=["POST"])
@role_required(Role.ADMIN)
def add_user() -> ResponseReturnValue:
    """Create a new user account.

    POST form: ``full_name``, ``username``, ``password`` (must pass strength
    rules), ``role`` (one of ALL_ROLES), optional ``email``, ``phone``,
    ``gender``, ``dob`` (ISO date), plus CSRF token.

    Access: admin role only.
    """
    full_name = request.form.get("full_name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "patient")
    email = request.form.get("email", "").strip() or None
    phone = request.form.get("phone", "").strip() or None
    gender = request.form.get("gender", "").strip() or None
    dob_raw = request.form.get("dob", "").strip()
    dob = parse_dob(dob_raw) if dob_raw else None
    if dob_raw and dob is None:
        flash("Invalid date of birth.", "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    if not all([full_name, username, password]):
        flash("Full name, username and password are required.", "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    if role not in _ALLOWED_ROLES:
        flash("Invalid role.", "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    pwd_error = validate_password(password)
    if pwd_error:
        flash(pwd_error, "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already taken.", "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    if email and User.query.filter_by(email=email).first():
        flash(f"Email '{email}' is already registered.", "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    new_user = User()
    new_user.full_name = full_name
    new_user.username = username
    new_user.role = role
    new_user.email = email
    new_user.phone = phone
    new_user.gender = gender
    new_user.dob = dob
    new_user.set_password(password)
    db.session.add(new_user)

    if not safe_commit(f"add_user username={username}"):
        flash("Could not create the user due to a database error.", "error")
        return redirect(url_for("admin_bp.admin_dashboard", tab="register"))

    audit_logger.info(f"SECURITY – Admin created user '{username}' (role={role})")
    flash(f"User '{full_name}' created successfully.", "success")
    return redirect(url_for("admin_bp.admin_dashboard"))


@admin_bp.route("/delete_user/<int:user_id>", methods=["POST"])
@role_required(Role.ADMIN)
def delete_user(user_id: int) -> ResponseReturnValue:
    """Delete a non-admin user account.

    Path param: ``user_id``. POST body carries only the CSRF token.

    Access: admin role only. Admin accounts cannot be deleted via this
    endpoint to prevent accidental lock-out.
    """
    user = User.query.get_or_404(user_id)
    if user.role == Role.ADMIN:
        flash("Cannot delete an admin account.", "error")
        return redirect(url_for("admin_bp.admin_dashboard"))

    db.session.delete(user)
    if not safe_commit(f"delete_user id={user_id}"):
        flash("Could not delete the user due to a database error.", "error")
        return redirect(url_for("admin_bp.admin_dashboard"))

    audit_logger.info(f"SECURITY – Admin deleted user '{user.username}'")
    flash(f"User '{user.full_name}' removed.", "success")
    return redirect(url_for("admin_bp.admin_dashboard"))

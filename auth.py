"""
auth.py  –  Login / role-based access decorators and the role -> dashboard
endpoint mapping shared by login redirect and post-upload redirect.
"""

from enum import Enum
from functools import wraps

from flask import flash, redirect, session, url_for


class Role(str, Enum):
    """Canonical user role values.

    Inherits from `str` so the members compare equal to their string values
    — existing code paths that store the role in the session as a plain
    string (`session["role"] = user.role`) and compare against literals
    keep working without change.
    """

    ADMIN     = "admin"
    DOCTOR    = "doctor"
    SECRETARY = "secretary"
    PATIENT   = "patient"


ALL_ROLES = frozenset(r.value for r in Role)


# Role → blueprint endpoint for the destination dashboard.
DASHBOARD_BY_ROLE = {
    Role.ADMIN.value:     "admin_bp.admin_dashboard",
    Role.DOCTOR.value:    "doctor_bp.doctor_dashboard",
    Role.SECRETARY.value: "secretary_bp.secretary_dashboard",
    Role.PATIENT.value:   "patient_bp.patient_dashboard",
}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth_bp.login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    """Allow only sessions whose `role` is in the given set.

    Accepts either bare strings (`role_required("admin")`) or Role members
    (`role_required(Role.ADMIN)`). We extract `.value` explicitly because
    `str(Role.ADMIN)` returns `"Role.ADMIN"` rather than `"admin"` on
    Python < 3.11 with a `class Role(str, Enum)` definition.
    """
    allowed = {r.value if isinstance(r, Role) else r for r in roles}

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth_bp.login"))
            if session.get("role") not in allowed:
                flash("Access denied.", "error")
                return redirect(url_for("auth_bp.login"))
            return f(*args, **kwargs)
        return decorated
    return decorator

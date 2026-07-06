"""
routes/auth_bp.py  –  Login form and logout.
"""

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue
from werkzeug.security import check_password_hash, generate_password_hash

from auth import DASHBOARD_BY_ROLE
from database import User
from extensions import limiter
from services.audit import audit_logger

auth_bp = Blueprint("auth_bp", __name__)

# A precomputed hash used to make the "user not found" path do the same
# work as "user found, wrong password" — defeats account-enumeration via
# response timing.
_DUMMY_HASH = generate_password_hash("dummy-password-never-matches")


@auth_bp.route("/", methods=["GET", "POST"])
@limiter.limit(
    "20 per minute; 100 per hour",
    methods=["POST"],
    error_message="Too many login attempts. Please wait a minute and try again.",
)
def login() -> ResponseReturnValue:
    """Render the login form (GET) or authenticate the user (POST).

    POST form: ``username``, ``password``, plus the CSRF token. On success
    the session is regenerated and the user is redirected to their role's
    dashboard. On failure a generic "Invalid username or password" message
    is rendered with HTTP 200.

    Access: public (no login required). POST is rate-limited.
    """
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # Regenerate the session to defeat session-fixation: any cookie
            # that existed before login is discarded; Flask issues a new one.
            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            session["role"] = user.role
            session["name"] = user.full_name

            audit_logger.info(
                f"SECURITY – login_success user_id={user.id} role={user.role} "
                f"ip={request.remote_addr}"
            )
            return redirect(url_for(DASHBOARD_BY_ROLE.get(user.role, "auth_bp.login")))

        # Equalize the failure path: even when the user doesn't exist, run a
        # password verification against a dummy hash so timing matches.
        if user is None:
            check_password_hash(_DUMMY_HASH, password)

        audit_logger.warning(
            f"SECURITY – login_failed ip={request.remote_addr}"
        )
        return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout() -> ResponseReturnValue:
    """Clear the session and redirect to the login screen.

    Access: any authenticated session; anonymous callers are also accepted
    and simply redirect (the session.clear() is a no-op).
    """
    user_id = session.get("user_id")
    session.clear()
    if user_id:
        audit_logger.info(f"SECURITY – logout user_id={user_id}")
    return redirect(url_for("auth_bp.login"))

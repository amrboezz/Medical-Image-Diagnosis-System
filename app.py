"""
app.py  –  Flask app factory for MediDiagnostic.

The factory wires up config, the SQLAlchemy database, all route blueprints, and
optionally preloads the four ML models. Production is launched via wsgi.py
(waitress); developer-mode `python app.py` runs Flask's reloader.
"""

import logging
import os
import sys

# Make Windows-installed CUDA visible to TensorFlow before any TF / keras
# import. Skipped on non-Windows (Linux finds CUDA via LD_LIBRARY_PATH from
# the OS package). Honors an explicit override via the CUDA_PATH env var.
if sys.platform.startswith("win"):
    _explicit = os.environ.get("CUDA_PATH", "").strip()
    _candidates = [_explicit] if _explicit else [
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.0\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin",
        r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.2\bin",
    ]
    for _cuda_path in _candidates:
        if _cuda_path and os.path.isdir(_cuda_path):
            os.environ["PATH"] = _cuda_path + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(_cuda_path)
            except AttributeError:
                pass
            break

# Keras 3 requires a backend choice before import.
os.environ["KERAS_BACKEND"] = "tensorflow"

from flask import Flask, jsonify  # noqa: E402

from config import DevConfig, enforce_runtime_invariants  # noqa: E402
from database import db  # noqa: E402
from extensions import csrf, limiter  # noqa: E402
from routes.admin_bp import admin_bp  # noqa: E402
from routes.api_bp import api_bp  # noqa: E402
from routes.auth_bp import auth_bp  # noqa: E402
from routes.doctor_bp import doctor_bp  # noqa: E402
from routes.patient_bp import patient_bp  # noqa: E402
from routes.secretary_bp import secretary_bp  # noqa: E402
from routes.uploads_bp import uploads_bp  # noqa: E402

_BLUEPRINTS = (
    auth_bp,
    admin_bp,
    doctor_bp,
    secretary_bp,
    patient_bp,
    uploads_bp,
    api_bp,
)


def _run_schema_migrations() -> None:
    """Run idempotent schema migrations for pre-existing SQLite databases.

    `db.create_all()` only creates missing tables; it never ALTERs existing
    ones. Each step here is keyed on inspector state so re-running is safe.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    if "reports" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("reports")}
        to_add = [
            ("approved_by_id", "INTEGER"),
            ("approved_at", "DATETIME"),
        ]
        with db.engine.begin() as conn:
            for col, sqltype in to_add:
                if col not in existing:
                    conn.execute(
                        text(f"ALTER TABLE reports ADD COLUMN {col} {sqltype}")
                    )

    # DOB column moved from String to Date (M4). SQLite stores both as text;
    # the on-disk format just needs to be ISO `YYYY-MM-DD` so SQLAlchemy's
    # Date adapter can read it. Normalize any legacy strings here.
    if "users" in inspector.get_table_names():
        from services.db_helpers import parse_dob

        with db.engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id, dob FROM users WHERE dob IS NOT NULL AND dob != ''")
            ).fetchall()
            for row_id, raw_dob in rows:
                # SQLite returns the column as a string regardless of declared type.
                if not isinstance(raw_dob, str):
                    continue
                if len(raw_dob) == 10 and raw_dob[4] == "-" and raw_dob[7] == "-":
                    continue  # already ISO
                parsed = parse_dob(raw_dob)
                if parsed is None:
                    conn.execute(
                        text("UPDATE users SET dob = NULL WHERE id = :id"),
                        {"id": row_id},
                    )
                else:
                    conn.execute(
                        text("UPDATE users SET dob = :iso WHERE id = :id"),
                        {"iso": parsed.isoformat(), "id": row_id},
                    )


def _enable_sqlite_foreign_keys() -> None:
    """SQLite ignores FK constraints unless `PRAGMA foreign_keys = ON` is set
    on every connection. Hook this onto the engine so ondelete clauses on
    Report.patient_id are actually enforced."""
    from sqlalchemy import event

    @event.listens_for(db.engine, "connect")
    def _set_pragma(dbapi_connection, _conn_record):
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:
            # Non-SQLite backend (e.g. Postgres in future) — pragma is a no-op.
            pass


_SECURITY_HEADERS_BASE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Tailwind output + GSAP are served from /static (same-origin). All
    # network calls (chat, uploads) are same-origin too. Inline `style=`
    # attrs and inline `onclick=`/`onchange=` handlers are present in
    # several templates today (search-clear, modal toggles, print button,
    # "Read More" expanders). 'unsafe-inline' is therefore allowed for
    # both directives so these don't silently break. Tighten by extracting
    # the inline handlers into static/js/*.js and adding a nonce.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}


def _install_health_route(app: Flask) -> None:
    """Register an unauthenticated liveness/readiness endpoint.

    `GET /health` returns a small JSON snapshot that monitors and load
    balancers can poll. The endpoint never queries the DB or hits external
    services so it stays cheap to call.
    """
    from extensions import csrf, limiter
    from services.inference import GLOBAL_MODELS

    @app.route("/health")
    @csrf.exempt
    @limiter.exempt
    def health():
        return jsonify(
            status="ok",
            models_loaded=sorted(GLOBAL_MODELS.keys()),
        ), 200


def _install_security_headers(app: Flask) -> None:
    """Attach an after_request hook that sets HTTPS-safe response headers."""
    headers = dict(_SECURITY_HEADERS_BASE)

    @app.after_request
    def _set_headers(response):
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


def _install_error_handlers(app: Flask) -> None:
    """Return clean, user-friendly responses instead of raw Werkzeug error
    pages. API/upload paths get JSON; normal navigation gets a flashed
    redirect (413) or a dependency-free HTML page (500)."""
    from flask import flash, redirect, request, url_for

    def _wants_json() -> bool:
        return request.path.startswith("/api") or request.path == "/upload"

    @app.errorhandler(413)
    def _payload_too_large(_e):
        msg = "File too large. The maximum upload size is 16 MB."
        if _wants_json():
            return jsonify(error=msg), 413
        flash(msg, "error")
        return redirect(request.referrer or url_for("auth_bp.login"))

    @app.errorhandler(500)
    def _internal_error(_e):
        msg = "Something went wrong on our end. Please try again."
        if _wants_json():
            return jsonify(error=msg), 500
        return (
            "<!doctype html><meta charset='utf-8'><title>Error</title>"
            "<div style='font-family:system-ui,sans-serif;max-width:34rem;"
            "margin:5rem auto;text-align:center;color:#334155'>"
            "<h1 style='font-size:1.4rem'>Something went wrong</h1>"
            "<p>An unexpected error occurred. Please go back and try again.</p>"
            "<p><a href='/' style='color:#2563eb'>Return to login</a></p></div>"
        ), 500


def create_app(
    *,
    preload: bool = True,
    test_config: dict | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config.from_object(DevConfig)
    if test_config:
        app.config.update(test_config)

    enforce_runtime_invariants(app)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    with app.app_context():
        _enable_sqlite_foreign_keys()
        db.create_all()
        _run_schema_migrations()

    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)

    _install_health_route(app)
    _install_security_headers(app)
    _install_error_handlers(app)

    if preload:
        from services.inference import preload_models
        preload_models(app.config["MODEL_DIR"])

    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s – %(message)s",
    )
    create_app().run(host="127.0.0.1", port=5000, debug=False)

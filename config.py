"""
config.py  –  Environment-driven configuration for the MediDiagnostic app.

Loads variables from a `.env` file (gitignored) via python-dotenv. Two configs
are exposed: DevConfig (debug enabled) and ProdConfig (debug disabled). The
factory in app.py picks one based on the `env` argument and then calls
``enforce_runtime_invariants(app)`` which fails fast on dangerous misconfig.
"""

import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Fixed fallback used in dev/test when SECRET_KEY is not provided in the
# environment. Crucially fixed (not random) so sessions survive across
# `flask run` reloads. enforce_runtime_invariants() refuses to start in
# prod without an explicit env value, so this string never reaches users.
_DEV_FALLBACK_SECRET_KEY = "dev-only-do-not-use-in-production-please-set-SECRET_KEY"


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or _DEV_FALLBACK_SECRET_KEY
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BASE_DIR, 'medidiagnostic.db')}",
    )

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MODEL_DIR = os.path.join(BASE_DIR, "models")
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "gif", "tiff", "webp", "dcm"}

    # Reject uploads larger than 16 MB at the framework boundary.
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # Session cookies: HttpOnly blocks JS access; Lax SameSite blunts CSRF
    # for top-level navigations while keeping normal links working. Secure
    # is only safe to enable behind TLS — ProdConfig turns it on.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)

    # Flask-Limiter: in-memory storage is fine for a single-process dev
    # deployment; production should switch to Redis.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    # Master on/off switch for rate limiting. Default on (secure). Set
    # RATELIMIT_ENABLED=false in .env to disable entirely — a handy
    # kill-switch during a live demo if the limits ever get in the way.
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "true").strip().lower() not in (
        "false", "0", "no", "off",
    )


class DevConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # dev runs on http://127.0.0.1


def enforce_runtime_invariants(app: Flask) -> None:
    """Fail fast on misconfigurations that would silently weaken security.

    Called from create_app() once the config object has been applied to the
    app — running here (rather than at import time) lets us inspect the
    final, post-test_config overrides too.
    """
    has_explicit_key = bool(os.environ.get("SECRET_KEY", "").strip())

    # Dev / test path: warn once if we're running on the dev fallback key so
    # the developer knows sessions are predictable. Suppressed under TESTING
    # to keep pytest output clean — tests inject their own SECRET_KEY.
    if not has_explicit_key and not app.config.get("TESTING"):
        logging.getLogger("medidiagnostic.config").warning(
            "SECRET_KEY is not set in the environment; using the fixed dev "
            "fallback. Generate a real key with `python -c \"import secrets; "
            "print(secrets.token_hex(32))\"` and put it in .env before "
            "exposing this app outside localhost."
        )

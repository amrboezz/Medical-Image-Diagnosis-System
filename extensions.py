"""
extensions.py  –  Single source of truth for Flask extension instances.

Holds the un-bound extension singletons that are init_app(app)'d inside
create_app(). Models and route modules import their handles from here so
that adding a future extension (Flask-Migrate, Flask-Login, Flask-Limiter)
has an obvious home and avoids circular imports between models and the app
factory.
"""

from flask import session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


def _rate_limit_key() -> str:
    """Rate-limit by user_id when logged in, IP otherwise."""
    return f"user:{session['user_id']}" if "user_id" in session else get_remote_address()


db = SQLAlchemy()
csrf = CSRFProtect()
limiter = Limiter(key_func=_rate_limit_key, default_limits=[])

"""
tests/conftest.py  –  Shared pytest fixtures.

The app fixture builds a fresh Flask app backed by an in-memory SQLite DB and
skips the (slow, GPU-bound) model warm-start. Tests that exercise inference
routes should monkeypatch ``services.inference.GLOBAL_MODELS``.
"""

import pytest

from app import create_app
from database import db, User


@pytest.fixture()
def app():
    flask_app = create_app(
        preload=False,
        test_config={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "SECRET_KEY": "test-secret",
        },
    )

    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        # Seed one user per role for permission tests.
        for role in ("admin", "doctor", "secretary", "patient"):
            u = User(full_name=f"Test {role.title()}", username=role, role=role)
            u.set_password(role)
            db.session.add(u)
        db.session.commit()

        yield flask_app

        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login(client):
    """Helper that logs in as a given role and returns the test client."""
    def _login(role: str):
        return client.post(
            "/",
            data={"username": role, "password": role},
            follow_redirects=False,
        )
    return _login


@pytest.fixture()
def csrf_app():
    """A second app instance with CSRF enabled, for negative-path tests."""
    flask_app = create_app(
        preload=False,
        test_config={
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": True,
            "RATELIMIT_ENABLED": False,
            "SECRET_KEY": "test-secret",
        },
    )
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        for role in ("admin", "doctor", "secretary", "patient"):
            u = User(full_name=f"Test {role.title()}", username=role, role=role)
            u.set_password(role)
            db.session.add(u)
        db.session.commit()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def csrf_client(csrf_app):
    return csrf_app.test_client()

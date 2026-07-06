"""
seed_db.py  –  Initialize the database and create a default admin user.

The admin password is taken from the ADMIN_PASSWORD environment variable.
If unset, a strong random password is generated and printed ONCE — copy it
before you close the terminal, the script will not show it again.

Run: ADMIN_PASSWORD=<strong> python seed_db.py
"""

import os
import secrets

from app import create_app
from database import User, db


def _resolve_admin_password() -> tuple[str, bool]:
    """Return (password, was_generated). Reject weak supplied passwords."""
    supplied = os.environ.get("ADMIN_PASSWORD", "").strip()
    if supplied:
        if len(supplied) < 12:
            raise SystemExit(
                "[seed_db] ADMIN_PASSWORD must be at least 12 characters."
            )
        return supplied, False
    return secrets.token_urlsafe(18), True


def main() -> None:
    # Skip the model warm-start when seeding — DB-only operation.
    app = create_app(preload=False)
    with app.app_context():
        db.create_all()
        print("[seed_db] Tables created.")

        if User.query.filter_by(username="admin").first():
            print("[seed_db] Admin user already exists, skipping.")
            return

        password, generated = _resolve_admin_password()
        admin = User(full_name="System Admin", username="admin", role="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()

        if generated:
            print("[seed_db] Default admin user created.")
            print("[seed_db] Username: admin")
            print(f"[seed_db] Password: {password}")
            print("[seed_db] >>> Copy this password now; it will not be shown again. <<<")
        else:
            print("[seed_db] Default admin user created with ADMIN_PASSWORD from env.")

    print("[seed_db] Done.")


if __name__ == "__main__":
    main()

# MediDiagnostic

A Flask-based medical diagnostic web application that runs four deep-learning
models on uploaded radiographs and provides a Gemini-powered clinical chatbot.

| Scan type | Model | Framework |
|---|---|---|
| Bone fracture | ResNet50 (transfer learning, 2-class) | PyTorch |
| Bone tumor | TorchScript classifier (512×512) | PyTorch |
| Knee osteoarthritis | Xception backbone, 5-class KL grade | TensorFlow / Keras 3 |
| Knee osteoporosis | DenseNet201 (2-class) | TensorFlow / Keras 3 |

> How they load (`services/inference.py`): fracture = ResNet50 + `state_dict`;
> tumor = TorchScript (`torch.jit.load`, 512×512); osteoarthritis = Xception
> rebuilt then `load_weights`; osteoporosis = complete saved model
> (`load_model`). The fracture, tumor, and osteoarthritis details are visible in
> code; the osteoporosis architecture is whatever was saved into the `.h5`.

The app supports four user roles: **admin**, **doctor**, **secretary**, **patient**.

---

## Quick start

```powershell
# 1. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies (pin torch/torchvision wheels to your CUDA version if needed)
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env and set SECRET_KEY (generate with: python -c "import secrets; print(secrets.token_hex(32))")
# and GEMINI_API_KEY (from https://aistudio.google.com/app/apikey)

# 4. Place model files
# Put Fracture.pt, tumor_model.pt, osteoarthritis_model.h5, osteoporosis_model.h5
# into the models/ directory.

# 5. Seed the database
# For a local demo: create/reset one known account per role + sample patient
# data. Idempotent and never wipes existing data; prints the demo logins.
python seed.py
#
# (Alternative) bootstrap only a production admin with a strong password:
# $env:ADMIN_PASSWORD = "<a-strong-password>"   # or let seed_db.py generate one
# python seed_db.py

# 6. Run
python app.py            # development (Flask reloader, http://127.0.0.1:5000)
python wsgi.py           # production-style (waitress, http://0.0.0.0:5000)
```

> **Demo logins:** `python seed.py` creates/resets one account per role
> (`admin`, `doc`, `sec`, `pat`) and **prints their passwords to the console**.
> These are for local demos only — change them before any real deployment.

---

## Project layout

```
.
├── app.py                  # Flask app factory (+ health, error handlers, security headers)
├── wsgi.py                 # Production entry (waitress)
├── config.py               # Dev / Prod config classes
├── database.py             # SQLAlchemy models (User, Report)
├── extensions.py           # Extension singletons (db, csrf, limiter)
├── seed.py                 # Idempotent demo seeding (role accounts + sample data)
├── seed_db.py              # One-shot DB initializer + default admin
├── auth.py                 # login_required, role_required decorators
├── services/
│   ├── inference.py        # Model registry, loaders, dual inference
│   ├── chatbot.py          # Gemini lazy init
│   ├── audit.py            # In-memory audit log handler
│   ├── dicom_utils.py      # DICOM (.dcm) → PNG conversion
│   └── db_helpers.py       # Commit + serialization + search helpers
├── routes/
│   ├── auth_bp.py          # Login / logout
│   ├── admin_bp.py         # /admin + user management + live JSON APIs
│   ├── doctor_bp.py        # /doctor + diagnosis approval
│   ├── secretary_bp.py     # /secretary
│   ├── patient_bp.py       # /patient
│   ├── uploads_bp.py       # Upload, image serving, print report
│   └── api_bp.py           # /api/chat (Gemini)
├── templates/              # Jinja2 templates
├── static/                 # Tailwind CSS + GSAP + UI module
├── models/                 # Trained model weights (gitignored)
├── uploads/                # Patient-sharded scan uploads (gitignored)

└── tests/                  # pytest smoke tests (mocked models)
```

---

## Running tests

```powershell
pytest -q
ruff check .
```

Tests use an in-memory SQLite DB and mock the `GLOBAL_MODELS` registry so the
real `.h5` / `.pt` files don't need to be loaded.

---

## Frontend (Tailwind CSS)

The compiled stylesheet at `static/css/style.css` is what the templates link
against. It is generated from `static/css/input.css` via the **Tailwind CSS
standalone binary**, which is a ~130 MB build tool that **must not** be
committed (see `.gitignore`).

To install / refresh the binary:

```powershell
# 1. Download the Windows x64 standalone binary from
#    https://github.com/tailwindlabs/tailwindcss/releases/latest
#    (file: tailwindcss-windows-x64.exe)
# 2. Drop it in tools/ and rename to tailwindcss.exe
mkdir -Force tools
Invoke-WebRequest -OutFile tools\tailwindcss.exe `
    https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-windows-x64.exe
```

To rebuild the stylesheet after editing templates or `input.css`:

```powershell
.\tools\tailwindcss.exe -i static\css\input.css -o static\css\style.css --minify
```

Run with `--watch` (no `--minify`) during active template development.

---

## Security notes

* Secrets (`SECRET_KEY`, `GEMINI_API_KEY`) come from `.env` only — never commit
  the real `.env` file.
* The dev server (`python app.py`) runs with `debug=False` (no interactive
  debugger or auto-reloader) — flip it to `True` in `app.py` for active
  development. The production entry (`wsgi.py`) always uses `ProdConfig`
  (`DEBUG=False`).
* Passwords are stored as Werkzeug PBKDF2 hashes (see `User.set_password`).
* Uploaded filenames are sanitized via `werkzeug.utils.secure_filename`, and
  uploaded bytes are content-validated with Pillow (extensions must match the
  detected image format).
* Cross-Site Request Forgery is enforced by Flask-WTF on every POST form.
* Login (`20/min, 100/hour`) and chat (`30/min, 500/day`) are rate-limited by
  Flask-Limiter (keyed by user id when authenticated, else client IP). Set
  `RATELIMIT_ENABLED=false` in `.env` to disable limits entirely (e.g. for a
  live demo).
* Oversized uploads (`> 16 MB`) and unexpected errors return clean `413` / `500`
  responses (JSON for `/api` and `/upload`) instead of raw stack traces.

### Production deployment

Production **must** run behind TLS (nginx, Caddy, IIS reverse proxy, etc.) —
without it `SESSION_COOKIE_SECURE=True` will cause the browser to drop the
session cookie. The `ProdConfig` boot path refuses to start unless:

  * `SECRET_KEY` is set explicitly (no ephemeral fallback).
  * `SESSION_COOKIE_SECURE` is `True` (it is, by default, in `ProdConfig`).

Run it via:

```powershell
$env:FLASK_ENV          = "prod"
$env:SECRET_KEY         = "<64-char hex>"
$env:GEMINI_API_KEY     = "<your-key>"
$env:ADMIN_PASSWORD     = "<strong>"      # only needed for the first seed_db
$env:RATELIMIT_STORAGE_URI = "redis://localhost:6379/0"   # recommended

python wsgi.py
```

The application listens on plain HTTP behind your reverse proxy. The proxy
should:

  * Terminate TLS (`Strict-Transport-Security` header is emitted in prod).
  * Forward `X-Forwarded-For` / `X-Forwarded-Proto` so rate-limiting and
    URL generation see the original client.
  * Cap request body size to match `MAX_CONTENT_LENGTH` (16 MB).

---

## License

TBD.

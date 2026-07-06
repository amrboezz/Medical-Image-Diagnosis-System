"""
routes/uploads_bp.py  –  Image upload + AI inference, image serving, and the
printable report view.

The upload endpoint dispatches to either the dual fracture/tumor pipeline or
the knee osteoarthritis + osteoporosis pipeline, based on `scan_target`.
"""

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue
from werkzeug.utils import secure_filename

from auth import DASHBOARD_BY_ROLE, Role, login_required
from database import Report, ReportStatus, User, db
from services.audit import audit_logger
from services.db_helpers import (
    allowed_file,
    can_view_report,
    compute_age,
    safe_commit,
    validate_image_file,
)
from services.inference import (
    SCAN_TYPE_LABELS,
    run_degenerative_knee_inference,
    run_fracture_inference,
    run_tumor_inference,
)

# Basename portion of an upload path: 32 hex chars + an extension we allow.
# The patient_id is enforced as <int:...> at the routing layer.
_IMAGE_BASENAME_RE = re.compile(
    r"^[0-9a-f]{32}\.(png|jpg|jpeg|bmp|gif|tiff|webp|dcm)$",
    re.IGNORECASE,
)

uploads_bp = Blueprint("uploads_bp", __name__)
executor = ThreadPoolExecutor(max_workers=2)

def process_inference_background(app, report_id, patient_id, scan_target, save_path, rel_path):
    with app.app_context():
        report = db.session.get(Report, report_id)
        if not report:
            return

        ai_result = "Analysis Pending"
        ai_confidence = 0.0
        winning_model = "unknown"
        report_status = ReportStatus.PRELIMINARY

        try:
            if scan_target == "degenerative_knee":
                ai_result, ai_confidence, winning_model = run_degenerative_knee_inference(save_path)
            elif scan_target == "fracture":
                ai_result, ai_confidence, winning_model = run_fracture_inference(save_path)
            elif scan_target == "tumor":
                ai_result, ai_confidence, winning_model = run_tumor_inference(save_path)

            audit_logger.info(
                f"MEDICAL – scan stored at path_hash={hash(rel_path) & 0xFFFFFFFF:08x} "
                f"winner='{winning_model}' patient_id={patient_id} "
                f"confidence={ai_confidence}% status={report_status}"
            )
        except RuntimeError as exc:
            audit_logger.error(f"Inference complete failure for patient_id={patient_id}: {exc}")
            ai_result = "AI analysis failed; awaiting manual review."
            ai_confidence = 0.0
            report_status = ReportStatus.ERROR
        except Exception as exc:
            audit_logger.error(f"Inference unexpected error for patient_id={patient_id}: {type(exc).__name__}")
            ai_result = "AI analysis failed; awaiting manual review."
            ai_confidence = 0.0
            report_status = ReportStatus.ERROR

        report.scan_type = SCAN_TYPE_LABELS.get(winning_model, scan_target.replace("_", " ").title())
        report.ai_result = ai_result
        report.ai_confidence = ai_confidence
        report.status = report_status
        safe_commit(f"background inference update for report_id={report_id}")


@uploads_bp.route("/upload", methods=["POST"])
@login_required
def upload() -> ResponseReturnValue:
    role = session.get("role")
    user_id = session.get("user_id")

    if role == Role.PATIENT:
        patient_id = user_id
        patient_user = User.query.get(patient_id)
        patient_name = patient_user.full_name if patient_user else "Unknown"
    elif role in (Role.SECRETARY, Role.ADMIN):
        patient_id = request.form.get("patient_id", type=int)
        patient_user = User.query.get(patient_id) if patient_id else None
        if not patient_user:
            flash("Please select a valid patient.", "error")
            return redirect(request.referrer or url_for("secretary_bp.secretary_dashboard"))
        patient_name = patient_user.full_name
    else:
        flash("Unauthorized upload.", "error")
        return redirect(url_for("auth_bp.login"))

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

    if not allowed_file(file.filename):
        flash("Invalid file type. Please upload an image.", "error")
        return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    patient_dir = os.path.join(upload_folder, str(patient_id))
    os.makedirs(patient_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    rel_path = f"{patient_id}/{unique_name}"
    save_path = os.path.join(patient_dir, unique_name)

    try:
        file.save(save_path)
    except OSError:
        audit_logger.error(f"Upload save failed for patient_id={patient_id} (disk write error)")
        flash("Could not save the uploaded file. Please try again.", "error")
        return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

    if ext == "dcm":
        new_ext = "png"
        new_unique_name = f"{uuid.uuid4().hex}.{new_ext}"
        new_rel_path = f"{patient_id}/{new_unique_name}"
        new_save_path = os.path.join(patient_dir, new_unique_name)

        try:
            from services.dicom_utils import convert_dicom_to_png
            convert_dicom_to_png(save_path, new_save_path)
        except Exception as e:
            audit_logger.error(f"DICOM conversion failed for patient_id={patient_id}: {e}")
            flash("Could not process DICOM file.", "error")
            try:
                os.remove(save_path)
            except OSError:
                pass
            return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

        try:
            os.remove(save_path)
        except OSError:
            pass

        ext = new_ext
        unique_name = new_unique_name
        rel_path = new_rel_path
        save_path = new_save_path

    content_error = validate_image_file(save_path, ext)
    if content_error:
        audit_logger.warning(f"SECURITY – rejected upload patient_id={patient_id} role={role} reason=content_validation")
        try:
            os.remove(save_path)
        except OSError:
            pass
        flash(content_error, "error")
        return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

    scan_target = request.form.get("scan_target", "fracture")

    if scan_target not in ["fracture", "tumor", "degenerative_knee"]:
        audit_logger.warning(f"SECURITY - Invalid scan_target '{scan_target}' from patient_id={patient_id}")
        try:
            os.remove(save_path)
        except OSError:
            pass
        flash("Invalid scan type selected. Please submit a valid scan.", "error")
        return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

    scan_type_initial = SCAN_TYPE_LABELS.get(scan_target, scan_target.replace("_", " ").title())
    report = Report()
    report.patient_id = patient_id
    report.patient_name = patient_name
    report.scan_type = scan_type_initial
    report.image_path = rel_path
    report.ai_result = "Analysis Pending"
    report.ai_confidence = 0.0
    report.status = ReportStatus.PRELIMINARY
    db.session.add(report)

    if not safe_commit(f"upload report initial for patient_id={patient_id}"):
        try:
            os.remove(save_path)
        except OSError as cleanup_exc:
            audit_logger.error(f"Failed to clean up orphaned upload for patient_id={patient_id}: {type(cleanup_exc).__name__}")
        flash("Scan uploaded, but the report could not be saved due to a database error.", "error")
        return redirect(request.referrer or url_for("patient_bp.patient_dashboard"))

    # Submit task to ThreadPoolExecutor
    executor.submit(
        process_inference_background,
        current_app._get_current_object(),
        report.id,
        patient_id,
        scan_target,
        save_path,
        rel_path
    )

    # Return JSON for Phase 1 polling
    return jsonify({"message": "Upload accepted for processing", "report_id": report.id}), 202


@uploads_bp.route("/uploads_view/<int:patient_id>/<filename>", endpoint="uploaded_file")
@login_required
def uploaded_file(patient_id: int, filename: str) -> ResponseReturnValue:
    if not _IMAGE_BASENAME_RE.match(filename):
        abort(404)

    rel_path = f"{patient_id}/{filename}"
    report = Report.query.filter_by(image_path=rel_path).first()
    if report is None:
        abort(404)

    role = session.get("role")
    user_id = session.get("user_id")
    if not can_view_report(report, role, user_id):
        audit_logger.warning(
            f"SECURITY – user_id={user_id} role={role} denied image "
            f"report_id={report.id}"
        )
        abort(403)

    return send_from_directory(current_app.config["UPLOAD_FOLDER"], rel_path)


@uploads_bp.route("/print_report/<int:report_id>")
@login_required
def print_report(report_id: int) -> ResponseReturnValue:
    report = Report.query.get_or_404(report_id)

    role = session.get("role")
    user_id = session.get("user_id")
    if not can_view_report(report, role, user_id):
        audit_logger.warning(
            f"SECURITY – user_id={user_id} role={role} denied print "
            f"report_id={report.id}"
        )
        flash("Unauthorized access to this medical record.", "error")
        return redirect(url_for(DASHBOARD_BY_ROLE.get(role, "auth_bp.login")))

    gender = (report.patient.gender if report.patient else None) or "—"
    age_value = compute_age(report.patient.dob if report.patient else None)
    age = age_value if age_value is not None else "—"

    return render_template("print_report.html", report=report, age=age, gender=gender)



@uploads_bp.route("/upload/status/<int:report_id>")
@login_required
def upload_status(report_id: int):
    report = Report.query.get_or_404(report_id)
    role = session.get("role")
    user_id = session.get("user_id")

    # Check access using the db_helper
    if not can_view_report(report, role, user_id):
        abort(403)

    if report.status == ReportStatus.ERROR:
        status_str = "ERROR"
    elif report.ai_result != "Analysis Pending":
        status_str = "COMPLETED"
    else:
        status_str = "PRELIMINARY"

    return jsonify({
        "status": status_str,
        "result": report.ai_result,
        "redirect_url": url_for(DASHBOARD_BY_ROLE.get(role, "patient_bp.patient_dashboard"))
    })

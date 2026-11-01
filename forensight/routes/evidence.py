import hashlib
import io
import json
import uuid
import warnings
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_login import current_user, login_required
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

from extensions import db
from models import AuditLog, Evidence
from routes.access import json_object, require_edit, visible_case


evidence_bp = Blueprint("evidence", __name__, url_prefix="/api")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf", "txt"}
IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EVIDENCE_CATEGORIES = {"Photograph", "Document", "Digital media", "Physical item", "Other"}


def validate_upload(filename, content, max_image_pixels=20_000_000):
    safe_name = secure_filename(filename)
    extension = Path(safe_name).suffix.lower().lstrip(".")
    if not safe_name or extension not in ALLOWED_EXTENSIONS or not content:
        return None
    if extension in {"jpg", "jpeg", "png", "webp"}:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                image = Image.open(io.BytesIO(content))
                if image.width * image.height > max_image_pixels:
                    return None
                image.verify()
            detected = IMAGE_MIMES.get(image.format)
            expected_extensions = {"JPEG": {"jpg", "jpeg"}, "PNG": {"png"}, "WEBP": {"webp"}}
            if not detected or extension not in expected_extensions.get(image.format, set()):
                return None
            return detected
        except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError, ValueError):
            return None
    if extension == "pdf" and content.startswith(b"%PDF-"):
        return "application/pdf"
    if extension == "txt":
        try:
            content.decode("utf-8")
            if b"\x00" not in content:
                return "text/plain"
        except UnicodeDecodeError:
            return None
    return None


@evidence_bp.get("/cases/<int:case_id>/evidence")
@login_required
def list_evidence(case_id):
    visible_case(case_id, current_user)
    query = Evidence.query.filter_by(case_id=case_id)
    if request.args.get("category"):
        query = query.filter_by(category=request.args["category"])
    if request.args.get("status"):
        query = query.filter_by(examination_status=request.args["status"])
    return jsonify(items=[entry.to_dict() for entry in query.order_by(Evidence.uploaded_at.desc()).all()])


@evidence_bp.post("/cases/<int:case_id>/evidence")
@login_required
def upload_evidence(case_id):
    case = visible_case(case_id, current_user)
    require_edit(case, current_user)
    upload = request.files.get("file")
    if not upload:
        return jsonify(error="Select a file to upload."), 400
    content = upload.read(current_app.config["MAX_CONTENT_LENGTH"] + 1)
    if len(content) > current_app.config["MAX_CONTENT_LENGTH"]:
        return jsonify(error="Upload exceeds the configured size limit."), 413
    mime_type = validate_upload(upload.filename or "", content, current_app.config["MAX_IMAGE_PIXELS"])
    if not mime_type:
        return jsonify(error="File content does not match an allowed JPG, PNG, WebP, PDF, or UTF-8 text file."), 400
    safe_name = secure_filename(upload.filename or "evidence")
    extension = Path(safe_name).suffix.lower()
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)
    while True:
        stored_name = f"{uuid.uuid4().hex}{extension}"
        target = upload_folder / stored_name
        try:
            with target.open("xb") as stored_file:
                stored_file.write(content)
            break
        except FileExistsError:
            continue
    category = request.form.get("category", "Other").strip() or "Other"
    description = request.form.get("description", "").strip()
    if category not in EVIDENCE_CATEGORIES or len(description) > 10000:
        target.unlink(missing_ok=True)
        return jsonify(error="Choose a supported evidence category and keep descriptions under 10,000 characters."), 400
    entry = Evidence(
        evidence_number=f"EV-{uuid.uuid4().hex[:10].upper()}", case_id=case.id,
        category=category, description=description, original_filename=safe_name,
        stored_filename=stored_name, storage_path=str(target.resolve()), mime_type=mime_type,
        file_size=len(content), sha256_hash=hashlib.sha256(content).hexdigest(), created_by=current_user.id,
    )
    db.session.add(entry)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Evidence uploaded", entity_type="Evidence", entity_id=str(entry.id), new_values=entry.sha256_hash))
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        target.unlink(missing_ok=True)
        raise
    return jsonify(evidence=entry.to_dict()), 201


@evidence_bp.get("/evidence/<int:evidence_id>")
@login_required
def get_evidence(evidence_id):
    entry = db.get_or_404(Evidence, evidence_id)
    visible_case(entry.case_id, current_user)
    return jsonify(evidence=entry.to_dict())


@evidence_bp.put("/evidence/<int:evidence_id>")
@login_required
def update_evidence(evidence_id):
    entry = db.get_or_404(Evidence, evidence_id)
    case = visible_case(entry.case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    if "verification_status" in data:
        return jsonify(error="Evidence integrity status cannot be edited directly."), 400
    previous = {field: getattr(entry, field) for field in ("category", "description", "examination_status")}
    for field in ("category", "description", "examination_status"):
        if field in data:
            if not isinstance(data[field], str):
                return jsonify(error=f"{field.replace('_', ' ').capitalize()} must be text."), 400
            value = data[field].strip()
            if field == "category" and value not in EVIDENCE_CATEGORIES:
                return jsonify(error="Unsupported evidence category."), 400
            if field == "description" and len(value) > 10000:
                return jsonify(error="Evidence description must be at most 10,000 characters."), 400
            if field == "examination_status" and value not in {"Not examined", "In progress", "Examined"}:
                return jsonify(error="Unsupported examination status."), 400
            setattr(entry, field, value)
    current = {field: getattr(entry, field) for field in previous}
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Evidence metadata updated", entity_type="Evidence", entity_id=str(entry.id), previous_values=json.dumps(previous), new_values=json.dumps(current)))
    db.session.commit()
    return jsonify(evidence=entry.to_dict())


@evidence_bp.post("/evidence/<int:evidence_id>/verify-integrity")
@login_required
def verify_integrity(evidence_id):
    entry = db.get_or_404(Evidence, evidence_id)
    visible_case(entry.case_id, current_user)
    path = Path(entry.storage_path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    matches = actual == entry.sha256_hash
    if not matches:
        entry.verification_status = "Integrity discrepancy"
        db.session.add(AuditLog(actor_id=current_user.id, case_id=entry.case_id, action="Evidence integrity mismatch", entity_type="Evidence", entity_id=str(entry.id), previous_values=entry.sha256_hash, new_values=actual or "File missing"))
        db.session.commit()
    return jsonify(matches=matches, stored_hash=entry.sha256_hash, calculated_hash=actual,
                   message="A hash mismatch indicates a file-integrity discrepancy requiring investigation; it does not independently establish when, how, or why a change occurred." if not matches else "The calculated hash matches the stored upload hash.")


@evidence_bp.get("/evidence/<int:evidence_id>/download")
@login_required
def download_evidence(evidence_id):
    entry = db.get_or_404(Evidence, evidence_id)
    visible_case(entry.case_id, current_user)
    path = Path(entry.storage_path)
    if not path.is_file():
        return jsonify(error="Stored evidence file is unavailable."), 404
    response = send_file(path, mimetype=entry.mime_type, as_attachment=True, download_name=entry.original_filename, max_age=0, conditional=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@evidence_bp.get("/evidence/<int:evidence_id>/preview")
@login_required
def preview_evidence(evidence_id):
    entry = db.get_or_404(Evidence, evidence_id)
    visible_case(entry.case_id, current_user)
    if not entry.mime_type.startswith("image/"):
        return jsonify(error="Inline preview is available for image files only."), 415
    path = Path(entry.storage_path)
    if not path.is_file():
        return jsonify(error="Stored evidence file is unavailable."), 404
    response = send_file(path, mimetype=entry.mime_type, as_attachment=False, download_name=entry.original_filename, max_age=0, conditional=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_file
from flask_login import current_user, login_required

from extensions import db
from models import AuditLog, GeneratedReport
from routes.access import visible_case
from services.report_service import build_case_report


reports_bp = Blueprint("reports", __name__, url_prefix="/api")


@reports_bp.get("/cases/<int:case_id>/reports")
@login_required
def list_reports(case_id):
    visible_case(case_id, current_user)
    reports = GeneratedReport.query.filter_by(case_id=case_id).order_by(GeneratedReport.generated_at.desc()).all()
    return jsonify(items=[{"id": report.id, "report_type": report.report_type, "generated_at": report.generated_at.isoformat()} for report in reports])


@reports_bp.post("/cases/<int:case_id>/reports")
@login_required
def create_report(case_id):
    case = visible_case(case_id, current_user)
    if current_user.role == "Reviewer":
        return jsonify(error="Reviewer accounts cannot generate reports."), 403
    report_file = build_case_report(case)
    filename = f"{uuid.uuid4().hex}.pdf"
    path = Path(current_app.config["REPORT_FOLDER"]) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(report_file.getvalue())
    report = GeneratedReport(case_id=case.id, generated_by=current_user.id, storage_path=str(path.resolve()))
    db.session.add(report)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Case report generated", entity_type="GeneratedReport", entity_id=str(report.id)))
    db.session.commit()
    return jsonify(report={"id": report.id, "report_type": report.report_type, "generated_at": report.generated_at.isoformat()}), 201


@reports_bp.get("/reports/<int:report_id>/download")
@login_required
def download_report(report_id):
    report = db.get_or_404(GeneratedReport, report_id)
    visible_case(report.case_id, current_user)
    path = Path(report.storage_path)
    if not path.is_file():
        return jsonify(error="Generated report file is unavailable."), 404
    response = send_file(path, mimetype="application/pdf", as_attachment=True, download_name=f"ForenSight-{report.case_id}-{report.id}.pdf", max_age=0, conditional=False)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
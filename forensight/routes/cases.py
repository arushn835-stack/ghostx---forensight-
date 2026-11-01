import json
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from extensions import db
from models import AuditLog, Case, Evidence, InvestigationTask, User
from routes.access import json_object, require_edit, visible_case


cases_bp = Blueprint("cases", __name__, url_prefix="/api")
STATUSES = {"Open", "Under investigation", "Awaiting review", "Closed"}
PRIORITIES = {"Low", "Standard", "High", "Urgent"}
CASE_TYPES = {"Theft", "Assault", "Homicide", "Property damage", "Other"}


@cases_bp.get("/dashboard/stats")
@login_required
def dashboard_stats():
    query = Case.query.filter_by(archived=False)
    if current_user.role != "Administrator":
        query = query.filter_by(assigned_investigator_id=current_user.id)
    case_ids = [case.id for case in query.all()]
    return jsonify(
        active_cases=query.filter(Case.status != "Closed").count(),
        evidence_records=Evidence.query.filter(Evidence.case_id.in_(case_ids)).count() if case_ids else 0,
        pending_tasks=InvestigationTask.query.filter(
            InvestigationTask.case_id.in_(case_ids), InvestigationTask.status != "Completed"
        ).count() if case_ids else 0,
        awaiting_review=query.filter_by(status="Awaiting review").count(),
    )


@cases_bp.get("/cases")
@login_required
def list_cases():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 20, type=int), 1), 100)
    query = Case.query.filter_by(archived=False)
    if current_user.role != "Administrator":
        query = query.filter_by(assigned_investigator_id=current_user.id)
    search = request.args.get("q", "").strip()
    if search:
        query = query.filter(or_(Case.case_number.ilike(f"%{search}%"), Case.title.ilike(f"%{search}%")))
    if request.args.get("status"):
        query = query.filter_by(status=request.args["status"])
    pagination = query.order_by(Case.updated_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify(items=[case.to_dict() for case in pagination.items], page=page, pages=pagination.pages, total=pagination.total)


@cases_bp.post("/cases")
@login_required
def create_case():
    if current_user.role == "Reviewer":
        return jsonify(error="Reviewer accounts cannot create cases."), 403
    data = json_object()
    title_value = data.get("title", "")
    if not isinstance(title_value, str):
        return jsonify(error="Case title must be text."), 400
    title = title_value.strip()
    if not title or len(title) > 160:
        return jsonify(error="Case title is required and must be 160 characters or fewer."), 400
    case_number_value = data.get("case_number", "")
    if not isinstance(case_number_value, str):
        return jsonify(error="Case number must be text."), 400
    case_number = case_number_value.strip() or f"FS-{datetime.now().year}-{uuid.uuid4().hex[:8].upper()}"
    if len(case_number) > 40:
        return jsonify(error="Case number must be 40 characters or fewer."), 400
    if Case.query.filter_by(case_number=case_number).first():
        return jsonify(error="Case number is already in use."), 409
    assignee_id = current_user.id
    if current_user.role == "Administrator" and data.get("assigned_investigator_id"):
        try:
            assignee_id = int(data["assigned_investigator_id"])
        except (TypeError, ValueError):
            return jsonify(error="Assigned investigator is invalid."), 400
        assignee = db.session.get(User, assignee_id)
        if not assignee or assignee.role != "Investigator" or not assignee.is_active:
            return jsonify(error="Choose an active Investigator account."), 400
    case_type = data.get("case_type", "Other")
    priority = data.get("priority", "Standard")
    description = data.get("description", "")
    if not isinstance(case_type, str) or case_type not in CASE_TYPES:
        return jsonify(error="Unsupported case type."), 400
    if not isinstance(priority, str) or priority not in PRIORITIES:
        return jsonify(error="Unsupported case priority."), 400
    if not isinstance(description, str) or len(description) > 10000:
        return jsonify(error="Case description must be text with at most 10,000 characters."), 400
    case = Case(
        case_number=case_number, title=title, description=description.strip(),
        case_type=case_type,
        priority=priority,
        assigned_investigator_id=assignee_id,
    )
    db.session.add(case)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Case created", entity_type="Case", entity_id=str(case.id)))
    db.session.commit()
    return jsonify(case=case.to_dict()), 201


@cases_bp.get("/cases/<int:case_id>")
@login_required
def get_case(case_id):
    return jsonify(case=visible_case(case_id, current_user).to_dict())


@cases_bp.put("/cases/<int:case_id>")
@login_required
def update_case(case_id):
    case = visible_case(case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    previous = {field: getattr(case, field) for field in ("title", "description", "case_type", "status", "priority", "assigned_investigator_id")}
    for field in ("title", "description", "case_type", "priority"):
        if field in data:
            if not isinstance(data[field], str):
                return jsonify(error=f"{field.replace('_', ' ').capitalize()} must be text."), 400
            value = data[field].strip()
            maximum = {"title": 160, "case_type": 50, "priority": 20}.get(field)
            if maximum and len(value) > maximum:
                return jsonify(error=f"{field.replace('_', ' ').capitalize()} is too long."), 400
            if field == "title" and not value:
                return jsonify(error="Case title cannot be empty."), 400
            if field == "case_type" and value not in CASE_TYPES:
                return jsonify(error="Unsupported case type."), 400
            if field == "priority" and value not in PRIORITIES:
                return jsonify(error="Unsupported case priority."), 400
            if field == "description" and len(value) > 10000:
                return jsonify(error="Case description must be at most 10,000 characters."), 400
            setattr(case, field, value)
    if "status" in data:
        if not isinstance(data["status"], str) or data["status"] not in STATUSES:
            return jsonify(error="Unsupported case status."), 400
        case.status = data["status"]
    if "assigned_investigator_id" in data:
        if current_user.role != "Administrator":
            return jsonify(error="Only administrators can reassign cases."), 403
        try:
            assignee_id = int(data["assigned_investigator_id"])
        except (TypeError, ValueError):
            return jsonify(error="Assigned investigator is invalid."), 400
        assignee = db.session.get(User, assignee_id)
        if not assignee or assignee.role != "Investigator" or not assignee.is_active:
            return jsonify(error="Choose an active Investigator account."), 400
        case.assigned_investigator_id = assignee.id
    current = {field: getattr(case, field) for field in previous}
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Case updated", entity_type="Case", entity_id=str(case.id), previous_values=json.dumps(previous), new_values=json.dumps(current)))
    db.session.commit()
    return jsonify(case=case.to_dict())


@cases_bp.patch("/cases/<int:case_id>/status")
@login_required
def update_case_status(case_id):
    case = visible_case(case_id, current_user)
    require_edit(case, current_user)
    status = json_object().get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return jsonify(error="Unsupported case status."), 400
    previous = case.status
    case.status = status
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Case status updated", entity_type="Case", entity_id=str(case.id), previous_values=previous, new_values=status))
    db.session.commit()
    return jsonify(case=case.to_dict())


@cases_bp.get("/cases/<int:case_id>/audit-log")
@login_required
def case_audit_log(case_id):
    visible_case(case_id, current_user)
    entries = AuditLog.query.filter_by(case_id=case_id).order_by(AuditLog.timestamp.desc()).limit(100).all()
    return jsonify(items=[{
        "id": entry.id, "actor_id": entry.actor_id, "action": entry.action,
        "entity_type": entry.entity_type, "entity_id": entry.entity_id,
        "previous_values": entry.previous_values, "new_values": entry.new_values,
        "timestamp": entry.timestamp.isoformat(),
    } for entry in entries])

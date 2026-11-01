import json
import math
import re
import warnings
from datetime import datetime, timezone

import networkx as nx
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from PIL import Image, UnidentifiedImageError

from extensions import db
from models import (AnalysisResult, AuditLog, Evidence, EvidenceRelation, HandlingLog,
                    InvestigationTask, SceneMarker)
from routes.access import json_object, require_edit, visible_case
from services.contamination_analysis import analyze_handling_events


workflows_bp = Blueprint("workflows", __name__, url_prefix="/api")
HANDLING_ACTIONS = {"Collected", "Packaged", "Transferred", "Received", "Examined", "Stored", "Released", "Other"}
TASK_PRIORITIES = {"Low", "Standard", "High", "Urgent"}


def parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, AttributeError):
        return False


@workflows_bp.get("/cases/<int:case_id>/tasks")
@login_required
def list_tasks(case_id):
    visible_case(case_id, current_user)
    tasks = InvestigationTask.query.filter_by(case_id=case_id).order_by(InvestigationTask.due_date.asc()).all()
    return jsonify(items=[task.to_dict() for task in tasks])


@workflows_bp.post("/cases/<int:case_id>/tasks")
@login_required
def create_task(case_id):
    case = visible_case(case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    title_value = data.get("title", "")
    description = data.get("description", "")
    priority = data.get("priority", "Standard")
    if not isinstance(title_value, str) or not title_value.strip() or len(title_value) > 160:
        return jsonify(error="Task title is required and must be 160 characters or fewer."), 400
    if not isinstance(description, str) or len(description) > 10000:
        return jsonify(error="Task description must be text with at most 10,000 characters."), 400
    if not isinstance(priority, str) or priority not in TASK_PRIORITIES:
        return jsonify(error="Unsupported task priority."), 400
    title = title_value.strip()
    due_date = None
    if data.get("due_date"):
        try:
            due_date = datetime.strptime(data["due_date"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return jsonify(error="Due date must use YYYY-MM-DD."), 400
    task = InvestigationTask(case_id=case.id, title=title, description=description.strip(), due_date=due_date, assigned_to=current_user.id, priority=priority)
    db.session.add(task)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Investigation task created", entity_type="InvestigationTask", entity_id=str(task.id), new_values=json.dumps({"title": task.title, "priority": task.priority, "due_date": task.due_date.isoformat() if task.due_date else None})))
    db.session.commit()
    return jsonify(task=task.to_dict()), 201


@workflows_bp.patch("/tasks/<int:task_id>")
@login_required
def update_task(task_id):
    task = db.get_or_404(InvestigationTask, task_id)
    case = visible_case(task.case_id, current_user)
    require_edit(case, current_user)
    status = json_object().get("status")
    if not isinstance(status, str) or status not in {"Pending", "In progress", "Completed"}:
        return jsonify(error="Unsupported task status."), 400
    previous_status = task.status
    task.status = status
    task.completed_at = datetime.now(timezone.utc) if status == "Completed" else None
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Investigation task status updated", entity_type="InvestigationTask", entity_id=str(task.id), previous_values=previous_status, new_values=status))
    db.session.commit()
    return jsonify(task=task.to_dict())


@workflows_bp.get("/evidence/<int:evidence_id>/handling")
@login_required
def list_handling(evidence_id):
    evidence = db.get_or_404(Evidence, evidence_id)
    visible_case(evidence.case_id, current_user)
    events = HandlingLog.query.filter_by(evidence_id=evidence_id).order_by(HandlingLog.event_timestamp.asc().nullsfirst(), HandlingLog.created_at.asc()).all()
    return jsonify(items=[event.to_dict() for event in events])


@workflows_bp.post("/evidence/<int:evidence_id>/handling")
@login_required
def create_handling(evidence_id):
    evidence = db.get_or_404(Evidence, evidence_id)
    case = visible_case(evidence.case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    action = data.get("action")
    if not isinstance(action, str) or action not in HANDLING_ACTIONS:
        return jsonify(error="Unsupported handling action."), 400
    timestamp = parse_timestamp(data.get("event_timestamp"))
    if timestamp is False:
        return jsonify(error="Timestamp must be a valid ISO-8601 date/time."), 400
    text_fields = {
        "recorded_location": (180, "Recorded location"),
        "previous_custodian": (120, "Previous custodian"),
        "new_custodian": (120, "New custodian"),
        "packaging_information": (10000, "Packaging information"),
        "equipment_information": (10000, "Equipment information"),
        "notes": (10000, "Notes"),
    }
    for field, (maximum, label) in text_fields.items():
        if field in data and not isinstance(data[field], str):
            return jsonify(error=f"{label} must be text."), 400
        if len(data.get(field, "")) > maximum:
            return jsonify(error=f"{label} is too long."), 400
    event = HandlingLog(
        case_id=case.id, evidence_id=evidence.id, actor_id=current_user.id, action=action,
        event_timestamp=timestamp, recorded_location=str(data.get("recorded_location", "")),
        previous_custodian=str(data.get("previous_custodian", "")), new_custodian=str(data.get("new_custodian", "")),
        packaging_information=str(data.get("packaging_information", "")),
        equipment_information=str(data.get("equipment_information", "")), notes=str(data.get("notes", "")),
    )
    db.session.add(event)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Handling event recorded", entity_type="HandlingLog", entity_id=str(event.id)))
    db.session.commit()
    return jsonify(event=event.to_dict()), 201


@workflows_bp.get("/evidence/<int:evidence_id>/risk-checks")
@login_required
def handling_risk_checks(evidence_id):
    evidence = db.get_or_404(Evidence, evidence_id)
    visible_case(evidence.case_id, current_user)
    events = HandlingLog.query.filter_by(evidence_id=evidence_id).order_by(HandlingLog.created_at.asc()).all()
    warnings = analyze_handling_events(events)
    return jsonify(screening="Documentation screening for human review; a warning does not prove contamination occurred.", warnings=warnings)


@workflows_bp.patch("/handling/<int:event_id>/review")
@login_required
def review_handling(event_id):
    event = db.get_or_404(HandlingLog, event_id)
    case = visible_case(event.case_id, current_user)
    data = json_object()
    if not isinstance(data.get("review_status"), str) or data["review_status"] not in {"Needs review", "Reviewed", "Resolved"}:
        return jsonify(error="Unsupported review status."), 400
    previous = {"review_status": event.review_status, "reviewer_notes": event.reviewer_notes}
    event.review_status = data["review_status"]
    event.reviewer_notes = str(data.get("reviewer_notes", ""))
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Handling prompt reviewed", entity_type="HandlingLog", entity_id=str(event.id), previous_values=json.dumps(previous), new_values=json.dumps({"review_status": event.review_status, "reviewer_notes": event.reviewer_notes})))
    db.session.commit()
    return jsonify(event=event.to_dict())


@workflows_bp.get("/cases/<int:case_id>/relationships")
@login_required
def list_relationships(case_id):
    visible_case(case_id, current_user)
    relations = EvidenceRelation.query.filter_by(case_id=case_id).all()
    return jsonify(items=[relation.to_dict() for relation in relations])


@workflows_bp.post("/cases/<int:case_id>/relationships")
@login_required
def create_relationship(case_id):
    case = visible_case(case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    try:
        source_id = int(data.get("source_evidence_id"))
        target_id = int(data.get("target_evidence_id"))
    except (TypeError, ValueError):
        return jsonify(error="Source and target evidence identifiers are required."), 400
    source = db.get_or_404(Evidence, source_id)
    target = db.get_or_404(Evidence, target_id)
    if source.case_id != case.id or target.case_id != case.id:
        return jsonify(error="Both evidence records must belong to this case."), 400
    if source.id == target.id:
        return jsonify(error="A relationship requires two different evidence records."), 400
    relation_type_value = data.get("relationship_type", "")
    if not isinstance(relation_type_value, str) or not relation_type_value.strip() or len(relation_type_value) > 80:
        return jsonify(error="Relationship type is required."), 400
    relation_type = relation_type_value.strip()
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 10000:
        return jsonify(error="Relationship description must be text with at most 10,000 characters."), 400
    relation = EvidenceRelation(
        case_id=case.id, source_evidence_id=source.id, target_evidence_id=target.id,
        relationship_type=relation_type, description=description.strip(),
        source_type="Investigator recorded", created_by=current_user.id,
    )
    db.session.add(relation)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Evidence relationship created", entity_type="EvidenceRelation", entity_id=str(relation.id)))
    db.session.commit()
    return jsonify(relationship=relation.to_dict()), 201


@workflows_bp.patch("/relationships/<int:relation_id>")
@login_required
def review_relationship(relation_id):
    relation = db.get_or_404(EvidenceRelation, relation_id)
    case = visible_case(relation.case_id, current_user)
    data = json_object()
    previous = {"verification_status": relation.verification_status, "reviewer_notes": relation.reviewer_notes}
    if "verification_status" in data:
        if not isinstance(data["verification_status"], str) or data["verification_status"] not in {"Unreviewed", "Accepted", "Rejected", "Needs review"}:
            return jsonify(error="Unsupported verification status."), 400
        relation.verification_status = data["verification_status"]
    relation.reviewer_notes = str(data.get("reviewer_notes", relation.reviewer_notes))
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Evidence relationship reviewed", entity_type="EvidenceRelation", entity_id=str(relation.id), previous_values=json.dumps(previous), new_values=json.dumps({"verification_status": relation.verification_status, "reviewer_notes": relation.reviewer_notes})))
    db.session.commit()
    return jsonify(relationship=relation.to_dict())


@workflows_bp.post("/cases/<int:case_id>/analyze-report")
@login_required
def analyze_case_references(case_id):
    case = visible_case(case_id, current_user)
    known = {item.evidence_number.casefold(): item for item in Evidence.query.filter_by(case_id=case.id).all()}
    documents = [("Case description", case.description or "", None)]
    documents.extend((item.evidence_number, item.description or "", item.id) for item in known.values())
    references = []
    warnings = []
    pattern = re.compile(r"\bEV-[A-Z0-9]{6,12}\b", re.IGNORECASE)
    for source_label, text, source_id in documents:
        for match in pattern.finditer(text):
            identifier = match.group(0).upper()
            if identifier in {key.upper() for key in known}:
                references.append({"source": source_label, "source_evidence_id": source_id, "referenced_evidence_number": identifier, "match_type": "Recorded identifier reference"})
            else:
                warnings.append({"rule": "EL-001", "source": source_label, "source_evidence_id": source_id, "referenced_identifier": identifier, "explanation": "Text references an evidence identifier that is not present in this case. Confirm the identifier and case scope."})
    return jsonify(
        nlp={"available": False, "message": "spaCy and a configured language model are not installed. Only explicit evidence-ID patterns were checked; names, dates, places, and organizations were not extracted."},
        references=references,
        warnings=warnings,
    )


@workflows_bp.get("/cases/<int:case_id>/evidence-graph")
@login_required
def evidence_graph(case_id):
    visible_case(case_id, current_user)
    evidence_items = Evidence.query.filter_by(case_id=case_id).all()
    relations = EvidenceRelation.query.filter_by(case_id=case_id).all()
    graph = nx.MultiGraph()
    for item in evidence_items:
        graph.add_node(item.id, label=item.evidence_number, category=item.category)
    for relation in relations:
        graph.add_edge(
            relation.source_evidence_id,
            relation.target_evidence_id,
            key=relation.id,
            relation_id=relation.id,
            label=relation.relationship_type,
            source_type=relation.source_type,
            verification_status=relation.verification_status,
        )
    return jsonify(
        nodes=[{"id": node, **data} for node, data in graph.nodes(data=True)],
        edges=[
            {"source": source, "target": target, "key": key, **data}
            for source, target, key, data in graph.edges(keys=True, data=True)
        ],
    )


@workflows_bp.get("/cases/<int:case_id>/scene-markers")
@login_required
def list_markers(case_id):
    visible_case(case_id, current_user)
    markers = SceneMarker.query.filter_by(case_id=case_id).all()
    return jsonify(items=[marker.to_dict() for marker in markers], reconstruction={"available": False, "message": "COLMAP reconstruction is not configured. This view uses manually entered approximate positions."})


@workflows_bp.post("/cases/<int:case_id>/scene-markers")
@login_required
def create_marker(case_id):
    case = visible_case(case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    try:
        evidence_id = int(data.get("evidence_id"))
    except (TypeError, ValueError):
        return jsonify(error="Evidence identifier is required."), 400
    evidence = db.get_or_404(Evidence, evidence_id)
    if evidence.case_id != case.id:
        return jsonify(error="Evidence must belong to this case."), 400
    try:
        coords = [float(data[key]) for key in ("x", "y", "z")]
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Enter valid x, y, and z coordinates."), 400
    if not all(math.isfinite(value) for value in coords):
        return jsonify(error="Scene coordinates must be finite numbers."), 400
    label_value = data.get("label", "")
    description = data.get("description", "")
    if not isinstance(label_value, str) or len(label_value) > 120:
        return jsonify(error="Marker label must be text with at most 120 characters."), 400
    if not isinstance(description, str) or len(description) > 10000:
        return jsonify(error="Marker description must be text with at most 10,000 characters."), 400
    label = label_value.strip() or evidence.evidence_number
    marker = SceneMarker(case_id=case.id, evidence_id=evidence.id, x=coords[0], y=coords[1], z=coords[2], label=label, description=description.strip(), created_by=current_user.id)
    db.session.add(marker)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Scene marker created", entity_type="SceneMarker", entity_id=str(marker.id), new_values=json.dumps({"x": marker.x, "y": marker.y, "z": marker.z, "label": marker.label})))
    db.session.commit()
    return jsonify(marker=marker.to_dict()), 201


@workflows_bp.put("/scene-markers/<int:marker_id>")
@login_required
def update_marker(marker_id):
    marker = db.get_or_404(SceneMarker, marker_id)
    case = visible_case(marker.case_id, current_user)
    require_edit(case, current_user)
    data = json_object()
    previous = {"x": marker.x, "y": marker.y, "z": marker.z, "label": marker.label, "description": marker.description}
    for key in ("x", "y", "z"):
        if key in data:
            try:
                coordinate = float(data[key])
            except (TypeError, ValueError):
                return jsonify(error=f"{key} must be a number."), 400
            if not math.isfinite(coordinate):
                return jsonify(error=f"{key} must be a finite number."), 400
            setattr(marker, key, coordinate)
    if "label" in data:
        if not isinstance(data["label"], str) or len(data["label"]) > 120 or not data["label"].strip():
            return jsonify(error="Marker label must be non-empty text with at most 120 characters."), 400
        marker.label = data["label"].strip()
    if "description" in data:
        if not isinstance(data["description"], str) or len(data["description"]) > 10000:
            return jsonify(error="Marker description must be text with at most 10,000 characters."), 400
        marker.description = data["description"].strip()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Scene marker updated", entity_type="SceneMarker", entity_id=str(marker.id), previous_values=json.dumps(previous), new_values=json.dumps({"x": marker.x, "y": marker.y, "z": marker.z, "label": marker.label, "description": marker.description})))
    db.session.commit()
    return jsonify(marker=marker.to_dict())


@workflows_bp.delete("/scene-markers/<int:marker_id>")
@login_required
def delete_marker(marker_id):
    marker = db.get_or_404(SceneMarker, marker_id)
    case = visible_case(marker.case_id, current_user)
    require_edit(case, current_user)
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Scene marker deleted", entity_type="SceneMarker", entity_id=str(marker.id), previous_values=json.dumps({"x": marker.x, "y": marker.y, "z": marker.z, "label": marker.label, "description": marker.description})))
    db.session.delete(marker)
    db.session.commit()
    return jsonify(ok=True)


@workflows_bp.post("/cases/<int:case_id>/reconstruction")
@login_required
def reconstruction_unavailable(case_id):
    visible_case(case_id, current_user)
    return jsonify(status="unavailable", message="COLMAP is not configured; no reconstruction was run or generated.") , 501


@workflows_bp.post("/evidence/<int:evidence_id>/analyze")
@login_required
def analyze_evidence(evidence_id):
    evidence = db.get_or_404(Evidence, evidence_id)
    case = visible_case(evidence.case_id, current_user)
    require_edit(case, current_user)
    if not evidence.mime_type.startswith("image/"):
        return jsonify(error="Image metadata analysis is available for image evidence only."), 415
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(evidence.storage_path) as image:
                if image.width * image.height > current_app.config["MAX_IMAGE_PIXELS"]:
                    return jsonify(error="Image exceeds the configured pixel limit."), 422
                result = {"width": image.width, "height": image.height, "format": image.format, "mode": image.mode}
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, UnidentifiedImageError, ValueError):
        return jsonify(error="The stored image could not be decoded."), 422
    analysis = AnalysisResult(case_id=case.id, evidence_id=evidence.id, analysis_type="Image metadata", model_name="Pillow", model_version="runtime", result_json=json.dumps(result), review_status="Unreviewed")
    db.session.add(analysis)
    db.session.flush()
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Image metadata analyzed", entity_type="AnalysisResult", entity_id=str(analysis.id)))
    db.session.commit()
    return jsonify(analysis={"id": analysis.id, "analysis_type": analysis.analysis_type, "result": result, "review_status": analysis.review_status}, object_detection={"available": False, "message": "No object-detection model is configured. No detections were generated."}), 201


@workflows_bp.get("/evidence/<int:evidence_id>/analysis")
@login_required
def list_analysis(evidence_id):
    evidence = db.get_or_404(Evidence, evidence_id)
    visible_case(evidence.case_id, current_user)
    items = AnalysisResult.query.filter_by(evidence_id=evidence.id).order_by(AnalysisResult.created_at.desc()).all()
    return jsonify(items=[{"id": item.id, "analysis_type": item.analysis_type, "model_name": item.model_name, "result": json.loads(item.result_json), "review_status": item.review_status, "created_at": item.created_at.isoformat()} for item in items])


@workflows_bp.patch("/analysis/<int:analysis_id>/review")
@login_required
def review_analysis(analysis_id):
    analysis = db.get_or_404(AnalysisResult, analysis_id)
    case = visible_case(analysis.case_id, current_user)
    data = json_object()
    if not isinstance(data.get("review_status"), str) or data["review_status"] not in {"Accepted", "Rejected", "Needs review"}:
        return jsonify(error="Unsupported review status."), 400
    previous_status = analysis.review_status
    analysis.review_status = data["review_status"]
    analysis.reviewed_by = current_user.id
    analysis.reviewed_at = datetime.now(timezone.utc)
    db.session.add(AuditLog(actor_id=current_user.id, case_id=case.id, action="Analysis result reviewed", entity_type="AnalysisResult", entity_id=str(analysis.id), previous_values=previous_status, new_values=analysis.review_status))
    db.session.commit()
    return jsonify(ok=True, review_status=analysis.review_status)
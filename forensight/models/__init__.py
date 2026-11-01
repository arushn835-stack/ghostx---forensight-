from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(24), nullable=False, default="Investigator")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "email": self.email, "role": self.role, "is_active": self.is_active, "created_at": self.created_at.isoformat()}


class Case(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    case_type = db.Column(db.String(50), nullable=False, default="Other")
    status = db.Column(db.String(40), nullable=False, default="Open", index=True)
    priority = db.Column(db.String(20), nullable=False, default="Standard")
    assigned_investigator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    investigator = db.relationship("User", backref="cases")

    def to_dict(self):
        return {
            "id": self.id,
            "case_number": self.case_number,
            "title": self.title,
            "description": self.description,
            "case_type": self.case_type,
            "status": self.status,
            "priority": self.priority,
            "assigned_investigator_id": self.assigned_investigator_id,
            "investigator": self.investigator.username,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class Evidence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evidence_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False, default="Other")
    description = db.Column(db.Text, default="")
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    storage_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(120), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    sha256_hash = db.Column(db.String(64), nullable=False)
    collected_at = db.Column(db.DateTime(timezone=True))
    uploaded_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    examination_status = db.Column(db.String(40), nullable=False, default="Not examined")
    verification_status = db.Column(db.String(40), nullable=False, default="Unreviewed")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    case = db.relationship("Case", backref="evidence")
    creator = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "evidence_number": self.evidence_number,
            "case_id": self.case_id,
            "case_number": self.case.case_number,
            "category": self.category,
            "description": self.description,
            "original_filename": self.original_filename,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "sha256_hash": self.sha256_hash,
            "uploaded_at": self.uploaded_at.isoformat(),
            "examination_status": self.examination_status,
            "verification_status": self.verification_status,
        }


class InvestigationTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(30), nullable=False, default="Pending")
    priority = db.Column(db.String(20), nullable=False, default="Standard")
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    due_date = db.Column(db.Date)
    completed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    case = db.relationship("Case", backref="tasks")
    assignee = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id, "case_id": self.case_id, "title": self.title,
            "description": self.description, "status": self.status,
            "priority": self.priority, "due_date": self.due_date.isoformat() if self.due_date else None,
            "assigned_to": self.assignee.username,
        }


class EvidenceRelation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False, index=True)
    source_evidence_id = db.Column(db.Integer, db.ForeignKey("evidence.id"), nullable=False)
    target_evidence_id = db.Column(db.Integer, db.ForeignKey("evidence.id"), nullable=False)
    relationship_type = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, default="")
    source_type = db.Column(db.String(30), nullable=False, default="Investigator recorded")
    verification_status = db.Column(db.String(30), nullable=False, default="Unreviewed")
    reviewer_notes = db.Column(db.Text, default="")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    source = db.relationship("Evidence", foreign_keys=[source_evidence_id])
    target = db.relationship("Evidence", foreign_keys=[target_evidence_id])
    case = db.relationship("Case", backref="relationships")
    creator = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id, "source": self.source.to_dict(), "target": self.target.to_dict(),
            "relationship_type": self.relationship_type, "description": self.description,
            "source_type": self.source_type, "verification_status": self.verification_status,
            "reviewer_notes": self.reviewer_notes,
        }


class HandlingLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False, index=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidence.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    event_timestamp = db.Column(db.DateTime(timezone=True))
    recorded_location = db.Column(db.String(180), default="")
    previous_custodian = db.Column(db.String(120), default="")
    new_custodian = db.Column(db.String(120), default="")
    packaging_information = db.Column(db.Text, default="")
    equipment_information = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    review_status = db.Column(db.String(30), nullable=False, default="Unreviewed")
    reviewer_notes = db.Column(db.Text, default="")
    evidence = db.relationship("Evidence", backref="handling_events")
    actor = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id, "evidence_id": self.evidence_id, "action": self.action,
            "event_timestamp": self.event_timestamp.isoformat() if self.event_timestamp else None,
            "recorded_location": self.recorded_location, "previous_custodian": self.previous_custodian,
            "new_custodian": self.new_custodian, "packaging_information": self.packaging_information,
            "equipment_information": self.equipment_information, "notes": self.notes,
            "actor": self.actor.username, "review_status": self.review_status,
            "reviewer_notes": self.reviewer_notes,
        }


class SceneMarker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False, index=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidence.id"), nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    z = db.Column(db.Float, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    evidence = db.relationship("Evidence", backref="scene_markers")

    def to_dict(self):
        return {
            "id": self.id, "case_id": self.case_id, "evidence_id": self.evidence_id,
            "evidence_number": self.evidence.evidence_number, "x": self.x, "y": self.y,
            "z": self.z, "label": self.label, "description": self.description,
        }


class AnalysisResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidence.id"), nullable=False)
    analysis_type = db.Column(db.String(60), nullable=False)
    model_name = db.Column(db.String(120), nullable=False)
    model_version = db.Column(db.String(80), default="")
    result_json = db.Column(db.Text, nullable=False)
    confidence = db.Column(db.Float)
    review_status = db.Column(db.String(30), nullable=False, default="Unreviewed")
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class GeneratedReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), nullable=False, index=True)
    generated_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    report_type = db.Column(db.String(40), nullable=False, default="Case summary")
    storage_path = db.Column(db.String(500), nullable=False)
    generated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    case_id = db.Column(db.Integer, db.ForeignKey("case.id"), index=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(60), nullable=False)
    previous_values = db.Column(db.Text, default="")
    new_values = db.Column(db.Text, default="")
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

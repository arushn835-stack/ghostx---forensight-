import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import (AnalysisResult, AuditLog, Case, Evidence, EvidenceRelation,
                    GeneratedReport, HandlingLog, InvestigationTask, SceneMarker,
                    User)
from extensions import db


def seed_demo_data(username, upload_folder):
    user = User.query.filter_by(username=username).first()
    if not user or user.role == "Reviewer":
        raise ValueError("Choose an existing Administrator or Investigator account.")
    if Case.query.filter(Case.case_number.in_(["DEMO-2026-001", "DEMO-2026-002"])).first():
        raise ValueError("Demonstration case numbers already exist; no data was added.")

    cases = [
        Case(case_number="DEMO-2026-001", title="Fictional studio inventory", description="FICTIONAL DEMONSTRATION CASE. No real incident or evidence.", case_type="Theft", status="Under investigation", priority="Standard", assigned_investigator_id=user.id),
        Case(case_number="DEMO-2026-002", title="Fictional archive review", description="FICTIONAL DEMONSTRATION CASE. Use only to explore application workflows.", case_type="Property damage", status="Open", priority="Low", assigned_investigator_id=user.id),
    ]
    db.session.add_all(cases)
    db.session.flush()
    evidence_by_case = {}
    base = Path(upload_folder)
    base.mkdir(parents=True, exist_ok=True)
    for case_index, case in enumerate(cases, start=1):
        entries = []
        for index, artifact in enumerate(("scene-notes", "inventory-sheet"), start=1):
            content = (
                "FORENSIGHT FICTIONAL DEMONSTRATION ARTIFACT\n"
                "Not real evidence. Not associated with a real person, incident, or investigation.\n"
                f"Demo case: {case.case_number}\nArtifact: {artifact}\n"
            ).encode("utf-8")
            stored_name = f"demo-{uuid.uuid4().hex}.txt"
            path = base / stored_name
            path.write_bytes(content)
            entry = Evidence(
                evidence_number=f"DEMO-EV-{case_index}{index:02d}", case_id=case.id,
                category="Document", description=f"FICTIONAL DEMO ONLY: synthetic {artifact.replace('-', ' ')}.",
                original_filename=f"{artifact}.txt", stored_filename=stored_name,
                storage_path=str(path.resolve()), mime_type="text/plain", file_size=len(content),
                sha256_hash=hashlib.sha256(content).hexdigest(), created_by=user.id,
            )
            db.session.add(entry)
            entries.append(entry)
        evidence_by_case[case.id] = entries
    db.session.flush()

    for case_index, case in enumerate(cases):
        first, second = evidence_by_case[case.id]
        db.session.add_all([
            InvestigationTask(case_id=case.id, title="Review synthetic scene notes", description="Fictional workflow example only.", priority="Standard", assigned_to=user.id, due_date=(datetime.now(timezone.utc) + timedelta(days=7 + case_index)).date()),
            InvestigationTask(case_id=case.id, title="Prepare demonstration summary", description="Example checklist task; not an approved procedure.", priority="Low", assigned_to=user.id),
            EvidenceRelation(case_id=case.id, source_evidence_id=first.id, target_evidence_id=second.id, relationship_type="Demo link only", description="Fictional demonstration relationship; not an inference.", source_type="Simulated demonstration data", created_by=user.id),
            SceneMarker(case_id=case.id, evidence_id=first.id, x=-1.2 + case_index, y=0.1, z=0.8, label="DEMO MARKER", description="Fictional approximate coordinate.", created_by=user.id),
            AnalysisResult(case_id=case.id, evidence_id=first.id, analysis_type="Simulated demonstration", model_name="SIMULATED / DEMO ONLY", model_version="not a model run", result_json=json.dumps({"simulated": True, "note": "Fictional placeholder for UI demonstration. No AI analysis was performed."}), review_status="Unreviewed"),
        ])
        db.session.add(HandlingLog(
            case_id=case.id, evidence_id=first.id, actor_id=user.id, action="Collected",
            event_timestamp=datetime.now(timezone.utc), recorded_location="Fictional demonstration location",
            packaging_information="Synthetic example only", notes="FICTIONAL DEMO DATA.",
        ))
        db.session.add(HandlingLog(
            case_id=case.id, evidence_id=first.id, actor_id=user.id, action="Transferred",
            event_timestamp=datetime.now(timezone.utc) + timedelta(minutes=10), recorded_location="Fictional demonstration location",
            previous_custodian=user.username, new_custodian="Demo examiner", packaging_information="Synthetic example only",
        ))
    db.session.commit()
    return len(cases)


def remove_demo_data(upload_folder, report_folder):
    cases = Case.query.filter(Case.case_number.in_(
        ["DEMO-2026-001", "DEMO-2026-002"]
    )).all()
    if not cases:
        return 0
    case_ids = [case.id for case in cases]
    evidence = Evidence.query.filter(Evidence.case_id.in_(case_ids)).all()
    reports = GeneratedReport.query.filter(GeneratedReport.case_id.in_(case_ids)).all()
    evidence_paths = [(entry.storage_path, entry.stored_filename) for entry in evidence]
    report_paths = [report.storage_path for report in reports]

    AnalysisResult.query.filter(AnalysisResult.case_id.in_(case_ids)).delete(synchronize_session=False)
    SceneMarker.query.filter(SceneMarker.case_id.in_(case_ids)).delete(synchronize_session=False)
    EvidenceRelation.query.filter(EvidenceRelation.case_id.in_(case_ids)).delete(synchronize_session=False)
    HandlingLog.query.filter(HandlingLog.case_id.in_(case_ids)).delete(synchronize_session=False)
    InvestigationTask.query.filter(InvestigationTask.case_id.in_(case_ids)).delete(synchronize_session=False)
    GeneratedReport.query.filter(GeneratedReport.case_id.in_(case_ids)).delete(synchronize_session=False)
    AuditLog.query.filter(AuditLog.case_id.in_(case_ids)).delete(synchronize_session=False)
    Evidence.query.filter(Evidence.case_id.in_(case_ids)).delete(synchronize_session=False)
    Case.query.filter(Case.id.in_(case_ids)).delete(synchronize_session=False)
    db.session.commit()

    upload_root = Path(upload_folder).resolve()
    for path_value, stored_name in evidence_paths:
        path = Path(path_value).resolve()
        if stored_name.startswith("demo-") and path.is_relative_to(upload_root) and path.is_file():
            path.unlink()
    report_root = Path(report_folder).resolve()
    for path_value in report_paths:
        path = Path(path_value).resolve()
        if path.is_relative_to(report_root) and path.is_file():
            path.unlink()
    return len(cases)
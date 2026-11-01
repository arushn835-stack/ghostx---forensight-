import io

import pytest
from PIL import Image

from app import create_app
from extensions import db
from models import User


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "UPLOAD_FOLDER": tmp_path / "uploads",
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
    with app.test_client() as test_client:
        yield test_client
    with app.app_context():
        db.drop_all()


def create_case(client, title="Scene examination"):
    client.post("/api/auth/register", json={
        "username": "investigator", "email": "investigator@example.test", "password": "long-secure-passphrase"
    })
    response = client.post("/api/cases", json={"title": title})
    assert response.status_code == 201
    return response.json["case"]["id"]


def upload_png(client, case_id):
    image = Image.new("RGB", (6, 4), color=(170, 120, 45))
    file_data = io.BytesIO()
    image.save(file_data, format="PNG")
    file_data.seek(0)
    response = client.post(
        f"/api/cases/{case_id}/evidence",
        data={"file": (file_data, "sample.png"), "category": "Photograph", "description": "Test image"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    return response.json["evidence"]


def test_case_access_is_scoped_to_assigned_investigator(client):
    case_id = create_case(client)
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={
        "username": "reviewer", "email": "reviewer@example.test", "password": "another-secure-passphrase"
    })
    assert client.get(f"/api/cases/{case_id}").status_code == 404


def test_upload_hash_and_integrity_verification(client):
    case_id = create_case(client)
    evidence = upload_png(client, case_id)
    assert len(evidence["sha256_hash"]) == 64
    forged_status = client.put(f"/api/evidence/{evidence['id']}", json={"verification_status": "Verified"})
    assert forged_status.status_code == 400
    download = client.get(f"/api/evidence/{evidence['id']}/download")
    assert download.status_code == 200
    assert "no-store" in download.headers["Cache-Control"]
    assert client.post(f"/api/evidence/{evidence['id']}/verify-integrity").json["matches"] is True
    with client.application.app_context():
        from models import Evidence
        record = db.session.get(Evidence, evidence["id"])
        with open(record.storage_path, "ab") as stored:
            stored.write(b"changed")
    response = client.post(f"/api/evidence/{evidence['id']}/verify-integrity")
    assert response.json["matches"] is False
    assert "does not independently establish" in response.json["message"]


def test_invalid_file_content_is_rejected(client):
    case_id = create_case(client)
    response = client.post(
        f"/api/cases/{case_id}/evidence",
        data={"file": (io.BytesIO(b"not an image"), "bad.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_image_upload_rejects_excessive_pixel_dimensions(monkeypatch):
    from routes.evidence import validate_upload

    class LargeImage:
        format = "PNG"
        width = 11
        height = 10

    monkeypatch.setattr("routes.evidence.Image.open", lambda _content: LargeImage())
    assert validate_upload("large.png", b"image-header", max_image_pixels=100) is None


def test_image_analysis_enforces_pixel_limit(client):
    case_id = create_case(client)
    evidence = upload_png(client, case_id)
    client.application.config["MAX_IMAGE_PIXELS"] = 1
    response = client.post(f"/api/evidence/{evidence['id']}/analyze")
    assert response.status_code == 422
    assert "pixel limit" in response.json["error"]


def test_case_creation_rejects_unhashable_priority_value(client):
    client.post("/api/auth/register", json={
        "username": "casecreator", "email": "casecreator@example.test", "password": "long-secure-passphrase"
    })
    response = client.post("/api/cases", json={"title": "Malformed priority", "priority": []})
    assert response.status_code == 400


def test_case_update_persists_metadata_and_status(client):
    case_id = create_case(client)
    updated = client.put(f"/api/cases/{case_id}", json={
        "title": "Updated case title", "status": "Awaiting review", "priority": "High",
    })
    assert updated.status_code == 200
    assert updated.json["case"]["title"] == "Updated case title"
    assert updated.json["case"]["status"] == "Awaiting review"
    assert updated.json["case"]["priority"] == "High"
    invalid = client.put(f"/api/cases/{case_id}", json={"title": "  "})
    assert invalid.status_code == 400


def test_case_list_api_paginates(client):
    client.post("/api/auth/register", json={
        "username": "pageuser", "email": "pageuser@example.test", "password": "long-secure-passphrase"
    })
    for index in range(21):
        response = client.post("/api/cases", json={"title": f"Page test {index}"})
        assert response.status_code == 201
    first_page = client.get("/api/cases?page=1&per_page=20").json
    second_page = client.get("/api/cases?page=2&per_page=20").json
    assert first_page["pages"] == 2
    assert len(first_page["items"]) == 20
    assert len(second_page["items"]) == 1


def test_tasks_handling_relationship_graph_and_markers_persist(client):
    case_id = create_case(client)
    first = upload_png(client, case_id)
    second = upload_png(client, case_id)
    task_response = client.post(f"/api/cases/{case_id}/tasks", json={"title": "Review scene photos"})
    assert task_response.status_code == 201
    completed = client.patch(f"/api/tasks/{task_response.json['task']['id']}", json={"status": "Completed"})
    assert completed.status_code == 200
    assert completed.json["task"]["status"] == "Completed"
    event = client.post(f"/api/evidence/{first['id']}/handling", json={"action": "Transferred"})
    assert event.status_code == 201
    warnings = client.get(f"/api/evidence/{first['id']}/risk-checks").json["warnings"]
    assert {warning["rule"] for warning in warnings} >= {"TG-002", "TG-003", "TG-004"}
    relation = client.post(f"/api/cases/{case_id}/relationships", json={
        "source_evidence_id": first["id"], "target_evidence_id": second["id"],
        "relationship_type": "Investigator-proposed connection",
    })
    assert relation.status_code == 201
    graph = client.get(f"/api/cases/{case_id}/evidence-graph").json
    assert len(graph["nodes"]) == 2 and len(graph["edges"]) == 1
    marker = client.post(f"/api/cases/{case_id}/scene-markers", json={
        "evidence_id": first["id"], "x": 1.2, "y": 0.4, "z": -2, "label": "North corner"
    })
    assert marker.status_code == 201
    assert client.get(f"/api/cases/{case_id}/scene-markers").json["items"][0]["z"] == -2


def test_graph_preserves_multiple_relationships_for_the_same_pair(client):
    case_id = create_case(client)
    first = upload_png(client, case_id)
    second = upload_png(client, case_id)
    for relation_type in ("Same recorded location", "Mentioned in same report"):
        response = client.post(f"/api/cases/{case_id}/relationships", json={
            "source_evidence_id": first["id"],
            "target_evidence_id": second["id"],
            "relationship_type": relation_type,
        })
        assert response.status_code == 201
    graph = client.get(f"/api/cases/{case_id}/evidence-graph").json
    assert len(graph["edges"]) == 2
    assert {edge["label"] for edge in graph["edges"]} == {"Same recorded location", "Mentioned in same report"}


def test_traceguard_detects_entry_timestamp_regression(client):
    case_id = create_case(client)
    evidence = upload_png(client, case_id)
    client.post(f"/api/evidence/{evidence['id']}/handling", json={"action": "Collected", "event_timestamp": "2025-02-02T10:00:00Z"})
    client.post(f"/api/evidence/{evidence['id']}/handling", json={"action": "Transferred", "event_timestamp": "2025-02-01T10:00:00Z", "new_custodian": "Examiner"})
    warnings = client.get(f"/api/evidence/{evidence['id']}/risk-checks").json["warnings"]
    assert any(warning["rule"] == "TG-006" for warning in warnings)


def test_traceguard_flags_packaging_and_equipment_gaps(client):
    case_id = create_case(client)
    evidence = upload_png(client, case_id)
    client.post(f"/api/evidence/{evidence['id']}/handling", json={"action": "Packaged"})
    client.post(f"/api/evidence/{evidence['id']}/handling", json={"action": "Examined"})
    warnings = client.get(f"/api/evidence/{evidence['id']}/risk-checks").json["warnings"]
    assert {warning["rule"] for warning in warnings} >= {"TG-005", "TG-008"}


def test_scene_marker_rejects_non_finite_coordinates(client):
    case_id = create_case(client)
    evidence = upload_png(client, case_id)
    response = client.post(f"/api/cases/{case_id}/scene-markers", json={
        "evidence_id": evidence["id"], "x": "nan", "y": 0, "z": 0,
    })
    assert response.status_code == 400


def test_assigned_reviewer_can_review_relationship(client):
    case_id = create_case(client)
    first = upload_png(client, case_id)
    second = upload_png(client, case_id)
    relation = client.post(f"/api/cases/{case_id}/relationships", json={
        "source_evidence_id": first["id"], "target_evidence_id": second["id"], "relationship_type": "same report"
    }).json["relationship"]
    with client.application.app_context():
        user = User.query.filter_by(username="investigator").one()
        user.role = "Reviewer"
        db.session.commit()
    response = client.patch(f"/api/relationships/{relation['id']}", json={"verification_status": "Accepted", "reviewer_notes": "Reviewed against source record."})
    assert response.status_code == 200
    assert response.json["relationship"]["verification_status"] == "Accepted"
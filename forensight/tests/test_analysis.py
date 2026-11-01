import io

import pytest
from PIL import Image

from app import create_app
from extensions import db


@pytest.fixture
def client(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "UPLOAD_FOLDER": tmp_path / "uploads",
        "REPORT_FOLDER": tmp_path / "reports",
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
    with app.test_client() as test_client:
        yield test_client
    with app.app_context():
        db.drop_all()


def test_identifier_scan_flags_unknown_evidence_reference(client):
    client.post("/api/auth/register", json={
        "username": "analyst", "email": "analyst@example.test", "password": "long-secure-passphrase"
    })
    case = client.post("/api/cases", json={"title": "Reference review"}).json["case"]
    image = Image.new("RGB", (2, 2), color=(90, 110, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    evidence = client.post(
        f"/api/cases/{case['id']}/evidence",
        data={"file": (buffer, "ref.png"), "description": ""},
        content_type="multipart/form-data",
    ).json["evidence"]
    client.put(f"/api/evidence/{evidence['id']}", json={
        "description": f"Recorded near {evidence['evidence_number']}; note EV-ABCDEF"
    })
    result = client.post(f"/api/cases/{case['id']}/analyze-report").json
    assert result["nlp"]["available"] is False
    assert result["references"][0]["referenced_evidence_number"] == evidence["evidence_number"]
    assert result["warnings"][0]["rule"] == "EL-001"
    assert result["warnings"][0]["referenced_identifier"] == "EV-ABCDEF"
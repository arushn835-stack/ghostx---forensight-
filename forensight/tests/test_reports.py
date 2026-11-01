import pytest

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


def test_report_is_generated_from_case_and_download_is_scoped(client):
    client.post("/api/auth/register", json={
        "username": "reporter", "email": "reporter@example.test", "password": "long-secure-passphrase"
    })
    case = client.post("/api/cases", json={"title": "Evidence inventory report", "case_number": "FS-TEST-1"}).json["case"]
    result = client.post(f"/api/cases/{case['id']}/reports")
    assert result.status_code == 201
    report_id = result.json["report"]["id"]
    download = client.get(f"/api/reports/{report_id}/download")
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF-")
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={
        "username": "outsider", "email": "outsider@example.test", "password": "another-secure-passphrase"
    })
    assert client.get(f"/api/reports/{report_id}/download").status_code == 404
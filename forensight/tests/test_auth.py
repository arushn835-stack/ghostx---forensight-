import pytest

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


def test_registration_hashes_password_and_login(client):
    response = client.post("/api/auth/register", json={
        "username": "caseworker", "email": "worker@example.test", "password": "long-secure-passphrase"
    })
    assert response.status_code == 201
    with client.application.app_context():
        user = User.query.filter_by(username="caseworker").one()
        assert user.password_hash != "long-secure-passphrase"
        assert user.check_password("long-secure-passphrase")
    assert client.get("/api/auth/me").json["user"]["username"] == "caseworker"
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_registration_rejects_short_password(client):
    response = client.post("/api/auth/register", json={
        "username": "caseworker", "email": "worker@example.test", "password": "short"
    })
    assert response.status_code == 400


def test_admin_user_management_and_last_admin_protection(client):
    client.post("/api/auth/register", json={
        "username": "administrator", "email": "admin@example.test", "password": "long-secure-passphrase"
    })
    with client.application.app_context():
        admin = User.query.filter_by(username="administrator").one()
        admin.role = "Administrator"
        investigator = User(username="review-target", email="review-target@example.test")
        investigator.set_password("another-secure-passphrase")
        db.session.add(investigator)
        db.session.commit()
        investigator_id = investigator.id
        admin_id = admin.id
    response = client.get("/api/admin/users")
    assert response.status_code == 200
    changed = client.patch(f"/api/admin/users/{investigator_id}/role", json={"role": "Reviewer"})
    assert changed.status_code == 200
    assert changed.json["user"]["role"] == "Reviewer"
    blocked = client.patch(f"/api/admin/users/{admin_id}/role", json={"role": "Investigator"})
    assert blocked.status_code == 400
    deactivate = client.patch(f"/api/admin/users/{admin_id}/role", json={"is_active": False})
    assert deactivate.status_code == 400


def test_csrf_protects_state_changes_and_home_shows_anonymous_state(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'csrf.db'}",
        "UPLOAD_FOLDER": tmp_path / "uploads",
        "WTF_CSRF_ENABLED": True,
    })
    client = app.test_client()
    with app.app_context():
        db.create_all()
    home = client.get("/")
    assert b'data-authenticated="false"' in home.data
    rejected = client.post("/api/auth/register", json={
        "username": "csrfuser", "email": "csrf@example.test", "password": "long-secure-passphrase"
    })
    assert rejected.status_code == 400
    with app.app_context():
        db.drop_all()


def test_unauthenticated_api_requests_return_json_401(client):
    response = client.get("/api/cases")
    assert response.status_code == 401
    assert response.is_json
    assert response.json["error"] == "Authentication required."


def test_auth_rejects_non_object_json_body(client):
    response = client.post("/api/auth/register", json=["not", "an", "object"])
    assert response.status_code == 400
    assert response.json["error"] == "Request body must be a JSON object."


def test_unexpected_api_errors_are_generic_json(client):
    @client.application.get("/api/test-unexpected-error")
    def raise_test_error():
        raise RuntimeError("sensitive internal detail")

    response = client.get("/api/test-unexpected-error")
    assert response.status_code == 500
    assert response.json == {"error": "Internal server error."}
import pytest
from pathlib import Path

from app import create_app
from extensions import db
from models import AnalysisResult, Case, Evidence
from services.demo_data import remove_demo_data, seed_demo_data


@pytest.fixture
def app(tmp_path):
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
        from models import User
        user = User(username="demo-owner", email="demo@example.test", role="Investigator")
        user.set_password("not-a-real-password-123")
        db.session.add(user)
        db.session.commit()
        yield app, user
        db.drop_all()


def test_demo_seed_is_explicit_and_labeled(app):
    application, user = app
    with application.app_context():
        assert seed_demo_data(user.username, application.config["UPLOAD_FOLDER"]) == 2
        assert Case.query.filter(Case.case_number.like("DEMO-%")).count() == 2
        assert Evidence.query.filter(Evidence.description.like("FICTIONAL DEMO ONLY:%")).count() == 4
        analyses = AnalysisResult.query.all()
        assert len(analyses) == 2
        assert all(analysis.model_name == "SIMULATED / DEMO ONLY" for analysis in analyses)
        assert all('"simulated": true' in analysis.result_json for analysis in analyses)
        with pytest.raises(ValueError, match="already exist"):
            seed_demo_data(user.username, application.config["UPLOAD_FOLDER"])


def test_demo_cleanup_removes_reserved_rows_and_private_files(app):
    application, user = app
    with application.app_context():
        seed_demo_data(user.username, application.config["UPLOAD_FOLDER"])
        paths = [entry.storage_path for entry in Evidence.query.all()]
        assert all(Path(path).is_file() for path in paths)
        assert remove_demo_data(application.config["UPLOAD_FOLDER"], application.config["REPORT_FOLDER"]) == 2
        assert Case.query.filter(Case.case_number.like("DEMO-%")).count() == 0
        assert all(not Path(path).exists() for path in paths)
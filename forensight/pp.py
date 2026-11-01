from pathlib import Path

import click
import os
from flask import Flask, jsonify, render_template, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from config import Config
from extensions import csrf, db, login_manager


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["REPORT_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "home"

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(error="Authentication required."), 401
        return app.view_functions["home"]()

    from models import User
    from routes.auth import admin_bp, auth_bp
    from routes.cases import cases_bp
    from routes.evidence import evidence_bp
    from routes.workflows import workflows_bp
    from routes.reports import reports_bp

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(workflows_bp)
    app.register_blueprint(reports_bp)

    @app.get("/")
    def home():
        return render_template("index.html", user=current_user)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="Upload exceeds the 20 MB limit."), 413

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error="CSRF token is missing or invalid."), 400
        return error.description, 400

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        app.logger.exception("Unhandled application error", exc_info=error)
        if request.path.startswith("/api/"):
            return jsonify(error="Internal server error."), 500
        return "Internal server error.", 500

    @app.cli.command("init-db")
    def init_db_command():
        """Create missing tables without deleting existing data."""
        with app.app_context():
            db.create_all()
        click.echo("Database tables are ready.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option()
    def create_admin(username, email, password):
        from models import User

        with app.app_context():
            if User.query.filter_by(role="Administrator").first():
                raise click.ClickException("An administrator already exists.")
            user = User(username=username.strip(), email=email.strip().lower(), role="Administrator")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        click.echo("Administrator account created.")

    @app.cli.command("seed-demo")
    @click.option("--username", prompt=True, help="Existing investigator or administrator who will own the demo cases.")
    @click.option("--confirm-fictional-data", is_flag=True, help="Confirm that all seeded records are fictional demo data.")
    def seed_demo(username, confirm_fictional_data):
        """Add fictional workflow examples to the configured database."""
        if os.environ.get("ALLOW_DEMO_DATA") != "1" or not confirm_fictional_data:
            raise click.ClickException("Set ALLOW_DEMO_DATA=1 and pass --confirm-fictional-data to seed demo records.")
        from services.demo_data import seed_demo_data

        try:
            with app.app_context():
                count = seed_demo_data(username, app.config["UPLOAD_FOLDER"])
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo(f"Added {count} fictional demonstration cases and related records.")

    @app.cli.command("remove-demo")
    @click.option("--confirm-fictional-data-removal", is_flag=True, help="Confirm removal of reserved fictional demo records and their generated files.")
    def remove_demo(confirm_fictional_data_removal):
        """Remove only the reserved fictional demonstration cases."""
        if os.environ.get("ALLOW_DEMO_DATA") != "1" or not confirm_fictional_data_removal:
            raise click.ClickException("Set ALLOW_DEMO_DATA=1 and pass --confirm-fictional-data-removal to remove demo records.")
        from services.demo_data import remove_demo_data

        with app.app_context():
            count = remove_demo_data(app.config["UPLOAD_FOLDER"], app.config["REPORT_FOLDER"])
        click.echo(f"Removed {count} reserved fictional demonstration cases and their related records.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"] if "DEBUG" in app.config else False)
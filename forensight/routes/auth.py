import json

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_

from extensions import db
from models import AuditLog, User
from routes.access import json_object


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@auth_bp.post("/register")
def register():
    data = json_object()
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(username) < 3 or len(username) > 80:
        return jsonify(error="Username must be between 3 and 80 characters."), 400
    if "@" not in email or len(email) > 255:
        return jsonify(error="Enter a valid email address."), 400
    if len(password) < 12:
        return jsonify(error="Password must be at least 12 characters."), 400
    if User.query.filter(or_(User.username == username, User.email == email)).first():
        return jsonify(error="Username or email is already registered."), 409
    user = User(username=username, email=email, role="Investigator")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify(user=user.to_dict()), 201


@auth_bp.post("/login")
def login():
    data = json_object()
    identity = str(data.get("identity", "")).strip()
    user = User.query.filter(or_(User.username == identity, User.email == identity.lower())).first()
    if not user or not user.is_active or not user.check_password(str(data.get("password", ""))):
        return jsonify(error="Invalid username/email or password."), 401
    login_user(user)
    return jsonify(user=user.to_dict())


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    return jsonify(ok=True)


@auth_bp.get("/me")
def me():
    if not current_user.is_authenticated:
        return jsonify(user=None), 401
    return jsonify(user=current_user.to_dict())


@admin_bp.get("/users")
@login_required
def list_users():
    if current_user.role != "Administrator":
        return jsonify(error="Administrator access is required."), 403
    users = User.query.order_by(User.username.asc()).all()
    return jsonify(items=[user.to_dict() for user in users])


@admin_bp.patch("/users/<int:user_id>/role")
@login_required
def update_user_access(user_id):
    if current_user.role != "Administrator":
        return jsonify(error="Administrator access is required."), 403
    user = db.get_or_404(User, user_id)
    data = json_object()
    role = data.get("role", user.role)
    if not isinstance(role, str) or role not in {"Administrator", "Investigator", "Reviewer"}:
        return jsonify(error="Unsupported user role."), 400
    if user.role == "Administrator" and role != "Administrator" and User.query.filter_by(role="Administrator", is_active=True).count() <= 1:
        return jsonify(error="The last active administrator cannot be demoted."), 400
    if "is_active" in data and not isinstance(data["is_active"], bool):
        return jsonify(error="is_active must be a boolean."), 400
    if user.id == current_user.id and data.get("is_active") is False:
        return jsonify(error="You cannot deactivate your own account."), 400
    previous = {"role": user.role, "is_active": user.is_active}
    user.role = role
    if "is_active" in data:
        user.is_active = data["is_active"]
    db.session.add(AuditLog(actor_id=current_user.id, action="User access updated", entity_type="User", entity_id=str(user.id), previous_values=json.dumps(previous), new_values=json.dumps({"role": user.role, "is_active": user.is_active})))
    db.session.commit()
    return jsonify(user=user.to_dict())
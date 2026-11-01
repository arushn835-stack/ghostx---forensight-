from flask import abort, request

from models import Case


def json_object():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="Request body must be a JSON object.")
    return payload


def visible_case(case_id, user):
    case = Case.query.filter_by(id=case_id, archived=False).first()
    if not case:
        abort(404)
    if user.role != "Administrator" and case.assigned_investigator_id != user.id:
        abort(404)
    return case


def require_edit(case, user):
    if user.role == "Reviewer":
        abort(403)

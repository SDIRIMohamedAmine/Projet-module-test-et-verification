"""API projets et applications cibles (FR-01..FR-10)."""
from flask import Blueprint, jsonify, request
import re

from ..models import Project, TargetApplication, db
from ..services.security import validate_target_url

bp = Blueprint("projects", __name__)


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "targets_count": len(p.targets),
    }


def _target_dict(t: TargetApplication) -> dict:
    configuration = dict(t.configuration or {})
    credentials = configuration.pop("credentials", {}) or {}
    return {
        "id": t.id,
        "project_id": t.project_id,
        "name": t.name,
        "base_url": t.base_url,
        "configuration": configuration,
        "credential_names": sorted(credentials),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "campaigns_count": len(t.campaigns),
    }


def _target_configuration(configuration, existing=None):
    if not isinstance(configuration, dict):
        raise ValueError("La configuration doit être un objet")
    config = dict(configuration)
    credentials = config.pop("credentials", None)
    saved = dict((existing or {}).get("credentials") or {})
    if credentials is not None:
        if not isinstance(credentials, dict):
            raise ValueError("Les identifiants doivent être fournis par variable")
        for name, value in credentials.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError("Nom de variable invalide")
            if value is None:
                saved.pop(name, None)
            elif isinstance(value, str) and value:
                saved[name] = value
            else:
                raise ValueError("Chaque variable doit avoir une valeur")
    if saved:
        config["credentials"] = saved
    return config


@bp.get("/projects")
def list_projects():
    projects = Project.query.order_by(Project.created_at.desc()).all()
    return jsonify([_project_dict(p) for p in projects])


@bp.post("/projects")
def create_project():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Le nom du projet est obligatoire"}), 400
    project = Project(name=name[:200], description=(data.get("description") or "").strip() or None)
    db.session.add(project)
    db.session.commit()
    return jsonify(_project_dict(project)), 201


@bp.get("/projects/<int:project_id>")
def get_project(project_id):
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Projet introuvable"}), 404
    data = _project_dict(project)
    data["targets"] = [_target_dict(t) for t in project.targets]
    return jsonify(data)


@bp.put("/projects/<int:project_id>")
def update_project(project_id):
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Projet introuvable"}), 404
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Le nom du projet est obligatoire"}), 400
        project.name = name[:200]
    if "description" in data:
        project.description = (data.get("description") or "").strip() or None
    db.session.commit()
    return jsonify(_project_dict(project))


@bp.delete("/projects/<int:project_id>")
def delete_project(project_id):
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Projet introuvable"}), 404
    db.session.delete(project)
    db.session.commit()
    return jsonify({"status": "deleted"})


@bp.post("/projects/<int:project_id>/targets")
def create_target(project_id):
    project = db.session.get(Project, project_id)
    if not project:
        return jsonify({"error": "Projet introuvable"}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip()
    if not name:
        return jsonify({"error": "Le nom de la cible est obligatoire"}), 400
    url_error = validate_target_url(base_url)
    if url_error:
        return jsonify({"error": url_error}), 400

    try:
        config = _target_configuration(data.get("configuration", {}))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    # normalise les limites d'exploration (FR-07)
    limits = config.get("limits") or {}
    for key in ("max_pages", "max_depth", "max_duration_seconds", "max_actions"):
        if key in limits:
            try:
                limits[key] = max(1, int(limits[key]))
            except (TypeError, ValueError):
                return jsonify({"error": f"Limite invalide : {key}"}), 400
    config["limits"] = limits
    if not isinstance(config.get("extra_domains", []), list):
        return jsonify({"error": "extra_domains doit être une liste"}), 400

    target = TargetApplication(
        project_id=project.id, name=name[:200], base_url=base_url, configuration=config
    )
    db.session.add(target)
    db.session.commit()
    return jsonify(_target_dict(target)), 201


@bp.put("/targets/<int:target_id>")
def update_target(target_id):
    target = db.session.get(TargetApplication, target_id)
    if not target:
        return jsonify({"error": "Cible introuvable"}), 404
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Le nom de la cible est obligatoire"}), 400
        target.name = name[:200]
    if "base_url" in data:
        base_url = (data.get("base_url") or "").strip()
        url_error = validate_target_url(base_url)
        if url_error:
            return jsonify({"error": url_error}), 400
        target.base_url = base_url
    if "configuration" in data:
        try:
            target.configuration = _target_configuration(data["configuration"], target.configuration)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    db.session.commit()
    return jsonify(_target_dict(target))


@bp.delete("/targets/<int:target_id>")
def delete_target(target_id):
    target = db.session.get(TargetApplication, target_id)
    if not target:
        return jsonify({"error": "Cible introuvable"}), 404
    db.session.delete(target)
    db.session.commit()
    return jsonify({"status": "deleted"})

"""API campagnes : création, exploration, génération de scénarios, statut."""
from flask import Blueprint, jsonify, request

from ..models import ExplorationPage, TargetApplication, TestCampaign, db
from ..services.explorer import explore_campaign
from ..services.scenario_generator import generate_scenarios_for_campaign
from ..tasks import run_in_background

bp = Blueprint("campaigns", __name__)


def _campaign_dict(c: TestCampaign, detail: bool = False) -> dict:
    data = {
        "id": c.id,
        "target_application_id": c.target_application_id,
        "target_name": c.target.name if c.target else None,
        "base_url": c.target.base_url if c.target else None,
        "objective": c.objective,
        "status": c.status,
        "task_stage": c.task_stage,
        "task_message": c.task_message,
        "task_progress": c.task_progress,
        "error_message": c.error_message,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "finished_at": c.finished_at.isoformat() if c.finished_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "configuration_snapshot": c.configuration_snapshot or {},
    }
    if detail:
        data["pages"] = [
            {
                "id": p.id,
                "url": p.url,
                "title": p.title,
                "depth": p.depth,
                "exploration_status": p.exploration_status,
                "elements_count": len(p.discovered_elements or []),
                "console_errors": p.console_errors or [],
                "failed_requests": p.failed_requests or [],
            }
            for p in sorted(c.pages, key=lambda x: x.id)
        ]
        data["scenario_counts"] = {
            "total": len(c.scenarios),
            "pending": sum(1 for s in c.scenarios if s.approval_status == "pending"),
            "approved": sum(1 for s in c.scenarios if s.approval_status == "approved"),
        }
    return data


@bp.post("/targets/<int:target_id>/campaigns")
def create_campaign(target_id):
    target = db.session.get(TargetApplication, target_id)
    if not target:
        return jsonify({"error": "Cible introuvable"}), 404
    data = request.get_json(silent=True) or {}
    objective = (data.get("objective") or "").strip()

    config = dict(target.configuration or {})
    if data.get("limits"):
        config["limits"] = {**(config.get("limits") or {}), **data["limits"]}

    campaign = TestCampaign(
        target_application_id=target.id,
        objective=objective or None,
        status="created",
        task_stage="created",
        task_message="Campagne créée. Prêt pour l'exploration.",
        task_progress=0,
        configuration_snapshot={
            "objective": objective,
            "limits": config.get("limits") or {},
            "extra_domains": config.get("extra_domains") or [],
            "exclude_url_patterns": config.get("exclude_url_patterns") or [],
            "constraints": config.get("constraints") or "",
            "allow_destructive_actions": config.get("allow_destructive_actions", False),
            "has_credentials": bool(config.get("credentials")),
        },
    )
    db.session.add(campaign)
    db.session.commit()
    return jsonify(_campaign_dict(campaign)), 201


@bp.get("/campaigns")
def list_campaigns():
    status_filter = request.args.get("status")
    query = TestCampaign.query.order_by(TestCampaign.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    campaigns = query.limit(200).all()
    return jsonify([_campaign_dict(c) for c in campaigns])


@bp.get("/campaigns/<int:campaign_id>")
def get_campaign(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    return jsonify(_campaign_dict(campaign, detail=True))


@bp.post("/campaigns/<int:campaign_id>/explore")
def start_exploration(campaign_id):
    from flask import current_app

    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    if campaign.status in ("exploring", "generating", "executing"):
        return jsonify({"error": f"Une tâche est déjà en cours ({campaign.status})"}), 409

    # réinitialise les pages d'une éventuelle exploration précédente
    for page in list(campaign.pages):
        db.session.delete(page)
    campaign.status = "created"
    campaign.task_stage = "queued"
    campaign.task_message = "Exploration mise en file…"
    campaign.task_progress = 0
    db.session.commit()

    run_in_background(current_app._get_current_object(), campaign_id, explore_campaign)
    return jsonify(_campaign_dict(campaign)), 202


@bp.post("/campaigns/<int:campaign_id>/generate-scenarios")
def generate_scenarios(campaign_id):
    from flask import current_app

    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    if campaign.status not in ("explored", "scenarios_ready", "completed", "failed"):
        return jsonify({"error": "L'exploration doit être terminée avant de générer des scénarios"}), 409
    if not campaign.pages:
        return jsonify({"error": "Aucune page explorée"}), 409

    if campaign.status == "scenarios_ready" and not request.args.get("force"):
        existing = [s for s in campaign.scenarios if s.approval_status != "deleted"]
        if existing:
            return jsonify(
                {"error": "Des scénarios existent déjà. Utilisez ?force=1 pour les régénérer."}
            ), 409

    # régénération = suppression des anciens scénarios
    if request.args.get("force"):
        for sc in list(campaign.scenarios):
            db.session.delete(sc)
        db.session.commit()
        campaign.status = "explored"

    campaign.status = "generating"
    campaign.task_stage = "generation"
    campaign.task_message = "Génération des scénarios…"
    campaign.task_progress = 30
    db.session.commit()

    def job(cid):
        generate_scenarios_for_campaign(cid)

    run_in_background(current_app._get_current_object(), campaign_id, job)
    return jsonify(_campaign_dict(campaign)), 202


@bp.get("/campaigns/<int:campaign_id>/exploration")
def get_exploration(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    pages = ExplorationPage.query.filter_by(campaign_id=campaign_id).order_by(ExplorationPage.id).all()
    return jsonify(
        [
            {
                "id": p.id,
                "url": p.url,
                "title": p.title,
                "depth": p.depth,
                "exploration_status": p.exploration_status,
                "discovered_elements": p.discovered_elements or [],
                "console_errors": p.console_errors or [],
                "failed_requests": p.failed_requests or [],
            }
            for p in pages
        ]
    )

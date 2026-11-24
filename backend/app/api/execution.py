"""API exécution et résultats."""
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file

from ..models import Evidence, TestCampaign, TestResult, TestScenario, db
from ..services.executor import execute_campaign
from ..services.scenario_validation import saved_scenario_errors
from ..tasks import run_in_background

bp = Blueprint("execution", __name__)


@bp.post("/campaigns/<int:campaign_id>/execute")
def start_execution(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    if campaign.status in ("exploring", "generating", "executing"):
        return jsonify({"error": f"Une tâche est déjà en cours ({campaign.status})"}), 409

    approved = [
        s
        for s in campaign.scenarios
        if s.approval_status == "approved" and s.steps
    ]
    if not approved:
        return jsonify({"error": "Aucun scénario approuvé à exécuter"}), 409
    for scenario in approved:
        errors = saved_scenario_errors(scenario)
        if errors:
            return jsonify({"error": f"{scenario.title} — {errors[0]}", "validation_errors": errors}), 409

    campaign.status = "executing"
    campaign.task_stage = "queued"
    campaign.task_message = "Exécution mise en file…"
    campaign.task_progress = 0
    campaign.error_message = None
    db.session.commit()

    run_in_background(current_app._get_current_object(), campaign_id, execute_campaign)
    return jsonify({"status": "queued", "approved_scenarios": len(approved)}), 202


@bp.get("/campaigns/<int:campaign_id>/results")
def get_results(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    results = (
        TestResult.query.join(TestScenario)
        .filter(TestScenario.campaign_id == campaign_id)
        .all()
    )
    by_scenario = {}
    for r in results:
        by_scenario[r.scenario_id] = {
            "id": r.id,
            "status": r.status,
            "actual_result": r.actual_result,
            "error_summary": r.error_summary,
            "step_outcomes": r.step_outcomes or [],
            "analysis": r.analysis,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "evidences": [
                {"id": e.id, "type": e.evidence_type, "metadata": e.evidence_metadata or {}}
                for e in r.evidences
            ],
        }
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    executed = len(results)
    passed = counts.get("PASSED", 0)
    return jsonify(
        {
            "counts": counts,
            "executed": executed,
            "success_rate": round(passed / executed * 100, 1) if executed else 0.0,
            "by_scenario": by_scenario,
        }
    )


@bp.get("/evidences/<int:evidence_id>/file")
def get_evidence_file(evidence_id):
    evidence = db.session.get(Evidence, evidence_id)
    if not evidence:
        return jsonify({"error": "Preuve introuvable"}), 404
    path = Path(evidence.file_path)
    if not path.exists():
        return jsonify({"error": "Fichier de preuve absent"}), 404
    return send_file(path, as_attachment=False, download_name=path.name)

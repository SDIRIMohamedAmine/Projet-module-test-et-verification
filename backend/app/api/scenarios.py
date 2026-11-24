"""API scénarios : consultation, édition, approbation (FR-23, FR-24)."""
from flask import Blueprint, jsonify, request

from ..models import TestScenario, TestStep, db
from ..services.scenario_generator import FALLBACK_STRATEGIES, VALID_ACTIONS, VALID_EXPECTS, VALID_STRATEGIES
from ..services.scenario_validation import saved_scenario_errors

bp = Blueprint("scenarios", __name__)

VALID_APPROVAL = {"pending", "approved", "modified", "disabled"}


def _step_dict(s: TestStep) -> dict:
    return {
        "id": s.id,
        "step_order": s.step_order,
        "action": s.action,
        "parameters": s.parameters or {},
        "expected_observation": s.expected_observation,
    }


def _scenario_dict(s: TestScenario, detail: bool = False) -> dict:
    data = {
        "id": s.id,
        "campaign_id": s.campaign_id,
        "title": s.title,
        "objective": s.objective,
        "preconditions": s.preconditions,
        "expected_result": s.expected_result,
        "approval_status": s.approval_status,
        "kind": s.kind,
        "source": s.source,
    }
    if detail:
        data["steps"] = [_step_dict(st) for st in sorted(s.steps, key=lambda x: x.step_order)]
        data["validation_errors"] = saved_scenario_errors(s)
        if s.result:
            data["result"] = {
                "id": s.result.id,
                "status": s.result.status,
                "actual_result": s.result.actual_result,
                "error_summary": s.result.error_summary,
                "step_outcomes": s.result.step_outcomes or [],
                "analysis": s.result.analysis,
                "started_at": s.result.started_at.isoformat() if s.result.started_at else None,
                "finished_at": s.result.finished_at.isoformat() if s.result.finished_at else None,
            }
    return data


@bp.get("/campaigns/<int:campaign_id>/scenarios")
def list_scenarios(campaign_id):
    scenarios = (
        TestScenario.query.filter_by(campaign_id=campaign_id)
        .filter(TestScenario.approval_status != "deleted")
        .order_by(TestScenario.id)
        .all()
    )
    return jsonify([_scenario_dict(s, detail=True) for s in scenarios])


@bp.get("/scenarios/<int:scenario_id>")
def get_scenario(scenario_id):
    scenario = db.session.get(TestScenario, scenario_id)
    if not scenario:
        return jsonify({"error": "Scénario introuvable"}), 404
    return jsonify(_scenario_dict(scenario, detail=True))


@bp.put("/scenarios/<int:scenario_id>")
def update_scenario(scenario_id):
    """Édition du scénario (titre, étapes…) — FR-24."""
    scenario = db.session.get(TestScenario, scenario_id)
    if not scenario:
        return jsonify({"error": "Scénario introuvable"}), 404
    data = request.get_json(silent=True) or {}

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "Le titre est obligatoire"}), 400
        scenario.title = title[:300]
    for field in ("objective", "preconditions", "expected_result"):
        if field in data:
            setattr(scenario, field, (data.get(field) or "").strip() or None)
    if "kind" in data and data["kind"] in ("positive", "negative"):
        scenario.kind = data["kind"]
    if "source" in data and data["source"] in ("observed", "hypothesis"):
        scenario.source = data["source"]

    if "steps" in data:
        steps_data = data.get("steps")
        if not isinstance(steps_data, list) or not steps_data:
            return jsonify({"error": "Au moins une étape est requise"}), 400
        cleaned = []
        for idx, step in enumerate(steps_data, start=1):
            if not isinstance(step, dict):
                return jsonify({"error": f"Étape {idx} invalide"}), 400
            action = str(step.get("action") or "").lower()
            if action not in VALID_ACTIONS:
                return jsonify({"error": f"Action invalide à l'étape {idx} : {action}"}), 400
            target = step.get("target") if isinstance(step.get("target"), dict) else {}
            strategy = str(target.get("strategy") or "css").lower()
            if strategy not in VALID_STRATEGIES and not (strategy == "near" and action == "read_text"):
                return jsonify({"error": f"Stratégie de localisation invalide à l'étape {idx}"}), 400
            locator = {"strategy": strategy, "value": str(target.get("value") or "")}
            fallback = target.get("fallback")
            if fallback is not None:
                if (
                    strategy == "near" or not isinstance(fallback, dict)
                    or str(fallback.get("strategy")) not in FALLBACK_STRATEGIES or not fallback.get("value")
                ):
                    return jsonify({"error": f"Localisateur de repli invalide à l'étape {idx}"}), 400
                locator["fallback"] = {"strategy": fallback["strategy"], "value": str(fallback["value"])}
            expect = step.get("expect")
            if expect is not None:
                if not isinstance(expect, dict) or str(expect.get("type", "")).lower() not in VALID_EXPECTS:
                    return jsonify({"error": f"Vérification invalide à l'étape {idx}"}), 400
                expect = {"type": str(expect.get("type")).lower(), "value": str(expect.get("value", ""))}
            cleaned.append(
                {
                    "action": action,
                    "target": locator,
                    "value": str(step.get("value") or ""),
                    "expect": expect,
                    "expected_observation": str(step.get("expected_observation") or "") or None,
                }
            )
        for old in list(scenario.steps):
            db.session.delete(old)
        db.session.flush()
        for order, step in enumerate(cleaned, start=1):
            db.session.add(
                TestStep(
                    scenario_id=scenario.id,
                    step_order=order,
                    action=step["action"],
                    parameters={
                        "target": step["target"],
                        "value": step["value"],
                        "expect": step["expect"],
                    },
                    expected_observation=step["expected_observation"],
                )
            )

    if scenario.approval_status == "approved":
        scenario.approval_status = "modified"
    db.session.commit()
    return jsonify(_scenario_dict(scenario, detail=True))


@bp.post("/scenarios/<int:scenario_id>/approval")
def set_approval(scenario_id):
    """Approuver, désactiver ou remettre en attente — FR-24."""
    scenario = db.session.get(TestScenario, scenario_id)
    if not scenario:
        return jsonify({"error": "Scénario introuvable"}), 404
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in VALID_APPROVAL:
        return jsonify({"error": f"Statut invalide. Valeurs : {sorted(VALID_APPROVAL)}"}), 400
    if status == "approved":
        errors = saved_scenario_errors(scenario)
        if errors:
            return jsonify({"error": errors[0], "validation_errors": errors}), 409
    scenario.approval_status = status
    db.session.commit()
    return jsonify(_scenario_dict(scenario, detail=True))


@bp.delete("/scenarios/<int:scenario_id>")
def delete_scenario(scenario_id):
    scenario = db.session.get(TestScenario, scenario_id)
    if not scenario:
        return jsonify({"error": "Scénario introuvable"}), 404
    scenario.approval_status = "deleted"
    db.session.commit()
    return jsonify({"status": "deleted"})


@bp.post("/campaigns/<int:campaign_id>/scenarios/approve-all")
def approve_all(campaign_id):
    scenarios = (
        TestScenario.query.filter_by(campaign_id=campaign_id, approval_status="pending")
        .all()
    )
    count = 0
    for s in scenarios:
        if not saved_scenario_errors(s):
            s.approval_status = "approved"
            count += 1
    db.session.commit()
    return jsonify({"approved": count, "needs_review": len(scenarios) - count})

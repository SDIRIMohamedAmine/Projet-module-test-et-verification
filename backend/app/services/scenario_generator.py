"""Génération de scénarios de test (FR-18..FR-24) : IA Groq + repli heuristique."""
from __future__ import annotations

import json
from collections import Counter

from ..models import ExplorationPage, TestCampaign, TestScenario, TestStep, db
from . import agent

SCENARIO_SCHEMA = {
    "scenarios": [
        {
            "title": "str",
            "objective": "str",
            "preconditions": "str",
            "expected_result": "str",
            "kind": "positive|negative",
            "source": "observed|hypothesis",
            "steps": [
                {
                    "action": "goto|click|fill|select|check|uncheck|press|wait|assert|read_text",
                    "target": {"strategy": "role|label|placeholder|text|css", "value": "str"},
                    "value": "str (facultatif)",
                    "expect": {
                        "type": "visible|hidden|text_contains|url_matches|url_equals|http_status|no_console_error|value_equals|title_equals",
                        "value": "str",
                    },
                    "expected_observation": "str (facultatif)",
                }
            ],
        }
    ]
}

VALID_ACTIONS = {"goto", "click", "fill", "select", "check", "uncheck", "press", "wait", "assert", "read_text"}
VALID_STRATEGIES = {"role", "label", "placeholder", "text", "css"}
VALID_EXPECTS = {
    "visible",
    "hidden",
    "text_contains",
    "url_matches",
    "url_equals",
    "http_status",
    "no_console_error",
    "title_equals",
    "value_equals",
}
GROQ_PROMPT_BYTES = 5_500
ELEMENT_PRIORITY = {"field": 0, "button": 1, "form": 2}


def _summarize_pages(pages: list[ExplorationPage], max_pages: int = 12) -> list[dict]:
    summary = []
    for page in pages[:max_pages]:
        summary.append(
            {
                "url": page.url,
                "title": page.title,
                "status": page.exploration_status,
                "elements": page.discovered_elements or [],
            }
        )
    return summary


def _build_prompt(objective: str, base_url: str, constraints: str, pages: list[dict]) -> str:
    payload = {
        "instruction": (
            "Tu es un ingénieur QA. Génère des scénarios de test E2E exploitables "
            "à partir des observations d'exploration d'une application inconnue. "
            "N'invente aucun sélecteur non observé : utilise uniquement les éléments "
            "fournis (role, label, placeholder, text). Marque source=hypothesis si "
            "une étape n'est pas directement observée. Inclus des tests négatifs "
            "(saisie invalide, champs manquants) quand des formulaires existent. "
            "Produis UNIQUEMENT le JSON du schéma fourni."
        ),
        "schema": SCENARIO_SCHEMA,
        "objective": objective or "Couvrir les parcours principaux de l'application",
        "base_url": base_url,
        "constraints": constraints or "aucune",
        "observed_pages": [],
    }

    def serialize():
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def fits():
        return len(serialize().encode("utf-8")) <= GROQ_PROMPT_BYTES

    if not fits():
        raise agent.AgentError("Objectif et contraintes trop longs pour la génération IA. Raccourcissez-les.")

    element_lists = []
    for page in pages:
        observation = {key: page[key] for key in ("url", "title", "status")}
        observation["elements"] = []
        payload["observed_pages"].append(observation)
        if not fits():
            payload["observed_pages"].pop()
            continue

        counts = Counter()
        selected = []
        for element in sorted(page["elements"], key=lambda el: ELEMENT_PRIORITY.get(el.get("kind"), 3)):
            kind = element.get("kind")
            if counts[kind] >= 5:
                continue
            descriptor = {
                key: value for key, value in element.items()
                if key != "options" and isinstance(value, str) and len(value) <= 160
            }
            selected.append(descriptor)
            counts[kind] += 1
        element_lists.append((observation["elements"], selected))

    for index in range(max((len(elements) for _, elements in element_lists), default=0)):
        for destination, elements in element_lists:
            if index < len(elements):
                destination.append(elements[index])
                if not fits():
                    destination.pop()
    return serialize()


def _sanitize_scenarios(data: dict) -> list[dict]:
    raw = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise agent.AgentError("Structure de scénarios invalide")
    clean = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        steps_raw = item.get("steps")
        if not title or not isinstance(steps_raw, list) or not steps_raw:
            continue
        steps = []
        for step in steps_raw:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "").lower()
            if action not in VALID_ACTIONS:
                continue
            target = step.get("target") if isinstance(step.get("target"), dict) else {}
            strategy = str(target.get("strategy") or "css").lower()
            if strategy not in VALID_STRATEGIES:
                strategy = "css"
            expect = step.get("expect") if isinstance(step.get("expect"), dict) else None
            if expect:
                etype = str(expect.get("type") or "").lower()
                if etype not in VALID_EXPECTS:
                    expect = None
                else:
                    expect = {"type": etype, "value": str(expect.get("value", ""))}
            steps.append(
                {
                    "action": action,
                    "target": {"strategy": strategy, "value": str(target.get("value") or "")},
                    "value": str(step.get("value") or ""),
                    "expect": expect,
                    "expected_observation": str(step.get("expected_observation") or "") or None,
                }
            )
        if not steps:
            continue
        clean.append(
            {
                "title": title[:300],
                "objective": str(item.get("objective") or "")[:2000],
                "preconditions": str(item.get("preconditions") or "")[:2000],
                "expected_result": str(item.get("expected_result") or "")[:2000],
                "kind": "negative" if str(item.get("kind", "")).lower() == "negative" else "positive",
                "source": "hypothesis"
                if str(item.get("source", "")).lower() == "hypothesis"
                else "observed",
                "steps": steps,
            }
        )
    return clean


def _heuristic_scenarios(base_url: str, pages: list[dict]) -> list[dict]:
    """Repli sans IA : scénarios de base dérivés des pages observées."""
    scenarios = []
    home = pages[0] if pages else {"url": base_url, "title": "Accueil", "elements": []}
    home_title = home.get("title") or "la page d'accueil"
    scenarios.append(
        {
            "title": f"Navigation vers {home_title}",
            "objective": "Vérifier que la page d'accueil se charge sans erreur",
            "preconditions": "Aucune",
            "expected_result": "La page est visible et aucune erreur JS critique",
            "kind": "positive",
            "source": "observed",
            "steps": [
                {
                    "action": "goto",
                    "target": {"strategy": "css", "value": "body"},
                    "value": home["url"],
                    "expect": {"type": "visible", "value": "body"},
                    "expected_observation": "Le contenu principal est affiché",
                },
                {
                    "action": "assert",
                    "target": {"strategy": "css", "value": "body"},
                    "value": "",
                    "expect": {"type": "no_console_error", "value": ""},
                    "expected_observation": "Aucune erreur JavaScript",
                },
            ],
        }
    )
    for page in pages[1:6]:
        title = page.get("title")
        expectation = (
            {"type": "title_equals", "value": title}
            if title else {"type": "http_status", "value": "200"}
        )
        observation = f"Titre affiché : {title}" if title else "Statut HTTP 200"
        scenarios.append(
            {
                "title": f"Accès à « {page.get('title') or page['url']} »",
                "objective": "Vérifier l'accessibilité de la page observée",
                "preconditions": "Page accessible depuis l'exploration",
                "expected_result": observation,
                "kind": "positive",
                "source": "observed",
                "steps": [
                    {
                        "action": "goto",
                        "target": {"strategy": "css", "value": "body"},
                        "value": page["url"],
                        "expect": {"type": "http_status", "value": "200"},
                        "expected_observation": "Statut HTTP 200",
                    },
                    *([
                        {
                            "action": "assert",
                            "target": {"strategy": "css", "value": "title"},
                            "value": "",
                            "expect": expectation,
                            "expected_observation": observation,
                        }
                    ] if title else []),
                ],
            }
        )
    return scenarios


def generate_scenarios_for_campaign(campaign_id: int) -> list[TestScenario]:
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return []
    pages = (
        ExplorationPage.query.filter_by(campaign_id=campaign_id)
        .order_by(ExplorationPage.id)
        .all()
    )
    if not pages:
        raise ValueError("Aucune page explorée pour cette campagne")

    config = campaign.target.configuration or {}
    constraints = config.get("constraints") or ""
    page_summary = _summarize_pages(pages)

    used_ai = False
    error_msg = None
    scenarios_data = None
    if agent.is_configured():
        try:
            raw = agent.chat_json(
                system=(
                    "Tu génères des scénarios de test E2E en JSON strict. "
                    "Pour goto, écris toujours l’URL complète dans value ; target sert aux sélecteurs. "
                    "Pour vérifier une redirection ou un accès à une page précise, utilise url_equals "
                    "avec l’URL complète. Vérifie la connexion avant de tester l’accès selon le rôle. "
                    "Pour remplir un champ, privilégie son label observé. Utilise placeholder "
                    "seulement si l’attribut placeholder exact figure dans les observations de cette page. "
                    "Conserve les variables {nom} exactement comme fournies et utilise-les uniquement "
                    "comme valeur d’une action fill. Chaque scénario démarre dans une session vierge. "
                    "Pour identifier un produit ou un libellé, utilise le texte réel fourni dans l’objectif. "
                    "Pour relever un total affiché, utilise read_text avec un sélecteur ciblé. "
                    "Une lecture est une observation ; ajoute une assertion distincte pour le verdict."
                ),
                user=_build_prompt(campaign.objective or "", campaign.target.base_url, constraints, page_summary),
            )
            scenarios_data = _sanitize_scenarios(raw)
            used_ai = True
        except agent.AgentError as exc:
            error_msg = str(exc)
    if not scenarios_data:
        scenarios_data = _heuristic_scenarios(campaign.target.base_url, page_summary)

    created = []
    for data in scenarios_data:
        scenario = TestScenario(
            campaign_id=campaign.id,
            title=data["title"],
            objective=data["objective"],
            preconditions=data["preconditions"],
            expected_result=data["expected_result"],
            approval_status="pending",
            kind=data["kind"],
            source=data["source"],
        )
        db.session.add(scenario)
        db.session.flush()
        for order, step in enumerate(data["steps"], start=1):
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
        created.append(scenario)

    campaign.status = "scenarios_ready"
    campaign.task_stage = "generation_done"
    campaign.task_progress = 100
    source = "IA" if used_ai else "heuristique"
    note = f" ({error_msg})" if error_msg else ""
    campaign.task_message = f"{len(created)} scénario(s) généré(s) via {source}{note}."
    db.session.commit()
    return created

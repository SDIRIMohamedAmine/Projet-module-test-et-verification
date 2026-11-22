"""Exécution des scénarios approuvés avec Playwright (FR-25..FR-37)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from ..models import Evidence, TestCampaign, TestResult, TestScenario, db
from .security import build_allowed_hosts, find_forbidden_action, is_url_allowed, mask_secrets
from .verifier import StepOutcome, combine_outcomes

STEP_TIMEOUT_MS = 10000


def _visible_form_fields(page) -> str:
    fields = page.locator("input:visible, textarea:visible").evaluate_all(
        """fields => fields.slice(0, 8).map(field => {
            const label = field.getAttribute('aria-label') ||
                Array.from(field.labels || [], item => item.textContent.trim()).join(' ');
            const placeholder = field.getAttribute('placeholder');
            return [
                'type=' + field.type,
                label && 'label=' + JSON.stringify(label.slice(0, 70)),
                placeholder && 'placeholder=' + JSON.stringify(placeholder.slice(0, 70)),
                field.id && 'id=' + JSON.stringify(field.id.slice(0, 70)),
            ].filter(Boolean).join(', ');
        })"""
    )
    return " | ".join(fields) or "aucun champ visible"


def _navigation_url(value: str, target: dict, base_url: str) -> str:
    destination = value.strip()
    if not destination:
        candidate = str(target.get("value") or "").strip()
        if candidate.startswith(("http://", "https://", "/")):
            destination = candidate
    if not destination:
        raise ValueError("URL de navigation manquante : renseignez value pour l’action goto")
    return urljoin(base_url, destination)


def _locator_for(page, target: dict):
    strategy = (target or {}).get("strategy", "css")
    value = (target or {}).get("value", "")
    if not value:
        raise ValueError("Cible de l'étape vide")
    if strategy == "role":
        # value: "role=nom" ou "nom" (rôle par défaut déduit)
        if "=" in value:
            role, name = value.split("=", 1)
            return page.get_by_role(role.strip(), name=name.strip() or None)
        return page.get_by_role(value.strip())
    if strategy == "label":
        return page.get_by_label(value)
    if strategy == "placeholder":
        return page.get_by_placeholder(value)
    if strategy == "text":
        return page.get_by_text(value, exact=False)
    return page.locator(value)


def _check_expect(
    page,
    expect: dict,
    last_status: int | None,
    console_errors: list,
    target: dict | None = None,
) -> tuple[bool, str]:
    etype = expect.get("type")
    value = str(expect.get("value", ""))
    if etype == "visible":
        if value:
            loc = _locator_for(page, {"strategy": "css", "value": value})
            sel = value
        else:
            loc = _locator_for(page, target or {"strategy": "css", "value": "body"})
            sel = (target or {}).get("value") or "body"
        loc.first.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
        return True, f"Élément visible : {sel}"
    if etype == "hidden":
        sel = value or (target or {}).get("value") or ""
        loc = _locator_for(page, {"strategy": "css", "value": sel})
        loc.first.wait_for(state="hidden", timeout=STEP_TIMEOUT_MS)
        return True, f"Élément masqué : {sel}"
    if etype == "text_contains":
        content = page.content()
        if value and value in content:
            return True, f"Texte présent : {value!r}"
        return False, f"Texte absent de la page : {value!r}"
    if etype == "title_equals":
        actual = page.title()
        if actual == value:
            return True, f"Titre conforme : {actual!r}"
        return False, f"Titre inattendu : {actual!r} (attendu : {value!r})"
    if etype == "url_equals":
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        if not value.strip():
            return False, "URL attendue manquante"
        expected = urljoin(page.url, value.strip())
        try:
            page.wait_for_url(lambda current: current == expected, timeout=STEP_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            return False, f"URL inattendue : {page.url} (attendu : {expected})"
        return True, f"URL conforme : {page.url}"
    if etype == "url_matches":
        current = page.url
        pattern = value if any(c in value for c in ".*+?[]()") else re.escape(value)
        if re.search(pattern, current, re.I):
            return True, f"URL conforme : {current}"
        return False, f"URL inattendue : {current} (attendu : {value})"
    if etype == "http_status":
        try:
            expected = int(value)
        except ValueError:
            return False, f"Valeur http_status invalide : {value!r}"
        if last_status is None:
            return False, "Aucune réponse HTTP observée pour cette vérification"
        if last_status == expected:
            return True, f"Statut HTTP {last_status}"
        return False, f"Statut HTTP {last_status} (attendu {expected})"
    if etype == "no_console_error":
        if console_errors:
            return False, f"{len(console_errors)} erreur(s) JS : {console_errors[0][:200]}"
        return True, "Aucune erreur JavaScript"
    if etype == "value_equals":
        loc = _locator_for(page, target or {"strategy": "css", "value": value})
        actual = loc.input_value(timeout=STEP_TIMEOUT_MS)
        if actual == value:
            return True, f"Valeur conforme : {value!r}"
        return False, f"Valeur inattendue : {actual!r} (attendu : {value!r})"
    return False, f"Type de vérification inconnu : {etype}"


def _perform_action(page, action: str, target: dict, value: str, parameters: dict, secrets: list[str]) -> int | None:
    """Réalise l'action, retourne le statut HTTP de la dernière navigation si pertinent."""
    timeout = STEP_TIMEOUT_MS
    if action == "goto":
        resp = page.goto(value, wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        return resp.status if resp else None
    if action == "click":
        _locator_for(page, target).first.click(timeout=timeout)
        return None
    if action == "fill":
        masked = mask_secrets(value, secrets)
        _locator_for(page, target).first.fill(value, timeout=timeout)
        _ = masked
        return None
    if action == "select":
        _locator_for(page, target).first.select_option(value, timeout=timeout)
        return None
    if action == "check":
        _locator_for(page, target).first.check(timeout=timeout)
        return None
    if action == "uncheck":
        _locator_for(page, target).first.uncheck(timeout=timeout)
        return None
    if action == "press":
        page.keyboard.press(value or "Enter")
        return None
    if action == "wait":
        page.wait_for_timeout(min(int(float(value or 500)), 10000))
        return None
    if action == "assert":
        return None
    raise ValueError(f"Action inconnue : {action}")


def execute_campaign(campaign_id: int) -> None:
    from flask import current_app
    from playwright.sync_api import sync_playwright

    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return

    scenarios = (
        TestScenario.query.filter_by(campaign_id=campaign_id, approval_status="approved")
        .order_by(TestScenario.id)
        .all()
    )
    # nettoie les anciens résultats
    for sc in scenarios:
        if sc.result:
            db.session.delete(sc.result)
    db.session.commit()

    campaign.status = "executing"
    campaign.task_stage = "execution"
    campaign.task_progress = 0
    campaign.task_message = f"Exécution de {len(scenarios)} scénario(s)…"
    campaign.error_message = None
    if not campaign.started_at:
        from ..models import utcnow

        campaign.started_at = utcnow()
    db.session.commit()

    config = dict(campaign.target.configuration or {})
    secrets = [str(v) for v in (config.get("credentials") or {}).values() if v]
    forbidden_patterns = config.get("forbidden_action_patterns") or []
    allow_destructive = bool(config.get("allow_destructive_actions", False))
    limits = dict(current_app.config["DEFAULT_EXPLORATION_LIMITS"])
    limits.update(config.get("limits") or {})

    evidence_root = Path(current_app.config["EVIDENCE_DIR"]) / str(campaign_id)
    evidence_root.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for idx, scenario in enumerate(scenarios):
                campaign.task_progress = int(idx / max(1, len(scenarios)) * 100)
                campaign.task_message = f"Exécution : {scenario.title}"
                db.session.commit()
                _execute_scenario(
                    browser,
                    campaign,
                    scenario,
                    config,
                    secrets,
                    forbidden_patterns,
                    allow_destructive,
                    evidence_root,
                    p,
                )
            browser.close()
    except Exception as exc:  # noqa: BLE001
        campaign.status = "failed"
        campaign.task_stage = "failed"
        campaign.error_message = f"Échec de l'exécution : {exc}"[:2000]
        campaign.task_message = campaign.error_message
        db.session.commit()
        return

    from ..models import utcnow

    campaign.status = "completed"
    campaign.task_stage = "execution_done"
    campaign.task_progress = 100
    campaign.finished_at = utcnow()
    counts = {}
    for sc in scenarios:
        if sc.result:
            counts[sc.result.status] = counts.get(sc.result.status, 0) + 1
    campaign.task_message = "Exécution terminée : " + ", ".join(
        f"{v} {k}" for k, v in sorted(counts.items())
    )
    db.session.commit()

    _run_analysis(campaign_id)


def _execute_scenario(
    browser,
    campaign: TestCampaign,
    scenario: TestScenario,
    config: dict,
    secrets: list[str],
    forbidden_patterns: list[str],
    allow_destructive: bool,
    evidence_root: Path,
    p,
) -> None:
    from ..models import utcnow

    result = TestResult(
        scenario_id=scenario.id,
        status="SKIPPED",
        started_at=utcnow(),
        step_outcomes=[],
    )
    db.session.add(result)
    db.session.flush()

    scenario_dir = evidence_root / f"scenario_{scenario.id}"
    scenario_dir.mkdir(parents=True, exist_ok=True)

    recording_options = {} if secrets else {
        "record_video_dir": str(scenario_dir / "videos"),
        "record_video_size": {"width": 1280, "height": 720},
    }
    context = browser.new_context(
        ignore_https_errors=True,
        viewport={"width": 1280, "height": 720},
        **recording_options,
    )
    if not secrets:
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
    page = context.new_page()

    console_errors: list[str] = []
    failed_requests: list[str] = []
    last_status: int | None = None

    def on_console(msg):
        if msg.type == "error":
            console_errors.append(mask_secrets(msg.text[:500], secrets))

    def on_page_error(exc):
        console_errors.append(mask_secrets(f"PageError: {exc}", secrets))

    def on_request_failed(req):
        failed_requests.append(mask_secrets(f"{req.url[:300]} — {req.failure}", secrets))

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)

    outcomes: list[StepOutcome] = []
    has_verified_expect = False
    blocked = False
    credentials = config.get("credentials") or {}
    base_url = campaign.target.base_url
    allowed_hosts = build_allowed_hosts(base_url, config.get("extra_domains"))

    steps = sorted(scenario.steps, key=lambda s: s.step_order)
    for step in steps:
        params = step.parameters or {}
        target = params.get("target") or {}
        value = str(params.get("value") or "")
        expect = params.get("expect")
        order = step.step_order

        if blocked:
            outcomes.append(
                StepOutcome(order, step.action, "SKIPPED", "Étape non exécutée après l’interruption du scénario")
            )
            continue

        # actions interdites (§10.6-7)
        if not allow_destructive:
            forbidden = find_forbidden_action(step.action, params, forbidden_patterns)
            if forbidden:
                outcomes.append(
                    StepOutcome(
                        order,
                        step.action,
                        "BLOCKED",
                        f"Action interdite par la politique de sécurité (motif : {forbidden})",
                    )
                )
                blocked = True
                continue

        # injection de credentials si la valeur correspond à un identifiant configuré
        fill_value = value
        if step.action == "fill" and re.fullmatch(r"\{[A-Za-z_][A-Za-z0-9_]*\}", value):
            fill_value = credentials.get(value[1:-1])
            if not fill_value:
                outcomes.append(StepOutcome(order, step.action, "BLOCKED", "Variable de test introuvable"))
                blocked = True
                continue
            if not is_url_allowed(page.url, allowed_hosts, base_url):
                outcomes.append(StepOutcome(order, step.action, "BLOCKED", "Domaine non autorisé pour les identifiants"))
                blocked = True
                continue

        outcome_status = "PASSED"
        message = ""
        try:
            if step.action == "goto":
                fill_value = _navigation_url(value, target, base_url)
                if not is_url_allowed(fill_value, allowed_hosts, base_url):
                    raise ValueError("URL de navigation hors du périmètre autorisé")
            if step.action == "read_text":
                locator = _locator_for(page, target)
                locator.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
                observed_text = locator.inner_text(timeout=STEP_TIMEOUT_MS).strip()
                message = f"Texte relevé : {observed_text[:500]}"
            else:
                nav_status = _perform_action(page, step.action, target, fill_value, params, secrets)
                if nav_status is not None:
                    last_status = nav_status
            if expect:
                has_verified_expect = True
                ok, detail = _check_expect(page, expect, last_status, console_errors, target)
                outcome_status = "PASSED" if ok else "FAILED"
                message = f"{message} · {detail}" if message else detail
            elif not message:
                message = f"Étape '{step.action}' exécutée"
        except Exception as exc:  # noqa: BLE001 — élément absent / timeout
            outcome_status = "ERROR"
            message = str(exc)
            blocked = True
            if step.action == "fill":
                try:
                    message = f"{message[:350]}\nChamps observés : {_visible_form_fields(page)}"
                except Exception:  # noqa: BLE001 — page indisponible
                    pass

        # capture par étape
        screenshot_rel = None
        if not secrets:
            try:
                shot_path = scenario_dir / f"step_{order:02d}.png"
                page.screenshot(path=str(shot_path), full_page=False)
                screenshot_rel = str(shot_path)
                db.session.add(Evidence(
                    test_result_id=result.id,
                    evidence_type="screenshot",
                    file_path=str(shot_path),
                    evidence_metadata={"step_order": order, "status": outcome_status},
                ))
            except Exception:  # noqa: BLE001
                pass

        outcomes.append(
            StepOutcome(
                order,
                step.action,
                outcome_status,
                mask_secrets(message, secrets)[:650],
                expect.get("type") if expect else None,
                screenshot_rel,
            )
        )
        db.session.commit()

    # erreurs JS / réseau → WARNING si PASSED (FR-33)
    runtime_warnings = []
    if console_errors:
        runtime_warnings.append(f"{len(console_errors)} erreur(s) JS")
    if failed_requests:
        runtime_warnings.append(f"{len(failed_requests)} requête(s) échouée(s)")

    verdict = combine_outcomes(outcomes, has_verified_expect, runtime_warnings)

    # journaux + trace en preuves
    log_path = scenario_dir / "log.txt"
    log_lines = [
        f"Statut final : {verdict.status}",
        f"Résumé : {verdict.summary}",
        "",
        "== Erreurs JS ==",
        *console_errors,
        "",
        "== Requêtes échouées ==",
        *failed_requests,
        "",
        "== Étapes ==",
        *[f"{o.step_order}. [{o.status}] {o.action} — {o.message}" for o in outcomes],
    ]
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    db.session.add(
        Evidence(
            test_result_id=result.id,
            evidence_type="log",
            file_path=str(log_path),
            evidence_metadata={"console_errors": len(console_errors)},
        )
    )

    if not secrets:
        _save_recordings(context, scenario_dir, result)

    try:
        context.close()
    except Exception:  # noqa: BLE001
        pass

    result.status = verdict.status
    result.actual_result = verdict.summary
    result.error_summary = (
        verdict.summary if verdict.status in ("FAILED", "ERROR", "BLOCKED") else None
    )
    result.step_outcomes = [o.to_dict() for o in verdict.outcomes]
    result.finished_at = utcnow()
    db.session.commit()


def _save_recordings(context, scenario_dir, result):
    try:
        trace_path = scenario_dir / "trace.zip"
        context.tracing.stop(path=str(trace_path))
        db.session.add(
            Evidence(
                test_result_id=result.id,
                evidence_type="trace",
                file_path=str(trace_path),
                evidence_metadata={},
            )
        )
    except Exception:  # noqa: BLE001
        pass

    for video in (scenario_dir / "videos").glob("*.webm"):
        db.session.add(
            Evidence(
                test_result_id=result.id,
                evidence_type="video",
                file_path=str(video),
                evidence_metadata={},
            )
        )


def _run_analysis(campaign_id: int) -> None:
    """FR-36 : analyse IA présentée comme hypothèse, pas comme preuve."""
    from . import agent

    if not agent.is_configured():
        return
    campaign = db.session.get(TestCampaign, campaign_id)
    if (campaign.target.configuration or {}).get("credentials"):
        return
    results = (
        TestResult.query.join(TestScenario)
        .filter(
            TestScenario.campaign_id == campaign_id,
            TestResult.status.in_(["FAILED", "ERROR", "BLOCKED"]),
        )
        .all()
    )
    for result in results:
        try:
            payload = json.dumps(
                {
                    "scenario": result.scenario.title,
                    "status": result.status,
                    "summary": result.actual_result,
                    "steps": result.step_outcomes,
                },
                ensure_ascii=False,
            )
            data = agent.chat_json(
                system=(
                    "Tu analyses des échecs de tests E2E. Réponds en JSON : "
                    '{"explanation": "...", "hypothesis": "...", "confidence": "low|medium|high"}. '
                    "L'explanation décrit les faits observés ; la hypothesis est une cause "
                    "possible NON confirmée. En français."
                ),
                user=payload,
            )
            if isinstance(data, dict):
                result.analysis = json.dumps(data, ensure_ascii=False)
                db.session.commit()
        except agent.AgentError:
            continue


def extract_scenario_json(steps) -> str:
    """Utilitaire de débogage : sérialise les étapes d'un scénario."""
    return json.dumps(
        [
            {"order": s.step_order, "action": s.action, "parameters": s.parameters}
            for s in steps
        ],
        ensure_ascii=False,
    )

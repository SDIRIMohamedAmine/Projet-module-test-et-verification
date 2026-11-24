"""Browser smoke test for the campaign workflow, using disposable local storage."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from threading import Thread

from flask import send_from_directory
from playwright.sync_api import expect, sync_playwright
import pytest
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import create_app
from app.config import Config
from app.services.executor import _covering_dialog, _read_near_label, _resolve_action_target
from app.services.explorer import EXTRACT_ELEMENTS_JS
from app.services.scenario_generator import _review_scenarios, _sanitize_scenarios
from demo_app.app import app as demo


def test_generated_login_is_checked_against_exploration():
    base = "http://127.0.0.1:5001"
    login = base + "/login"
    scenarios = _sanitize_scenarios({"scenarios": [{"title": "Connexion", "steps": [
        {"action": "goto", "target": {"value": login}},
        {"action": "fill", "value": "{test_password}", "target": {"value": "#password"}},
        {"action": "click", "target": {"strategy": "role", "value": "button",
         "fallback": {"strategy": "text", "value": "Se connecter"}},
         "expect": {"type": "url_equals", "value": login}},
        {"action": "assert", "target": {"value": "body"},
         "expect": {"type": "visible", "value": "Indicateur utilisateur connecté"}},
    ]}]})
    observed = [{"url": login, "elements": [{"kind": "button", "text": "Se connecter"}]}]
    errors = _review_scenarios(scenarios, base, observed)
    assert any("sélecteur CSS" in error for error in errors)
    assert any("résultat de la connexion" in error for error in errors)
    steps = scenarios[0]["steps"]
    assert steps[0]["value"] == login
    assert steps[2]["target"]["value"] == "button=Se connecter"
    steps[2]["expect"] = {"type": "url_equals", "value": base + "/dashboard"}
    steps.pop()
    assert not _review_scenarios(scenarios, base, observed)


def test_live_page_observations_and_locators():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <h1>Checkout</h1>
            <label for="email">Adresse e-mail</label><input id="email" type="email">
            <input id="nickname" type="text"><input id="password" type="password">
            <section><label>Quantité</label><div><button>−</button><span>1</span>
                <button onclick="this.previousElementSibling.textContent = '2'">+</button></div></section>
            <div><strong>Total</strong><span>9000.00 TND</span></div>
            <button id="checkout">Confirmer la réservation</button>
            <div role="dialog" style="display:none;position:fixed;inset:0;background:white">
                <h2>Connexion requise</h2><button>Connexion</button>
            </div>
        """)
        elements = page.evaluate(EXTRACT_ELEMENTS_JS)
        assert any(el["kind"] == "button" and el.get("text") == "+" and "1" in el.get("context", "") for el in elements)
        assert any(el["kind"] == "value" and el.get("context") == "Total9000.00 TND" for el in elements)

        field, fallback = _resolve_action_target(page, {"strategy": "placeholder", "value": "Adresse e-mail"}, "fill")
        assert fallback == "label"
        field.fill("qa@example.test")
        generic = {"strategy": "role", "value": "textbox"}
        email, _ = _resolve_action_target(page, generic, "fill", "{account_1_email}")
        password, _ = _resolve_action_target(page, generic, "fill", "{account_1_password}")
        assert email.get_attribute("id") == "email"
        assert password.get_attribute("id") == "password"
        with pytest.raises(ValueError, match="Plusieurs contrôles"):
            _resolve_action_target(page, generic, "fill", "Lina")
        page.evaluate("""() => {
            const button = document.createElement('button');
            button.textContent = 'Modifier';
            button.onclick = () => { button.textContent = 'Enregistrer'; };
            document.body.append(button);
        }""")
        edit, _ = _resolve_action_target(page, {"strategy": "css", "value": "button=Modifier"}, "click")
        edit.click()
        expect(page.locator('button:text-is("Enregistrer")')).to_be_visible()
        increment, fallback = _resolve_action_target(page, {
            "strategy": "css", "value": ".old-increment", "fallback": {"strategy": "role", "value": "button=+"},
        }, "click")
        assert fallback == "role"
        increment.click()
        assert _read_near_label(page, "Quantité") == "2"
        assert _read_near_label(page, "Total") == "9000.00 TND"
        with pytest.raises(ValueError, match="Plusieurs contrôles"):
            _resolve_action_target(page, {"strategy": "css", "value": "button"}, "click")
        page.get_by_role("button", name="Confirmer la réservation").evaluate(
            "button => button.addEventListener('click', () => document.querySelector('[role=dialog]').style.display = 'block')"
        )
        checkout = page.locator("#checkout")
        checkout.click()
        assert _covering_dialog(checkout) == "Connexion requise"
        browser.close()


@contextmanager
def serve(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


def test_campaign_from_browser(tmp_path):
    dist = ROOT / "frontend" / "dist"
    assert (dist / "index.html").is_file(), "Run npm run build in frontend first"

    class TestConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'campaign.db').as_posix()}"
        GROQ_API_KEY = ""
        EVIDENCE_DIR = str(tmp_path / "evidence")
        REPORTS_DIR = str(tmp_path / "reports")

    app = create_app(TestConfig)

    @app.get("/")
    def index():
        return send_from_directory(dist, "index.html")

    @app.get("/assets/<path:name>")
    def assets(name):
        return send_from_directory(dist / "assets", name)

    with serve(demo) as target, serve(app) as platform, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(platform)
        page.get_by_role("button", name="Créer un projet", exact=True).click()
        page.get_by_role("textbox", name="Nom", exact=True).fill("Validation locale")
        page.get_by_role("button", name="Enregistrer").click()
        page.get_by_role("button", name="Ajouter une cible", exact=True).click()
        page.get_by_role("textbox", name="Nom", exact=True).fill("Application de démonstration")
        page.get_by_role("textbox", name="URL de départ").fill(target + "/")
        page.get_by_role("spinbutton", name="Pages", exact=True).fill("2")
        page.get_by_role("button", name="Enregistrer").click()
        page.get_by_role("textbox", name="Objectif facultatif").fill("Vérifier la navigation")
        page.get_by_role("button", name="Créer la campagne").click()
        page.get_by_role("button", name="Explorer la cible").click()
        generate = page.get_by_role("button", name="Générer les scénarios")
        expect(generate).to_be_enabled(timeout=30_000)
        generate.click()
        approve = page.get_by_role("button", name="Approuver les scénarios en attente")
        expect(approve).to_be_enabled(timeout=30_000)
        approve.click()
        scenario = page.locator("article").first
        scenario.get_by_role("button", name="Modifier").click()
        scenario.get_by_role("textbox", name="Titre", exact=True).fill("Scénario relu")
        scenario.get_by_role("button", name="Enregistrer").click()
        expect(scenario.get_by_text("Modifié", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Exécuter les scénarios approuvés (1)")).to_be_visible()
        scenario.get_by_role("button", name="Approuver", exact=True).click()
        page.get_by_role("button", name="Exécuter les scénarios approuvés (2)").click()
        report = page.get_by_role("link", name="Consulter le rapport")
        expect(report).to_be_visible(timeout=45_000)
        expect(page.get_by_text("PASSED 2", exact=True)).to_be_visible()
        result = page.request.get(platform + report.get_attribute("href"))
        assert result.ok and "Scénario relu" in result.text()
        assert "Titre conforme" in result.text()
        evidence = page.get_by_role("link", name="screenshot", exact=False).first
        assert page.request.get(platform + evidence.get_attribute("href")).ok
        page.get_by_role("button", name="Nouvelle campagne", exact=True).click()
        page.get_by_role("button", name="Campagne #1", exact=False).click()
        page.get_by_role("button", name="Résultats", exact=True).click()
        expect(report).to_be_visible()

        page.get_by_role("button", name="Modifier", exact=True).click()
        page.get_by_text("Identifiants de test", exact=True).click()
        for index, name in enumerate(("test_user", "test_password")):
            page.get_by_role("button", name="Ajouter une variable").click()
            page.locator(f'[name="credential-name-{index}"]').fill(name)
            page.locator(f'[name="credential-value-{index}"]').fill("demo")
        page.get_by_role("button", name="Enregistrer").click()
        page.get_by_role("button", name="Nouvelle campagne", exact=True).click()
        expect(page.get_by_text("{test_password}", exact=True)).to_be_visible()
        configuration = page.request.get(platform + "/api/projects/1").json()["targets"][0]
        assert configuration["credential_names"] == ["test_password", "test_user"]
        assert "credentials" not in configuration["configuration"]

        page.get_by_role("button", name="Créer la campagne").click()
        page.get_by_role("button", name="Explorer la cible").click()
        expect(generate).to_be_enabled(timeout=30_000)
        generate.click()
        expect(approve).to_be_enabled(timeout=30_000)
        scenario.get_by_role("button", name="Modifier").click()
        steps = [
            {"action": "goto", "target": {"value": target + "/login"}},
            {"action": "fill", "target": {"value": "#username"}, "value": "{test_user}"},
            {"action": "fill", "target": {"value": "#password"}, "value": "{test_password}",
             "expect": {"type": "value_equals", "value": "{test_password}"}},
            {"action": "click", "target": {"value": "button[type=submit]"},
             "expect": {"type": "url_equals", "value": target + "/dashboard"}},
            {"action": "read_text", "target": {"value": ".ok"}},
            {"action": "goto", "value": target + "/missing-test-page",
             "expect": {"type": "http_status", "value": "200"}},
            {"action": "goto", "value": target + "/logout"},
        ]
        scenario.get_by_role("textbox", name="Étapes (JSON)").fill(json.dumps(steps))
        scenario.get_by_role("button", name="Enregistrer").click()
        scenario.get_by_role("button", name="Approuver", exact=True).click()
        page.get_by_role("button", name="Exécuter les scénarios approuvés (1)").click()
        expect(report).to_be_visible(timeout=45_000)
        report_body = page.request.get(platform + report.get_attribute("href")).text()
        assert "Texte relevé : Connexion réussie." in report_body
        assert "Valeur de test conforme" in report_body
        result = page.request.get(platform + "/api/campaigns/2/results").json()["by_scenario"]
        outcome = next(iter(result.values()))
        assert [step["status"] for step in outcome["step_outcomes"]][-2:] == ["FAILED", "SKIPPED"]
        log_id = next(evidence["id"] for evidence in outcome["evidences"] if evidence["type"] == "log")
        assert f"HTTP 404 — GET {target}/missing-test-page" in page.request.get(
            platform + f"/api/evidences/{log_id}/file"
        ).text()
        assert "screenshot #" not in report_body
        assert "trace #" not in report_body
        assert "video #" not in report_body
        scenario_id = next(iter(result))
        steps[3]["expect"]["value"] = target + "/login"
        invalid = page.request.put(platform + f"/api/scenarios/{scenario_id}", data={"steps": steps})
        assert invalid.ok and invalid.json()["validation_errors"]
        approval = page.request.post(platform + f"/api/scenarios/{scenario_id}/approval",
                                     data={"status": "approved"})
        assert approval.status == 409
        browser.close()

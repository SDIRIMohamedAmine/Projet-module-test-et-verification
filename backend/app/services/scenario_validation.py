"""Validation structurelle des scénarios avant approbation."""
import re
from urllib.parse import urljoin, urlsplit

TARGET_ACTIONS = {"click", "fill", "select", "check", "uncheck", "read_text"}
HTML_TAGS = set("a article aside b body button div em fieldset footer form h1 h2 h3 h4 h5 h6 header html input label legend li main nav ol option output p section select small span strong table tbody td textarea th tr ul svg".split())


def _prose_selector(value):
    words = value.split()
    if len(words) == 1 and value[0].isupper() and value.isalpha():
        return value.lower() not in HTML_TAGS
    return len(words) > 1 and re.fullmatch(r"[\w\s-]+", value) and any(
        word.lower() not in HTML_TAGS and "-" not in word for word in words
    )


def _password_field(target, value):
    locator = str(target.get("value") or "").lower()
    return any(word in locator or word in value.lower() for word in ("password", "mot de passe", "passwd"))


def _http_url(base_url, value):
    if not value or any(char.isspace() for char in value):
        return None
    try:
        resolved = urljoin(base_url, value)
        parsed = urlsplit(resolved)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return resolved
    except ValueError:
        pass
    return None


def validate_steps(steps, base_url):
    if not steps:
        return ["Ajoutez au moins une étape."]
    errors = []
    current_url = base_url
    password_filled = False
    pending_login_check = None

    for index, step in enumerate(steps, 1):
        action = step["action"]
        target = step.get("target") or {}
        value = str(step.get("value") or "").strip()
        target_value = str(target.get("value") or "").strip()
        expect = step.get("expect") or {}
        expect_type = expect.get("type")
        expected = str(expect.get("value") or "").strip()
        expected_url = _http_url(current_url, expected) if expect_type == "url_equals" else None
        if expect_type == "url_equals" and not expected_url:
            errors.append(f"Étape {index} : URL attendue manquante ou invalide.")

        if action == "goto":
            if pending_login_check:
                errors.append(f"Étape {pending_login_check} : vérifiez le résultat de la connexion avant de changer de page.")
                pending_login_check = None
            destination = value or (target_value if target_value.startswith(("http://", "https://", "/")) else "")
            resolved = _http_url(base_url, destination)
            if not resolved:
                errors.append(f"Étape {index} : URL de navigation manquante ou invalide.")
            current_url = expected_url or resolved or current_url
            password_filled = False
        elif action in TARGET_ACTIONS and not target_value:
            errors.append(f"Étape {index} : le contrôle à utiliser doit être indiqué.")

        if action == "fill" and _password_field(target, value):
            password_filled = True
        elif password_filled and action in {"click", "press"}:
            password_filled = False
            pending_login_check = index
            if action == "click" and (
                (target.get("strategy") == "role" and "=" not in target_value)
                or (target.get("strategy") == "css" and target_value in {"button", "*"})
            ):
                errors.append(f"Étape {index} : précisez le bouton qui soumet le formulaire de connexion.")

        invalid_visibility = expect_type in {"visible", "hidden"} and _prose_selector(expected)
        if invalid_visibility:
            errors.append(f"Étape {index} : la vérification de visibilité exige un sélecteur CSS, pas une description.")

        if pending_login_check:
            if expected_url and expected_url != current_url:
                current_url = expected_url
                pending_login_check = None
            elif expect_type == "visible" and not invalid_visibility:
                selector = expected or target_value
                if (
                    selector and selector.lower() not in {"body", "html", "*", "form", "main", "input", "button"}
                    and not _password_field({"value": selector}, "")
                    and not re.fullmatch(r"input\[type=['\"]?email['\"]?\]", selector, re.I)
                ):
                    pending_login_check = None
            elif expect_type == "text_contains" and expected:
                pending_login_check = None

    if pending_login_check:
        errors.append(f"Étape {pending_login_check} : vérifiez le résultat de la connexion avec une URL différente ou un élément visible précis.")
    return errors


def saved_scenario_errors(scenario):
    steps = [
        {**(step.parameters or {}), "action": step.action}
        for step in sorted(scenario.steps, key=lambda step: step.step_order)
    ]
    return validate_steps(steps, scenario.campaign.target.base_url)

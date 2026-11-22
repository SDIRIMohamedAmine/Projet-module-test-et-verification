"""Client Groq (compatible OpenAI) pour l'agent IA + mode dégradé sans clé."""
from __future__ import annotations

import json
import re

import requests
from flask import current_app


class AgentError(Exception):
    pass


def is_configured() -> bool:
    return bool(current_app.config.get("GROQ_API_KEY"))


def chat_json(system: str, user: str, temperature: float = 0.2) -> dict | list:
    """Appel Groq attendu en JSON strict. Lève AgentError sinon."""
    api_key = current_app.config.get("GROQ_API_KEY")
    if not api_key:
        raise AgentError("GROQ_API_KEY non configurée")
    base = current_app.config["GROQ_BASE_URL"].rstrip("/")
    model = current_app.config.get("GROQ_MODEL") or "mimo-v2.6-flash"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.post(
            f"{base}/chat/completions", json=payload, headers=headers, timeout=90
        )
        if resp.status_code != 200:
            detail = resp.text[:500]
            # repli sur un modèle gratuit large si le modèle demandé est indisponible
            if resp.status_code in (400, 404) and model != "llama-3.3-70b-versatile":
                payload["model"] = "llama-3.3-70b-versatile"
                resp = requests.post(
                    f"{base}/chat/completions", json=payload, headers=headers, timeout=90
                )
                if resp.status_code != 200:
                    raise AgentError(f"Erreur Groq ({resp.status_code}) : {resp.text[:500]}")
            else:
                raise AgentError(f"Erreur Groq ({resp.status_code}) : {detail}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json(content)
    except requests.RequestException as exc:
        raise AgentError(f"Impossible de joindre Groq : {exc}") from exc


def _parse_json(content: str):
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", content, re.S)
        if match:
            return json.loads(match.group(0))
        raise AgentError("Réponse de l'IA non valide (JSON attendu)")

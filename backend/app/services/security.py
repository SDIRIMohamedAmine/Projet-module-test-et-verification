"""Contrôles de sécurité : domaines autorisés, masquage secrets, actions interdites."""
from __future__ import annotations

import re
from urllib.parse import urlparse

DEFAULT_FORBIDDEN_ACTION_PATTERNS = [
    r"\bdelete\b",
    r"\bremove\b",
    r"\bdestroy\b",
    r"\berase\b",
    r"\bpurchase\b",
    r"\bcheckout\b",
    r"\bpay\b",
    r"\bpayment\b",
    r"\btransfer\b",
    r"\bunsubscribe\b",
]

DEFAULT_SECRET_KEYS = [
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
]


def registrable_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def build_allowed_hosts(base_url: str, extra_domains: list[str] | None = None) -> set[str]:
    hosts = {registrable_host(base_url)}
    for domain in extra_domains or []:
        domain = domain.strip().lower()
        if domain:
            hosts.add(domain[4:] if domain.startswith("www.") else domain)
    hosts.discard("")
    return hosts


def is_url_allowed(url: str, allowed_hosts: set[str], base_url: str) -> bool:
    """Autorise le domaine de base, ses sous-domaines et les domaines supplémentaires."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    host = host[4:] if host.startswith("www.") else host
    base_host = registrable_host(base_url)
    for allowed in allowed_hosts:
        if host == allowed or host.endswith("." + allowed):
            return True
    # sous-domaines du domaine de base
    if base_host and (host == base_host or host.endswith("." + base_host)):
        return True
    return False


def mask_secrets(text: str, extra_values: list[str] | None = None) -> str:
    """Masque les valeurs secrètes et paires clé=valeur sensibles dans un texte."""
    if not text:
        return text
    masked = text
    for value in extra_values or []:
        if value and len(value) >= 3:
            masked = masked.replace(value, "***")
    patterns = [
        r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S+",
        r"(?i)(bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*",
    ]
    for pattern in patterns:
        masked = re.sub(pattern, r"\1***", masked)
    return masked


def find_forbidden_action(
    step_action: str, parameters: dict, extra_patterns: list[str] | None = None
) -> str | None:
    """Retourne le motif interdit trouvé dans une étape, ou None."""
    blob = " ".join(
        str(parameters.get(k, ""))
        for k in ("value", "text", "selector", "url", "description")
    )
    blob = f"{step_action} {blob}".lower()
    patterns = DEFAULT_FORBIDDEN_ACTION_PATTERNS + (extra_patterns or [])
    for pattern in patterns:
        if re.search(pattern, blob):
            return pattern
    return None


def validate_target_url(url: str) -> str | None:
    """Retourne un message d'erreur si l'URL est invalide, sinon None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "L'URL doit commencer par http:// ou https://"
    if not parsed.hostname:
        return "L'URL ne contient pas de domaine valide"
    return None

"""Exploration automatisée d'une application cible avec Playwright (FR-11..FR-17)."""
from __future__ import annotations

import time
from urllib.parse import urldefrag, urljoin, urlparse

from ..models import ExplorationPage, TestCampaign, db
from .security import build_allowed_hosts, is_url_allowed

EXTRACT_ELEMENTS_JS = """
() => {
  const out = [];
  const seen = new Set();
  const describe = (el, kind) => {
    try {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0 && kind !== 'form') return null;
      const info = { kind, tag: el.tagName.toLowerCase() };
      const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120);
      if (text) info.text = text;
      if (el.id) info.id = el.id;
      const name = el.getAttribute('name');
      if (name) info.name = name;
      const aria = el.getAttribute('aria-label');
      if (aria) info.aria_label = aria;
      const ph = el.getAttribute('placeholder');
      if (ph) info.placeholder = ph;
      const type = el.getAttribute('type');
      if (type) info.type = type;
      const href = el.getAttribute('href');
      if (href) info.href = href;
      const role = el.getAttribute('role');
      if (role) info.role = role;
      if (el.tagName === 'SELECT') {
        info.options = Array.from(el.options).slice(0, 20).map(o => o.text.trim());
      }
      if (el.tagName === 'FORM') {
        info.action = el.getAttribute('action');
        info.method = (el.getAttribute('method') || 'get').toLowerCase();
      }
      if (el.labels && el.labels.length) {
        info.label = (el.labels[0].innerText || '').trim().slice(0, 120);
      }
      return info;
    } catch (e) { return null; }
  };
  const add = (el, kind) => {
    const info = describe(el, kind);
    if (!info) return;
    const key = kind + '|' + (info.id || info.name || info.text || info.href || info.placeholder || '') + '|' + (info.type || '');
    if (seen.has(key)) return;
    seen.add(key);
    out.push(info);
  };
  document.querySelectorAll('a[href]').forEach(a => add(a, 'link'));
  document.querySelectorAll('button, input[type=button], input[type=submit], [role=button]').forEach(b => add(b, 'button'));
  document.querySelectorAll('input:not([type=hidden]), textarea, select').forEach(i => add(i, 'field'));
  document.querySelectorAll('form').forEach(f => add(f, 'form'));
  document.querySelectorAll('nav a, menu a').forEach(n => add(n, 'nav'));
  return out.slice(0, 200);
}
"""


def _normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/") or url


def _internal_links(page) -> list[str]:
    return page.eval_on_selector_all(
        "a[href]",
        """els => els.map(a => {
            try { return new URL(a.getAttribute('href'), location.href).href; }
            catch (e) { return null; }
        }).filter(Boolean)""",
    )


def explore_campaign(campaign_id: int, app=None) -> None:
    """Exécute l'exploration en arrière-plan pour une campagne (FR-11..FR-17)."""
    from flask import current_app

    from playwright.sync_api import sync_playwright

    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return
    target = campaign.target
    config = dict(target.configuration or {})
    limits = dict(current_app.config["DEFAULT_EXPLORATION_LIMITS"])
    limits.update(config.get("limits") or {})

    campaign.status = "exploring"
    campaign.task_stage = "exploration"
    campaign.task_message = "Ouverture du navigateur…"
    campaign.task_progress = 0
    campaign.error_message = None
    db.session.commit()

    base_url = target.base_url
    allowed_hosts = build_allowed_hosts(base_url, config.get("extra_domains"))
    exclude_patterns = [p.lower() for p in (config.get("exclude_url_patterns") or [])]
    max_pages = int(limits["max_pages"])
    max_depth = int(limits["max_depth"])
    max_duration = float(limits["max_duration_seconds"])
    start = time.time()

    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(base_url, 0)]
    found_links: set[str] = set()
    console_errors_all: list[dict] = []
    failed_requests_all: list[dict] = []

    def set_progress(done: int, message: str):
        campaign.task_progress = min(99, int(done / max(1, max_pages) * 100))
        campaign.task_message = message
        db.session.commit()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(ignore_https_errors=True, viewport={"width": 1280, "height": 720})
            page = context.new_page()

            page_console: list[dict] = []
            page_failed: list[dict] = []

            def on_console(msg):
                if msg.type == "error":
                    page_console.append({"text": msg.text[:500], "at": time.time()})

            def on_request_failed(req):
                page_failed.append(
                    {"url": req.url[:500], "error": (req.failure or "")[:200], "at": time.time()}
                )

            page.on("console", on_console)
            page.on("requestfailed", on_request_failed)

            while queue:
                if time.time() - start > max_duration:
                    break
                if len(visited) >= max_pages:
                    break

                url, depth = queue.pop(0)
                norm = _normalize_url(url)
                if norm in visited:
                    continue
                if not is_url_allowed(url, allowed_hosts, base_url):
                    continue
                lowered = url.lower()
                if any(pat in lowered for pat in exclude_patterns):
                    continue

                visited.add(norm)
                page_console.clear()
                page_failed.clear()
                set_progress(len(visited), f"Exploration de {urlparse(url).path or '/'} (prof. {depth})")

                record = ExplorationPage(
                    campaign_id=campaign.id,
                    url=url,
                    title=None,
                    discovered_elements=[],
                    exploration_status="visited",
                    depth=depth,
                    console_errors=[],
                    failed_requests=[],
                )
                try:
                    response = page.goto(
                        url, wait_until="domcontentloaded", timeout=15000
                    )
                    if response and response.status >= 400:
                        record.exploration_status = f"http_{response.status}"
                    try:
                        page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:  # noqa: BLE001 — networkidle optionnel
                        pass
                    record.title = (page.title() or "")[:500] or None
                    elements = page.evaluate(EXTRACT_ELEMENTS_JS)
                    record.discovered_elements = elements
                    record.console_errors = list(page_console)
                    record.failed_requests = list(page_failed)
                    console_errors_all.extend(page_console)
                    failed_requests_all.extend(page_failed)

                    if depth < max_depth:
                        for link in _internal_links(page):
                            if not is_url_allowed(link, allowed_hosts, base_url):
                                continue
                            norm_link = _normalize_url(link)
                            if norm_link in visited or norm_link in found_links:
                                continue
                            if any(pat in link.lower() for pat in exclude_patterns):
                                continue
                            found_links.add(norm_link)
                            queue.append((link, depth + 1))
                except Exception as exc:  # noqa: BLE001 — page inaccessible
                    record.exploration_status = "error"
                    record.console_errors = list(page_console)
                    if record.discovered_elements is None:
                        record.discovered_elements = []
                    record.discovered_elements = list(record.discovered_elements or [])
                    db.session.add(record)
                    db.session.commit()
                    continue

                db.session.add(record)
                db.session.commit()

            browser.close()
    except Exception as exc:  # noqa: BLE001
        campaign.status = "failed"
        campaign.task_stage = "failed"
        campaign.error_message = f"Échec de l'exploration : {exc}"[:2000]
        campaign.task_message = campaign.error_message
        db.session.commit()
        return

    campaign.status = "explored"
    campaign.task_stage = "exploration_done"
    campaign.task_progress = 100
    campaign.task_message = (
        f"Exploration terminée : {len(visited)} page(s), "
        f"{len(console_errors_all)} erreur(s) JS, "
        f"{len(failed_requests_all)} requête(s) échouée(s)."
    )
    db.session.commit()

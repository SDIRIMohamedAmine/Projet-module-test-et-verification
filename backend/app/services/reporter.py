"""Génération du rapport HTML de campagne (FR-38..FR-43)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from flask import current_app

from ..models import Evidence, TestCampaign, TestResult, TestScenario, db

STATUS_COLORS = {
    "PASSED": "#1a7f37",
    "FAILED": "#cf222e",
    "ERROR": "#a40e26",
    "BLOCKED": "#9a6700",
    "SKIPPED": "#57606a",
    "WARNING": "#bc4c00",
}

_CSS = """
body { font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; margin: 0; background: #f6f8fa; color: #1f2328; }
header { background: #0969da; color: #fff; padding: 20px 32px; }
header h1 { margin: 0 0 4px; font-size: 22px; }
header p { margin: 0; opacity: .9; font-size: 14px; }
main { padding: 24px 32px; max-width: 1100px; margin: 0 auto; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.card { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 14px 20px; min-width: 110px; text-align: center; }
.card .num { font-size: 26px; font-weight: 700; }
.card .lbl { font-size: 12px; color: #57606a; text-transform: uppercase; }
h2 { font-size: 18px; border-bottom: 1px solid #d0d7de; padding-bottom: 6px; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d0d7de; border-radius: 8px; overflow: hidden; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #d0d7de; font-size: 14px; vertical-align: top; }
th { background: #f6f8fa; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; color: #fff; font-size: 12px; font-weight: 600; }
.scenario { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; }
.scenario h3 { margin: 0 0 6px; font-size: 16px; }
.meta { color: #57606a; font-size: 13px; margin-bottom: 8px; }
.step { padding: 6px 0 6px 12px; border-left: 3px solid #d0d7de; margin: 6px 0; font-size: 14px; }
.step.PASSED { border-color: #1a7f37; } .step.FAILED { border-color: #cf222e; }
.step.ERROR { border-color: #a40e26; } .step.BLOCKED { border-color: #9a6700; }
.step.SKIPPED { border-color: #57606a; }
.analysis { background: #fff8c5; border: 1px solid #d4a72c; border-radius: 6px; padding: 10px 14px; margin-top: 10px; font-size: 14px; }
.analysis strong { color: #7d4e00; }
.evidence a { color: #0969da; margin-right: 12px; font-size: 13px; }
.error-box { background: #ffebe9; border: 1px solid #ff818266; border-radius: 6px; padding: 12px 16px; margin: 12px 0; }
footer { text-align: center; color: #57606a; font-size: 12px; padding: 16px; }
"""


def _badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#57606a")
    return f'<span class="badge" style="background:{color}">{escape(status)}</span>'


def _fmt_dt(dt) -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_report(campaign_id: int) -> Path:
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        raise ValueError("Campagne introuvable")

    scenarios = (
        TestScenario.query.filter(
            TestScenario.campaign_id == campaign_id,
            TestScenario.approval_status != "deleted",
        )
        .order_by(TestScenario.id)
        .all()
    )
    results = {
        r.scenario_id: r
        for r in TestResult.query.join(TestScenario)
        .filter(TestScenario.campaign_id == campaign_id)
        .all()
    }

    counts: dict[str, int] = {}
    executed = 0
    passed = 0
    for sc in scenarios:
        r = results.get(sc.id)
        if r:
            counts[r.status] = counts.get(r.status, 0) + 1
            executed += 1
            if r.status == "PASSED":
                passed += 1
    success_rate = round(passed / executed * 100, 1) if executed else 0.0

    target = campaign.target
    project = target.project

    cards = "".join(
        f'<div class="card"><div class="num" style="color:{STATUS_COLORS.get(k, "#1f2328")}">{v}</div>'
        f'<div class="lbl">{k}</div></div>'
        for k, v in sorted(counts.items())
    )
    cards = (
        f'<div class="card"><div class="num">{len(scenarios)}</div><div class="lbl">Scénarios</div></div>'
        f'<div class="card"><div class="num">{success_rate}%</div><div class="lbl">Réussite</div></div>'
        + cards
    )

    rows = []
    detail_blocks = []
    for sc in scenarios:
        r = results.get(sc.id)
        status = r.status if r else "SKIPPED"
        rows.append(
            "<tr>"
            f"<td>{sc.id}</td>"
            f"<td>{escape(sc.title)}</td>"
            f"<td>{escape(sc.kind)}</td>"
            f"<td>{escape(sc.approval_status)}</td>"
            f"<td>{_badge(status)}</td>"
            f"<td>{escape((r.actual_result if r else '') or '—')}</td>"
            "</tr>"
        )

        steps_html = []
        outcomes = (r.step_outcomes if r else []) or []
        outcome_by_order = {o.get("step_order"): o for o in outcomes}
        for step in sorted(sc.steps, key=lambda s: s.step_order):
            o = outcome_by_order.get(step.step_order, {})
            st = o.get("status", "SKIPPED")
            params = step.parameters or {}
            target_info = params.get("target") or {}
            desc = (
                f"{step.step_order}. <strong>{escape(step.action)}</strong> "
                f"→ {escape(target_info.get('value') or params.get('value') or '')}"
            )
            if step.expected_observation:
                desc += f" <em>({escape(step.expected_observation)})</em>"
            steps_html.append(
                f'<div class="step {st}">{_badge(st)} {desc}'
                f'<div class="meta">{escape(o.get("message") or "")}</div></div>'
            )

        analysis_html = ""
        if r and r.analysis:
            try:
                a = json.loads(r.analysis)
                analysis_html = (
                    '<div class="analysis"><strong>Analyse IA (hypothèse, non confirmée) — '
                    f'confiance : {escape(str(a.get("confidence", "?")))}</strong><br>'
                    f"{escape(str(a.get('explanation', '')))}<br>"
                    f"<em>Cause possible : {escape(str(a.get('hypothesis', '')))}</em></div>"
                )
            except (json.JSONDecodeError, TypeError):
                pass

        evid_html = ""
        if r:
            evs = Evidence.query.filter_by(test_result_id=r.id).all()
            links = []
            for ev in evs:
                links.append(
                    f'<a href="/api/evidences/{ev.id}/file" target="_blank">'
                    f"{escape(ev.evidence_type)} #{ev.id}</a>"
                )
            if links:
                evid_html = '<div class="evidence" style="margin-top:8px">' + "".join(links) + "</div>"

        expected = escape(sc.expected_result or "—")
        detail_blocks.append(
            f'<div class="scenario"><h3>#{sc.id} — {escape(sc.title)} {_badge(status)}</h3>'
            f'<div class="meta"><strong>Objectif :</strong> {escape(sc.objective or "—")} | '
            f"<strong>Résultat attendu :</strong> {expected}</div>"
            f'{"".join(steps_html)}'
            f'<div class="meta" style="margin-top:8px"><strong>Résultat observé :</strong> '
            f"{escape((r.actual_result if r else '') or 'Non exécuté')}</div>"
            f"{analysis_html}{evid_html}</div>"
        )

    error_box = ""
    if campaign.error_message:
        error_box = f'<div class="error-box"><strong>Erreur de campagne :</strong> {escape(campaign.error_message)}</div>'

    snapshot = campaign.configuration_snapshot or {}
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Rapport campagne #{campaign.id} — {escape(project.name)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Rapport de campagne #{campaign.id} — {escape(project.name)} / {escape(target.name)}</h1>
  <p>URL cible : {escape(target.base_url)} | Objectif : {escape(campaign.objective or "—")}</p>
  <p>Début : {_fmt_dt(campaign.started_at)} — Fin : {_fmt_dt(campaign.finished_at)} | Statut campagne : {escape(campaign.status)}</p>
</header>
<main>
  {error_box}
  <div class="cards">{cards}</div>
  <h2>Synthèse des scénarios</h2>
  <table>
    <tr><th>#</th><th>Titre</th><th>Type</th><th>Approbation</th><th>Statut</th><th>Résultat</th></tr>
    {"".join(rows) or '<tr><td colspan="6">Aucun scénario</td></tr>'}
  </table>
  <h2 style="margin-top:28px">Détail par scénario</h2>
  {"".join(detail_blocks) or "<p>Aucun scénario.</p>"}
  <h2 style="margin-top:28px">Configuration de la campagne</h2>
  <table><tr><th>Paramètre</th><th>Valeur</th></tr>
  {"".join(f"<tr><td>{escape(str(k))}</td><td>{escape(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))}</td></tr>" for k, v in snapshot.items()) or '<tr><td colspan="2">—</td></tr>'}
  </table>
</main>
<footer>Généré le {_fmt_dt(datetime.now(timezone.utc))} — Agent universel de test E2E</footer>
</body>
</html>"""

    reports_dir = Path(current_app.config["REPORTS_DIR"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"campaign_{campaign.id}.html"
    path.write_text(html, encoding="utf-8")
    return path

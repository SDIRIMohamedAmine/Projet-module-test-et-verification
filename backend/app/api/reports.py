"""API rapports HTML et historique."""
from pathlib import Path
from datetime import timezone

from flask import Blueprint, current_app, jsonify, send_file

from ..models import TestCampaign, db
from ..services.reporter import generate_report

bp = Blueprint("reports", __name__)


def _current_report(campaign):
    path = Path(current_app.config["REPORTS_DIR"]) / f"campaign_{campaign.id}.html"
    finished = campaign.finished_at
    if not path.exists() or (
        finished is not None
        and path.stat().st_mtime < (finished if finished.tzinfo else finished.replace(tzinfo=timezone.utc)).timestamp()
    ):
        return generate_report(campaign.id)
    return path


@bp.post("/campaigns/<int:campaign_id>/report")
def create_report(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    try:
        path = generate_report(campaign_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"url": f"/api/campaigns/{campaign_id}/report", "path": str(path)})


@bp.get("/campaigns/<int:campaign_id>/report")
def get_report(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    try:
        path = _current_report(campaign)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return send_file(path, mimetype="text/html")


@bp.get("/campaigns/<int:campaign_id>/report/download")
def download_report(campaign_id):
    campaign = db.session.get(TestCampaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campagne introuvable"}), 404
    try:
        path = _current_report(campaign)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return send_file(path, as_attachment=True, download_name=f"rapport_campagne_{campaign_id}.html")

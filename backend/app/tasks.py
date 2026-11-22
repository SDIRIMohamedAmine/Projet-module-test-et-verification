import logging
import traceback
from typing import Callable

logger = logging.getLogger(__name__)


def run_in_background(app, campaign_id: int, fn: Callable[[int], None]):
    """Exécute fn(campaign_id) dans un thread, avec contexte Flask/DB."""
    import threading

    def wrapper():
        with app.app_context():
            from .models import TestCampaign, db

            try:
                fn(campaign_id)
            except Exception as exc:  # noqa: BLE001 — journalise toute erreur tâche
                logger.error(
                    "Tâche campagne %s échouée: %s\n%s",
                    campaign_id,
                    exc,
                    traceback.format_exc(),
                )
                campaign = db.session.get(TestCampaign, campaign_id)
                if campaign:
                    campaign.status = "failed"
                    campaign.task_stage = "failed"
                    campaign.task_message = str(exc)[:2000]
                    campaign.error_message = str(exc)[:2000]
                    db.session.commit()

    thread = threading.Thread(target=wrapper, daemon=True, name=f"campaign-{campaign_id}")
    thread.start()
    return thread

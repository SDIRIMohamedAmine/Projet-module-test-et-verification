"""Moteur de vérification : assertions déterministes et classification des statuts (§5.6-5.7)."""
from __future__ import annotations

from dataclasses import dataclass, field

VALID_STATUSES = ["PASSED", "FAILED", "ERROR", "BLOCKED", "SKIPPED", "WARNING"]


@dataclass
class StepOutcome:
    step_order: int
    action: str
    status: str  # PASSED | FAILED | ERROR | BLOCKED | SKIPPED
    message: str = ""
    expect_type: str | None = None
    screenshot: str | None = None

    def to_dict(self) -> dict:
        return {
            "step_order": self.step_order,
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "expect_type": self.expect_type,
            "screenshot": self.screenshot,
        }


@dataclass
class ScenarioVerdict:
    status: str
    summary: str
    outcomes: list[StepOutcome] = field(default_factory=list)


def combine_outcomes(
    outcomes: list[StepOutcome], has_verified_expect: bool, runtime_warnings: list[str]
) -> ScenarioVerdict:
    """FR-32/35/37 : détermine le statut global d'un scénario à partir des étapes."""
    if not outcomes:
        return ScenarioVerdict("SKIPPED", "Aucune étape exécutée.")

    statuses = [o.status for o in outcomes]
    if "ERROR" in statuses:
        first = next(o for o in outcomes if o.status == "ERROR")
        return ScenarioVerdict(
            "ERROR",
            f"Erreur technique à l'étape {first.step_order} : {first.message}",
            outcomes,
        )
    if "BLOCKED" in statuses:
        first = next(o for o in outcomes if o.status == "BLOCKED")
        return ScenarioVerdict(
            "BLOCKED",
            f"Scénario bloqué à l'étape {first.step_order} : {first.message}",
            outcomes,
        )
    if "FAILED" in statuses:
        first = next(o for o in outcomes if o.status == "FAILED")
        return ScenarioVerdict(
            "FAILED",
            f"Vérification en échec à l'étape {first.step_order} : {first.message}",
            outcomes,
        )

    if not has_verified_expect:
        # FR-37 : ne pas déclarer PASSED sans vérification explicite
        return ScenarioVerdict(
            "WARNING",
            "Scénario exécuté sans critère de vérification explicite : résultat non concluant.",
            outcomes,
        )
    if runtime_warnings:
        return ScenarioVerdict(
            "WARNING",
            "Vérifications satisfaites mais points d'attention : " + "; ".join(runtime_warnings[:5]),
            outcomes,
        )
    return ScenarioVerdict("PASSED", "Toutes les vérifications définies sont satisfaites.", outcomes)

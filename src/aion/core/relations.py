# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Vokabular für typisierte Beziehungen zwischen klinischen Ereignissen.

Erweitert die Definition aus AION_v1.0:
    e = (p, a, τ, α, ρ)
mit
    ρ : E → R   (Funktion von referenzierten Events zu Beziehungstypen)

statt der ursprünglichen ungetypten Menge ρ ⊆ E.

Das ermöglicht echten Knowledge-Graph: Eine Beobachtung kann z. B. eine
Diagnose `confirms` ODER `rules_out`, ein Antibiotikum kann `response_to`
einer Sepsis sein. Die Semantik wird dadurch explizit.

Das Vokabular ist nicht abgeschlossen: Reference relations sind als
Strings serialisiert, die EventRelation-Konstanten dienen nur als
Konvention. Eigene Domains können beliebige Relation-Strings ergänzen.
"""
from __future__ import annotations

from typing import Final


class EventRelation:
    """Vordefinierte Beziehungstypen. Convenience-Konstanten, kein Enum.

    Eigenes Vokabular ist erlaubt: jeder String mit
    [a-z_][a-z0-9_]* ist gültig (siehe is_valid_relation).
    """

    # ── Diagnostische Beziehungen ───────────────────────────────
    OBSERVATION_OF: Final[str] = "observation_of"   # Messung X gehört zu Diagnose Y
    CONFIRMS:       Final[str] = "confirms"         # Befund X bestätigt Diagnose Y
    RULES_OUT:      Final[str] = "rules_out"        # Befund X schließt Diagnose Y aus
    INDICATES:      Final[str] = "indicates"        # Schwächer als confirms

    # ── Therapeutische Beziehungen ──────────────────────────────
    RESPONSE_TO:    Final[str] = "response_to"      # Therapie X reagiert auf Y
    SIDE_EFFECT_OF: Final[str] = "side_effect_of"   # X ist Nebenwirkung von Y
    CONTRAINDICATES:Final[str] = "contraindicates"  # X spricht gegen Y

    # ── Kausale / temporale Beziehungen ─────────────────────────
    CAUSED_BY:      Final[str] = "caused_by"        # X wurde durch Y verursacht
    TRIGGERED_BY:   Final[str] = "triggered_by"     # schwächer als caused_by
    PRECEDED_BY:    Final[str] = "preceded_by"      # rein zeitlich

    # ── Strukturell / generisch ─────────────────────────────────
    PART_OF:        Final[str] = "part_of"          # X ist Teil von Aufenthalt/Episode Y
    REPLACES:       Final[str] = "replaces"         # X ersetzt Y (Korrektur)
    REFERENCES:     Final[str] = "references"       # Generischer Verweis (Default)

    @classmethod
    def all(cls) -> tuple[str, ...]:
        """Liste aller vordefinierten Relation-Konstanten."""
        return tuple(
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str)
        )


def is_valid_relation(relation: str) -> bool:
    """Prüft, ob ein String als Relation-Bezeichner zulässig ist.

    Akzeptiert lowercase ASCII + Underscore, mit Buchstaben oder Underscore
    als erstem Zeichen. Keine Whitespaces, keine Sonderzeichen.
    """
    if not relation or not isinstance(relation, str):
        return False
    if not (relation[0].isalpha() or relation[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in relation) and relation.islower() or relation == relation.lower()


# Inverse Beziehungen — wenn X "caused_by" Y, dann Y "caused" X.
# Wird vom SQLiteEventStore.referenced_by_with_relation() genutzt.
INVERSE_RELATIONS: Final[dict[str, str]] = {
    EventRelation.CAUSED_BY:       "caused",
    EventRelation.TRIGGERED_BY:    "triggered",
    EventRelation.RESPONSE_TO:     "responded_with",
    EventRelation.OBSERVATION_OF:  "observed_by",
    EventRelation.CONFIRMS:        "confirmed_by",
    EventRelation.RULES_OUT:       "ruled_out_by",
    EventRelation.SIDE_EFFECT_OF:  "had_side_effect",
    EventRelation.PART_OF:         "contains",
    EventRelation.PRECEDED_BY:     "succeeded_by",
    EventRelation.REPLACES:        "replaced_by",
    EventRelation.REFERENCES:      "referenced_by",
    EventRelation.INDICATES:       "indicated_by",
    EventRelation.CONTRAINDICATES: "contraindicated_by",
}


def inverse_of(relation: str) -> str:
    """Liefert die inverse Beziehung. Default: 'inverse_of_<relation>'."""
    return INVERSE_RELATIONS.get(relation, f"inverse_of_{relation}")

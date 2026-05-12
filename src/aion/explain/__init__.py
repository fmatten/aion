# aion/explain/__init__.py
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Erklaerbarkeit nach §22 (FM-3) - Shapley, Counterfactual, Sufficient, Bounded."""
from aion.explain.shapley import (
    ShapleyResult, CounterfactualResult, SufficientExplanation, BoundedExplanation,
    shapley_event_attribution, minimal_counterfactual,
    sufficient_explanation, bounded_explanation,
)
__all__ = [
    "ShapleyResult", "CounterfactualResult",
    "SufficientExplanation", "BoundedExplanation",
    "shapley_event_attribution", "minimal_counterfactual",
    "sufficient_explanation", "bounded_explanation",
]

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""AION ↔ DoWhy-Bridge.

Optionales Plugin zur Validierung kausaler Effekt-Schätzungen mit dem
`dowhy`-Paket: Backdoor-Identifikation, Effekt-Schätzung mit
verschiedenen Methoden (Linear-Regression, Propensity-Score-Matching),
und vor allem **Refutation-Tests** (Placebo, Random Common Cause,
Data Subset Refuter, Add Unobserved Common Cause).

Designentscheidungen:

  * **Lazy-Import** — DoWhy wird erst bei Aufruf der Bridge geladen,
    Verfügbarkeit prüfbar via `aion.has_dowhy()`. AION-Core läuft
    ohne DoWhy.
  * **CausalGraph als Eingabe** — `to_dowhy_model(graph, data, ...)`
    nimmt einen AION-CausalGraph und ein pandas.DataFrame, liefert ein
    DoWhy-`CausalModel`-Objekt. Keine eigene Datenmodell-Schicht.
  * **Pandas verpflichtend** für DoWhy — in dieser Bridge dokumentiert.
    AION-Core bleibt pandas-frei.

Beispiel:

    from aion import CausalGraph, has_dowhy
    if has_dowhy():
        from aion.dowhy import to_dowhy_model, refute_estimate

        g = CausalGraph()
        g.add_edge("Z", "T"); g.add_edge("Z", "Y"); g.add_edge("T", "Y")

        model = to_dowhy_model(g, df, treatment="T", outcome="Y")
        identified = model.identify_effect()
        estimate = model.estimate_effect(identified, method_name="backdoor.linear_regression")
        refutation = refute_estimate(model, identified, estimate, "placebo_treatment_refuter")
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import pandas as pd
    from aion.core.causal import CausalGraph


def _require_dowhy():
    """Importiert dowhy lazy. Wirft ImportError mit klarer Botschaft, falls fehlt."""
    try:
        import dowhy  # noqa: F401
        return dowhy
    except ImportError as e:
        raise ImportError(
            "DoWhy ist nicht installiert. Installation:\n"
            "  pip install -e \".[dowhy]\"\n\n"
            "DoWhy zieht numpy, scipy, pandas, networkx, scikit-learn und "
            "statsmodels — etwa 200 MB Dependencies. Wird bewusst nur als "
            "Optional gehalten, damit AION-Core leichtgewichtig bleibt."
        ) from e


def _require_pandas():
    try:
        import pandas as pd
        return pd
    except ImportError as e:
        raise ImportError(
            "pandas wird für die DoWhy-Bridge benötigt "
            "(kommt automatisch mit `pip install -e \".[dowhy]\"`)."
        ) from e


def causal_graph_to_gml(graph: "CausalGraph") -> str:
    """Konvertiert AION-CausalGraph in GML-String (DoWhy-kompatibel)."""
    lines = ["graph [", "  directed 1"]
    nodes = graph.nodes()
    node_id = {name: i for i, name in enumerate(nodes)}
    for name, i in node_id.items():
        lines.append(f"  node [ id {i} label \"{name}\" ]")
    for src, dst in graph.edges():
        lines.append(f"  edge [ source {node_id[src]} target {node_id[dst]} ]")
    lines.append("]")
    return "\n".join(lines)


def to_dowhy_model(
    graph: "CausalGraph",
    data: "pd.DataFrame",
    treatment: str,
    outcome: str,
    *,
    common_causes: Optional[list[str]] = None,
) -> Any:
    """Baut ein DoWhy-CausalModel aus AION-Graph + pandas-DataFrame.

    Args:
        graph: AION-CausalGraph mit benannten Knoten und gerichteten Kanten.
        data: pandas.DataFrame, dessen Spalten die Knoten-Namen enthalten.
        treatment: Name der Treatment-Variable (muss Knoten im graph sein).
        outcome: Name der Outcome-Variable (muss Knoten im graph sein).
        common_causes: optional, Liste von Confoundern. Wenn None, leitet
                       DoWhy diese aus dem Graph ab.

    Returns:
        dowhy.CausalModel — bereit für `identify_effect()` und
        `estimate_effect(method_name=...)`.

    Raises:
        ValueError: treatment oder outcome ist kein Knoten im Graph.
        ValueError: data fehlt eine Spalte für einen der Knoten.
        ImportError: DoWhy oder pandas nicht installiert.
    """
    _require_dowhy()
    _require_pandas()
    from dowhy import CausalModel

    # Validierung
    nodes = set(graph.nodes())
    if treatment not in nodes:
        raise ValueError(f"Treatment '{treatment}' ist kein Knoten im Graph.")
    if outcome not in nodes:
        raise ValueError(f"Outcome '{outcome}' ist kein Knoten im Graph.")
    missing_cols = nodes - set(data.columns)
    if missing_cols:
        raise ValueError(
            f"DataFrame fehlen Spalten für Graph-Knoten: {sorted(missing_cols)}"
        )

    gml = causal_graph_to_gml(graph)
    return CausalModel(
        data=data,
        treatment=treatment,
        outcome=outcome,
        graph=gml,
        common_causes=common_causes,
    )


def estimate_ate(
    model: Any,
    method_name: str = "backdoor.linear_regression",
) -> Any:
    """Bequemer Wrapper: Identifikation + Schätzung in einem Schritt.

    Args:
        model: DoWhy-CausalModel (aus `to_dowhy_model`).
        method_name: DoWhy-Methode, z. B. "backdoor.linear_regression",
                     "backdoor.propensity_score_matching".

    Returns:
        dowhy CausalEstimate-Objekt; enthält den ATE als `.value`.
    """
    _require_dowhy()
    identified = model.identify_effect(proceed_when_unidentifiable=True)
    return model.estimate_effect(identified, method_name=method_name)


def refute_estimate(
    model: Any,
    identified: Any,
    estimate: Any,
    method: str = "random_common_cause",
    **kwargs: Any,
) -> Any:
    """Wrappt DoWhy refute_estimate für die gängigen Refutation-Methoden.

    Sinnvolle Methoden:
        * "random_common_cause" — fügt zufälligen Confounder hinzu.
          Erwartung: ATE ändert sich kaum. Bestes Default für Robustheits-
          Checks; läuft zuverlässig.
        * "data_subset_refuter" — schätzt auf Datensubset neu.
          Erwartung: ATE stabil über Subsamples.
        * "add_unobserved_common_cause" — simuliert unbeobachteten
          Confounder bekannter Stärke. Quantitative Sensitivitätsanalyse.
        * "placebo_treatment_refuter" — ersetzt Treatment durch Zufall.
          Erwartung: ATE ≈ 0. **Bekannter DoWhy-Bug** (Stand 0.14):
          schlägt fehl mit `identifier_method=None`. Workaround:
          ``identified.identifier_method = "backdoor"`` vor dem Aufruf
          setzen.

    Args:
        model: DoWhy-CausalModel.
        identified: Output von `model.identify_effect(...)`.
        estimate: Output von `model.estimate_effect(...)`.
        method: Name der Refutation-Methode.
        **kwargs: weiterleitende Parameter an DoWhys refute_estimate.

    Returns:
        dowhy CausalRefutation-Objekt mit `.estimated_effect`,
        `.new_effect`, `.refutation_result`.
    """
    _require_dowhy()

    # Workaround für DoWhy-Bug: placebo_treatment_refuter und einige
    # andere greifen auf identifier_method.startswith() zu, das
    # ist None nach `identify_effect()` mit method_name="default".
    if method == "placebo_treatment_refuter" and getattr(identified, "identifier_method", None) is None:
        identified.identifier_method = "backdoor"

    return model.refute_estimate(identified, estimate, method_name=method, **kwargs)


__all__ = [
    "causal_graph_to_gml",
    "to_dowhy_model",
    "estimate_ate",
    "refute_estimate",
]

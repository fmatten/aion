# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Causal-Inference-Demo — Backdoor-Adjustierung an klinischem Beispiel.

Szenario: Wirkt Frühe Antibiotika-Gabe (T) auf das Outcome 30-Tage-Mortalität (Y)?
Confounder: Schweregrad der Sepsis bei Aufnahme (Z) — beeinflusst beides.
"""
import math
from aion import CausalGraph


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def main():
    g = CausalGraph()
    g.add_edge("SOFA_at_admission", "EarlyAntibiotics")  # Z → T
    g.add_edge("SOFA_at_admission", "Mortality30d")       # Z → Y
    g.add_edge("EarlyAntibiotics", "Mortality30d")        # T → Y
    g.add_edge("EarlyAntibiotics", "ICU_Length")          # T → Mediator (Nachfahre, NICHT in Z)
    g.add_edge("ICU_Length", "Mortality30d")

    print("Kausaler Graph:")
    print(g.to_dot())
    print()

    treatment = "EarlyAntibiotics"
    outcome = "Mortality30d"

    bs = g.find_backdoor_adjustment_set(treatment, outcome)
    print(f"Backdoor-Adjustment-Set für {treatment} → {outcome}: {bs}")

    paths = g.backdoor_paths(treatment, outcome)
    print(f"Backdoor-Pfade: {len(paths)}")
    for p in paths:
        print(f"  {' ← '.join(p)}")

    # ── Synthetisches Modell ─────────────────────────────────────
    # SOFA_at_admission ∈ {0=mild, 1=schwer}
    # P(SOFA=1) = 0.4
    # P(Y=1 | T, Z) = sigmoid(-2 + 1.5*Z - 0.8*T)
    z_value_space = {"SOFA_at_admission": ["0", "1"]}

    def p_y_given_t_z(t, y, z):
        z_val = int(z["SOFA_at_admission"]) if z else 0
        t_val = int(t)
        log_odds = -2.0 + 1.5 * z_val - 0.8 * t_val
        p1 = sigmoid(log_odds)
        return p1 if y == "1" else 1 - p1

    def p_z(z):
        z_val = int(z["SOFA_at_admission"])
        return 0.4 if z_val == 1 else 0.6

    p_dox1 = g.do_backdoor(p_y_given_t_z, p_z, z_value_space,
                           treatment=treatment, outcome=outcome,
                           x="1", y="1")
    p_dox0 = g.do_backdoor(p_y_given_t_z, p_z, z_value_space,
                           treatment=treatment, outcome=outcome,
                           x="0", y="1")

    print(f"\nP(Y=1 | do(T=1)) = {p_dox1:.4f}  # mit Antibiotika")
    print(f"P(Y=1 | do(T=0)) = {p_dox0:.4f}  # ohne")
    print(f"Kausaler Effekt (ATE) = {p_dox1 - p_dox0:+.4f}")


if __name__ == "__main__":
    main()

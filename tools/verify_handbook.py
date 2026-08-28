# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Verifikations-Skript: prüft die im Benutzerhandbuch genannten Zahlen
gegen den tatsächlichen Code-Output.

Lauf:
    PYTHONPATH=src python tools/verify_handbook.py

Bricht mit Exit-Code 1 ab, wenn Diskrepanzen gefunden werden.
Genau das, was bei den letzten Iterationen schiefging:
„plausible Zahl" hingeschrieben statt nachgerechnet.
"""
from __future__ import annotations

import math
import sys
from typing import Callable

from aion import (
    CausalGraph, FuzzyAllenInterval, TCFG,
)


# ANSI-Farben für lesbaren Output
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def assert_close(name: str, actual: float, expected: float, tol: float = 0.02) -> bool:
    """Numerische Behauptung prüfen. Toleranz default 2 Prozentpunkte."""
    ok = abs(actual - expected) <= tol
    sign = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    print(f"  {sign} {name}")
    print(f"      tatsächlich = {actual:.4f}")
    print(f"      Handbuch    = {expected:.4f}   (Toleranz ±{tol})")
    return ok


def assert_in_dict(name: str, key, dct: dict, expected: float, tol: float = 0.05) -> bool:
    """Prüft, ob key in dct existiert und Wert nahe am Erwarteten ist."""
    if key not in dct:
        print(f"  {RED}✗{RESET} {name}")
        print(f"      Schlüssel {key!r} fehlt — Handbuch sagt {expected:.4f}")
        return False
    return assert_close(f"{name}  [{key}]", dct[key], expected, tol)


def assert_pattern_found(name: str, pattern: tuple, patterns: dict, expected_support: float) -> bool:
    if pattern not in patterns:
        print(f"  {RED}✗{RESET} {name}")
        print(f"      Pattern {pattern} nicht gefunden — Handbuch sagt {expected_support:.0%}")
        return False
    return assert_close(f"{name}  {pattern}", patterns[pattern], expected_support, 0.05)


def check_allen_handbook_section_5_4() -> list[bool]:
    """Sektion 5.4: I1=[1,4] mit ε_e=0.5 vs I2=[3,6] → overlaps≈0.98, before≈0.02."""
    print(f"\n{YELLOW}── Sektion 5.4 (Allen-Tour) ──{RESET}")
    f1 = FuzzyAllenInterval(1.0, 4.0, 0.0, 0.5)
    f2 = FuzzyAllenInterval(3.0, 6.0, 0.0, 0.0)
    dist = f1.confidence_distribution(f2, n_samples=10_000, seed=42)

    return [
        assert_in_dict("overlaps-Wahrscheinlichkeit", "overlaps", dist, 0.98, tol=0.03),
        assert_in_dict("before-Wahrscheinlichkeit", "before", dist, 0.02, tol=0.02),
        # meets MUSS unter Toleranz liegen (Punktwahrscheinlichkeit = 0)
        ((dist.get("meets", 0.0) < 0.005) and
         (print(f"  {GREEN}✓{RESET} meets ≈ 0 (Punktbedingung)") or True))
        or
        (print(f"  {RED}✗{RESET} meets sollte ≈ 0 sein, ist {dist.get('meets', 0.0):.4f}") or False),
    ]


def check_causal_demo_section_5_5() -> list[bool]:
    """Sektion 5.5: P(Y=1 | do(X=1)) ≈ 0.69 mit Beispiel-Graph."""
    print(f"\n{YELLOW}── Sektion 5.5 (Causal-Tab Demo-Inferenz) ──{RESET}")

    # Genau dieser Graph wird im Tab durch "Beispiel laden" angelegt
    g = CausalGraph()
    g.add_edge("Z1", "X"); g.add_edge("Z1", "Y")
    g.add_edge("Z2", "X"); g.add_edge("Z2", "Y")
    g.add_edge("X", "Y")
    g.add_edge("X", "M"); g.add_edge("M", "Y")

    bs = g.find_backdoor_adjustment_set("X", "Y") or set()
    value_space = {z: ["0", "1"] for z in bs}

    def p_y_given_x_z(x, y, z):
        lin = 0.5 * int(x) + 0.3 * sum(int(v) for v in z.values())
        p1 = 1 / (1 + math.exp(-lin))
        return p1 if y == "1" else 1 - p1

    def p_z(z):
        return 0.5 ** len(z) if z else 1.0

    p1 = g.do_backdoor(p_y_given_x_z, p_z, value_space, "X", "Y", "1", "1")

    return [
        assert_close("P(Y=1 | do(X=1))", p1, 0.69, tol=0.01),
        # Plus: Backdoor-Set sollte {Z1, Z2} sein
        ((bs == {"Z1", "Z2"}) and
         (print(f"  {GREEN}✓{RESET} Backdoor-Set = {bs}") or True))
        or
        (print(f"  {RED}✗{RESET} Backdoor-Set = {bs}, erwartet {{Z1, Z2}}") or False),
    ]


def check_pattern_mining_phase_a_demo() -> list[bool]:
    """phase_a_demo.py: Sepsis-Phasen mit erwarteten Support-Werten."""
    print(f"\n{YELLOW}── phase_a_demo: Pattern-Mining ──{RESET}")
    seqs = [
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Schock", "ICU"],
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Schock", "Tod"],
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Antibiose", "Genesung"],
        ["Aufnahme", "Husten", "Fieber", "SIRS", "Sepsis", "ICU", "Genesung"],
        ["Aufnahme", "Genesung"],
    ]
    patterns = TCFG.mine_patterns(seqs, min_length=2, max_length=4, min_support=0.6)

    return [
        assert_pattern_found(
            "Hauptphase Sepsis-Trias",
            ("Fieber", "SIRS", "Sepsis"),
            patterns, 0.80,
        ),
        assert_pattern_found(
            "Vollständige Aufnahme→Sepsis-Phase",
            ("Aufnahme", "Fieber", "SIRS", "Sepsis"),
            patterns, 0.60,
        ),
    ]


def check_test_count() -> list[bool]:
    """Sektion 3: 93 Tests gesamt, 91 ohne Z3."""
    print(f"\n{YELLOW}── Sektion 3 (Test-Anzahlen) ──{RESET}")
    import subprocess
    import re
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        capture_output=True, text=True,
    )
    # In aktuellen pytest-Versionen ist die -q-Ausgabe pro Datei:
    #   tests/test_causal.py: 13
    # Also die Zahlen auf Doppelpunkten summieren.
    n_tests = 0
    for line in result.stdout.splitlines():
        m = re.match(r"^tests/[^:]+:\s*(\d+)\s*$", line.strip())
        if m:
            n_tests += int(m.group(1))
    # Fallback: alte Variante mit "N tests collected"
    if n_tests == 0:
        match = re.search(r"(\d+)\s+tests?\s+collected", result.stdout + result.stderr)
        if match:
            n_tests = int(match.group(1))

    ok = n_tests == 367
    sign = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    print(f"  {sign} Tests gesamt = {n_tests} (Handbuch: 367)")
    return [ok]


def main() -> int:
    print("Verifikation der numerischen Behauptungen im Benutzerhandbuch.\n")

    all_results: list[bool] = []
    all_results.extend(check_allen_handbook_section_5_4())
    all_results.extend(check_causal_demo_section_5_5())
    all_results.extend(check_pattern_mining_phase_a_demo())
    all_results.extend(check_test_count())

    n_total = len(all_results)
    n_pass = sum(all_results)
    n_fail = n_total - n_pass

    print()
    if n_fail == 0:
        print(f"{GREEN}═══ {n_pass}/{n_total} Behauptungen verifiziert ═══{RESET}")
        return 0
    else:
        print(f"{RED}═══ {n_fail} Diskrepanz(en) bei {n_total} Behauptungen ═══{RESET}")
        print("Handbuch sollte aktualisiert werden.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

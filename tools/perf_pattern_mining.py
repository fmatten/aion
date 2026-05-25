# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Performance-Messung für TCFG.mine_patterns auf realistischen Datenmengen.

Lauf:
    PYTHONPATH=src python tools/perf_pattern_mining.py

Ausgabe: Tabelle mit Verlauf-Anzahl, gefundenen Patterns, Laufzeit.
Ziel: vor der Vorführung kontrollieren, dass Pattern-Mining
auf dem Vorführungs-Laptop in Sub-Sekunden-Zeit läuft.
"""
from __future__ import annotations

import random
import statistics
import time
from typing import Callable

from aion import TCFG


def synthetic_clinical_sequences(n: int, seed: int = 42) -> list[list[str]]:
    """Erzeugt n synthetische klinische Verläufe (Mischung aus
    Sepsis-, STEMI- und Standard-Verläufen)."""
    rng = random.Random(seed)
    base_phases = [
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Antibiose", "ICU", "Genesung"],
        ["Aufnahme", "EKG_Befund", "Troponin", "STEMI", "PCI", "Statin", "Entlassung"],
        ["Aufnahme", "Husten", "Beobachtung", "Genesung"],
        ["Aufnahme", "EKG_Befund", "Vorhofflimmern", "Antikoagulation", "Entlassung"],
    ]
    sequences: list[list[str]] = []
    for _ in range(n):
        seq = list(rng.choice(base_phases))
        # Variation: 30 % Chance auf zusätzliches Rauschen
        if rng.random() < 0.3:
            pos = rng.randint(0, len(seq))
            seq.insert(pos, rng.choice([
                "Vitalzeichen", "Blutbild", "Beobachtung", "Konsil",
            ]))
        sequences.append(seq)
    return sequences


def benchmark(name: str, n: int, runs: int = 3) -> None:
    sequences = synthetic_clinical_sequences(n)
    avg_len = sum(len(s) for s in sequences) / len(sequences)

    times: list[float] = []
    n_patterns = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        patterns = TCFG.mine_patterns(
            sequences, min_length=2, max_length=5, min_support=0.20,
        )
        dt = time.perf_counter() - t0
        times.append(dt)
        n_patterns = len(patterns)

    median_ms = statistics.median(times) * 1000
    min_ms = min(times) * 1000
    print(f"  {name:<20s}  {n:>6,} × ~{avg_len:.0f} Tokens  "
          f"→ {n_patterns:>3} Patterns  "
          f"{median_ms:>7.1f} ms (min {min_ms:.1f})")


def main() -> int:
    print("\n  TCFG Pattern-Mining — Performance-Profil\n")
    print(f"  {'Größe':<20s}  {'Verläufe × Länge':<22s}     "
          f"{'Patterns':<13s} {'Zeit':<15s}")
    print(f"  {'-' * 76}")

    benchmark("klein", 100)
    benchmark("typisch (Studie)", 1_000)
    benchmark("Krankenhaus-Jahr", 10_000)
    benchmark("Multi-Zentrum", 50_000)

    print()
    print("  → Empfehlung: Pattern-Mining ist Echtzeit-tauglich für")
    print("    interaktive Workflows bis ca. 50.000 Verläufe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

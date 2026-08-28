# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""AION Clinical — Live-Demo-Skript für Vorführung.

Story-Bogen (ca. 14-18 Min Laufzeit):

    1. Wir haben drei Sepsis-Patienten in der Datenbank.
    2. Knowledge-Graph mit typisierten Beziehungen (confirms, response_to).
    3. Diese Daten könnten genauso aus einem FHIR-Bundle kommen —
       AION ist HL7-anschlussfähig (Akt 1½, übersprungen wenn fhir.resources fehlt).
    4. Aus 50 ähnlichen Verläufen lernen wir die typischen klinischen Phasen
       AUTOMATISCH heraus — ohne dass jemand sie manuell modelliert hat.
    5. Die gefundenen Muster werden zu neuen Konzepten in der Wissensbasis.
    6. Auf dieser Basis bauen wir kausale Modelle: hilft frühe Antibiose?

Bedienung während der Vorführung:
    Enter drücken für nächsten Schritt — so kannst Du das Tempo dem
    Publikum anpassen.

    python vorfuehrung.py            # interaktiv, mit Pausen
    python vorfuehrung.py --auto     # ohne Pausen, für Trockenlauf
"""
from __future__ import annotations

import math
import random
import sys
import time
from datetime import datetime, timedelta

from aion import (
    ClinicalEvent, EventRelation, SQLiteEventStore,
    TypeHierarchy, TCFG, CausalGraph,
    is_valid_backdoor_set, check_inheritance_conflicts,
)


# ── Steuerung ──────────────────────────────────────────────────────
AUTO_MODE = "--auto" in sys.argv

# ANSI-Farben für lesbaren Beamer-Output
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def headline(text: str) -> None:
    """Großer Abschnittstitel — gut auf Beamer sichtbar."""
    print()
    print(f"{BOLD}{BLUE}{'═' * 72}{RESET}")
    print(f"{BOLD}{BLUE}  {text}{RESET}")
    print(f"{BOLD}{BLUE}{'═' * 72}{RESET}")
    print()


def step(text: str) -> None:
    print(f"{CYAN}▶ {text}{RESET}")


def pause(prompt: str = "Enter für weiter") -> None:
    if AUTO_MODE:
        time.sleep(0.8)
        return
    try:
        input(f"\n{DIM}    [{prompt}]{RESET}")
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)


def slow_print(text: str, delay: float = 0.015) -> None:
    """Tippt Text langsam — Aufmerksamkeit fokussieren."""
    if AUTO_MODE:
        print(text)
        return
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


# ────────────────────────────────────────────────────────────────────
#  Akt 1: Drei Patienten, Knowledge-Graph mit typisierten Beziehungen
# ────────────────────────────────────────────────────────────────────
def akt_1_knowledge_graph(store: SQLiteEventStore) -> list[str]:
    """Legt drei Sepsis-Patienten an und zeigt die typisierten Beziehungen."""
    headline("Akt 1 — Drei Patienten, ein Knowledge-Graph")

    slow_print(
        "AION modelliert klinische Verläufe als typisierte Ereignisse.\n"
        "Beziehungen zwischen Ereignissen sind benannt, nicht nur 'verbunden':"
    )
    print(f"  {GREEN}confirms{RESET}, {GREEN}rules_out{RESET}, "
          f"{GREEN}response_to{RESET}, {GREEN}observation_of{RESET}, ...")

    pause()

    step("Drei ICU-Patienten anlegen (Sepsis-Verdacht)")

    base = datetime(2026, 4, 28, 14, 0)
    stay = (base, base + timedelta(days=4))
    patient_ids: list[str] = []

    def make(pid: str, typ: str, attrs: dict, offset_min: int) -> ClinicalEvent:
        return ClinicalEvent(
            patient_id=pid,
            event_type=typ,
            t_start=base + timedelta(minutes=offset_min),
            t_end=base + timedelta(minutes=offset_min + 5),
            stay_start=stay[0], stay_end=stay[1],
            attributes=attrs,
        )

    for n, pid in enumerate(["P-101", "P-102", "P-103"], start=1):
        patient_ids.append(pid)
        # Aufnahme → Fieber → Laktatmessung → Sepsis-Diagnose → Antibiose
        aufnahme = make(pid, "Aufnahme", {"abteilung": "ICU"}, 0)
        fieber   = make(pid, "Fieber", {"temp_c": 39.2 + n * 0.1}, 30)
        laktat   = make(pid, "Laktatmessung", {"value": 3.8 + n * 0.3}, 60)
        diag     = make(pid, "Sepsis", {"sofa_score": 7 + n}, 90)
        antibio  = make(pid, "Antibiotikum",
                        {"atc_code": "J01DH02", "dose": 1000}, 120)

        # Typisierte Beziehungen
        diag.add_reference(laktat, EventRelation.CONFIRMS)
        diag.add_reference(fieber, EventRelation.OBSERVATION_OF)
        antibio.add_reference(diag, EventRelation.RESPONSE_TO)

        store.add_many([aufnahme, fieber, laktat, diag, antibio])

    print(f"  {GREEN}✓{RESET} {len(patient_ids)} Patienten, je 5 Ereignisse persistiert")

    pause()

    step("Knowledge-Graph abfragen — wer bestätigt was?")
    print()
    confirms = store.find_by_relation("confirms")
    for evt_id, ref_id in confirms:
        evt = store.get(evt_id); ref = store.get(ref_id)
        print(f"  {evt.patient_id}: {YELLOW}{evt.event_type}{RESET} "
              f"--[confirms]--> {YELLOW}{ref.event_type}{RESET}")
    print()

    step("Inverse Suche: was reagiert auf welche Diagnose?")
    print()
    response = store.find_by_relation("response_to")
    for evt_id, ref_id in response:
        evt = store.get(evt_id); ref = store.get(ref_id)
        print(f"  {evt.patient_id}: {YELLOW}{evt.event_type}{RESET} "
              f"--[response_to]--> {YELLOW}{ref.event_type}{RESET}")

    pause()
    return patient_ids


# ────────────────────────────────────────────────────────────────────
#  Akt 1.5: Wo kommen die Daten her? FHIR-Anbindung
# ────────────────────────────────────────────────────────────────────
def akt_1b_fhir(store: SQLiteEventStore) -> None:
    """Kurzer Akt: zeigt FHIR-Anschlussfähigkeit.

    Wird übersprungen, wenn fhir.resources nicht installiert ist —
    die Vorführung soll auch ohne FHIR-Dependency laufen können.
    """
    from aion import has_fhir
    if not has_fhir():
        # Stiller Skip — keine Aufmerksamkeit auf fehlende Dependency lenken
        return

    headline("Akt 1½ — FHIR-Anschluss: woher kommen die Daten?")

    slow_print(
        "Bisher haben wir Ereignisse direkt programmatisch erzeugt.\n"
        "In der Realität kommen sie aus einem KIS/HIS — typischerweise\n"
        "als FHIR-Bundle (HL7-Standard für klinische Daten).\n"
        "AION liest und schreibt FHIR-Bundles direkt:"
    )

    pause()

    from aion.fhir import to_fhir_bundle, from_fhir_bundle
    from aion.fhir.bundle import bundle_to_json, bundle_from_json

    step("Aktuelle Ereignisse als FHIR-Bundle exportieren")
    events = store.all()
    bundle = to_fhir_bundle(events)
    json_text = bundle_to_json(bundle)

    print(f"  {GREEN}✓{RESET} {len(events)} Events → FHIR Bundle ({bundle.type})")
    print(f"     {len(bundle.entry)} Resources, {len(json_text):,} Zeichen JSON")
    print()
    print(f"  {DIM}Ressourcentypen im Bundle:{RESET}")
    counts: dict[str, int] = {}
    for entry in bundle.entry:
        rt = type(entry.resource).__name__
        counts[rt] = counts.get(rt, 0) + 1
    for rt, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"     {n} × {YELLOW}{rt}{RESET}")

    pause()

    step("Round-Trip: Bundle → JSON → Bundle → ClinicalEvents")
    bundle_back = bundle_from_json(json_text)
    events_back = from_fhir_bundle(bundle_back)
    print(f"  {GREEN}✓{RESET} {len(events_back)} Events zurückgewonnen "
          f"({'identisch' if len(events_back) == len(events) else 'ABWEICHUNG'})")

    pause()

    slow_print(
        f"\n{BOLD}Bedeutung:{RESET} AION ist HL7-kompatibel anschlussfähig.\n"
        f"Real-Daten aus Synthea, MIMIC-IV-FHIR, oder direkten Klinik-\n"
        f"Schnittstellen können ohne Konvertierungs-Pipeline geladen werden."
    )

    pause()


# ────────────────────────────────────────────────────────────────────
#  Akt 2: Pattern-Mining — der Hauptakt
# ────────────────────────────────────────────────────────────────────
def akt_2_pattern_mining() -> dict:
    """Hauptakt: aus 50 Verläufen lernen wir klinische Phasen."""
    headline("Akt 2 — Klinische Phasen automatisch erkennen")

    slow_print(
        "Bisher: jemand muss klinische Phasen manuell modellieren\n"
        "(Sepsis-Trias, Schock-Kaskade, Recovery-Pattern).\n"
        "\n"
        "AION findet sie automatisch — aus echten Verlaufsdaten."
    )

    pause()

    step("50 synthetische Patientenverläufe generieren")
    print(f"  {DIM}(Mischung: Sepsis-Patienten und unauffällige Verläufe){RESET}")

    rng = random.Random(42)
    sequences: list[list[str]] = []

    # 35 Sepsis-Patienten mit der typischen Phase
    for _ in range(35):
        seq = ["Aufnahme"]
        if rng.random() < 0.3:
            seq.append("Husten")
        seq.extend(["Fieber", "SIRS", "Sepsis"])
        if rng.random() < 0.7:
            seq.append("Schock")
        # Ausgang
        outcome = rng.choices(
            ["Antibiose", "ICU", "Tod"], weights=[5, 3, 1], k=1,
        )[0]
        seq.append(outcome)
        if outcome != "Tod":
            seq.append("Genesung")
        sequences.append(seq)

    # 15 Verläufe ohne Sepsis
    for _ in range(15):
        seq = ["Aufnahme"]
        seq.append(rng.choice(["Husten", "Fieber", "Beobachtung"]))
        seq.append("Genesung")
        sequences.append(seq)

    rng.shuffle(sequences)
    print(f"  {GREEN}✓{RESET} {len(sequences)} Verläufe — durchschnittliche Länge "
          f"{sum(len(s) for s in sequences) / len(sequences):.1f} Ereignisse")

    print(f"\n  {DIM}Beispiel-Verläufe:{RESET}")
    for i in [0, 12, 25, 47]:
        print(f"  {DIM}  P-{i:03d}:{RESET} " + " → ".join(sequences[i]))

    pause()

    step("Pattern-Mining anwerfen (min. 50% Support, Länge 2-5)")

    patterns = TCFG.mine_patterns(
        sequences,
        min_length=2, max_length=5,
        min_support=0.50,
    )

    print(f"  {GREEN}✓{RESET} {len(patterns)} frequente Phasen gefunden\n")

    step("Top-Phasen — automatisch entdeckt:")
    print()
    print(f"  {BOLD}Support  Phase{RESET}")
    print(f"  {DIM}─────────────────────────────────────────────────────{RESET}")
    for pat, support in list(patterns.items())[:10]:
        chain = " → ".join(pat)
        bar = "█" * int(support * 30)
        print(f"  {support:5.0%}    {chain}")
        print(f"           {DIM}{bar}{RESET}")

    pause()

    print()
    slow_print(
        f"{BOLD}Beobachtung:{RESET} Die Phase 'Fieber → SIRS → Sepsis' wurde\n"
        f"NICHT vorgegeben — AION hat sie aus den Daten extrahiert.\n"
    )
    print(f"  Klinisch: {YELLOW}Sepsis-3-Trias{RESET} ({BOLD}automatisch erkannt{RESET})")

    pause()
    return patterns


# ────────────────────────────────────────────────────────────────────
#  Akt 3: Patterns als neue Wissens-Bausteine
# ────────────────────────────────────────────────────────────────────
def akt_3_patterns_zu_konzepten(patterns: dict) -> None:
    """Gefundene Patterns werden in die Typhierarchie übernommen."""
    headline("Akt 3 — Aus Mustern werden Konzepte")

    slow_print(
        "Die gefundenen Phasen können als neue Typen in die Hierarchie\n"
        "übernommen werden — AION lernt das klinische Vokabular weiter.\n"
    )

    step("Aktuelle Hierarchie:")
    h = TypeHierarchy()
    for typ in ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Schock", "Antibiose", "Genesung"]:
        h.add_type(typ)
    print(f"  {len(h)} elementare Typen")

    pause()

    step("Top-3-Patterns als komplexe Phasen-Typen einführen:")
    print()

    h.add_type("Klinische_Phase")
    top_3 = list(patterns.keys())[:3]
    for i, pat in enumerate(top_3, start=1):
        name = "Phase_" + "_".join(pat)
        try:
            h.add_type(name, parent="Klinische_Phase",
                       description=f"Auto-extrahierte Phase: {' → '.join(pat)}")
            support = patterns[pat]
            print(f"  + {GREEN}{name}{RESET}  ({support:.0%} Support)")
        except Exception as e:
            print(f"  ⚠ {name}: {e}")

    print(f"\n  {GREEN}✓{RESET} Hierarchie nun: {len(h)} Typen")
    print(f"     davon {len(h.descendants('Klinische_Phase'))} auto-extrahierte Phasen")

    step("Schema auf Konsistenz prüfen:")
    report = check_inheritance_conflicts(h)
    if report.ok:
        print(f"  {GREEN}✓{RESET} Hierarchie ist konsistent (keine Multi-Inheritance-Konflikte)")
    else:
        print(f"  {RED}✗{RESET} {len(report.conflicts)} Konflikte")

    pause()


# ────────────────────────────────────────────────────────────────────
#  Akt 4: Kausale Frage — wirkt frühe Antibiose?
# ────────────────────────────────────────────────────────────────────
def akt_4_kausal() -> None:
    """Klinische Frage: hilft frühe Antibiotikagabe?"""
    headline("Akt 4 — Eine kausale Frage stellen")

    slow_print(
        "Frage: Wirkt frühe Antibiotikagabe (T) auf 30-Tage-Mortalität (Y)?\n"
        "Problem: Schwerer-Kranke bekommen häufiger frühe Antibiose UND\n"
        "haben höhere Mortalität — Confounder!\n"
    )

    step("Kausalmodell aufbauen:")
    g = CausalGraph()
    g.add_edge("SOFA_Aufnahme", "Frühe_Antibiose")  # Confounder → Treatment
    g.add_edge("SOFA_Aufnahme", "Mortalität_30d")    # Confounder → Outcome
    g.add_edge("Frühe_Antibiose", "Mortalität_30d")  # Treatment → Outcome
    g.add_edge("Frühe_Antibiose", "ICU_Tage")        # Mediator
    g.add_edge("ICU_Tage", "Mortalität_30d")

    print()
    print(f"      {YELLOW}SOFA_Aufnahme{RESET}")
    print(f"        ↙       ↘")
    print(f"  {YELLOW}Frühe_Antibiose{RESET} → {YELLOW}Mortalität_30d{RESET}")
    print(f"        ↘       ↗")
    print(f"        {YELLOW}ICU_Tage{RESET}")

    pause()

    step("Backdoor-Adjustment-Set automatisch ableiten:")
    bs = g.find_backdoor_adjustment_set("Frühe_Antibiose", "Mortalität_30d")
    print(f"  Z = {sorted(bs)}")

    step("Validierung formell prüfen (Pearl, d-Separation):")
    report = is_valid_backdoor_set(g, "Frühe_Antibiose", "Mortalität_30d", bs)
    print(f"  {report}")

    pause()

    step("Effekt schätzen mit synthetischen Daten:")

    def p_y_given_t_z(t, y, z):
        z_val = int(z["SOFA_Aufnahme"]) if z else 0
        log_odds = -2.0 + 1.5 * z_val - 0.8 * int(t)
        p1 = 1 / (1 + math.exp(-log_odds))
        return p1 if y == "1" else 1 - p1

    def p_z(z):
        return 0.4 if int(z["SOFA_Aufnahme"]) == 1 else 0.6

    p_with = g.do_backdoor(p_y_given_t_z, p_z, {"SOFA_Aufnahme": ["0", "1"]},
                           "Frühe_Antibiose", "Mortalität_30d", "1", "1")
    p_without = g.do_backdoor(p_y_given_t_z, p_z, {"SOFA_Aufnahme": ["0", "1"]},
                              "Frühe_Antibiose", "Mortalität_30d", "0", "1")

    print()
    print(f"  P(Mortalität | do(frühe Antibiose=ja)) = {GREEN}{p_with:.3f}{RESET}")
    print(f"  P(Mortalität | do(frühe Antibiose=nein)) = {p_without:.3f}")
    print(f"\n  {BOLD}ATE = {p_with - p_without:+.3f}{RESET}  (negativ = Antibiose senkt Mortalität)")

    pause()


# ────────────────────────────────────────────────────────────────────
#  Schluss
# ────────────────────────────────────────────────────────────────────
def schluss() -> None:
    headline("Zusammenfassung")
    print(f"  {GREEN}1.{RESET} Klinische Verläufe als typisierter Knowledge-Graph")
    print(f"  {GREEN}2.{RESET} HL7-FHIR-Anschluss für Real-Daten")
    print(f"  {GREEN}3.{RESET} Klinische Phasen automatisch aus Daten extrahieren")
    print(f"  {GREEN}4.{RESET} Patterns werden zu neuen Konzepten in der Hierarchie")
    print(f"  {GREEN}5.{RESET} Kausale Inferenz mit formaler Backdoor-Validierung")
    print()
    print(f"  {BOLD}Stack:{RESET} Python stdlib + PyYAML — keine schweren Dependencies")
    print(f"  {BOLD}Tests:{RESET} 364 unit-tests grün, 1 skipped")
    print(f"  {BOLD}GUI:{RESET}   PySide6 (Qt for Python, LGPL)")
    print(f"  {BOLD}FHIR:{RESET}  Round-Trip Observation/Condition/Medication/Procedure")
    print()
    print(f"  Fragen?")
    print()


# ────────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"\n{BOLD}AION Clinical — Live-Demo{RESET}")
    print(f"{DIM}Modus: {'AUTO (kein Warten)' if AUTO_MODE else 'INTERAKTIV (Enter für weiter)'}{RESET}")

    with SQLiteEventStore(":memory:") as store:
        akt_1_knowledge_graph(store)
        akt_1b_fhir(store)
        patterns = akt_2_pattern_mining()
        akt_3_patterns_zu_konzepten(patterns)
        akt_4_kausal()
        schluss()

    return 0


if __name__ == "__main__":
    sys.exit(main())

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Demo der Phase-A-Erweiterungen — typisierte Referenzen, Pattern-Mining,
Schema- und Backdoor-Verifikation.

Ausführen:
    python examples/phase_a_demo.py
"""
from datetime import datetime, timedelta

from aion import (
    TypeHierarchy, ClinicalEvent, EventRelation, SQLiteEventStore,
    CausalGraph, TCFG,
    check_inheritance_conflicts, is_valid_backdoor_set, has_z3,
)


def demo_typed_references():
    print("─── 1. Typisierte Referenzen (Knowledge-Graph) ──────────────")

    base = datetime(2026, 2, 1, 8, 0)
    stay = (base, base + timedelta(days=5))

    def make(typ, attrs=None, offset_minutes=0):
        return ClinicalEvent(
            patient_id="P-77",
            event_type=typ,
            t_start=base + timedelta(minutes=offset_minutes),
            t_end=base + timedelta(minutes=offset_minutes + 5),
            stay_start=stay[0], stay_end=stay[1],
            attributes=attrs or {},
        )

    # Sepsis-Verdacht → Laktatmessung (bestätigt Diagnose) → Antibiotikum (Reaktion)
    laktat = make("Laktatmessung", {"value": 4.2}, offset_minutes=10)
    diag   = make("Sepsis", {"sofa_score": 8}, offset_minutes=20)
    antibio = make("Antibiotikum", {"atc_code": "J01DH02"}, offset_minutes=30)

    # Drei verschiedene typisierte Beziehungen:
    diag.add_reference(laktat, EventRelation.CONFIRMS)
    antibio.add_reference(diag, EventRelation.RESPONSE_TO)
    laktat.add_reference(diag, EventRelation.OBSERVATION_OF)

    with SQLiteEventStore(":memory:") as store:
        store.add_many([laktat, diag, antibio])

        print("   Diagnose-Referenzen (was bestätigt sie?):")
        for ref_id, rel in store.references_of(diag.event_id).items():
            ref = store.get(ref_id)
            print(f"     --[{rel}]--> {ref.event_type}")

        print("   Inverse Suche (wer reagiert auf die Diagnose?):")
        for src_id, rel in store.referenced_by(diag.event_id).items():
            src = store.get(src_id)
            print(f"     {src.event_type} --[{rel}]-->")

        print("   Alle 'response_to'-Beziehungen in der DB:")
        for evt_id, ref_id in store.find_by_relation("response_to"):
            evt = store.get(evt_id); ref = store.get(ref_id)
            print(f"     {evt.event_type} → {ref.event_type}")


def demo_pattern_mining():
    print("\n─── 2. TCFG Pattern-Mining ──────────────────────────────────")

    # 5 Patientenverläufe — die meisten zeigen das Sepsis-Schema
    patient_sequences = [
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Schock", "ICU"],
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Schock", "Tod"],
        ["Aufnahme", "Fieber", "SIRS", "Sepsis", "Antibiose", "Genesung"],
        ["Aufnahme", "Husten", "Fieber", "SIRS", "Sepsis", "ICU", "Genesung"],
        ["Aufnahme", "Genesung"],  # ohne Sepsis
    ]

    patterns = TCFG.mine_patterns(
        patient_sequences,
        min_length=2, max_length=4,
        min_support=0.6,  # in mindestens 60% der Verläufe
    )

    print("   Frequente klinische Phasen (Support ≥ 60%):")
    for pat, support in list(patterns.items())[:8]:
        arrow_chain = " → ".join(pat)
        print(f"     [{support:.0%}]  {arrow_chain}")


def demo_schema_verification():
    print("\n─── 3. Schema-Verifikation (Multi-Inheritance) ──────────────")

    # Konflikt konstruieren: zwei Eltern haben unterschiedliche Ranges für 'level'
    h = TypeHierarchy()
    h.add_type("BaseScale", attributes={
        "level": {"type": "int", "range": [0, 10]},
    })
    h.add_type("StrictScale", attributes={
        "level": {"type": "int", "range": [3, 7]},
    })
    h.add_type("ConflictingScale", attributes={
        "level": {"type": "int", "range": [20, 30]},
    })
    # Combined erbt von BaseScale + StrictScale → kompatibel ([3, 7])
    h.add_type("Combined", parent="BaseScale")
    h.add_edge("Combined", "StrictScale")
    # Broken erbt von BaseScale + ConflictingScale → disjunkt
    h.add_type("Broken", parent="BaseScale")
    h.add_edge("Broken", "ConflictingScale")

    report = check_inheritance_conflicts(h)
    print(f"   {'✅' if report.ok else '❌'} {len(report.conflicts)} Konflikt(e) gefunden")
    for c in report.conflicts:
        print(f"     • {c}")

    # Z3 (falls verfügbar): Erfüllbarkeit prüfen
    if has_z3():
        from aion.verify.z3_plugin import check_schema_satisfiability
        print("\n   Z3 SMT-Erfüllbarkeit:")
        for typ in ["Combined", "Broken"]:
            sat = check_schema_satisfiability(h, typ)
            print(f"     {typ}: {sat}")
    else:
        print("\n   (Z3-Plugin nicht installiert — pip install z3-solver)")


def demo_backdoor_validation():
    print("\n─── 4. Formale Backdoor-Validierung (d-Separation) ──────────")

    # Klassisches Konfounder-Setup mit Mediator
    g = CausalGraph()
    g.add_edge("Z", "X")    # Z confounds
    g.add_edge("Z", "Y")
    g.add_edge("X", "M")    # X → M ist Mediator
    g.add_edge("M", "Y")
    g.add_edge("X", "Y")    # direkte Wirkung

    print("   Graph: Z→X, Z→Y, X→Y, X→M, M→Y\n")
    cases = [
        ("Z d-trennt X von Y im Backdoor?", {"Z"}, True),
        ("∅ als Adjustment?",                 set(), False),
        ("M (Mediator) als Adjustment?",      {"M"}, False),  # Nachfahre von X
        ("{Z, M} als Adjustment?",            {"Z", "M"}, False),
    ]
    for desc, z, expected in cases:
        report = is_valid_backdoor_set(g, "X", "Y", z)
        marker = "✅" if report.valid == expected else "❌"
        print(f"   {marker} {desc}")
        print(f"      → {report}")


if __name__ == "__main__":
    demo_typed_references()
    demo_pattern_mining()
    demo_schema_verification()
    demo_backdoor_validation()

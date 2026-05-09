# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Basic Usage — Typ-Hierarchie via Builder, Decorator und YAML."""
from dataclasses import dataclass
from datetime import datetime

from aion import (
    TypeHierarchy, TypeBuilder, aion_type, AION_REGISTRY,
    ClinicalEvent,
)


def demo_programmatic():
    print("─── 1. Programmatic API ─────────────────────────────────────")
    h = TypeHierarchy()
    h.add_type("Diagnose", fhir_resource="Condition")
    h.add_type("Herzinfarkt", parent="Diagnose",
               attributes={"troponin": {"type": "float", "unit": "ng/ml"}})
    print(f"   Hierarchie: {h}")
    print(f"   Herzinfarkt ≺* Diagnose: {h.is_subtype('Herzinfarkt', 'Diagnose')}")


def demo_builder():
    print("\n─── 2. Builder-Pattern ──────────────────────────────────────")
    h = TypeHierarchy()
    h.add_type("Diagnose", fhir_resource="Condition")
    (TypeBuilder(h, "Sepsis")
        .under("Diagnose")
        .fhir("Condition")
        .attr("sofa_score", type="int", range=[0, 24])
        .attr("lactate",    type="float", unit="mmol/l")
        .describe("Sepsis-3-Definition")
        .build())
    print(f"   Sepsis-Attribute: {list(h.get('Sepsis').attributes)}")


def demo_decorator():
    print("\n─── 3. Decorator-Pattern ────────────────────────────────────")

    @aion_type(name="Blutdruckmessung", parent="Beobachtung", fhir="Observation")
    @dataclass
    class Blutdruck:
        systolic: int
        diastolic: int

    h = TypeHierarchy()
    h.add_type("Beobachtung")
    AION_REGISTRY.materialize(h)
    print(f"   Registriert: {h.get('Blutdruckmessung').attributes}")
    AION_REGISTRY.clear()  # Cleanup für Repeated Runs


def demo_event_validation():
    print("\n─── 4. Ereignis-Erzeugung ───────────────────────────────────")
    now = datetime(2026, 1, 1, 9, 0)
    e = ClinicalEvent(
        patient_id="P001",
        event_type="Herzinfarkt",
        t_start=now,
        t_end=now,
        stay_start=datetime(2026, 1, 1, 8, 0),
        stay_end=datetime(2026, 1, 5, 12, 0),
        attributes={"troponin": 5.4, "stemi": True},
    )
    print(f"   Ereignis: {e.event_type} für {e.patient_id}")
    print(f"   Zeitlich eingebettet: {e.is_temporally_embedded()}")


if __name__ == "__main__":
    demo_programmatic()
    demo_builder()
    demo_decorator()
    demo_event_validation()

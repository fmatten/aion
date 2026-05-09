# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""FHIR-Demo: Round-Trip zwischen ClinicalEvents und FHIR-Bundle.

Zeigt:
    1. Patient-Timeline als ClinicalEvents anlegen
    2. Konvertieren in FHIR-Bundle (mit Type-Hierarchie als Resource-Typ-Quelle)
    3. JSON-Export — kann an HAPI-FHIR-Server geschickt werden
    4. Reimport: JSON → Bundle → ClinicalEvents
    5. Verifikation: alles erhalten
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aion import (
    ClinicalEvent, EventRelation, TypeHierarchy,
)
from aion.fhir import (
    has_fhir, to_fhir_bundle, from_fhir_bundle,
    bundle_to_json, bundle_from_json,
)


def main():
    if not has_fhir():
        print("fhir.resources nicht installiert.")
        print("Installation: pip install -e \".[fhir]\"")
        return

    # ── 1. Type-Hierarchie mit FHIR-Resource-Mapping ────────────────
    h = TypeHierarchy()
    h.add_type("Diagnose",     fhir_resource="Condition")
    h.add_type("Beobachtung",  fhir_resource="Observation")
    h.add_type("Medikation",   fhir_resource="MedicationAdministration")
    h.add_type("Prozedur",     fhir_resource="Procedure")
    h.add_type("Sepsis",       parent="Diagnose")
    h.add_type("Laktatmessung", parent="Beobachtung")
    h.add_type("Antibiotikum", parent="Medikation")
    h.add_type("ZVK_Anlage",   parent="Prozedur")

    # ── 2. Patient-Timeline ──────────────────────────────────────
    stay = (
        datetime(2026, 4, 10,  8,  0, tzinfo=timezone.utc),
        datetime(2026, 4, 17, 12,  0, tzinfo=timezone.utc),
    )

    def at(hours_after_admission, minutes=5):
        s = stay[0] + timedelta(hours=hours_after_admission)
        return s, s + timedelta(minutes=minutes)

    laktat_t = at(2)
    laktat = ClinicalEvent(
        patient_id="P-77", event_type="Laktatmessung",
        t_start=laktat_t[0], t_end=laktat_t[1],
        stay_start=stay[0], stay_end=stay[1],
        attributes={"value": 4.8, "unit": "mmol/L"},
    )

    sepsis_t = at(2.5, minutes=1)
    sepsis = ClinicalEvent(
        patient_id="P-77", event_type="Sepsis",
        t_start=sepsis_t[0], t_end=sepsis_t[1],
        stay_start=stay[0], stay_end=stay[1],
        attributes={"severity": "severe", "sofa_score": 9},
        references={laktat.event_id: EventRelation.CONFIRMS},
    )

    zvk_t = at(3, minutes=20)
    zvk = ClinicalEvent(
        patient_id="P-77", event_type="ZVK_Anlage",
        t_start=zvk_t[0], t_end=zvk_t[1],
        stay_start=stay[0], stay_end=stay[1],
        attributes={"site": "v_jugularis"},
        references={sepsis.event_id: EventRelation.RESPONSE_TO},
    )

    antibio_t = at(3.5, minutes=60)
    antibio = ClinicalEvent(
        patient_id="P-77", event_type="Antibiotikum",
        t_start=antibio_t[0], t_end=antibio_t[1],
        stay_start=stay[0], stay_end=stay[1],
        attributes={"atc_code": "J01DH02", "dose": 1000.0,
                    "unit": "mg", "route": "iv"},
        references={sepsis.event_id: EventRelation.RESPONSE_TO},
    )

    events_in = [laktat, sepsis, zvk, antibio]

    print(f"Eingangsdaten: {len(events_in)} Events für Patient P-77")
    for e in events_in:
        print(f"  {e.t_start.strftime('%Y-%m-%d %H:%M')}  {e.event_type:18s} "
              f"refs: {len(e.references)}")

    # ── 3. → FHIR-Bundle ──────────────────────────────────────────
    bundle = to_fhir_bundle(events_in, type_hierarchy=h)
    print(f"\nFHIR-Bundle erstellt: {bundle.type}, {len(bundle.entry)} Entries")
    for entry in bundle.entry:
        print(f"  {type(entry.resource).__name__:25s} id={entry.resource.id}")

    # ── 4. → JSON-Datei ───────────────────────────────────────────
    out_dir = Path("/tmp/aion-fhir-demo")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "patient_p77_bundle.json"
    text = bundle_to_json(bundle, indent=2)
    out_path.write_text(text, encoding="utf-8")
    print(f"\nGeschrieben: {out_path} ({len(text)} bytes)")

    # ── 5. ← JSON-Reimport und Round-Trip-Verifikation ────────────
    bundle_back = bundle_from_json(out_path.read_text(encoding="utf-8"))
    events_back = from_fhir_bundle(bundle_back)
    print(f"\nNach Reimport: {len(events_back)} Events")

    # Verifizieren
    in_by_id = {e.event_id: e for e in events_in}
    print("\nRound-Trip-Verifikation:")
    all_ok = True
    for e_back in events_back:
        original = in_by_id[e_back.event_id]
        refs_match = original.references == e_back.references
        attrs_match = original.attributes == e_back.attributes
        marker = "✓" if (refs_match and attrs_match) else "✗"
        print(f"  {marker} {original.event_type:18s} "
              f"attrs={attrs_match} refs={refs_match}")
        if not (refs_match and attrs_match):
            all_ok = False
            print(f"     attrs IN:  {original.attributes}")
            print(f"     attrs OUT: {e_back.attributes}")

    print(f"\n{'✅ Round-Trip vollständig' if all_ok else '❌ Inkonsistenzen!'}")
    print(f"Datei für eigene Inspektion: {out_path}")


if __name__ == "__main__":
    main()

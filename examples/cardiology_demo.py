# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Kardiologie-Demo — STEMI-Patient mit voller Behandlungskette.

Zeigt:
    1. Basis- und Kardiologie-Schema kombiniert laden
    2. Realistischen STEMI-Verlauf modellieren
    3. Typisierte Beziehungen (Troponin confirms STEMI, PCI response_to STEMI)
    4. Door-to-Balloon-Zeit berechnen — wichtiger Qualitätsindikator

Voraussetzung: clinical_base.yaml und cardiology_extension.yaml in schemas/
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from aion import (
    ClinicalEvent, EventRelation, SQLiteEventStore,
    TypeHierarchy, check_inheritance_conflicts,
)


def load_combined_schema() -> TypeHierarchy:
    """Kombiniert Basis- und Kardiologie-Schema."""
    schemas_dir = Path(__file__).resolve().parent.parent / "schemas"
    h = TypeHierarchy()
    for fname in ("clinical_base.yaml", "cardiology_extension.yaml"):
        with open(schemas_dir / fname, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # Topologisches Einsortieren — Parents zuerst
        entries = data.get("types", [])
        by_name = {e["name"]: e for e in entries}
        visited: set[str] = set()
        ordered: list[dict] = []

        def visit(name: str) -> None:
            if name in visited or name not in by_name:
                return
            visited.add(name)
            p = by_name[name].get("parent")
            if p and p in by_name:
                visit(p)
            ordered.append(by_name[name])

        for e in entries:
            visit(e["name"])
        for e in ordered:
            if e["name"] in h:
                continue
            h.add_type(
                name=e["name"],
                parent=e.get("parent"),
                fhir_resource=e.get("fhir"),
                attributes=e.get("attributes", {}) or {},
                description=e.get("description", "") or "",
            )
    return h


def build_stemi_patient() -> list[ClinicalEvent]:
    """Realistischer STEMI-Verlauf einer 67-jährigen Patientin.

    Zeitachse:
        T+0 min   Aufnahme NA, Symptombeginn vor 90 Min
        T+12 min  EKG zeigt ST-Hebung anterior
        T+25 min  Troponin hochgradig erhöht
        T+38 min  STEMI-Diagnose
        T+45 min  ASS + Ticagrelor Loading
        T+52 min  Heparin
        T+68 min  Koronarangiographie
        T+82 min  PCI mit DES auf RIVA  ← Door-to-Balloon: 82 Min ✓
        T+95 min  Beta-Blocker
        T+120 min Echo, EF 38% (HFrEF)
    """
    aufnahme = datetime(2026, 5, 8, 9, 30)  # 09:30 Uhr
    stay_start = aufnahme
    stay_end = aufnahme + timedelta(days=5)

    def evt(typ: str, attrs: dict, t_offset_min: int, dur_min: int = 1) -> ClinicalEvent:
        t = aufnahme + timedelta(minutes=t_offset_min)
        return ClinicalEvent(
            patient_id="P-K044",
            event_type=typ,
            t_start=t,
            t_end=t + timedelta(minutes=dur_min),
            stay_start=stay_start,
            stay_end=stay_end,
            attributes=attrs,
        )

    ekg = evt("EKG_Befund",
              {"rhythmus": "sinus", "hr_bpm": 92, "qrs_ms": 88, "qt_ms": 410},
              t_offset_min=12, dur_min=3)

    troponin = evt("Troponin",
                   {"value_ng_l": 4280.0, "assay": "hochsensitiv"},
                   t_offset_min=25)

    diagnose = evt("STEMI",
                   {"lokalisation": "anterior",
                    "st_hebung_mm": 3.2,
                    "onset_to_admission_min": 90,
                    "door_to_balloon_min": 82,
                    "grace_score": 142},
                   t_offset_min=38)
    diagnose.add_reference(ekg, EventRelation.CONFIRMS)
    diagnose.add_reference(troponin, EventRelation.CONFIRMS)

    ass = evt("Thrombozytenaggregationshemmer",
              {"substanz": "ass", "ladedosis": True},
              t_offset_min=45)
    ass.add_reference(diagnose, EventRelation.RESPONSE_TO)

    ticagrelor = evt("Thrombozytenaggregationshemmer",
                     {"substanz": "ticagrelor", "ladedosis": True},
                     t_offset_min=45)
    ticagrelor.add_reference(diagnose, EventRelation.RESPONSE_TO)

    heparin = evt("Antikoagulation",
                  {"substanz": "heparin", "indikation": "periinterventionell"},
                  t_offset_min=52)
    heparin.add_reference(diagnose, EventRelation.RESPONSE_TO)

    angio = evt("Koronarangiographie",
                {"zugang": "radial", "kontrastmittel_ml": 95},
                t_offset_min=68, dur_min=14)
    angio.add_reference(diagnose, EventRelation.RESPONSE_TO)

    pci = evt("PCI",
              {"gefaess": "LAD",
               "stent_typ": "DES",
               "stent_anzahl": 1,
               "tici_flow_post": 3},
              t_offset_min=82, dur_min=18)
    pci.add_reference(diagnose, EventRelation.RESPONSE_TO)

    bb = evt("BetaBlocker",
             {"substanz": "metoprolol", "target_hr_bpm": 65},
             t_offset_min=95)

    echo = evt("Echokardiographie",
               {"modalitaet": "TTE",
                "ef_prozent": 38,
                "lvedd_mm": 58,
                "perikarderguss": False},
               t_offset_min=120, dur_min=20)

    statin = evt("Statin",
                 {"substanz": "atorvastatin", "dosis_mg": 80},
                 t_offset_min=130)

    # Sekundärdiagnose nach Echo
    hfref = evt("Herzinsuffizienz",
                {"nyha_klasse": "II", "ef_prozent": 38, "typ": "HFrEF"},
                t_offset_min=140)
    hfref.add_reference(echo, EventRelation.CONFIRMS)
    hfref.add_reference(diagnose, EventRelation.CAUSED_BY)

    return [ekg, troponin, diagnose, ass, ticagrelor, heparin,
            angio, pci, bb, echo, statin, hfref]


def main() -> int:
    print("─── Kardiologie-Demo ─────────────────────────────────────")

    h = load_combined_schema()
    print(f"\n1. Schema geladen: {len(h)} Typen")
    print(f"   Top-Level: {sorted(h.children_of(h.TOP))}")

    report = check_inheritance_conflicts(h)
    print(f"   Konsistenz: {'✓ konsistent' if report.ok else '✗ ' + str(report)}")

    # Validierung: Hat das Schema STEMI-Subtypen unter AkutesKoronarsyndrom?
    aks_subs = sorted(h.descendants("AkutesKoronarsyndrom"))
    print(f"\n2. Akute Koronarsyndrome im Schema: {aks_subs}")

    events = build_stemi_patient()
    print(f"\n3. STEMI-Patient P-K044: {len(events)} Ereignisse über "
          f"{(events[-1].t_start - events[0].t_start).total_seconds() / 60:.0f} Minuten")

    with SQLiteEventStore(":memory:") as store:
        store.add_many(events)

        print("\n4. Behandlungs-Timeline (Zeit ab Aufnahme):")
        # Aufnahmezeit ist stay_start des ersten Events
        admission_t = events[0].stay_start
        for e in store.find_by_patient("P-K044"):
            offset_min = (e.t_start - admission_t).total_seconds() / 60
            attrs_summary = ", ".join(f"{k}={v}" for k, v in
                                       list(e.attributes.items())[:2])
            print(f"   T+{offset_min:5.0f} min  {e.event_type:32s}  {attrs_summary}")

        # Door-to-Balloon-Zeit aus den Daten extrahieren
        stemi_events = store.find_by_type("STEMI")
        if stemi_events:
            stemi = stemi_events[0]
            d2b = stemi.attributes.get("door_to_balloon_min")
            if d2b is not None:
                quality = "✓ Leitlinien-konform" if d2b <= 90 else "✗ Über Zielwert!"
                print(f"\n5. Qualitätsindikator Door-to-Balloon-Zeit:")
                print(f"   {d2b} Minuten   ({quality}, Ziel ≤ 90 min)")

        # Knowledge-Graph: Was bestätigt die Diagnose?
        print(f"\n6. Knowledge-Graph — Diagnose-Beziehungen:")
        for stemi in stemi_events:
            print(f"   STEMI ←")
            confirms_pairs = store.find_by_relation("confirms", event_id=stemi.event_id)
            for evt_id, ref_id in confirms_pairs:
                ref = store.get(ref_id)
                print(f"      [confirms] {ref.event_type} ({list(ref.attributes.items())[:1]})")
            response_back = store.referenced_by(stemi.event_id)
            for src_id, rel in response_back.items():
                if rel == "response_to":
                    src = store.get(src_id)
                    print(f"      [response_to] {src.event_type}")

    print("\n✓ Kardiologie-Demo abgeschlossen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

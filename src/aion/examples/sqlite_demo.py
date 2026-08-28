# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""SQLite-Demo — Patiententimeline mit ClinicalEvents persistieren und abfragen."""
from datetime import datetime, timedelta
from aion import ClinicalEvent, SQLiteEventStore
from aion.core.relations import EventRelation


def main():
    # In-Memory-DB für die Demo (oder Pfad zu Datei angeben)
    with SQLiteEventStore(":memory:") as store:

        # ── Beispielpatient: Sepsis-Aufnahme ───────────────────────
        stay_start = datetime(2026, 1, 10, 14, 30)
        stay_end   = datetime(2026, 1, 17,  9, 0)

        diag = ClinicalEvent(
            patient_id="P-42",
            event_type="Sepsis",
            t_start=stay_start + timedelta(hours=2),
            t_end=stay_start + timedelta(hours=2, minutes=15),
            stay_start=stay_start, stay_end=stay_end,
            attributes={"sofa_score": 8, "lactate": 4.2, "septic_shock": True},
        )

        laktat = ClinicalEvent(
            patient_id="P-42",
            event_type="Laktatmessung",
            t_start=stay_start + timedelta(hours=1, minutes=45),
            t_end=stay_start + timedelta(hours=1, minutes=46),
            stay_start=stay_start, stay_end=stay_end,
            attributes={"value": 4.2},
        )

        # Diagnose referenziert Laktatmessung als unterstützenden Befund
        diag.add_reference(laktat, EventRelation.OBSERVATION_OF)

        antibio = ClinicalEvent(
            patient_id="P-42",
            event_type="Antibiotikum",
            t_start=stay_start + timedelta(hours=2, minutes=30),
            t_end=stay_start + timedelta(hours=3),
            stay_start=stay_start, stay_end=stay_end,
            attributes={"atc_code": "J01DH02", "dose": 1000, "unit": "mg", "route": "iv"},
            references={diag.event_id: EventRelation.RESPONSE_TO},
        )

        store.add_many([laktat, diag, antibio])

        # ── Abfragen ──────────────────────────────────────────────
        print("Patient P-42 — Timeline")
        print("=" * 70)
        for e in store.find_by_patient("P-42"):
            print(f"  {e.t_start.isoformat(timespec='minutes')}  "
                  f"{e.event_type:18s}  {e.attributes}")

        print("\nZusammenfassung:")
        s = store.patient_summary("P-42")
        print(f"  Ereignisse: {s['event_count']}")
        print(f"  Erstes:     {s['first_event']}")
        print(f"  Letztes:    {s['last_event']}")
        print(f"  Nach Typ:   {s['by_type']}")

        print("\nReferenzen der Diagnose 'Sepsis':")
        for ref_id, relation in store.references_of(diag.event_id).items():
            ref_event = store.get(ref_id)
            print(f"  --[{relation}]--> {ref_event.event_type} ({ref_event.attributes})")

        print("\nWer reagierte auf die Sepsis (inverse Suche):")
        for source_id, relation in store.referenced_by(diag.event_id).items():
            source = store.get(source_id)
            print(f"  {source.event_type} --[{relation}]--> Sepsis")

        print("\nFenster-Abfrage [+1h .. +3h]:")
        for e in store.find_in_window(
            "P-42",
            stay_start + timedelta(hours=1),
            stay_start + timedelta(hours=3),
        ):
            print(f"  {e.event_type} @ {e.t_start.isoformat(timespec='minutes')}")

        print("\nAttribut-Suche (sofa_score=8):")
        for e in store.find_by_attribute("sofa_score", 8):
            print(f"  {e.event_type} bei {e.patient_id}")


if __name__ == "__main__":
    main()

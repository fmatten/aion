# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""HL7-v2-Import Demo.

Liest die mitgelieferten Test-Fixtures und zeigt:
  1. Default-Mapping: ADT-Trigger und LOINC-Codes
  2. Fallback-Verhalten: unbekannte Codes → HL7_<Type>_<Trigger>
  3. Anwender-Code-Mapping als Erweiterung
  4. Verzeichnis-Import

Hinweis: Test-Fixtures sind synthetisch (von Hand erzeugt).
Für echte HL7-Daten siehe Mirth Connect, HAPI HL7v2 oder ein
KIS-Testsystem.
"""
from __future__ import annotations

from pathlib import Path

from aion.hl7v2 import (
    hl7v2_import_file,
    hl7v2_import_directory,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hl7v2"


def main() -> int:
    if not FIXTURES.exists():
        print(f"✗ Fixtures fehlen: {FIXTURES}")
        return 1

    print("─── HL7-v2 Import Demo ───────────────────────────────────────")
    print()

    # ── 1. Einzelne ADT-Aufnahme ─────────────────────────────────
    print("1. ADT^A01 (Aufnahme):")
    events = hl7v2_import_file(FIXTURES / "adt_a01_aufnahme.hl7")
    for e in events:
        print(f"   {e.t_start.strftime('%Y-%m-%d %H:%M')}  "
              f"{e.event_type:25s}  Patient={e.patient_id}  "
              f"Klasse={e.attributes.get('patient_class', '?')}")

    # ── 2. Einzelne ORU-Befund ───────────────────────────────────
    print()
    print("2. ORU^R01 (Hämoglobin-Befund):")
    events = hl7v2_import_file(FIXTURES / "oru_r01_haemoglobin.hl7")
    for e in events:
        print(f"   {e.t_start.strftime('%Y-%m-%d %H:%M')}  "
              f"{e.event_type:25s}  "
              f"Wert={e.attributes.get('value')} {e.attributes.get('unit', '')}  "
              f"LOINC={e.attributes.get('loinc_code')}")

    # ── 3. Multi-Message-Datei ───────────────────────────────────
    print()
    print("3. Multi-Message-Datei (3 Nachrichten in einer Datei):")
    events = hl7v2_import_file(FIXTURES / "multi_messages.hl7")
    for e in events:
        print(f"   {e.t_start.strftime('%H:%M')}  {e.event_type}")

    # ── 4. Anwender-Code-Mapping ─────────────────────────────────
    print()
    print("4. Mit Anwender-Code-Mapping (Custom-Aufnahme-Label):")
    extra = {"A01": "Notaufnahme_Spezial"}
    events = hl7v2_import_file(
        FIXTURES / "adt_a01_aufnahme.hl7",
        code_map=extra,
    )
    for e in events:
        print(f"   {e.event_type}  (statt 'Aufnahme', via code_map)")

    # ── 5. Verzeichnis-Import ────────────────────────────────────
    print()
    print("5. Verzeichnis-Import (alle *.hl7 aus Fixtures):")
    all_events = hl7v2_import_directory(FIXTURES)
    print(f"   {len(all_events)} Events aus mehreren Dateien")
    types = {}
    for e in all_events:
        types[e.event_type] = types.get(e.event_type, 0) + 1
    for t, n in sorted(types.items(), key=lambda kv: -kv[1]):
        print(f"   {n:3d}  {t}")

    print()
    print("─── Demo abgeschlossen ──────────────────────────────────────")
    print()
    print("In der Praxis (mit echtem KIS-Output):")
    print("  aion import /var/hl7-export/ --hl7v2 --db klinik.db --limit 1000")
    print("  aion stats klinik.db")
    print("  aion mine klinik.db --min-support 0.3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

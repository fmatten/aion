# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Synthea-Import Demo.

Liest ein Synthea-realistisches FHIR-Bundle (Test-Fixture) ein und zeigt:
  1. Code-Mapping: was wird automatisch zugeordnet?
  2. Fallback-Verhalten: was bleibt als FHIR_<ResourceType>?
  3. Anwender-Code-Mapping als Erweiterung
  4. Verzeichnis-Import (mit synthetischer Vervielfältigung)

Hinweis: Test-Fixture ist synthetisch, nicht aus Synthea direkt.
Für echte Synthea-Daten siehe github.com/synthetichealth/synthea
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from aion.synthea import (
    synthea_import_bundle,
    synthea_import_directory,
)


FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "synthea" / "Patient_001.json"


def main() -> int:
    if not FIXTURE.exists():
        print(f"✗ Fixture fehlt: {FIXTURE}")
        return 1

    print("─── Synthea-Import Demo ─────────────────────────────────────")
    print()
    print(f"Bundle: {FIXTURE.name}")
    print()

    # ── 1. Default-Mapping ────────────────────────────────────────
    print("1. Import mit eingebautem Default-Mapping:")
    events = synthea_import_bundle(FIXTURE)
    for e in events:
        attrs_short = ", ".join(f"{k}={v}" for k, v in list(e.attributes.items())[:2])
        print(f"   {e.t_start.strftime('%H:%M')}  {e.event_type:30s}  {attrs_short}")

    n_mapped = sum(1 for e in events if not e.event_type.startswith("FHIR_"))
    n_fallback = len(events) - n_mapped
    print(f"\n   {n_mapped} Events semantisch gemappt, "
          f"{n_fallback} als Fallback (FHIR_<Type>)")

    # ── 2. Mit eigenem Code-Mapping ──────────────────────────────
    print()
    print("2. Import mit Anwender-Mapping (Sepsis, ICU):")
    extra = {
        "91302008": "Sepsis",                # SNOMED
        "33195004": "Intensivmedizin",       # SNOMED
        "1656976":  "Piperacillin",          # RxNorm
    }
    events_mapped = synthea_import_bundle(FIXTURE, code_map=extra)
    for e in events_mapped:
        if e.event_type in ("Sepsis", "Intensivmedizin", "Piperacillin"):
            print(f"   ✓ {e.event_type:25s}  Code: {e.attributes.get('fhir_code', '—')}")

    n_mapped_v2 = sum(1 for e in events_mapped if not e.event_type.startswith("FHIR_"))
    print(f"\n   {n_mapped_v2}/{len(events_mapped)} Events gemappt "
          f"(+{n_mapped_v2 - n_mapped} durch Anwender-Mapping)")

    # ── 3. Verzeichnis-Import ────────────────────────────────────
    print()
    print("3. Verzeichnis-Import (5 Bundles synthetisch dupliziert):")
    with tempfile.TemporaryDirectory(prefix="aion-synthea-") as tmpdir:
        # 5 Kopien anlegen
        for i in range(5):
            dst = Path(tmpdir) / f"Patient_{i:03d}.json"
            shutil.copy(FIXTURE, dst)

        all_events = synthea_import_directory(tmpdir)
        print(f"   {len(all_events)} Events aus 5 Bundles ({len(all_events)//5} je Patient)")

    print()
    print("─── Demo abgeschlossen ──────────────────────────────────────")
    print()
    print("In der Praxis (mit echtem Synthea-Output):")
    print("  aion import output/fhir/ --synthea --db klinik.db --limit 100")
    print("  aion stats klinik.db")
    print("  aion mine klinik.db --min-support 0.3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

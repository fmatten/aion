# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Code-Mappings für HL7-v2-Import.

DESIGNENTSCHEIDUNG (1.8.0, Lesart C analog Synthea):

Diese Datei enthält nur ein **minimales, unstrittiges** Default-Mapping
für ca. 25 häufige HL7-Codes auf AION-Typnamen. Der Anwender ist
dafür verantwortlich, dieses Mapping zu erweitern.

Eingebaut sind nur Codes, die zwei Bedingungen erfüllen:

  1. Eindeutige klinische Bedeutung (kein Spielraum für Fehlinterpretation)
  2. Häufig in HL7-v2-Standardströmen

Was hier ABSICHTLICH NICHT eingebaut ist:
  * ICD-10-Diagnosen — brauchen klinische Validierung
  * Lokale OPS- oder hauseigene Codes
  * Medikamenten-Codes (RxNorm, ATC, PZN)

Wer mehr Mappings braucht: eigenes Mapping per `code_map=...` übergeben.

NICHT-VALIDIERT KLINISCH. Vor Produktiv-Einsatz prüfen.
"""
from __future__ import annotations

from typing import Optional


# ────────────────────────────────────────────────────────────────────
#  ADT Event-Typen (MSH-9.2 -- Trigger Events)
#  Standard HL7 v2.x ADT-Events
# ────────────────────────────────────────────────────────────────────
DEFAULT_ADT_MAP: dict[str, str] = {
    "A01": "Aufnahme",                      # Admit/visit notification
    "A02": "Verlegung",                     # Transfer a patient
    "A03": "Entlassung",                    # Discharge/end visit
    "A04": "Ambulanz_Registrierung",        # Register patient (ambulant)
    "A05": "Voraufnahme",                   # Pre-admit
    "A06": "Stationaer_Wechsel",            # Change outpatient → inpatient
    "A07": "Ambulant_Wechsel",              # Change inpatient → outpatient
    "A08": "Patienten_Update",              # Update patient information
    "A11": "Aufnahme_Storno",               # Cancel admit
    "A12": "Verlegung_Storno",              # Cancel transfer
    "A13": "Entlassung_Storno",             # Cancel discharge
}


# ────────────────────────────────────────────────────────────────────
#  LOINC-Codes für ORU-Befunde (OBX-3.1)
#  Identisch mit den Codes aus aion.synthea.codes — bewusst doppelt,
#  damit hl7v2 stand-alone funktioniert. Synchronisation per Konvention.
# ────────────────────────────────────────────────────────────────────
DEFAULT_LOINC_MAP: dict[str, str] = {
    # Vitalzeichen
    "8867-4":   "Herzfrequenz",
    "8480-6":   "Blutdruck_systolisch",
    "8462-4":   "Blutdruck_diastolisch",
    "8310-5":   "Körpertemperatur",
    "29463-7":  "Körpergewicht",
    "8302-2":   "Körpergröße",
    "39156-5":  "BMI",

    # Häufige Labortests
    "2345-7":   "Glucose",
    "2160-0":   "Kreatinin",
    "718-7":    "Hämoglobin",
    "6690-2":   "Leukozyten",
    "789-8":    "Erythrozyten",
    "777-3":    "Thrombozyten",
    "2951-2":   "Natrium",
    "2823-3":   "Kalium",
    "2075-0":   "Chlorid",
    "1742-6":   "ALT",
    "1920-8":   "AST",
}


def lookup_adt(trigger_event: str) -> Optional[str]:
    """Sucht ADT-Trigger-Event (z. B. "A01") im Default-Mapping."""
    return DEFAULT_ADT_MAP.get(trigger_event)


def lookup_loinc(
    code: str,
    *,
    extra_map: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Sucht LOINC-Code im Default- + optionalem Anwender-Mapping."""
    if extra_map and code in extra_map:
        return extra_map[code]
    return DEFAULT_LOINC_MAP.get(code)


def fallback_type_name(message_type: str, trigger: str) -> str:
    """Fallback für unzugeordnete HL7-Nachrichtentypen.

    z. B. ADT^A99 (unbekannter Trigger) → 'HL7_ADT_A99'
    """
    return f"HL7_{message_type}_{trigger}" if trigger else f"HL7_{message_type}"


__all__ = [
    "DEFAULT_ADT_MAP",
    "DEFAULT_LOINC_MAP",
    "lookup_adt",
    "lookup_loinc",
    "fallback_type_name",
]

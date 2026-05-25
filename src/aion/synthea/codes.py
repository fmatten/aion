# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Code-Mappings für Synthea-Import.

DESIGNENTSCHEIDUNG (1.4.0, Lesart C):

Diese Datei enthält nur ein **minimales, unstrittiges** Default-Mapping
für ca. 15 häufige FHIR-Codes auf AION-Typnamen. Der Anwender ist
dafür verantwortlich, dieses Mapping zu erweitern oder zu ersetzen.

Was hier eingebaut ist, sind Codes die zwei Bedingungen erfüllen:
  1. Eindeutige klinische Bedeutung (kein Spielraum für Fehlinterpretation)
  2. Häufig in Synthea-Default-Output

Was hier ABSICHTLICH NICHT eingebaut ist:
  * Spezifische Diagnosen (z. B. einzelne Sepsis-Codes) — die brauchen
    klinische Validierung, die wir hier nicht leisten können
  * Medikamenten-Codes (RxNorm, ATC) — sehr kontextabhängig
  * Lokal gültige Codes, ICD-10-GM-Spezifika

Wer mehr Mappings braucht: eigene `code_map`-YAML-Datei pflegen und
beim Import übergeben (siehe `synthea_import_bundle(code_map=...)`).

NICHT-VALIDIERT KLINISCH. Vor Produktiv-Einsatz prüfen.
"""
from __future__ import annotations

from typing import Optional


# ────────────────────────────────────────────────────────────────────
#  Default-Mapping: SNOMED-CT-Konzepte → AION-Typnamen
# ────────────────────────────────────────────────────────────────────
# Format: SNOMED-Code → AION-Typname
# Quelle: SNOMED-CT International Edition. Codes sind weltweit eindeutig.

DEFAULT_SNOMED_MAP: dict[str, str] = {
    # ── Vitalzeichen / Beobachtungen (ganz unstrittig) ─────────
    "184099003": "Geburtsdatum",          # Date of birth
    "364075005": "Herzfrequenz",          # Heart rate
    "271649006": "Blutdruck",             # Systolic blood pressure
    "8462-4":    "Blutdruck",             # Diastolic (LOINC, oft mitgenutzt)
    "27113001":  "Körpergewicht",         # Body weight
    "50373000":  "Körpergröße",           # Body height
    "386725007": "Körpertemperatur",      # Body temperature

    # ── Encounter-Klassen (ganz unstrittig) ────────────────────
    "185345009": "Aufnahme",              # Encounter for symptom
    "185349003": "Routine_Untersuchung",  # Encounter for check up
    "50849002":  "Notaufnahme",           # Emergency room admission

    # ── Demografie (formal, kein klinisches Urteil) ────────────
    "184516000": "Patientenkontakt",      # Patient referral
}


# ────────────────────────────────────────────────────────────────────
#  Default-Mapping: LOINC-Codes → AION-Typnamen
# ────────────────────────────────────────────────────────────────────
# LOINC ist standardisiert für Laborbefunde — eindeutiger als ICD/SNOMED.

DEFAULT_LOINC_MAP: dict[str, str] = {
    # ── Vitalzeichen ───────────────────────────────────────────
    "8867-4":   "Herzfrequenz",
    "8480-6":   "Blutdruck_systolisch",
    "8462-4":   "Blutdruck_diastolisch",
    "8310-5":   "Körpertemperatur",
    "29463-7":  "Körpergewicht",
    "8302-2":   "Körpergröße",
    "39156-5":  "BMI",

    # ── Häufige Labortests ─────────────────────────────────────
    "2345-7":   "Glucose",
    "2160-0":   "Kreatinin",
    "718-7":    "Hämoglobin",
    "6690-2":   "Leukozyten",
    "789-8":    "Erythrozyten",
    "777-3":    "Thrombozyten",
}


def lookup_code(
    code: str,
    system: Optional[str] = None,
    *,
    extra_map: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Sucht einen FHIR-Code im Default- + optionalem Anwender-Mapping.

    Args:
        code: der Code-Wert (z. B. "8867-4" oder "364075005")
        system: optionale System-URL ("http://loinc.org",
                "http://snomed.info/sct"). Wird als Heuristik genutzt,
                aber nicht erzwungen — auch ohne System wird gesucht.
        extra_map: zusätzliches Mapping vom Anwender, hat Vorrang.

    Returns:
        AION-Typname oder None, wenn kein Mapping gefunden.
    """
    # Anwender-Mapping schlägt Default
    if extra_map and code in extra_map:
        return extra_map[code]

    # System-Hinweis nutzen, falls gegeben
    if system:
        if "loinc" in system.lower() and code in DEFAULT_LOINC_MAP:
            return DEFAULT_LOINC_MAP[code]
        if "snomed" in system.lower() and code in DEFAULT_SNOMED_MAP:
            return DEFAULT_SNOMED_MAP[code]

    # Fallback: in beiden Mappings suchen
    return DEFAULT_LOINC_MAP.get(code) or DEFAULT_SNOMED_MAP.get(code)


def fallback_type_name(resource_type: str) -> str:
    """Fallback-Typname für unzugeordnete Codes.

    z. B. eine Observation ohne bekanntes Mapping wird zu
    `FHIR_Observation` — Daten gehen nicht verloren, sind nur weniger
    semantisch annotiert.
    """
    return f"FHIR_{resource_type}"


__all__ = [
    "DEFAULT_SNOMED_MAP",
    "DEFAULT_LOINC_MAP",
    "lookup_code",
    "fallback_type_name",
]

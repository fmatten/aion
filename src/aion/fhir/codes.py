# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""FHIR-System-URLs und Default-Code-Mappings.

Hier werden Klinik-Codes (LOINC, SNOMED-CT, ICD-10) und die
AION-eigenen System-URLs zentral verwaltet. So lassen sie sich an
einer Stelle anpassen, ohne den Mapper anzufassen.
"""
from __future__ import annotations

from typing import Final


# ── AION-eigene URLs für Round-Trip-fähige Round-Trip-Felder ────────
# Diese URLs MÜSSEN Round-Trip-stabil sein. Ändere sie nicht ohne
# Migrationsstrategie.
AION_SYSTEM_URL: Final[str] = "https://aion-clinical.org/fhir/CodeSystem/event-type"
AION_RELATION_URL: Final[str] = "https://aion-clinical.org/fhir/StructureDefinition/relation"
AION_CONFIDENCE_URL: Final[str] = "https://aion-clinical.org/fhir/StructureDefinition/confidence"
AION_STAY_URL: Final[str] = "https://aion-clinical.org/fhir/StructureDefinition/stay-period"
AION_ATTRIBUTE_URL: Final[str] = "https://aion-clinical.org/fhir/StructureDefinition/attribute"


# ── Externe Standard-Code-Systeme ───────────────────────────────────
LOINC_URL: Final[str] = "http://loinc.org"
SNOMED_CT_URL: Final[str] = "http://snomed.info/sct"
ICD10_URL: Final[str] = "http://hl7.org/fhir/sid/icd-10"
ATC_URL: Final[str] = "http://www.whocc.no/atc"
UCUM_URL: Final[str] = "http://unitsofmeasure.org"
RXNORM_URL: Final[str] = "http://www.nlm.nih.gov/research/umls/rxnorm"


# ── ResourceType-Default per AION-Type-Familie ──────────────────────
# Wird verwendet, wenn die TypeHierarchy keinen `fhir_resource` setzt
# (Fallback). In der Praxis sollten Schemata den Resource-Typ explizit
# angeben.
DEFAULT_RESOURCE_BY_HINT: Final[dict[str, str]] = {
    "diagnose":     "Condition",
    "diagnosis":    "Condition",
    "beobachtung":  "Observation",
    "observation":  "Observation",
    "messung":      "Observation",
    "medikation":   "MedicationAdministration",
    "medication":   "MedicationAdministration",
    "prozedur":     "Procedure",
    "procedure":    "Procedure",
}


def guess_resource_type(type_name: str) -> str:
    """Heuristik für den Fallback, wenn `fhir_resource` im Schema fehlt.

    Liefert "Observation" als sehr defensive Default-Wahl, wenn nichts
    passt — Observation hat das flexibelste Wertemodell.
    """
    lower = type_name.lower()
    for hint, rt in DEFAULT_RESOURCE_BY_HINT.items():
        if hint in lower:
            return rt
    return "Observation"


# ── ATC-Mapping für Medikationen ────────────────────────────────────
# Optional: Wenn ein attributes["atc_code"] gesetzt ist, wird er als
# CodeableConcept mit diesem System gerendert.
def atc_to_coding(atc_code: str) -> dict:
    """ATC-Code als Coding-Dict für FHIR."""
    return {"system": ATC_URL, "code": atc_code}


def icd10_to_coding(icd_code: str) -> dict:
    return {"system": ICD10_URL, "code": icd_code}


def loinc_to_coding(loinc_code: str, display: str = "") -> dict:
    d = {"system": LOINC_URL, "code": loinc_code}
    if display:
        d["display"] = display
    return d

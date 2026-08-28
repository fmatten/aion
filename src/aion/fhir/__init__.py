# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""FHIR-Mapper für AION Clinical — OPTIONAL.

Lädt nur, wenn `fhir.resources` installiert ist:

    pip install fhir.resources

Public-API:

    to_fhir(event)                   — ClinicalEvent → FHIR-Resource
    from_fhir(resource)              — FHIR-Resource → ClinicalEvent
    to_fhir_bundle(events)           — Iterable → Bundle
    from_fhir_bundle(bundle)         — Bundle → list[ClinicalEvent]
    bundle_to_json / bundle_from_json
    bundle_to_file / bundle_from_file

Round-Trip-Test:

    >>> from aion.fhir import to_fhir, from_fhir
    >>> event2 = from_fhir(to_fhir(event1))
    >>> assert event1.patient_id == event2.patient_id
"""
# Diese Imports werfen ImportError mit klarer Botschaft, falls fhir.resources
# fehlt — nur beim ersten Funktionsaufruf, nicht beim Modul-Load.
from aion.fhir.mapper import to_fhir, from_fhir  # noqa: F401
from aion.fhir.bundle import (  # noqa: F401
    to_fhir_bundle, from_fhir_bundle,
    bundle_to_json, bundle_from_json,
    bundle_to_file, bundle_from_file,
)
from aion.fhir.codes import (  # noqa: F401
    AION_SYSTEM_URL, AION_RELATION_URL, AION_CONFIDENCE_URL,
    LOINC_URL, SNOMED_CT_URL, ICD10_URL, ATC_URL, UCUM_URL,
)


def has_fhir() -> bool:
    """Prüft, ob fhir.resources verfügbar ist."""
    try:
        import fhir.resources  # noqa: F401
        return True
    except ImportError:
        return False


__all__ = [
    "to_fhir", "from_fhir",
    "to_fhir_bundle", "from_fhir_bundle",
    "bundle_to_json", "bundle_from_json",
    "bundle_to_file", "bundle_from_file",
    "has_fhir",
    "AION_SYSTEM_URL", "AION_RELATION_URL", "AION_CONFIDENCE_URL",
    "LOINC_URL", "SNOMED_CT_URL", "ICD10_URL", "ATC_URL", "UCUM_URL",
]

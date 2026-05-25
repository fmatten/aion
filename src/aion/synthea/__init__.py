# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Synthea-Importer für AION Clinical.

Liest Standard-Synthea-`output/fhir/`-Bundles (FHIR R4 JSON) ein und
mappt FHIR-Resources auf AION-ClinicalEvents.

Designentscheidungen (Lesart C aus 1.4.0):

  * **Code-Mapping minimal eingebaut** — nur ~25 unstrittige Codes,
    Anwender-Mapping via `code_map=...` ergänzt oder überschreibt.
  * **Fallback statt Verlust** — unbekannte Codes werden zu
    `FHIR_<ResourceType>`-Events mit Code als Attribut. Keine Daten
    gehen verloren, sind nur weniger semantisch annotiert.
  * **Encounter → Aufnahme + stay_period** — jeder Synthea-Encounter
    wird sowohl als Aufnahme-Event mitgeschrieben als auch als
    `stay_start`/`stay_end` aller Events innerhalb des Encounters
    eingetragen. Das passt zur Demo-Konvention.

Beispiel:

    from aion.synthea import synthea_import_bundle, synthea_import_directory

    # Eine Datei
    events = synthea_import_bundle("output/fhir/Mary123.json")

    # Ganzes Verzeichnis
    events = synthea_import_directory("output/fhir/", limit=100)

    # Mit eigenem Code-Mapping
    extra = {"56265001": "Herzkrankheit"}  # SNOMED: Heart disease
    events = synthea_import_bundle("Patient.json", code_map=extra)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Union, Iterable

from aion.core.events import ClinicalEvent
from aion.core.relations import EventRelation
from aion.core.logging_setup import get_logger
from aion.synthea.codes import lookup_code, fallback_type_name

log = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
#  Hilfs-Funktionen
# ────────────────────────────────────────────────────────────────────
def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parst FHIR-Datetime-Strings zu naiven datetimes (UTC angenommen)."""
    if not value:
        return None
    # FHIR-Format: "2026-04-01T08:30:00+00:00" oder "2026-04-01T08:30:00Z"
    s = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        # Auf naiv umstellen für Konsistenz mit dem Rest von AION
        return dt.replace(tzinfo=None)
    except ValueError:
        log.debug("Konnte Datum nicht parsen: %s", value)
        return None


def _extract_patient_id(resource: dict, encounter_subject_ref: Optional[str] = None) -> str:
    """Holt Patient-ID aus FHIR-Resource via subject-Reference."""
    subject = resource.get("subject") or resource.get("patient")
    if isinstance(subject, dict) and "reference" in subject:
        # Format: "Patient/abc-123" oder "urn:uuid:abc-123"
        ref = subject["reference"]
        return ref.split("/")[-1].split(":")[-1]
    if encounter_subject_ref:
        return encounter_subject_ref.split("/")[-1].split(":")[-1]
    return "P-unknown"


def _resolve_event_type(
    resource: dict,
    code_map: Optional[dict[str, str]] = None,
) -> str:
    """Bestimmt AION-Typname aus FHIR-Code(s) der Resource.

    Probiert Code-Mapping. Wenn keiner passt, Fallback `FHIR_<Type>`.
    """
    resource_type = resource.get("resourceType", "Unknown")

    # FHIR-Code kann an verschiedenen Stellen sitzen
    code_blocks = []
    if "code" in resource and isinstance(resource["code"], dict):
        code_blocks.append(resource["code"])
    if "medicationCodeableConcept" in resource:
        code_blocks.append(resource["medicationCodeableConcept"])
    # Encounter hat type[] als Liste
    for t in resource.get("type", []) or []:
        if isinstance(t, dict):
            code_blocks.append(t)

    for block in code_blocks:
        for coding in block.get("coding", []) or []:
            code = coding.get("code")
            system = coding.get("system")
            if code:
                mapped = lookup_code(code, system=system, extra_map=code_map)
                if mapped:
                    return mapped

    return fallback_type_name(resource_type)


def _extract_attributes(resource: dict) -> dict:
    """Bündelt FHIR-spezifische Werte als AION-Attribute."""
    attrs: dict[str, Any] = {}

    # Numeric value (Observation)
    vq = resource.get("valueQuantity")
    if isinstance(vq, dict):
        if "value" in vq:
            attrs["value"] = vq["value"]
        if "unit" in vq:
            attrs["unit"] = vq["unit"]

    # CodeableConcept value (Condition severity etc.)
    vcc = resource.get("valueCodeableConcept")
    if isinstance(vcc, dict):
        for coding in vcc.get("coding", []) or []:
            if "display" in coding:
                attrs["value"] = coding["display"]
                break

    # String value
    vs = resource.get("valueString")
    if vs:
        attrs["value"] = vs

    # Bool value
    if "valueBoolean" in resource:
        attrs["value"] = resource["valueBoolean"]

    # Code-Information mitnehmen, auch wenn Mapping erfolgte
    # Probiert zwei Stellen: 'code' und 'medicationCodeableConcept'
    code_block = resource.get("code") or resource.get("medicationCodeableConcept")
    if isinstance(code_block, dict):
        for coding in code_block.get("coding", []) or []:
            if coding.get("code"):
                attrs["fhir_code"] = coding["code"]
                if coding.get("system"):
                    attrs["fhir_system"] = coding["system"]
                if coding.get("display"):
                    attrs["fhir_display"] = coding["display"]
                break

    # Severity, status für Conditions
    if resource.get("severity"):
        sev = resource["severity"]
        if isinstance(sev, dict):
            for c in sev.get("coding", []) or []:
                if c.get("display"):
                    attrs["severity"] = c["display"]
                    break

    if resource.get("clinicalStatus"):
        cs = resource["clinicalStatus"]
        if isinstance(cs, dict):
            for c in cs.get("coding", []) or []:
                if c.get("code"):
                    attrs["status"] = c["code"]
                    break

    return attrs


# ────────────────────────────────────────────────────────────────────
#  Encounter-Indexierung
# ────────────────────────────────────────────────────────────────────
def _index_encounters(bundle: dict) -> dict[str, tuple[Optional[datetime], Optional[datetime], str]]:
    """Liefert Encounter-ID → (start, end, patient_id) für alle Encounters."""
    index: dict[str, tuple[Optional[datetime], Optional[datetime], str]] = {}

    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        if res.get("resourceType") != "Encounter":
            continue

        enc_id = res.get("id", "")
        period = res.get("period", {})
        start = _parse_dt(period.get("start"))
        end = _parse_dt(period.get("end"))
        patient_id = _extract_patient_id(res)

        index[enc_id] = (start, end, patient_id)
        # Auch via fullUrl referenzierbar
        full_url = entry.get("fullUrl", "")
        if full_url:
            ref_id = full_url.split("/")[-1].split(":")[-1]
            index[ref_id] = (start, end, patient_id)

    return index


def _resolve_encounter(resource: dict, encounters: dict) -> tuple[Optional[datetime], Optional[datetime]]:
    """Sucht stay_start/stay_end für eine Resource via encounter-Reference."""
    enc_ref = resource.get("encounter")
    if isinstance(enc_ref, dict) and "reference" in enc_ref:
        ref = enc_ref["reference"]
        ref_id = ref.split("/")[-1].split(":")[-1]
        if ref_id in encounters:
            start, end, _ = encounters[ref_id]
            return start, end
    return None, None


def _resource_event_time(resource: dict) -> Optional[datetime]:
    """Findet primären Zeitstempel einer FHIR-Resource."""
    # In Reihenfolge der FHIR-Konvention
    for key in ("effectiveDateTime", "onsetDateTime", "occurrenceDateTime",
                "performedDateTime", "issued", "recordedDate", "authoredOn"):
        dt = _parse_dt(resource.get(key))
        if dt:
            return dt
    # Fallback: Period-Start
    period = resource.get("effectivePeriod") or resource.get("performedPeriod")
    if isinstance(period, dict):
        return _parse_dt(period.get("start"))
    return None


# ────────────────────────────────────────────────────────────────────
#  Kern-Importer
# ────────────────────────────────────────────────────────────────────
SUPPORTED_RESOURCE_TYPES = {
    "Encounter", "Condition", "Observation",
    "MedicationRequest", "MedicationAdministration",
    "Procedure",
}


def synthea_import_bundle(
    path: Union[str, Path],
    *,
    code_map: Optional[dict[str, str]] = None,
    include_encounters: bool = True,
) -> list[ClinicalEvent]:
    """Liest ein Synthea-Bundle (FHIR R4 JSON) und mappt es auf ClinicalEvents.

    Args:
        path: Pfad zur Bundle-JSON-Datei.
        code_map: optionales Anwender-Mapping (FHIR-Code → AION-Typname).
                  Hat Vorrang vor dem eingebauten Default-Mapping.
        include_encounters: wenn True (Default), werden Encounter zusätzlich
                            als `Aufnahme`-Events mitgeschrieben.

    Returns:
        Liste ClinicalEvents — chronologisch sortiert nach t_start.

    Raises:
        FileNotFoundError: Datei existiert nicht.
        json.JSONDecodeError: kein gültiges JSON.
        ValueError: kein FHIR Bundle.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Bundle nicht gefunden: {path}")

    with open(path, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    if bundle.get("resourceType") != "Bundle":
        raise ValueError(
            f"Nicht ein FHIR-Bundle (resourceType={bundle.get('resourceType')!r})"
        )

    encounters = _index_encounters(bundle)
    events: list[ClinicalEvent] = []
    n_skipped = 0

    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rtype = res.get("resourceType", "")

        if rtype not in SUPPORTED_RESOURCE_TYPES:
            n_skipped += 1
            continue

        # Encounter separat behandeln
        if rtype == "Encounter":
            if not include_encounters:
                continue
            event = _build_encounter_event(res, code_map)
            if event:
                events.append(event)
            continue

        event = _build_event(res, encounters, code_map)
        if event:
            events.append(event)
        else:
            n_skipped += 1

    log.info("Synthea-Import: %s → %d Events, %d übersprungen",
             path.name, len(events), n_skipped)

    # Chronologisch sortieren
    events.sort(key=lambda e: e.t_start)
    return events


def _build_encounter_event(
    resource: dict,
    code_map: Optional[dict[str, str]],
) -> Optional[ClinicalEvent]:
    """Baut ein 'Aufnahme'-Event aus einem Encounter."""
    period = resource.get("period", {})
    start = _parse_dt(period.get("start"))
    end = _parse_dt(period.get("end"))

    if not start:
        return None

    # End ist bei laufenden Encountern None
    if not end:
        end = start + timedelta(hours=1)  # konservativ

    # Klassen-Code mitnehmen
    attrs: dict[str, Any] = {}
    enc_class = resource.get("class")
    if isinstance(enc_class, dict):
        if enc_class.get("code"):
            attrs["encounter_class"] = enc_class["code"]
        if enc_class.get("display"):
            attrs["encounter_display"] = enc_class["display"]

    # Typname: Aufnahme als Default; Versuch via Type-Codes
    event_type = "Aufnahme"
    type_list = resource.get("type", [])
    if type_list and isinstance(type_list, list):
        for t in type_list:
            for coding in t.get("coding", []) or []:
                mapped = lookup_code(
                    coding.get("code", ""),
                    system=coding.get("system"),
                    extra_map=code_map,
                )
                if mapped:
                    event_type = mapped
                    break
            if event_type != "Aufnahme":
                break

    return ClinicalEvent(
        patient_id=_extract_patient_id(resource),
        event_type=event_type,
        t_start=start,
        t_end=start + timedelta(minutes=1),  # Aufnahme als Punktereignis
        stay_start=start,
        stay_end=end,
        attributes=attrs,
    )


def _build_event(
    resource: dict,
    encounters: dict,
    code_map: Optional[dict[str, str]],
) -> Optional[ClinicalEvent]:
    """Baut ein ClinicalEvent aus einer FHIR-Resource (außer Encounter)."""
    t_event = _resource_event_time(resource)
    if not t_event:
        return None

    stay_start, stay_end = _resolve_encounter(resource, encounters)
    # Falls kein Encounter zuordenbar: Stay = Event ± 1h
    if not stay_start:
        stay_start = t_event - timedelta(hours=1)
    if not stay_end:
        stay_end = t_event + timedelta(hours=1)

    return ClinicalEvent(
        patient_id=_extract_patient_id(resource),
        event_type=_resolve_event_type(resource, code_map),
        t_start=t_event,
        t_end=t_event,  # Punktereignis; Period wäre genauer aber selten gesetzt
        stay_start=stay_start,
        stay_end=stay_end,
        attributes=_extract_attributes(resource),
    )


def synthea_import_directory(
    directory: Union[str, Path],
    *,
    limit: Optional[int] = None,
    code_map: Optional[dict[str, str]] = None,
    pattern: str = "*.json",
) -> list[ClinicalEvent]:
    """Liest alle Synthea-Bundles aus einem Verzeichnis batch-weise ein.

    Args:
        directory: Pfad zum Verzeichnis (z. B. Synthea `output/fhir/`).
        limit: optional max. Anzahl Patienten-Bundles. None = alle.
        code_map: optionales Anwender-Mapping.
        pattern: Glob-Pattern für Datei-Auswahl (Default `*.json`).

    Returns:
        Aggregierte Liste aller ClinicalEvents über alle Bundles.

    Raises:
        FileNotFoundError: Verzeichnis existiert nicht.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Verzeichnis nicht gefunden: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {directory}")

    bundles = sorted(directory.glob(pattern))
    if limit is not None:
        bundles = bundles[:limit]

    log.info("Synthea-Verzeichnis: %d Bundle(s) zu lesen", len(bundles))

    all_events: list[ClinicalEvent] = []
    n_failed = 0
    for bundle_path in bundles:
        try:
            events = synthea_import_bundle(bundle_path, code_map=code_map)
            all_events.extend(events)
        except Exception as e:
            log.warning("Bundle %s übersprungen: %s", bundle_path.name, e)
            n_failed += 1

    log.info("Synthea-Verzeichnis: %d Events insgesamt, %d Bundle(s) gescheitert",
             len(all_events), n_failed)
    return all_events


__all__ = [
    "synthea_import_bundle",
    "synthea_import_directory",
    "SUPPORTED_RESOURCE_TYPES",
]

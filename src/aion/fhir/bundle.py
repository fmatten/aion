# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""FHIR-Bundle-Operationen für AION ClinicalEvents.

Ein Bundle ist ein Container für mehrere FHIR-Resourcen — typisch
für Synthea-Exports oder MIMIC-IV-FHIR-Datasets.

Wir unterstützen drei Bundle-Typen:
    * collection  — ungeordnete Sammlung (Default für Export)
    * batch       — Server soll alle einzeln verarbeiten
    * transaction — atomarer Block

Beim Lesen ignorieren wir den Typ und ziehen alle Entries.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional
import json
import uuid

from aion.core.events import ClinicalEvent
from aion.fhir.mapper import to_fhir, from_fhir, _require_fhir


_SUPPORTED_RESOURCES = {
    "Observation", "Condition", "MedicationAdministration", "Procedure",
}


def to_fhir_bundle(
    events: Iterable[ClinicalEvent],
    *,
    bundle_type: str = "collection",
    type_hierarchy: Optional[Any] = None,
) -> Any:
    """Wandelt ClinicalEvents in ein FHIR-Bundle.

    Args:
        events:         iterierbar von ClinicalEvent
        bundle_type:    "collection", "batch", "transaction", "document", ...
        type_hierarchy: optional, falls FHIR-Resource-Typ aus Schema gelesen
                        werden soll (Feld `fhir_resource` im TypeNode).
    """
    _require_fhir()
    from fhir.resources.bundle import Bundle, BundleEntry

    entries = []
    for event in events:
        rt = None
        if type_hierarchy is not None and event.event_type in type_hierarchy:
            node = type_hierarchy.get(event.event_type)
            rt = node.fhir_resource
            if rt is None:
                # Versuche Vorfahren
                for ancestor in type_hierarchy.ancestors(event.event_type):
                    if ancestor == type_hierarchy.TOP:
                        continue
                    a_node = type_hierarchy.get(ancestor)
                    if a_node.fhir_resource:
                        rt = a_node.fhir_resource
                        break
        resource = to_fhir(event, resource_type=rt)
        entry = BundleEntry(
            fullUrl=f"urn:uuid:{event.event_id}",
            resource=resource,
        )
        entries.append(entry)

    bundle = Bundle(
        id=str(uuid.uuid4()),
        type=bundle_type,
        entry=entries,
    )
    return bundle


def from_fhir_bundle(bundle: Any) -> list[ClinicalEvent]:
    """Liest alle unterstützten Resourcen aus einem Bundle als ClinicalEvents.

    Resourcen, deren Typ wir nicht unterstützen (z. B. Patient, Encounter,
    DiagnosticReport), werden mit einer Warnung übersprungen — nicht als
    Fehler behandelt, weil typische FHIR-Bundles diese mitschicken.
    """
    _require_fhir()
    out: list[ClinicalEvent] = []
    for entry in (bundle.entry or []):
        resource = entry.resource
        if resource is None:
            continue
        rt = resource.__class__.__name__
        if rt not in _SUPPORTED_RESOURCES:
            continue
        try:
            event = from_fhir(resource)
            out.append(event)
        except Exception as e:
            # Im Bundle-Kontext: einzelne fehlerhafte Entry nicht das ganze
            # Parsen abbrechen lassen.
            import warnings
            warnings.warn(
                f"FHIR-Bundle: Konnte {rt} (id={resource.id}) nicht parsen: {e}",
                stacklevel=2,
            )
    return out


def bundle_to_json(bundle: Any, *, indent: int = 2) -> str:
    """Serialisiert ein Bundle in einen JSON-String."""
    _require_fhir()
    if hasattr(bundle, "model_dump_json"):
        return bundle.model_dump_json(indent=indent)
    return bundle.json(indent=indent)


def bundle_from_json(text: str) -> Any:
    """Liest ein Bundle aus einem JSON-String."""
    _require_fhir()
    from fhir.resources.bundle import Bundle
    data = json.loads(text)
    return Bundle.model_validate(data)


def bundle_from_file(path: str) -> Any:
    """Liest ein Bundle aus einer Datei."""
    with open(path, "r", encoding="utf-8") as f:
        return bundle_from_json(f.read())


def bundle_to_file(bundle: Any, path: str, *, indent: int = 2) -> None:
    """Schreibt ein Bundle als JSON-Datei."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(bundle_to_json(bundle, indent=indent))

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Round-Trip-Mapper zwischen AION ClinicalEvent und FHIR-Resourcen.

Unterstützte Resource-Typen (R5 via fhir.resources):
    * Observation (Beobachtungen, Messungen, Scores)
    * Condition (Diagnosen)
    * MedicationAdministration (Medikamentengabe)
    * Procedure (Prozeduren, Eingriffe)

Round-Trip-Garantie:
    Bei zerstörungsfreiem Mapping gilt:
        from_fhir(to_fhir(event)) == event   (modulo nicht-AION-Felder)

    Felder, die FHIR nicht nativ kennt (Konfidenzmaß, Beziehungstyp,
    Aufenthalts-Periode), werden als Extensions mit AION-eigenen
    System-URLs gespeichert (siehe codes.py).

Mapping-Konzept:
    ClinicalEvent              FHIR
    ─────────────────────────  ──────────────────────────────────────
    event_id                   Resource.id
    patient_id                 subject.reference = "Patient/{id}"
    event_type                 code.coding[].code (System: AION_SYSTEM_URL)
    t_start, t_end             effective[Period|DateTime] (Resource-spezifisch)
    stay_start, stay_end       Extension (AION_STAY_URL)
    confidence                 Extension (AION_CONFIDENCE_URL), nur falls < 1.0
    attributes                 ResourceType-spezifisch (component, dosage, ...)
    references[ref]=relation   Resource-spezifisch (derivedFrom, partOf, ...)
                               + Extension mit AION_RELATION_URL für die Relation
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

from aion.core.events import ClinicalEvent
from aion.core.relations import EventRelation
from aion.fhir.codes import (
    AION_SYSTEM_URL, AION_RELATION_URL, AION_CONFIDENCE_URL, AION_STAY_URL,
    AION_ATTRIBUTE_URL, UCUM_URL, guess_resource_type,
)


def _require_fhir():
    """Lazy-Loader für fhir.resources. Sprechende Fehlermeldung."""
    try:
        import fhir.resources  # noqa: F401
        return True
    except ImportError as e:
        raise ImportError(
            "fhir.resources ist nicht installiert. Installation:\n"
            "    pip install fhir.resources\n"
            "(Optionale Abhängigkeit für aion.fhir.)"
        ) from e


# ────────────────────────────────────────────────────────────────────
# Hilfsfunktionen für Datetime-Konvertierung
# ────────────────────────────────────────────────────────────────────
def _ensure_tz(dt: datetime) -> datetime:
    """FHIR verlangt zeitzonenbewusste Datetime-Werte. Naive Werte werden
    als UTC interpretiert.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_fhir_datetime(dt: datetime) -> str:
    """ISO-String mit Z-Suffix für FHIR."""
    return _ensure_tz(dt).isoformat().replace("+00:00", "Z")


def _from_fhir_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────
def to_fhir(event: ClinicalEvent, *, resource_type: Optional[str] = None) -> Any:
    """Konvertiert ein ClinicalEvent in eine FHIR-Resource.

    Args:
        event:         Das zu konvertierende Ereignis.
        resource_type: Erzwingt einen bestimmten Resource-Typ. Wenn None,
                       wird er aus event.event_type via TypeHierarchy oder
                       Heuristik abgeleitet (siehe guess_resource_type).

    Returns:
        fhir.resources-Objekt (Observation/Condition/MedicationAdministration/Procedure).
    """
    _require_fhir()
    rt = resource_type or guess_resource_type(event.event_type)

    if rt == "Observation":
        return _to_observation(event)
    if rt == "Condition":
        return _to_condition(event)
    if rt == "MedicationAdministration":
        return _to_medication(event)
    if rt == "Procedure":
        return _to_procedure(event)
    raise ValueError(f"Unbekannter FHIR-Resource-Typ: {rt!r}")


def from_fhir(resource: Any) -> ClinicalEvent:
    """Konvertiert eine FHIR-Resource zurück in ein ClinicalEvent."""
    _require_fhir()
    rt = resource.__class__.__name__
    if rt == "Observation":
        return _from_observation(resource)
    if rt == "Condition":
        return _from_condition(resource)
    if rt == "MedicationAdministration":
        return _from_medication(resource)
    if rt == "Procedure":
        return _from_procedure(resource)
    raise ValueError(f"Nicht unterstützter FHIR-Resource-Typ: {rt}")


# ────────────────────────────────────────────────────────────────────
# Gemeinsame Bausteine
# ────────────────────────────────────────────────────────────────────
def _build_code(event_type: str):
    """CodeableConcept mit AION-System-URL."""
    from fhir.resources.codeableconcept import CodeableConcept
    from fhir.resources.coding import Coding
    return CodeableConcept(coding=[
        Coding(system=AION_SYSTEM_URL, code=event_type, display=event_type),
    ])


def _build_subject(patient_id: str):
    """Reference auf Patient/{id}."""
    from fhir.resources.reference import Reference
    return Reference(reference=f"Patient/{patient_id}")


def _build_period(start: datetime, end: datetime):
    from fhir.resources.period import Period
    return Period(start=_to_fhir_datetime(start), end=_to_fhir_datetime(end))


def _stay_extension(event: ClinicalEvent):
    """Extension mit dem Aufenthalts-Zeitraum."""
    from fhir.resources.extension import Extension
    return Extension(
        url=AION_STAY_URL,
        valuePeriod=_build_period(event.stay_start, event.stay_end),
    )


def _confidence_extension(event: ClinicalEvent) -> Optional[Any]:
    """Extension mit Konfidenz, nur falls != 1.0."""
    if event.confidence == 1.0:
        return None
    from fhir.resources.extension import Extension
    return Extension(url=AION_CONFIDENCE_URL, valueDecimal=event.confidence)


def _relation_extension(relation: str):
    """Extension, die einer FHIR-Reference die AION-Relation anhängt."""
    from fhir.resources.extension import Extension
    return Extension(url=AION_RELATION_URL, valueString=relation)


def _build_reference_with_relation(target_id: str, relation: str):
    """Erzeugt eine FHIR-Reference auf einen anderen Event mit Relation-Extension."""
    from fhir.resources.reference import Reference
    return Reference(
        reference=f"Observation/{target_id}",  # generisch, beim Parsen lesen wir nur die ID
        extension=[_relation_extension(relation)],
    )


def _build_extensions(event: ClinicalEvent) -> list:
    """Sammelt alle AION-spezifischen Extensions (Stay-Period, Confidence)."""
    exts = [_stay_extension(event)]
    conf_ext = _confidence_extension(event)
    if conf_ext is not None:
        exts.append(conf_ext)
    return exts


def _build_attribute_extensions(attributes: dict) -> list:
    """Wandelt Restattribute, die nicht in native Felder gemappt wurden,
    in eine flache Liste von Extensions um.
    """
    from fhir.resources.extension import Extension
    out = []
    for key, value in attributes.items():
        ext = Extension(url=f"{AION_ATTRIBUTE_URL}#{key}")
        if isinstance(value, bool):
            ext.valueBoolean = value
        elif isinstance(value, int):
            ext.valueInteger = value
        elif isinstance(value, float):
            ext.valueDecimal = value
        else:
            ext.valueString = str(value)
        out.append(ext)
    return out


# ────────────────────────────────────────────────────────────────────
# Parser-Helper
# ────────────────────────────────────────────────────────────────────
def _extract_event_type(resource) -> str:
    """Extrahiert event_type aus dem AION-System-Coding (mit Fallback)."""
    code = getattr(resource, "code", None)
    if code is None:
        return resource.__class__.__name__
    for coding in (code.coding or []):
        if coding.system == AION_SYSTEM_URL:
            return coding.code
    # Fallback: erstes Coding nehmen
    if code.coding:
        return code.coding[0].code or resource.__class__.__name__
    return resource.__class__.__name__


def _extract_patient_id(resource) -> str:
    subj = getattr(resource, "subject", None)
    if subj is None or not subj.reference:
        return "UNKNOWN"
    ref = subj.reference
    return ref.split("/", 1)[1] if "/" in ref else ref


def _extract_stay_period(resource) -> tuple[Optional[datetime], Optional[datetime]]:
    for ext in (getattr(resource, "extension", None) or []):
        if ext.url == AION_STAY_URL and ext.valuePeriod:
            return (
                _from_fhir_datetime(ext.valuePeriod.start),
                _from_fhir_datetime(ext.valuePeriod.end),
            )
    return None, None


def _extract_confidence(resource) -> float:
    for ext in (getattr(resource, "extension", None) or []):
        if ext.url == AION_CONFIDENCE_URL and ext.valueDecimal is not None:
            return float(ext.valueDecimal)
    return 1.0


def _extract_attribute_extensions(resource) -> dict:
    """Liest Extensions zurück, die per _build_attribute_extensions geschrieben wurden."""
    attrs: dict = {}
    for ext in (getattr(resource, "extension", None) or []):
        if not ext.url.startswith(AION_ATTRIBUTE_URL):
            continue
        if "#" not in ext.url:
            continue
        key = ext.url.split("#", 1)[1]
        if ext.valueBoolean is not None:
            attrs[key] = ext.valueBoolean
        elif ext.valueInteger is not None:
            attrs[key] = ext.valueInteger
        elif ext.valueDecimal is not None:
            attrs[key] = float(ext.valueDecimal)
        elif ext.valueString is not None:
            attrs[key] = ext.valueString
    return attrs


def _extract_references_from(field_value, default_relation: str) -> dict[str, str]:
    """Extrahiert Reference-Listen mit Relation-Extension."""
    refs: dict[str, str] = {}
    if not field_value:
        return refs
    for r in field_value:
        if not r.reference:
            continue
        target_id = r.reference.split("/", 1)[1] if "/" in r.reference else r.reference
        # Relation aus Extension lesen, sonst default
        rel = default_relation
        for ext in (r.extension or []):
            if ext.url == AION_RELATION_URL and ext.valueString:
                rel = ext.valueString
                break
        refs[target_id] = rel
    return refs


# ────────────────────────────────────────────────────────────────────
# Observation
# ────────────────────────────────────────────────────────────────────
def _to_observation(event: ClinicalEvent):
    from fhir.resources.observation import Observation

    obs = Observation(
        id=event.event_id,
        status="final",
        code=_build_code(event.event_type),
        subject=_build_subject(event.patient_id),
        effectivePeriod=_build_period(event.t_start, event.t_end),
        extension=_build_extensions(event),
    )

    # Attribute-Mapping: 'value' und 'unit' werden als valueQuantity gerendert,
    # alles andere als Component oder Extension.
    remaining = dict(event.attributes)
    if "value" in remaining and isinstance(remaining["value"], (int, float)):
        from fhir.resources.quantity import Quantity
        unit = remaining.pop("unit", None)
        q = Quantity(value=float(remaining.pop("value")))
        if unit:
            q.unit = str(unit)
            q.system = UCUM_URL
            q.code = str(unit)
        obs.valueQuantity = q

    # Restliche numerische Attribute als Components rendern (Blutdruck-Pattern)
    components = []
    leftover: dict = {}
    for key, val in remaining.items():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            from fhir.resources.observation import ObservationComponent
            from fhir.resources.quantity import Quantity
            comp = ObservationComponent(
                code=_build_code(key),
                valueQuantity=Quantity(value=float(val)),
            )
            components.append(comp)
        else:
            leftover[key] = val
    if components:
        obs.component = components
    if leftover:
        obs.extension = (obs.extension or []) + _build_attribute_extensions(leftover)

    # Referenzen — alle als derivedFrom mit Relation-Extension
    if event.references:
        obs.derivedFrom = [
            _build_reference_with_relation(ref_id, rel)
            for ref_id, rel in event.references.items()
        ]

    return obs


def _from_observation(obs) -> ClinicalEvent:
    period = obs.effectivePeriod
    t_start = _from_fhir_datetime(period.start) if period and period.start else None
    t_end = _from_fhir_datetime(period.end) if period and period.end else t_start
    stay_start, stay_end = _extract_stay_period(obs)

    attrs: dict = {}
    if obs.valueQuantity is not None:
        attrs["value"] = float(obs.valueQuantity.value)
        if obs.valueQuantity.unit:
            attrs["unit"] = obs.valueQuantity.unit
        elif obs.valueQuantity.code:
            attrs["unit"] = obs.valueQuantity.code

    for comp in (obs.component or []):
        # Component-Code → Attribut-Name
        name = None
        for c in (comp.code.coding or []):
            if c.system == AION_SYSTEM_URL:
                name = c.code
                break
        if name and comp.valueQuantity is not None:
            attrs[name] = float(comp.valueQuantity.value)

    attrs.update(_extract_attribute_extensions(obs))

    references = _extract_references_from(obs.derivedFrom, EventRelation.OBSERVATION_OF)

    return ClinicalEvent(
        event_id=obs.id,
        patient_id=_extract_patient_id(obs),
        event_type=_extract_event_type(obs),
        t_start=t_start,
        t_end=t_end,
        stay_start=stay_start or t_start,
        stay_end=stay_end or t_end,
        attributes=attrs,
        references=references,
        confidence=_extract_confidence(obs),
    )


# ────────────────────────────────────────────────────────────────────
# Condition
# ────────────────────────────────────────────────────────────────────
def _to_condition(event: ClinicalEvent):
    from fhir.resources.condition import Condition
    from fhir.resources.codeableconcept import CodeableConcept
    from fhir.resources.coding import Coding

    cond = Condition(
        id=event.event_id,
        clinicalStatus=CodeableConcept(coding=[Coding(
            system="http://terminology.hl7.org/CodeSystem/condition-clinical",
            code="active",
        )]),
        code=_build_code(event.event_type),
        subject=_build_subject(event.patient_id),
        onsetDateTime=_to_fhir_datetime(event.t_start),
        extension=_build_extensions(event),
    )

    # 'severity' als FHIR-natives Feld
    remaining = dict(event.attributes)
    if "severity" in remaining and remaining["severity"]:
        from fhir.resources.codeableconcept import CodeableConcept
        from fhir.resources.coding import Coding
        cond.severity = CodeableConcept(coding=[Coding(
            system=AION_SYSTEM_URL, code=str(remaining.pop("severity")),
        )])

    if remaining:
        cond.extension = (cond.extension or []) + _build_attribute_extensions(remaining)

    if event.references:
        # Condition kennt evidence + reasonReference, hier nutzen wir evidence
        from fhir.resources.codeablereference import CodeableReference
        evidence_refs = []
        for ref_id, rel in event.references.items():
            cr = CodeableReference(
                reference=_build_reference_with_relation(ref_id, rel),
            )
            evidence_refs.append(cr)
        # In R5 ist Condition.evidence eine Liste von CodeableReference
        try:
            cond.evidence = evidence_refs
        except Exception:
            # Fallback bei API-Differenzen
            cond.extension = (cond.extension or []) + [
                _relation_extension(f"{rel}:{ref_id}")
                for ref_id, rel in event.references.items()
            ]

    return cond


def _from_condition(cond) -> ClinicalEvent:
    t_start = _from_fhir_datetime(cond.onsetDateTime) if cond.onsetDateTime else None
    stay_start, stay_end = _extract_stay_period(cond)

    attrs: dict = {}
    if cond.severity and cond.severity.coding:
        for c in cond.severity.coding:
            if c.code:
                attrs["severity"] = c.code
                break
    attrs.update(_extract_attribute_extensions(cond))

    references: dict[str, str] = {}
    for ev in (cond.evidence or []):
        if ev.reference and ev.reference.reference:
            target = ev.reference.reference
            target_id = target.split("/", 1)[1] if "/" in target else target
            rel = EventRelation.CONFIRMS
            for ext in (ev.reference.extension or []):
                if ext.url == AION_RELATION_URL and ext.valueString:
                    rel = ext.valueString
                    break
            references[target_id] = rel

    return ClinicalEvent(
        event_id=cond.id,
        patient_id=_extract_patient_id(cond),
        event_type=_extract_event_type(cond),
        t_start=t_start,
        t_end=t_start,  # Condition hat keinen End-Zeitpunkt im Default
        stay_start=stay_start or t_start,
        stay_end=stay_end or t_start,
        attributes=attrs,
        references=references,
        confidence=_extract_confidence(cond),
    )


# ────────────────────────────────────────────────────────────────────
# MedicationAdministration
# ────────────────────────────────────────────────────────────────────
def _to_medication(event: ClinicalEvent):
    from fhir.resources.medicationadministration import (
        MedicationAdministration, MedicationAdministrationDosage,
    )
    from fhir.resources.codeablereference import CodeableReference
    from fhir.resources.codeableconcept import CodeableConcept
    from fhir.resources.coding import Coding
    from fhir.resources.quantity import Quantity

    remaining = dict(event.attributes)

    # Medication-Code aus atc_code, falls vorhanden
    medication_codings = [Coding(system=AION_SYSTEM_URL, code=event.event_type,
                                 display=event.event_type)]
    if "atc_code" in remaining:
        from aion.fhir.codes import ATC_URL
        medication_codings.append(Coding(system=ATC_URL,
                                         code=str(remaining.pop("atc_code"))))

    medication = CodeableReference(
        concept=CodeableConcept(coding=medication_codings),
    )

    med = MedicationAdministration(
        id=event.event_id,
        status="completed",
        medication=medication,
        subject=_build_subject(event.patient_id),
        occurencePeriod=_build_period(event.t_start, event.t_end),
        extension=_build_extensions(event),
    )

    # Dosis-Mapping
    if "dose" in remaining:
        dose = remaining.pop("dose")
        unit = remaining.pop("unit", None)
        route_code = remaining.pop("route", None)
        dosage = MedicationAdministrationDosage()
        if isinstance(dose, (int, float)):
            q = Quantity(value=float(dose))
            if unit:
                q.unit = str(unit)
            dosage.dose = q
        if route_code:
            dosage.route = CodeableConcept(coding=[
                Coding(system=AION_SYSTEM_URL, code=str(route_code)),
            ])
        med.dosage = dosage

    if remaining:
        med.extension = (med.extension or []) + _build_attribute_extensions(remaining)

    if event.references:
        # MedicationAdministration kennt reason (CodeableReference) — passt für response_to
        from fhir.resources.codeablereference import CodeableReference as CR
        med.reason = []
        for ref_id, rel in event.references.items():
            cr = CR(reference=_build_reference_with_relation(ref_id, rel))
            med.reason.append(cr)

    return med


def _from_medication(med) -> ClinicalEvent:
    period = med.occurencePeriod
    t_start = _from_fhir_datetime(period.start) if period and period.start else None
    t_end = _from_fhir_datetime(period.end) if period and period.end else t_start
    stay_start, stay_end = _extract_stay_period(med)

    attrs: dict = {}
    # Medication-Konzept zurückbauen
    if med.medication and med.medication.concept:
        for c in (med.medication.concept.coding or []):
            from aion.fhir.codes import ATC_URL
            if c.system == ATC_URL and c.code:
                attrs["atc_code"] = c.code
                break

    # Dosage zurückbauen
    if med.dosage:
        if med.dosage.dose:
            attrs["dose"] = float(med.dosage.dose.value)
            if med.dosage.dose.unit:
                attrs["unit"] = med.dosage.dose.unit
        if med.dosage.route and med.dosage.route.coding:
            for c in med.dosage.route.coding:
                if c.code:
                    attrs["route"] = c.code
                    break

    attrs.update(_extract_attribute_extensions(med))

    references: dict[str, str] = {}
    for r in (med.reason or []):
        if r.reference and r.reference.reference:
            target = r.reference.reference
            target_id = target.split("/", 1)[1] if "/" in target else target
            rel = EventRelation.RESPONSE_TO
            for ext in (r.reference.extension or []):
                if ext.url == AION_RELATION_URL and ext.valueString:
                    rel = ext.valueString
                    break
            references[target_id] = rel

    return ClinicalEvent(
        event_id=med.id,
        patient_id=_extract_patient_id(med),
        event_type=_extract_event_type_from_medication(med),
        t_start=t_start,
        t_end=t_end,
        stay_start=stay_start or t_start,
        stay_end=stay_end or t_end,
        attributes=attrs,
        references=references,
        confidence=_extract_confidence(med),
    )


def _extract_event_type_from_medication(med) -> str:
    """MedicationAdministration hat keinen .code, sondern medication.concept.coding."""
    if med.medication and med.medication.concept:
        for c in (med.medication.concept.coding or []):
            if c.system == AION_SYSTEM_URL:
                return c.code
    return "MedicationAdministration"


# ────────────────────────────────────────────────────────────────────
# Procedure
# ────────────────────────────────────────────────────────────────────
def _to_procedure(event: ClinicalEvent):
    from fhir.resources.procedure import Procedure

    proc = Procedure(
        id=event.event_id,
        status="completed",
        code=_build_code(event.event_type),
        subject=_build_subject(event.patient_id),
        occurrencePeriod=_build_period(event.t_start, event.t_end),
        extension=_build_extensions(event),
    )

    if event.attributes:
        proc.extension = (proc.extension or []) + _build_attribute_extensions(event.attributes)

    if event.references:
        from fhir.resources.codeablereference import CodeableReference
        proc.reason = []
        for ref_id, rel in event.references.items():
            cr = CodeableReference(reference=_build_reference_with_relation(ref_id, rel))
            proc.reason.append(cr)

    return proc


def _from_procedure(proc) -> ClinicalEvent:
    period = proc.occurrencePeriod
    t_start = _from_fhir_datetime(period.start) if period and period.start else None
    t_end = _from_fhir_datetime(period.end) if period and period.end else t_start
    stay_start, stay_end = _extract_stay_period(proc)

    attrs = _extract_attribute_extensions(proc)

    references: dict[str, str] = {}
    for r in (proc.reason or []):
        if r.reference and r.reference.reference:
            target = r.reference.reference
            target_id = target.split("/", 1)[1] if "/" in target else target
            rel = EventRelation.RESPONSE_TO
            for ext in (r.reference.extension or []):
                if ext.url == AION_RELATION_URL and ext.valueString:
                    rel = ext.valueString
                    break
            references[target_id] = rel

    return ClinicalEvent(
        event_id=proc.id,
        patient_id=_extract_patient_id(proc),
        event_type=_extract_event_type(proc),
        t_start=t_start,
        t_end=t_end,
        stay_start=stay_start or t_start,
        stay_end=stay_end or t_end,
        attributes=attrs,
        references=references,
        confidence=_extract_confidence(proc),
    )

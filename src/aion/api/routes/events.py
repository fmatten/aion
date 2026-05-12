# aion/api/routes/events.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – EUPL-1.2
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from aion.api.auth_keycloak import require_user, ClaimsUser
from aion.api.metrics import events_created, query_duration

router = APIRouter()


class EventIn(BaseModel):
    patient_id:  str
    event_type:  str
    t_start:     datetime
    t_end:       datetime | None = None
    stay_start:  datetime | None = None
    stay_end:    datetime | None = None
    attributes:  dict[str, Any]  = Field(default_factory=dict)
    confidence:  float           = Field(default=1.0, ge=0.0, le=1.0)
    references:  dict[str, str]  = Field(default_factory=dict)
    version_id:  str             = "v1.0"


class EventOut(BaseModel):
    event_id:    str
    patient_id:  str
    event_type:  str
    t_start:     datetime
    t_end:       datetime | None
    stay_start:  datetime | None
    stay_end:    datetime | None
    attributes:  dict[str, Any]
    confidence:  float
    version_id:  str | None


@router.post("/", response_model=EventOut, status_code=201,
             summary="Klinisches Ereignis anlegen")
async def create_event(
    body: EventIn,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfügbar")

    from aion import ClinicalEvent

    stay_start = body.stay_start or body.t_start
    stay_end   = body.stay_end   or body.t_end or (body.t_start + timedelta(days=1))
    t_end      = body.t_end      or body.t_start

    event = ClinicalEvent(
        patient_id=body.patient_id,
        event_type=body.event_type,
        t_start=body.t_start,
        t_end=t_end,
        stay_start=stay_start,
        stay_end=stay_end,
        attributes=body.attributes,
        confidence=body.confidence,
    )
    eid = await request.app.state.store.add(event, current_user=user.sub)
    events_created.labels(type=body.event_type).inc()

    return EventOut(
        event_id=eid,
        patient_id=body.patient_id,
        event_type=body.event_type,
        t_start=body.t_start,
        t_end=t_end,
        stay_start=stay_start,
        stay_end=stay_end,
        attributes=body.attributes,
        confidence=body.confidence,
        version_id=body.version_id,
    )


@router.get("/{patient_id}", summary="Ereignisse eines Patienten abrufen")
async def get_events(
    patient_id: str,
    request: Request,
    t_from:      datetime | None = None,
    t_to:        datetime | None = None,
    type_filter: str | None = None,
    version_id:  str | None = None,
    limit:       int = 500,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfügbar")

    with query_duration.labels(endpoint="events_get").time():
        events = await request.app.state.store.find_by_patient(
            patient_id, t_from=t_from, t_to=t_to,
            type_filter=type_filter, version_id=version_id, limit=limit,
        )
    return [
        {
            "patient_id":  getattr(e, "patient_id",  ""),
            "event_type":  getattr(e, "event_type",   ""),
            "t_start":     getattr(e, "t_start",      None),
            "t_end":       getattr(e, "t_end",        None),
            "attributes":  getattr(e, "attributes",   {}),
            "confidence":  getattr(e, "confidence",   1.0),
        }
        for e in events
    ]


@router.get("/{patient_id}/refs/{event_id}",
            summary="Typisierte Referenzen eines Ereignisses (§4 ρ)")
async def get_references(
    patient_id: str,
    event_id: str,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfügbar")
    refs = await request.app.state.store.get_references(event_id)
    return {"event_id": event_id, "references": refs}

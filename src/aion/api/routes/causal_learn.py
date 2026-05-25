# aion/api/routes/causal_learn.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - AGPL-3.0-only OR LicenseRef-Iscad-Commercial
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from aion.api.auth_keycloak import require_user

router = APIRouter()


class PCRequest(BaseModel):
    event_types: list[str] | None = None
    threshold:   float = Field(default=0.05, ge=0.0, le=1.0)
    max_cond:    int   = Field(default=2,    ge=0,   le=4)
    bootstrap_b: int   = Field(default=30,   ge=5,   le=200)
    gamma_g:     float = Field(default=0.5,  ge=0.1, le=0.9)


@router.post("/learn", summary="PC-Algorithmus Kausalstrukturlernen (§15.3)")
async def learn(body: PCRequest, request: Request, user=Depends(require_user)):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    from aion.causal_learn.pc_algorithm import pc_algorithm
    # Alle Ereignisse laden (Limit 5000)
    all_events = []
    for pid_set_page in range(1):   # Erweiterbar auf echte Paginierung
        evs = await request.app.state.store.find_by_type(
            body.event_types[0] if body.event_types else "", limit=5000
        ) if body.event_types else []
        all_events.extend(evs)
    if not all_events and body.event_types:
        raise HTTPException(404, "Keine Ereignisse gefunden")
    g = pc_algorithm(all_events, body.event_types, body.threshold, body.max_cond)
    return g.to_dict()


@router.post("/bootstrap", summary="Bootstrap-Kantenkonfidenzen (§15.5)")
async def bootstrap(body: PCRequest, request: Request, user=Depends(require_user)):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    from aion.causal_learn.pc_algorithm import bootstrap_edge_confidence
    all_events = []
    if body.event_types:
        for t in body.event_types:
            evs = await request.app.state.store.find_by_type(t, limit=2000)
            all_events.extend(evs)
    g = bootstrap_edge_confidence(
        all_events, body.event_types,
        B=body.bootstrap_b, threshold=body.threshold, gamma_g=body.gamma_g
    )
    return g.to_dict()

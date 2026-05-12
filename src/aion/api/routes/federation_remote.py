# aion/api/routes/federation_remote.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – EUPL-1.2
"""Echte Multi-Institutionen-Föderierung über HTTPS (§20.7)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from aion.api.auth_keycloak import require_user, require_admin, ClaimsUser

router = APIRouter()


class RemoteInstitutionBody(BaseModel):
    institution_id: str
    name:           str
    endpoint_url:   str
    bearer_token:   str   = ""
    epsilon:        float = 1.0
    verify_ssl:     bool  = True


class FederatedQueryBody(BaseModel):
    formula: dict
    institution_ids: list[str] = []   # leer = alle


@router.post("/remote/register",
    summary="Remote-Institution registrieren (admin only)")
async def register_remote(
    body: RemoteInstitutionBody,
    request: Request,
    user: ClaimsUser = Depends(require_admin),
):
    """Fügt eine Partner-Institution zur Föderation hinzu."""
    from aion.federation.remote import RemoteInstitution, FederatedCoordinator

    if not hasattr(request.app.state, "federated_coordinator") or \
       request.app.state.federated_coordinator is None:
        request.app.state.federated_coordinator = FederatedCoordinator([])

    remote = RemoteInstitution(
        institution_id=body.institution_id,
        name=body.name,
        endpoint_url=body.endpoint_url,
        bearer_token=body.bearer_token,
        epsilon=body.epsilon,
        verify_ssl=body.verify_ssl,
    )
    request.app.state.federated_coordinator.add_remote(remote)

    # Persistenz: in Redis speichern (ohne Token aus Sicherheitsgründen)
    if request.app.state.redis is not None:
        try:
            import json as _json
            existing_raw = await request.app.state.redis.get("aion:federation:remotes")
            existing = _json.loads(existing_raw) if existing_raw else {}
            # Token verschlüsselt? Hier vereinfacht: nur ID/URL/eps speichern
            existing[body.institution_id] = {
                "name": body.name,
                "endpoint_url": body.endpoint_url,
                "epsilon": body.epsilon,
                "verify_ssl": body.verify_ssl,
            }
            await request.app.state.redis.set(
                "aion:federation:remotes", _json.dumps(existing)
            )
        except Exception:
            pass

    return {
        "registered": True,
        "remote":     remote.to_dict(),
        "n_remotes":  len(request.app.state.federated_coordinator.remotes),
    }


@router.delete("/remote/{institution_id}",
    summary="Remote-Institution entfernen (admin only)")
async def unregister_remote(
    institution_id: str,
    request: Request,
    user: ClaimsUser = Depends(require_admin),
):
    if not hasattr(request.app.state, "federated_coordinator") or \
       request.app.state.federated_coordinator is None:
        raise HTTPException(404, "Föderation nicht initialisiert")
    request.app.state.federated_coordinator.remove_remote(institution_id)
    return {"removed": institution_id}


@router.get("/remote/status",
    summary="Status aller Remote-Institutionen")
async def remote_status(
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if not hasattr(request.app.state, "federated_coordinator") or \
       request.app.state.federated_coordinator is None:
        return {"n_remotes": 0, "remotes": []}
    return request.app.state.federated_coordinator.status()


@router.get("/remote/health",
    summary="Erreichbarkeit aller Remote-Institutionen prüfen")
async def remote_health(
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if not hasattr(request.app.state, "federated_coordinator") or \
       request.app.state.federated_coordinator is None:
        return {"n_total": 0, "n_reachable": 0, "institutions": {}}
    return await request.app.state.federated_coordinator.health_check_all()


@router.post("/remote/query",
    summary="Föderierte Abfrage über echte Multi-Institutionen-API")
async def remote_query(
    body: FederatedQueryBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    """
    Sendet die Abfrage an alle (oder spezifizierten) Remote-Institutionen.
    Jede wendet eigene Local-DP an. Coordinator aggregiert nur die
    verrauschten Counts.
    """
    if not hasattr(request.app.state, "federated_coordinator") or \
       request.app.state.federated_coordinator is None:
        raise HTTPException(400, "Föderation nicht initialisiert – /remote/register aufrufen")

    coord = request.app.state.federated_coordinator
    if not coord.remotes:
        raise HTTPException(400, "Keine Remote-Institutionen registriert")

    # Optionale Filterung nach institution_ids
    if body.institution_ids:
        from aion.federation.remote import FederatedCoordinator
        filtered = [
            r for r_id, r in coord.remotes.items()
            if r_id in body.institution_ids
        ]
        sub_coord = FederatedCoordinator(filtered)
        result = await sub_coord.execute_query(body.formula)
    else:
        result = await coord.execute_query(body.formula)

    return result

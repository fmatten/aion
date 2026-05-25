# aion/api/routes/mllp.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""MLLP-Status und Dead-Letter-Queue Management (§HL7v2)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from aion.api.auth_keycloak import require_user, require_admin, ClaimsUser

router = APIRouter()


@router.get("/status", summary="MLLP-Queue Status")
async def mllp_status(
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.redis is None:
        raise HTTPException(503, "Redis nicht verfügbar")
    from aion.api.mllp_worker import mllp_status
    return await mllp_status(request.app.state.redis)


@router.get("/deadletter", summary="Dead-Letter-Queue anzeigen")
async def get_dlq(
    request: Request,
    limit: int = 10,
    user: ClaimsUser = Depends(require_admin),
):
    """Gibt die letzten N fehlgeschlagenen HL7v2-Nachrichten zurück."""
    if request.app.state.redis is None:
        raise HTTPException(503, "Redis nicht verfügbar")
    items = await request.app.state.redis.lrange(
        "aion:hl7v2:deadletter", 0, limit - 1
    )
    return {
        "deadletter_count": len(items),
        "messages": [
            {
                "index": i,
                "raw":   item.decode("latin-1", errors="replace")[:500],
            }
            for i, item in enumerate(items)
        ]
    }


@router.delete("/deadletter", summary="Dead-Letter-Queue leeren")
async def clear_dlq(
    request: Request,
    user: ClaimsUser = Depends(require_admin),
):
    """Leert die Dead-Letter-Queue (nur aion-admin)."""
    if request.app.state.redis is None:
        raise HTTPException(503, "Redis nicht verfügbar")
    deleted = await request.app.state.redis.delete("aion:hl7v2:deadletter")
    return {"deleted": bool(deleted), "message": "Dead-Letter-Queue geleert"}


@router.get("/processed", summary="Zuletzt verarbeitete Nachrichten")
async def get_processed(
    request: Request,
    limit: int = 5,
    user: ClaimsUser = Depends(require_user),
):
    """Ring-Buffer: letzte N erfolgreich verarbeitete HL7v2-Nachrichten."""
    if request.app.state.redis is None:
        raise HTTPException(503, "Redis nicht verfügbar")
    items = await request.app.state.redis.lrange(
        "aion:hl7v2:processed", 0, limit - 1
    )
    return {
        "count": len(items),
        "messages": [
            item.decode("latin-1", errors="replace")[:300]
            for item in items
        ]
    }

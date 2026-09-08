# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
# aion/api/routes/schema.py
# Copyright © 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0
"""
REST-Endpunkte für Schemaevolution (§18) und Typhierarchie (§3).
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from aion.api.auth_keycloak import require_user, ClaimsUser
from aion.api.metrics import schema_migrations
from aion.schema_evolution import SchemaMigration, SchemaOp
from aion.schema_registry import SchemaVersion

router = APIRouter()


# ── Typhierarchie ──────────────────────────────────────────────────────────

@router.get("/types", summary="Aktuelle Typhierarchie (§3)")
async def get_types(
    request: Request,
    version_id: str | None = None,
    user: ClaimsUser = Depends(require_user),
):
    registry = request.app.state.schema_registry
    version = (
        registry._versions.get(version_id)
        if version_id
        else registry.current()
    )
    if version is None:
        raise HTTPException(404, f"Version '{version_id}' nicht gefunden")

    result = {
        "version_id":  version.version_id,
        "t_begin":     version.t_begin.isoformat(),
        "description": version.description,
        "types": [],
        "edges": [],
    }
    if version.hierarchy is not None:
        try:
            result["types"] = list(version.hierarchy.all_types())
            result["edges"] = list(version.hierarchy.edges()) \
                if hasattr(version.hierarchy, "edges") else []
        except Exception:
            pass
    return result


# ── Versionsverwaltung ─────────────────────────────────────────────────────

@router.get("/versions", summary="Alle Schemaversionen (§18.1)")
async def list_versions(
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    registry = request.app.state.schema_registry
    return [
        {
            "version_id":  v.version_id,
            "t_begin":     v.t_begin.isoformat(),
            "t_end":       v.t_end.isoformat() if v.t_end else None,
            "description": v.description,
            "active":      v.t_end is None,
        }
        for v in sorted(registry._versions.values(), key=lambda x: x.t_begin)
    ]


class VersionIn(BaseModel):
    version_id:  str
    description: str
    t_begin:     datetime | None = None


@router.post("/versions", status_code=201, summary="Neue Schemaversion anlegen")
async def create_version(
    body: VersionIn,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if "aion-admin" not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Admins dürfen Versionen anlegen")
    registry = request.app.state.schema_registry
    if body.version_id in registry._versions:
        raise HTTPException(409, f"Version '{body.version_id}' existiert bereits")

    version = SchemaVersion(
        version_id=body.version_id,
        t_begin=body.t_begin or datetime.now(timezone.utc),
        t_end=None,
        description=body.description,
    )
    registry.activate_version(version)

    # In DB persistieren
    try:
        await registry.save_version(version, request.app.state.store._pool)
    except Exception as exc:
        # Speicher-Fehler nicht hart blocken – Version in Memory bleibt aktiv
        pass

    return {"created": True, "version_id": body.version_id}


# ── Migrationen ────────────────────────────────────────────────────────────

class OpIn(BaseModel):
    op:     str
    params: dict = Field(default_factory=dict)


class MigrationIn(BaseModel):
    from_version: str
    to_version:   str
    operations:   list[OpIn]


@router.post("/migrations", status_code=201,
             summary="Migration registrieren (§18.2)")
async def register_migration(
    body: MigrationIn,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if "aion-admin" not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Admins dürfen Migrationen registrieren")

    mig = SchemaMigration(
        from_version=body.from_version,
        to_version=body.to_version,
        operations=[SchemaOp(op=o.op, params=o.params) for o in body.operations],
    )
    compat = {
        "forward":  mig.is_forward_compatible(),
        "backward": mig.is_backward_compatible(),
    }
    registry = request.app.state.schema_registry
    registry.add_migration(mig)

    try:
        await registry.save_migration(mig, request.app.state.store._pool)
    except Exception:
        pass

    return {
        "registered": True,
        "from_version": body.from_version,
        "to_version":   body.to_version,
        "compatibility": compat,
    }


@router.get("/migrations", summary="Alle registrierten Migrationen")
async def list_migrations(
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    registry = request.app.state.schema_registry
    return [m.to_dict() for m in registry._migrations]


class RunMigrationIn(BaseModel):
    from_version: str
    to_version:   str
    dry_run:      bool = False


@router.post("/migrations/run",
             summary="Batch-Migration ausführen (§18.4)")
async def run_migration(
    body: RunMigrationIn,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if "aion-admin" not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Nur Admins dürfen Migrationen ausführen")

    registry = request.app.state.schema_registry
    store    = request.app.state.store

    # Alle Ereignisse der Quellversion laden
    async with store._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id, patient_id, type_id, t_begin, t_end, "
            "confidence, attributes FROM event WHERE version_id = $1",
            body.from_version,
        )

    results = {"migrated": 0, "rejected": 0, "dry_run": body.dry_run}
    path = registry._migration_path(body.from_version, body.to_version)

    for row in rows:
        # Minimales Event-Objekt
        class _E:
            pass
        e = _E()
        e.patient_id  = row["patient_id"]  # type: ignore
        e.event_type  = row["type_id"]     # type: ignore
        e.t_start     = row["t_begin"]     # type: ignore
        e.t_end       = row.get("t_end")   # type: ignore
        e.confidence  = float(row.get("confidence", 1.0))  # type: ignore
        attrs = row.get("attributes") or {}
        e.attributes  = attrs if isinstance(attrs, dict) else json.loads(attrs)  # type: ignore

        migrated = e
        for mig in path:
            migrated = mig.migrate_event(migrated)
            if migrated is None:
                break

        eid = str(row["event_id"])
        if migrated is None:
            results["rejected"] += 1
            if not body.dry_run:
                await store.log_migration_rejected(
                    eid, body.from_version, body.to_version
                )
        else:
            results["migrated"] += 1
            if not body.dry_run:
                await store.update_event_version(
                    event_id=eid,
                    new_type_id=getattr(migrated, "event_type", row["type_id"]),
                    new_attributes=getattr(migrated, "attributes", {}),
                    new_version_id=body.to_version,
                    from_version=body.from_version,
                )

    schema_migrations.labels(
        from_version=body.from_version,
        to_version=body.to_version,
        status="completed" if not body.dry_run else "dry_run",
    ).inc()

    return results

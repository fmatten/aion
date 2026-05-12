# aion/persist/postgres_store.py
# Copyright © 2026 Friedhelm Matten / ISCaD GmbH – EUPL-1.2
from __future__ import annotations
import json, uuid, logging
from datetime import datetime, timezone
from typing import Any

try:
    import asyncpg
except ImportError:
    asyncpg = None

log = logging.getLogger(__name__)


def _utc(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _row_to_event(row):
    attrs = row.get("attributes") or {}
    if isinstance(attrs, str):
        attrs = json.loads(attrs)

    t_start = row["t_begin"]
    t_end   = row.get("t_end") or t_start
    # Echtes ClinicalEvent bauen (benoetigt event_id fuer FHIR-Export)
    try:
        from aion import ClinicalEvent
        ev = ClinicalEvent(
            patient_id=row["patient_id"],
            event_type=row["type_id"],
            t_start=t_start,
            t_end=t_end,
            stay_start=t_start,
            stay_end=t_end,
            attributes=attrs,
            confidence=float(row.get("confidence", 1.0)),
        )
        # event_id aus DB uebernehmen (UUID-String)
        object.__setattr__(ev, "event_id", str(row["event_id"]))
        return ev
    except Exception:
        # Fallback: _E-Objekt mit event_id
        class _E: pass
        e = _E()
        e.patient_id = row["patient_id"]
        e.event_type = row["type_id"]
        e.event_id   = str(row["event_id"])   # NEU: event_id ergaenzt
        e.t_start    = t_start
        e.t_end      = t_end
        e.attributes = attrs
        e.confidence = float(row.get("confidence", 1.0))
        e.version_id = row.get("version_id", "v1.0")
        return e


class PostgresEventStore:
    def __init__(self, dsn: str, pool_min: int = 2, pool_max: int = 10):
        if asyncpg is None:
            raise ImportError("asyncpg nicht installiert")
        self._dsn = dsn.replace("+asyncpg", "")
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool = None

    async def __aenter__(self):
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=self._pool_min,
            max_size=self._pool_max, command_timeout=30,
        )
        log.info("PostgresEventStore: Pool geöffnet (%s)", self._dsn.split("@")[-1])
        return self

    async def __aexit__(self, *_):
        if self._pool:
            await self._pool.close()

    async def add(self, event, current_user: str = "api") -> str:
        eid   = str(uuid.uuid4())
        attrs = json.dumps(getattr(event, "attributes", {}) or {})
        t_begin = _utc(getattr(event, "t_start", None))
        t_end   = _utc(getattr(event, "t_end",   None))
        vid     = getattr(event, "version_id", "v1.0") or "v1.0"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO event
                        (event_id, patient_id, type_id, t_begin, t_end,
                         confidence, attributes, version_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    eid,
                    str(event.patient_id),
                    str(getattr(event, "event_type", "unknown")),
                    t_begin,
                    t_end,
                    float(getattr(event, "confidence", 1.0)),
                    attrs,
                    vid,
                )
                for ref_id, rel_type in (getattr(event, "references", None) or {}).items():
                    await conn.execute(
                        """
                        INSERT INTO event_reference (event_id, ref_id, rel_type)
                        VALUES ($1,$2,$3) ON CONFLICT DO NOTHING
                        """,
                        eid, ref_id, rel_type,
                    )
        log.info("add: event_id=%s type=%s patient=%s",
                 eid[:8], getattr(event, "event_type", "?"), event.patient_id)
        return eid

    async def add_many(self, events: list, current_user: str = "api") -> list[str]:
        ids = []
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    eid = str(uuid.uuid4())
                    await conn.execute(
                        """
                        INSERT INTO event
                            (event_id, patient_id, type_id, t_begin, t_end,
                             confidence, attributes, version_id)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                        """,
                        eid,
                        str(event.patient_id),
                        str(getattr(event, "event_type", "unknown")),
                        _utc(getattr(event, "t_start", None)),
                        _utc(getattr(event, "t_end",   None)),
                        float(getattr(event, "confidence", 1.0)),
                        json.dumps(getattr(event, "attributes", {}) or {}),
                        getattr(event, "version_id", "v1.0") or "v1.0",
                    )
                    ids.append(eid)
        return ids

    async def find_by_patient(self, patient_id, t_from=None, t_to=None,
                               type_filter=None, version_id=None, limit=1000):
        q = "SELECT * FROM event WHERE patient_id = $1"
        args = [patient_id]
        if t_from:
            args.append(_utc(t_from)); q += f" AND t_begin >= ${len(args)}"
        if t_to:
            args.append(_utc(t_to));   q += f" AND t_begin <= ${len(args)}"
        if type_filter:
            args.append(type_filter);  q += f" AND type_id = ${len(args)}"
        if version_id:
            args.append(version_id);   q += f" AND version_id = ${len(args)}"
        args.append(limit);            q += f" ORDER BY t_begin LIMIT ${len(args)}"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q, *args)
        return [_row_to_event(dict(r)) for r in rows]

    async def get(self, event_id):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM event WHERE event_id = $1", event_id)
        return _row_to_event(dict(row)) if row else None

    async def get_references(self, event_id):
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT ref_id, rel_type FROM event_reference WHERE event_id = $1",
                event_id)
        return [{"ref_id": str(r["ref_id"]), "rel_type": r["rel_type"]} for r in rows]

    async def find_by_type(self, type_id, version_id=None, limit=500):
        q = "SELECT * FROM event WHERE type_id = $1"
        args = [type_id]
        if version_id:
            args.append(version_id); q += f" AND version_id = ${len(args)}"
        args.append(limit);          q += f" ORDER BY t_begin LIMIT ${len(args)}"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(q, *args)
        return [_row_to_event(dict(r)) for r in rows]

    async def update_event_version(self, event_id, new_type_id, new_attributes,
                                    new_version_id, from_version, current_user="migration"):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE event SET type_id=$1, attributes=$2, "
                    "version_id=$3, updated_at=now() WHERE event_id=$4",
                    new_type_id, json.dumps(new_attributes), new_version_id, event_id,
                )
                await conn.execute(
                    "INSERT INTO event_migration "
                    "(event_id, from_version, to_version, status) "
                    "VALUES ($1,$2,$3,'migrated') "
                    "ON CONFLICT (event_id, from_version, to_version) "
                    "DO UPDATE SET status='migrated', migrated_at=now()",
                    event_id, from_version, new_version_id,
                )

    async def log_migration_rejected(self, event_id, from_version, to_version):
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO event_migration "
                "(event_id, from_version, to_version, status) "
                "VALUES ($1,$2,$3,'rejected') ON CONFLICT DO NOTHING",
                event_id, from_version, to_version,
            )

    async def health(self):
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT count(*) AS cnt FROM event")
        return {"status": "ok", "event_count": row["cnt"],
                "pool_size": self._pool.get_size()}

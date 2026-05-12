"""VersionedSchemaRegistry §18.1/18.5 – aion.schema_registry"""
from __future__ import annotations
import json, logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from aion.schema_evolution import SchemaMigration, SchemaOp

log = logging.getLogger(__name__)

@dataclass
class SchemaVersion:
    version_id:str; t_begin:datetime; t_end:Any; description:str; hierarchy:Any=field(default=None,repr=False)

class VersionedSchemaRegistry:
    def __init__(self): self._versions={}; self._migrations=[]

    def register(self,v): self._versions[v.version_id]=v

    def current(self):
        act=[v for v in self._versions.values() if v.t_end is None]
        if not act: raise RuntimeError("Keine aktive Schemaversion")
        return max(act,key=lambda v:v.t_begin)

    def for_event_time(self,t):
        for v in sorted(self._versions.values(),key=lambda x:x.t_begin,reverse=True):
            if v.t_begin<=t and (v.t_end is None or t<v.t_end): return v
        return self.current()

    def activate_version(self,v):
        try: self.current().t_end=v.t_begin
        except RuntimeError: pass
        self.register(v)

    def add_migration(self,m): self._migrations.append(m)

    def migrate_event(self,event,target):
        if event is None: return None
        src=self.for_event_time(getattr(event,"t_start",datetime.now(timezone.utc))).version_id
        if src==target: return event
        try: path=self._migration_path(src,target)
        except ValueError as e: log.error(str(e)); return None
        e=event
        for m in path:
            e=m.migrate_event(e)
            if e is None: return None
        return e

    def _migration_path(self,fv,tv):
        adj={m.from_version:m for m in self._migrations}
        q=deque([(fv,[])]); vis=set()
        while q:
            cur,path=q.popleft()
            if cur==tv: return path
            if cur in vis: continue
            vis.add(cur)
            if cur in adj:
                m=adj[cur]; q.append((m.to_version,path+[m]))
        raise ValueError(f"Kein Migrationspfad '{fv}' → '{tv}'")

    async def save_version(self,v,pool):
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO schema_version (version_id,t_begin,t_end,description) VALUES ($1,$2,$3,$4) ON CONFLICT (version_id) DO UPDATE SET t_end=$3,description=$4",v.version_id,v.t_begin,v.t_end,v.description)

    async def save_migration(self,m,pool):
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO schema_migration (from_version,to_version,op_seq) VALUES ($1,$2,$3)",m.from_version,m.to_version,json.dumps([o.to_dict() for o in m.operations]))

    async def load_all(self,pool):
        async with pool.acquire() as conn:
            vrows=await conn.fetch("SELECT * FROM schema_version ORDER BY t_begin")
            mrows=await conn.fetch("SELECT * FROM schema_migration ORDER BY id")
        for r in vrows:
            self.register(SchemaVersion(r["version_id"],r["t_begin"],r["t_end"],r["description"] or ""))
        for r in mrows:
            d=r["op_seq"]; ops=json.loads(d) if isinstance(d,str) else d
            self._migrations.append(SchemaMigration(r["from_version"],r["to_version"],[SchemaOp.from_dict(o) for o in ops]))

# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
# AION — Algebraic Interval Ontology for Clinical Networks
"""
aion.schema.evolution
=====================
AION §16: Schema Evolution.

Versioned type system (H_T^(v))_{v ∈ V} with:
  - Seven elementary schema change operations
  - Compatibility conditions (forward / backward / bidirectional)
  - Migration function μ_{v→v'}: E^(v) → E^(v') ∪ {⊥}
  - Versioned query model φ^(v)(p)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from ..core.types import TypeHierarchy, AttributeSchema, AttributeDef, Obligateness
from ..core.event import ClinicalEvent, EventSet


# ── SchemaVersion ─────────────────────────────────────────────────────────────

@dataclass
class SchemaVersion:
    """
    AION §16.1: One version v ∈ V with validity interval [t_v^B, t_v^E].
    """
    version_id:  str
    t_begin:     datetime.datetime
    t_end:       Optional[datetime.datetime]   # None = current version
    description: str = ""

    @property
    def is_current(self) -> bool:
        return self.t_end is None

    def contains(self, t: datetime.datetime) -> bool:
        if t < self.t_begin:
            return False
        if self.t_end is not None and t >= self.t_end:
            return False
        return True

    def __repr__(self) -> str:
        end = self.t_end.strftime("%Y-%m-%d") if self.t_end else "now"
        return f"SchemaVersion({self.version_id!r}, {self.t_begin.strftime('%Y-%m-%d')}–{end})"


# ── Schema Change Operations (AION §16.2) ─────────────────────────────────────

class OpKind(str, Enum):
    ADD_TYPE    = "AddType"
    REM_TYPE    = "RemType"
    REN_TYPE    = "RenType"
    MOVE_TYPE   = "MoveType"
    ADD_ATTR    = "AddAttr"
    REM_ATTR    = "RemAttr"
    CHG_ATTR    = "ChgAttr"


@dataclass(frozen=True)
class SchemaOp:
    """
    AION §16.2: Elementary schema change operation.
    """
    kind:        OpKind
    type_name:   str
    # Optional fields depending on op kind
    parent:      Optional[str]          = None   # AddType, MoveType
    new_name:    Optional[str]          = None   # RenType
    attr_name:   Optional[str]          = None   # AddAttr, RemAttr, ChgAttr
    attr_def:    Optional[AttributeDef] = None   # AddAttr, ChgAttr

    def __repr__(self) -> str:
        return f"SchemaOp({self.kind.value}, {self.type_name!r})"


# ── Compatibility ─────────────────────────────────────────────────────────────

class Compatibility(str, Enum):
    FORWARD       = "forward"        # old events valid under new schema
    BACKWARD      = "backward"       # new events valid under old schema
    BIDIRECTIONAL = "bidirectional"  # both
    BREAKING      = "breaking"       # neither


def op_compatibility(op: SchemaOp) -> Compatibility:
    """
    AION §16.3: Determine compatibility level of a single schema op.
    """
    if op.kind == OpKind.ADD_TYPE:
        return Compatibility.FORWARD
    if op.kind == OpKind.ADD_ATTR:
        if op.attr_def and op.attr_def.obligateness == Obligateness.OPTIONAL:
            return Compatibility.FORWARD
        return Compatibility.BREAKING   # required attr = breaking
    if op.kind in (OpKind.REM_TYPE, OpKind.REM_ATTR):
        return Compatibility.BREAKING
    if op.kind == OpKind.CHG_ATTR:
        return Compatibility.BREAKING   # conservative; caller may override
    if op.kind in (OpKind.REN_TYPE, OpKind.MOVE_TYPE):
        return Compatibility.BREAKING   # requires migration function
    return Compatibility.BREAKING


# ── SchemaMigration ───────────────────────────────────────────────────────────

@dataclass
class MigrationRecord:
    """Record of a single event migration."""
    event_id:     str
    from_version: str
    to_version:   str
    status:       str   # "migrated" | "rejected" | "pending"
    notes:        str = ""


class SchemaMigration:
    """
    AION §16.2: Migration from version v to v'.

    Δ_{v→v'} = sequence of SchemaOps.
    μ_{v→v'}: E^(v) → E^(v') ∪ {⊥}  — migration function.

    Migration invariants (AION §16.4):
      1. Type consistency    : type^(v')(μ(e)) ∈ T^(v')
      2. Time invariance     : t^B(μ(e)) = t^B(e), t^E(μ(e)) = t^E(e)
      3. Patient invariance  : p(μ(e)) = p(e)
      4. Attribute preservation: unchanged attrs keep their values
    """

    def __init__(
        self,
        from_version: str,
        to_version:   str,
        ops:          list[SchemaOp],
    ) -> None:
        self.from_version = from_version
        self.to_version   = to_version
        self.ops          = ops
        self._field_maps:  dict[str, dict[str, str]] = {}   # type → {old_attr → new_attr}
        self._type_renames: dict[str, str] = {}              # old_name → new_name
        self._records:     list[MigrationRecord] = []

    def set_field_map(
        self,
        type_name: str,
        old_attr:  str,
        new_attr:  str,
    ) -> None:
        """Register attribute rename for migration."""
        self._field_maps.setdefault(type_name, {})[old_attr] = new_attr

    def set_type_rename(self, old_name: str, new_name: str) -> None:
        """Register type rename for migration."""
        self._type_renames[old_name] = new_name

    @property
    def compatibility(self) -> Compatibility:
        """Overall compatibility = most restrictive of all ops."""
        comps = [op_compatibility(op) for op in self.ops]
        if Compatibility.BREAKING in comps:
            return Compatibility.BREAKING
        if Compatibility.FORWARD in comps and Compatibility.BACKWARD in comps:
            return Compatibility.BIDIRECTIONAL
        return comps[0] if comps else Compatibility.BIDIRECTIONAL

    def migrate_event(
        self,
        event: ClinicalEvent,
        target_hierarchy: TypeHierarchy,
    ) -> tuple[Optional[ClinicalEvent], MigrationRecord]:
        """
        μ_{v→v'}(e): Migrate one event to the new schema.
        Returns (migrated_event | None, record).
        """
        # 1. Resolve type name
        new_type = self._type_renames.get(event.type, event.type)

        # 2. Check type exists in target hierarchy
        if new_type not in target_hierarchy:
            rec = MigrationRecord(
                event_id=event.id,
                from_version=self.from_version,
                to_version=self.to_version,
                status="rejected",
                notes=f"Type {new_type!r} not in target hierarchy",
            )
            self._records.append(rec)
            return None, rec

        # 3. Migrate attributes
        new_attrs = dict(event.attributes)
        field_map = self._field_maps.get(event.type, {})
        for old_attr, new_attr in field_map.items():
            if old_attr in new_attrs:
                new_attrs[new_attr] = new_attrs.pop(old_attr)

        # 4. Remove attrs that no longer exist in new schema
        target_schema = target_hierarchy.effective_schema(new_type)
        valid_names   = {a.name for a in target_schema.all_attrs}
        for removed_op in (op for op in self.ops if op.kind == OpKind.REM_ATTR):
            if removed_op.type_name == event.type and removed_op.attr_name in new_attrs:
                new_attrs.pop(removed_op.attr_name, None)

        # 5. Build migrated event (preserving time + patient invariants)
        migrated = ClinicalEvent(
            patient_id=event.patient_id,    # patient invariance
            stay_id=event.stay_id,
            type=new_type,
            tau=event.tau,                  # time invariance
            attributes=new_attrs,
            refs=event.refs,
            confidence=event.confidence,
        )

        rec = MigrationRecord(
            event_id=event.id,
            from_version=self.from_version,
            to_version=self.to_version,
            status="migrated",
        )
        self._records.append(rec)
        return migrated, rec

    def migrate_event_set(
        self,
        event_set:        EventSet,
        target_hierarchy: TypeHierarchy,
    ) -> tuple[EventSet, list[MigrationRecord]]:
        """
        Migrate all events in *event_set* to the new schema.
        Returns (migrated_set, records).
        """
        migrated_es = EventSet(hierarchy=target_hierarchy)
        records:    list[MigrationRecord] = []

        for event in event_set.all_events:
            migrated, rec = self.migrate_event(event, target_hierarchy)
            records.append(rec)
            if migrated is not None:
                try:
                    migrated_es.add(migrated)
                except ValueError:
                    rec.status = "rejected"
                    rec.notes  = "Duplicate ID after migration"

        return migrated_es, records

    @property
    def records(self) -> list[MigrationRecord]:
        return list(self._records)

    def migration_summary(self) -> dict[str, int]:
        counts = {"migrated": 0, "rejected": 0, "pending": 0}
        for r in self._records:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def __repr__(self) -> str:
        return (
            f"SchemaMigration({self.from_version!r}→{self.to_version!r}, "
            f"{len(self.ops)} ops, "
            f"compat={self.compatibility.value})"
        )


# ── VersionedTypeSystem ───────────────────────────────────────────────────────

class VersionedTypeSystem:
    """
    AION §16.1: (H_T^(v))_{v ∈ V} — family of type hierarchies.

    Each version covers a disjoint validity interval.
    Versions are linearly ordered: v_0, v_1, v_2, ...
    """

    def __init__(self) -> None:
        self._versions:    list[SchemaVersion]          = []
        self._hierarchies: dict[str, TypeHierarchy]    = {}
        self._migrations:  list[SchemaMigration]       = []

    def add_version(
        self,
        version_id:  str,
        t_begin:     datetime.datetime,
        t_end:       Optional[datetime.datetime],
        hierarchy:   TypeHierarchy,
        description: str = "",
    ) -> SchemaVersion:
        """Register a new schema version."""
        sv = SchemaVersion(version_id, t_begin, t_end, description)
        self._versions.append(sv)
        self._hierarchies[version_id] = hierarchy
        return sv

    def add_migration(self, migration: SchemaMigration) -> None:
        self._migrations.append(migration)

    def hierarchy_at(self, t: datetime.datetime) -> Optional[TypeHierarchy]:
        """Return the type hierarchy valid at time t."""
        for sv in self._versions:
            if sv.contains(t):
                return self._hierarchies.get(sv.version_id)
        return None

    def hierarchy_for(self, version_id: str) -> Optional[TypeHierarchy]:
        return self._hierarchies.get(version_id)

    def current_hierarchy(self) -> Optional[TypeHierarchy]:
        for sv in reversed(self._versions):
            if sv.is_current:
                return self._hierarchies.get(sv.version_id)
        return None

    def version_for_event(self, event: ClinicalEvent) -> Optional[SchemaVersion]:
        return next(
            (sv for sv in self._versions if sv.contains(event.tau.start)),
            None,
        )

    def migrate(
        self,
        from_vid: str,
        to_vid:   str,
        event_set: EventSet,
    ) -> tuple[EventSet, list[MigrationRecord]]:
        """
        Run migration from from_vid to to_vid over event_set.
        Looks up the registered SchemaMigration.
        """
        migration = next(
            (m for m in self._migrations
             if m.from_version == from_vid and m.to_version == to_vid),
            None,
        )
        if migration is None:
            raise KeyError(
                f"No migration registered for {from_vid!r} → {to_vid!r}"
            )
        target_h = self._hierarchies.get(to_vid)
        if target_h is None:
            raise KeyError(f"No hierarchy for version {to_vid!r}")
        return migration.migrate_event_set(event_set, target_h)

    @property
    def versions(self) -> list[SchemaVersion]:
        return list(self._versions)

    def __len__(self) -> int:
        return len(self._versions)

    def __repr__(self) -> str:
        return f"VersionedTypeSystem({len(self)} versions)"

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""TypeHierarchy — Implementierung von H = (T ∪ {⊤}, ≺) als DAG.

Stdlib-only (außer optional PyYAML für Schema-Import).
Eager-Validation, LRU-Cache für transitive Hülle, Multi-Inheritance optional.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Optional, Iterable, Any
import json


class TypeHierarchyError(Exception):
    """Verletzung der Wohlgeformtheit der Typ-Hierarchie."""


@dataclass
class TypeNode:
    """Knoten in der Typ-Hierarchie.

    Attributes:
        name:           eindeutiger Bezeichner des Typs
        parent:         Name des direkten Parent-Typs (None ⇒ Kind von ⊤)
        fhir_resource:  optionales Mapping auf FHIR-Ressource (z. B. "Observation")
        attributes:     Schema der erlaubten Attribute α: {name: spec_dict}
        description:    freier Text für Domain-Experten
    """
    name: str
    parent: Optional[str] = None
    fhir_resource: Optional[str] = None
    attributes: dict[str, dict] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class TypeHierarchy:
    """Gerichteter azyklischer Graph (DAG) für die Typ-Hierarchie.

    Mathematisches Modell:
        H = (T ∪ {⊤}, ≺) mit:
            T:  Menge der klinischen Ereignistypen
            ⊤:  Wurzel ("klinisches Ereignis")
            ≺:  irreflexive, transitive Relation (Subtyp)

    Implementierung:
        Zwei Adjazenzlisten (parents, children) für O(1)-Zugriff.
        Transitive Hülle via DFS, gecacht mit functools.lru_cache.
        Eager-Zyklusprüfung beim Hinzufügen von Kanten.
    """

    TOP = "⊤"

    def __init__(self) -> None:
        self._parents: dict[str, set[str]] = {self.TOP: set()}
        self._children: dict[str, set[str]] = {self.TOP: set()}
        self._nodes: dict[str, TypeNode] = {self.TOP: TypeNode(name=self.TOP)}

    # ────────────────────────────────────────────────────────────────
    # Mutation
    # ────────────────────────────────────────────────────────────────
    def add_type(
        self,
        name: str,
        parent: Optional[str] = None,
        *,
        fhir_resource: Optional[str] = None,
        attributes: Optional[dict] = None,
        description: str = "",
    ) -> TypeNode:
        """Fügt einen neuen Typ als Subtyp von `parent` (default: ⊤) hinzu.

        Eager-Validation: prüft Existenz des Parents. Da `name` neu ist,
        kann kein Zyklus entstehen.
        """
        if not name or name == self.TOP:
            raise TypeHierarchyError(f"Ungültiger Typname: {name!r}")
        if name in self._nodes:
            raise TypeHierarchyError(f"Typ '{name}' existiert bereits.")
        parent = parent or self.TOP
        if parent not in self._nodes:
            raise TypeHierarchyError(f"Parent '{parent}' nicht vorhanden.")

        node = TypeNode(
            name=name,
            parent=parent if parent != self.TOP else None,
            fhir_resource=fhir_resource,
            attributes=attributes or {},
            description=description,
        )
        self._nodes[name] = node
        self._parents[name] = {parent}
        self._children[name] = set()
        self._children[parent].add(name)
        self._invalidate_cache()
        return node

    def add_edge(self, child: str, parent: str) -> None:
        """Multi-Inheritance: zusätzliche Parent-Kante. Zyklusprüfung zwingend."""
        if child not in self._nodes:
            raise TypeHierarchyError(f"Child '{child}' nicht vorhanden.")
        if parent not in self._nodes:
            raise TypeHierarchyError(f"Parent '{parent}' nicht vorhanden.")
        if child == parent:
            raise TypeHierarchyError("Selbstreferenz nicht erlaubt.")
        # Würde child ≺* parent gelten, entstünde mit (parent → child) ein Zyklus
        if self.is_subtype(parent, child):
            raise TypeHierarchyError(
                f"Kante {parent}→{child} würde Zyklus erzeugen."
            )
        self._parents[child].add(parent)
        self._children[parent].add(child)
        self._invalidate_cache()

    def remove_type(self, name: str, *, reparent_to_top: bool = True) -> None:
        """Entfernt einen Typ. Kinder werden optional zu ⊤ umgehängt."""
        if name == self.TOP:
            raise TypeHierarchyError("Wurzel ⊤ kann nicht entfernt werden.")
        if name not in self._nodes:
            raise TypeHierarchyError(f"Typ '{name}' nicht vorhanden.")

        for child in list(self._children[name]):
            self._parents[child].discard(name)
            if not self._parents[child] and reparent_to_top:
                self._parents[child].add(self.TOP)
                self._children[self.TOP].add(child)
        for p in self._parents[name]:
            self._children[p].discard(name)

        del self._nodes[name]
        del self._parents[name]
        del self._children[name]
        self._invalidate_cache()

    # ────────────────────────────────────────────────────────────────
    # Queries
    # ────────────────────────────────────────────────────────────────
    def has(self, name: str) -> bool:
        return name in self._nodes

    def get(self, name: str) -> TypeNode:
        if name not in self._nodes:
            raise TypeHierarchyError(f"Typ '{name}' nicht vorhanden.")
        return self._nodes[name]

    def all_types(self, *, include_top: bool = False) -> list[str]:
        return [n for n in self._nodes if include_top or n != self.TOP]

    def parents_of(self, name: str) -> set[str]:
        return set(self._parents.get(name, set()))

    def children_of(self, name: str) -> set[str]:
        return set(self._children.get(name, set()))

    @lru_cache(maxsize=4096)
    def ancestors(self, name: str) -> frozenset[str]:
        """Transitive Hülle ≺* (alle Vorfahren ohne `name` selbst)."""
        if name not in self._nodes:
            return frozenset()
        seen: set[str] = set()
        stack: list[str] = list(self._parents[name])
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self._parents.get(n, set()))
        return frozenset(seen)

    @lru_cache(maxsize=4096)
    def descendants(self, name: str) -> frozenset[str]:
        """Alle Nachfahren (transitiv, ohne `name` selbst)."""
        if name not in self._nodes:
            return frozenset()
        seen: set[str] = set()
        stack: list[str] = list(self._children[name])
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self._children.get(n, set()))
        return frozenset(seen)

    @lru_cache(maxsize=8192)
    def is_subtype(self, child: str, parent: str) -> bool:
        """Prüft child ≺* parent (reflexiv-transitive Subtyp-Beziehung)."""
        if child == parent:
            return True
        return parent in self.ancestors(child)

    def depth(self, name: str) -> int:
        """Maximale Distanz zu ⊤."""
        if name == self.TOP:
            return 0
        return 1 + max((self.depth(p) for p in self._parents[name]), default=-1)

    def is_acyclic(self) -> bool:
        """Sicherheitsnetz — sollte invariant True sein."""
        try:
            for n in self._nodes:
                self.ancestors(n)
            return True
        except RecursionError:
            return False

    # ────────────────────────────────────────────────────────────────
    # Serialisierung
    # ────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "types": [
                {
                    "name": n.name,
                    "parent": n.parent,
                    "fhir": n.fhir_resource,
                    "attributes": n.attributes,
                    "description": n.description,
                }
                for k, n in self._nodes.items()
                if k != self.TOP
            ]
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, schema: dict) -> "TypeHierarchy":
        h = cls()
        for entry in cls._topo_sort(schema.get("types", [])):
            h.add_type(
                name=entry["name"],
                parent=entry.get("parent"),
                fhir_resource=entry.get("fhir"),
                attributes=entry.get("attributes", {}) or {},
                description=entry.get("description", "") or "",
            )
        return h

    @classmethod
    def from_yaml(cls, path: str) -> "TypeHierarchy":
        try:
            import yaml
        except ImportError as e:
            raise ImportError(
                "PyYAML wird zum Lesen von YAML-Schemata benötigt: pip install PyYAML"
            ) from e
        with open(path, "r", encoding="utf-8") as f:
            schema = yaml.safe_load(f)
        return cls.from_dict(schema)

    @classmethod
    def from_json(cls, path: str) -> "TypeHierarchy":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @staticmethod
    def _topo_sort(entries: list[dict]) -> list[dict]:
        """Bring Typen in topologische Reihenfolge (Parents zuerst)."""
        by_name = {e["name"]: e for e in entries}
        visited: set[str] = set()
        result: list[dict] = []

        def visit(name: str) -> None:
            if name in visited or name not in by_name:
                return
            visited.add(name)
            p = by_name[name].get("parent")
            if p:
                visit(p)
            result.append(by_name[name])

        for e in entries:
            visit(e["name"])
        return result

    # ────────────────────────────────────────────────────────────────
    # Validation
    # ────────────────────────────────────────────────────────────────
    def validate_attribute(self, type_name: str, attr_name: str, value: Any) -> bool:
        """Prüft, ob `value` zum Wertebereich des Attributs passt.

        Auch Vorfahren-Attribute werden berücksichtigt (Vererbung).
        """
        if type_name not in self._nodes:
            return False
        # Vorfahren durchsuchen
        for t in [type_name, *self.ancestors(type_name)]:
            if t == self.TOP:
                continue
            spec = self._nodes[t].attributes.get(attr_name)
            if spec is None:
                continue
            return self._matches_spec(value, spec)
        return False  # Attribut nicht im Schema

    @staticmethod
    def _matches_spec(value: Any, spec: dict) -> bool:
        t = spec.get("type")
        if t == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                return False
        elif t == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
        elif t == "string":
            if not isinstance(value, str):
                return False
        elif t == "bool":
            if not isinstance(value, bool):
                return False
        elif t == "enum":
            return value in (spec.get("values") or [])
        # Range-Check
        rng = spec.get("range")
        if rng and isinstance(value, (int, float)):
            lo, hi = rng
            if not (lo <= value <= hi):
                return False
        return True

    # ────────────────────────────────────────────────────────────────
    # Internal
    # ────────────────────────────────────────────────────────────────
    def _invalidate_cache(self) -> None:
        self.is_subtype.cache_clear()
        self.ancestors.cache_clear()
        self.descendants.cache_clear()

    def __len__(self) -> int:
        return len(self._nodes) - 1  # ⊤ nicht mitzählen

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def __repr__(self) -> str:
        return f"TypeHierarchy(types={len(self)})"

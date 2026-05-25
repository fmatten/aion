# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Vereinfachte Typ-Erstellung: Builder, Decorator, globales Registry.

Drei komplementäre Wege zur Typ-Definition:

1. Programmatic API (TypeHierarchy.add_type) - direkt
2. Builder mit Fluent-API (TypeBuilder) - lesbarer Code
3. Decorator (@aion_type) - zur Klassen-Registrierung
4. YAML/JSON-Schemata - für Domain-Experten ohne Python-Kenntnisse
"""
from __future__ import annotations

from dataclasses import is_dataclass, fields
from typing import Optional, Any

from aion.core.types import TypeHierarchy, TypeNode


class TypeBuilder:
    """Fluent-API zum bequemen Hinzufügen von Typen.

    Beispiel:
        h = TypeHierarchy()
        (TypeBuilder(h, "Sepsis")
            .under("Diagnose")
            .fhir("Condition")
            .attr("sofa_score", type="int", range=[0, 24])
            .attr("lactate", type="float", unit="mmol/l")
            .describe("Sepsis nach Sepsis-3-Definition")
            .build())
    """

    def __init__(self, hierarchy: TypeHierarchy, name: str) -> None:
        self._h = hierarchy
        self._name = name
        self._parent: Optional[str] = None
        self._fhir: Optional[str] = None
        self._attrs: dict[str, dict] = {}
        self._desc: str = ""

    def under(self, parent: str) -> "TypeBuilder":
        self._parent = parent
        return self

    def fhir(self, resource: str) -> "TypeBuilder":
        self._fhir = resource
        return self

    def attr(self, name: str, **spec: Any) -> "TypeBuilder":
        self._attrs[name] = spec
        return self

    def describe(self, text: str) -> "TypeBuilder":
        self._desc = text
        return self

    def build(self) -> TypeNode:
        return self._h.add_type(
            self._name,
            parent=self._parent,
            fhir_resource=self._fhir,
            attributes=self._attrs,
            description=self._desc,
        )


class _AionRegistry:
    """Globales Registry für decorator-registrierte Typen.

    Dies ist KEIN Singleton im klassischen Sinn — es ist ein Modul-globales
    Objekt, das alle via @aion_type dekorierten Klassen sammelt.
    """

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def register(
        self,
        name: str,
        parent: Optional[str] = None,
        fhir: Optional[str] = None,
        attributes: Optional[dict] = None,
        cls: Optional[type] = None,
        description: str = "",
    ) -> None:
        self._entries.append(
            {
                "name": name,
                "parent": parent,
                "fhir": fhir,
                "attributes": attributes or {},
                "cls": cls,
                "description": description,
            }
        )

    def materialize(self, hierarchy: TypeHierarchy) -> None:
        """Trägt alle registrierten Typen in die übergebene Hierarchie ein."""
        # Topologische Sortierung
        by_name = {e["name"]: e for e in self._entries}
        visited: set[str] = set()
        ordered: list[dict] = []

        def visit(name: str) -> None:
            if name in visited or name not in by_name:
                return
            visited.add(name)
            p = by_name[name].get("parent")
            if p:
                visit(p)
            ordered.append(by_name[name])

        for e in self._entries:
            visit(e["name"])

        for e in ordered:
            if e["name"] in hierarchy:
                continue
            hierarchy.add_type(
                name=e["name"],
                parent=e.get("parent"),
                fhir_resource=e.get("fhir"),
                attributes=e.get("attributes") or {},
                description=e.get("description", ""),
            )

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


AION_REGISTRY = _AionRegistry()


def aion_type(
    name: str,
    parent: Optional[str] = None,
    fhir: Optional[str] = None,
    description: str = "",
):
    """Decorator zur Registrierung einer Klasse als AION-Typ.

    Aus einer @dataclass werden die Felder als erlaubte Attribute extrahiert.

    Beispiel:
        @aion_type(name="Laktatmessung", parent="Blutmessung", fhir="Observation")
        @dataclass
        class LaktatMessung:
            value_mmol_l: float
            timestamp: datetime
    """

    def wrap(cls):
        attrs: dict[str, dict] = {}
        if is_dataclass(cls):
            for f in fields(cls):
                t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "any")
                attrs[f.name] = {"type": _normalize_type(t)}
        AION_REGISTRY.register(
            name=name,
            parent=parent,
            fhir=fhir,
            attributes=attrs,
            cls=cls,
            description=description,
        )
        # Für Convenience: speichere die Registry-Info am Klassen-Objekt
        cls.__aion_type__ = name
        return cls

    return wrap


def _normalize_type(t: Any) -> str:
    """Mappt Python-Typen auf Schema-Typen."""
    if isinstance(t, type):
        t = t.__name__
    s = str(t).lower()
    if s in ("int", "integer"):
        return "int"
    if s in ("float", "double"):
        return "float"
    if s in ("str", "string"):
        return "string"
    if s in ("bool", "boolean"):
        return "bool"
    return "any"

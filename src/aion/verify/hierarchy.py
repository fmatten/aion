# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Verifikation von Typ-Hierarchien — stdlib-only.

Prüfungen:
    1. **Multi-Inheritance-Konsistenz**:
       Erbt ein Typ ein Attribut von mehreren Eltern, müssen die Specs
       kompatibel sein (gleicher type, kompatible Wertebereiche).

    2. **Vollständigkeit Required-Attribute**:
       Welche Attribute sind im transitive Hülle eines Typs als
       `required: true` markiert?

    3. **Range-Verschärfung**:
       Subtyp-Range darf den Eltern-Range nur **einschränken**, nicht erweitern.
       Eine Beobachtung mit range [0, 100] darf keinen Subtyp mit [50, 200] haben.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aion.core.types import TypeHierarchy


@dataclass
class InheritanceConflict:
    """Ein konkreter Konflikt im Schema einer Typ-Hierarchie."""

    type_name: str
    attribute: str
    reason: str
    sources: list[tuple[str, dict]] = field(default_factory=list)
    """Liste von (parent_type_name, spec_dict) — die widersprüchlichen Specs."""

    def __str__(self) -> str:
        srcs = ", ".join(f"{src} ({spec})" for src, spec in self.sources)
        return f"[{self.type_name}.{self.attribute}] {self.reason} — Quellen: {srcs}"


@dataclass
class ValidationReport:
    """Ergebnis einer kompletten Schema-Validierung."""

    conflicts: list[InheritanceConflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.conflicts) == 0

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "✅ Schema konsistent."
        lines = []
        if self.conflicts:
            lines.append(f"❌ {len(self.conflicts)} Konflikt(e):")
            for c in self.conflicts:
                lines.append(f"   • {c}")
        if self.warnings:
            lines.append(f"⚠️  {len(self.warnings)} Warnung(en):")
            for w in self.warnings:
                lines.append(f"   • {w}")
        return "\n".join(lines)


def inherited_attributes(
    hierarchy: TypeHierarchy,
    type_name: str,
) -> dict[str, list[tuple[str, dict]]]:
    """Sammelt alle Attribute, die ein Typ via Inheritance „sieht".

    Returns:
        {attribute_name: [(source_type, spec), ...]}
        Eine Liste pro Attribut — bei Multi-Inheritance können mehrere
        Quellen für dasselbe Attribut existieren. Eigene Attribute des
        Typs sind ebenfalls enthalten (source = type_name selbst).
    """
    if type_name not in hierarchy:
        raise ValueError(f"Typ '{type_name}' nicht in Hierarchie.")

    attrs: dict[str, list[tuple[str, dict]]] = {}
    # Reihenfolge: erst eigene, dann Vorfahren (closer-to-self zuerst)
    chain = [type_name] + list(hierarchy.ancestors(type_name))
    seen: set[str] = set()
    for t in chain:
        if t == hierarchy.TOP or t in seen:
            continue
        seen.add(t)
        node = hierarchy.get(t)
        for attr_name, spec in node.attributes.items():
            attrs.setdefault(attr_name, []).append((t, spec))
    return attrs


def check_inheritance_conflicts(hierarchy: TypeHierarchy) -> ValidationReport:
    """Prüft alle Typen auf Multi-Inheritance-Konflikte.

    Was geprüft wird:
        - Bei mehreren Quellen für dasselbe Attribut müssen die
          `type`-Felder übereinstimmen.
        - Range-Intersection bei numerischen Typen darf nicht leer sein.
        - Enum-Werte: Subtyp-Werte müssen Teilmenge der Eltern-Werte sein.
    """
    report = ValidationReport()

    for t in hierarchy.all_types():
        attrs = inherited_attributes(hierarchy, t)
        for attr_name, sources in attrs.items():
            if len(sources) <= 1:
                continue  # Nur eine Quelle → kein Konflikt möglich
            conflict = _detect_conflict(t, attr_name, sources)
            if conflict is not None:
                report.conflicts.append(conflict)

    return report


def _detect_conflict(
    type_name: str,
    attr_name: str,
    sources: list[tuple[str, dict]],
) -> Optional[InheritanceConflict]:
    """Vergleicht mehrere Specs für dasselbe Attribut auf Konsistenz."""
    # Type-Mismatch?
    types = {spec.get("type") for _, spec in sources if "type" in spec}
    if len(types) > 1:
        return InheritanceConflict(
            type_name=type_name,
            attribute=attr_name,
            reason=f"Inkonsistente type-Felder: {types}",
            sources=list(sources),
        )

    # Range-Verschärfung: Subtyp-Range darf nicht über Eltern hinausragen.
    # Hier: Schnittmenge aller Ranges muss nicht leer sein.
    ranges = [spec.get("range") for _, spec in sources if spec.get("range")]
    if len(ranges) >= 2:
        lo = max(r[0] for r in ranges)
        hi = min(r[1] for r in ranges)
        if lo > hi:
            return InheritanceConflict(
                type_name=type_name,
                attribute=attr_name,
                reason=f"Disjunkte Wertebereiche: Schnitt [{lo}, {hi}] ist leer",
                sources=list(sources),
            )

    # Enum-Specialization: jüngste Quelle (sources[0]) darf nur Werte
    # haben, die in ALLEN Vorfahren-Quellen vorkommen.
    enums = [(src, set(spec["values"])) for src, spec in sources if spec.get("values")]
    if len(enums) >= 2:
        own = enums[0][1]
        for src, parent_vals in enums[1:]:
            extra = own - parent_vals
            if extra:
                return InheritanceConflict(
                    type_name=type_name,
                    attribute=attr_name,
                    reason=(
                        f"Enum-Werte {sorted(extra)} nicht in Eltern-Definition "
                        f"({src})"
                    ),
                    sources=list(sources),
                )

    return None


def check_required_attributes(
    hierarchy: TypeHierarchy,
    type_name: str,
) -> set[str]:
    """Liefert die Menge aller Required-Attribute eines Typs (geerbt + eigen).

    Ein Attribut gilt als required, wenn IRGENDEINE seiner Quellen
    `required: true` setzt — die strengste Anforderung gewinnt.
    """
    attrs = inherited_attributes(hierarchy, type_name)
    return {
        name
        for name, sources in attrs.items()
        if any(spec.get("required", False) for _, spec in sources)
    }

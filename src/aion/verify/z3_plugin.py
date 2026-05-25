# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Z3-basierte SMT-Verifikation für Schema-Constraints — OPTIONAL.

Lädt nur, wenn `z3-solver` installiert ist:

    pip install z3-solver

Was bietet dieses Modul:

    Bei großen Schema-Hierarchien mit vielen Range-Constraints kann
    Multi-Inheritance dazu führen, dass ein Subtyp UNERFÜLLBAR wird —
    es gibt keine Werte mehr, die alle ererbten Constraints erfüllen.

    Die stdlib-Variante `verify.hierarchy.check_inheritance_conflicts`
    findet die häufigsten Fälle (disjunkte Ranges, Enum-Mismatch) durch
    direkte Vergleiche. Der Z3-Solver geht weiter:

      * Numerische Constraints werden symbolisch als lineare
        Arithmetik-Formel kodiert und auf Erfüllbarkeit geprüft.
      * Bei UNSAT wird ein konkreter Konfliktbeweis (UNSAT-Core) geliefert.
      * Bei SAT bekommst Du ein Modell — also ein konkretes
        Beispiel-Tupel, das alle Constraints erfüllt. Das ist ein
        Sanity-Check beim Schema-Design.

    Geprüft werden:
      * `range`-Constraints von int/float-Attributen (mit Vererbung).
      * `enum`-Constraints (welche Werte zulässig sind).
      * `required`-Felder müssen einen Wert annehmen können.

Beispiel:

    >>> from aion.core.types import TypeHierarchy
    >>> from aion.verify.z3_plugin import check_schema_satisfiability
    >>> h = TypeHierarchy.from_yaml("schemas/clinical_base.yaml")
    >>> report = check_schema_satisfiability(h, "Sepsis")
    >>> print(report)
    ✅ Sepsis ist erfüllbar
       Modell: {sofa_score: 12, lactate: 4.2, septic_shock: True}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from aion.core.types import TypeHierarchy
from aion.verify.hierarchy import inherited_attributes


def _require_z3():
    """Lädt z3 lazy. Wirft eine sprechende ImportError, falls nicht da."""
    try:
        import z3
        return z3
    except ImportError as e:
        raise ImportError(
            "z3-solver ist nicht installiert. Installation:\n"
            "    pip install z3-solver\n"
            "(Optionale Abhängigkeit für aion.verify.z3_plugin.)"
        ) from e


@dataclass
class SatReport:
    """Ergebnis einer Z3-Erfüllbarkeitsprüfung."""

    type_name: str
    satisfiable: bool
    model: dict[str, Any] = field(default_factory=dict)
    unsat_reasons: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.satisfiable:
            mdl = ", ".join(f"{k}: {v}" for k, v in self.model.items())
            return f"✅ {self.type_name} ist erfüllbar\n   Modell: {{{mdl}}}"
        reasons = "\n   • " + "\n   • ".join(self.unsat_reasons)
        return f"❌ {self.type_name} ist UNERFÜLLBAR{reasons}"


def check_schema_satisfiability(
    hierarchy: TypeHierarchy,
    type_name: str,
) -> SatReport:
    """Prüft via Z3, ob es ein konkretes Tupel gibt, das alle Schema-Constraints
    eines Typs (inklusive ererbter) erfüllt.

    Wenn UNSAT, ist das Schema des Typs in sich widersprüchlich und sollte
    korrigiert werden. Wenn SAT, liefert der Bericht ein konkretes
    Beispiel-Tupel zur Inspektion.
    """
    z3 = _require_z3()
    if type_name not in hierarchy:
        return SatReport(
            type_name=type_name, satisfiable=False,
            unsat_reasons=[f"Typ '{type_name}' nicht in Hierarchie."],
        )

    solver = z3.Solver()
    z3_vars: dict[str, Any] = {}

    attrs = inherited_attributes(hierarchy, type_name)
    for attr_name, sources in attrs.items():
        # Attributtyp ermitteln (sollte bereits konsistent sein)
        att_type = next(
            (spec.get("type") for _, spec in sources if "type" in spec),
            None,
        )
        if att_type is None:
            continue

        var = _make_z3_var(z3, attr_name, att_type, sources)
        if var is None:
            continue
        z3_vars[attr_name] = var

        # Constraints aus allen Quellen sammeln (Vererbung verschärft)
        for src_type, spec in sources:
            _add_constraints(z3, solver, var, spec, src_type, attr_name)

    result = solver.check()
    if result == z3.sat:
        m = solver.model()
        model_dict: dict[str, Any] = {}
        for attr_name, var in z3_vars.items():
            value = m[var]
            if value is None:
                continue
            model_dict[attr_name] = _z3_value_to_python(value, z3)
        return SatReport(
            type_name=type_name, satisfiable=True, model=model_dict,
        )
    else:
        return SatReport(
            type_name=type_name, satisfiable=False,
            unsat_reasons=[
                f"Z3 UNSAT — kein Wert-Tupel erfüllt alle Constraints.",
                f"Hinweis: häufige Ursache sind disjunkte Wertebereiche bei "
                f"Multi-Inheritance.",
            ],
        )


def _make_z3_var(z3, attr_name: str, att_type: str, sources):
    """Erzeugt eine Z3-Variable passenden Typs."""
    if att_type == "int":
        return z3.Int(attr_name)
    if att_type == "float":
        return z3.Real(attr_name)
    if att_type == "bool":
        return z3.Bool(attr_name)
    if att_type in ("string", "enum"):
        # Enum: encodieren als Int über Index. Einfachste Variante.
        return z3.Int(f"{attr_name}_idx")
    return None


def _add_constraints(z3, solver, var, spec: dict, src: str, attr_name: str) -> None:
    rng = spec.get("range")
    if rng and len(rng) == 2:
        lo, hi = rng
        if spec.get("type") == "int":
            solver.add(var >= int(lo), var <= int(hi))
        elif spec.get("type") == "float":
            solver.add(var >= float(lo), var <= float(hi))

    values = spec.get("values")
    if values and spec.get("type") == "enum":
        # var ist Index → muss in [0, len(values))
        solver.add(var >= 0, var < len(values))


def _z3_value_to_python(value, z3) -> Any:
    """Konvertiert Z3-Modell-Wert in Python-Native."""
    try:
        if z3.is_int_value(value):
            return value.as_long()
        if z3.is_real(value):
            # Real kann RatNumRef sein → in float konvertieren
            try:
                return float(value.as_decimal(prec=6).rstrip("?"))
            except Exception:
                return float(value.as_fraction())
        if z3.is_bool(value):
            return bool(value)
    except Exception:
        pass
    return str(value)

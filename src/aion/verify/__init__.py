# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Verifikations-Modul für AION Clinical.

Zwei Schichten:

1. **stdlib-only Kern** (`verify.hierarchy`, `verify.causal`):
   Multi-Inheritance-Konsistenz, geerbte Required-Attribute, d-Separation,
   formale Backdoor-Set-Validierung. Läuft ohne externe Abhängigkeiten.

2. **Optionales Z3-Plugin** (`verify.z3_plugin`):
   SMT-basierte Erfüllbarkeitsprüfung für Schema-Constraints. Lädt nur,
   wenn z3-solver installiert ist:

       pip install z3-solver

   Ohne Z3-Installation funktioniert der Rest weiter.
"""
from aion.verify.hierarchy import (  # noqa: F401
    InheritanceConflict, ValidationReport,
    check_inheritance_conflicts, check_required_attributes,
    inherited_attributes,
)
from aion.verify.causal import (  # noqa: F401
    d_separates, is_valid_backdoor_set, BackdoorValidationReport,
)


def has_z3() -> bool:
    """Prüft, ob das Z3-Plugin verfügbar ist (z3-solver installiert)."""
    try:
        import z3  # noqa: F401
        return True
    except ImportError:
        return False

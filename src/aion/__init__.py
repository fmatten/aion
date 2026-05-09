# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""AION Clinical — formale Wissensrepräsentation für klinische Verläufe.

Public API:
    TypeHierarchy, TypeNode  — Typ-Hierarchie (DAG)
    ClinicalEvent            — Ereignismodell e = (p, a, τ, α, ρ)
    AllenInterval            — 13 Allen-Relationen
    FuzzyAllenInterval       — Unscharfe Intervalle mit Monte-Carlo
    CausalGraph              — Kausaler Graph mit Backdoor-Adjustierung
    TCFG                     — Temporale kontextfreie Grammatik (CYK + Beam)
    SQLiteEventStore         — Persistenz für ClinicalEvents
    TypeBuilder              — Fluent-API zur Typ-Erstellung
    aion_type                — Decorator zur Typ-Registrierung
"""

from aion.core.types import TypeHierarchy, TypeNode, TypeHierarchyError
from aion.core.events import ClinicalEvent
from aion.core.relations import EventRelation, is_valid_relation, inverse_of
from aion.core.temporal import AllenInterval, FuzzyAllenInterval, ALLEN_RELATIONS
from aion.core.causal import CausalGraph
from aion.core.tcfg import TCFG, TCFGResult
from aion.core.builder import TypeBuilder, aion_type, AION_REGISTRY
from aion.core.logging_setup import setup_logging, get_logger
from aion.core.privacy import pseudonymize, safe_path, fingerprint_dict
from aion.audit import AuditLog, AuditAction
from aion.config import (
    AionConfig, get_config, load_config, set_config, ConfigError,
)
from aion.persistence.sqlite_store import SQLiteEventStore
from aion.persistence.store import EventStore, create_event_store

# Verify-Modul: stdlib-Kern lädt immer; Z3-Plugin optional
from aion.verify import (
    check_inheritance_conflicts,
    check_required_attributes,
    d_separates,
    is_valid_backdoor_set,
    has_z3,
)

__version__ = "1.10.3"


def has_fhir() -> bool:
    """Prüft, ob das FHIR-Plugin verfügbar ist (fhir.resources installiert)."""
    try:
        import fhir.resources  # noqa: F401
        return True
    except ImportError:
        return False


def has_dowhy() -> bool:
    """Prüft, ob das DoWhy-Plugin verfügbar ist (dowhy installiert)."""
    try:
        import dowhy  # noqa: F401
        return True
    except ImportError:
        return False


def has_synthea() -> bool:
    """Synthea-Importer ist immer verfügbar (stdlib only)."""
    return True


def has_hl7v2() -> bool:
    """HL7-v2-Importer ist immer verfügbar (stdlib only)."""
    return True


def has_mllp() -> bool:
    """MLLP-Server ist immer verfügbar (stdlib only)."""
    return True


def has_auth() -> bool:
    """Auth-Module sind immer verfügbar (stdlib + PyYAML).

    LDAP- und OIDC-Backends erfordern zusätzlich `ldap3` bzw.
    `authlib + requests`, die als Optional-Extras installierbar sind.
    """
    return True


def has_notebook() -> bool:
    """Prüft, ob die Notebook-Helfer voll funktionsfähig sind (matplotlib installiert)."""
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


__all__ = [
    "TypeHierarchy", "TypeNode", "TypeHierarchyError",
    "ClinicalEvent",
    "EventRelation", "is_valid_relation", "inverse_of",
    "AllenInterval", "FuzzyAllenInterval", "ALLEN_RELATIONS",
    "CausalGraph",
    "TCFG", "TCFGResult",
    "TypeBuilder", "aion_type", "AION_REGISTRY",
    "SQLiteEventStore",
    "EventStore", "create_event_store",
    # logging
    "setup_logging", "get_logger",
    # privacy
    "pseudonymize", "safe_path", "fingerprint_dict",
    # audit
    "AuditLog", "AuditAction",
    # config
    "AionConfig", "get_config", "load_config", "set_config", "ConfigError",
    # verify
    "check_inheritance_conflicts", "check_required_attributes",
    "d_separates", "is_valid_backdoor_set", "has_z3",
    # fhir
    "has_fhir",
    # dowhy
    "has_dowhy",
    # notebook
    "has_notebook",
    # synthea
    "has_synthea",
    # hl7v2
    "has_hl7v2",
    # mllp
    "has_mllp",
    # auth
    "has_auth",
]

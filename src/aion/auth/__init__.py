# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""AION Auth-Modul (1.10.0).

Pluggable Auth-Backends:
    * NoneAuthBackend     — Default, kein Schutz (Dev/Test)
    * APIKeyBackend       — gehashte Keys aus YAML-Datei (vollständig)
    * LDAPBackend         — Active Directory / LDAP (optional, ldap3)
    * OIDCBackend         — OAuth2/OIDC mit JWT (optional, authlib)

Beispiele:

    # Aus Config laden (empfohlen)
    from aion.auth import create_auth_backend
    from aion.config import get_config

    backend = create_auth_backend(get_config())

    # Direkt nutzen
    from aion.auth import APIKeyCredentials
    principal = backend.authenticate(APIKeyCredentials("aion_J7K..."))
    print(principal.user_id, principal.roles)

    # Direkt instanziieren
    from aion.auth import APIKeyBackend
    backend = APIKeyBackend("/etc/aion/api-keys.yaml")
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from aion.auth.backend import (
    AuthBackend,
    Principal,
    PasswordCredentials,
    APIKeyCredentials,
    TokenCredentials,
    Credentials,
    AuthError,
    BadCredentials,
    BackendError,
    AuthDisabled,
)
from aion.auth.none_backend import NoneAuthBackend
from aion.auth.apikey import (
    APIKeyBackend, APIKeyEntry,
    hash_api_key, verify_api_key, generate_api_key,
)

if TYPE_CHECKING:
    from aion.config import AionConfig


# ────────────────────────────────────────────────────────────────────
#  Factory — wählt Backend aus Config
# ────────────────────────────────────────────────────────────────────
def create_auth_backend(cfg: Optional["AionConfig"] = None) -> AuthBackend:
    """Erzeugt ein Auth-Backend aus der Konfiguration.

    Liest `cfg.auth.backend` (none|apikey|ldap|oidc) und instanziiert
    den passenden Backend mit den Config-Werten.
    """
    if cfg is None:
        from aion.config import get_config
        cfg = get_config()

    backend_name = getattr(cfg.auth, "backend", "none")

    if backend_name == "none":
        return NoneAuthBackend()

    if backend_name == "apikey":
        key_file = getattr(cfg.auth, "apikey_file", None)
        if not key_file:
            raise BackendError(
                "auth.backend=apikey braucht auth.apikey_file in Config"
            )
        return APIKeyBackend(key_file)

    if backend_name == "ldap":
        from aion.auth.ldap_backend import LDAPBackend, LDAPConfig
        ldap_cfg = LDAPConfig(
            server=getattr(cfg.auth, "ldap_server", "ldaps://localhost"),
            bind_dn_template=getattr(cfg.auth, "ldap_bind_dn_template",
                                      "${user}@example.com"),
            use_ssl=getattr(cfg.auth, "ldap_use_ssl", True),
            start_tls=getattr(cfg.auth, "ldap_start_tls", False),
            timeout=getattr(cfg.auth, "ldap_timeout", 10.0),
            search_base=getattr(cfg.auth, "ldap_search_base", None),
            group_filter_template=getattr(cfg.auth, "ldap_group_filter", None),
            role_mapping=getattr(cfg.auth, "ldap_role_mapping", {}) or {},
        )
        return LDAPBackend(ldap_cfg)

    if backend_name == "oidc":
        from aion.auth.oidc import OIDCBackend, OIDCConfig
        oidc_cfg = OIDCConfig(
            issuer=getattr(cfg.auth, "oidc_issuer", ""),
            audience=getattr(cfg.auth, "oidc_audience", None),
            client_id=getattr(cfg.auth, "oidc_client_id", None),
            jwks_uri=getattr(cfg.auth, "oidc_jwks_uri", None),
            jwks_cache_ttl=getattr(cfg.auth, "oidc_jwks_cache_ttl", 3600),
            roles_claim=getattr(cfg.auth, "oidc_roles_claim",
                                "realm_access.roles"),
            user_id_claim=getattr(cfg.auth, "oidc_user_id_claim",
                                   "preferred_username"),
            display_name_claim=getattr(cfg.auth, "oidc_display_name_claim",
                                        "name"),
            leeway=getattr(cfg.auth, "oidc_leeway", 30),
        )
        return OIDCBackend(oidc_cfg)

    raise BackendError(f"Unbekanntes Auth-Backend: {backend_name!r}")


__all__ = [
    # Datentypen
    "Principal",
    "PasswordCredentials", "APIKeyCredentials", "TokenCredentials",
    "Credentials",
    # Protocol
    "AuthBackend",
    # Exceptions
    "AuthError", "BadCredentials", "BackendError", "AuthDisabled",
    # Backends
    "NoneAuthBackend", "APIKeyBackend",
    # API-Key-Helfer
    "APIKeyEntry", "hash_api_key", "verify_api_key", "generate_api_key",
    # Factory
    "create_auth_backend",
]

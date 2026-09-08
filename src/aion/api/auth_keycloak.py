# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
# aion/api/auth.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
OIDC/JWT-Authentifizierung für AION Clinical API.

Konfiguration (.env):
    AION_AUTH_ENABLED=true
    AION_OIDC_ISSUER=http://localhost:8080/realms/aion
    AION_OIDC_CLIENT_ID=aion-api

Dev-Modus (AUTH_ENABLED=false):
    Alle Anfragen als aion-admin durchgelassen – kein Token nötig.

Produktion (AUTH_ENABLED=true):
    Bearer-Token erforderlich, JWKS-Validierung gegen Keycloak.
"""
from __future__ import annotations
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from aion.api.config import settings

log = logging.getLogger(__name__)


@dataclass
class ClaimsUser:
    """Validierter Benutzer aus JWT-Claims."""
    sub:    str
    email:  str | None        = None
    name:   str | None        = None
    roles:  list[str]         = field(default_factory=list)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def is_admin(self) -> bool:
        return "aion-admin" in self.roles


# ── JWKS-Cache (lädt Schlüssel vom Keycloak einmalig) ─────────────────

_jwks_cache: dict = {}
_jwks_loaded_at: float = 0.0
_JWKS_TTL = 300  # 5 Minuten


def _load_jwks() -> dict:
    global _jwks_cache, _jwks_loaded_at
    now = time.time()
    if _jwks_cache and (now - _jwks_loaded_at) < _JWKS_TTL:
        return _jwks_cache
    url = f"{settings.OIDC_ISSUER}/protocol/openid-connect/jwks"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            _jwks_cache = json.loads(resp.read())
            _jwks_loaded_at = now
            log.info("JWKS geladen von %s (%d Schlüssel)",
                     url, len(_jwks_cache.get("keys", [])))
    except Exception as exc:
        log.warning("JWKS-Laden fehlgeschlagen: %s", exc)
    return _jwks_cache


def _validate_token(token: str) -> ClaimsUser:
    """
    Validiert JWT gegen Keycloak JWKS.
    Extrahiert Rollen aus realm_access.roles.
    """
    try:
        from jose import jwt, JWTError, jwk
        from jose.utils import base64url_decode
    except ImportError:
        raise ImportError(
            "python-jose nicht installiert: pip install python-jose[cryptography]"
        )

    jwks = _load_jwks()
    if not jwks:
        raise ValueError("JWKS nicht verfügbar – Keycloak erreichbar?")

    try:
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=settings.OIDC_CLIENT_ID,
            issuer=settings.OIDC_ISSUER,
            options={"verify_at_hash": False},
        )
    except Exception as exc:
        raise ValueError(f"Token-Validierung fehlgeschlagen: {exc}")

    # Rollen aus realm_access + resource_access
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    client_roles = (
        payload.get("resource_access", {})
               .get(settings.OIDC_CLIENT_ID, {})
               .get("roles", [])
    )
    roles = list(set(realm_roles + client_roles))

    return ClaimsUser(
        sub=payload["sub"],
        email=payload.get("email"),
        name=payload.get("name"),
        roles=roles,
    )


# ── FastAPI Dependency ────────────────────────────────────────────────

try:
    from fastapi import Depends, HTTPException, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    _bearer = HTTPBearer(auto_error=False)

    async def require_user(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> ClaimsUser:
        """
        FastAPI Dependency: gibt validierten ClaimsUser zurück.

        Dev-Modus (AUTH_ENABLED=false):
            → ClaimsUser(sub='dev-user', roles=['aion-admin','aion-user'])

        Produktion (AUTH_ENABLED=true):
            → Bearer-Token aus Authorization-Header validieren
        """
        if not settings.AUTH_ENABLED:
            return ClaimsUser(
                sub="dev-user",
                email="dev@iscad.de",
                name="Entwickler",
                roles=["aion-admin", "aion-user"],
            )

        if creds is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization-Header fehlt (Bearer-Token erforderlich)",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            return _validate_token(creds.credentials)
        except Exception as exc:
            log.warning("Auth-Fehler: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token ungültig: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def require_admin(
        user: ClaimsUser = Depends(require_user),
    ) -> ClaimsUser:
        """Dependency: nur aion-admin darf durch."""
        if not user.is_admin():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rolle 'aion-admin' erforderlich. "
                       f"Aktuelle Rollen: {user.roles}",
            )
        return user

except ImportError:
    # Fallback ohne FastAPI
    async def require_user():  # type: ignore
        return ClaimsUser(sub="dev-user", roles=["aion-admin", "aion-user"])

    async def require_admin():  # type: ignore
        return ClaimsUser(sub="dev-user", roles=["aion-admin"])

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""OIDC/OAuth2 Backend für moderne Identity-Provider.

Designentscheidungen:

  * **Token-basiert, nicht User+Passwort** — Anwender authentifiziert
    sich beim IDP (Keycloak, Telekom-IDP), bekommt einen Access-Token,
    schickt diesen an AION.
  * **JWT-Validierung** über JWKS-Endpoint des Issuers, mit Caching.
  * **Optional-Dependency `authlib`** — robuste Bibliothek mit guter
    JWT-Validierung, Discovery-Endpoint-Support.
  * **Rollen aus Token-Claims** — typisch `realm_access.roles` bei
    Keycloak, `groups` bei anderen.

WARNUNG: Erst-Test gegen echten Telekom-IDP wird Anpassungen brauchen.
Häufige Stolpersteine:
  * Audience-Validierung — wer ist `aud`?
  * Custom-Claims — ist `email` direkt da oder unter `userinfo`?
  * Clock-Skew zwischen IDP und AION
  * Refresh-Token-Handling (außerhalb dieses Backends)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from aion.auth.backend import (
    AuthBackend, BadCredentials, BackendError,
    Credentials, Principal, TokenCredentials,
)
from aion.core.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class OIDCConfig:
    """Konfiguration des OIDC-Backends."""
    issuer: str = "https://idp.example.com/realms/aion"
    audience: Optional[str] = None  # erwarteter `aud`-Claim
    client_id: Optional[str] = None  # falls audience=client_id
    # JWKS-Endpoint (auto-discovered wenn None)
    jwks_uri: Optional[str] = None
    # Cache-Zeit in Sekunden
    jwks_cache_ttl: int = 3600
    # Wo Rollen im Token stehen
    roles_claim: str = "realm_access.roles"
    # Welcher Claim ist user_id
    user_id_claim: str = "preferred_username"
    # Welcher Claim ist Display-Name
    display_name_claim: str = "name"
    # Clock-Skew-Toleranz in Sekunden
    leeway: int = 30


class OIDCBackend:
    """OIDC-Token-Authentifizierung.

    Erfüllt das AuthBackend-Protocol strukturell.

    Erfordert: pip install authlib requests
    """
    name = "oidc"

    def __init__(self, config: OIDCConfig) -> None:
        try:
            import authlib.jose
            import requests
        except ImportError as e:
            raise BackendError(
                "OIDC-Backend braucht authlib + requests: "
                'pip install -e ".[oidc]"'
            ) from e

        self._authlib_jose = authlib.jose
        self._requests = requests
        self.config = config
        self._jwks_cache: Optional[dict] = None
        self._jwks_cached_at: float = 0.0

        # JWKS-URI auto-discoveren wenn nicht gesetzt
        if not self.config.jwks_uri:
            self.config.jwks_uri = self._discover_jwks_uri()

    def _discover_jwks_uri(self) -> str:
        """Holt jwks_uri aus dem .well-known/openid-configuration."""
        url = f"{self.config.issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            resp = self._requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            jwks_uri = data.get("jwks_uri")
            if not jwks_uri:
                raise BackendError(f"OIDC-Discovery liefert kein jwks_uri")
            return jwks_uri
        except Exception as e:
            raise BackendError(
                f"OIDC-Discovery fehlgeschlagen ({url}): {e}"
            ) from e

    def _get_jwks(self) -> dict:
        """JWKS holen, mit TTL-Cache."""
        now = time.time()
        if (self._jwks_cache and
                now - self._jwks_cached_at < self.config.jwks_cache_ttl):
            return self._jwks_cache
        try:
            resp = self._requests.get(self.config.jwks_uri, timeout=10)
            resp.raise_for_status()
            self._jwks_cache = resp.json()
            self._jwks_cached_at = now
            return self._jwks_cache
        except Exception as e:
            raise BackendError(f"JWKS-Fetch fehlgeschlagen: {e}") from e

    def supports(self, credentials: Credentials) -> bool:
        return isinstance(credentials, TokenCredentials)

    def authenticate(self, credentials: Credentials) -> Principal:
        if not isinstance(credentials, TokenCredentials):
            raise BadCredentials("OIDCBackend braucht TokenCredentials")

        token = credentials.token
        if not token:
            raise BadCredentials("Leerer Token")

        # JWT validieren
        try:
            jwks = self._get_jwks()
            from authlib.jose import jwt
            claims = jwt.decode(
                token,
                key=jwks,
                claims_options={
                    "iss": {"essential": True, "value": self.config.issuer},
                },
            )

            # Standard-Claims validieren (exp, nbf, iat)
            claims.validate(leeway=self.config.leeway)

        except Exception as e:
            # JWT ungültig (Signatur, abgelaufen, falscher Issuer, ...)
            log.info("Token-Validierung fehlgeschlagen: %s", e)
            raise BadCredentials(f"Token ungültig: {e}") from e

        # Audience-Check (manuell, weil flexibel)
        expected_aud = self.config.audience or self.config.client_id
        if expected_aud:
            aud = claims.get("aud")
            if isinstance(aud, str):
                aud_ok = aud == expected_aud
            elif isinstance(aud, list):
                aud_ok = expected_aud in aud
            else:
                aud_ok = False
            if not aud_ok:
                raise BadCredentials(
                    f"Audience-Mismatch: erwartet {expected_aud}, "
                    f"bekommen {aud}"
                )

        # User-Info aus Claims extrahieren
        user_id = self._get_claim(claims, self.config.user_id_claim) or "unknown"
        display_name = (
            self._get_claim(claims, self.config.display_name_claim)
            or user_id
        )

        # Rollen
        roles = self._get_claim(claims, self.config.roles_claim) or []
        if isinstance(roles, str):
            roles = [roles]

        return Principal(
            user_id=str(user_id),
            display_name=str(display_name),
            backend="oidc",
            roles=frozenset(str(r) for r in roles),
            extra=tuple(
                (k, v) for k, v in claims.items()
                if k in ("email", "sub", "iss")
            ),
        )

    @staticmethod
    def _get_claim(claims, path: str):
        """Holt einen verschachtelten Claim, z. B. 'realm_access.roles'."""
        parts = path.split(".")
        obj = claims
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            else:
                return None
            if obj is None:
                return None
        return obj


__all__ = ["OIDCBackend", "OIDCConfig"]

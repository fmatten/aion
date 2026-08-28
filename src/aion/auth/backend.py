# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Auth-Backend-Protocol und gemeinsame Datentypen.

Designentscheidungen (1.10.0):

  * **Protocol statt ABC** — wie bei EventStore. Strukturelle Konformität
    erlaubt Mocks und Custom-Backends ohne Inheritance-Pflicht.
  * **`Principal`-Datenklasse** — was authentifiziert wurde (User-ID,
    Display-Name, Rollen, Backend-Quelle). Bewusst minimal, nicht jedes
    LDAP-Attribut wird durchgereicht.
  * **`AuthError`-Exception-Hierarchie** — unterscheidet zwischen
    "kein Match" (BadCredentials) und "Backend kaputt" (BackendError).
    Wichtig für Logging und Retry-Logik.
  * **Plain-text Credentials nur in der Methode** — nie speichern, nie
    loggen. `__repr__` der Credentials-Klassen verbirgt das Passwort.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


# ────────────────────────────────────────────────────────────────────
#  Exceptions
# ────────────────────────────────────────────────────────────────────
class AuthError(Exception):
    """Basisklasse für alle Auth-Fehler."""


class BadCredentials(AuthError):
    """User+Passwort/Key passt nicht — normaler Fehler, der oft passiert."""


class BackendError(AuthError):
    """Auth-Backend nicht erreichbar oder konfigurations-kaputt — selten,
    sollte alarmieren."""


class AuthDisabled(AuthError):
    """Versuch, Auth zu nutzen, obwohl backend=none konfiguriert ist."""


# ────────────────────────────────────────────────────────────────────
#  Datentypen
# ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Principal:
    """Ein authentifizierter Benutzer oder Service.

    Bewusst flach gehalten — wenn man mehr braucht (Group-Membership-Details,
    LDAP-DN, Token-Claims), holt man das per `extra` mit.

    Attribute:
        user_id:    eindeutiger Identifier (z. B. UPN bei AD, sub bei OIDC,
                    oder API-Key-Name)
        display_name: Anzeige-Name (für Audit-Log, GUI)
        backend:    welches Backend hat authentifiziert ("apikey", "ldap", "oidc")
        roles:      optionale Rollen (frozenset für Hash-Stabilität)
        extra:      Backend-spezifische Zusatzdaten (E-Mail, Department, etc.)
    """
    user_id: str
    display_name: str
    backend: str
    roles: frozenset[str] = field(default_factory=frozenset)
    extra: tuple = field(default_factory=tuple)  # tuple of (key, value) pairs

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def get_extra(self, key: str, default=None):
        for k, v in self.extra:
            if k == key:
                return v
        return default

    def __repr__(self) -> str:
        # Keine Geheimnisse loggen
        return (f"Principal(user={self.user_id!r}, backend={self.backend!r}, "
                f"roles={set(self.roles)})")


@dataclass(frozen=True)
class PasswordCredentials:
    """User + Passwort. Wird sofort verwendet, nie gespeichert."""
    username: str
    password: str

    def __repr__(self) -> str:
        # Niemals Passwort in Logs
        return f"PasswordCredentials(username={self.username!r}, password=***)"


@dataclass(frozen=True)
class APIKeyCredentials:
    """API-Key. Wird sofort verwendet, nie gespeichert."""
    api_key: str

    def __repr__(self) -> str:
        # Nur Prefix loggen, damit Debug möglich ist
        prefix = self.api_key[:8] if len(self.api_key) >= 8 else "***"
        return f"APIKeyCredentials(api_key={prefix}…)"


@dataclass(frozen=True)
class TokenCredentials:
    """OIDC-Access-Token oder JWT."""
    token: str

    def __repr__(self) -> str:
        prefix = self.token[:12] if len(self.token) >= 12 else "***"
        return f"TokenCredentials(token={prefix}…)"


# Vereinigung aller Credential-Typen
Credentials = PasswordCredentials | APIKeyCredentials | TokenCredentials


# ────────────────────────────────────────────────────────────────────
#  AuthBackend-Protocol
# ────────────────────────────────────────────────────────────────────
@runtime_checkable
class AuthBackend(Protocol):
    """Schnittstelle für Authentifizierungs-Backends.

    Jedes Backend muss `authenticate(credentials)` implementieren und
    entweder einen `Principal` zurückgeben oder eine Exception aus der
    `AuthError`-Hierarchie werfen.

    Konventionen:
        * `BadCredentials` werfen, wenn Login fehlschlägt (häufig)
        * `BackendError` werfen, wenn Backend nicht erreichbar (selten)
        * Niemals Passwörter in Logs schreiben
        * Connection-Pools sind Backend-Implementierungs-Sache
    """

    name: str  # z. B. "apikey", "ldap", "oidc"

    def authenticate(self, credentials: Credentials) -> Principal:
        """Authentifiziert. Returns Principal oder wirft AuthError."""
        ...

    def supports(self, credentials: Credentials) -> bool:
        """Kann dieses Backend diesen Credential-Typ verarbeiten?"""
        ...


__all__ = [
    "Principal",
    "PasswordCredentials",
    "APIKeyCredentials",
    "TokenCredentials",
    "Credentials",
    "AuthBackend",
    "AuthError",
    "BadCredentials",
    "BackendError",
    "AuthDisabled",
]

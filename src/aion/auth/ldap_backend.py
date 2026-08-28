# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""LDAP/Active Directory Backend.

Designentscheidungen:

  * **Optional-Dependency `ldap3`** — keine Klartext-Bibliothek, weil
    `python-ldap` C-Build braucht. `ldap3` ist Pure-Python.
  * **Bind-DN per Template** — flexibel für unterschiedliche AD-Setups:
    `${user}@klinik.local` (UPN) oder
    `cn=${user},ou=users,dc=klinik,dc=local` (Distinguished Name).
  * **TLS verpflichtend in Production** — `ldaps://` oder StartTLS.
    Für Dev kann `ldap://` mit Warnung benutzt werden.
  * **Group-Membership per Filter** — wer in welcher AD-Gruppe ist,
    wird zu AION-Rollen gemappt (konfigurierbar).
  * **Connection-Pooling per Bind** — jeder Auth-Versuch öffnet eine
    eigene Verbindung. Bei Last später Pool ergänzen.

WARNUNG: Erst-Test gegen echtes AD wird Anpassungen brauchen.
Häufige Stolpersteine:
  * UPN vs. sAMAccountName (`alice@klinik.local` vs. `alice`)
  * Referrals (Multi-Forest-AD)
  * NTLM/Kerberos statt Simple Bind
  * Server-side Filter-Limits
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from aion.auth.backend import (
    AuthBackend, BadCredentials, BackendError,
    Credentials, PasswordCredentials, Principal,
)
from aion.core.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class LDAPConfig:
    """Konfiguration des LDAP-Backends."""
    server: str = "ldaps://ldap.example.com"
    bind_dn_template: str = "${user}@example.com"
    use_ssl: bool = True
    start_tls: bool = False
    timeout: float = 10.0
    # Optional: Group-Suche
    search_base: Optional[str] = None
    group_filter_template: Optional[str] = None
    # z. B. "(member=cn=${user},ou=users,dc=example,dc=com)"
    role_mapping: dict = field(default_factory=dict)
    # z. B. {"AION-Admins": "admin", "AION-Aerzte": "physician"}


class LDAPBackend:
    """LDAP/AD-Authentifizierung über Simple Bind.

    Erfüllt das AuthBackend-Protocol strukturell.

    Erfordert: pip install ldap3
    """
    name = "ldap"

    def __init__(self, config: LDAPConfig) -> None:
        # Lazy import — nur wenn LDAPBackend wirklich genutzt wird
        try:
            import ldap3
        except ImportError as e:
            raise BackendError(
                "LDAP-Backend braucht ldap3: pip install -e \".[ldap]\""
            ) from e

        self._ldap3 = ldap3
        self.config = config

        if not config.use_ssl and not config.start_tls:
            log.warning(
                "LDAP ohne TLS — nur für Entwicklung. "
                "In Production: ldaps:// oder start_tls=true setzen."
            )

    def supports(self, credentials: Credentials) -> bool:
        return isinstance(credentials, PasswordCredentials)

    def authenticate(self, credentials: Credentials) -> Principal:
        if not isinstance(credentials, PasswordCredentials):
            raise BadCredentials("LDAPBackend braucht PasswordCredentials")

        username = credentials.username
        password = credentials.password

        if not username or not password:
            raise BadCredentials("Leerer Username oder Passwort")

        # Bind-DN aus Template bauen
        # Wir verwenden bewusst einfaches String-Replace, kein eval —
        # alles, was nicht ${user} ist, bleibt unverändert.
        bind_dn = self.config.bind_dn_template.replace("${user}", username)

        try:
            server = self._ldap3.Server(
                self.config.server,
                use_ssl=self.config.use_ssl,
                connect_timeout=self.config.timeout,
            )
            conn = self._ldap3.Connection(
                server,
                user=bind_dn,
                password=password,
                auto_bind=False,
                raise_exceptions=False,
                read_only=True,
            )

            if self.config.start_tls:
                if not conn.start_tls():
                    raise BackendError("StartTLS fehlgeschlagen")

            if not conn.bind():
                # Authentication fehlgeschlagen — kann sein:
                # invalidCredentials, account locked, password expired etc.
                result = conn.result
                code = result.get("description", "unknown")
                log.info("LDAP-Bind fehlgeschlagen für %s: %s",
                         username, code)
                raise BadCredentials(f"LDAP-Bind fehlgeschlagen: {code}")

            # Bind erfolgreich — jetzt Rollen ermitteln (optional)
            roles = self._fetch_roles(conn, username)

            # Display-Name: optional aus LDAP-Search holen
            display_name = self._fetch_display_name(conn, username) or username

            conn.unbind()

            return Principal(
                user_id=username,
                display_name=display_name,
                backend="ldap",
                roles=frozenset(roles),
            )

        except self._ldap3.core.exceptions.LDAPException as e:
            log.exception("LDAP-Backend Fehler")
            raise BackendError(f"LDAP-Backend Fehler: {e}") from e

    def _fetch_roles(self, conn, username: str) -> list[str]:
        """Sucht AD-Gruppen-Mitgliedschaften, mappt auf AION-Rollen."""
        if not self.config.search_base or not self.config.group_filter_template:
            return []

        try:
            filter_str = self.config.group_filter_template.replace(
                "${user}", username
            )
            conn.search(
                search_base=self.config.search_base,
                search_filter=filter_str,
                attributes=["cn"],
            )
            ad_groups = []
            for entry in conn.entries:
                cn = entry.cn.value if hasattr(entry, "cn") else None
                if cn:
                    ad_groups.append(str(cn))

            roles: list[str] = []
            for ad_group in ad_groups:
                if ad_group in self.config.role_mapping:
                    roles.append(self.config.role_mapping[ad_group])
            return roles
        except Exception:
            log.warning("Group-Search fehlgeschlagen für %s", username,
                        exc_info=True)
            return []

    def _fetch_display_name(self, conn, username: str) -> Optional[str]:
        """Holt displayName-Attribut aus LDAP. Best effort."""
        if not self.config.search_base:
            return None
        try:
            # AD-typischer Filter: sAMAccountName oder UPN
            user_local = username.split("@", 1)[0]
            search_filter = (
                f"(|(sAMAccountName={user_local})"
                f"(userPrincipalName={username}))"
            )
            conn.search(
                search_base=self.config.search_base,
                search_filter=search_filter,
                attributes=["displayName"],
            )
            if conn.entries:
                dn = conn.entries[0].displayName.value
                return str(dn) if dn else None
        except Exception:
            log.debug("displayName-Lookup fehlgeschlagen", exc_info=True)
        return None


__all__ = ["LDAPBackend", "LDAPConfig"]

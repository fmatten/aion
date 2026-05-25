# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""API-Key-Backend für Service-zu-Service-Authentifizierung.

Designentscheidungen:

  * **Keys sind in einer YAML-Datei abgelegt** mit gehashten Werten.
    Klartext-Keys gibt es nur beim Erzeugen (CLI-Output für Operator).
  * **Hash-Verfahren: blake2b mit Salt** (kein bcrypt, kein argon2 —
    API-Keys sind hochentropisch, brauchen kein Key-Stretching).
  * **Konstante Vergleichszeit** via `hmac.compare_digest`, um
    Timing-Attacken zu vermeiden.
  * **Per-Key-Metadaten:** Name, Rollen, Ablaufdatum (optional),
    erlaubte IP-Ranges (optional, später).

Datei-Format `/etc/aion/api-keys.yaml`:

    keys:
      - name: mirth-channel-1
        hash: blake2b$<salt-hex>$<digest-hex>
        roles: [ingest]
        expires: 2027-12-31
      - name: monitoring-readonly
        hash: blake2b$<salt-hex>$<digest-hex>
        roles: [readonly]

Klartext-Keys werden über `aion auth keygen` erzeugt und einmalig
ausgegeben — der Operator muss sie dann selbst sicher übermitteln
(Mirth-Channel-Konfig, env-File, Vault).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

import yaml

from aion.auth.backend import (
    APIKeyCredentials, AuthBackend, BadCredentials, BackendError,
    Credentials, Principal,
)
from aion.core.logging_setup import get_logger

log = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
#  Hashing
# ────────────────────────────────────────────────────────────────────
_HASH_ALGO = "blake2b"
_HASH_DIGEST_SIZE = 32  # 256 bit
_SALT_SIZE = 16


def hash_api_key(api_key: str, *, salt: Optional[bytes] = None) -> str:
    """Hashed einen API-Key. Format: 'blake2b$<salt-hex>$<digest-hex>'."""
    if salt is None:
        salt = secrets.token_bytes(_SALT_SIZE)
    h = hashlib.blake2b(api_key.encode("utf-8"),
                        salt=salt, digest_size=_HASH_DIGEST_SIZE)
    return f"{_HASH_ALGO}${salt.hex()}${h.hexdigest()}"


def verify_api_key(api_key: str, stored_hash: str) -> bool:
    """Prüft API-Key gegen gespeicherten Hash. Konstante Zeit."""
    try:
        algo, salt_hex, digest_hex = stored_hash.split("$", 2)
    except ValueError:
        log.warning("Ungültiges Hash-Format")
        return False
    if algo != _HASH_ALGO:
        log.warning("Unbekannter Hash-Algorithmus: %s", algo)
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    h = hashlib.blake2b(api_key.encode("utf-8"),
                        salt=salt, digest_size=_HASH_DIGEST_SIZE)
    # Konstante Vergleichszeit gegen Timing-Attacken
    return hmac.compare_digest(h.hexdigest(), digest_hex)


def generate_api_key(*, prefix: str = "aion") -> str:
    """Erzeugt einen neuen API-Key.

    Format: <prefix>_<41-char-base32-token>. Lesbar und unverwechselbar
    mit Passwörtern. Beispiel: aion_J7K9X2BF...
    """
    # 32 bytes Zufall = 256 bit Entropie
    raw = secrets.token_bytes(32)
    # base32 ohne Padding für URL-Safety und visuelle Klarheit
    import base64
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    return f"{prefix}_{encoded}"


# ────────────────────────────────────────────────────────────────────
#  Key-Datenklasse
# ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class APIKeyEntry:
    """Ein gespeicherter API-Key (gehashed) mit Metadaten."""
    name: str
    hash: str
    roles: frozenset[str] = frozenset()
    expires: Optional[date] = None

    def is_expired(self, *, now: Optional[date] = None) -> bool:
        if self.expires is None:
            return False
        if now is None:
            from datetime import timezone
            now = datetime.now(timezone.utc).date()
        return now > self.expires


# ────────────────────────────────────────────────────────────────────
#  Backend
# ────────────────────────────────────────────────────────────────────
class APIKeyBackend:
    """API-Key-Authentifizierung gegen YAML-Datei.

    Lädt die Key-Datei beim Konstruieren. Für Hot-Reload kann
    `reload()` aufgerufen werden — keine automatische Beobachtung.
    """
    name = "apikey"

    def __init__(self, key_file: Union[str, Path]) -> None:
        self.key_file = Path(key_file)
        self._keys: list[APIKeyEntry] = []
        self.reload()

    def reload(self) -> None:
        """Lädt Keys aus der Datei neu."""
        if not self.key_file.exists():
            raise BackendError(
                f"API-Key-Datei nicht gefunden: {self.key_file}"
            )

        try:
            with self.key_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as e:
            raise BackendError(f"API-Key-Datei nicht lesbar: {e}") from e

        keys_raw = data.get("keys", [])
        if not isinstance(keys_raw, list):
            raise BackendError("'keys' muss eine Liste sein")

        loaded: list[APIKeyEntry] = []
        for i, entry in enumerate(keys_raw):
            if not isinstance(entry, dict):
                log.warning("Eintrag %d übersprungen: kein Dict", i)
                continue
            try:
                expires = entry.get("expires")
                if expires is not None:
                    if isinstance(expires, str):
                        expires = date.fromisoformat(expires)
                    elif isinstance(expires, datetime):
                        expires = expires.date()

                roles = entry.get("roles", [])
                if isinstance(roles, str):
                    roles = [roles]

                loaded.append(APIKeyEntry(
                    name=str(entry["name"]),
                    hash=str(entry["hash"]),
                    roles=frozenset(roles),
                    expires=expires,
                ))
            except (KeyError, ValueError, TypeError) as e:
                log.warning("Key-Eintrag %d übersprungen: %s", i, e)

        self._keys = loaded
        log.info("APIKey-Backend: %d Keys aus %s geladen",
                 len(loaded), self.key_file)

    def supports(self, credentials: Credentials) -> bool:
        return isinstance(credentials, APIKeyCredentials)

    def authenticate(self, credentials: Credentials) -> Principal:
        if not isinstance(credentials, APIKeyCredentials):
            raise BadCredentials("APIKeyBackend braucht APIKeyCredentials")

        api_key = credentials.api_key
        if not api_key:
            raise BadCredentials("Leerer API-Key")

        # Alle Einträge durchgehen — konstante Zeit pro Eintrag,
        # keine early-exit, damit Timing keine Info verrät.
        # (Bei <100 Keys nicht messbar; nur Vorsicht für später.)
        match: Optional[APIKeyEntry] = None
        for entry in self._keys:
            if verify_api_key(api_key, entry.hash):
                match = entry
                # Kein break — Timing-Konsistenz

        if match is None:
            raise BadCredentials("Unbekannter API-Key")

        if match.is_expired():
            log.warning("Abgelaufener API-Key verwendet: %s", match.name)
            raise BadCredentials(f"API-Key '{match.name}' abgelaufen")

        return Principal(
            user_id=match.name,
            display_name=f"API-Key: {match.name}",
            backend="apikey",
            roles=match.roles,
        )


__all__ = [
    "APIKeyBackend",
    "APIKeyEntry",
    "hash_api_key",
    "verify_api_key",
    "generate_api_key",
]

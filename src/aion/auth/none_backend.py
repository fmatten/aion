# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""None-Backend: Auth deaktiviert.

Das ist der **Default**. Wenn `auth.backend: none` in der Config steht
(oder Auth gar nicht konfiguriert ist), liefert dieser Backend einen
festen "anonymous"-Principal — was technisch keine Authentifizierung
ist.

Verwendung:
    * Lokale Entwicklung
    * CLI- und GUI-Nutzung wo OS-User-Permissions reichen
    * Erste Test-Phase, bevor echte Auth aufgesetzt ist

NICHT für Production geeignet, sobald Eintrittspunkte aus dem Netz
erreichbar werden (MLLP, REST-API).
"""
from __future__ import annotations

from aion.auth.backend import (
    AuthBackend, AuthDisabled,
    Credentials, Principal,
)


class NoneAuthBackend:
    """Liefert immer denselben anonymous-Principal.

    Erfüllt das AuthBackend-Protocol strukturell.
    """
    name = "none"

    def authenticate(self, credentials: Credentials) -> Principal:
        # Wir akzeptieren jeden — das ist genau der Punkt von "none"
        return Principal(
            user_id="anonymous",
            display_name="Anonymous (auth disabled)",
            backend="none",
            roles=frozenset({"anonymous"}),
        )

    def supports(self, credentials: Credentials) -> bool:
        return True  # nimmt alles an


__all__ = ["NoneAuthBackend"]

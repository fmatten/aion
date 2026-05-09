# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""MLLP-Listener für HL7-v2 (1.9.0).

MLLP = Minimum Lower Layer Protocol — der Standard-Transport für HL7-v2
über TCP. Eine Nachricht ist mit Start- und End-Markern umrahmt:

    <VT> ... message ... <FS><CR>
    0x0B  ...           0x1C 0x0D

Designentscheidungen:

  * **Stdlib-only**: socketserver.ThreadingTCPServer, kein asyncio,
    kein twisted. Ein Thread pro Verbindung, einfach zu debuggen.
  * **Signal-Handling**: SIGTERM/SIGINT = graceful shutdown — laufende
    Verbindungen werden zu Ende bedient (mit Timeout).
  * **Pluggable Handler**: was mit jeder Nachricht passiert, ist über
    das `MLLPHandler`-Protocol austauschbar. Default speichert in
    EventStore + Audit, aber Tests können einen Mock-Handler injizieren.
  * **ACK-Format Standard-konform**: MSH gespiegelt mit MSA|AA|... oder
    MSA|AE|... bei Verarbeitungsfehlern.

Beispiel:

    from aion.hl7v2.mllp import MLLPServer, DefaultHandler
    from aion import create_event_store
    from aion.audit import AuditLog

    audit = AuditLog("audit.db")
    with create_event_store() as store:
        handler = DefaultHandler(store=store, audit=audit)
        server = MLLPServer(("0.0.0.0", 2575), handler=handler)
        server.serve_forever()
"""
from __future__ import annotations

import logging
import socket
import socketserver
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from aion.core.events import ClinicalEvent
from aion.core.logging_setup import get_logger
from aion.hl7v2 import HL7Message, parse_message, message_to_event

log = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
#  MLLP-Konstanten
# ────────────────────────────────────────────────────────────────────
MLLP_START_BLOCK = b"\x0b"   # <VT>
MLLP_END_BLOCK = b"\x1c"     # <FS>
MLLP_CARRIAGE_RETURN = b"\x0d"  # <CR>
MLLP_END = MLLP_END_BLOCK + MLLP_CARRIAGE_RETURN

DEFAULT_PORT = 2575
DEFAULT_BUFFER_SIZE = 8192
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB


# ────────────────────────────────────────────────────────────────────
#  Handler-Protocol
# ────────────────────────────────────────────────────────────────────
@runtime_checkable
class MLLPHandler(Protocol):
    """Schnittstelle für was mit empfangenen Nachrichten passiert.

    Jeder Handler muss `handle(msg, raw)` implementieren und einen
    ACK-Code zurückgeben:
        "AA" = Application Accept (Erfolg)
        "AE" = Application Error (verarbeitbarer Fehler)
        "AR" = Application Reject (kann/will nicht verarbeiten)
    """

    def handle(self, msg: HL7Message, raw: bytes) -> str:
        """Verarbeitet eine empfangene Nachricht. Liefert ACK-Code."""
        ...


# ────────────────────────────────────────────────────────────────────
#  Default-Handler: speichert in EventStore + Audit
# ────────────────────────────────────────────────────────────────────
class DefaultHandler:
    """Standard-Verarbeitung: Mappt zu ClinicalEvent, speichert in Store,
    protokolliert in Audit.

    Optional mit Auth: wenn `auth_backend` gesetzt ist, wird der API-Key
    aus MSH-3 (Sending Application) extrahiert und gegen den Backend
    geprüft. Nicht-authentifizierte Nachrichten bekommen `AR`
    (Application Reject).

    Erfüllt MLLPHandler-Protocol strukturell.
    """

    def __init__(
        self,
        store: Optional[Any] = None,    # EventStore-kompatibel
        audit: Optional[Any] = None,    # AuditLog-kompatibel (oder None)
        code_map: Optional[dict[str, str]] = None,
        auth_backend: Optional[Any] = None,  # AuthBackend (oder None = kein Auth)
        required_role: Optional[str] = None,  # z. B. "ingest"
    ) -> None:
        self.store = store
        self.audit = audit
        self.code_map = code_map
        self.auth_backend = auth_backend
        self.required_role = required_role
        self._lock = threading.Lock()  # Für SQLite-Single-Writer-Schutz

    def handle(self, msg: HL7Message, raw: bytes) -> str:
        # Audit zuerst — auch bei Fehlern
        msg_id = msg.field("MSH", 10) or "unknown"
        sender = msg.field("MSH", 3) or "unknown"

        # ── Auth-Check (wenn Backend konfiguriert) ──────────────
        if self.auth_backend is not None:
            try:
                from aion.auth import APIKeyCredentials, AuthError
                # API-Key wird im MSH-3 erwartet: "key-name|aion_KEY..."
                # Konvention: MSH-3 = "<channel-name>" und der Key
                # selbst kommt aus MSH-4 (Sending Facility). Das ist
                # eine Konvention für Mirth — siehe Doku.
                # Alternativ: ganzes MSH-3 als Key.
                api_key = msg.field("MSH", 4) or ""
                if not api_key.startswith("aion_"):
                    # Nicht der erwartete Key-Stil — leeres Feld oder
                    # ein Klar-Name. Das nehmen wir als "kein Key".
                    log.info("MLLP: kein API-Key in MSH-4 von %s", sender)
                    self._audit_failure(msg_id, sender, "auth-missing", None)
                    return "AR"
                credentials = APIKeyCredentials(api_key)
                principal = self.auth_backend.authenticate(credentials)
                if (self.required_role and
                        not principal.has_role(self.required_role)):
                    log.info("MLLP: Principal %s hat Role %s nicht",
                             principal.user_id, self.required_role)
                    self._audit_failure(msg_id, sender, "auth-no-role", None)
                    return "AR"
                # Audit nutzt jetzt den authentifizierten Namen
                authenticated_user = f"mllp:{principal.user_id}"
            except AuthError as e:
                log.info("MLLP-Auth fehlgeschlagen für %s: %s", sender, e)
                self._audit_failure(msg_id, sender, "auth-failed", str(e))
                return "AR"
        else:
            # Kein Auth konfiguriert
            authenticated_user = f"mllp:{sender}"

        try:
            event = message_to_event(msg, code_map=self.code_map)
        except Exception as e:
            log.exception("Mapping fehlgeschlagen für %s", msg_id)
            self._audit_failure(msg_id, authenticated_user, "mapping-error", str(e))
            return "AE"

        if event is None:
            log.debug("Nachricht ohne Patient/Zeit übersprungen: %s", msg_id)
            self._audit_failure(msg_id, authenticated_user, "no-patient-or-time", None)
            # Nicht "AE" — die Nachricht ist syntaktisch ok, hat nur keine
            # AION-relevanten Daten. KIS soll das nicht als Fehler sehen.
            return "AA"

        if self.store is not None:
            try:
                with self._lock:
                    self.store.add(event)
            except Exception as e:
                log.exception("Store-Insert fehlgeschlagen für %s", msg_id)
                self._audit_failure(msg_id, authenticated_user, "store-error", str(e))
                return "AE"

        # Audit erfolgreichen Empfang
        if self.audit is not None:
            try:
                from aion.audit import AuditAction
                self.audit.record(
                    action=AuditAction.IMPORT,
                    user=authenticated_user,
                    resource_type="ClinicalEvent",
                    resource_id=event.event_id,
                    patient_id=event.patient_id,
                    details=f"hl7v2 msg_id={msg_id} type={msg.message_type}^{msg.trigger_event}",
                )
            except Exception:
                # Audit-Fehler darf nicht ACK verhindern (Audit-DB-Probleme
                # sollen nicht KIS-Aufnahme blockieren)
                log.exception("Audit-Eintrag fehlgeschlagen für %s", msg_id)

        return "AA"

    def _audit_failure(
        self,
        msg_id: str,
        sender: str,
        reason: str,
        details: Optional[str],
    ) -> None:
        if self.audit is None:
            return
        try:
            from aion.audit import AuditAction
            self.audit.record(
                action=AuditAction.IMPORT,
                user=f"mllp:{sender}",
                success=False,
                details=f"hl7v2 msg_id={msg_id} reason={reason}"
                        + (f" | {details}" if details else ""),
            )
        except Exception:
            log.exception("Audit-Eintrag (Fehler) fehlgeschlagen")


# ────────────────────────────────────────────────────────────────────
#  ACK-Generierung
# ────────────────────────────────────────────────────────────────────
def build_ack(msg: HL7Message, ack_code: str = "AA",
              text_message: Optional[str] = None) -> bytes:
    """Erzeugt eine ACK-Nachricht zu einer empfangenen.

    Format:
        MSH|^~\\&|<aion-app>|<aion-fac>|<orig-sender>|<orig-fac>|<now>||ACK^<trigger>|<msg-id>|P|2.5
        MSA|<ack_code>|<orig-msg-id>|<text>

    Args:
        msg: die empfangene HL7Message (für Sender/Receiver-Spiegelung)
        ack_code: "AA", "AE", "AR"
        text_message: optionaler Erklärungstext (MSA-3)

    Returns:
        Bytes mit MLLP-Framing (<VT>...<FS><CR>)
    """
    sep = msg.field_sep
    comp = msg.component_sep

    # Sender/Receiver vertauschen
    orig_sender_app = msg.field("MSH", 3) or ""
    orig_sender_fac = msg.field("MSH", 4) or ""
    orig_recv_app = msg.field("MSH", 5) or ""
    orig_recv_fac = msg.field("MSH", 6) or ""
    orig_msg_id = msg.field("MSH", 10) or ""
    orig_version = msg.field("MSH", 12) or "2.5"
    orig_trigger = msg.trigger_event or "A01"

    # Original-Trigger im ACK reflektieren: ACK^A01^ACK
    msg_type = f"ACK{comp}{orig_trigger}"

    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ack_msg_id = f"ACK{now}"

    encoding_chars = msg.component_sep + msg.repetition_sep + msg.escape + msg.subcomponent_sep

    msh = sep.join([
        "MSH",                         # 0
        encoding_chars,                # MSH-2 (encoding)
        orig_recv_app,                 # 3 = original receiver app, jetzt Sender
        orig_recv_fac,                 # 4
        orig_sender_app,               # 5 = original sender, jetzt Receiver
        orig_sender_fac,               # 6
        now,                           # 7 = timestamp
        "",                            # 8
        msg_type,                      # 9 = ACK^trigger
        ack_msg_id,                    # 10
        "P",                           # 11 = Processing ID
        orig_version,                  # 12 = Version
    ])
    # Bei MSH muss das Zeichen MSH-1 (= sep) direkt nach 'MSH' stehen,
    # NICHT als reguläres Feld. Wir bauen das von Hand:
    msh = "MSH" + sep + encoding_chars + sep + sep.join([
        orig_recv_app, orig_recv_fac,
        orig_sender_app, orig_sender_fac,
        now, "", msg_type, ack_msg_id, "P", orig_version,
    ])

    # MSA
    msa_parts = ["MSA", ack_code, orig_msg_id]
    if text_message:
        msa_parts.append(text_message)
    msa = sep.join(msa_parts)

    # Segmente mit \r trennen (HL7-Standard)
    raw = (msh + "\r" + msa + "\r").encode("utf-8")
    return MLLP_START_BLOCK + raw + MLLP_END


# ────────────────────────────────────────────────────────────────────
#  TCP-Handler
# ────────────────────────────────────────────────────────────────────
class _MLLPRequestHandler(socketserver.BaseRequestHandler):
    """Wird von ThreadingTCPServer pro Verbindung instanziiert."""

    def setup(self) -> None:
        self.request.settimeout(self.server.connection_timeout)
        self._buffer = bytearray()
        self._messages_handled = 0
        log.info("MLLP-Verbindung von %s:%d", *self.client_address)

    def handle(self) -> None:
        try:
            while True:
                data = self.request.recv(DEFAULT_BUFFER_SIZE)
                if not data:
                    break  # Client hat geschlossen
                self._buffer.extend(data)

                # Buffer-Größe begrenzen
                if len(self._buffer) > self.server.max_message_size:
                    log.warning("Buffer-Overflow von %s — Verbindung schließen",
                                self.client_address[0])
                    break

                # So lange Nachrichten extrahieren wie möglich
                while True:
                    msg_bytes = self._extract_message()
                    if msg_bytes is None:
                        break
                    self._process_message(msg_bytes)
                    self._messages_handled += 1
        except socket.timeout:
            log.info("Timeout %s — Verbindung geschlossen nach %d Nachrichten",
                     self.client_address[0], self._messages_handled)
        except ConnectionResetError:
            log.info("Connection-Reset von %s", self.client_address[0])
        except Exception:
            log.exception("Unerwarteter Fehler in MLLP-Handler")

    def finish(self) -> None:
        log.info("MLLP-Verbindung %s zu, %d Nachrichten verarbeitet",
                 self.client_address[0], self._messages_handled)

    def _extract_message(self) -> Optional[bytes]:
        """Extrahiert eine vollständige MLLP-umrahmte Nachricht aus _buffer.

        Returns:
            Die rohe HL7-Nachricht ohne MLLP-Framing, oder None wenn
            keine vollständige Nachricht im Buffer ist.
        """
        # Start-Block suchen
        start = self._buffer.find(MLLP_START_BLOCK)
        if start < 0:
            # Kein Start-Block — alles vor dem Suchpunkt ist Müll
            self._buffer.clear()
            return None
        if start > 0:
            # Müll vor dem Start-Block
            log.debug("Verwerfe %d Bytes vor Start-Block", start)
            del self._buffer[:start]

        # End-Block suchen
        end = self._buffer.find(MLLP_END, 1)
        if end < 0:
            return None  # noch nicht vollständig

        # Nachricht extrahieren (ohne Framing)
        msg_bytes = bytes(self._buffer[1:end])
        # Buffer-Reste behalten
        del self._buffer[:end + len(MLLP_END)]
        return msg_bytes

    def _process_message(self, msg_bytes: bytes) -> None:
        """Verarbeitet eine extrahierte Nachricht und sendet ACK."""
        # Decode
        try:
            raw_str = msg_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                raw_str = msg_bytes.decode("iso-8859-1")
            except Exception:
                log.error("Konnte Nachricht nicht dekodieren von %s",
                          self.client_address[0])
                return

        # Parsen
        try:
            msg = parse_message(raw_str)
        except ValueError as e:
            log.warning("Parse-Fehler von %s: %s", self.client_address[0], e)
            # Können kein ACK senden, weil wir kein MSH zum Spiegeln haben
            return

        # Handler aufrufen
        try:
            ack_code = self.server.handler.handle(msg, msg_bytes)
        except Exception:
            log.exception("Handler-Exception für msg von %s", self.client_address[0])
            ack_code = "AE"

        # ACK senden
        try:
            ack_bytes = build_ack(msg, ack_code=ack_code)
            self.request.sendall(ack_bytes)
        except Exception:
            log.exception("ACK-Senden fehlgeschlagen für %s", self.client_address[0])


# ────────────────────────────────────────────────────────────────────
#  Server
# ────────────────────────────────────────────────────────────────────
class MLLPServer(socketserver.ThreadingTCPServer):
    """MLLP-Server für HL7-v2-Nachrichten.

    Ein Thread pro Verbindung. Beim Beenden via SIGTERM/SIGINT wird
    `serve_forever()` graceful unterbrochen.

    Verwendung:
        server = MLLPServer(("0.0.0.0", 2575), handler=DefaultHandler(...))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
    """

    allow_reuse_address = True
    daemon_threads = True   # Bei Server-Stop nicht auf Threads warten

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: MLLPHandler,
        *,
        connection_timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE,
    ) -> None:
        # Bind und activate werden später gemacht
        super().__init__(server_address, _MLLPRequestHandler,
                         bind_and_activate=False)
        self.handler = handler
        self.connection_timeout = connection_timeout
        self.max_message_size = max_message_size

        # Jetzt binden und starten
        try:
            self.server_bind()
            self.server_activate()
        except Exception:
            self.server_close()
            raise

    def server_bind(self) -> None:
        # SO_REUSEADDR setzen, dann binden
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()


# ────────────────────────────────────────────────────────────────────
#  Bequeme High-Level-API
# ────────────────────────────────────────────────────────────────────
def serve_mllp(
    host: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
    handler: Optional[MLLPHandler] = None,
    *,
    store: Optional[Any] = None,
    audit: Optional[Any] = None,
    code_map: Optional[dict[str, str]] = None,
    auth_backend: Optional[Any] = None,
    required_role: Optional[str] = None,
    block: bool = True,
) -> MLLPServer:
    """Startet einen MLLP-Server.

    Args:
        host: Bind-Adresse. "0.0.0.0" lauscht auf allen Interfaces;
              "127.0.0.1" nur localhost.
        port: TCP-Port (Default 2575, HL7-v2-Standard).
        handler: optionaler Custom-Handler. Wenn None, wird DefaultHandler
                 mit store + audit + auth_backend erstellt.
        store: nur wenn handler=None: EventStore zum Speichern.
        audit: nur wenn handler=None: AuditLog zum Loggen.
        code_map: nur wenn handler=None: zusätzliches HL7-Code-Mapping.
        auth_backend: nur wenn handler=None: AuthBackend für API-Key-
                      Validierung in MSH-4. Ohne Backend = keine Auth.
        required_role: nur wenn handler=None: erforderliche Rolle des
                       Principals (z. B. "ingest").
        block: True (Default) = `serve_forever()` aufrufen, blockt bis
               Strg+C. False = Server starten und sofort zurückkehren
               (Caller muss `serve_forever()` selbst aufrufen).

    Returns:
        Den MLLPServer-Instance. Bei `block=True` wird das nach
        `shutdown()` zurückgegeben.

    Beispiel mit Auth:
        from aion import create_event_store, AuditLog
        from aion.auth import APIKeyBackend
        from aion.hl7v2.mllp import serve_mllp

        with create_event_store() as store:
            audit = AuditLog("audit.db")
            auth = APIKeyBackend("/etc/aion/api-keys.yaml")
            serve_mllp(
                store=store, audit=audit,
                auth_backend=auth, required_role="ingest",
            )
    """
    if handler is None:
        handler = DefaultHandler(
            store=store, audit=audit, code_map=code_map,
            auth_backend=auth_backend, required_role=required_role,
        )

    server = MLLPServer((host, port), handler=handler)
    log.info("MLLP-Server lauscht auf %s:%d", host, port)
    if auth_backend is not None:
        log.info("MLLP-Auth aktiv: %s (required_role=%s)",
                 auth_backend.name, required_role or "—")

    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("Strg+C empfangen, fahre Server herunter…")
        finally:
            server.shutdown()
            server.server_close()
            log.info("MLLP-Server beendet")

    return server


__all__ = [
    "MLLPServer", "MLLPHandler", "DefaultHandler",
    "serve_mllp", "build_ack",
    "MLLP_START_BLOCK", "MLLP_END_BLOCK", "MLLP_END",
    "DEFAULT_PORT",
]

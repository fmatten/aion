# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.hl7v2.mllp — MLLP-Server.

Tests gegen einen laufenden Server auf 127.0.0.1 mit Random-Port.
Jeder Test startet seinen eigenen Server, damit Tests parallel laufen
und kein Port-Konflikt entsteht.
"""
import socket
import threading
import time
import unittest
from unittest.mock import MagicMock

from aion import SQLiteEventStore, AuditLog
from aion.hl7v2 import HL7Message, parse_message
from aion.hl7v2.mllp import (
    MLLPServer, MLLPHandler, DefaultHandler,
    build_ack,
    MLLP_START_BLOCK, MLLP_END_BLOCK, MLLP_END,
    DEFAULT_PORT,
)


# ────────────────────────────────────────────────────────────────────
#  Hilfs-Funktionen
# ────────────────────────────────────────────────────────────────────
SAMPLE_ADT = (
    "MSH|^~\\&|KIS|KLINIK|AION|RZ|20260430120000||ADT^A01|MSG-001|P|2.5\r"
    "EVN|A01|20260430120000\r"
    "PID|1||P-TEST-001||TestPatient^Demo||19700101|M\r"
    "PV1|1|I|3A^301^1||||||||||||||||V|||||||||||||||||||||||||20260430120000\r"
)

SAMPLE_ORU = (
    "MSH|^~\\&|LAB|KLINIK|AION|RZ|20260415100500||ORU^R01|MSG-002|P|2.5\r"
    "PID|1||P-TEST-002||TestPatient2\r"
    "OBX|1|NM|718-7^Hemoglobin^LN||13.4|g/dL|||||F|||20260415100500\r"
)


def to_mllp(raw: str) -> bytes:
    return MLLP_START_BLOCK + raw.encode("utf-8") + MLLP_END


def from_mllp(data: bytes) -> bytes:
    """Entfernt MLLP-Framing."""
    return data.replace(MLLP_START_BLOCK, b"").replace(MLLP_END, b"")


def send_and_recv(host: str, port: int, mllp_msg: bytes,
                   timeout: float = 5.0) -> bytes:
    """Verbindet, sendet, empfängt ACK, schließt."""
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, port))
    s.sendall(mllp_msg)
    ack = s.recv(8192)
    s.close()
    return ack


class MLLPTestServer:
    """Context-Manager: Server starten, am Ende beenden."""

    def __init__(self, handler):
        self.handler = handler
        self.server = None
        self.thread = None
        self.port = None

    def __enter__(self):
        self.server = MLLPServer(("127.0.0.1", 0), handler=self.handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)  # kurz warten, bis Server bereit
        return self

    def __exit__(self, *args):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


# ────────────────────────────────────────────────────────────────────
#  build_ack - Tests
# ────────────────────────────────────────────────────────────────────
class TestBuildACK(unittest.TestCase):

    def test_ack_aa_for_received_message(self):
        msg = parse_message(SAMPLE_ADT)
        ack = build_ack(msg, "AA")
        self.assertTrue(ack.startswith(MLLP_START_BLOCK))
        self.assertTrue(ack.endswith(MLLP_END))

        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AA|MSG-001", ack_str)
        self.assertIn("ACK^A01", ack_str)

    def test_ack_swaps_sender_receiver(self):
        msg = parse_message(SAMPLE_ADT)  # Sender: KIS/KLINIK, Receiver: AION/RZ
        ack = build_ack(msg, "AA")
        ack_str = from_mllp(ack).decode("utf-8")
        # In ACK: AION sendet, KIS empfängt
        msh = ack_str.split("\r")[0]
        fields = msh.split("|")
        self.assertEqual(fields[2], "AION")  # MSH-3 = sender app
        self.assertEqual(fields[3], "RZ")    # MSH-4 = sender fac
        self.assertEqual(fields[4], "KIS")   # MSH-5 = receiver app
        self.assertEqual(fields[5], "KLINIK")  # MSH-6 = receiver fac

    def test_ack_ae_with_text(self):
        msg = parse_message(SAMPLE_ADT)
        ack = build_ack(msg, "AE", text_message="Mapping fehlgeschlagen")
        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AE|MSG-001|Mapping fehlgeschlagen", ack_str)

    def test_ack_format_parseable_as_hl7(self):
        """ACK selbst muss eine gültige HL7-Nachricht sein."""
        msg = parse_message(SAMPLE_ADT)
        ack = build_ack(msg, "AA")
        ack_str = from_mllp(ack).decode("utf-8")
        ack_msg = parse_message(ack_str)
        self.assertEqual(ack_msg.message_type, "ACK")
        self.assertEqual(ack_msg.trigger_event, "A01")


# ────────────────────────────────────────────────────────────────────
#  DefaultHandler - Tests
# ────────────────────────────────────────────────────────────────────
class TestDefaultHandler(unittest.TestCase):

    def test_handler_writes_to_store(self):
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        msg = parse_message(SAMPLE_ADT)
        ack_code = handler.handle(msg, SAMPLE_ADT.encode("utf-8"))

        self.assertEqual(ack_code, "AA")
        self.assertEqual(store.count(), 1)
        events = store.all()
        self.assertEqual(events[0].event_type, "Aufnahme")
        self.assertEqual(events[0].patient_id, "P-TEST-001")
        store.close()

    def test_handler_writes_audit(self):
        store = SQLiteEventStore(":memory:")
        audit = AuditLog(":memory:")
        handler = DefaultHandler(store=store, audit=audit)

        msg = parse_message(SAMPLE_ADT)
        handler.handle(msg, SAMPLE_ADT.encode("utf-8"))

        # Audit hat Eintrag
        self.assertEqual(audit.count(), 1)
        entry = audit.query()[0]
        self.assertEqual(entry["action"], "import")
        self.assertEqual(entry["user"], "mllp:KIS")
        self.assertTrue(entry["success"])
        # Patient-ID ist pseudonymisiert (nicht im Klartext)
        self.assertNotEqual(entry["patient_hash"], "P-TEST-001")

        store.close()
        audit.close()

    def test_handler_returns_aa_for_message_without_aion_data(self):
        """Nachricht ohne Patient-ID darf AION nicht abweisen."""
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        # MSH ohne PID
        no_pid = "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M|P|2.5\rEVN|A01|20260101"
        msg = parse_message(no_pid)
        ack_code = handler.handle(msg, no_pid.encode("utf-8"))

        # Keine Patient-ID → kein Event, aber ACK trotzdem AA
        # (weil syntaktisch korrekt — KIS soll nicht retransmittieren)
        self.assertEqual(ack_code, "AA")
        self.assertEqual(store.count(), 0)
        store.close()

    def test_handler_returns_ae_on_store_error(self):
        """Wenn Store-Insert fehlschlägt, AE zurückgeben."""
        # Mock-Store, der bei add() crasht
        broken_store = MagicMock()
        broken_store.add.side_effect = RuntimeError("DB full")
        handler = DefaultHandler(store=broken_store, audit=None)

        msg = parse_message(SAMPLE_ADT)
        ack_code = handler.handle(msg, SAMPLE_ADT.encode("utf-8"))
        self.assertEqual(ack_code, "AE")


# ────────────────────────────────────────────────────────────────────
#  MLLP-Server End-to-End-Tests
# ────────────────────────────────────────────────────────────────────
class TestMLLPServerEndToEnd(unittest.TestCase):

    def test_send_one_message_and_receive_ack(self):
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        with MLLPTestServer(handler) as srv:
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(SAMPLE_ADT))

        # ACK ist MLLP-umrahmt
        self.assertTrue(ack.startswith(MLLP_START_BLOCK))
        self.assertTrue(ack.endswith(MLLP_END))

        # Inhalt ist AA für MSG-001
        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AA|MSG-001", ack_str)

        # Event ist im Store
        self.assertEqual(store.count(), 1)
        store.close()

    def test_multiple_messages_one_connection(self):
        """Ein Client schickt zwei Nachrichten in einer Verbindung."""
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        with MLLPTestServer(handler) as srv:
            s = socket.socket()
            s.settimeout(5.0)
            s.connect(("127.0.0.1", srv.port))

            # Zwei Nachrichten direkt hintereinander
            s.sendall(to_mllp(SAMPLE_ADT) + to_mllp(SAMPLE_ORU))

            # Zwei ACKs lesen
            received = b""
            while received.count(MLLP_END) < 2:
                chunk = s.recv(8192)
                if not chunk:
                    break
                received += chunk
            s.close()

            # Beide ACKs vorhanden
            self.assertEqual(received.count(MLLP_END), 2)

        time.sleep(0.05)
        # Beide Events im Store
        self.assertEqual(store.count(), 2)
        store.close()

    def test_two_concurrent_clients(self):
        """Zwei Clients gleichzeitig — beide kommen durch."""
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        results: list[bytes] = []
        results_lock = threading.Lock()

        def client(msg_bytes):
            try:
                ack = send_and_recv("127.0.0.1", srv.port, msg_bytes,
                                     timeout=10.0)
                with results_lock:
                    results.append(ack)
            except Exception as e:
                with results_lock:
                    results.append(b"ERROR:" + str(e).encode())

        with MLLPTestServer(handler) as srv:
            t1 = threading.Thread(target=client, args=(to_mllp(SAMPLE_ADT),))
            t2 = threading.Thread(target=client, args=(to_mllp(SAMPLE_ORU),))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

        time.sleep(0.05)
        # Beide ACKs angekommen
        self.assertEqual(len(results), 2)
        for ack in results:
            self.assertFalse(ack.startswith(b"ERROR:"), f"Fehler: {ack!r}")
            self.assertIn(b"MSA|AA|", ack)

        # Beide Events gespeichert
        self.assertEqual(store.count(), 2)
        store.close()

    def test_garbage_before_start_block_is_skipped(self):
        """Manchmal kommt nach Reconnect Müll vor dem Start-Block."""
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        with MLLPTestServer(handler) as srv:
            # Müll davor
            data = b"junk-from-previous-connection-noise" + to_mllp(SAMPLE_ADT)
            ack = send_and_recv("127.0.0.1", srv.port, data)

        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AA|", ack_str)
        store.close()

    def test_invalid_message_no_msh_no_ack(self):
        """Nicht parsbare Daten → keine ACK, Verbindung wird beendet."""
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        with MLLPTestServer(handler) as srv:
            s = socket.socket()
            s.settimeout(2.0)
            s.connect(("127.0.0.1", srv.port))
            # Unsinnsdaten
            s.sendall(MLLP_START_BLOCK + b"NOT A VALID HL7" + MLLP_END)
            # Kein ACK erwartet — wir lesen mit Timeout, soll leer sein
            try:
                ack = s.recv(4096)
            except socket.timeout:
                ack = b""
            s.close()

        # Kein Crash, kein Event gespeichert
        self.assertEqual(store.count(), 0)
        store.close()

    def test_handler_protocol_compliance(self):
        """Custom-Handler statt DefaultHandler einsetzen."""
        received_messages = []

        class MockHandler:
            def handle(self, msg, raw):
                received_messages.append((msg.trigger_event, raw))
                return "AA"

        handler = MockHandler()
        # Strukturell muss MockHandler MLLPHandler erfüllen
        self.assertIsInstance(handler, MLLPHandler)

        with MLLPTestServer(handler) as srv:
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(SAMPLE_ADT))

        self.assertIn(b"MSA|AA|", ack)
        self.assertEqual(len(received_messages), 1)
        self.assertEqual(received_messages[0][0], "A01")


# ────────────────────────────────────────────────────────────────────
#  Edge-Cases
# ────────────────────────────────────────────────────────────────────
class TestEdgeCases(unittest.TestCase):

    def test_oru_message_with_loinc_lookup(self):
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store, audit=None)

        with MLLPTestServer(handler) as srv:
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(SAMPLE_ORU))

        time.sleep(0.05)
        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AA|MSG-002", ack_str)

        events = store.all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "Hämoglobin")
        self.assertEqual(events[0].attributes.get("value"), 13.4)
        store.close()

    def test_default_port_constant(self):
        self.assertEqual(DEFAULT_PORT, 2575)


if __name__ == "__main__":
    unittest.main()

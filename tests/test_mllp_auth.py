# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Integration-Tests: MLLP-Listener + API-Key-Auth.

Testet das Zusammenspiel von DefaultHandler und APIKeyBackend.
"""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import yaml

from aion import SQLiteEventStore, AuditLog
from aion.auth import (
    APIKeyBackend, APIKeyCredentials,
    hash_api_key, generate_api_key,
)
from aion.hl7v2.mllp import (
    MLLPServer, DefaultHandler,
    MLLP_START_BLOCK, MLLP_END,
)


def to_mllp(raw: str) -> bytes:
    return MLLP_START_BLOCK + raw.encode("utf-8") + MLLP_END


def from_mllp(data: bytes) -> bytes:
    return data.replace(MLLP_START_BLOCK, b"").replace(MLLP_END, b"")


def send_and_recv(host, port, mllp_msg, timeout=5.0):
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, port))
    s.sendall(mllp_msg)
    ack = s.recv(8192)
    s.close()
    return ack


class _ServerCtx:
    """Context-Manager: MLLP-Server in Thread starten/stoppen."""

    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        self.server = MLLPServer(("127.0.0.1", 0), handler=self.handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        time.sleep(0.05)
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


def _make_message(*, sender_app="KIS", sender_fac="KLINIK", msg_id="MSG-001"):
    """Baut eine HL7-Nachricht. sender_fac = MSH-4 = unser Auth-Feld."""
    return (
        f"MSH|^~\\&|{sender_app}|{sender_fac}|AION|RZ|"
        f"20260430120000||ADT^A01|{msg_id}|P|2.5\r"
        "EVN|A01|20260430120000\r"
        "PID|1||P-AUTH-001||TestPatient^Demo||19700101|M\r"
        "PV1|1|I|3A^301^1||||||||||||||||V|||||||||||||||||||||||||"
        "20260430120000\r"
    )


class TestMLLPWithAPIKeyAuth(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="aion-mllp-auth-")
        self.keyfile = Path(self.tmpdir) / "keys.yaml"

        self.key_ingest = generate_api_key()
        self.key_readonly = generate_api_key()

        self.keyfile.write_text(yaml.safe_dump({
            "keys": [
                {
                    "name": "mirth-channel-1",
                    "hash": hash_api_key(self.key_ingest),
                    "roles": ["ingest"],
                },
                {
                    "name": "monitoring",
                    "hash": hash_api_key(self.key_readonly),
                    "roles": ["readonly"],
                },
            ]
        }))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_key_accepts(self):
        store = SQLiteEventStore(":memory:")
        auth = APIKeyBackend(self.keyfile)
        handler = DefaultHandler(
            store=store, auth_backend=auth, required_role="ingest",
        )

        with _ServerCtx(handler) as srv:
            # Key in MSH-4 = Sending Facility
            msg = _make_message(sender_fac=self.key_ingest)
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AA|MSG-001", ack_str)
        time.sleep(0.05)
        self.assertEqual(store.count(), 1)
        store.close()

    def test_invalid_key_rejects(self):
        store = SQLiteEventStore(":memory:")
        auth = APIKeyBackend(self.keyfile)
        handler = DefaultHandler(
            store=store, auth_backend=auth, required_role="ingest",
        )

        with _ServerCtx(handler) as srv:
            msg = _make_message(sender_fac="aion_FALSCHERSCHLUESSEL")
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        ack_str = from_mllp(ack).decode("utf-8")
        # AR = Application Reject
        self.assertIn("MSA|AR|MSG-001", ack_str)
        # Kein Event gespeichert
        self.assertEqual(store.count(), 0)
        store.close()

    def test_no_key_in_msh4_rejects(self):
        store = SQLiteEventStore(":memory:")
        auth = APIKeyBackend(self.keyfile)
        handler = DefaultHandler(
            store=store, auth_backend=auth, required_role="ingest",
        )

        with _ServerCtx(handler) as srv:
            # MSH-4 = "KLINIK" (kein aion_-Prefix)
            msg = _make_message(sender_fac="KLINIK")
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AR|", ack_str)
        self.assertEqual(store.count(), 0)
        store.close()

    def test_required_role_enforced(self):
        store = SQLiteEventStore(":memory:")
        auth = APIKeyBackend(self.keyfile)
        # required_role="ingest", aber wir verwenden den readonly-Key
        handler = DefaultHandler(
            store=store, auth_backend=auth, required_role="ingest",
        )

        with _ServerCtx(handler) as srv:
            msg = _make_message(sender_fac=self.key_readonly)
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        ack_str = from_mllp(ack).decode("utf-8")
        # AR weil falsche Rolle
        self.assertIn("MSA|AR|", ack_str)
        self.assertEqual(store.count(), 0)
        store.close()

    def test_audit_logs_authenticated_user(self):
        store = SQLiteEventStore(":memory:")
        audit = AuditLog(":memory:")
        auth = APIKeyBackend(self.keyfile)
        handler = DefaultHandler(
            store=store, audit=audit,
            auth_backend=auth, required_role="ingest",
        )

        with _ServerCtx(handler) as srv:
            msg = _make_message(sender_fac=self.key_ingest)
            send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        time.sleep(0.05)

        # Audit-Eintrag enthält den Principal-Namen, nicht den Sender-Header
        entries = audit.query()
        self.assertEqual(len(entries), 1)
        # User ist "mllp:mirth-channel-1" (aus Principal.user_id),
        # nicht "mllp:KIS" (aus MSH-3)
        self.assertEqual(entries[0]["user"], "mllp:mirth-channel-1")
        self.assertTrue(entries[0]["success"])

        store.close()
        audit.close()

    def test_audit_logs_failed_auth(self):
        store = SQLiteEventStore(":memory:")
        audit = AuditLog(":memory:")
        auth = APIKeyBackend(self.keyfile)
        handler = DefaultHandler(
            store=store, audit=audit,
            auth_backend=auth, required_role="ingest",
        )

        with _ServerCtx(handler) as srv:
            msg = _make_message(sender_fac="aion_INVALID")
            send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        time.sleep(0.05)

        entries = audit.query()
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0]["success"])
        self.assertIn("auth-failed", entries[0]["details"])

        store.close()
        audit.close()


class TestMLLPWithoutAuth(unittest.TestCase):
    """Sicherstellen, dass MLLP ohne auth_backend wie bisher funktioniert."""

    def test_no_auth_backend_means_no_auth_check(self):
        store = SQLiteEventStore(":memory:")
        handler = DefaultHandler(store=store)  # auth_backend=None

        with _ServerCtx(handler) as srv:
            # MSH-4 ist "KLINIK", kein API-Key
            msg = _make_message(sender_fac="KLINIK")
            ack = send_and_recv("127.0.0.1", srv.port, to_mllp(msg))

        ack_str = from_mllp(ack).decode("utf-8")
        self.assertIn("MSA|AA|", ack_str)
        time.sleep(0.05)
        self.assertEqual(store.count(), 1)
        store.close()


if __name__ == "__main__":
    unittest.main()

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Auth-Demo: API-Key-Erzeugung, Speicherung, MLLP-Integration.

Demonstriert die komplette Pipeline:
  1. API-Key generieren
  2. Gehashed in YAML-Datei speichern
  3. APIKeyBackend lädt Datei
  4. Erfolgreiche und fehlgeschlagene Auth zeigen
  5. MLLP-Listener mit Auth + Required-Role
"""
from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import yaml

from aion import SQLiteEventStore, AuditLog
from aion.auth import (
    APIKeyBackend, APIKeyCredentials,
    BadCredentials,
    generate_api_key, hash_api_key,
)
from aion.hl7v2.mllp import (
    MLLPServer, DefaultHandler,
    MLLP_START_BLOCK, MLLP_END,
)


def to_mllp(raw: str) -> bytes:
    return MLLP_START_BLOCK + raw.encode("utf-8") + MLLP_END


def from_mllp(data: bytes) -> bytes:
    return data.replace(MLLP_START_BLOCK, b"").replace(MLLP_END, b"")


def main() -> int:
    print("─── AION Auth Demo ────────────────────────────────────────")
    print()

    # 1. API-Keys generieren
    print("1. API-Keys generieren:")
    key_mirth = generate_api_key()
    key_monitor = generate_api_key()
    print(f"   mirth-channel-1: {key_mirth[:18]}…")
    print(f"   monitoring:      {key_monitor[:18]}…")
    print()

    # 2. YAML-Datei mit gehashten Keys
    tmpdir = tempfile.mkdtemp(prefix="aion-auth-demo-")
    keyfile = Path(tmpdir) / "api-keys.yaml"
    keyfile.write_text(yaml.safe_dump({
        "keys": [
            {"name": "mirth-channel-1",
             "hash": hash_api_key(key_mirth),
             "roles": ["ingest"]},
            {"name": "monitoring",
             "hash": hash_api_key(key_monitor),
             "roles": ["readonly"]},
        ]
    }))
    print(f"2. Keys (gehashed) gespeichert in {keyfile.name}")
    print()

    # 3. Backend laden und einzeln testen
    print("3. Backend lädt Keys, prüft:")
    backend = APIKeyBackend(keyfile)

    p1 = backend.authenticate(APIKeyCredentials(key_mirth))
    print(f"   ✓ {p1}")

    try:
        backend.authenticate(APIKeyCredentials("aion_FALSCHER_KEY"))
    except BadCredentials as e:
        print(f"   ✗ Falscher Key: {e}")
    print()

    # 4. MLLP-Listener mit Auth starten
    print("4. MLLP-Listener mit Auth + required_role='ingest':")
    store = SQLiteEventStore(":memory:")
    audit = AuditLog(":memory:")
    handler = DefaultHandler(
        store=store, audit=audit,
        auth_backend=backend, required_role="ingest",
    )

    server = MLLPServer(("127.0.0.1", 0), handler=handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.05)
    print(f"   Server: 127.0.0.1:{port}")
    print()

    # 5. Drei Test-Nachrichten: gültig, ungültig, falsche Rolle
    def send_msg(label: str, key_in_msh4: str, expected_ack: str):
        msg = (
            f"MSH|^~\\&|TEST|{key_in_msh4}|AION|RZ|"
            f"20260430120000||ADT^A01|MSG-{label}|P|2.5\r"
            "EVN|A01|20260430120000\r"
            "PID|1||P-DEMO-001||TestPatient\r"
            "PV1|1|I|3A^301^1||||||||||||||||V|||||||||||||||||||||||||"
            "20260430120000\r"
        )
        s = socket.socket()
        s.settimeout(5.0)
        s.connect(("127.0.0.1", port))
        s.sendall(to_mllp(msg))
        ack = s.recv(8192)
        s.close()
        ack_str = from_mllp(ack).decode("utf-8")
        # MSA-Zeile finden
        for line in ack_str.split("\r"):
            if line.startswith("MSA"):
                print(f"   {label}: {line[:50]:50s}  (erwartet: MSA|{expected_ack}|...)")
                break

    print("5. Sende drei Test-Nachrichten:")
    send_msg("VALID", key_mirth,            "AA")
    send_msg("WRONG-KEY", "aion_FALSCH",    "AR")
    send_msg("WRONG-ROLE", key_monitor,     "AR")
    print()

    time.sleep(0.1)
    print(f"6. Im Store: {store.count()} Event(s)")
    print(f"   Audit-Einträge: {audit.count()}")
    for entry in audit.query():
        ok = "✓" if entry["success"] else "✗"
        print(f"   {ok} user={entry['user']:30s} success={bool(entry['success'])}")

    server.shutdown()
    server.server_close()
    store.close()
    audit.close()

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print("─── Demo abgeschlossen ────────────────────────────────────")
    print()
    print("In Production:")
    print("  aion auth keygen --name mirth-1 --roles ingest")
    print("  aion mllp-listen --auth-keys /etc/aion/api-keys.yaml \\")
    print("                   --auth-role ingest --port 2575")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""MLLP-Demo: Server und Client in einem Prozess.

Startet einen MLLP-Server in einem Background-Thread, schickt eine
Test-Nachricht aus den 1.8.0-Fixtures, zeigt das ACK und das resultierende
Event im Store.

Für realen Einsatz:
    aion mllp-listen --host 0.0.0.0 --port 2575 --db klinik.db --audit audit.db
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

from aion import SQLiteEventStore, AuditLog
from aion.hl7v2.mllp import (
    MLLPServer, DefaultHandler,
    MLLP_START_BLOCK, MLLP_END,
)


FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hl7v2" / "adt_a01_aufnahme.hl7"


def main() -> int:
    print("─── MLLP-Demo ─────────────────────────────────────────────")
    print()

    # 1. Setup: Store + Audit + Handler
    store = SQLiteEventStore(":memory:")
    audit = AuditLog(":memory:")
    handler = DefaultHandler(store=store, audit=audit)

    # 2. Server auf Random-Port starten
    server = MLLPServer(("127.0.0.1", 0), handler=handler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(f"1. MLLP-Server gestartet auf 127.0.0.1:{port}")
    time.sleep(0.1)

    # 3. Test-Nachricht aus Fixture schicken
    if not FIXTURE.exists():
        print(f"✗ Fixture fehlt: {FIXTURE}")
        return 1

    raw_msg = FIXTURE.read_bytes()
    # Datei-Inhalt enthält evtl. \n statt \r — normalisieren
    raw_msg = raw_msg.replace(b"\r\n", b"\r").replace(b"\n", b"\r")
    mllp_msg = MLLP_START_BLOCK + raw_msg + MLLP_END

    print(f"2. Sende Test-Nachricht ({len(raw_msg)} bytes HL7) "
          f"als MLLP-Frame ({len(mllp_msg)} bytes)")

    s = socket.socket()
    s.settimeout(5.0)
    s.connect(("127.0.0.1", port))
    s.sendall(mllp_msg)

    ack = s.recv(4096)
    s.close()

    print(f"3. ACK empfangen ({len(ack)} bytes):")
    ack_clean = ack.replace(MLLP_START_BLOCK, b"").replace(MLLP_END, b"")
    for line in ack_clean.decode("utf-8").replace("\r", "\n").splitlines():
        if line.strip():
            print(f"   {line}")

    # 4. Kurz warten, damit Handler durch ist
    time.sleep(0.1)

    print(f"\n4. Events im Store: {store.count()}")
    for e in store.all():
        print(f"   {e.t_start.strftime('%H:%M')}  {e.event_type:25s}  "
              f"Patient={e.patient_id}")

    print(f"\n5. Audit-Einträge: {audit.count()}")
    for entry in audit.query():
        print(f"   {entry['timestamp'][:19]}  {entry['action']}  "
              f"user={entry['user']}  success={bool(entry['success'])}")

    # 5. Aufräumen
    server.shutdown()
    server.server_close()
    store.close()
    audit.close()

    print("\n─── Demo abgeschlossen ────────────────────────────────────")
    print()
    print("Realer Einsatz:")
    print("  aion mllp-listen --host 0.0.0.0 --port 2575 \\")
    print("                   --db /var/lib/aion-stack/aion-data/aion.db \\")
    print("                   --audit /var/lib/aion-stack/aion-data/audit.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

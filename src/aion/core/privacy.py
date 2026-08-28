# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Datenschutz-Helfer für AION Clinical.

Designentscheidungen für 1.0.0 (production-ready):

  * **Logs enthalten nie Klartext-Patient-IDs.**
    `pseudonymize(patient_id)` liefert einen stabilen, kurzen Hash,
    der innerhalb einer Session reidentifizierbar ist (für Debugging),
    aber außerhalb nicht auf den echten Patienten zurückführt.
  * **Datei-Pfade werden basenamed.**
    `safe_path()` gibt nur den Datei-Namen aus, nicht den vollen Pfad —
    der könnte Klinik-Namen oder Nutzer-Verzeichnisse enthalten.
  * **Reversibel ist nichts.**
    Es ist absichtlich keine Möglichkeit eingebaut, aus einem Pseudonym
    den Klartext zurückzugewinnen. Wer mappen will, baut sich seine
    eigene Lookup-Tabelle.

Das ist ein **Logging-Helfer**, keine vollständige Datenschutz-Lösung.
DSGVO-Compliance erfordert mehr (Audit-Trail, Löschkonzept, Zweckbindung).
Dieses Modul deckt nur die häufigste Schwachstelle ab: zufälliges
Klartext-Logging beim Debuggen.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Union


# Session-spezifischer Salt: identisch innerhalb eines Prozesses,
# unterschiedlich zwischen Prozessen. Damit kann man im selben Log
# zwei Einträge zum selben Patienten korrelieren, aber zwei Logs
# verschiedener Prozesse nicht zusammenführen.
_SESSION_SALT: bytes = secrets.token_bytes(16)


def pseudonymize(value: Union[str, int, None], length: int = 8) -> str:
    """Erzeugt ein stabiles Pseudonym für eine ID.

    Innerhalb derselben Python-Session liefert dieselbe Eingabe immer
    dasselbe Pseudonym. Über Sessions hinweg sind die Pseudonyme nicht
    korrelierbar (anderer Salt).

    Args:
        value: Patient-ID, Event-ID o. ä.
        length: Länge des Pseudonyms in Zeichen (default 8 Hex-Zeichen).

    Returns:
        z. B. "p#a3f7b21c" für patient_id "P-12345"
    """
    if value is None:
        return "p#none"
    payload = str(value).encode("utf-8")
    digest = hashlib.blake2b(payload, key=_SESSION_SALT, digest_size=length // 2 + 1).hexdigest()
    return f"p#{digest[:length]}"


def safe_path(path: Union[str, Path, None]) -> str:
    """Reduziert einen Datei-Pfad auf den Basisnamen für Logging.

    Volle Pfade können sensitive Informationen enthalten:
      /home/dr-mueller/klinik-XYZ/patients.db  →  patients.db
      C:\\Users\\Admin\\Sepsis-Studie\\data.db  →  data.db

    Funktioniert plattformunabhängig: behandelt sowohl /-Trenner
    (POSIX) als auch \\-Trenner (Windows), unabhängig vom Host-OS.
    """
    if path is None:
        return "<none>"
    s = str(path)
    if s == ":memory:":
        return s
    # Beide Trennzeichen normalisieren, dann letzten Komponenten nehmen
    last = s.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return last or "<root>"


def fingerprint_dict(data: dict, max_keys: int = 5) -> str:
    """Liefert einen kompakten Fingerabdruck eines Dicts ohne die Werte.

    Für Logs nützlich: man sieht welche Schlüssel vorkommen,
    aber keine konkreten Werte (die könnten Patient-Daten sein).

      {"patient_id": "P-1", "lactate": 4.2, "stemi": True}
        →  "{patient_id, lactate, stemi}"
    """
    if not data:
        return "{}"
    keys = sorted(data.keys())
    if len(keys) > max_keys:
        shown = ", ".join(keys[:max_keys])
        return f"{{{shown}, +{len(keys) - max_keys} more}}"
    return "{" + ", ".join(keys) + "}"


def reset_session_salt() -> None:
    """Nur für Tests: Session-Salt neu generieren.

    In Produktion **nie** aufrufen — würde laufende Korrelations-IDs
    in der gleichen Session unbrauchbar machen.
    """
    global _SESSION_SALT
    _SESSION_SALT = secrets.token_bytes(16)

# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Zentrales Logging-Setup für AION Clinical.

Designentscheidungen:

  * Stdlib `logging` — keine zusätzliche Abhängigkeit.
  * Per Default: WARNING auf stderr, kein Rauschen für CLI-Nutzer.
  * Mit `setup_logging(level="DEBUG")` oder via Umgebungsvariable
    `AION_LOG_LEVEL=DEBUG`: ausführliches Tracing.
  * GUI nutzt zusätzlich einen RotatingFileHandler in
    `~/.aion/aion-gui.log` — falls bei der Vorführung etwas schiefgeht,
    haben wir eine Spur.
  * Idempotent: mehrfacher Aufruf von `setup_logging()` doppelt keine
    Handler. Wichtig, weil Tests und Tools mehrfach aufrufen können.

Verwendung in Modulen:

    from aion.core.logging_setup import get_logger
    log = get_logger(__name__)
    log.info("etwas passiert")
    log.exception("Fehler bei Operation X")  # mit Traceback

Verwendung in der GUI:

    from aion.core.logging_setup import setup_logging, get_logger
    setup_logging(file_logging=True)  # einmal beim Start
    log = get_logger(__name__)
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_INITIALIZED = False
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str = "aion") -> logging.Logger:
    """Liefert einen Logger für ein Modul.

    Üblicher Aufruf am Modul-Anfang:
        log = get_logger(__name__)
    """
    return logging.getLogger(name)


def setup_logging(
    level: Optional[str] = None,
    *,
    file_logging: bool = False,
    log_path: Optional[Path] = None,
) -> Path | None:
    """Initialisiert das AION-Logging einmalig.

    Args:
        level: "DEBUG", "INFO", "WARNING", "ERROR". Wenn None, wird die
               Umgebungsvariable AION_LOG_LEVEL gelesen, default "WARNING".
        file_logging: Wenn True, zusätzlich in eine Datei loggen
                      (default: ~/.aion/aion-gui.log).
        log_path: Eigener Log-Datei-Pfad (überstimmt Default).

    Returns:
        Pfad der Logdatei, falls file_logging aktiv, sonst None.
    """
    global _INITIALIZED

    # Level-Bestimmung
    if level is None:
        level = os.environ.get("AION_LOG_LEVEL", "WARNING").upper()
    numeric_level = getattr(logging, level, logging.WARNING)

    root = logging.getLogger("aion")
    root.setLevel(numeric_level)

    # Idempotenz: bestehende AION-Handler entfernen
    if _INITIALIZED:
        for h in list(root.handlers):
            root.removeHandler(h)

    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    # ── Konsolen-Handler (stderr) ─────────────────────────────────
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # ── Datei-Handler (optional) ──────────────────────────────────
    log_file: Path | None = None
    if file_logging:
        if log_path is None:
            log_path = Path.home() / ".aion" / "aion-gui.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=2 * 1024 * 1024,  # 2 MB
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)  # Datei sieht alles
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
            log_file = log_path
        except OSError as e:
            # File-Logging nicht kritisch — Konsole reicht
            root.warning(f"File-Logging deaktiviert: {e}")

    # Library-Verhalten: logging.captureWarnings für Konsistenz
    logging.captureWarnings(True)

    _INITIALIZED = True
    root.debug(f"Logging initialisiert (level={level}, file={log_file})")
    return log_file


def reset_logging() -> None:
    """Nur für Tests: Logging-State zurücksetzen."""
    global _INITIALIZED
    root = logging.getLogger("aion")
    for h in list(root.handlers):
        root.removeHandler(h)
    _INITIALIZED = False

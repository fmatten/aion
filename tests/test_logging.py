# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.core.logging_setup."""
import logging
import os
import tempfile
import unittest
from pathlib import Path

from aion.core.logging_setup import get_logger, setup_logging, reset_logging


class TestLoggingSetup(unittest.TestCase):

    def setUp(self):
        reset_logging()
        # Vor jedem Test sicherstellen, dass keine Umgebungsvariable stört
        self._old_env = os.environ.pop("AION_LOG_LEVEL", None)

    def tearDown(self):
        reset_logging()
        if self._old_env is not None:
            os.environ["AION_LOG_LEVEL"] = self._old_env

    def test_get_logger_returns_named_logger(self):
        log = get_logger("aion.test")
        self.assertEqual(log.name, "aion.test")

    def test_setup_default_level_is_warning(self):
        setup_logging()
        root = logging.getLogger("aion")
        self.assertEqual(root.level, logging.WARNING)

    def test_setup_with_debug_level(self):
        setup_logging(level="DEBUG")
        root = logging.getLogger("aion")
        self.assertEqual(root.level, logging.DEBUG)

    def test_env_variable_sets_level(self):
        os.environ["AION_LOG_LEVEL"] = "INFO"
        try:
            setup_logging()
            self.assertEqual(logging.getLogger("aion").level, logging.INFO)
        finally:
            del os.environ["AION_LOG_LEVEL"]

    def test_idempotent_setup(self):
        """Mehrfacher Aufruf darf keine doppelten Handler erzeugen."""
        setup_logging(level="INFO")
        n_before = len(logging.getLogger("aion").handlers)
        setup_logging(level="INFO")
        n_after = len(logging.getLogger("aion").handlers)
        self.assertEqual(n_before, n_after)

    def test_file_logging_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "test.log"
            result = setup_logging(level="DEBUG",
                                   file_logging=True,
                                   log_path=log_path)
            self.assertEqual(result, log_path)
            log = get_logger("aion.test")
            log.info("Test-Eintrag")
            # Handler flushen
            for h in logging.getLogger("aion").handlers:
                h.flush()
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("Test-Eintrag", content)

    def test_invalid_level_falls_back_to_warning(self):
        setup_logging(level="QUATSCH")
        # Sollte nicht crashen
        self.assertEqual(logging.getLogger("aion").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()

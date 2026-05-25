# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Tests für aion.config — Konfigurations-Schicht."""
import os
import tempfile
import unittest
from pathlib import Path

from aion.config import (
    AionConfig, StorageConfig, PrivacyConfig, LoggingConfig,
    AuthConfig, PerformanceConfig, ValidationConfig,
    ConfigError,
    load_config, validate_config,
    get_config, set_config, reset_config,
    _substitute_env,
)


class TestEnvSubstitution(unittest.TestCase):

    def setUp(self):
        # Saubere env, damit Tests reproduzierbar sind
        for k in ("TEST_VAR", "AION_TEST_SALT"):
            os.environ.pop(k, None)

    def test_simple_substitution(self):
        os.environ["TEST_VAR"] = "world"
        try:
            self.assertEqual(_substitute_env("hello ${TEST_VAR}"), "hello world")
        finally:
            os.environ.pop("TEST_VAR")

    def test_default_when_unset(self):
        # Var ist nicht gesetzt, default greift
        result = _substitute_env("${UNDEFINED_VAR:-fallback}")
        self.assertEqual(result, "fallback")

    def test_empty_when_unset_no_default(self):
        result = _substitute_env("${UNDEFINED_NO_DEFAULT}")
        self.assertEqual(result, "")

    def test_recursive_in_dict(self):
        os.environ["TEST_VAR"] = "VALUE"
        try:
            data = {"a": "${TEST_VAR}", "b": ["${TEST_VAR}", "static"]}
            result = _substitute_env(data)
            self.assertEqual(result["a"], "VALUE")
            self.assertEqual(result["b"], ["VALUE", "static"])
        finally:
            os.environ.pop("TEST_VAR")

    def test_non_string_passes_through(self):
        self.assertEqual(_substitute_env(42), 42)
        self.assertEqual(_substitute_env(True), True)
        self.assertEqual(_substitute_env(None), None)

    def test_multiple_in_one_string(self):
        os.environ["A"] = "x"
        os.environ["B"] = "y"
        try:
            result = _substitute_env("${A} und ${B}")
            self.assertEqual(result, "x und y")
        finally:
            os.environ.pop("A"); os.environ.pop("B")


class TestDefaults(unittest.TestCase):

    def test_default_config_passes_validation(self):
        cfg = AionConfig()
        errors = validate_config(cfg)
        self.assertEqual(errors, [])

    def test_default_storage_paths(self):
        cfg = AionConfig()
        self.assertEqual(cfg.storage.database, "aion.db")
        self.assertEqual(cfg.storage.audit, "audit.db")

    def test_default_log_level_is_info(self):
        cfg = AionConfig()
        self.assertEqual(cfg.logging.level, "INFO")

    def test_default_auth_is_none(self):
        cfg = AionConfig()
        self.assertEqual(cfg.auth.backend, "none")


class TestValidation(unittest.TestCase):

    def test_invalid_log_level(self):
        cfg = AionConfig(logging=LoggingConfig(level="WRONG"))
        errors = validate_config(cfg)
        self.assertTrue(any("logging.level" in e for e in errors))

    def test_invalid_log_format(self):
        cfg = AionConfig(logging=LoggingConfig(format="xml"))
        errors = validate_config(cfg)
        self.assertTrue(any("logging.format" in e for e in errors))

    def test_invalid_auth_backend(self):
        cfg = AionConfig(auth=AuthConfig(backend="basic"))
        errors = validate_config(cfg)
        self.assertTrue(any("auth.backend" in e for e in errors))

    def test_ldap_without_server_fails(self):
        cfg = AionConfig(auth=AuthConfig(backend="ldap"))  # ldap_server fehlt
        errors = validate_config(cfg)
        self.assertTrue(any("ldap_server" in e for e in errors))

    def test_oidc_without_issuer_fails(self):
        cfg = AionConfig(auth=AuthConfig(backend="oidc"))
        errors = validate_config(cfg)
        self.assertTrue(any("oidc_issuer" in e for e in errors))

    def test_negative_retention_fails(self):
        cfg = AionConfig(privacy=PrivacyConfig(audit_retention_days=-1))
        errors = validate_config(cfg)
        self.assertTrue(any("audit_retention_days" in e for e in errors))

    def test_pattern_length_below_2_fails(self):
        cfg = AionConfig(performance=PerformanceConfig(max_pattern_length=1))
        errors = validate_config(cfg)
        self.assertTrue(any("max_pattern_length" in e for e in errors))

    def test_postgres_url_without_at_fails(self):
        cfg = AionConfig(storage=StorageConfig(database="postgresql://noathost"))
        errors = validate_config(cfg)
        self.assertTrue(any("PostgreSQL" in e for e in errors))


class TestYAMLLoading(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="aion-config-test-")
        self.path = Path(self._tmpdir) / "test.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        # env-Vars aufräumen
        for k in ("AION_CONFIG_FILE", "TEST_DB", "TEST_SALT"):
            os.environ.pop(k, None)

    def _write(self, content: str):
        self.path.write_text(content, encoding="utf-8")

    def test_load_simple_yaml(self):
        self._write("""
storage:
  database: /var/test.db
logging:
  level: DEBUG
""")
        cfg = load_config(self.path)
        self.assertEqual(cfg.storage.database, "/var/test.db")
        self.assertEqual(cfg.logging.level, "DEBUG")

    def test_load_with_env_substitution(self):
        os.environ["TEST_DB"] = "/var/from-env.db"
        self._write("""
storage:
  database: ${TEST_DB}
""")
        cfg = load_config(self.path)
        self.assertEqual(cfg.storage.database, "/var/from-env.db")

    def test_load_with_env_default(self):
        # TEST_SALT ist nicht gesetzt → default greift
        self._write("""
privacy:
  salt: ${TEST_SALT:-default-salt-value}
""")
        cfg = load_config(self.path)
        self.assertEqual(cfg.privacy.salt, "default-salt-value")

    def test_unknown_fields_ignored(self):
        """Unbekannte YAML-Felder dürfen nicht crashen."""
        self._write("""
storage:
  database: /test.db
  unknown_field: xyz
unknown_section:
  foo: bar
""")
        cfg = load_config(self.path)
        self.assertEqual(cfg.storage.database, "/test.db")

    def test_empty_yaml_uses_defaults(self):
        self._write("")
        cfg = load_config(self.path)
        self.assertEqual(cfg.storage.database, "aion.db")  # Default

    def test_invalid_yaml_top_level(self):
        self._write("nur ein string")
        with self.assertRaises(ConfigError):
            load_config(self.path)

    def test_validation_failure_raises(self):
        self._write("""
logging:
  level: WRONG_LEVEL
""")
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.path)
        self.assertIn("logging.level", str(ctx.exception))

    def test_skip_validation(self):
        """Mit validate=False kommen ungültige Werte durch."""
        self._write("""
logging:
  level: WRONG_LEVEL
""")
        cfg = load_config(self.path, validate=False)
        self.assertEqual(cfg.logging.level, "WRONG_LEVEL")

    def test_skip_env_substitution(self):
        os.environ["TEST_SALT"] = "should-not-be-used"
        self._write("""
privacy:
  salt: ${TEST_SALT}
""")
        cfg = load_config(self.path, substitute_env=False)
        # Mit substitute_env=False bleibt der Platzhalter im String
        self.assertEqual(cfg.privacy.salt, "${TEST_SALT}")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_config("/tmp/does-not-exist-aion.yaml")


class TestNoFileLoad(unittest.TestCase):

    def setUp(self):
        for k in ("AION_CONFIG_FILE",):
            os.environ.pop(k, None)
        reset_config()

    def tearDown(self):
        reset_config()

    def test_no_path_no_env_returns_defaults(self):
        cfg = load_config()
        # Defaults
        self.assertEqual(cfg.storage.database, "aion.db")

    def test_aion_config_file_env_var_used(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                          delete=False) as f:
            f.write("storage:\n  database: /from-env-var.db\n")
            path = f.name
        try:
            os.environ["AION_CONFIG_FILE"] = path
            cfg = load_config()
            self.assertEqual(cfg.storage.database, "/from-env-var.db")
        finally:
            os.environ.pop("AION_CONFIG_FILE", None)
            Path(path).unlink()


class TestSingleton(unittest.TestCase):

    def setUp(self):
        reset_config()

    def tearDown(self):
        reset_config()

    def test_get_returns_default_lazy(self):
        cfg = get_config()
        self.assertIsInstance(cfg, AionConfig)

    def test_set_overrides(self):
        custom = AionConfig(storage=StorageConfig(database="/override.db"))
        set_config(custom)
        self.assertEqual(get_config().storage.database, "/override.db")

    def test_get_returns_same_instance(self):
        cfg1 = get_config()
        cfg2 = get_config()
        self.assertIs(cfg1, cfg2)

    def test_reset_clears(self):
        custom = AionConfig(storage=StorageConfig(database="/before-reset.db"))
        set_config(custom)
        reset_config()
        cfg = get_config()
        self.assertEqual(cfg.storage.database, "aion.db")  # Default zurück


class TestRoundTrip(unittest.TestCase):

    def test_to_dict_contains_all_sections(self):
        cfg = AionConfig()
        d = cfg.to_dict()
        for key in ("storage", "privacy", "logging", "auth", "performance", "validation"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()

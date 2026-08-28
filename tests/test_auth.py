# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.auth — alle Backend-Varianten und Factory."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from aion.auth import (
    AuthBackend, Principal,
    APIKeyBackend, APIKeyCredentials, APIKeyEntry,
    NoneAuthBackend,
    PasswordCredentials, TokenCredentials,
    AuthError, BadCredentials, BackendError,
    hash_api_key, verify_api_key, generate_api_key,
    create_auth_backend,
)
from aion.config import AionConfig, AuthConfig


# ────────────────────────────────────────────────────────────────────
#  Hash / Verify / Generate
# ────────────────────────────────────────────────────────────────────
class TestHashing(unittest.TestCase):

    def test_generate_key_format(self):
        k = generate_api_key()
        self.assertTrue(k.startswith("aion_"))
        # base32 ohne Padding, ca. 52 Chars (32 bytes → 52 base32)
        self.assertGreaterEqual(len(k), 50)
        self.assertLess(len(k), 60)

    def test_generate_keys_are_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        self.assertEqual(len(keys), 100)

    def test_hash_format(self):
        h = hash_api_key("test-key")
        parts = h.split("$")
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], "blake2b")
        # Salt 16 bytes hex = 32 chars; digest 32 bytes hex = 64 chars
        self.assertEqual(len(parts[1]), 32)
        self.assertEqual(len(parts[2]), 64)

    def test_verify_correct_key(self):
        key = generate_api_key()
        h = hash_api_key(key)
        self.assertTrue(verify_api_key(key, h))

    def test_verify_wrong_key(self):
        h = hash_api_key("right-key")
        self.assertFalse(verify_api_key("wrong-key", h))

    def test_verify_malformed_hash(self):
        self.assertFalse(verify_api_key("any", "not-a-hash"))
        self.assertFalse(verify_api_key("any", "blake2b$bad"))
        self.assertFalse(verify_api_key("any", "md5$xxx$yyy"))

    def test_same_key_different_salts_different_hashes(self):
        h1 = hash_api_key("same-key")
        h2 = hash_api_key("same-key")
        self.assertNotEqual(h1, h2)
        # Beide aber verifizieren
        self.assertTrue(verify_api_key("same-key", h1))
        self.assertTrue(verify_api_key("same-key", h2))


# ────────────────────────────────────────────────────────────────────
#  Principal-Datenklasse
# ────────────────────────────────────────────────────────────────────
class TestPrincipal(unittest.TestCase):

    def test_principal_basic_fields(self):
        p = Principal(user_id="alice", display_name="Alice",
                      backend="apikey", roles=frozenset({"admin"}))
        self.assertEqual(p.user_id, "alice")
        self.assertTrue(p.has_role("admin"))
        self.assertFalse(p.has_role("physician"))

    def test_principal_repr_no_secrets(self):
        p = Principal(user_id="alice", display_name="Alice",
                      backend="apikey", roles=frozenset({"admin"}))
        s = repr(p)
        self.assertIn("alice", s)
        self.assertNotIn("password", s.lower())

    def test_password_credentials_repr_hides_password(self):
        c = PasswordCredentials("alice", "geheim")
        s = repr(c)
        self.assertIn("alice", s)
        self.assertNotIn("geheim", s)
        self.assertIn("***", s)

    def test_apikey_credentials_repr_truncates(self):
        c = APIKeyCredentials("aion_VERYLONGAPIKEY1234567890")
        s = repr(c)
        # Vollständiger Key NICHT im repr
        self.assertNotIn("VERYLONGAPIKEY1234567890", s)
        # Aber Prefix für Debug
        self.assertIn("aion_", s)


# ────────────────────────────────────────────────────────────────────
#  None-Backend
# ────────────────────────────────────────────────────────────────────
class TestNoneBackend(unittest.TestCase):

    def test_returns_anonymous(self):
        backend = NoneAuthBackend()
        p = backend.authenticate(APIKeyCredentials("any"))
        self.assertEqual(p.user_id, "anonymous")
        self.assertEqual(p.backend, "none")

    def test_implements_protocol(self):
        backend = NoneAuthBackend()
        self.assertIsInstance(backend, AuthBackend)

    def test_supports_anything(self):
        backend = NoneAuthBackend()
        self.assertTrue(backend.supports(APIKeyCredentials("x")))
        self.assertTrue(backend.supports(PasswordCredentials("u", "p")))
        self.assertTrue(backend.supports(TokenCredentials("t")))


# ────────────────────────────────────────────────────────────────────
#  APIKey-Backend
# ────────────────────────────────────────────────────────────────────
class TestAPIKeyBackend(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="aion-auth-test-")
        self.keyfile = Path(self.tmpdir) / "keys.yaml"

        self.key_mirth = generate_api_key()
        self.key_monitoring = generate_api_key()
        self.key_expired = generate_api_key()

        data = {
            "keys": [
                {
                    "name": "mirth-channel-1",
                    "hash": hash_api_key(self.key_mirth),
                    "roles": ["ingest"],
                },
                {
                    "name": "monitoring",
                    "hash": hash_api_key(self.key_monitoring),
                    "roles": ["readonly"],
                    "expires": (date.today() + timedelta(days=30)).isoformat(),
                },
                {
                    "name": "old-key",
                    "hash": hash_api_key(self.key_expired),
                    "roles": ["ingest"],
                    "expires": (date.today() - timedelta(days=1)).isoformat(),
                },
            ]
        }
        self.keyfile.write_text(yaml.safe_dump(data))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_loads_keys_from_file(self):
        backend = APIKeyBackend(self.keyfile)
        self.assertEqual(len(backend._keys), 3)

    def test_authenticate_valid_key(self):
        backend = APIKeyBackend(self.keyfile)
        p = backend.authenticate(APIKeyCredentials(self.key_mirth))
        self.assertEqual(p.user_id, "mirth-channel-1")
        self.assertIn("ingest", p.roles)
        self.assertEqual(p.backend, "apikey")

    def test_authenticate_with_roles(self):
        backend = APIKeyBackend(self.keyfile)
        p = backend.authenticate(APIKeyCredentials(self.key_monitoring))
        self.assertEqual(p.user_id, "monitoring")
        self.assertIn("readonly", p.roles)

    def test_authenticate_unknown_key(self):
        backend = APIKeyBackend(self.keyfile)
        with self.assertRaises(BadCredentials):
            backend.authenticate(APIKeyCredentials("aion_nonexistent"))

    def test_authenticate_empty_key(self):
        backend = APIKeyBackend(self.keyfile)
        with self.assertRaises(BadCredentials):
            backend.authenticate(APIKeyCredentials(""))

    def test_authenticate_expired_key(self):
        backend = APIKeyBackend(self.keyfile)
        with self.assertRaises(BadCredentials) as ctx:
            backend.authenticate(APIKeyCredentials(self.key_expired))
        self.assertIn("abgelaufen", str(ctx.exception))

    def test_authenticate_wrong_credential_type(self):
        backend = APIKeyBackend(self.keyfile)
        with self.assertRaises(BadCredentials):
            backend.authenticate(PasswordCredentials("u", "p"))

    def test_supports_only_apikey(self):
        backend = APIKeyBackend(self.keyfile)
        self.assertTrue(backend.supports(APIKeyCredentials("x")))
        self.assertFalse(backend.supports(PasswordCredentials("u", "p")))
        self.assertFalse(backend.supports(TokenCredentials("t")))

    def test_missing_file_raises_backend_error(self):
        with self.assertRaises(BackendError):
            APIKeyBackend("/nonexistent/path/keys.yaml")

    def test_malformed_yaml_raises_backend_error(self):
        bad_file = Path(self.tmpdir) / "bad.yaml"
        bad_file.write_text("not: valid: yaml: structure: [unclosed")
        with self.assertRaises(BackendError):
            APIKeyBackend(bad_file)

    def test_protocol_compliance(self):
        backend = APIKeyBackend(self.keyfile)
        self.assertIsInstance(backend, AuthBackend)

    def test_reload_picks_up_changes(self):
        backend = APIKeyBackend(self.keyfile)
        original_count = len(backend._keys)

        # Schreibe neue Datei mit nur 1 Key
        new_key = generate_api_key()
        self.keyfile.write_text(yaml.safe_dump({
            "keys": [{
                "name": "only-one",
                "hash": hash_api_key(new_key),
                "roles": [],
            }]
        }))

        backend.reload()
        self.assertEqual(len(backend._keys), 1)
        # Alter Key funktioniert nicht mehr
        with self.assertRaises(BadCredentials):
            backend.authenticate(APIKeyCredentials(self.key_mirth))
        # Neuer Key funktioniert
        p = backend.authenticate(APIKeyCredentials(new_key))
        self.assertEqual(p.user_id, "only-one")

    def test_skips_malformed_entries_but_loads_valid(self):
        bad_file = Path(self.tmpdir) / "mixed.yaml"
        valid_key = generate_api_key()
        bad_file.write_text(yaml.safe_dump({
            "keys": [
                "not-a-dict",  # ungültig
                {"name": "missing-hash"},  # KeyError
                {  # gültig
                    "name": "good",
                    "hash": hash_api_key(valid_key),
                    "roles": ["ingest"],
                },
            ]
        }))
        backend = APIKeyBackend(bad_file)
        # Nur der gültige Eintrag sollte geladen sein
        self.assertEqual(len(backend._keys), 1)
        self.assertEqual(backend._keys[0].name, "good")


# ────────────────────────────────────────────────────────────────────
#  Factory
# ────────────────────────────────────────────────────────────────────
class TestCreateAuthBackend(unittest.TestCase):

    def test_factory_default_is_none_backend(self):
        cfg = AionConfig()  # auth.backend = "none"
        backend = create_auth_backend(cfg)
        self.assertIsInstance(backend, NoneAuthBackend)

    def test_factory_apikey(self):
        tmpdir = tempfile.mkdtemp()
        try:
            keyfile = Path(tmpdir) / "keys.yaml"
            keyfile.write_text(yaml.safe_dump({"keys": []}))
            cfg = AionConfig(auth=AuthConfig(
                backend="apikey",
                apikey_file=str(keyfile),
            ))
            backend = create_auth_backend(cfg)
            self.assertIsInstance(backend, APIKeyBackend)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_factory_apikey_missing_file_config(self):
        cfg = AionConfig(auth=AuthConfig(backend="apikey"))
        with self.assertRaises(BackendError):
            create_auth_backend(cfg)

    def test_factory_unknown_backend_raises(self):
        cfg = AionConfig(auth=AuthConfig(backend="invented"))
        with self.assertRaises(BackendError):
            create_auth_backend(cfg)


# ────────────────────────────────────────────────────────────────────
#  LDAP-Backend (Mock-only)
# ────────────────────────────────────────────────────────────────────
class TestLDAPBackend(unittest.TestCase):
    """Mock-Tests, weil kein echter LDAP-Server.

    Diese Tests prüfen die Logik unseres Wrappers, NICHT die echte
    LDAP-Konnektivität — die muss bei Inbetriebnahme separat verifiziert
    werden.
    """

    def setUp(self):
        try:
            import ldap3  # noqa
            self.has_ldap3 = True
        except ImportError:
            self.has_ldap3 = False

    def test_ldap_backend_without_ldap3_raises_clear_error(self):
        if self.has_ldap3:
            self.skipTest("ldap3 ist installiert — kann ImportError-Pfad nicht testen")
        from aion.auth.ldap_backend import LDAPBackend, LDAPConfig
        with self.assertRaises(BackendError) as ctx:
            LDAPBackend(LDAPConfig(server="ldap://x"))
        self.assertIn("ldap3", str(ctx.exception))

    def test_ldap_supports_password_credentials(self):
        if not self.has_ldap3:
            self.skipTest("ldap3 nicht installiert")
        from aion.auth.ldap_backend import LDAPBackend, LDAPConfig
        backend = LDAPBackend(LDAPConfig(server="ldap://x"))
        self.assertTrue(backend.supports(PasswordCredentials("u", "p")))
        self.assertFalse(backend.supports(APIKeyCredentials("k")))


# ────────────────────────────────────────────────────────────────────
#  OIDC-Backend (Mock-only)
# ────────────────────────────────────────────────────────────────────
class TestOIDCBackend(unittest.TestCase):

    def setUp(self):
        try:
            import authlib  # noqa
            import requests  # noqa
            self.has_oidc = True
        except ImportError:
            self.has_oidc = False

    def test_oidc_backend_without_libs_raises_clear_error(self):
        if self.has_oidc:
            self.skipTest("authlib/requests installiert — kann nicht testen")
        from aion.auth.oidc import OIDCBackend, OIDCConfig
        with self.assertRaises(BackendError) as ctx:
            OIDCBackend(OIDCConfig(issuer="https://x"))
        self.assertIn("authlib", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

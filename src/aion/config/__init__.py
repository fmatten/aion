# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""AION Clinical — Konfigurations-Schicht.

Designentscheidungen für 1.6.0:

  * **stdlib-only**: dataclasses + PyYAML (das schon da ist).
    Kein pydantic, kein attrs.
  * **YAML-zentriert**: eine `aion.yaml`-Datei für alle Settings.
    Default-Pfad: `$AION_CONFIG_FILE` oder `aion.yaml` im CWD.
  * **env-var-Substitution**: `${VAR}` und `${VAR:-default}` werden
    beim Laden ersetzt. Damit landen Secrets nicht im YAML, sondern
    werden zur Laufzeit injiziert.
  * **Validierung beim Laden**: Pflichtfelder, zulässige Werte,
    konsistente Pfade. Fehler werden früh und klar gemeldet.
  * **Singleton via get_config()**: globaler Zugriff, aber überschreibbar
    in Tests durch `set_config()`.

Verwendung:

    # Default: lädt aus $AION_CONFIG_FILE oder Defaults
    from aion.config import get_config
    cfg = get_config()
    print(cfg.storage.database)

    # Aus expliziter Datei
    from aion.config import load_config
    cfg = load_config("aion-prod.yaml")

    # Programmatisch (für Tests)
    from aion.config import AionConfig, StorageConfig, set_config
    set_config(AionConfig(storage=StorageConfig(database="/tmp/test.db")))
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, Union

from aion.core.logging_setup import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
#  env-var-Substitution
# ─────────────────────────────────────────────────────────────────────
_ENV_PATTERN = re.compile(
    r'\$\{'             # ${
    r'([A-Z_][A-Z0-9_]*)'  # VAR_NAME
    r'(?::-([^}]*))?'   # :-default (optional)
    r'\}'               # }
)


def _substitute_env(value: Any) -> Any:
    """Ersetzt rekursiv ${VAR} und ${VAR:-default} in Strings.

    Listen und Dicts werden rekursiv durchlaufen. Andere Typen
    bleiben unangetastet.
    """
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default)
        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    return value


# ─────────────────────────────────────────────────────────────────────
#  Konfigurations-Schemata (dataclasses)
# ─────────────────────────────────────────────────────────────────────
@dataclass
class StorageConfig:
    """Persistenz-Settings.

    Attributes:
        database: Pfad zur Haupt-DB. Bei PostgreSQL (ab 1.7.0):
                  postgresql://user:pass@host/db. Bei SQLite ein Pfad.
        audit: Pfad zur Audit-Log-DB (separat).
        wal: SQLite WAL-Mode aktivieren. Bei NFS/Netzlaufwerken false.
    """
    database: str = "aion.db"
    audit: str = "audit.db"
    wal: bool = True


@dataclass
class PrivacyConfig:
    """Datenschutz-Settings."""
    # Salt für pseudonymize() — in Production aus Secret-Store kommen lassen
    salt: str = ""
    # Wie lange werden Audit-Einträge aufbewahrt? (Tage)
    # DSGVO-Aufbewahrungsfrist je nach Rechtsgrundlage 6 Monate bis 30 Jahre
    audit_retention_days: int = 3650


@dataclass
class LoggingConfig:
    level: str = "INFO"        # DEBUG, INFO, WARNING, ERROR
    format: str = "text"       # "text" oder "json"
    file: Optional[str] = None
    rotate_max_mb: int = 100
    rotate_keep: int = 7


@dataclass
class AuthConfig:
    """Authentifizierung — Backend-Auswahl und -Konfiguration.

    Stub seit 1.6.0, voll aktivierbar seit 1.10.0.
    """
    backend: str = "none"  # "none", "apikey", "ldap", "oidc"

    # API-Key-Backend
    apikey_file: Optional[str] = None  # z. B. /etc/aion/api-keys.yaml

    # LDAP/AD-Backend
    ldap_server: Optional[str] = None  # z. B. ldaps://ad.klinik.local
    ldap_base_dn: Optional[str] = None  # behält Rückwärts-Kompatibilität
    ldap_bind_dn_template: str = "${user}@example.com"
    ldap_use_ssl: bool = True
    ldap_start_tls: bool = False
    ldap_timeout: float = 10.0
    ldap_search_base: Optional[str] = None
    ldap_group_filter: Optional[str] = None
    ldap_role_mapping: dict = field(default_factory=dict)

    # OIDC-Backend
    oidc_issuer: Optional[str] = None  # z. B. https://idp.tld/realms/aion
    oidc_audience: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_jwks_uri: Optional[str] = None
    oidc_jwks_cache_ttl: int = 3600
    oidc_roles_claim: str = "realm_access.roles"
    oidc_user_id_claim: str = "preferred_username"
    oidc_display_name_claim: str = "name"
    oidc_leeway: int = 30


@dataclass
class PerformanceConfig:
    max_pattern_length: int = 6
    db_pool_size: int = 10


@dataclass
class ValidationConfig:
    """Klinische Plausibilitäts-Settings (geplant 1.8.0)."""
    enable_value_ranges: bool = False
    ranges_file: Optional[str] = None
    code_map_file: Optional[str] = None


@dataclass
class AionConfig:
    """Vollständige AION-Konfiguration."""
    storage: StorageConfig = field(default_factory=StorageConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)

    def to_dict(self) -> dict:
        """Serialisiert als reines Dict (für YAML-Dump)."""
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────
#  Validierung
# ─────────────────────────────────────────────────────────────────────
class ConfigError(ValueError):
    """Wird geworfen, wenn die Konfiguration ungültig ist."""


_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_VALID_LOG_FORMATS = {"text", "json"}
_VALID_AUTH_BACKENDS = {"none", "apikey", "ldap", "oidc"}


def validate_config(cfg: AionConfig) -> list[str]:
    """Prüft die Konfiguration auf Konsistenz.

    Returns:
        Liste von Fehlermeldungen. Leer = OK.
    """
    errors: list[str] = []

    # Logging
    if cfg.logging.level not in _VALID_LOG_LEVELS:
        errors.append(
            f"logging.level: {cfg.logging.level!r} ungültig — "
            f"muss in {sorted(_VALID_LOG_LEVELS)} sein"
        )
    if cfg.logging.format not in _VALID_LOG_FORMATS:
        errors.append(
            f"logging.format: {cfg.logging.format!r} ungültig — "
            f"muss in {sorted(_VALID_LOG_FORMATS)} sein"
        )
    if cfg.logging.rotate_max_mb < 1:
        errors.append(f"logging.rotate_max_mb muss > 0 sein")
    if cfg.logging.rotate_keep < 0:
        errors.append(f"logging.rotate_keep muss ≥ 0 sein")

    # Auth
    if cfg.auth.backend not in _VALID_AUTH_BACKENDS:
        errors.append(
            f"auth.backend: {cfg.auth.backend!r} ungültig — "
            f"muss in {sorted(_VALID_AUTH_BACKENDS)} sein"
        )
    if cfg.auth.backend == "apikey" and not cfg.auth.apikey_file:
        errors.append("auth.backend=apikey aber auth.apikey_file fehlt")
    if cfg.auth.backend == "ldap" and not cfg.auth.ldap_server:
        errors.append("auth.backend=ldap aber auth.ldap_server fehlt")
    if cfg.auth.backend == "oidc" and not cfg.auth.oidc_issuer:
        errors.append("auth.backend=oidc aber auth.oidc_issuer fehlt")

    # Privacy
    if cfg.privacy.audit_retention_days < 1:
        errors.append("privacy.audit_retention_days muss > 0 sein")

    # Performance
    if cfg.performance.max_pattern_length < 2:
        errors.append("performance.max_pattern_length muss ≥ 2 sein")
    if cfg.performance.db_pool_size < 1:
        errors.append("performance.db_pool_size muss ≥ 1 sein")

    # Storage — Database-URL grob plausibel
    if cfg.storage.database.startswith("postgresql://"):
        # Postgres-URL grob prüfen
        if "@" not in cfg.storage.database:
            errors.append("storage.database: PostgreSQL-URL braucht @host-Teil")

    return errors


# ─────────────────────────────────────────────────────────────────────
#  Loader
# ─────────────────────────────────────────────────────────────────────
def load_config(
    path: Optional[Union[str, Path]] = None,
    *,
    substitute_env: bool = True,
    validate: bool = True,
) -> AionConfig:
    """Lädt eine Konfigurationsdatei.

    Args:
        path: Pfad zur YAML-Datei. Wenn None: $AION_CONFIG_FILE oder
              Defaults (alles auf default-Werten).
        substitute_env: env-var-Platzhalter ersetzen (default True).
        validate: nach dem Laden auf Konsistenz prüfen (default True).

    Returns:
        AionConfig-Instanz.

    Raises:
        FileNotFoundError: explizit angegebene Datei existiert nicht.
        ConfigError: Datei ist ungültig oder Validierung scheitert.
    """
    if path is None:
        env_path = os.environ.get("AION_CONFIG_FILE")
        if env_path:
            path = env_path
        else:
            log.debug("Keine Config-Datei angegeben, nutze Defaults.")
            return AionConfig()

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config-Datei nicht gefunden: {path}")

    try:
        import yaml
    except ImportError as e:
        raise ConfigError("PyYAML wird für Config-Loading benötigt") from e

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ConfigError(f"Config-Datei muss ein Dict sein, ist {type(raw).__name__}")

    if substitute_env:
        raw = _substitute_env(raw)

    cfg = _build_config(raw)

    if validate:
        errors = validate_config(cfg)
        if errors:
            raise ConfigError(
                f"Config-Validierung fehlgeschlagen:\n  - " + "\n  - ".join(errors)
            )

    log.info("Konfiguration geladen aus %s", path)
    return cfg


def _build_config(raw: dict) -> AionConfig:
    """Baut AionConfig aus rohem Dict; ignoriert unbekannte Felder."""
    storage = StorageConfig(**_filter(raw.get("storage", {}), StorageConfig))
    privacy = PrivacyConfig(**_filter(raw.get("privacy", {}), PrivacyConfig))
    logging_cfg = LoggingConfig(**_filter(raw.get("logging", {}), LoggingConfig))
    auth = AuthConfig(**_filter(raw.get("auth", {}), AuthConfig))
    performance = PerformanceConfig(**_filter(raw.get("performance", {}), PerformanceConfig))
    validation_cfg = ValidationConfig(**_filter(raw.get("validation", {}), ValidationConfig))
    return AionConfig(
        storage=storage, privacy=privacy, logging=logging_cfg,
        auth=auth, performance=performance, validation=validation_cfg,
    )


def _filter(d: dict, cls) -> dict:
    """Filtert ein Dict auf nur die Felder, die die dataclass kennt."""
    if not isinstance(d, dict):
        return {}
    valid = {f.name for f in cls.__dataclass_fields__.values()}
    return {k: v for k, v in d.items() if k in valid}


# ─────────────────────────────────────────────────────────────────────
#  Singleton-Zugriff
# ─────────────────────────────────────────────────────────────────────
_active_config: Optional[AionConfig] = None


def get_config() -> AionConfig:
    """Liefert die aktive Konfiguration (lädt sie beim ersten Aufruf).

    Wenn keine via set_config() gesetzt wurde, lädt entweder aus
    $AION_CONFIG_FILE oder mit Default-Werten.
    """
    global _active_config
    if _active_config is None:
        _active_config = load_config()
    return _active_config


def set_config(cfg: AionConfig) -> None:
    """Setzt die aktive Konfiguration explizit (für Tests, Init-Code)."""
    global _active_config
    _active_config = cfg


def reset_config() -> None:
    """Setzt die globale Config zurück (forciert Reload beim nächsten get)."""
    global _active_config
    _active_config = None


__all__ = [
    "AionConfig", "StorageConfig", "PrivacyConfig", "LoggingConfig",
    "AuthConfig", "PerformanceConfig", "ValidationConfig",
    "ConfigError",
    "load_config", "validate_config",
    "get_config", "set_config", "reset_config",
]

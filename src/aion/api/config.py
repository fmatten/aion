# aion/api/config.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
from __future__ import annotations
import os


class Settings:
    """Konfiguration aus Umgebungsvariablen."""

    AION_ENV:      str  = os.environ.get("AION_ENV",      "development")
    AION_DB_URL:   str  = os.environ.get("AION_DB_URL",
        "postgresql+asyncpg://aion:aion@localhost:5432/aion_clinical")
    AION_REDIS_URL: str = os.environ.get("AION_REDIS_URL", "redis://localhost:6379/0")
    AION_SECRET_KEY: str = os.environ.get("AION_SECRET_KEY", "dev-secret-change-me")

    # OIDC / Keycloak
    OIDC_ISSUER:    str  = os.environ.get(
        "AION_OIDC_ISSUER",
        "http://keycloak:8080/realms/aion"   # Docker-interner Hostname
    )
    OIDC_CLIENT_ID: str  = os.environ.get("AION_OIDC_CLIENT_ID", "aion-api")
    AUTH_ENABLED:   bool = os.environ.get(
        "AION_AUTH_ENABLED", "false"
    ).lower() == "true"

    # DB Pool
    DB_POOL_MIN: int = int(os.environ.get("AION_DB_POOL_MIN", "2"))
    DB_POOL_MAX: int = int(os.environ.get("AION_DB_POOL_MAX", "10"))

    # MLLP
    MLLP_ENABLED: bool = os.environ.get("AION_MLLP_ENABLED", "false").lower() == "true"
    MLLP_HOST:    str  = os.environ.get("AION_MLLP_HOST", "0.0.0.0")
    MLLP_PORT:    int  = int(os.environ.get("AION_MLLP_PORT", "2575"))

    # Differential Privacy
    DP_EPSILON: float = float(os.environ.get("AION_DP_EPSILON", "10.0"))

    @property
    def CORS_ORIGINS(self) -> list[str]:
        raw = os.environ.get("AION_CORS_ORIGINS", "*")
        return ["*"] if raw == "*" else [o.strip() for o in raw.split(",")]


settings = Settings()

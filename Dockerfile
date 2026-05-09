# syntax=docker/dockerfile:1.6
# AION Clinical — Production Container
#
# Multi-stage Build:
#   Stage 1 (builder): installiert Build-Dependencies und baut Wheel
#   Stage 2 (runtime): minimaler Runtime, läuft als non-root user
#
# Verwendung:
#   docker build -t aion-clinical:1.5.0 .
#   docker run --rm -p 8080:8080 -v aion-data:/var/lib/aion aion-clinical:1.5.0
#
# Größe: ca. 180 MB final (slim-bookworm + Python deps).
# Security: non-root, no shell tools, minimum packages.

# ─────────────────────────────────────────────────────────────────
# Stage 1 — Builder
# ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System-Dependencies nur für Build (gcc nur falls benötigt)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Source kopieren
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Wheel bauen
RUN pip install --upgrade pip build && \
    python -m build --wheel --outdir /wheels

# Optional-Dependencies vorbauen — verify (Z3) und fhir, kein dowhy
# (zu schwer, ~200 MB). DoWhy bleibt Opt-In via separatem Image-Tag.
RUN pip install --prefix=/install \
        /wheels/aion_clinical-*.whl[verify,fhir]


# ─────────────────────────────────────────────────────────────────
# Stage 2 — Runtime
# ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="" \
    AION_DATA_DIR=/var/lib/aion \
    AION_LOG_LEVEL=INFO \
    AION_AUDIT_PATH=/var/lib/aion/audit.db \
    AION_DB_PATH=/var/lib/aion/aion.db

# CA-Zertifikate für TLS, sonst keine zusätzlichen Pakete.
# tini als PID-1-Wrapper, damit Signal-Handling sauber ist.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root user anlegen
RUN groupadd --system --gid 10001 aion && \
    useradd --system --uid 10001 --gid aion --no-create-home --shell /usr/sbin/nologin aion

# Python-Pakete aus Builder kopieren
COPY --from=builder /install /usr/local

# Daten-Verzeichnis (Volume mount-target)
RUN mkdir -p /var/lib/aion && \
    chown -R aion:aion /var/lib/aion

USER aion
WORKDIR /var/lib/aion

# Health-Check: einfacher Versions-Aufruf
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD aion --version || exit 1

# Entrypoint via tini, default-CLI ist `aion`
ENTRYPOINT ["/usr/bin/tini", "--", "aion"]
CMD ["--help"]

# OCI-Labels
LABEL org.opencontainers.image.title="AION Clinical" \
      org.opencontainers.image.description="Klinische Verlaufs-Analyse: Knowledge-Graph, Pattern-Mining, Causal Inference" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://example.org/aion-clinical" \
      org.opencontainers.image.version="1.5.0"

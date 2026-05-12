# aion/api/app.py
# Copyright © 2026 Friedhelm Matten / ISCaD GmbH – EUPL-1.2
from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from aion.api.config import settings

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown. Fehler werden geloggt, stoppen aber nicht den Start."""

    # 1. PostgreSQL-Pool
    app.state.store = None
    try:
        from aion.persist.postgres_store import PostgresEventStore
        store = PostgresEventStore(
            settings.AION_DB_URL,
            pool_min=settings.DB_POOL_MIN,
            pool_max=settings.DB_POOL_MAX,
        )
        await store.__aenter__()
        app.state.store = store
        log.info("PostgreSQL verbunden")
    except Exception as exc:
        log.error("PostgreSQL nicht erreichbar: %s – API startet ohne Store", exc)

    # 2. Redis
    app.state.redis = None
    try:
        import redis.asyncio as aioredis
        app.state.redis = await aioredis.from_url(
            settings.AION_REDIS_URL, socket_connect_timeout=3
        )
        await app.state.redis.ping()
        log.info("Redis verbunden: %s", settings.AION_REDIS_URL)
    except Exception as exc:
        log.warning("Redis nicht erreichbar: %s", exc)

    # 3. SchemaRegistry
    from aion.schema_registry import VersionedSchemaRegistry, SchemaVersion
    from datetime import datetime, timezone
    registry = VersionedSchemaRegistry()
    if app.state.store:
        try:
            await registry.load_all(app.state.store._pool)
        except Exception as exc:
            log.warning("SchemaRegistry-DB-Laden fehlgeschlagen: %s", exc)
    if "v1.0" not in registry._versions:
        registry.register(SchemaVersion(
            version_id="v1.0",
            t_begin=datetime(2026, 1, 1, tzinfo=timezone.utc),
            t_end=None,
            description="Initiale AION-Produktionsversion",
        ))
    app.state.schema_registry = registry
    log.info("SchemaRegistry bereit – aktive Version: %s",
             registry.current().version_id)


    # 4. Differential Privacy Engine (§20)
    from aion.privacy.dp import PrivacyBudget, DPQueryEngine
    import os
    dp_epsilon = float(os.environ.get("AION_DP_EPSILON", "10.0"))
    app.state.dp_engine = DPQueryEngine(PrivacyBudget(dp_epsilon))
    log.info("DP-Engine bereit: epsilon_ges=%.1f", dp_epsilon)


    # 5b. TrajectoryPredictor (§21.5b) – startet leer, wird via /trajectories/fit trainiert
    from aion.ai.trajectories import TrajectoryPredictor
    app.state.trajectory_predictor = TrajectoryPredictor(order=1)

    # Trajektorien-Modell aus Redis laden falls vorhanden (Persistenz v1.1.0-D)
    if app.state.redis is not None:
        try:
            import json as _json
            raw = await app.state.redis.get("aion:trajectory:model")
            if raw:
                payload = _json.loads(raw)
                app.state.trajectory_predictor.load_dict(payload.get("predictor", {}))
                log.info("Trajektorien-Modell aus Redis geladen")
        except Exception as exc:
            log.warning("Trajektorien-Modell konnte nicht geladen werden: %s", exc)

    log.info("TrajectoryPredictor bereit (§21.5b) – noch nicht trainiert")

    # 6. MLLP (optional)
    mllp_task = None
    if settings.MLLP_ENABLED and app.state.redis and app.state.store:
        import asyncio
        from aion.api.mllp_worker import start_mllp_server
        mllp_task = asyncio.create_task(
            start_mllp_server(app.state.store, app.state.redis)
        )
        log.info("MLLP-Listener gestartet auf %s:%d",
                 settings.MLLP_HOST, settings.MLLP_PORT)

    log.info("AION API bereit (ENV=%s)", settings.AION_ENV)
    yield

    # Shutdown
    if mllp_task:
        mllp_task.cancel()
    if app.state.redis:
        try:
            await app.state.redis.close()
        except Exception:
            pass
    if app.state.store:
        try:
            await app.state.store.__aexit__(None, None, None)
        except Exception:
            pass
    log.info("AION API heruntergefahren")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AION Clinical API",
        description=(
            "Formale Wissensrepräsentation für klinische Verläufe. "
            "Referenzimplementierung AION-Paper DOI: 10.5281/zenodo.19548857"
        ),
        version="1.10.3",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-Session-ID"],
    )

    # Router einbinden
    from aion.api.routes import events, fhir, verify, causal, schema as sr, cohorts, explain, causal_learn, mllp, federation_remote
    app.include_router(events.router, prefix="/events",  tags=["Events"])
    app.include_router(fhir.router,   prefix="/fhir",    tags=["FHIR"])
    app.include_router(verify.router, prefix="/verify",  tags=["Verifikation"])
    app.include_router(causal.router, prefix="/causal",  tags=["Kausal"])
    app.include_router(sr.router,     prefix="/schema",  tags=["Schema"])
    app.include_router(cohorts.router,      prefix="/cohorts",  tags=["Kohorten (DP)"])
    app.include_router(explain.router,      prefix="/explain",  tags=["Erklaerbarkeit §22"])
    app.include_router(causal_learn.router, prefix="/causal-learn", tags=["Kausallernen §15"])
    app.include_router(mllp.router,         prefix="/mllp",         tags=["MLLP HL7v2"])
    app.include_router(federation_remote.router, prefix="/federation", tags=["Foederierung §20.7"])

    # Health-Endpunkte – antworten IMMER, auch ohne DB
    @app.get("/health", tags=["Ops"])
    async def health():
        db_ok = app.state.store is not None
        redis_ok = app.state.redis is not None
        return {
            "status":  "ok",
            "version": "1.10.3",
            "env":     settings.AION_ENV,
            "db":      "connected" if db_ok    else "unavailable",
            "redis":   "connected" if redis_ok else "unavailable",
        }

    @app.get("/health/db", tags=["Ops"])
    async def health_db():
        if app.state.store is None:
            return {"db": "unavailable"}
        try:
            result = await app.state.store.health()
            return result
        except Exception as exc:
            return {"db": "error", "detail": str(exc)}

    # Prometheus /metrics Endpunkt

    # Prometheus /metrics Endpunkt
    @app.get("/metrics", tags=["Ops"])
    async def metrics_endpoint():
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        from fastapi.responses import Response
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app

app = create_app()

# aion/api/metrics.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Prometheus-Metriken für AION Clinical API."""

try:
    from prometheus_client import Counter, Histogram, Gauge, Summary

    # §4 Events
    events_created = Counter(
        "aion_events_created_total",
        "Klinische Ereignisse angelegt",
        ["type"],
    )
    query_duration = Histogram(
        "aion_query_duration_seconds",
        "Abfrage-Laufzeit nach Endpunkt",
        ["endpoint"],
        buckets=[0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0],
    )

    # §20 Differential Privacy
    dp_budget_remaining = Gauge(
        "aion_dp_budget_remaining",
        "Verbleibendes Differential-Privacy-Budget (§20)",
    )
    dp_queries_total = Counter(
        "aion_dp_queries_total",
        "DP-Abfragen nach Typ und Epsilon-Bereich",
        ["query_type", "epsilon_range"],
    )

    # MLLP HL7v2
    mllp_messages = Counter(
        "aion_mllp_messages_total",
        "Empfangene HL7v2-Nachrichten",
        ["message_type", "status"],
    )
    mllp_queue_length = Gauge(
        "aion_mllp_queue_length",
        "Aktuelle MLLP-Queue-Länge",
    )
    mllp_dlq_length = Gauge(
        "aion_mllp_dlq_length",
        "Dead-Letter-Queue Länge",
    )

    # §19 FHIR
    fhir_imports = Counter(
        "aion_fhir_imports_total",
        "FHIR Bundle Importe",
        ["status"],
    )
    fhir_exports = Counter(
        "aion_fhir_exports_total",
        "FHIR Bundle Exporte",
        ["status"],
    )

    # §21 KI
    ai_extractions = Counter(
        "aion_ai_extractions_total",
        "KI-Textextraktionen (§21.4)",
        ["status"],
    )
    ai_risk_scores = Histogram(
        "aion_ai_risk_score",
        "Risikoschätzung-Verteilung (§21.7)",
        buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    )
    ai_anomalies = Counter(
        "aion_ai_anomalies_total",
        "Erkannte Anomalien (§21.6)",
        ["level"],
    )

    # §18 Schema
    schema_migrations = Counter(
        "aion_schema_migrations_total",
        "Ausgeführte Schemamigrationen",
        ["from_version", "to_version", "status"],
    )

    # Verifikation
    verify_calls = Counter(
        "aion_verify_calls_total",
        "Schemaverifikationsaufrufe",
        ["result"],
    )



    # §21.5 Trajektorien
    trajectory_fits = Counter(
        "aion_trajectory_fits_total",
        "Trajektorienmodell-Trainings",
        ["status"],
    )
    trajectory_predictions = Counter(
        "aion_trajectory_predictions_total",
        "Trajektorien-Vorhersagen (§21.5b)",
        ["confidence_level"],
    )

    # API allgemein
    api_requests_total = Counter(
        "aion_api_requests_total",
        "API-Anfragen gesamt",
        ["method", "endpoint", "status_code"],
    )

except ImportError:
    class _Stub:
        def labels(self, **_): return self
        def __call__(self, *_, **__): return self
        def inc(self, *_): pass
        def observe(self, *_): pass
        def set(self, *_): pass
        def time(self): return _StubCtx()

    class _StubCtx:
        def __enter__(self): return self
        def __exit__(self, *_): pass

    events_created      = _Stub()
    query_duration      = _Stub()
    dp_budget_remaining = _Stub()
    dp_queries_total    = _Stub()
    mllp_messages       = _Stub()
    mllp_queue_length   = _Stub()
    mllp_dlq_length     = _Stub()
    fhir_imports        = _Stub()
    fhir_exports        = _Stub()
    ai_extractions      = _Stub()
    ai_risk_scores      = _Stub()
    ai_anomalies        = _Stub()
    schema_migrations   = _Stub()
    verify_calls        = _Stub()
    api_requests_total  = _Stub()
    trajectory_fits     = _Stub()
    trajectory_predictions = _Stub()

# aion/api/routes/cohorts.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
"""
Endpunkte fuer §11 (Abfragesprache), §20 (DP + Foederierung), §21 (KI).
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from aion.api.auth_keycloak import require_user, ClaimsUser
from aion.api.metrics import ai_extractions, ai_risk_scores, ai_anomalies
from aion.api.metrics import dp_budget_remaining

router = APIRouter()


# ── §11 Formale Abfragesprache ────────────────────────────────────────

class ValFilter(BaseModel):
    attr:      str
    op:        str   # > < >= <= == !=
    threshold: float

class CohortFormulaBody(BaseModel):
    event_type:  str | None = None
    min_count:   int        = 1
    attr_filter: dict       = {}
    val_filters: list[ValFilter] = []
    agg_attr:    str | None = None
    agg_op:      str | None = None
    agg_thresh:  float | None = None
    agg_comp:    str        = ">"
    patient_ids: list[str] | None = None
    apply_dp:    bool       = False
    epsilon:     float      = Field(default=0.5, gt=0, le=10)


@router.post("/query",
    summary="Kohortenabfrage (formale Abfragesprache §11)")
async def cohort_query(
    body: CohortFormulaBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.query.language import execute_cohort_query
        formula_dict = {
            "event_type":  body.event_type,
            "min_count":   body.min_count,
            "attr_filter": body.attr_filter,
            "val_filters": [vf.dict() for vf in body.val_filters],
            "agg_attr":    body.agg_attr,
            "agg_op":      body.agg_op,
            "agg_thresh":  body.agg_thresh,
            "agg_comp":    body.agg_comp,
        }
        result = await execute_cohort_query(
            formula_dict,
            request.app.state.store,
            patient_ids=body.patient_ids,
        )
        if body.apply_dp:
            dp_engine = request.app.state.dp_engine
            dp_result = dp_engine.cohort_count(
                result["cohort_size"], epsilon=body.epsilon
            )
            dp_budget_remaining.set(
                dp_engine.budget_status["epsilon_remaining"]
            )
            result["cohort_size_dp"] = dp_result.to_dict()
            result["matching_patients"] = []  # nicht offenlegen
        return result
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.get("/query/examples",
    summary="Beispielabfragen aus §11.3 des AION-Papers")
async def query_examples(user: ClaimsUser = Depends(require_user)):
    from aion.query.language import example_A, example_D
    return {
        "example_A": example_A(),
        "example_D": example_D(),
        "usage": "POST /cohorts/query mit formula aus example_A['formula']",
    }


# ── §20 DP-Abfragen ───────────────────────────────────────────────────

class CohortQuery(BaseModel):
    patient_ids: list[str] | None = None
    event_type:  str | None       = None
    epsilon:     float = Field(default=0.5, gt=0, le=10)

class MeanQuery(BaseModel):
    patient_ids: list[str] | None = None
    event_type:  str
    attribute:   str
    value_min:   float
    value_max:   float
    epsilon:     float = Field(default=0.5, gt=0, le=10)


@router.post("/count",
    summary="DP-geschuetzte Kohortenanzahl (§20.5/20.8)")
async def cohort_count(
    body: CohortQuery,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    dp_engine = request.app.state.dp_engine
    try:
        events = await request.app.state.store.find_by_patient(
            body.patient_ids[0] if body.patient_ids else "",
            type_filter=body.event_type, limit=10000,
        ) if body.patient_ids else []
        true_count = len(set(getattr(e,"patient_id","") for e in events))
        result = dp_engine.cohort_count(true_count, epsilon=body.epsilon)
        dp_budget_remaining.set(dp_engine.budget_status["epsilon_remaining"])
        return {
            **result.to_dict(),
            "budget": dp_engine.budget_status,
            "note": "Ergebnis ist epsilon-differential-privat.",
        }
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/mean",
    summary="DP-geschuetzter Mittelwert (§20.5/20.8)")
async def cohort_mean(
    body: MeanQuery,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    dp_engine = request.app.state.dp_engine
    try:
        all_events = []
        for pid in (body.patient_ids or []):
            evs = await request.app.state.store.find_by_patient(
                pid, type_filter=body.event_type, limit=1000
            )
            all_events.extend(evs)
        values = [
            getattr(e,"attributes",{}).get(body.attribute)
            for e in all_events
            if isinstance(getattr(e,"attributes",{}).get(body.attribute),(int,float))
        ]
        if not values:
            raise HTTPException(404, f"Keine Werte fuer {body.attribute!r}")
        true_mean = sum(values) / len(values)
        result = dp_engine.mean_value(
            true_mean, len(values), body.value_min, body.value_max,
            epsilon=body.epsilon,
        )
        dp_budget_remaining.set(dp_engine.budget_status["epsilon_remaining"])
        return {**result.to_dict(), "n_observations": len(values),
                "budget": dp_engine.budget_status}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, str(exc))


@router.get("/budget",
    summary="Datenschutzbudget-Status (§20.6)")
async def budget_status(
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    return request.app.state.dp_engine.budget_status


# ── §20 Foederierung ─────────────────────────────────────────────────

class FederatedQueryBody(BaseModel):
    formula:         dict
    n_institutions:  int   = 3
    epsilon_per_inst: float = 1.0
    simulate:        bool  = True   # True = Simulation ohne echte DB


@router.post("/federated",
    summary="Foederierte Kohortenabfrage mit lokalem DP (§20.1-20.7)")
async def federated_query(
    body: FederatedQueryBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    try:
        from aion.federation.federated import (
            simulate_federated, Institution, FederatedQueryEngine
        )
        if body.simulate:
            result = simulate_federated(
                n_institutions=body.n_institutions,
                epsilon=body.epsilon_per_inst,
            )
        else:
            # Echte Foederierung: alle Institutionen nutzen denselben Store
            # (in Produktion: separate Stores je Institution)
            insts = [
                Institution(
                    institution_id=f"inst_{i+1}",
                    name=f"Klinik {chr(65+i)}",
                    epsilon=body.epsilon_per_inst,
                )
                for i in range(body.n_institutions)
            ]
            engine = FederatedQueryEngine(insts)
            local_stores = {
                inst.institution_id: request.app.state.store
                for inst in insts
            }
            result = await engine.execute_federated_query(
                local_stores, body.formula
            )
        return result.to_dict()
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.get("/federated/status",
    summary="Foederierungsinfrastruktur-Status")
async def federated_status(user: ClaimsUser = Depends(require_user)):
    from aion.federation.federated import FederatedQueryEngine, Institution
    demo_insts = [
        Institution("I1","Klinik A", epsilon=1.0),
        Institution("I2","Klinik B", epsilon=0.5),
        Institution("I3","Klinik C", epsilon=2.0),
    ]
    engine = FederatedQueryEngine(demo_insts)
    return {
        **engine.status(),
        "dp_mechanism": "Laplace (lokal, §20.7)",
        "composition":  "Sequentiell (§20.6)",
    }


# ── §21 KI-Komponenten ────────────────────────────────────────────────

class TextExtractionBody(BaseModel):
    text:       str
    patient_id: str
    c_min:      float = 0.5


class RiskBody(BaseModel):
    patient_id: str


@router.post("/ai/extract",
    summary="Ereignisextraktion aus Freitext (§21.4)")
async def ai_extract(
    body: TextExtractionBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    try:
        from aion.ai.components import (
            EventExtractionComponent, ValidationOperator
        )
        validator = ValidationOperator(c_min=body.c_min)
        extractor = EventExtractionComponent(validator=validator)
        result    = extractor.extract_and_validate(body.text, body.patient_id)

        # Akzeptierte Ereignisse in DB speichern
        saved_ids = []
        if request.app.state.store and result["events"]:
            for ev in result["events"]:
                try:
                    eid = await request.app.state.store.add(
                        ev, current_user=user.sub
                    )
                    saved_ids.append(eid)
                except Exception as exc:
                    pass

        ai_extractions.labels(status="accepted").inc(result["accepted"])
        ai_extractions.labels(status="rejected").inc(result["rejected"])
        return {
            "extracted":  result["extracted"],
            "accepted":   result["accepted"],
            "rejected":   result["rejected"],
            "saved_ids":  saved_ids,
            "validation": result["validation"],
            "layer":      "Schicht 2 (§21.4)",
        }
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/ai/risk",
    summary="Risikoschatzung fuer Patient (§21.7)")
async def ai_risk(
    body: RiskBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.ai.components import RiskEstimationComponent
        events = await request.app.state.store.find_by_patient(
            body.patient_id, limit=200
        )
        if not events:
            raise HTTPException(404, f"Keine Ereignisse fuer {body.patient_id!r}")
        model  = RiskEstimationComponent(c_min=0.0)
        result = model.predict_with_validation(events, body.patient_id)
        ai_risk_scores.observe(result["risk_score"])

        # v1.1.0-D: Trajektorienvorhersage als zusaetzliches Feature
        predictor = request.app.state.trajectory_predictor
        if predictor.has_training_data():
            try:
                from aion.ai.trajectories import EpisodeBuilder
                builder  = EpisodeBuilder(
                    ["Diagnose", "Laborbefund", "Aufnahme", "Entlassung"],
                    delta_days=30.0,
                )
                episodes = builder.build(events, body.patient_id)
                if episodes:
                    pred = predictor.predict(episodes, top_k=3)
                    if pred:
                        result["trajectory_prediction"] = pred.to_dict()
            except Exception as exc:
                pass  # Trajektorien-Vorhersage optional

        return {**result, "layer": "Schicht 5 (§21.7)"}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, str(exc))


@router.post("/ai/validate",
    summary="Validierungsoperator Pi_l fuer Ereignis (§21.2)")
async def ai_validate(
    event_dict: dict,
    user: ClaimsUser = Depends(require_user),
):
    try:
        from aion.ai.components import ValidationOperator
        c_min = float(event_dict.get("_c_min", 0.5))
        conf  = float(event_dict.get("_confidence", 1.0))
        op    = ValidationOperator(c_min=c_min)

        class _E:
            pass
        e = _E()
        for k, v in event_dict.items():
            if not k.startswith("_"):
                setattr(e, k, v)

        result = op.validate(e, confidence=conf)
        return {
            **result.to_dict(),
            "operator": "Pi_l (§21.2)",
        }
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.get("/ai/layers",
    summary="KI-Schichtenmodell Uebersicht (§21.9)")
async def ai_layers(user: ClaimsUser = Depends(require_user)):
    from aion.ai.components import AI_LAYER_OVERVIEW
    return AI_LAYER_OVERVIEW


# ── §21.6 Anomalieerkennung ───────────────────────────────────────────

class AnomalyBody(BaseModel):
    patient_id: str
    threshold:  float = 0.5


@router.post("/ai/anomaly",
    summary="Anomalieerkennung fuer Patientenereignisse (§21.6)")
async def ai_anomaly(
    body: AnomalyBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.ai.components import AnomalyDetectionComponent
        events = await request.app.state.store.find_by_patient(
            body.patient_id, limit=200
        )
        if not events:
            raise HTTPException(404, f"Keine Ereignisse fuer {body.patient_id!r}")

        detector = AnomalyDetectionComponent(threshold=body.threshold)
        results  = detector.detect_batch(events, body.patient_id)
        anomalies = [r for r in results if r.is_anomaly]

        for r in anomalies:
            ai_anomalies.labels(level="anomalie").inc()
        return {
            "patient_id":  body.patient_id,
            "n_events":    len(events),
            "summary":     detector.summary(results),
            "anomalies":   [
                {
                    "event_type": getattr(r.event,"event_type","?"),
                    "t_start":    str(getattr(r.event,"t_start","")),
                    **r.to_dict(),
                }
                for r in anomalies
            ],
            "layer": "Schicht 4 (§21.6)",
        }
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, str(exc))


# ── §21.8 Regellernen ─────────────────────────────────────────────────

class RuleLearnBody(BaseModel):
    patient_ids:    list[str] | None = None
    target_label:   str = "hoch"
    min_support:    float = 0.1
    min_confidence: float = 0.6


@router.post("/ai/rules",
    summary="Regellernen aus Ereignisdaten (§21.8)")
async def ai_rules(
    body: RuleLearnBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.ai.components import (
            RuleLearningComponent, RiskEstimationComponent
        )
        risk_model = RiskEstimationComponent()
        learner    = RuleLearningComponent(
            min_support=body.min_support,
            min_confidence=body.min_confidence,
        )

        # Daten laden
        async with request.app.state.store._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT patient_id FROM event LIMIT 500"
            )
        pids = [r["patient_id"] for r in rows]
        if body.patient_ids:
            pids = [p for p in pids if p in body.patient_ids]

        all_events, all_labels = [], []
        for pid in pids:
            evs = await request.app.state.store.find_by_patient(pid, limit=100)
            if not evs: continue
            score, _ = risk_model.predict(evs)
            label = "hoch" if score > 0.6 else "mittel" if score > 0.3 else "niedrig"
            for ev in evs:
                all_events.append(ev)
                all_labels.append(label)

        if not all_events:
            raise HTTPException(404, "Keine Ereignisse gefunden")

        learner.fit(all_events, all_labels)

        return {
            "n_events":     len(all_events),
            "n_patients":   len(pids),
            "n_rules":      len(learner.rules_),
            "rules":        learner.rules_as_dict(),
            "layer":        "Schicht 6 (§21.8)",
        }
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, str(exc))


# ── §21.9 Schichtenkomposition ────────────────────────────────────────

class PipelineBody(BaseModel):
    text:       str
    patient_id: str
    c_min:      float = 0.5
    threshold:  float = 0.5


@router.post("/ai/pipeline",
    summary="Vollstaendige KI-Pipeline (§21.9 Schichtenkomposition)")
async def ai_pipeline(
    body: PipelineBody,
    request: Request,
    user: ClaimsUser = Depends(require_user),
):
    try:
        from aion.ai.components import (
            EventExtractionComponent, ValidationOperator,
            AnomalyDetectionComponent, RiskEstimationComponent,
            RuleLearningComponent, LayerComposer
        )
        validator = ValidationOperator(c_min=body.c_min)
        composer  = LayerComposer(
            extractor=EventExtractionComponent(validator=validator),
            anomaly=AnomalyDetectionComponent(threshold=body.threshold),
            risk=RiskEstimationComponent(),
        )
        result = composer.process(body.text, body.patient_id)

        # Akzeptierte Ereignisse speichern
        if request.app.state.store and result.get("status") == "ok":
            from aion.ai.components import EventExtractionComponent
            extracted = EventExtractionComponent(validator=validator)
            raw = extracted.extract(body.text, body.patient_id)
            accepted, _ = validator.validate_many(raw)
            saved = []
            for ev in accepted:
                try:
                    eid = await request.app.state.store.add(ev, current_user=user.sub)
                    saved.append(eid)
                except Exception:
                    pass
            result["saved_event_ids"] = saved

        return result
    except Exception as exc:
        raise HTTPException(422, str(exc))

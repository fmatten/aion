import logging
log = logging.getLogger(__name__)

# aion/api/routes/causal.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from aion.api.auth_keycloak import require_user
from aion.api.metrics import trajectory_fits, trajectory_predictions

router = APIRouter()


class BackdoorRequest(BaseModel):
    treatment_type: str
    outcome_type:   str
    adjustment_set: list[str] = []


class PCRequest(BaseModel):
    node_names:  list[str]
    values:      dict[str, list[float]]
    alpha:       float = 0.05
    n_bootstrap: int   = 50
    gamma:       float = 0.5


class ExplainRequest(BaseModel):
    patient_id: str
    phi_min:    float = 0.05
    epsilon_s:  float = 0.05


@router.post("/backdoor", summary="Backdoor-Adjustierung (§14)")
async def backdoor(body: BackdoorRequest, user=Depends(require_user)):
    try:
        from aion import CausalGraph
        from aion.verify import is_valid_backdoor_set
        g = CausalGraph()
        report = is_valid_backdoor_set(
            g, body.treatment_type, body.outcome_type, set(body.adjustment_set)
        )
        return {"treatment": body.treatment_type, "outcome": body.outcome_type,
                "adjustment_set": body.adjustment_set, "valid": bool(report)}
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/pc", summary="PC-Algorithmus Kausalstrukturlernen (§15.3)")
async def pc_learn(body: PCRequest, user=Depends(require_user)):
    try:
        from aion.causal_learn.pc_algorithm import pc_algorithm
        if len(body.node_names) != len(body.values):
            raise HTTPException(422, "node_names und values muessen gleich lang sein")
        result = pc_algorithm(body.values, alpha=body.alpha)
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/pc/bootstrap", summary="Bootstrap-Kantenkonfidenzen (§15.5)")
async def pc_bootstrap(body: PCRequest, user=Depends(require_user)):
    try:
        from aion.causal_learn.pc_algorithm import bootstrap_pc
        result = bootstrap_pc(
            body.values,
            n_bootstrap=body.n_bootstrap,
            gamma=body.gamma,
            alpha=body.alpha,
        )
        return result.to_dict()
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/explain/shapley", summary="Shapley-Attribution (§22.2)")
async def explain_shapley(
    body: ExplainRequest,
    request: Request,
    user=Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.explain.shapley import shapley_event_attribution

        all_events = await request.app.state.store.find_by_patient(
            body.patient_id, limit=100
        )
        if not all_events:
            raise HTTPException(404, f"Keine Ereignisse fuer {body.patient_id!r}")
        # Shapley ist O(2^n) – auf max 8 Events begrenzen fuer akzeptable Laufzeit
        events = all_events[:8]

        def feature_fn(evs):
            vals = []
            for e in evs:
                attrs = getattr(e, "attributes", {}) or {}
                for v in attrs.values():
                    if isinstance(v, (int, float)):
                        vals.append(float(v))
            return [sum(vals)/max(len(vals),1)] if vals else [0.0]

        def model_fn(feats):
            return min(1.0, max(0.0, feats[0] / 10.0)) if feats else 0.0

        result = shapley_event_attribution(
            events, feature_fn, model_fn, phi_min=body.phi_min
        )
        return {
            **result.to_dict(),
            "patient_id": body.patient_id,
            "n_events":   len(events),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/explain/counterfactual", summary="Kontrafaktische Erklaerung (§22.3)")
async def explain_counterfactual(
    body: ExplainRequest,
    request: Request,
    user=Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.explain.shapley import minimal_counterfactual

        all_events = await request.app.state.store.find_by_patient(
            body.patient_id, limit=100
        )
        if not all_events:
            raise HTTPException(404, f"Keine Ereignisse fuer {body.patient_id!r}")
        # Shapley ist O(2^n) – auf max 8 Events begrenzen fuer akzeptable Laufzeit
        events = all_events[:8]

        def feature_fn(evs):
            vals = []
            for e in evs:
                for v in (getattr(e,"attributes",{}) or {}).values():
                    if isinstance(v, (int, float)): vals.append(float(v))
            return [sum(vals)/max(len(vals),1)] if vals else [0.0]

        def model_fn(feats):
            return min(1.0, max(0.0, feats[0] / 10.0)) if feats else 0.0

        cf = minimal_counterfactual(events, feature_fn, model_fn)
        if cf is None:
            return {"message": "Kein kontrafaktisches Ereignis gefunden",
                    "patient_id": body.patient_id}
        return {**cf.to_dict(), "patient_id": body.patient_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc))



class TrajectoryPredictBody(BaseModel):
    patient_id:  str
    event_types: list[str] = ["Diagnose", "Laborbefund", "Aufnahme", "Entlassung"]
    delta_days:  float     = 30.0
    top_k:       int       = 3


class TrajectoryBody(BaseModel):
    patient_id:   str
    event_types:  list[str] = ["Diagnose","Laborbefund","Operation"]
    delta_days:   float     = 30.0
    predict_next: bool      = True


@router.post("/trajectories", summary="Episoden und Trajektorien (§9.3/9.4/21.5)")
async def build_trajectory(
    body: TrajectoryBody,
    request: Request,
    user=Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.ai.trajectories import (
            EpisodeBuilder, ClinicalTrajectory,
            TrajectoryPredictor, TrajectoryValidator
        )
        events = await request.app.state.store.find_by_patient(
            body.patient_id, limit=500
        )
        if not events:
            raise HTTPException(404, f"Keine Ereignisse fuer {body.patient_id!r}")

        # §9.3 Episodenbildung
        builder  = EpisodeBuilder(body.event_types, delta_days=body.delta_days)
        episodes = builder.build(events, body.patient_id)

        # §9.4 Trajektorie
        traj = ClinicalTrajectory(body.patient_id, episodes)

        # §21.2 Validierung
        validator = TrajectoryValidator(min_episodes=1)
        validation = validator.validate(traj)

        result = {
            **traj.to_dict(),
            "validation": validation,
            "layer":      "Schicht 3 (§21.5)",
        }

        # §21.5b Vorhersage naechste Episode
        if body.predict_next and len(episodes) >= 1:
            predictor = request.app.state.trajectory_predictor
            pred = predictor.predict(episodes)
            if pred:
                result["next_episode_prediction"] = pred.to_dict()

        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.post("/trajectories/fit",
    summary="Trajektorienmodell trainieren (§21.5b)")
async def fit_trajectory_model(
    body: TrajectoryBody,
    request: Request,
    user=Depends(require_user),
):
    """
    Trainiert den TrajectoryPredictor auf allen verfuegbaren Trajektorien.
    Sollte nach ausreichend Datenbasis aufgerufen werden.
    """
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.ai.trajectories import (
            EpisodeBuilder, ClinicalTrajectory, EpisodeDeltaLearner
        )
        import asyncio

        async with request.app.state.store._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT patient_id FROM event LIMIT 1000"
            )
        patient_ids = [r["patient_id"] for r in rows]

        builder    = EpisodeBuilder(body.event_types, delta_days=body.delta_days)
        trajs      = []
        delta_data = []

        for pid in patient_ids:
            events = await request.app.state.store.find_by_patient(pid, limit=200)
            eps    = builder.build(events, pid)
            if eps:
                traj = ClinicalTrajectory(pid, eps)
                trajs.append(traj)
                if len(eps) >= 2:
                    delta_data.append(traj)

        predictor = request.app.state.trajectory_predictor
        predictor.fit(trajs)

        learner = EpisodeDeltaLearner()
        if delta_data:
            learner.fit(delta_data)

        # Modell persistieren (Redis)
        persisted = False
        if request.app.state.redis is not None and predictor.has_training_data():
            try:
                import json as _json
                payload = _json.dumps({
                    "predictor": predictor.to_dict(),
                    "delta_summary": learner.summary(),
                })
                await request.app.state.redis.set(
                    "aion:trajectory:model", payload
                )
                persisted = True
            except Exception as exc:
                log.warning("Trajektorien-Modell konnte nicht persistiert werden: %s", exc)

        trajectory_fits.labels(status="ok").inc()
        return {
            "trained_on_patients":    len(patient_ids),
            "trajectories_built":     len(trajs),
            "delta_learner_summary":  learner.summary(),
            "predictor_has_data":     predictor.has_training_data(),
            "model_persisted":        persisted,
            "layer": "Schicht 3 (§21.5)",
        }
    except Exception as exc:
        trajectory_fits.labels(status="error").inc()
        raise HTTPException(422, str(exc))


@router.post("/trajectories/predict",
    summary="Naechsten Episodentyp vorhersagen (§21.5b)")
async def predict_trajectory(
    body: TrajectoryPredictBody,
    request: Request,
    user=Depends(require_user),
):
    """
    Sagt den naechsten Episodentyp und Zeitabstand fuer einen Patienten vorher.
    Erfordert: Modell muss vorher mit /trajectories/fit trainiert worden sein.
    """
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    try:
        from aion.ai.trajectories import EpisodeBuilder, ClinicalTrajectory

        predictor = request.app.state.trajectory_predictor
        if not predictor.has_training_data():
            return {
                "predicted":       False,
                "reason":          "Kein Trainingsmodell vorhanden - bitte erst /trajectories/fit aufrufen",
                "predictor_ready": False,
            }

        events = await request.app.state.store.find_by_patient(
            body.patient_id, limit=200
        )
        if not events:
            raise HTTPException(404, f"Keine Ereignisse fuer {body.patient_id!r}")

        builder  = EpisodeBuilder(body.event_types, delta_days=body.delta_days)
        episodes = builder.build(events, body.patient_id)
        if not episodes:
            return {
                "predicted":      False,
                "reason":         "Keine Episoden bildbar",
                "n_events":       len(events),
                "patient_id":     body.patient_id,
            }

        prediction = predictor.predict(episodes, top_k=body.top_k)
        if prediction is not None:
            cl = "high" if prediction.confidence >= 0.7 else ("medium" if prediction.confidence >= 0.4 else "low")
            trajectory_predictions.labels(confidence_level=cl).inc()
        if prediction is None:
            return {
                "predicted":  False,
                "reason":     "Vorhersage nicht moeglich",
                "patient_id": body.patient_id,
            }

        return {
            "predicted":         True,
            "patient_id":        body.patient_id,
            "n_episodes":        len(episodes),
            "current_sequence":  [
                ep.event_types[0] if ep.event_types else "?"
                for ep in episodes
            ],
            "prediction":        prediction.to_dict(),
            "layer":             "Schicht 3 (§21.5b)",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, str(exc))


@router.get("/trajectories/model/status",
    summary="Status des Trajektorienmodells")
async def trajectory_model_status(
    request: Request,
    user=Depends(require_user),
):
    """Gibt Status des trainierten Trajektorienmodells zurueck."""
    predictor = request.app.state.trajectory_predictor
    n_transitions = sum(
        sum(v.values()) for v in predictor._transitions.values()
    ) if predictor.has_training_data() else 0
    return {
        "has_training_data": predictor.has_training_data(),
        "n_transition_contexts": len(predictor._transitions) if predictor.has_training_data() else 0,
        "n_transitions_learned": n_transitions,
        "model_order": predictor.order,
        "layer": "Schicht 3 (§21.5)",
    }

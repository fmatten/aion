# aion/api/routes/explain.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from aion.api.auth_keycloak import require_user

router = APIRouter()


class ExplainRequest(BaseModel):
    patient_id: str
    phi_min:    float = Field(default=0.05, ge=0.0, le=1.0)
    threshold:  float = Field(default=0.25, ge=0.0, le=1.0)
    tolerance:  float = Field(default=0.02, ge=0.0, le=0.5)


@router.post("/shapley", summary="Shapley-Attribution auf Ereignisebene (§22.2)")
async def shapley(body: ExplainRequest, request: Request, user=Depends(require_user)):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    from aion.explain.shapley import shapley_event_attribution, simple_risk_model
    events = await request.app.state.store.find_by_patient(body.patient_id, limit=50)
    if not events:
        raise HTTPException(404, f"Keine Ereignisse fuer Patient {body.patient_id!r}")
    result = shapley_event_attribution(simple_risk_model, events, phi_min=body.phi_min)
    return result.to_dict()


@router.post("/counterfactual", summary="Kontrafaktische Erklaerung Δ*_cf (§22.3)")
async def counterfactual(body: ExplainRequest, request: Request, user=Depends(require_user)):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    from aion.explain.shapley import counterfactual_explanation, simple_risk_model
    events = await request.app.state.store.find_by_patient(body.patient_id, limit=50)
    if not events:
        raise HTTPException(404, f"Keine Ereignisse fuer Patient {body.patient_id!r}")
    return counterfactual_explanation(simple_risk_model, events, threshold=body.threshold)


@router.post("/sufficient", summary="Suffiziente Erklaerung S*_suf (§22.4)")
async def sufficient(body: ExplainRequest, request: Request, user=Depends(require_user)):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    from aion.explain.shapley import sufficient_explanation, simple_risk_model
    events = await request.app.state.store.find_by_patient(body.patient_id, limit=50)
    if not events:
        raise HTTPException(404, f"Keine Ereignisse fuer Patient {body.patient_id!r}")
    return sufficient_explanation(simple_risk_model, events, tolerance=body.tolerance)



class BoundedRequest(BaseModel):
    patient_id: str
    k_max:      int   = Field(default=5, ge=1, le=20)
    epsilon_s:  float = Field(default=0.05, ge=0.0, le=0.5)


@router.post("/bounded", summary="Beschraenkte Erklaerung Pi+_l (§22.5)")
async def bounded(body: BoundedRequest, request: Request, user=Depends(require_user)):
    """
    Erklaerung mit |S| <= k_max nach §22.5.
    Wenn weniger Events als k_max: vollstaendige Erklaerung.
    Sonst greedy bis k_max oder bis suffizient.
    """
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfuegbar")
    from aion.explain.shapley import bounded_explanation

    events = await request.app.state.store.find_by_patient(body.patient_id, limit=50)
    if not events:
        raise HTTPException(404, f"Keine Ereignisse fuer Patient {body.patient_id!r}")

    def feature_fn(evs):
        # Vereinfachtes Feature: Anzahl Diagnosen + max Laktat
        n_dx = sum(1 for e in evs if getattr(e,'event_type','')=='Diagnose')
        max_lact = max(
            (getattr(e,'attributes',{}).get('qlaktat',0) for e in evs),
            default=0
        )
        return {'n_dx': n_dx, 'max_lact': max_lact}

    def model_fn(feats):
        import math
        z = 0.3 * feats.get('n_dx',0) + 0.2 * feats.get('max_lact',0)
        return 1.0 / (1.0 + math.exp(-z))

    result = bounded_explanation(
        events, feature_fn, model_fn,
        k_max=body.k_max, epsilon_s=body.epsilon_s
    )
    return {**result.to_dict(), "patient_id": body.patient_id}

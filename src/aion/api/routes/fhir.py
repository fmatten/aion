# aion/api/routes/fhir.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from aion.api.auth_keycloak import require_user
from aion.api.metrics import fhir_imports, fhir_exports

router = APIRouter()


@router.post("/bundle", summary="FHIR Bundle importieren (§19)")
async def import_bundle(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_user),
):
    raw = await file.read()
    try:
        bundle_dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Ungültiges JSON: {exc}")
    try:
        from aion.fhir import from_fhir_bundle
        events = from_fhir_bundle(bundle_dict)
    except Exception as exc:
        fhir_imports.labels(status="error").inc()
        raise HTTPException(422, f"FHIR-Mapping fehlgeschlagen: {exc}")
    ids = []
    if request.app.state.store:
        for e in events:
            try:
                eid = await request.app.state.store.add(e, current_user=user.sub)
                ids.append(eid)
            except Exception:
                fhir_imports.labels(status="partial_error").inc()
    fhir_imports.labels(status="ok").inc()
    return {"imported": len(ids), "event_ids": ids,
            "skipped": len(events) - len(ids)}


@router.get("/bundle/{patient_id}", summary="FHIR Bundle exportieren (§19)")
async def export_bundle(
    patient_id: str,
    request: Request,
    user=Depends(require_user),
):
    if request.app.state.store is None:
        raise HTTPException(503, "Datenbank nicht verfügbar")
    events = await request.app.state.store.find_by_patient(patient_id)
    try:
        from aion.fhir import to_fhir_bundle
        import warnings
        warnings.filterwarnings("ignore")
        bundle = to_fhir_bundle(events)

        # Pydantic v2: model_dump_json() ist die korrekte Methode
        for method in ("model_dump_json", "json"):
            fn = getattr(bundle, method, None)
            if fn:
                try:
                    raw = fn(exclude_none=True)
                    fhir_exports.labels(status="ok").inc()
                    return JSONResponse(content=json.loads(raw))
                except Exception:
                    continue

        # Fallback: dict + default=str
        d = bundle.dict(exclude_none=True) if hasattr(bundle, "dict") else {}
        return JSONResponse(content=json.loads(json.dumps(d, default=str)))

    except Exception as exc:
        fhir_exports.labels(status="error").inc()
        raise HTTPException(500, f"FHIR-Export fehlgeschlagen: {exc}")

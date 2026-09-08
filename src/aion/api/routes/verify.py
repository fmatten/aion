# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
# aion/api/routes/verify.py
# Copyright © 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from aion.api.auth_keycloak import require_user
from aion.api.metrics import verify_calls

router = APIRouter()

class SchemaIn(BaseModel):
    yaml_content: str | None = None
    schema_path:  str | None = None

@router.post("/schema", summary="Schema-Konsistenzprüfung (§16 + aion.verify)")
async def verify_schema(body: SchemaIn, user=Depends(require_user)):
    try:
        from aion import TypeHierarchy
        from aion.verify import check_inheritance_conflicts
        import yaml, io
        if body.yaml_content:
            data = yaml.safe_load(io.StringIO(body.yaml_content))
            h = TypeHierarchy()
            for t, info in (data.get("types") or {}).items():
                parent = info.get("parent") if isinstance(info, dict) else None
                h.add_type(t, parent=parent) if parent else h.add_type(t)
        else:
            h = TypeHierarchy.from_yaml(body.schema_path or "schemas/clinical_base.yaml")
        report = check_inheritance_conflicts(h)
        verify_calls.labels(result="ok").inc()
        return {"valid": True, "summary": str(report.summary()) if hasattr(report, "summary") else "OK"}
    except Exception as exc:
        verify_calls.labels(result="error").inc()
        return {"valid": False, "error": str(exc)}

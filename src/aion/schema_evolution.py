"""Schemaevolution §18 AION-Paper – aion.schema_evolution"""
from __future__ import annotations
import copy, logging
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger(__name__)
OpType = Literal["add_type","rem_type","ren_type","move_type","add_attr","rem_attr","chg_attr"]

@dataclass
class SchemaOp:
    op: OpType
    params: dict = field(default_factory=dict)
    def to_dict(self): return {"op":self.op,"params":self.params}
    @classmethod
    def from_dict(cls,d): return cls(op=d["op"],params=d.get("params",{}))

class SchemaMigration:
    def __init__(self,from_version,to_version,operations=None):
        self.from_version=from_version; self.to_version=to_version
        self.operations=operations or []

    def migrate_event(self, event):
        if event is None: return None
        orig_patient=getattr(event,"patient_id",None)
        orig_t_start=getattr(event,"t_start",None)
        result=event
        for op in self.operations:
            match op.op:
                case "ren_type":
                    if getattr(result,"event_type",None)==op.params.get("old"):
                        result=_rep(result,"event_type",op.params.get("new",""))
                case "rem_type":
                    if getattr(result,"event_type",None)==op.params.get("type"):
                        return None
                case "rem_attr":
                    attrs={**getattr(result,"attributes",{})}
                    attrs.pop(op.params.get("attr_name",""),None)
                    result=_rep(result,"attributes",attrs)
                case "add_attr":
                    default=op.params.get("default")
                    if default is not None:
                        attrs={**getattr(result,"attributes",{})}
                        attrs.setdefault(op.params.get("attr_name",""),default)
                        result=_rep(result,"attributes",attrs)
                case "chg_attr":
                    attr=op.params.get("attr_name",""); nt=op.params.get("new_type")
                    attrs={**getattr(result,"attributes",{})}
                    if nt and attr in attrs:
                        try:
                            attrs[attr]={"str":str,"int":int,"float":float}[nt](attrs[attr])
                            result=_rep(result,"attributes",attrs)
                        except: pass
        assert getattr(result,"patient_id",None)==orig_patient
        assert getattr(result,"t_start",None)==orig_t_start
        return result

    def is_forward_compatible(self):
        for op in self.operations:
            if op.op in ("rem_type","rem_attr"): return False
            if op.op=="chg_attr" and op.params.get("narrows_domain"): return False
        return True

    def is_backward_compatible(self):
        for op in self.operations:
            if op.op not in ("add_type","add_attr"): return False
            if op.op=="add_attr" and op.params.get("obligatory"): return False
        return True

    def is_bidirectional_compatible(self):
        return self.is_forward_compatible() and self.is_backward_compatible()

    def to_dict(self):
        return {"from_version":self.from_version,"to_version":self.to_version,
                "operations":[o.to_dict() for o in self.operations]}

    @classmethod
    def from_dict(cls,d):
        return cls(d["from_version"],d["to_version"],[SchemaOp.from_dict(o) for o in d.get("operations",[])])

def _rep(obj,field,value):
    try:
        from dataclasses import replace,is_dataclass
        if is_dataclass(obj): return replace(obj,**{field:value})
    except: pass
    import copy as _c; o2=_c.copy(obj); object.__setattr__(o2,field,value); return o2

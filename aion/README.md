# AION — Algebraic Interval Ontology for Clinical Networks

> **Formal mathematical model for clinical information systems. FM-3.**

[![Tests](https://img.shields.io/badge/tests-326%20passing-brightgreen)](https://codeberg.org/fm2-project/aion)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![License](https://img.shields.io/badge/license-EUPL--1.2-blue)](LICENSE)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-orange)](https://hl7.org/fhir/R4/)

---

## What is AION?

AION is the fully general formal model for clinical information systems of which
**CAIRN** (FM-2) is a special case. It generalises the foundational FM-1 model
in nineteen dimensions and forms the theoretical basis for the AION Python software.

| FM document | Scope | Role |
|---|---|---|
| FM-1 (2020) | Cardiac surgery | Foundational formal model |
| FM-2 / CAIRN | CDR-to-FHIR mapping | Special case of AION |
| FM-3 / **AION** | All clinical domains | General model |

---

## Architecture

```
aion/
├── core/          Allen algebra (13 relations), type system σ(τ),
│                  event 6-tuple, fuzzy intervals, process DAG
├── abstraction/   Episode formation B_{Φ,Δ}, clinical trajectories
├── query/         Cohort algebra, RTP patterns, TCFG, predicates
├── causal/        Causal graph, do-operator, backdoor adjustment,
│                  PC algorithm, bootstrap structure learning
├── privacy/       ε-DP Laplace/Gaussian, federated model, LDP
├── ai/            AI components A_l = (X,Y,f_θ,L,θ*), Π_l operator,
│                  feature extraction Ψ, risk estimation
├── explain/       Shapley attribution, counterfactual Δ*_cf,
│                  sufficient explanation S*_suf, Π_l^+ gate
├── schema/        Versioned type system, 7 schema change ops,
│                  migration function μ_{v→v'}
└── adapters/
    └── fhir/      Structural homomorphism (h_T, h_σ), Q_map index
```

---

## Quick Start

```bash
pip install aion
```

```python
from aion.core import (
    Interval, AllenRelation, classify,
    TypeHierarchy, ClinicalEvent, EventSet,
    FuzzyInterval, ProbabilisticAllen,
    ProcessDAG,
)
import datetime

# Create events
dt = lambda h: datetime.datetime(2024, 1, 1, h, 0)
anaesthesia = Interval(dt(7), dt(12))
operation   = Interval(dt(8), dt(11))

# Allen relation: anaesthesia CONTAINS operation
rel = classify(anaesthesia, operation)
print(rel)   # AllenRelation.CONTAINS

# Fuzzy interval
fi = FuzzyInterval(dt(7), dt(12), eps_start=600.0, eps_end=600.0)
p  = ProbabilisticAllen.confidence(AllenRelation.CONTAINS, fi,
         FuzzyInterval(dt(8), dt(11), 0, 0))
print(f"P(Contains) = {p:.3f}")  # ≈ 0.998
```

---

## Key Concepts

### Event 6-Tuple (AION §5)

```python
e = (p, a, τ, [t^B, t^E], α, ρ)
```
- `p` patient, `a` stay, `τ` type, `[t^B,t^E]` interval, `α` attributes, `ρ` references

### All 13 Allen Relations (AION §6)

```python
from aion.core.allen import AllenRelation, holds
# precedes, meets, overlaps, finished-by, contains, starts, equals,
# started-by, during, finishes, overlapped-by, met-by, preceded-by
```

### Cohort Algebra (AION §10)

```python
from aion.query.cohort import query_has_type_event, query_event_sequence

q_dx_before_op = query_event_sequence("Diagnosis", "Procedure")
q_with_lab     = query_has_type_event("LabResult")
q_combined     = q_dx_before_op & q_with_lab   # P_φ ∩ P_ψ
cohort = q_combined.evaluate(ctx)
```

### Causal Inference (AION §14)

```python
from aion.causal.graph import CausalGraph
from aion.causal.do import DoOperator, ObservationalDistribution

g = CausalGraph()
g.add_edge("Diagnosis", "Procedure")
g.add_edge("Procedure", "LabResult")

do  = DoOperator(g, ObservationalDistribution(event_set))
res = do.intervene("Procedure", "LabResult")
print(f"ATE = {res.ate:+.3f}")
```

### Differential Privacy (AION §20)

```python
from aion.privacy.differential import PrivacyBudget, LaplaceMechanism

budget = PrivacyBudget(epsilon_total=1.0)
mech   = LaplaceMechanism(budget, seed=42)
result = mech.release_cohort_size(true_size=247)
print(f"ε-DP estimate: {result.noisy_value:.1f}")
```

### FHIR Mapping (AION §17)

```python
from aion.adapters.fhir.mapping import FHIRMappingSpec

spec   = FHIRMappingSpec()
bundle = spec.export_bundle(event_set)
print(f"Coverage: {bundle.mapping_coverage:.1%}")
print(f"Q_map: {spec.quality_index(event_set):.3f}")
```

---

## Test Suite

```bash
git clone https://codeberg.org/fm2-project/aion.git
cd aion
pip install -e ".[dev]"
pytest aion/tests/   # 326 tests, ~2s
```

---

## Formal Foundation

AION formalises 19 dimensions of the clinical information model:

1. Type system with hierarchy and schema inheritance
2. Universal event model (6-tuple)
3. General observation model (7 value space classes)
4. Complete temporal algebra (all 13 Allen relations)
5. DAG process model with composition schema
6. Multi-level abstraction (events → episodes → trajectories)
7. Extended query language with cohort algebra
8. Schema-based validation with weighted quality index
9. Causal structure learning (PC algorithm, GES, bootstrap)
10. Explainability (Shapley, counterfactual, sufficient)
11. Schema evolution (7 operations, migration functions)
12. FHIR mapping as structural homomorphism
13. Multi-patient relations (contact, transmission, matching)
14. Causal model (do-operator, backdoor adjustment)
15. Fuzzy time intervals with probabilistic Allen relations
16. Temporal pattern languages (RTP + TCFG)
17. Formal AI component model
18. Computational complexity classification
19. Federation with differential privacy

---

## License & Citation

**EUPL-1.2** — open source. Commercial licence: `licensing@iscad-it.de`

```bibtex
@software{aion2025,
  title  = {AION: Algebraic Interval Ontology for Clinical Networks},
  author = {Matten, Friedhelm},
  year   = {2025},
  url    = {https://codeberg.org/fm2-project/aion},
  note   = {FM-3 formal clinical information model, EUPL-1.2}
}
```

© Friedhelm Matten, ISCaD GmbH, 30900 Wedemark

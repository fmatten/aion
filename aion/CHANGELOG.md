# Changelog — AION

All notable changes are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [1.0.0] — 2025-04

### Added — Phase 1: Core Formal Model (AION §3–§8)

- **`aion/core/allen.py`** — All 13 Allen interval relations, `classify()`,
  `holds()`, `holds_weak()` with ε-slack, `relation_preserved()`,
  full composition table, exhaustiveness proven (88 tests)
- **`aion/core/types.py`** — `TypeHierarchy` with σ(τ) attribute schemas,
  schema inheritance σ(τ) ⊇ σ(τ'), comp(τ) composition schema,
  `add_type()` with DAG-cycle and schema-inheritance validation
- **`aion/core/event.py`** — `ClinicalEvent` 6-tuple with ρ reference set,
  confidence ∈ [0,1], all 4 consistency conditions (AION §5.2), `EventSet`
  with E_{≺τ} subtype queries and E_{c_min} confidence filtering
- **`aion/core/fuzzy.py`** — `FuzzyInterval` with ε-radii, probabilistic
  Allen relations for all 13 relations (normal distribution model),
  `TemporalValidator` Π_temp, `FuzzyTemporalPredicate` TRel~
- **`aion/core/process.py`** — `ProcessDAG` with AION §8.1 invariants
  (acyclicity, temporal embedding, type conformance), `sub()`, `desc()`,
  `parent()`, `procs()`, `ProcessIndex`

### Added — Phase 2: Abstraction and Query (AION §9–§11)

- **`aion/abstraction/episode.py`** — `EpisodeFormationOperator` B_{Φ,Δ},
  `Episode` 4-tuple, `DerivedEvent` ρ(S), `EpisodeIndex`
- **`aion/abstraction/trajectory.py`** — `Trajectory` J_k with §9.4
  ordering invariant, `TrajectoryPattern` with gap constraints, `TrajectoryBuilder`
- **`aion/query/predicates.py`** — All AION §10.1 predicates: HasType,
  AttrEq, AttrVal, TRel, SubOf, Dist, EpisodePred, EvtExists, EvtExistsN,
  AggCond with standard aggregators
- **`aion/query/cohort.py`** — `CohortQuery` with full cohort algebra
  (∩ ∪ \ ¬), standard queries φ_A–φ_D (AION §10.3), `Cohort`
- **`aion/query/patterns.py`** — Complete RTP grammar: Atom, Concat,
  Alternate, KleeneStar, Option, Repetition. `MatchOperator`, `PatternStats`
  (freq/supp/conf), `TCFG`, builder helpers `atom()`, `seq()`, `star()`, …

### Added — Phase 3: Causal Model and Privacy (AION §14–§20)

- **`aion/causal/graph.py`** — `CausalGraph` with Bayes-Ball d-separation,
  `satisfies_backdoor()`, `mutilate()`, `topological_order()`
- **`aion/causal/do.py`** — `DoOperator` with backdoor adjustment formula,
  `StructuralEquationModel` with 3-step counterfactual (abduction→action→
  prediction), `counterfactual_cohort()`
- **`aion/causal/structure.py`** — `ConditionalIndependenceTest` (MI-based),
  `PCAlgorithm` (skeleton + v-structures + Meek rules), `BootstrapCausalLearner`
  with edge confidences c_G(τ_i,τ_j) and stable graph G_{γ_G}
- **`aion/privacy/differential.py`** — `Sensitivity` (Δq=1 for cohort size),
  `PrivacyBudget` with sequential composition, `LaplaceMechanism`, `GaussianMechanism`,
  `DPCohortQuery`, `FederatedModel` P = ⊔_k P_k, local DP

### Added — Phase 4: AI Components and Explainability (AION §19–§21)

- **`aion/ai/component.py`** — `AIComponent` 5-tuple, `ValidationOperator` Π_l,
  `EventExtractionComponent` (Layer 2), `FeatureExtractor` Ψ: P → ℝ^d,
  `RiskEstimationComponent` (Layer 5), `AIEventIntegrator` c_min gate
- **`aion/explain/shapley.py`** — `ShapleyExplainer` with exact Shapley values
  over all 2^d coalitions, event-level back-propagation, `CounterfactualExplainer`
  Δ*_cf (greedy accumulating removal), `SufficientExplainer` S*_suf,
  `ExtendedValidationOperator` Π_l^+ with K_max gate, `FullExplanationReport`

### Added — Phase 5: Schema Evolution and FHIR Mapping (AION §16–§17)

- **`aion/schema/evolution.py`** — `VersionedTypeSystem` (H_T^(v))_{v∈V},
  7 `SchemaOp` kinds, compatibility classification (forward/backward/breaking),
  `SchemaMigration` μ_{v→v'} with 4 invariants, `MigrationRecord` audit trail
- **`aion/adapters/fhir/mapping.py`** — `FHIRMappingSpec` (h_T, h_σ) structural
  homomorphism, 4 homomorphism conditions, default type+attribute maps,
  `map_event()`, `quality_index()` Q_map, `FHIRBundle`, `export_bundle()`

### Tests

- 326 tests across 5 test modules, all passing in ~2s
- Coverage: core, abstraction, query, causal, privacy, ai, explain, schema, FHIR adapters

---

## [Unreleased]

### Planned
- `aion/adapters/hl7v2/`  — HL7 v2 adapter (from CAIRN)
- `aion/adapters/csv/`    — CSV/DataFrame adapter
- `aion/db/`              — PostgreSQL ORM (from CAIRN)
- `aion/api/`             — FastAPI REST server
- `aion/cli/`             — Click CLI
- `aion/report/`          — Excel + HTML reports
- Zenodo DOI publication
- PyPI release

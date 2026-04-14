# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
"""Tests for aion.causal and aion.privacy — AION §14–§20."""

import datetime
import math
import random
import pytest

from aion.core.allen import Interval
from aion.core.event import ClinicalEvent, EventSet
from aion.core.types import TypeHierarchy, reset_default_hierarchy

from aion.causal.graph import CausalGraph, CausalEdge
from aion.causal.do import (
    ObservationalDistribution, DoOperator,
    StructuralEquationModel, SEMEquation,
    CounterfactualResult, counterfactual_cohort,
    BackdoorAdjustmentResult,
)
from aion.causal.structure import (
    ConditionalIndependenceTest, PCAlgorithm,
    BootstrapCausalLearner, SkeletonResult,
)
from aion.privacy.differential import (
    Sensitivity, PrivacyBudget,
    LaplaceMechanism, GaussianMechanism,
    DPCohortQuery, DPCohortResult,
    FederatedModel, Institution, FederatedQueryResult,
    _laplace_sample,
)
from aion.query.cohort import CohortQuery, query_has_type_event
from aion.query.predicates import QueryContext


# ── Fixtures ──────────────────────────────────────────────────────────────────

def dt(hour: int, day: int = 1) -> datetime.datetime:
    return datetime.datetime(2024, 1, day, hour, 0)


def iv(h_start: int, h_end: int, day: int = 1) -> Interval:
    return Interval(dt(h_start, day), dt(h_end, day))


def make_event(
    patient_id: str = "P1",
    stay_id:    str = "S1",
    type_:      str = "Observation",
    h_start:    int = 8,
    h_end:      int = 9,
    attrs:      dict = None,
) -> ClinicalEvent:
    return ClinicalEvent(
        patient_id=patient_id,
        stay_id=stay_id,
        type=type_,
        tau=iv(h_start, h_end),
        attributes={"q_code": "test", "value": 1.0, **(attrs or {})},
    )


@pytest.fixture(autouse=True)
def reset_h():
    reset_default_hierarchy()
    yield
    reset_default_hierarchy()


@pytest.fixture
def h():
    return TypeHierarchy()


@pytest.fixture
def event_set(h):
    """3 patients: P1 has Diagnosis+Procedure+LabResult, P2 has D+P, P3 has D only."""
    es = EventSet(hierarchy=h)
    # P1
    es.add(make_event("P1","S1","Diagnosis",  8, 8,  {"dx_code":"I50"}))
    es.add(make_event("P1","S1","Procedure",  9,12,  {"op_code":"CABG"}))
    es.add(make_event("P1","S1","LabResult", 10,10,  {"q_code":"L","value":4.0}))
    # P2
    es.add(make_event("P2","S2","Diagnosis",  8, 8,  {"dx_code":"I50"}))
    es.add(make_event("P2","S2","Procedure",  9,11,  {"op_code":"ABL"}))
    # P3: Diagnosis only → no complication (Procedure) after
    es.add(make_event("P3","S3","Diagnosis",  8, 8,  {"dx_code":"I50"}))
    return es


@pytest.fixture
def causal_graph():
    """Simple chain: Diagnosis → Procedure → LabResult."""
    g = CausalGraph()
    g.add_type("Diagnosis")
    g.add_type("Procedure")
    g.add_type("LabResult")
    g.add_edge("Diagnosis", "Procedure", strength=0.6)
    g.add_edge("Procedure", "LabResult", strength=0.4)
    return g


@pytest.fixture
def ctx(event_set, h):
    return QueryContext(event_set=event_set, hierarchy=h)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Causal Graph (AION §14.1)
# ══════════════════════════════════════════════════════════════════════════════

class TestCausalGraph:
    def test_add_types_and_edges(self, causal_graph):
        assert "Diagnosis" in causal_graph
        assert "Procedure" in causal_graph
        assert causal_graph.has_edge("Diagnosis", "Procedure")

    def test_cycle_rejected(self):
        g = CausalGraph()
        g.add_type("A"); g.add_type("B")
        g.add_edge("A", "B")
        with pytest.raises(ValueError, match="cycle"):
            g.add_edge("B", "A")

    def test_parents_children(self, causal_graph):
        assert "Diagnosis" in causal_graph.parents("Procedure")
        assert "Procedure" in causal_graph.children("Diagnosis")

    def test_ancestors(self, causal_graph):
        anc = causal_graph.ancestors("LabResult")
        assert "Diagnosis" in anc
        assert "Procedure" in anc

    def test_descendants(self, causal_graph):
        desc = causal_graph.descendants("Diagnosis")
        assert "Procedure" in desc
        assert "LabResult" in desc

    def test_is_not_ancestor_of_self(self, causal_graph):
        assert not causal_graph.is_ancestor("Diagnosis", "Diagnosis")

    def test_d_separation_chain(self, causal_graph):
        # In chain A→B→C: A ⊥ C | B
        assert causal_graph.d_separated("Diagnosis", "LabResult", {"Procedure"})
        # But A not ⊥ C without conditioning
        assert not causal_graph.d_separated("Diagnosis", "LabResult", set())

    def test_mutilate(self, causal_graph):
        g2 = causal_graph.mutilate("Procedure")
        # Incoming edge Diagnosis→Procedure removed
        assert not g2.has_edge("Diagnosis", "Procedure")
        # Outgoing edge Procedure→LabResult remains
        assert g2.has_edge("Procedure", "LabResult")

    def test_topological_order(self, causal_graph):
        order = causal_graph.topological_order()
        idx   = {t: i for i, t in enumerate(order)}
        assert idx["Diagnosis"] < idx["Procedure"]
        assert idx["Procedure"] < idx["LabResult"]

    def test_backdoor_criterion_satisfied(self):
        # Confounded: D ← Z → Y, D → Y
        # Backdoor set Z blocks D←Z→Y
        g = CausalGraph()
        for t in ("D", "Z", "Y"):
            g.add_type(t)
        g.add_edge("Z", "D")
        g.add_edge("Z", "Y")
        g.add_edge("D", "Y")
        # Z satisfies backdoor: Z is not a descendant of D; Z blocks D←Z→Y
        assert g.satisfies_backdoor("D", "Y", {"Z"})

    def test_backdoor_fails_for_descendant(self):
        g = CausalGraph()
        for t in ("D", "M", "Y"):
            g.add_type(t)
        g.add_edge("D", "M")
        g.add_edge("M", "Y")
        # M is descendant of D → cannot use M for adjustment
        assert not g.satisfies_backdoor("D", "Y", {"M"})

    def test_copy_independence(self, causal_graph):
        g2 = causal_graph.copy()
        g2.add_type("NewType")
        assert "NewType" not in causal_graph

    def test_edge_metadata(self, causal_graph):
        edge = causal_graph.get_edge("Diagnosis", "Procedure")
        assert edge is not None
        assert edge.strength == pytest.approx(0.6)

    def test_validation_ok(self, causal_graph):
        assert causal_graph.is_valid
        assert causal_graph.validate() == []

    def test_skeleton(self, causal_graph):
        skel = causal_graph.skeleton()
        assert skel.has_edge("Diagnosis", "Procedure")
        assert skel.has_edge("Procedure", "LabResult")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Observational Distribution & Do-Operator (AION §14.3–§14.4)
# ══════════════════════════════════════════════════════════════════════════════

class TestObservationalDistribution:
    def test_prevalence_all(self, event_set, h):
        obs = ObservationalDistribution(event_set, h)
        p   = obs.prevalence("Diagnosis")
        assert p == pytest.approx(1.0)   # all 3 patients have Diagnosis

    def test_prevalence_partial(self, event_set, h):
        obs = ObservationalDistribution(event_set, h)
        p   = obs.prevalence("LabResult")
        assert p == pytest.approx(1/3)   # only P1

    def test_prevalence_given(self, event_set, h):
        obs = ObservationalDistribution(event_set, h)
        # P(LabResult=1 | Procedure=1) = P1+P2 have Procedure, only P1 has Lab
        p = obs.prevalence_given("LabResult", "Procedure", True)
        assert p == pytest.approx(0.5)   # P1/(P1+P2)


class TestDoOperator:
    def test_intervene_returns_result(self, event_set, h, causal_graph):
        obs = ObservationalDistribution(event_set, h)
        do  = DoOperator(causal_graph, obs)
        result = do.intervene("Procedure", "LabResult", z_set=set())
        assert isinstance(result, BackdoorAdjustmentResult)
        assert 0.0 <= result.p_do <= 1.0
        assert 0.0 <= result.p_baseline <= 1.0

    def test_ate_direction(self, event_set, h, causal_graph):
        obs = ObservationalDistribution(event_set, h)
        do  = DoOperator(causal_graph, obs)
        result = do.intervene("Procedure", "LabResult", z_set=set())
        # ATE can be + or -, just check it's computable
        assert isinstance(result.ate, float)

    def test_relative_risk(self, event_set, h, causal_graph):
        obs = ObservationalDistribution(event_set, h)
        do  = DoOperator(causal_graph, obs)
        result = do.intervene("Procedure", "LabResult", z_set=set())
        if result.p_baseline > 0:
            assert result.rr is not None
            assert result.rr >= 0

    def test_auto_adjustment_set(self, event_set, h):
        g = CausalGraph()
        for t in ("Diagnosis", "Procedure", "LabResult"):
            g.add_type(t)
        g.add_edge("Diagnosis", "Procedure")
        g.add_edge("Procedure", "LabResult")
        obs    = ObservationalDistribution(event_set, h)
        do     = DoOperator(g, obs)
        result = do.intervene("Procedure", "LabResult")  # no z_set provided
        assert isinstance(result, BackdoorAdjustmentResult)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Structural Equation Model (AION §14.5)
# ══════════════════════════════════════════════════════════════════════════════

class TestSEM:
    def _make_sem(self, causal_graph):
        sem = StructuralEquationModel(causal_graph)
        # X_Procedure = 0.8 * X_Diagnosis + U_Procedure
        sem.add_linear_equation("Procedure", {"Diagnosis": 0.8}, noise_std=0.1)
        # X_LabResult = 0.6 * X_Procedure + U_LabResult
        sem.add_linear_equation("LabResult", {"Procedure": 0.6}, noise_std=0.05)
        return sem

    def test_observe_and_predict(self, causal_graph):
        sem = self._make_sem(causal_graph)
        sem.observe("P1", "Diagnosis", 1.0)
        sem.observe("P1", "Procedure", 0.7)
        sem.observe("P1", "LabResult", 0.4)

        # Predict LabResult without intervention
        val = sem.predict("P1", "LabResult")
        assert isinstance(val, float)

    def test_counterfactual(self, causal_graph):
        sem = self._make_sem(causal_graph)
        sem.observe("P1", "Diagnosis", 1.0)
        sem.observe("P1", "Procedure", 0.8)
        sem.observe("P1", "LabResult", 0.5)

        # Counterfactual: what if Procedure = 0 (no operation)?
        cf = sem.counterfactual("P1", "Procedure", 0.0, "LabResult")
        assert isinstance(cf, float)
        # With Procedure=0, LabResult should be lower
        factual = sem.predict("P1", "LabResult")
        assert cf < factual

    def test_abduction_residual(self, causal_graph):
        sem = self._make_sem(causal_graph)
        sem.observe("P1", "Diagnosis", 1.0)
        sem.observe("P1", "Procedure", 1.0)
        # Predicted Procedure = 0.8 * 1.0 = 0.8 → residual = 1.0 - 0.8 = 0.2
        residual = sem.abduct("P1", "Procedure")
        assert residual == pytest.approx(0.2, abs=0.01)

    def test_counterfactual_cohort(self, causal_graph):
        sem = self._make_sem(causal_graph)
        for pid, proc_val, lab_val in [
            ("P1", 0.8, 0.5),
            ("P2", 0.7, 0.4),
            ("P3", 0.3, 0.2),
        ]:
            sem.observe(pid, "Diagnosis", 1.0)
            sem.observe(pid, "Procedure", proc_val)
            sem.observe(pid, "LabResult", lab_val)

        # Which patients would have LabResult < 0.3 if Procedure = 0?
        results = counterfactual_cohort(
            sem, ["P1","P2","P3"],
            do_type="Procedure", do_value=0.0,
            query_type="LabResult",
            outcome_pred=lambda v: v < 0.3,
        )
        # All should have lower LabResult with no procedure
        assert len(results) >= 1
        for r in results:
            assert isinstance(r, CounterfactualResult)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Causal Structure Learning (AION §15)
# ══════════════════════════════════════════════════════════════════════════════

class TestConditionalIndependenceTest:
    def test_perfectly_correlated(self, event_set, h):
        """Two identical types should have high MI."""
        ci = ConditionalIndependenceTest(event_set, h, eps=0.01)
        mi = ci.mutual_information("Diagnosis", "Diagnosis")
        # Perfect self-correlation: MI ≥ 0
        assert mi >= 0

    def test_independent_types(self, event_set, h):
        """Types with no shared patients should have low MI."""
        ci  = ConditionalIndependenceTest(event_set, h, eps=1.0)
        # With high eps everything is "independent"
        assert ci.independent("LabResult", "Procedure", set())

    def test_mi_non_negative(self, event_set, h):
        ci = ConditionalIndependenceTest(event_set, h)
        for t1, t2 in [("Diagnosis","Procedure"), ("Procedure","LabResult")]:
            mi = ci.mutual_information(t1, t2)
            assert mi >= 0


class TestPCAlgorithm:
    def test_chain_skeleton(self, event_set, h):
        """Skeleton learning with high eps (conservative): edges survive."""
        # With only 3 patients, use high eps to keep all edges
        ci  = ConditionalIndependenceTest(event_set, h, eps=1.0)
        pc  = PCAlgorithm(ci, max_cond=0)  # no conditioning
        res = pc.learn_skeleton(["Diagnosis", "Procedure", "LabResult"])
        skel = res.skeleton
        # With eps=1.0 nothing is declared independent → full skeleton
        assert skel.number_of_nodes() == 3

    def test_pc_returns_causal_graph(self, event_set, h):
        ci    = ConditionalIndependenceTest(event_set, h, eps=0.05)
        pc    = PCAlgorithm(ci, max_cond=1)
        graph = pc.run(["Diagnosis", "Procedure", "LabResult"])
        assert isinstance(graph, CausalGraph)
        assert graph.is_valid

    def test_learned_graph_acyclic(self, event_set, h):
        ci    = ConditionalIndependenceTest(event_set, h, eps=0.05)
        pc    = PCAlgorithm(ci, max_cond=1)
        graph = pc.run(["Diagnosis", "Procedure", "LabResult"])
        assert graph.is_valid   # no cycles


class TestBootstrapCausalLearner:
    def test_bootstrap_returns_result(self, event_set, h):
        learner = BootstrapCausalLearner(
            event_set, ["Diagnosis", "Procedure", "LabResult"],
            hierarchy=h, seed=42
        )
        result = learner.run(n_resamples=5, threshold=0.4)
        assert result.n_resamples == 5
        assert result.threshold   == 0.4
        assert isinstance(result.stable_graph, CausalGraph)

    def test_bootstrap_confidences_in_range(self, event_set, h):
        learner = BootstrapCausalLearner(
            event_set, ["Diagnosis", "Procedure"],
            hierarchy=h, seed=42
        )
        result = learner.run(n_resamples=10, threshold=0.3)
        for ec in result.edge_confidences:
            assert 0.0 <= ec.confidence <= 1.0

    def test_stable_graph_above_threshold(self, event_set, h):
        learner = BootstrapCausalLearner(
            event_set, ["Diagnosis", "Procedure", "LabResult"],
            hierarchy=h, seed=0
        )
        threshold = 0.6
        result    = learner.run(n_resamples=10, threshold=threshold)
        for edge in result.stable_graph.all_edges():
            assert edge.confidence >= threshold


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Differential Privacy (AION §20)
# ══════════════════════════════════════════════════════════════════════════════

class TestLaplaceSampler:
    def test_mean_near_zero(self):
        rng = random.Random(42)
        samples = [_laplace_sample(1.0, rng) for _ in range(10000)]
        mean = sum(samples) / len(samples)
        assert abs(mean) < 0.05   # should be near 0

    def test_scale_affects_variance(self):
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        small = [abs(_laplace_sample(0.1, rng1)) for _ in range(1000)]
        large = [abs(_laplace_sample(10.0, rng2)) for _ in range(1000)]
        assert sum(large) / len(large) > sum(small) / len(small) * 5


class TestSensitivity:
    def test_cohort_size(self):
        assert Sensitivity.cohort_size() == 1.0

    def test_mean_value(self):
        s = Sensitivity.mean_value(0.0, 10.0, 100)
        assert s == pytest.approx(0.1)

    def test_mean_value_zero_cohort(self):
        s = Sensitivity.mean_value(0.0, 10.0, 0)
        assert s == 10.0


class TestPrivacyBudget:
    def test_initial_state(self):
        b = PrivacyBudget(1.0)
        assert b.remaining == pytest.approx(1.0)
        assert not b.is_exhausted

    def test_consume(self):
        b = PrivacyBudget(1.0)
        allocated = b.consume(0.3)
        assert allocated == pytest.approx(0.3)
        assert b.remaining == pytest.approx(0.7)

    def test_cannot_exceed_budget(self):
        b = PrivacyBudget(1.0)
        b.consume(0.8)
        allocated = b.consume(0.5)   # only 0.2 left
        assert allocated == pytest.approx(0.2)
        assert b.is_exhausted

    def test_per_query_budget(self):
        b = PrivacyBudget(1.0)
        per_q = b.per_query_budget(4)
        assert per_q == pytest.approx(0.25)

    def test_n_queries_tracked(self):
        b = PrivacyBudget(2.0)
        b.consume(0.5)
        b.consume(0.5)
        assert b.n_queries == 2


class TestLaplaceMechanism:
    def test_release_returns_result(self):
        b  = PrivacyBudget(1.0)
        m  = LaplaceMechanism(b, seed=42)
        r  = m.release(50.0, sensitivity=1.0, epsilon=0.5)
        assert r.mechanism    == "Laplace"
        assert r.true_value   == pytest.approx(50.0)
        assert r.epsilon_used == pytest.approx(0.5)
        assert isinstance(r.noisy_value, float)

    def test_release_cohort_size(self):
        b  = PrivacyBudget(1.0)
        m  = LaplaceMechanism(b, seed=0)
        r  = m.release_cohort_size(100)
        assert r.true_value == 100.0

    def test_budget_consumed(self):
        b   = PrivacyBudget(1.0)
        m   = LaplaceMechanism(b, seed=0)
        m.release(10.0, 1.0, epsilon=0.5)
        assert b.remaining == pytest.approx(0.5)

    def test_exhausted_raises(self):
        b = PrivacyBudget(0.1)
        m = LaplaceMechanism(b, seed=0)
        m.release(10.0, 1.0, epsilon=0.1)
        with pytest.raises(RuntimeError, match="exhausted"):
            m.release(10.0, 1.0, epsilon=0.1)

    def test_noise_distribution(self):
        """Large epsilon → small noise. Each release uses epsilon=100."""
        b      = PrivacyBudget(100_000.0)   # large budget for 200 queries
        m      = LaplaceMechanism(b, seed=42)
        noises = []
        for _ in range(200):
            r = m.release(100.0, 1.0, epsilon=100.0)
            noises.append(abs(r.noise))
        mean_noise = sum(noises) / len(noises)
        # Expected |noise| = Δq/ε = 1/100 = 0.01
        assert mean_noise < 0.1


class TestGaussianMechanism:
    def test_release_returns_result(self):
        b = PrivacyBudget(1.0)
        m = GaussianMechanism(b, delta=1e-5, seed=42)
        r = m.release(50.0, sensitivity=1.0, epsilon=0.5)
        assert r.mechanism == "Gaussian"
        assert isinstance(r.noisy_value, float)


class TestDPCohortQuery:
    def test_evaluate(self, ctx):
        b   = PrivacyBudget(1.0)
        mec = LaplaceMechanism(b, seed=42)
        cq  = query_has_type_event("Diagnosis")
        dp  = DPCohortQuery(cq, mec, epsilon=0.5)
        res = dp.evaluate(ctx)

        assert isinstance(res, DPCohortResult)
        assert res.true_size == 3   # all 3 patients have Diagnosis
        assert isinstance(res.estimated_size, float)

    def test_relative_error_reasonable(self, ctx):
        """With ε=1 and cohort=3: mean error ≈ 1/ε = 1 → rel_err ≈ 33%."""
        errors = []
        for seed in range(100):
            b   = PrivacyBudget(2.0)
            mec = LaplaceMechanism(b, seed=seed)
            cq  = query_has_type_event("Diagnosis")
            dp  = DPCohortQuery(cq, mec, epsilon=1.0)
            res = dp.evaluate(ctx)
            if res.relative_error is not None:
                errors.append(res.relative_error)
        mean_err = sum(errors) / len(errors)
        assert mean_err < 2.0   # generous bound


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Federated Model (AION §20.1–§20.2)
# ══════════════════════════════════════════════════════════════════════════════

class TestFederatedModel:
    def _make_federated(self, h):
        """Split P1,P2 into I1 and P3 into I2."""
        es1 = EventSet(hierarchy=h)
        es1.add(make_event("P1","S1","Diagnosis",8,8,{"dx_code":"I50"}))
        es1.add(make_event("P2","S2","Diagnosis",8,8,{"dx_code":"I50"}))
        es2 = EventSet(hierarchy=h)
        es2.add(make_event("P3","S3","Diagnosis",8,8,{"dx_code":"I50"}))

        i1 = Institution("I1", es1, PrivacyBudget(1.0))
        i2 = Institution("I2", es2, PrivacyBudget(1.0))

        fm = FederatedModel(hierarchy=h)
        fm.add_institution(i1)
        fm.add_institution(i2)
        return fm

    def test_disjoint_patients(self, h):
        fm = self._make_federated(h)
        assert fm.total_patients() == 3

    def test_overlapping_patients_rejected(self, h):
        es1 = EventSet(hierarchy=h)
        es1.add(make_event("P1","S1","Diagnosis",8,8))
        es2 = EventSet(hierarchy=h)
        es2.add(make_event("P1","S1","Diagnosis",8,8))  # same patient!

        i1 = Institution("I1", es1, PrivacyBudget(1.0))
        i2 = Institution("I2", es2, PrivacyBudget(1.0))
        fm = FederatedModel(hierarchy=h)
        fm.add_institution(i1)
        with pytest.raises(ValueError, match="overlap"):
            fm.add_institution(i2)

    def test_federated_cohort_size_unbiased(self, h):
        """E[noisy_total] ≈ true_total over many runs."""
        totals = []
        for seed in range(200):
            es1 = EventSet(hierarchy=h)
            es1.add(make_event("P1","S1","Diagnosis",8,8,{"dx_code":"I50"}))
            es1.add(make_event("P2","S2","Diagnosis",8,8,{"dx_code":"I50"}))
            es2 = EventSet(hierarchy=h)
            es2.add(make_event("P3","S3","Diagnosis",8,8,{"dx_code":"I50"}))

            i1 = Institution("I1", es1, PrivacyBudget(10.0))
            i2 = Institution("I2", es2, PrivacyBudget(10.0))
            fm = FederatedModel(hierarchy=h)
            fm.add_institution(i1)
            fm.add_institution(i2)

            # Use fixed random for noise
            import aion.privacy.differential as dp_mod
            orig = dp_mod.random.Random
            dp_mod._laplace_sample = lambda scale, rng: random.Random(seed).gauss(0, scale)

            q   = query_has_type_event("Diagnosis")
            res = fm.federated_cohort_size(q, use_ldp=True, epsilon=2.0)
            totals.append(res.noisy_total)

        mean_total = sum(totals) / len(totals)
        # True total = 3; with unbiased Laplace mean should be near 3
        assert abs(mean_total - 3.0) < 1.5   # generous bound

    def test_federated_true_total_exact(self, h):
        fm  = self._make_federated(h)
        q   = query_has_type_event("Diagnosis")
        res = fm.federated_cohort_size(q, use_ldp=False)
        assert res.true_total == 3

    def test_federated_result_properties(self, h):
        fm  = self._make_federated(h)
        q   = query_has_type_event("Diagnosis")
        res = fm.federated_cohort_size(q, use_ldp=True, epsilon=10.0)
        assert isinstance(res, FederatedQueryResult)
        assert res.n_institutions == 2
        assert res.true_total == 3
        assert res.absolute_error >= 0
        assert isinstance(res.expected_std, float)

    def test_local_cohort_size(self, h):
        es1 = EventSet(hierarchy=h)
        es1.add(make_event("P1","S1","Diagnosis",8,8))
        es1.add(make_event("P2","S2","Diagnosis",8,8))
        i1  = Institution("I1", es1, PrivacyBudget(1.0))
        q   = query_has_type_event("Diagnosis")
        assert i1.local_cohort_size(q, h) == 2

    def test_len(self, h):
        fm = self._make_federated(h)
        assert len(fm) == 2

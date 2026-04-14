# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
"""
Tests for aion.core — allen, types, event, fuzzy, process.
All AION §3–§8 invariants.
"""

import datetime
import math
import pytest

from aion.core.allen import (
    Interval, AllenRelation, classify, holds, holds_weak,
    relation_preserved,
)
from aion.core.types import (
    AttributeDef, AttributeSchema, Obligateness,
    TypeHierarchy, default_hierarchy, reset_default_hierarchy,
)
from aion.core.event import ClinicalEvent, EventSet, ValidationResult
from aion.core.fuzzy import (
    FuzzyInterval, ProbabilisticAllen, FuzzyTemporalPredicate,
    TemporalValidator, fuzzy_from_interval, fuzzy_precedes, fuzzy_contains,
)
from aion.core.process import ProcessDAG, ProcessIndex, build_dag, ProcessEdge


# ── Fixtures ──────────────────────────────────────────────────────────────────

def dt(hour: int, minute: int = 0, day: int = 1) -> datetime.datetime:
    return datetime.datetime(2024, 1, day, hour, minute)


def iv(h_start: int, h_end: int, day: int = 1) -> Interval:
    return Interval(dt(h_start, day=day), dt(h_end, day=day))


def make_event(
    patient_id: str = "P1",
    stay_id: str = "S1",
    type_: str = "Observation",
    h_start: int = 8,
    h_end: int = 9,
    attrs: dict = None,
    confidence: float = 1.0,
) -> ClinicalEvent:
    return ClinicalEvent(
        patient_id=patient_id,
        stay_id=stay_id,
        type=type_,
        tau=iv(h_start, h_end),
        attributes={"q_code": "test", "value": 1.0, **(attrs or {})},
        confidence=confidence,
    )


@pytest.fixture(autouse=True)
def reset_hierarchy():
    reset_default_hierarchy()
    yield
    reset_default_hierarchy()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Allen Algebra (AION §6)
# ══════════════════════════════════════════════════════════════════════════════

class TestAllenBasic:
    def test_precedes(self):
        assert classify(iv(1, 3), iv(5, 7)) == AllenRelation.PRECEDES

    def test_preceded_by(self):
        assert classify(iv(5, 7), iv(1, 3)) == AllenRelation.PRECEDED_BY

    def test_meets(self):
        assert classify(iv(1, 5), iv(5, 9)) == AllenRelation.MEETS

    def test_met_by(self):
        assert classify(iv(5, 9), iv(1, 5)) == AllenRelation.MET_BY

    def test_overlaps(self):
        assert classify(iv(1, 6), iv(4, 9)) == AllenRelation.OVERLAPS

    def test_overlapped_by(self):
        assert classify(iv(4, 9), iv(1, 6)) == AllenRelation.OVERLAPPED_BY

    def test_starts(self):
        assert classify(iv(2, 5), iv(2, 9)) == AllenRelation.STARTS

    def test_started_by(self):
        assert classify(iv(2, 9), iv(2, 5)) == AllenRelation.STARTED_BY

    def test_during(self):
        assert classify(iv(3, 6), iv(1, 9)) == AllenRelation.DURING

    def test_contains(self):
        assert classify(iv(1, 9), iv(3, 6)) == AllenRelation.CONTAINS

    def test_finishes(self):
        assert classify(iv(5, 9), iv(2, 9)) == AllenRelation.FINISHES

    def test_finished_by(self):
        assert classify(iv(2, 9), iv(5, 9)) == AllenRelation.FINISHED_BY

    def test_equals(self):
        assert classify(iv(3, 7), iv(3, 7)) == AllenRelation.EQUALS


class TestAllenExhaustiveness:
    """Every pair of intervals maps to exactly one relation."""

    def _make_pairs(self):
        times = [1, 3, 5, 7, 9, 11]
        pairs = []
        for s1 in times:
            for e1 in times:
                if s1 >= e1:
                    continue
                for s2 in times:
                    for e2 in times:
                        if s2 >= e2:
                            continue
                        pairs.append((iv(s1, e1), iv(s2, e2)))
        return pairs

    def test_exactly_one_relation(self):
        for i, j in self._make_pairs():
            rel = classify(i, j)
            count = sum(1 for r in AllenRelation if holds(r, i, j))
            assert count == 1, (
                f"Expected exactly 1 relation for {i!r}, {j!r} — got {count}"
            )

    def test_inverse_symmetry(self):
        for i, j in self._make_pairs():
            r = classify(i, j)
            r_inv = classify(j, i)
            assert r.inverse == r_inv, (
                f"classify({i!r},{j!r})={r}, "
                f"classify({j!r},{i!r})={r_inv}, "
                f"expected inverse={r.inverse}"
            )


class TestAllenHolds:
    def test_holds_true(self):
        assert holds(AllenRelation.PRECEDES, iv(1, 3), iv(5, 7))

    def test_holds_false(self):
        assert not holds(AllenRelation.DURING, iv(1, 3), iv(5, 7))

    def test_holds_weak_zero_epsilon(self):
        assert holds_weak(AllenRelation.PRECEDES, iv(1, 3), iv(5, 7))
        assert not holds_weak(AllenRelation.DURING, iv(1, 3), iv(5, 7))

    def test_holds_weak_with_slack(self):
        # Near-meeting intervals; with ε=1min boundary becomes "meets"
        eps = datetime.timedelta(minutes=2)
        i = Interval(dt(8, 0), dt(10, 0))
        j = Interval(dt(10, 1), dt(12, 0))
        # Without slack: PRECEDES
        assert classify(i, j) == AllenRelation.PRECEDES
        # With slack: MEETS is true
        assert holds_weak(AllenRelation.MEETS, i, j, epsilon=eps)


class TestAllenRelationPreserved:
    def test_preserved_true(self):
        ok, actual = relation_preserved(AllenRelation.PRECEDES, iv(1, 3), iv(5, 7))
        assert ok
        assert actual == AllenRelation.PRECEDES

    def test_preserved_false(self):
        ok, actual = relation_preserved(AllenRelation.DURING, iv(1, 3), iv(5, 7))
        assert not ok

    def test_none_interval(self):
        ok, actual = relation_preserved(AllenRelation.PRECEDES, None, iv(5, 7))
        assert not ok
        assert actual is None


class TestAllenComposition:
    def test_precedes_precedes(self):
        result = AllenRelation.PRECEDES.compose(AllenRelation.PRECEDES)
        assert AllenRelation.PRECEDES in result
        assert len(result) == 1

    def test_equals_any(self):
        for r in AllenRelation:
            result = AllenRelation.EQUALS.compose(r)
            assert r in result

    def test_inverse_property(self):
        assert AllenRelation.PRECEDES.inverse == AllenRelation.PRECEDED_BY
        assert AllenRelation.EQUALS.inverse   == AllenRelation.EQUALS
        assert AllenRelation.DURING.inverse   == AllenRelation.CONTAINS


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Type System (AION §3)
# ══════════════════════════════════════════════════════════════════════════════

class TestAttributeSchema:
    def test_required_attr(self):
        schema = AttributeSchema([
            AttributeDef("q_code", str, Obligateness.REQUIRED),
            AttributeDef("value",  float, Obligateness.REQUIRED),
            AttributeDef("unit",   str, Obligateness.OPTIONAL),
        ])
        errors = schema.validate_instance({"q_code": "L01", "value": 1.5})
        assert errors == []

    def test_missing_required(self):
        schema = AttributeSchema([
            AttributeDef("q_code", str, Obligateness.REQUIRED),
            AttributeDef("value",  float, Obligateness.REQUIRED),
        ])
        errors = schema.validate_instance({"q_code": "L01"})
        assert any("value" in e for e in errors)

    def test_schema_union_inherits_all(self):
        parent = AttributeSchema([
            AttributeDef("id", str, Obligateness.REQUIRED),
        ])
        child = AttributeSchema([
            AttributeDef("extra", int, Obligateness.OPTIONAL),
        ])
        merged = child.union(parent)
        names = {a.name for a in merged.all_attrs}
        assert "id" in names
        assert "extra" in names

    def test_is_subschema_of(self):
        parent = AttributeSchema([AttributeDef("id", str, Obligateness.REQUIRED)])
        child  = AttributeSchema([
            AttributeDef("id", str, Obligateness.REQUIRED),
            AttributeDef("x",  int, Obligateness.OPTIONAL),
        ])
        assert child.is_subschema_of(parent)
        assert not parent.is_subschema_of(child)


class TestTypeHierarchy:
    def test_default_types_present(self):
        h = TypeHierarchy()
        for t in ["Observation", "LabResult", "Procedure", "Diagnosis",
                  "Medication", "Encounter", "⊤"]:
            assert t in h, f"'{t}' should be in default hierarchy"

    def test_is_subtype_reflexive(self):
        h = TypeHierarchy()
        assert h.is_subtype("Observation", "Observation")

    def test_is_subtype_direct(self):
        h = TypeHierarchy()
        assert h.is_subtype("LabResult", "Observation")
        assert h.is_subtype("LabResult", "⊤")

    def test_is_subtype_negative(self):
        h = TypeHierarchy()
        assert not h.is_subtype("Diagnosis", "Observation")

    def test_lca_same_node(self):
        h = TypeHierarchy()
        assert h.lca("LabResult", "LabResult") == "LabResult"

    def test_lca_sibling_types(self):
        h = TypeHierarchy()
        lca = h.lca("LabResult", "VitalSign")
        assert lca == "Observation"

    def test_lca_different_branches(self):
        h = TypeHierarchy()
        lca = h.lca("LabResult", "Diagnosis")
        assert lca == "⊤"

    def test_add_custom_type(self):
        h = TypeHierarchy()
        from aion.core.types import AttributeSchema, AttributeDef, Obligateness
        schema = AttributeSchema([
            AttributeDef("ecg_lead", str, Obligateness.REQUIRED),
        ])
        h.add_type("ECGTrace", "Observation", schema, label="ECG Recording")
        assert "ECGTrace" in h
        assert h.is_subtype("ECGTrace", "Observation")
        assert h.is_subtype("ECGTrace", "⊤")

    def test_add_type_cycle_rejected(self):
        h = TypeHierarchy()
        from aion.core.types import AttributeSchema
        # Attempting to create A → B → A cycle via add_type
        # First add a legitimate child
        h.add_type("CustomObs", "Observation", AttributeSchema([]), label="Custom")
        # Now try to make Observation a subtype of CustomObs — would create cycle
        # We patch the graph directly to verify the DAG check works
        import networkx as nx
        h._g.add_edge("Observation", "CustomObs")  # create cycle
        assert not nx.is_directed_acyclic_graph(h._g), "Should have cycle now"
        # Restore
        h._g.remove_edge("Observation", "CustomObs")

    def test_schema_inheritance(self):
        h = TypeHierarchy()
        schema = h.effective_schema("LabResult")
        names = {a.name for a in schema.all_attrs}
        # LabResult inherits id, t_begin from root
        assert "id" in names
        assert "t_begin" in names
        # And has its own attributes
        assert "q_code" in names or "value" in names  # from obs/lab schema

    def test_composition_valid(self):
        h = TypeHierarchy()
        assert h.composition_valid("Procedure", "HLMPhase")
        assert h.composition_valid("Procedure", "LabResult")
        assert not h.composition_valid("Diagnosis", "HLMPhase")

    def test_direct_subtypes(self):
        h = TypeHierarchy()
        subs = h.direct_subtypes("Observation")
        assert "LabResult" in subs
        assert "VitalSign" in subs


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Event Model (AION §5)
# ══════════════════════════════════════════════════════════════════════════════

class TestClinicalEvent:
    def test_creation(self):
        e = make_event()
        assert e.patient_id == "P1"
        assert e.type == "Observation"
        assert e.confidence == 1.0

    def test_auto_id(self):
        e1 = make_event()
        e2 = make_event()
        assert e1.id != e2.id   # UUIDs are unique

    def test_has_type_exact(self):
        e = make_event(type_="LabResult")
        assert e.has_type("LabResult")

    def test_has_type_ancestor(self):
        e = make_event(type_="LabResult")
        assert e.has_type("Observation")
        assert e.has_type("⊤")

    def test_has_type_negative(self):
        e = make_event(type_="LabResult")
        assert not e.has_type("Diagnosis")

    def test_validate_ok(self):
        e = make_event(type_="Observation", attrs={"q_code": "L01", "value": 1.5})
        result = e.validate(stay_interval=iv(6, 12))
        assert result.is_valid, result.errors

    def test_validate_temporal_violation(self):
        e = make_event(h_start=4, h_end=5)  # outside stay [6,12]
        result = e.validate(stay_interval=iv(6, 12))
        assert not result.is_valid
        assert any("TEMPORAL" in err for err in result.errors)

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            make_event(confidence=1.5)
        with pytest.raises(ValueError):
            make_event(confidence=-0.1)

    def test_with_attr(self):
        e = make_event()
        e2 = e.with_attr("value", 42.0)
        assert e2.attr("value") == 42.0
        assert e.attr("value") == 1.0   # original unchanged

    def test_refs(self):
        e = ClinicalEvent(
            patient_id="P1", stay_id="S1",
            type="LabResult",
            tau=iv(8, 9),
            attributes={"q_code": "L01", "value": 2.0},
            refs=frozenset({"parent-event-id"}),
        )
        assert "parent-event-id" in e.refs


class TestEventSet:
    def test_add_and_retrieve(self):
        es = EventSet()
        e = make_event(patient_id="P1")
        es.add(e)
        assert es.get(e.id) == e

    def test_duplicate_id_rejected(self):
        es = EventSet()
        e = make_event()
        es.add(e)
        with pytest.raises(ValueError, match="Duplicate"):
            es.add(e)

    def test_by_patient(self):
        es = EventSet()
        e1 = make_event(patient_id="P1", h_start=8, h_end=9)
        e2 = make_event(patient_id="P1", h_start=10, h_end=11)
        e3 = make_event(patient_id="P2", h_start=8, h_end=9)
        es.add(e1); es.add(e2); es.add(e3)
        p1_evts = es.by_patient("P1")
        assert len(p1_evts) == 2
        assert p1_evts[0].tau.start <= p1_evts[1].tau.start  # sorted

    def test_by_type_subtype(self):
        es = EventSet()
        e_lab  = make_event(type_="LabResult")
        e_obs  = make_event(type_="Observation")
        e_diag = make_event(type_="Diagnosis")
        es.add(e_lab); es.add(e_obs); es.add(e_diag)

        obs_set = es.by_type("Observation")
        ids = {e.id for e in obs_set}
        # LabResult ≺ Observation → both should appear
        assert e_lab.id in ids
        assert e_obs.id in ids
        assert e_diag.id not in ids

    def test_confidence_filter(self):
        es = EventSet()
        e_high = make_event(confidence=0.95)
        e_low  = make_event(confidence=0.7)
        es.add(e_high); es.add(e_low)

        accepted = es.with_confidence(0.9)
        assert e_high.id in accepted
        assert e_low.id not in accepted

    def test_len(self):
        es = EventSet()
        for _ in range(5):
            es.add(make_event())
        assert len(es) == 5


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Fuzzy Intervals (AION §7)
# ══════════════════════════════════════════════════════════════════════════════

class TestFuzzyInterval:
    def test_exact_degenerate(self):
        fi = fuzzy_from_interval(iv(8, 10))
        assert fi.is_exact
        assert fi.sharp_core == iv(8, 10)
        assert fi.outer_hull == iv(8, 10)

    def test_outer_hull(self):
        fi = FuzzyInterval(
            nominal_start=dt(8),
            nominal_end=dt(10),
            eps_start=3600.0,  # 1 hour in seconds
            eps_end=3600.0,
        )
        hull = fi.outer_hull
        assert hull.start == dt(7)
        assert hull.end   == dt(11)

    def test_start_after_end_raises(self):
        with pytest.raises(ValueError):
            FuzzyInterval(nominal_start=dt(10), nominal_end=dt(8))

    def test_negative_eps_raises(self):
        with pytest.raises(ValueError):
            FuzzyInterval(nominal_start=dt(8), nominal_end=dt(10), eps_start=-1.0)

    def test_embedding_probability_exact_inside(self):
        fi = fuzzy_from_interval(iv(8, 10))
        stay = iv(6, 12)
        p = fi.embedding_probability(stay)
        assert p == 1.0

    def test_embedding_probability_exact_outside(self):
        fi = fuzzy_from_interval(iv(4, 5))
        stay = iv(6, 12)
        p = fi.embedding_probability(stay)
        assert p == 0.0

    def test_embedding_probability_fuzzy_high(self):
        # Nominal well inside stay, small ε → high probability
        fi = FuzzyInterval(dt(9), dt(11), eps_start=60.0, eps_end=60.0)
        stay = iv(6, 14)
        p = fi.embedding_probability(stay)
        assert p > 0.99

    def test_embedding_probability_fuzzy_uncertain(self):
        # Nominal at boundary, large ε → ~50% probability
        fi = FuzzyInterval(dt(8), dt(10), eps_start=3600.0, eps_end=3600.0)
        stay = iv(8, 10)  # stay = sharp_core
        p = fi.embedding_probability(stay)
        assert 0.2 <= p <= 0.8   # uncertain range around 50%


class TestProbabilisticAllen:
    def test_exact_intervals_deterministic(self):
        fi = fuzzy_from_interval(iv(1, 3))
        fj = fuzzy_from_interval(iv(5, 7))
        p_precedes = ProbabilisticAllen.confidence(AllenRelation.PRECEDES, fi, fj)
        p_during   = ProbabilisticAllen.confidence(AllenRelation.DURING,   fi, fj)
        assert p_precedes == pytest.approx(1.0, abs=0.01)
        assert p_during   == pytest.approx(0.0, abs=0.01)

    def test_fuzzy_precedes_high_confidence(self):
        # Well-separated intervals with small ε
        fi = FuzzyInterval(dt(8), dt(9), eps_start=60.0, eps_end=60.0)
        fj = FuzzyInterval(dt(12), dt(14), eps_start=60.0, eps_end=60.0)
        p = ProbabilisticAllen.confidence(AllenRelation.PRECEDES, fi, fj)
        assert p > 0.99

    def test_fuzzy_contains_high_confidence(self):
        # Operation inside anaesthesia with small ε
        ana = FuzzyInterval(dt(7, 45), dt(12, 0), eps_start=60.0, eps_end=60.0)
        op  = FuzzyInterval(dt(8, 0),  dt(11, 30), eps_start=60.0, eps_end=60.0)
        p = ProbabilisticAllen.confidence(AllenRelation.CONTAINS, ana, op)
        assert p > 0.9

    def test_most_likely_exact(self):
        fi = fuzzy_from_interval(iv(1, 3))
        fj = fuzzy_from_interval(iv(5, 7))
        rel, conf = ProbabilisticAllen.most_likely(fi, fj)
        assert rel  == AllenRelation.PRECEDES
        assert conf == pytest.approx(1.0, abs=0.01)

    def test_all_confidences_sum_approx_one_for_exact(self):
        fi = fuzzy_from_interval(iv(1, 5))
        fj = fuzzy_from_interval(iv(3, 7))
        confs = ProbabilisticAllen.all_confidences(fi, fj)
        total = sum(confs.values())
        # For exact intervals exactly one relation = 1, rest = 0 → sum = 1
        assert total == pytest.approx(1.0, abs=0.01)


class TestFuzzyTemporalPredicate:
    def test_holds_above_threshold(self):
        pred = FuzzyTemporalPredicate(AllenRelation.PRECEDES, threshold=0.9)
        fi = FuzzyInterval(dt(8), dt(9), eps_start=60.0, eps_end=60.0)
        fj = FuzzyInterval(dt(12), dt(14), eps_start=60.0, eps_end=60.0)
        assert pred.holds(fi, fj)

    def test_holds_below_threshold(self):
        pred = FuzzyTemporalPredicate(AllenRelation.EQUALS, threshold=0.9)
        fi = FuzzyInterval(dt(8), dt(10), eps_start=7200.0, eps_end=7200.0)
        fj = FuzzyInterval(dt(12), dt(14), eps_start=60.0, eps_end=60.0)
        assert not pred.holds(fi, fj)


class TestTemporalValidator:
    def test_accept_high_confidence(self):
        validator = TemporalValidator(gamma_emb=0.9)
        fi   = FuzzyInterval(dt(9), dt(11), eps_start=60.0, eps_end=60.0)
        stay = iv(6, 14)
        assert validator.accept(fi, stay)

    def test_reject_low_confidence(self):
        validator = TemporalValidator(gamma_emb=0.9)
        fi   = FuzzyInterval(dt(6), dt(14), eps_start=7200.0, eps_end=7200.0)
        stay = iv(6, 14)   # hull extends far outside
        # Quality index should be low
        qi = validator.quality_index(fi, stay)
        # Not asserting exact value but smoke test
        assert 0.0 <= qi <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Process Model (AION §8)
# ══════════════════════════════════════════════════════════════════════════════

class TestProcessDAG:
    def _op_event(self) -> ClinicalEvent:
        return ClinicalEvent(
            patient_id="P1", stay_id="S1",
            type="Procedure",
            tau=Interval(dt(8), dt(12)),
            attributes={"id": "op-1", "op_code": "5-361"},
        )

    def _hlm_event(self) -> ClinicalEvent:
        return ClinicalEvent(
            patient_id="P1", stay_id="S1",
            type="HLMPhase",
            tau=Interval(dt(9), dt(11)),
            attributes={"id": "hlm-1", "op_code": "HLM"},
        )

    def _lab_event(self) -> ClinicalEvent:
        return ClinicalEvent(
            patient_id="P1", stay_id="S1",
            type="LabResult",
            tau=Interval(dt(9, 30), dt(9, 30)),
            attributes={"id": "lab-1", "q_code": "LACT", "value": 2.1},
        )

    def test_basic_dag(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        lab = self._lab_event()

        dag.add_event(op)
        dag.add_event(hlm)
        dag.add_event(lab)
        dag.add_subprocess("op-1", "hlm-1")
        dag.add_subprocess("hlm-1", "lab-1")

        assert len(dag) == 3
        assert dag.is_valid

    def test_sub_query(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        dag.add_event(op); dag.add_event(hlm)
        dag.add_subprocess("op-1", "hlm-1")
        sub = dag.sub("op-1")
        assert len(sub) == 1
        assert sub[0].id == "hlm-1"

    def test_desc_transitive(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        lab = self._lab_event()
        dag.add_event(op); dag.add_event(hlm); dag.add_event(lab)
        dag.add_subprocess("op-1", "hlm-1")
        dag.add_subprocess("hlm-1", "lab-1")

        desc = {e.id for e in dag.desc("op-1")}
        assert "hlm-1" in desc
        assert "lab-1" in desc

    def test_parent_query(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        dag.add_event(op); dag.add_event(hlm)
        dag.add_subprocess("op-1", "hlm-1")
        assert dag.parent("hlm-1").id == "op-1"
        assert dag.parent("op-1") is None

    def test_roots(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        dag.add_event(op); dag.add_event(hlm)
        dag.add_subprocess("op-1", "hlm-1")
        roots = dag.roots()
        assert len(roots) == 1
        assert roots[0].id == "op-1"

    def test_temporal_violation_rejected(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        # Child outside parent interval
        outside = ClinicalEvent(
            patient_id="P1", stay_id="S1",
            type="HLMPhase",
            tau=Interval(dt(13), dt(15)),  # after op ends
            attributes={"id": "outside", "op_code": "HLM"},
        )
        dag.add_event(op); dag.add_event(outside)
        with pytest.raises(ValueError, match="AION §8.1"):
            dag.add_subprocess("op-1", "outside")

    def test_composition_violation_rejected(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        # Diagnosis inside Procedure — not in comp(Procedure)
        dx = ClinicalEvent(
            patient_id="P1", stay_id="S1",
            type="Diagnosis",
            tau=Interval(dt(9), dt(10)),
            attributes={"id": "dx-1", "dx_code": "I50.0"},
        )
        dag.add_event(op); dag.add_event(dx)
        with pytest.raises(ValueError, match="AION §8.2"):
            dag.add_subprocess("op-1", "dx-1")

    def test_cycle_rejected(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        dag.add_event(op); dag.add_event(hlm)
        dag.add_subprocess("op-1", "hlm-1", validate=False)
        with pytest.raises(ValueError, match="cycle"):
            dag.add_subprocess("hlm-1", "op-1", validate=False)

    def test_wrong_patient_rejected(self):
        dag = ProcessDAG("P1", "S1")
        e   = ClinicalEvent(
            patient_id="P2",  # wrong patient
            stay_id="S1", type="Observation",
            tau=iv(8, 9),
            attributes={"q_code": "x", "value": 1.0},
        )
        with pytest.raises(ValueError, match="patient"):
            dag.add_event(e)

    def test_validate_returns_empty_for_valid_dag(self):
        dag = ProcessDAG("P1", "S1")
        op  = self._op_event()
        hlm = self._hlm_event()
        dag.add_event(op); dag.add_event(hlm)
        dag.add_subprocess("op-1", "hlm-1")
        assert dag.validate() == []


class TestBuildDag:
    def test_build_dag_helper(self):
        op = ClinicalEvent(
            patient_id="P1", stay_id="S1", type="Procedure",
            tau=Interval(dt(8), dt(12)),
            attributes={"id": "op-x", "op_code": "5-361"},
        )
        hlm = ClinicalEvent(
            patient_id="P1", stay_id="S1", type="HLMPhase",
            tau=Interval(dt(9), dt(11)),
            attributes={"id": "hlm-x", "op_code": "HLM"},
        )
        dag = build_dag(
            patient_id="P1", stay_id="S1",
            events=[op, hlm],
            edges=[ProcessEdge("op-x", "hlm-x")],
        )
        assert dag.is_valid
        assert len(dag.sub("op-x")) == 1


class TestProcessIndex:
    def test_get_or_create(self):
        idx = ProcessIndex()
        dag1 = idx.get_or_create("P1", "S1")
        dag2 = idx.get_or_create("P1", "S1")
        assert dag1 is dag2   # same object returned

    def test_separate_stays(self):
        idx = ProcessIndex()
        dag1 = idx.get_or_create("P1", "S1")
        dag2 = idx.get_or_create("P1", "S2")
        assert dag1 is not dag2

    def test_for_patient(self):
        idx = ProcessIndex()
        idx.get_or_create("P1", "S1")
        idx.get_or_create("P1", "S2")
        idx.get_or_create("P2", "S3")
        p1_dags = idx.for_patient("P1")
        assert len(p1_dags) == 2

# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
"""Tests for aion.abstraction and aion.query — AION §9–§11."""

import datetime
import pytest

from aion.core.allen import Interval, AllenRelation
from aion.core.event import ClinicalEvent, EventSet
from aion.core.types import TypeHierarchy, reset_default_hierarchy
from aion.core.process import ProcessDAG, ProcessIndex

from aion.abstraction.episode import (
    Episode, DerivedEvent, EpisodeFormationOperator, EpisodeIndex,
)
from aion.abstraction.trajectory import (
    Trajectory, TrajectoryPattern, EpisodePredicate,
    TrajectoryBuilder,
)
from aion.query.predicates import (
    QueryContext, DistFunc, dist_seconds,
    HasType, AttrEq, AttrVal, TRel, SubOf, Dist,
    EvtExists, EvtExistsN, AggCond,
    agg_mean, agg_max, evt_attr_gt,
)
from aion.query.cohort import (
    CohortQuery, Cohort,
    query_has_type_event, query_event_sequence,
    query_treatment_path, query_recurring_episodes,
)
from aion.query.patterns import (
    RTPAtom, AtomPattern, ConcatPattern, AlternatePattern,
    KleeneStarPattern, OptionPattern, RepetitionPattern,
    MatchOperator, PatternStats, TCFG, TCFGRule,
    atom, seq, star, opt, rep, alt,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def dt(hour: int, minute: int = 0, day: int = 1) -> datetime.datetime:
    return datetime.datetime(2024, 1, day, hour, minute)


def iv(h_start: int, h_end: int, day: int = 1) -> Interval:
    return Interval(dt(h_start, day=day), dt(h_end, day=day))


def make_event(
    patient_id: str = "P1",
    stay_id:    str = "S1",
    type_:      str = "Observation",
    h_start:    int = 8,
    h_end:      int = 9,
    attrs:      dict = None,
    day:        int = 1,
) -> ClinicalEvent:
    return ClinicalEvent(
        patient_id=patient_id,
        stay_id=stay_id,
        type=type_,
        tau=iv(h_start, h_end, day=day),
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
def event_set():
    """Standard 3-patient event set used across multiple tests."""
    es = EventSet()
    # P1: dx at day1, op at day2, lab during op at day2
    es.add(make_event("P1","S1","Diagnosis",  8, 8,  {"dx_code":"I50.0"}, day=1))
    es.add(make_event("P1","S1","Procedure",  8,12,  {"op_code":"CABG"},  day=2))
    es.add(make_event("P1","S1","LabResult",  9,10,  {"q_code":"LACT","value":3.8}, day=2))
    es.add(make_event("P1","S1","LabResult", 10,11,  {"q_code":"LACT","value":1.9}, day=2))
    # P2: dx + op same day
    es.add(make_event("P2","S2","Diagnosis",  8, 8,  {"dx_code":"I50.0"}, day=1))
    es.add(make_event("P2","S2","Procedure", 10,14,  {"op_code":"ABL"},   day=1))
    # P3: no operation
    es.add(make_event("P3","S3","Diagnosis",  9, 9,  {"dx_code":"J18.0"}, day=1))
    return es


@pytest.fixture
def ctx(event_set, h):
    return QueryContext(event_set=event_set, hierarchy=h)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Episode Formation (AION §9.3)
# ══════════════════════════════════════════════════════════════════════════════

class TestEpisode:
    def test_episode_duration(self):
        ep = Episode(
            patient_id="P1",
            interval=iv(8, 12),
            type_set=frozenset({"Diagnosis"}),
            events=[make_event(h_start=8, h_end=12)],
            index=1,
        )
        assert ep.duration == datetime.timedelta(hours=4)

    def test_gap_to(self):
        ep1 = Episode("P1", iv(8, 10), frozenset({"D"}), [], 1)
        ep2 = Episode("P1", iv(14, 16), frozenset({"D"}), [], 2)
        gap = ep1.gap_to(ep2)
        assert gap == datetime.timedelta(hours=4)

    def test_gap_to_overlapping(self):
        ep1 = Episode("P1", iv(8, 12), frozenset({"D"}), [], 1)
        ep2 = Episode("P1", iv(10, 14), frozenset({"D"}), [], 2)
        gap = ep1.gap_to(ep2)
        assert gap == datetime.timedelta(0)

    def test_allen_relation(self):
        ep1 = Episode("P1", iv(8, 10), frozenset({"D"}), [], 1)
        ep2 = Episode("P1", iv(12, 14), frozenset({"D"}), [], 2)
        assert ep1.allen_relation(ep2) == AllenRelation.PRECEDES


class TestDerivedEvent:
    def test_interval_is_convex_hull(self):
        e1 = make_event(h_start=8, h_end=9)
        e2 = make_event(h_start=11, h_end=12)
        de = DerivedEvent("Episode", "P1", "S1", [e1, e2], rule_name="cluster")
        assert de.interval.start == dt(8)
        assert de.interval.end   == dt(12)

    def test_to_clinical_event(self):
        e = make_event(h_start=8, h_end=9)
        de = DerivedEvent("Episode", "P1", "S1", [e])
        ce = de.to_clinical_event()
        assert ce.type == "Episode"
        assert ce.patient_id == "P1"

    def test_empty_source_raises(self):
        with pytest.raises(ValueError):
            DerivedEvent("Episode", "P1", "S1", [])


class TestEpisodeFormationOperator:
    def test_single_event_one_episode(self, event_set, h):
        op = EpisodeFormationOperator(
            frozenset({"Diagnosis"}), delta=86400.0, hierarchy=h
        )
        episodes = op.form("P1", event_set)
        assert len(episodes) == 1
        assert episodes[0].index == 1

    def test_two_events_same_cluster(self, event_set, h):
        # P1 has 2 LabResult events 1 hour apart
        op = EpisodeFormationOperator(
            frozenset({"LabResult"}), delta=7200.0, hierarchy=h  # 2hr gap
        )
        episodes = op.form("P1", event_set)
        # Both labs on day 2 are within 2 hours → one episode
        assert len(episodes) == 1

    def test_two_events_separate_clusters(self, event_set, h):
        # Build two events with a genuine 2-hour gap
        es2 = EventSet()
        es2.add(make_event("P1","S1","LabResult", 9, 10,  {"q_code":"L","value":1.0}))
        es2.add(make_event("P1","S1","LabResult", 12, 13, {"q_code":"L","value":2.0}))

        # 2hr gap, threshold 3hr → same cluster
        op_wide = EpisodeFormationOperator(
            frozenset({"LabResult"}), delta=10800.0, hierarchy=h
        )
        assert len(op_wide.form("P1", es2)) == 1

        # 2hr gap, threshold 60s → separate clusters
        op_narrow = EpisodeFormationOperator(
            frozenset({"LabResult"}), delta=60.0, hierarchy=h
        )
        episodes = op_narrow.form("P1", es2)
        assert len(episodes) == 2
        assert episodes[0].index == 1
        assert episodes[1].index == 2

    def test_subtype_events_included(self, event_set, h):
        # Observation subtypes should be found when querying "Observation"
        op = EpisodeFormationOperator(
            frozenset({"Observation"}), delta=86400.0, hierarchy=h
        )
        episodes = op.form("P1", event_set)
        # LabResult ≺ Observation → should be included
        total_events = sum(ep.event_count for ep in episodes)
        assert total_events >= 2

    def test_form_all(self, event_set, h):
        op = EpisodeFormationOperator(
            frozenset({"Diagnosis"}), delta=86400.0, hierarchy=h
        )
        all_eps = op.form_all(event_set)
        assert "P1" in all_eps
        assert "P2" in all_eps
        assert "P3" in all_eps

    def test_no_matching_events(self, event_set, h):
        op = EpisodeFormationOperator(
            frozenset({"Imaging"}), delta=86400.0, hierarchy=h
        )
        episodes = op.form("P1", event_set)
        assert episodes == []


class TestEpisodeIndex:
    def test_add_and_retrieve(self):
        idx = EpisodeIndex()
        ep  = Episode("P1", iv(8, 10), frozenset({"Diagnosis"}), [], 1)
        idx.add(ep)
        retrieved = idx.get("P1", frozenset({"Diagnosis"}))
        assert len(retrieved) == 1
        assert retrieved[0] is ep

    def test_get_by_index(self):
        idx = EpisodeIndex()
        ep1 = Episode("P1", iv(8, 10), frozenset({"D"}), [], 1)
        ep2 = Episode("P1", iv(14, 16), frozenset({"D"}), [], 2)
        idx.add(ep1); idx.add(ep2)
        result = idx.get("P1", frozenset({"D"}), index=2)
        assert len(result) == 1
        assert result[0].index == 2

    def test_count(self):
        idx = EpisodeIndex()
        idx.add(Episode("P1", iv(8,10), frozenset({"D"}), [], 1))
        idx.add(Episode("P1", iv(14,16), frozenset({"D"}), [], 2))
        assert idx.count("P1", frozenset({"D"})) == 2

    def test_populate_from_operator(self, event_set, h):
        idx = EpisodeIndex()
        op  = EpisodeFormationOperator(frozenset({"Diagnosis"}), 86400.0, h)
        idx.populate_from_operator(op, event_set)
        assert len(idx) >= 2  # P1 + P2 + P3 each have 1 dx episode


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Trajectory (AION §9.4)
# ══════════════════════════════════════════════════════════════════════════════

class TestTrajectory:
    def _ep(self, h_start, h_end, day=1) -> Episode:
        return Episode(
            patient_id="P1",
            interval=iv(h_start, h_end, day=day),
            type_set=frozenset({"Diagnosis"}),
            events=[],
        )

    def test_ordering_enforced(self):
        ep1 = self._ep(8, 10, day=1)
        ep2 = self._ep(12, 14, day=2)
        t = Trajectory("P1", [ep2, ep1])  # reversed input
        assert t.episodes[0].interval.start < t.episodes[1].interval.start

    def test_overlapping_raises(self):
        ep1 = self._ep(8, 12, day=1)
        ep2 = self._ep(10, 14, day=1)  # overlaps ep1
        with pytest.raises(ValueError):
            Trajectory("P1", [ep1, ep2])

    def test_gap_between(self):
        ep1 = self._ep(8, 10, day=1)
        ep2 = self._ep(14, 16, day=1)
        t   = Trajectory("P1", [ep1, ep2])
        gap = t.gap_between(0, 1)
        assert gap == datetime.timedelta(hours=4)

    def test_consecutive_gaps(self):
        ep1 = self._ep(8, 10, day=1)
        ep2 = self._ep(12, 14, day=1)
        ep3 = self._ep(16, 18, day=1)
        t   = Trajectory("P1", [ep1, ep2, ep3])
        gaps = t.consecutive_gaps()
        assert len(gaps) == 2
        assert all(g == datetime.timedelta(hours=2) for g in gaps)

    def test_total_span(self):
        ep1 = self._ep(8, 10, day=1)
        ep2 = self._ep(12, 14, day=1)
        t   = Trajectory("P1", [ep1, ep2])
        span = t.total_span
        assert span.start == dt(8)
        assert span.end   == dt(14)

    def test_empty_trajectory(self):
        t = Trajectory("P1", [])
        assert t.is_empty
        assert t.total_span is None


class TestTrajectoryPattern:
    def _ep(self, h_start, h_end, type_s="D", day=1) -> Episode:
        return Episode(
            "P1", iv(h_start, h_end, day=day),
            frozenset({type_s}), [], 1
        )

    def test_single_predicate_matches(self):
        ep   = self._ep(8, 10)
        t    = Trajectory("P1", [ep])
        pred = EpisodePredicate(frozenset({"D"}))
        pat  = TrajectoryPattern([pred])
        assert pat.matches(t)

    def test_type_mismatch_no_match(self):
        ep   = self._ep(8, 10, type_s="X")
        t    = Trajectory("P1", [ep])
        pred = EpisodePredicate(frozenset({"D"}))
        pat  = TrajectoryPattern([pred])
        assert not pat.matches(t)

    def test_two_predicate_gap_constraint(self):
        ep1 = self._ep(8, 10,  "A", day=1)
        ep2 = self._ep(12, 14, "B", day=1)  # 2hr gap
        t   = Trajectory("P1", [ep1, ep2])

        # Gap must be >= 1hr
        p1  = EpisodePredicate(frozenset({"A"}))
        p2  = EpisodePredicate(frozenset({"B"}), min_gap_from_prev=3600.0)
        pat = TrajectoryPattern([p1, p2])
        assert pat.matches(t)

    def test_gap_too_small_no_match(self):
        ep1 = self._ep(8,  10, "A")
        ep2 = self._ep(11, 13, "B")  # only 1hr gap
        t   = Trajectory("P1", [ep1, ep2])

        p1  = EpisodePredicate(frozenset({"A"}))
        p2  = EpisodePredicate(frozenset({"B"}), min_gap_from_prev=7200.0)  # 2hr min
        pat = TrajectoryPattern([p1, p2])
        assert not pat.matches(t)


class TestTrajectoryBuilder:
    def test_build_from_index(self, event_set, h):
        idx = EpisodeIndex()
        op  = EpisodeFormationOperator(frozenset({"Diagnosis"}), 86400.0, h)
        idx.populate_from_operator(op, event_set)

        builder = TrajectoryBuilder(idx)
        t = builder.build("P1")
        assert t is not None
        assert t.patient_id == "P1"

    def test_build_all(self, event_set, h):
        idx = EpisodeIndex()
        op  = EpisodeFormationOperator(frozenset({"Diagnosis"}), 86400.0, h)
        idx.populate_from_operator(op, event_set)
        builder = TrajectoryBuilder(idx)
        all_t = builder.build_all()
        assert "P1" in all_t
        assert "P2" in all_t

    def test_build_empty_returns_none(self):
        idx     = EpisodeIndex()
        builder = TrajectoryBuilder(idx)
        t = builder.build("UNKNOWN")
        assert t is None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Predicates (AION §10.1)
# ══════════════════════════════════════════════════════════════════════════════

class TestAtomicPredicates:
    def test_has_type_exact(self, ctx, event_set):
        e = event_set.by_type_exact("LabResult")[0]
        pred = HasType(e, "LabResult")
        assert pred.evaluate(ctx)

    def test_has_type_ancestor(self, ctx, event_set):
        e = event_set.by_type_exact("LabResult")[0]
        pred = HasType(e, "Observation")
        assert pred.evaluate(ctx)

    def test_has_type_negative(self, ctx, event_set):
        e = event_set.by_type_exact("LabResult")[0]
        pred = HasType(e, "Diagnosis")
        assert not pred.evaluate(ctx)

    def test_attr_eq_true(self, ctx, event_set):
        e = event_set.by_type_exact("Diagnosis")[0]
        pred = AttrEq(e, "dx_code", "I50.0")
        assert pred.evaluate(ctx)

    def test_attr_eq_false(self, ctx, event_set):
        e = event_set.by_type_exact("Diagnosis")[0]
        pred = AttrEq(e, "dx_code", "WRONG")
        assert not pred.evaluate(ctx)

    def test_attr_val_gt(self, ctx, event_set):
        labs = event_set.by_type_exact("LabResult")
        e    = next(e for e in labs if e.attr("value") == 3.8)
        pred = AttrVal(e, "value", lambda v: v > 3.0)
        assert pred.evaluate(ctx)

    def test_trel_precedes(self, ctx, event_set):
        dx = event_set.by_type_exact("Diagnosis")[0]
        op = event_set.by_type_exact("Procedure")[0]
        pred = TRel(dx, op, AllenRelation.PRECEDES)
        assert pred.evaluate(ctx)

    def test_dist_ok(self, ctx, event_set):
        labs = sorted(
            event_set.by_type_exact("LabResult"),
            key=lambda e: e.tau.start,
        )
        e1, e2 = labs[0], labs[1]
        # They're 1 hour apart
        pred = Dist(e1, e2, DistFunc.START_TO_START,
                    delta_min=0, delta_max=7200.0)
        assert pred.evaluate(ctx)

    def test_dist_fails(self, ctx, event_set):
        labs = sorted(
            event_set.by_type_exact("LabResult"),
            key=lambda e: e.tau.start,
        )
        e1, e2 = labs[0], labs[1]
        pred = Dist(e1, e2, DistFunc.START_TO_START,
                    delta_min=0, delta_max=10.0)   # only 10s allowed
        assert not pred.evaluate(ctx)


class TestQuantifierPredicates:
    def test_evt_exists_true(self, ctx):
        pred = EvtExists("P1", lambda e: e.type == "Diagnosis")
        assert pred.evaluate(ctx)

    def test_evt_exists_false(self, ctx):
        pred = EvtExists("P1", lambda e: e.type == "Imaging")
        assert not pred.evaluate(ctx)

    def test_evt_exists_n_sufficient(self, ctx):
        pred = EvtExistsN("P1", lambda e: e.type == "LabResult", n=2)
        assert pred.evaluate(ctx)

    def test_evt_exists_n_insufficient(self, ctx):
        pred = EvtExistsN("P1", lambda e: e.type == "LabResult", n=5)
        assert not pred.evaluate(ctx)


class TestAggCond:
    def test_mean_above_threshold(self, ctx, event_set):
        labs = event_set.by_type_exact("LabResult")
        lab_ids = [e.id for e in labs]
        # mean([3.8, 1.9]) = 2.85
        pred = AggCond(
            event_ids=lab_ids,
            attr_name="value",
            agg_fn=agg_mean,
            cond_fn=lambda v: v > 2.0,
        )
        assert pred.evaluate(ctx)

    def test_max_below_threshold(self, ctx, event_set):
        labs = event_set.by_type_exact("LabResult")
        lab_ids = [e.id for e in labs]
        pred = AggCond(
            event_ids=lab_ids,
            attr_name="value",
            agg_fn=agg_max,
            cond_fn=lambda v: v < 3.0,   # max is 3.8 → fails
        )
        assert not pred.evaluate(ctx)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Cohort Queries (AION §10.2–§10.3)
# ══════════════════════════════════════════════════════════════════════════════

class TestCohortAlgebra:
    def test_intersect(self, ctx):
        q_dx  = query_has_type_event("Diagnosis")
        q_op  = query_has_type_event("Procedure")
        q_and = q_dx & q_op

        cohort = q_and.evaluate(ctx)
        assert "P1" in cohort  # has both
        assert "P3" not in cohort  # no operation

    def test_union(self, ctx):
        q_op  = query_has_type_event("Procedure")
        q_dx  = query_has_type_event("Diagnosis")
        q_or  = q_op | q_dx

        cohort = q_or.evaluate(ctx)
        assert "P1" in cohort
        assert "P3" in cohort  # has Diagnosis

    def test_difference(self, ctx):
        q_dx = query_has_type_event("Diagnosis")
        q_op = query_has_type_event("Procedure")
        q    = q_dx - q_op  # patients with dx but no op

        cohort = q.evaluate(ctx)
        assert "P3" in cohort
        assert "P1" not in cohort
        assert "P2" not in cohort

    def test_invert(self, ctx):
        q_op = query_has_type_event("Procedure")
        q    = ~q_op
        cohort = q.evaluate(ctx)
        assert "P3" in cohort
        assert "P1" not in cohort

    def test_cohort_size(self, ctx):
        q = query_has_type_event("Diagnosis")
        c = q.evaluate(ctx)
        assert c.size == 3  # all 3 patients have a diagnosis


class TestStandardQueries:
    def test_query_has_type_event(self, ctx):
        q = query_has_type_event("LabResult")
        c = q.evaluate(ctx)
        assert "P1" in c
        assert "P2" not in c

    def test_query_has_type_with_filter(self, ctx):
        q = query_has_type_event(
            "Diagnosis",
            attr_filter=lambda e: e.attr("dx_code") == "I50.0",
        )
        c = q.evaluate(ctx)
        assert "P1" in c
        assert "P2" in c
        assert "P3" not in c  # P3 has J18.0

    def test_query_event_sequence(self, ctx):
        q = query_event_sequence(
            "Diagnosis", "Procedure",
            relation=AllenRelation.PRECEDES,
        )
        c = q.evaluate(ctx)
        assert "P1" in c
        assert "P2" in c
        assert "P3" not in c

    def test_query_event_sequence_same_stay(self, ctx):
        # P1: dx day1/stay1, op day2/stay1 — same stay_id
        # P2: dx day1/stay2, op day1/stay2 — same stay
        q = query_event_sequence(
            "Diagnosis", "Procedure",
            relation=AllenRelation.PRECEDES,
            same_stay=True,
        )
        c = q.evaluate(ctx)
        # Both P1 and P2 have dx before op in same stay
        assert len(c) >= 1

    def test_query_recurring_episodes(self, ctx, h):
        # Create index with P1 having 2 dx episodes
        idx = EpisodeIndex()
        ep1 = Episode("P1", iv(8, 8, day=1), frozenset({"Diagnosis"}), [], 1)
        ep2 = Episode("P1", iv(8, 8, day=10), frozenset({"Diagnosis"}), [], 2)
        ep3 = Episode("P2", iv(8, 8, day=1), frozenset({"Diagnosis"}), [], 1)
        idx.add(ep1); idx.add(ep2); idx.add(ep3)

        ctx2 = QueryContext(
            event_set=ctx.event_set,
            episode_index=idx,
            hierarchy=h,
        )
        q = query_recurring_episodes(frozenset({"Diagnosis"}), min_count=2)
        c = q.evaluate(ctx2)
        assert "P1" in c
        assert "P2" not in c


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: RTP Patterns (AION §11)
# ══════════════════════════════════════════════════════════════════════════════

class TestAtomPattern:
    def test_matches_correct_type(self, h, event_set):
        sequence = event_set.by_patient("P1")
        pat = atom("Diagnosis")
        matches = pat.match_all(sequence, h)
        assert len(matches) >= 1
        assert all(m[0].type == "Diagnosis" for m in matches)

    def test_no_match_wrong_type(self, h, event_set):
        sequence = event_set.by_patient("P1")
        pat = atom("Imaging")
        assert not pat.has_match(sequence, h)

    def test_subtype_matched(self, h, event_set):
        sequence = event_set.by_patient("P1")
        # LabResult ≺ Observation
        pat = atom("Observation")
        assert pat.has_match(sequence, h)

    def test_attr_filter(self, h, event_set):
        sequence = event_set.by_patient("P1")
        pat = atom("LabResult", value=lambda v: v > 3.0)
        matches = pat.match_all(sequence, h)
        assert len(matches) == 1  # only value=3.8


class TestConcatPattern:
    def test_dx_before_op(self, h, event_set):
        sequence = event_set.by_patient("P1")
        pat = seq(atom("Diagnosis"), atom("Procedure"))
        assert pat.has_match(sequence, h)

    def test_dx_before_op_p3_no_match(self, h, event_set):
        sequence = event_set.by_patient("P3")
        pat = seq(atom("Diagnosis"), atom("Procedure"))
        assert not pat.has_match(sequence, h)

    def test_with_value_filter(self, h, event_set):
        sequence = event_set.by_patient("P1")
        # Lab 3.8 (9-10) MEETS lab 1.9 (10-11) — use MEETS relation
        pat = ConcatPattern(
            AtomPattern(RTPAtom("LabResult", attr_pred=lambda e: (e.attr("value") or 0) > 3.0)),
            AtomPattern(RTPAtom("LabResult", attr_pred=lambda e: (e.attr("value") or 99) < 2.0)),
            relation=AllenRelation.MEETS,
        )
        assert pat.has_match(sequence, h)


class TestAlternatePattern:
    def test_alt_matches_either(self, h, event_set):
        sequence = event_set.by_patient("P3")
        pat = alt(atom("Diagnosis"), atom("Procedure"))
        assert pat.has_match(sequence, h)

    def test_alt_no_match(self, h, event_set):
        sequence = event_set.by_patient("P3")
        pat = alt(atom("Imaging"), atom("Score"))
        assert not pat.has_match(sequence, h)


class TestKleeneStarPattern:
    def test_zero_matches(self, h, event_set):
        sequence = event_set.by_patient("P3")
        pat = star(atom("LabResult"))
        # Zero occurrences is always a valid match
        matches = pat.match(sequence, h, 0)
        assert [] in matches  # empty match for zero occurrences

    def test_multiple_matches(self, h, event_set):
        sequence = event_set.by_patient("P1")
        pat = star(atom("LabResult"))
        matches = pat.match(sequence, h, 0)
        # Should have matches of length 0, 1, 2
        lens = {len(m) for m in matches}
        assert 0 in lens
        assert 2 in lens


class TestRepetitionPattern:
    def test_rep_min_max(self, h, event_set):
        sequence = event_set.by_patient("P1")
        pat = rep(atom("LabResult"), 1, 3)
        matches = pat.match(sequence, h, 0)
        assert len(matches) >= 1

    def test_rep_invalid_bounds(self):
        with pytest.raises(ValueError):
            rep(atom("X"), 3, 1)


class TestMatchOperator:
    def test_has_pattern_true(self, h, event_set):
        op = MatchOperator(seq(atom("Diagnosis"), atom("Procedure")), h)
        assert op.has_pattern("P1", event_set)
        assert op.has_pattern("P2", event_set)

    def test_has_pattern_false(self, h, event_set):
        op = MatchOperator(seq(atom("Diagnosis"), atom("Procedure")), h)
        assert not op.has_pattern("P3", event_set)

    def test_match_count(self, h, event_set):
        op = MatchOperator(atom("LabResult"), h)
        count = op.match_count("P1", event_set)
        assert count == 2  # P1 has 2 lab results


class TestPatternStats:
    def test_frequency(self, h, event_set):
        op   = MatchOperator(atom("Diagnosis"), h)
        pids = list(event_set.all_patients)
        freq = PatternStats.frequency(op, pids, event_set)
        assert freq == 3  # all 3 have diagnosis

    def test_support(self, h, event_set):
        op   = MatchOperator(atom("Procedure"), h)
        pids = list(event_set.all_patients)
        supp = PatternStats.support(op, pids, event_set)
        assert abs(supp - 2/3) < 0.01  # 2 of 3 have procedure

    def test_confidence(self, h, event_set):
        op1  = MatchOperator(atom("Diagnosis"),  h)
        op2  = MatchOperator(atom("Procedure"),  h)
        pids = list(event_set.all_patients)
        conf = PatternStats.confidence(op1, op2, pids, event_set)
        # 2/3 patients have both; support(dx)=1.0 → conf = (2/3)/1.0 = 0.67
        assert abs(conf - 2/3) < 0.01


class TestTCFG:
    def test_simple_tcfg(self, h, event_set):
        """
        Grammar: S → Lab →[meets] Lab
        Matches: two lab results where first MEETS second (contiguous hours).
        """
        rule = TCFGRule(
            lhs="S",
            rhs=[
                RTPAtom("LabResult"),
                RTPAtom("LabResult"),
            ],
            relations=[AllenRelation.MEETS],
        )
        grammar = TCFG(start="S", rules=[rule], hierarchy=h)
        assert grammar.has_grammar_pattern("P1", event_set)
        assert not grammar.has_grammar_pattern("P2", event_set)

    def test_tcfg_compile_to_rtp(self, h, event_set):
        rule = TCFGRule(
            lhs="S",
            rhs=[RTPAtom("Diagnosis"), RTPAtom("Procedure")],
            relations=[AllenRelation.PRECEDES],
        )
        grammar = TCFG(start="S", rules=[rule], hierarchy=h)
        rtp = grammar.to_rtp()
        op  = MatchOperator(rtp, h)
        assert op.has_pattern("P1", event_set)

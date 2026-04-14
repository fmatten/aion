# SPDX-License-Identifier: EUPL-1.2
# Copyright © Friedhelm Matten, ISCaD GmbH, 30900 Wedemark
"""Tests for aion.ai and aion.explain — AION §19–§21."""

import datetime
import math
import pytest

from aion.core.allen import Interval
from aion.core.event import ClinicalEvent, EventSet
from aion.core.types import TypeHierarchy, reset_default_hierarchy

from aion.ai.component import (
    AIOutput, ValidationOperator, ValidationDecision,
    EventExtractionComponent, ExtractedEvent,
    PatientFeatureVector, FeatureExtractor,
    RiskEstimationComponent, AIEventIntegrator,
)
from aion.explain.shapley import (
    ExplanationResult, ShapleyExplainer,
    CounterfactualExplainer, CounterfactualExplanation,
    SufficientExplainer, SufficientExplanation,
    ExtendedValidationOperator, FullExplanationReport,
)


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
    es = EventSet(hierarchy=h)
    es.add(make_event("P1","S1","Diagnosis",  8, 8,  {"dx_code":"I50"}))
    es.add(make_event("P1","S1","Procedure",  9,12,  {"op_code":"CABG"}))
    es.add(make_event("P1","S1","LabResult", 10,10,  {"q_code":"L","value":4.5}))
    es.add(make_event("P1","S1","LabResult", 11,11,  {"q_code":"L","value":1.8}))
    es.add(make_event("P2","S2","Diagnosis",  8, 8,  {"dx_code":"I50"}))
    es.add(make_event("P2","S2","Procedure",  9,11,  {"op_code":"ABL"}))
    es.add(make_event("P3","S3","Diagnosis",  8, 8,  {"dx_code":"I50"}))
    return es


@pytest.fixture
def extractor(h):
    return FeatureExtractor(
        type_names=["Diagnosis","Procedure","LabResult"],
        attr_aggs=[
            ("LabResult","value","mean"),
            ("LabResult","value","max"),
        ],
        hierarchy=h,
    )


@pytest.fixture
def risk_component(extractor):
    """Simple linear risk model: risk = mean_lab * 0.1 + has_procedure * 0.3."""
    feature_names = extractor.feature_names
    def model(fv: list[float]) -> float:
        names = feature_names
        d     = dict(zip(names, fv))
        risk  = (
            d.get("mean_LabResult_value", 0.0) * 0.08 +
            d.get("has_Procedure",        0.0) * 0.25 +
            d.get("max_LabResult_value",  0.0) * 0.05
        )
        return min(1.0, max(0.0, risk))

    return RiskEstimationComponent(
        model_fn=model,
        feature_names=feature_names,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: AIOutput and ValidationOperator (AION §19.1–§19.2)
# ══════════════════════════════════════════════════════════════════════════════

class TestAIOutput:
    def test_creation(self):
        out = AIOutput(value=42.0, confidence=0.9, component="Test")
        assert out.value      == 42.0
        assert out.confidence == pytest.approx(0.9)

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError):
            AIOutput(value=1.0, confidence=1.5)

    def test_confidence_zero(self):
        out = AIOutput(value="hello", confidence=0.0)
        assert out.confidence == 0.0


class TestValidationOperator:
    def test_accepts_above_threshold(self):
        vo  = ValidationOperator(layer=2, c_min=0.8)
        out = AIOutput(value="test", confidence=0.9)
        dec = vo.validate(out)
        assert dec.accepted

    def test_rejects_below_threshold(self):
        vo  = ValidationOperator(layer=2, c_min=0.9)
        out = AIOutput(value="test", confidence=0.7)
        dec = vo.validate(out)
        assert not dec.accepted
        assert "confidence" in dec.reason

    def test_custom_check_passes(self):
        vo = ValidationOperator(
            layer=5,
            custom_checks=[lambda v: [] if v > 0 else ["negative value"]],
        )
        dec = vo.validate(AIOutput(value=1.0, confidence=1.0))
        assert dec.accepted

    def test_custom_check_fails(self):
        vo = ValidationOperator(
            layer=5,
            custom_checks=[lambda v: ["negative"] if v < 0 else []],
        )
        dec = vo.validate(AIOutput(value=-1.0, confidence=1.0))
        assert not dec.accepted
        assert "negative" in dec.errors[0]

    def test_bool_conversion(self):
        assert ValidationDecision(accepted=True)
        assert not ValidationDecision(accepted=False)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Event Extraction (AION §19.4)
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractedEvent:
    def test_to_clinical_event_ok(self, h):
        ee = ExtractedEvent(
            patient_id="P1", stay_id="S1",
            type_name="Diagnosis",
            t_begin=dt(8), t_end=dt(8),
            attributes={"dx_code": "I50"},
        )
        ce = ee.to_clinical_event(h, confidence=0.95)
        assert ce is not None
        assert ce.type == "Diagnosis"
        assert ce.confidence == pytest.approx(0.95)

    def test_to_clinical_event_no_time(self, h):
        ee = ExtractedEvent(
            patient_id="P1", stay_id="S1",
            type_name="Diagnosis",
            t_begin=None, t_end=None,
            attributes={},
        )
        ce = ee.to_clinical_event(h)
        assert ce is None


class TestEventExtractionComponent:
    def test_default_predict(self, h):
        comp = EventExtractionComponent(h, c_min=0.5)
        out  = comp.predict("Patient admitted with heart failure")
        assert isinstance(out, AIOutput)
        assert isinstance(out.value, ExtractedEvent)

    def test_validation_rejects_unknown_type(self, h):
        comp = EventExtractionComponent(h, c_min=0.0)
        # Manually create output with unknown type
        ee  = ExtractedEvent("P1","S1","UnknownType123", dt(8), dt(8), {})
        out = AIOutput(value=ee, confidence=1.0)
        dec = comp.validate(out)
        assert not dec.accepted

    def test_validation_rejects_no_time(self, h):
        comp = EventExtractionComponent(h, c_min=0.0)
        ee   = ExtractedEvent("P1","S1","Diagnosis", None, None, {})
        out  = AIOutput(value=ee, confidence=1.0)
        dec  = comp.validate(out)
        assert not dec.accepted
        assert any("TEMPORAL_LOSS" in e for e in dec.errors)

    def test_validation_accepts_valid(self, h):
        comp = EventExtractionComponent(h, c_min=0.5)
        ee   = ExtractedEvent("P1","S1","Diagnosis", dt(8), dt(8), {"dx_code":"I50"})
        out  = AIOutput(value=ee, confidence=0.9)
        dec  = comp.validate(out)
        assert dec.accepted


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Feature Extraction (AION §19.7)
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureExtractor:
    def test_extract_counts(self, event_set, extractor):
        fv = extractor.extract("P1", event_set)
        assert fv.features["count_Diagnosis"] == pytest.approx(1.0)
        assert fv.features["count_Procedure"] == pytest.approx(1.0)
        assert fv.features["count_LabResult"] == pytest.approx(2.0)

    def test_extract_has_indicator(self, event_set, extractor):
        fv = extractor.extract("P1", event_set)
        assert fv.features["has_Diagnosis"] == pytest.approx(1.0)
        fv3 = extractor.extract("P3", event_set)
        assert fv3.features["has_Procedure"] == pytest.approx(0.0)

    def test_extract_aggregates(self, event_set, extractor):
        fv = extractor.extract("P1", event_set)
        # Mean of [4.5, 1.8] = 3.15
        assert fv.features.get("mean_LabResult_value", 0.0) == pytest.approx(3.15)
        assert fv.features.get("max_LabResult_value",  0.0) == pytest.approx(4.5)

    def test_to_list_order(self, event_set, extractor):
        fv     = extractor.extract("P1", event_set)
        names  = extractor.feature_names
        values = fv.to_list(names)
        assert len(values) == len(names)
        assert all(isinstance(v, float) for v in values)

    def test_extract_all(self, event_set, extractor):
        all_fv = extractor.extract_all(event_set)
        assert "P1" in all_fv
        assert "P2" in all_fv
        assert "P3" in all_fv

    def test_no_events_for_type(self, event_set, extractor):
        fv = extractor.extract("P3", event_set)
        assert fv.features["count_LabResult"] == pytest.approx(0.0)
        assert fv.features.get("mean_LabResult_value", 0.0) == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Risk Estimation Component (AION §19.7)
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskEstimationComponent:
    def test_predict_returns_output(self, event_set, extractor, risk_component):
        fv  = extractor.extract("P1", event_set)
        out = risk_component.predict(fv)
        assert isinstance(out, AIOutput)
        assert 0.0 <= out.value <= 1.0

    def test_higher_lab_higher_risk(self, event_set, h, extractor, risk_component):
        """P1 has high lab values → higher risk than P3 (no labs)."""
        fv1  = extractor.extract("P1", event_set)
        fv3  = extractor.extract("P3", event_set)
        risk1 = risk_component.predict(fv1).value
        risk3 = risk_component.predict(fv3).value
        assert risk1 > risk3

    def test_estimate_cohort(self, event_set, extractor, risk_component):
        all_fv = extractor.extract_all(event_set)
        risks  = risk_component.estimate_cohort(all_fv)
        assert set(risks.keys()) == {"P1", "P2", "P3"}
        assert all(0.0 <= r <= 1.0 for r in risks.values())

    def test_validation_clamps(self, extractor, h):
        """Model returning >1 or <0 should be clamped."""
        def bad_model(fv): return 2.5
        comp = RiskEstimationComponent(
            model_fn=bad_model,
            feature_names=extractor.feature_names,
        )
        fv  = PatientFeatureVector("P1", {"x": 1.0})
        out = comp.predict(fv)
        assert out.value <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: AIEventIntegrator (AION §19.3)
# ══════════════════════════════════════════════════════════════════════════════

class TestAIEventIntegrator:
    def test_accept_above_threshold(self, h):
        es  = EventSet(hierarchy=h)
        ig  = AIEventIntegrator(es, c_min=0.9, hierarchy=h)
        e   = make_event(h_start=8, h_end=9)
        dec = ig.submit(e, confidence=0.95)
        assert dec.accepted
        assert ig.n_accepted == 1
        assert e.id in es

    def test_reject_below_threshold(self, h):
        es  = EventSet(hierarchy=h)
        ig  = AIEventIntegrator(es, c_min=0.9, hierarchy=h)
        e   = make_event(h_start=8, h_end=9)
        dec = ig.submit(e, confidence=0.7)
        assert not dec.accepted
        assert ig.n_rejected == 1
        assert e.id not in es

    def test_acceptance_rate(self, h):
        es = EventSet(hierarchy=h)
        ig = AIEventIntegrator(es, c_min=0.5, hierarchy=h)
        ig.submit(make_event(h_start=8,  h_end=9),  confidence=0.9)
        ig.submit(make_event(h_start=10, h_end=11), confidence=0.3)
        assert ig.acceptance_rate == pytest.approx(0.5)

    def test_temporal_validation_rejects(self, h):
        es       = EventSet(hierarchy=h)
        ig       = AIEventIntegrator(es, c_min=0.0, hierarchy=h)
        e        = make_event(h_start=4, h_end=5)  # outside stay
        stay     = iv(6, 12)
        dec      = ig.submit(e, confidence=1.0, stay_interval=stay)
        # Should be rejected due to temporal embedding violation
        assert not dec.accepted

    def test_confidence_stamped_on_event(self, h):
        es  = EventSet(hierarchy=h)
        ig  = AIEventIntegrator(es, c_min=0.5, hierarchy=h)
        e   = make_event()
        ig.submit(e, confidence=0.85)
        stored = es.get(e.id)
        assert stored is not None
        assert stored.confidence == pytest.approx(0.85)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Shapley Explainer (AION §21.2)
# ══════════════════════════════════════════════════════════════════════════════

class TestShapleyExplainer:
    def test_explain_returns_result(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = ShapleyExplainer(risk_component, extractor.feature_names, phi_min=0.0)
        res = exp.explain("P1", fv, event_set, h)
        assert isinstance(res, ExplanationResult)
        assert res.patient_id == "P1"
        assert res.method == "shapley"

    def test_risk_nonzero(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = ShapleyExplainer(risk_component, extractor.feature_names)
        res = exp.explain("P1", fv, event_set, h)
        assert res.output_value > 0.0

    def test_phi_min_filters(self, event_set, extractor, risk_component, h):
        fv       = extractor.extract("P1", event_set)
        exp_low  = ShapleyExplainer(risk_component, extractor.feature_names, phi_min=0.0)
        exp_high = ShapleyExplainer(risk_component, extractor.feature_names, phi_min=999.0)
        res_low  = exp_low.explain("P1", fv, event_set, h)
        res_high = exp_high.explain("P1", fv, event_set, h)
        # Low threshold: more events; high threshold: fewer (or none)
        assert res_low.size >= res_high.size

    def test_shapley_values_sum_to_risk(self, extractor, risk_component):
        """Shapley efficiency: Σ_j φ_j ≈ f(x) - f(∅)."""
        feature_names = extractor.feature_names
        exp = ShapleyExplainer(risk_component, feature_names)
        fv  = [1.0, 1.0, 1.0, 0.0, 0.0, 4.5, 3.15] + [0.0] * (len(feature_names) - 7)
        fv  = fv[:len(feature_names)]
        phis = exp._shapley_values(fv)
        risk = exp._f(fv)
        null = exp._f([0.0] * len(fv))
        # Sum of Shapley values ≈ f(x) - f(∅)  (efficiency axiom)
        phi_sum = sum(phis)
        assert abs(phi_sum - (risk - null)) < 0.1   # generous tolerance

    def test_fidelity_in_range(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = ShapleyExplainer(risk_component, extractor.feature_names, phi_min=0.0)
        res = exp.explain("P1", fv, event_set, h)
        assert 0.0 <= res.fidelity <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Counterfactual Explainer (AION §21.3)
# ══════════════════════════════════════════════════════════════════════════════

class TestCounterfactualExplainer:
    def test_explain_returns_result(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = CounterfactualExplainer(
            risk_component, extractor.feature_names, extractor, h
        )
        res = exp.explain("P1", fv, event_set, target_risk=0.1)
        assert isinstance(res, CounterfactualExplanation)
        assert res.patient_id == "P1"

    def test_cf_risk_lower_than_original(self, event_set, extractor, risk_component, h):
        """Removing ALL events should drive risk toward zero (no features)."""
        fv = extractor.extract("P1", event_set)
        original_risk = risk_component.predict(fv).value
        exp = CounterfactualExplainer(
            risk_component, extractor.feature_names, extractor, h
        )
        # target=0 forces removal of all events
        res = exp.explain("P1", fv, event_set, target_risk=0.0)
        # With all events removed, feature vector is zero → risk = 0
        assert res.cf_value == pytest.approx(0.0, abs=0.05)
        assert res.delta_size > 0

    def test_original_value_correct(self, event_set, extractor, risk_component, h):
        fv = extractor.extract("P1", event_set)
        original_risk = risk_component.predict(fv).value
        exp = CounterfactualExplainer(
            risk_component, extractor.feature_names, extractor, h
        )
        res = exp.explain("P1", fv, event_set)
        assert res.original_value == pytest.approx(original_risk, abs=0.01)

    def test_action_is_remove(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = CounterfactualExplainer(
            risk_component, extractor.feature_names, extractor, h
        )
        res = exp.explain("P1", fv, event_set)
        assert res.action == "remove"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: Sufficient Explainer (AION §21.4)
# ══════════════════════════════════════════════════════════════════════════════

class TestSufficientExplainer:
    def test_explain_returns_result(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = SufficientExplainer(
            risk_component, extractor.feature_names, extractor,
            epsilon_s=0.5, hierarchy=h
        )
        res = exp.explain("P1", fv, event_set)
        assert isinstance(res, SufficientExplanation)
        assert res.patient_id == "P1"

    def test_sufficient_subset_smaller_or_equal(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        n_total = len(event_set.by_patient("P1"))
        exp = SufficientExplainer(
            risk_component, extractor.feature_names, extractor,
            epsilon_s=0.3, hierarchy=h
        )
        res = exp.explain("P1", fv, event_set)
        assert res.size <= n_total

    def test_faithful_with_high_epsilon(self, event_set, extractor, risk_component, h):
        fv  = extractor.extract("P1", event_set)
        exp = SufficientExplainer(
            risk_component, extractor.feature_names, extractor,
            epsilon_s=1.0, hierarchy=h   # very permissive
        )
        res = exp.explain("P1", fv, event_set)
        assert res.is_faithful

    def test_output_value_matches_risk(self, event_set, extractor, risk_component, h):
        fv        = extractor.extract("P1", event_set)
        true_risk = risk_component.predict(fv).value
        exp = SufficientExplainer(
            risk_component, extractor.feature_names, extractor,
            epsilon_s=0.5, hierarchy=h
        )
        res = exp.explain("P1", fv, event_set)
        assert res.output_value == pytest.approx(true_risk, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: ExtendedValidationOperator Π_l^+ (AION §21.5)
# ══════════════════════════════════════════════════════════════════════════════

class TestExtendedValidationOperator:
    def test_accepts_within_k_max(self, event_set, extractor, risk_component, h):
        base_vo  = ValidationOperator(layer=5, c_min=0.0)
        shapley  = ShapleyExplainer(risk_component, extractor.feature_names, phi_min=0.0)
        ext_vo   = ExtendedValidationOperator(base_vo, shapley, k_max=100)
        fv       = extractor.extract("P1", event_set)
        out      = risk_component.predict(fv)
        dec      = ext_vo.validate(out, "P1", fv, event_set, h)
        assert dec.accepted

    def test_rejects_too_many_explanations(self, event_set, extractor, risk_component, h):
        base_vo  = ValidationOperator(layer=5, c_min=0.0)
        shapley  = ShapleyExplainer(risk_component, extractor.feature_names, phi_min=0.0)
        ext_vo   = ExtendedValidationOperator(base_vo, shapley, k_max=0)   # nothing allowed
        fv       = extractor.extract("P1", event_set)
        out      = risk_component.predict(fv)
        dec      = ext_vo.validate(out, "P1", fv, event_set, h)
        # P1 has 4 events with phi_min=0 → all 4 are explaining → exceeds K_max=0
        assert not dec.accepted
        assert "explanation_too_large" in dec.reason

    def test_base_rejection_propagated(self, event_set, extractor, risk_component, h):
        # Base validator rejects (confidence too low)
        base_vo  = ValidationOperator(layer=5, c_min=0.99)
        shapley  = ShapleyExplainer(risk_component, extractor.feature_names)
        ext_vo   = ExtendedValidationOperator(base_vo, shapley, k_max=100)
        fv       = extractor.extract("P1", event_set)
        out      = AIOutput(value=0.3, confidence=0.5, component="Test")
        dec      = ext_vo.validate(out, "P1", fv, event_set, h)
        assert not dec.accepted
        assert dec.reason == "confidence_too_low"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: Full Explanation Report
# ══════════════════════════════════════════════════════════════════════════════

class TestFullExplanationReport:
    def test_summary_contains_key_info(self, event_set, extractor, risk_component, h):
        fv   = extractor.extract("P1", event_set)
        risk = risk_component.predict(fv).value

        shapley_exp = ShapleyExplainer(
            risk_component, extractor.feature_names, phi_min=0.0
        )
        cf_exp = CounterfactualExplainer(
            risk_component, extractor.feature_names, extractor, h
        )
        suf_exp = SufficientExplainer(
            risk_component, extractor.feature_names, extractor,
            epsilon_s=0.5, hierarchy=h
        )

        report = FullExplanationReport(
            patient_id="P1",
            risk_estimate=risk,
            shapley=shapley_exp.explain("P1", fv, event_set, h),
            counterfactual=cf_exp.explain("P1", fv, event_set),
            sufficient=suf_exp.explain("P1", fv, event_set),
        )

        summary = report.summary()
        assert "P1"    in summary
        assert "Risk"  in summary
        assert "Shapley" in summary
        assert "CF"      in summary
        assert "Sufficient" in summary

    def test_report_risk_matches_component(self, event_set, extractor, risk_component, h):
        fv   = extractor.extract("P1", event_set)
        risk = risk_component.predict(fv).value
        report = FullExplanationReport(patient_id="P1", risk_estimate=risk)
        assert report.risk_estimate == pytest.approx(risk)

    def test_report_without_optional_fields(self):
        report = FullExplanationReport(patient_id="P1", risk_estimate=0.42)
        summary = report.summary()
        assert "P1"    in summary
        assert "0.42"  in summary

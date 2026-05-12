# aion/ai/components.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
"""
KI-Komponenten vollstaendig nach §21 des AION-Papers.

§21.1  Formale KI-Komponente A_l = (X_l, Y_l, f_theta, L, theta*)
§21.2  Validierungsoperator Pi_l
§21.3  Konfidenzgewichtete Ereignismenge E_cmin + Kalibrierung
§21.4  Schicht 2: Ereignisextraktion
§21.5  Schicht 3: Episoden/Trajektorien (in trajectories.py)
§21.6  Schicht 4: Anomalieerkennung
§21.7  Schicht 5: Risikoschatzung
§21.8  Schicht 6: Regellernen
§21.9  Schichtenkompositionsoperator
"""
from __future__ import annotations
import math, logging, re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)


# ── §21.1 Formale KI-Komponente ───────────────────────────────────────

@dataclass
class AIComponent:
    """
    A_l = (X_l, Y_l, f_theta_l, L_l, theta*_l) nach §21.1.

    X_l: Eingaberaum
    Y_l: Ausgaberaum
    f:   Lernfunktion (parametrisiert durch theta)
    L:   Verlustfunktion
    theta*: optimale Parameter (nach Training)
    """
    layer_id:    int
    name:        str
    input_space: str
    output_space: str
    paper_ref:   str

    def __call__(self, x: Any) -> Any:
        raise NotImplementedError(f"f_theta nicht implementiert fuer {self.name}")

    def loss(self, y_pred: Any, y_true: Any) -> float:
        raise NotImplementedError

    def info(self) -> dict:
        return {
            "layer_id":    self.layer_id,
            "name":        self.name,
            "input_space": self.input_space,
            "output_space": self.output_space,
            "paper_ref":   self.paper_ref,
        }


# ── §21.2 Validierungsoperator Pi_l ───────────────────────────────────

@dataclass
class ValidationResult:
    accepted:   bool
    event:      Any
    violations: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "accepted":   self.accepted,
            "violations": self.violations,
            "confidence": round(self.confidence, 4),
        }


class ValidationOperator:
    """
    Pi_l: Y_l -> Y_l UNION {bottom} nach §21.2.
    Akzeptiert y wenn alle Konsistenzbedingungen erfuellt.
    """

    def __init__(self, c_min: float = 0.5,
                 required_attrs: list[str] | None = None,
                 k_max: int = 50):
        self.c_min          = c_min
        self.required_attrs = required_attrs or []
        self.k_max          = k_max

    def validate(self, event, confidence: float = 1.0) -> ValidationResult:
        violations = []
        if confidence < self.c_min:
            violations.append(
                f"Konfidenz {confidence:.3f} < c_min {self.c_min:.3f}"
            )
        if not getattr(event, "event_type", None):
            violations.append("event_type fehlt")
        if not getattr(event, "t_start", None):
            violations.append("t_start fehlt")
        if not getattr(event, "patient_id", None):
            violations.append("patient_id fehlt")
        attrs = getattr(event, "attributes", {}) or {}
        for attr in self.required_attrs:
            if attr not in attrs:
                violations.append(f"Pflichtattribut '{attr}' fehlt")
        accepted = len(violations) == 0
        return ValidationResult(
            accepted=accepted,
            event=event if accepted else None,
            violations=violations,
            confidence=confidence,
        )

    def validate_many(self, events_with_conf: list[tuple]) -> tuple[list, list]:
        results, accepted = [], []
        for ev, conf in events_with_conf:
            r = self.validate(ev, conf)
            results.append(r)
            if r.accepted:
                accepted.append(ev)
        return accepted, results


# ── §21.3 Konfidenzgewichtete Ereignismenge E_cmin ────────────────────

@dataclass
class ConfidenceWeightedEvent:
    event:      Any
    confidence: float

    def is_accepted(self, c_min: float) -> bool:
        return self.confidence >= c_min


class ConfidenceEventStore:
    """E_cmin = {e | (e,c) in E_hat, c >= c_min} nach §21.3."""

    def __init__(self, c_min: float = 0.9):
        self.c_min   = c_min
        self._events: list[ConfidenceWeightedEvent] = []

    def add(self, event, confidence: float = 1.0) -> bool:
        ce = ConfidenceWeightedEvent(event, confidence)
        self._events.append(ce)
        return ce.is_accepted(self.c_min)

    def accepted(self) -> list:
        return [ce.event for ce in self._events if ce.is_accepted(self.c_min)]

    def summary(self) -> dict:
        total    = len(self._events)
        accepted = sum(1 for ce in self._events if ce.is_accepted(self.c_min))
        return {
            "c_min":           self.c_min,
            "total_events":    total,
            "accepted_events": accepted,
            "rejected_events": total - accepted,
            "acceptance_rate": round(accepted / max(total, 1), 4),
        }


class CalibrationModel:
    """
    Kalibrierungsbedingung nach §21.3:
    E[p in E | f^(5)(Psi(p)) = r] = r

    Implementiert Platt-Scaling als post-hoc Kalibrierung.
    Skalierer: sigma(A * f(x) + B) = kalibrierter Score.
    """

    def __init__(self):
        self.A: float = 1.0   # Skalierung
        self.B: float = 0.0   # Verschiebung
        self._fitted = False

    def fit(self, scores: list[float], labels: list[float]) -> None:
        """
        Platt-Scaling: logistische Regression auf (score, label).
        Analytische Loesung via Gradientenabstieg (5 Iterationen).
        """
        if len(scores) < 5:
            log.warning("Kalibrierung: zu wenige Datenpunkte (%d)", len(scores))
            return
        lr = 0.1
        for _ in range(500):
            grad_A = grad_B = 0.0
            for s, y in zip(scores, labels):
                p = 1 / (1 + math.exp(-(self.A * s + self.B)))
                err = p - y
                grad_A += err * s
                grad_B += err
            self.A -= lr * grad_A / len(scores)
            self.B -= lr * grad_B / len(scores)
        self._fitted = True
        log.info("Kalibrierung: A=%.4f B=%.4f", self.A, self.B)

    def calibrate(self, score: float) -> float:
        """Gibt kalibrierten Score in [0,1] zurueck."""
        return 1 / (1 + math.exp(-(self.A * score + self.B)))

    @property
    def is_fitted(self) -> bool:
        return self._fitted


# ── §21.4 Schicht 2: Ereignisextraktion ──────────────────────────────

class EventExtractionComponent(AIComponent):
    """f_theta_2: Sigma-star -> Delta(Ehat) nach §21.4."""

    CONDITION_KEYWORDS = {
        "herzinsuffizienz": ("Herzinsuffizienz", "I50.0", 0.85),
        "herzinfarkt":      ("Herzinfarkt",      "I21.9", 0.85),
        "diabetes":         ("DM Typ 2",         "E11.9", 0.75),
        "pneumonie":        ("Pneumonie",         "J18.9", 0.80),
        "sepsis":           ("Sepsis",            "A41.9", 0.85),
        "nierenversagen":   ("Akutes Nierenversagen", "N17.9", 0.80),
        "vorhofflimmern":   ("Vorhofflimmern",   "I48.9", 0.80),
        "schlaganfall":     ("Schlaganfall",      "I63.9", 0.85),
        "bluthochdruck":    ("Arterielle Hypertonie","I10", 0.75),
        "copd":             ("COPD",              "J44.9", 0.80),
    }
    LAB_PATTERN = {
        "laktat":       ("Laborbefund", "qlaktat",    "mmol/L"),
        "kreatinin":    ("Laborbefund", "kreatinin",  "mg/dL"),
        "haemoglobin":  ("Laborbefund", "haemoglobin","g/dL"),
        "leukozyten":   ("Laborbefund", "leukozyten", "G/L"),
        "crp":          ("Laborbefund", "crp",        "mg/L"),
        "troponin":     ("Laborbefund", "troponin",   "ng/L"),
        "procalcitonin":("Laborbefund", "procalcitonin","ng/mL"),
        "natrium":      ("Laborbefund", "natrium",    "mmol/L"),
        "kalium":       ("Laborbefund", "kalium",     "mmol/L"),
        "sofa":         ("Score",       "sofa_score", "Punkte"),
        "apache":       ("Score",       "apache_ii",  "Punkte"),
    }

    def __init__(self, validator: ValidationOperator | None = None):
        super().__init__(
            layer_id=2,
            name="Ereignisextraktion",
            input_space="Sigma* (Freitext)",
            output_space="Delta(Ehat)",
            paper_ref="§21.4",
        )
        self.validator = validator or ValidationOperator(c_min=0.5)

    def __call__(self, text: str, patient_id: str,
                 t_start: datetime | None = None) -> list[tuple]:
        return self.extract(text, patient_id, t_start)

    def loss(self, y_pred, y_true) -> float:
        """F1-basierter Verlust fuer Extraktionsguete."""
        tp = sum(1 for e in y_pred if e in y_true)
        fp = len(y_pred) - tp
        fn = len(y_true) - tp
        precision = tp / max(tp + fp, 1)
        recall    = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        return 1.0 - f1

    def extract(self, text: str, patient_id: str,
                t_start: datetime | None = None) -> list[tuple]:
        from aion import ClinicalEvent
        results  = []
        text_low = text.lower()
        now      = t_start or datetime.now(timezone.utc)

        for keyword, (label, icd, base_conf) in self.CONDITION_KEYWORDS.items():
            if keyword in text_low:
                conf = base_conf
                try:
                    ev = ClinicalEvent(
                        patient_id=patient_id, event_type="Diagnose",
                        t_start=now, t_end=now, stay_start=now, stay_end=now,
                        attributes={"dx_label": label, "dx_code": icd},
                        confidence=conf,
                    )
                    results.append((ev, conf))
                except Exception as exc:
                    log.warning("Extraktion %s fehlgeschlagen: %s", keyword, exc)

        for lab_key, (ev_type, attr, unit) in self.LAB_PATTERN.items():
            pattern = rf"{lab_key}\s*[:\s]\s*(\d+[.,]\d+)"
            m = re.search(pattern, text_low)
            if m:
                val  = float(m.group(1).replace(",", "."))
                conf = 0.90
                try:
                    ev = ClinicalEvent(
                        patient_id=patient_id, event_type=ev_type,
                        t_start=now, t_end=now, stay_start=now, stay_end=now,
                        attributes={attr: val, "unit": unit},
                        confidence=conf,
                    )
                    results.append((ev, conf))
                except Exception as exc:
                    log.warning("Labor-Extraktion %s fehlgeschlagen: %s", lab_key, exc)

        log.info("Extraktion: %d Ereignisse aus %d Zeichen", len(results), len(text))
        return results

    def extract_and_validate(self, text: str, patient_id: str,
                              t_start=None) -> dict:
        raw = self.extract(text, patient_id, t_start)
        accepted, results = self.validator.validate_many(raw)
        return {
            "extracted":  len(raw),
            "accepted":   len(accepted),
            "rejected":   len(raw) - len(accepted),
            "events":     accepted,
            "validation": [r.to_dict() for r in results],
        }


# ── §21.6 Schicht 4: Anomalieerkennung ───────────────────────────────

@dataclass
class AnomalyResult:
    """Ergebnis der Anomalieerkennung."""
    event:         Any
    is_anomaly:    bool
    anomaly_score: float   # 0=normal, 1=stark anomal
    reasons:       list[str] = field(default_factory=list)
    confidence:    float = 1.0

    def to_dict(self) -> dict:
        return {
            "is_anomaly":    self.is_anomaly,
            "anomaly_score": round(self.anomaly_score, 4),
            "reasons":       self.reasons,
            "confidence":    round(self.confidence, 4),
        }


class AnomalyDetectionComponent(AIComponent):
    """
    Schicht 4: Anomalieerkennung f^(4)_theta nach §21.6.
    f^(4)_theta: E -> [0,1] (Anomaliescore)

    Implementierung: regelbasierte Referenzgrenzen +
    statistischer Z-Score ueber Patientenhistorie.

    Referenzbereiche (vereinfacht, nicht medizinisch validiert):
    Erweiterbar durch ML-Modell (Autoencoder, IsolationForest).
    """

    # Klinische Referenzbereiche (normal: [low, high])
    REFERENCE_RANGES: dict[str, tuple[float, float]] = {
        "qlaktat":      (0.5, 2.0),    # mmol/L
        "kreatinin":    (0.6, 1.2),    # mg/dL
        "haemoglobin":  (12.0, 17.5),  # g/dL
        "leukozyten":   (4.0, 11.0),   # G/L
        "crp":          (0.0, 5.0),    # mg/L
        "troponin":     (0.0, 14.0),   # ng/L
        "natrium":      (135.0, 145.0),# mmol/L
        "kalium":       (3.5, 5.0),    # mmol/L
        "sofa_score":   (0.0, 2.0),    # Punkte (normal < 2)
        "apache_ii":    (0.0, 10.0),   # Punkte
    }

    def __init__(self, threshold: float = 0.5,
                 calibrator: CalibrationModel | None = None):
        super().__init__(
            layer_id=4,
            name="Anomalieerkennung",
            input_space="E (ClinicalEvent)",
            output_space="[0,1] (Anomaliescore)",
            paper_ref="§21.6",
        )
        self.threshold   = threshold
        self.calibrator  = calibrator
        self._history:   dict[str, list[dict]] = {}

    def loss(self, y_pred: float, y_true: float) -> float:
        """Binaraer Cross-Entropy Verlust."""
        eps = 1e-7
        y_pred = max(eps, min(1-eps, y_pred))
        return -(y_true * math.log(y_pred) + (1-y_true) * math.log(1-y_pred))

    def _reference_score(self, attrs: dict) -> tuple[float, list[str]]:
        """Regelbasierter Anomaliescore: wie weit ausserhalb des Referenzbereichs."""
        deviations = []
        reasons    = []
        for attr, (lo, hi) in self.REFERENCE_RANGES.items():
            val = attrs.get(attr)
            if val is None or not isinstance(val, (int, float)):
                continue
            span = hi - lo
            if span < 1e-9:
                continue
            if val < lo:
                dev = (lo - val) / span
                reasons.append(f"{attr}={val:.2f} < Referenz [{lo},{hi}]")
            elif val > hi:
                dev = (val - hi) / span
                reasons.append(f"{attr}={val:.2f} > Referenz [{lo},{hi}]")
            else:
                dev = 0.0
            deviations.append(min(1.0, dev))
        if not deviations:
            return 0.0, []
        score = min(1.0, sum(deviations) / len(deviations))
        return score, reasons

    def _zscore(self, patient_id: str, attrs: dict) -> float:
        """Statistischer Z-Score gegen Patientenhistorie."""
        if patient_id not in self._history or not self._history[patient_id]:
            return 0.0
        z_scores = []
        hist = self._history[patient_id]
        for attr in self.REFERENCE_RANGES:
            val = attrs.get(attr)
            if not isinstance(val, (int, float)):
                continue
            hist_vals = [h.get(attr) for h in hist
                         if isinstance(h.get(attr), (int, float))]
            if len(hist_vals) < 3:
                continue
            mu  = sum(hist_vals) / len(hist_vals)
            sig = math.sqrt(sum((v-mu)**2 for v in hist_vals) / len(hist_vals))
            if sig > 1e-6:
                z_scores.append(abs(val - mu) / sig)
        if not z_scores:
            return 0.0
        # Z-Score > 2.5 -> anomal
        mean_z = sum(z_scores) / len(z_scores)
        return min(1.0, mean_z / 2.5)

    def detect(self, event, patient_id: str | None = None) -> AnomalyResult:
        """f^(4)_theta(e): Gibt AnomalyResult zurueck."""
        attrs = getattr(event, "attributes", {}) or {}
        pid   = patient_id or getattr(event, "patient_id", "unknown")

        # Regelbasierter Score
        ref_score, reasons = self._reference_score(attrs)

        # Z-Score gegen Historie
        z_score = self._zscore(pid, attrs)

        # Kombinierter Score (gewichtet)
        combined = 0.7 * ref_score + 0.3 * z_score

        # Kalibrierung anwenden
        if self.calibrator and self.calibrator.is_fitted:
            combined = self.calibrator.calibrate(combined)

        # Historisieren
        if pid not in self._history:
            self._history[pid] = []
        self._history[pid].append(attrs)
        if len(self._history[pid]) > 100:
            self._history[pid] = self._history[pid][-100:]

        is_anomaly = combined >= self.threshold
        if is_anomaly:
            log.info("Anomalie: patient=%s score=%.3f reasons=%s",
                     pid, combined, reasons[:2])

        return AnomalyResult(
            event=event,
            is_anomaly=is_anomaly,
            anomaly_score=combined,
            reasons=reasons,
            confidence=1.0 - abs(combined - self.threshold),
        )

    def detect_batch(
        self, events: list, patient_id: str
    ) -> list[AnomalyResult]:
        return [self.detect(e, patient_id) for e in events]

    def summary(self, results: list[AnomalyResult]) -> dict:
        total     = len(results)
        anomalies = sum(1 for r in results if r.is_anomaly)
        return {
            "total_events":    total,
            "anomalies":       anomalies,
            "anomaly_rate":    round(anomalies / max(total,1), 4),
            "threshold":       self.threshold,
            "mean_score":      round(
                sum(r.anomaly_score for r in results) / max(total,1), 4
            ),
        }


# ── §21.8 Schicht 6: Regellernen ─────────────────────────────────────

@dataclass
class LearnedRule:
    """Gelernte Regel: Pra (Muster) -> Kon (Label) nach §21.8."""
    antecedent:  dict    # {attr: (op, threshold)}
    consequent:  str     # Vorhersage-Label
    support:     float   # P(Pra)
    confidence:  float   # P(Kon|Pra)
    lift:        float   # conf / P(Kon)

    def applies_to(self, attrs: dict) -> bool:
        for attr, (op, thresh) in self.antecedent.items():
            val = attrs.get(attr)
            if val is None or not isinstance(val, (int, float)):
                return False
            ops = {">":val>thresh,"<":val<thresh,
                   ">=":val>=thresh,"<=":val<=thresh,"==":val==thresh}
            if not ops.get(op, False):
                return False
        return True

    def to_dict(self) -> dict:
        ant_str = " AND ".join(
            f"{attr} {op} {thresh}"
            for attr,(op,thresh) in self.antecedent.items()
        )
        return {
            "rule":       f"IF {ant_str} THEN {self.consequent}",
            "support":    round(self.support, 4),
            "confidence": round(self.confidence, 4),
            "lift":       round(self.lift, 4),
        }


class RuleLearningComponent(AIComponent):
    """
    Schicht 6: Regellernen f^(6)_theta nach §21.8.

    Lernt Assoziationsregeln der Form:
    Phi_k(e) -> tau_target

    Implementierung: vereinfachtes RIPPER-artiges Verfahren
    (sequentielle Abdeckung mit greedy Spezialisierung).
    """

    def __init__(self, min_support: float = 0.1,
                 min_confidence: float = 0.7,
                 max_rules: int = 20):
        super().__init__(
            layer_id=6,
            name="Regellernen",
            input_space="E_tau (Ereignisse eines Typs)",
            output_space="Regelwerk R",
            paper_ref="§21.8",
        )
        self.min_support    = min_support
        self.min_confidence = min_confidence
        self.max_rules      = max_rules
        self.rules_:        list[LearnedRule] = []

    def loss(self, y_pred: str, y_true: str) -> float:
        return 0.0 if y_pred == y_true else 1.0

    def fit(self, events: list, labels: list[str]) -> None:
        """
        Lernt Regeln aus (event, label) Paaren.
        Greedy-Spezialisierung ueber numerische Attribute.
        """
        if not events or len(events) != len(labels):
            return

        all_attrs: set[str] = set()
        for e in events:
            for k,v in (getattr(e,"attributes",{}) or {}).items():
                if isinstance(v, (int, float)):
                    all_attrs.add(k)

        label_counts: dict[str, int] = {}
        for l in labels:
            label_counts[l] = label_counts.get(l,0) + 1

        rules: list[LearnedRule] = []
        n = len(events)

        for target_label in label_counts:
            p_label = label_counts[target_label] / n
            # Kandidatenregeln: ein Attribut-Schwellwert-Paar
            for attr in all_attrs:
                vals = sorted(set(
                    (getattr(e,"attributes",{}) or {}).get(attr)
                    for e in events
                    if isinstance((getattr(e,"attributes",{}) or {}).get(attr),(int,float))
                ))
                if len(vals) < 2:
                    continue
                # Schwellwert: Medianwert
                mid = vals[len(vals)//2]
                for op, cmp in [(">", lambda v,t: v>t), ("<=", lambda v,t: v<=t)]:
                    matching = [
                        (e,l) for e,l in zip(events,labels)
                        if isinstance((getattr(e,"attributes",{}) or {}).get(attr),(int,float))
                        and cmp((getattr(e,"attributes",{}) or {}).get(attr), mid)
                    ]
                    if not matching:
                        continue
                    support = len(matching) / n
                    if support < self.min_support:
                        continue
                    conf = sum(1 for _,l in matching if l==target_label) / len(matching)
                    if conf < self.min_confidence:
                        continue
                    lift = conf / max(p_label, 1e-9)
                    rules.append(LearnedRule(
                        antecedent={attr: (op, mid)},
                        consequent=target_label,
                        support=support,
                        confidence=conf,
                        lift=lift,
                    ))

        # Nach Lift sortieren, Top-N behalten
        self.rules_ = sorted(rules, key=lambda r: -r.lift)[:self.max_rules]
        log.info("Regellernen: %d Regeln gelernt (min_sup=%.2f, min_conf=%.2f)",
                 len(self.rules_), self.min_support, self.min_confidence)

    def predict(self, event) -> str | None:
        """Wendet erste passende Regel an."""
        attrs = getattr(event, "attributes", {}) or {}
        for rule in self.rules_:
            if rule.applies_to(attrs):
                return rule.consequent
        return None

    def rules_as_dict(self) -> list[dict]:
        return [r.to_dict() for r in self.rules_]


# ── §21.9 Schichtenkompositionsoperator ──────────────────────────────

class LayerComposer:
    """
    Kompositionsoperator der KI-Schichten nach §21.9.

    f^(2..6) = f^(6) o f^(5) o f^(4) o f^(3) o f^(2)

    Verarbeitet Freitext durch alle Schichten sequentiell:
    Text -> Ereignisse -> Episoden -> Anomalien -> Risiko -> Regeln
    """

    def __init__(
        self,
        extractor:  EventExtractionComponent,
        anomaly:    AnomalyDetectionComponent,
        risk:       "RiskEstimationComponent",
        rule_learner: RuleLearningComponent | None = None,
    ):
        self.extractor   = extractor
        self.anomaly     = anomaly
        self.risk        = risk
        self.rule_learner = rule_learner

    def process(
        self, text: str, patient_id: str,
        t_start: datetime | None = None,
    ) -> dict:
        """
        Vollstaendige Schichtenpipeline (§21.9).
        f^(2..6)(text, pk)
        """
        result: dict = {"patient_id": patient_id, "pipeline": []}

        # Schicht 2: Extraktion
        extracted = self.extractor.extract_and_validate(text, patient_id, t_start)
        events    = extracted["events"]
        result["layer_2_extraction"] = {
            "extracted": extracted["extracted"],
            "accepted":  extracted["accepted"],
        }
        result["pipeline"].append("layer_2_done")

        if not events:
            result["status"] = "no_events_extracted"
            return result

        # Schicht 4: Anomalieerkennung
        anomaly_results = self.anomaly.detect_batch(events, patient_id)
        anomalies = [r for r in anomaly_results if r.is_anomaly]
        result["layer_4_anomaly"] = self.anomaly.summary(anomaly_results)
        result["pipeline"].append("layer_4_done")

        # Schicht 5: Risikoschatzung
        risk_result = self.risk.predict_with_validation(events, patient_id)
        result["layer_5_risk"] = {
            "risk_score": risk_result["risk_score"],
            "risk_level": risk_result["risk_level"],
            "features":   risk_result["features"],
        }
        result["pipeline"].append("layer_5_done")

        # Schicht 6: Regelanwendung
        if self.rule_learner and self.rule_learner.rules_:
            rule_pred = self.rule_learner.predict(events[0]) if events else None
            result["layer_6_rules"] = {
                "prediction": rule_pred,
                "n_rules":    len(self.rule_learner.rules_),
            }
            result["pipeline"].append("layer_6_done")

        result["status"] = "ok"
        result["n_anomalies"] = len(anomalies)
        return result


# ── §21.7 Risikoschatzung ─────────────────────────────────────────────

class RiskEstimationComponent(AIComponent):
    """f^(5)_theta: R^d -> [0,1] nach §21.7."""

    DEFAULT_WEIGHTS = {
        "qlaktat":     0.15,
        "sofa_score":  0.12,
        "kreatinin":   0.08,
        "alter":       0.05,
        "n_diagnosen": 0.06,
        "n_ereignisse":0.04,
        "crp":         0.05,
        "troponin":    0.10,
        "apache_ii":   0.08,
    }

    def __init__(self, weights: dict | None = None, c_min: float = 0.0):
        super().__init__(
            layer_id=5,
            name="Risikoschatzung",
            input_space="R^d (Merkmalsvektor)",
            output_space="[0,1]",
            paper_ref="§21.7",
        )
        self.weights   = weights or self.DEFAULT_WEIGHTS
        self.validator = ValidationOperator(c_min=c_min)
        self.calibrator = CalibrationModel()

    def loss(self, y_pred: float, y_true: float) -> float:
        """Binaraer Cross-Entropy."""
        eps = 1e-7
        y_pred = max(eps, min(1-eps, y_pred))
        return -(y_true * math.log(y_pred) + (1-y_true) * math.log(1-y_pred))

    def feature_vector(self, events: list) -> dict:
        features: dict[str,float] = {}
        all_attrs = [getattr(e,"attributes",{}) or {} for e in events]
        for attr in self.weights:
            vals = [float(a[attr]) for a in all_attrs
                    if attr in a and isinstance(a[attr],(int,float))]
            if vals:
                features[attr] = sum(vals)/len(vals)
        features["n_ereignisse"] = float(len(events))
        features["n_diagnosen"]  = float(sum(
            1 for e in events if getattr(e,"event_type","") == "Diagnose"
        ))
        return features

    def __call__(self, events: list) -> float:
        score, _ = self.predict(events)
        return score

    def predict(self, events: list) -> tuple[float, dict]:
        feats  = self.feature_vector(events)
        linear = sum(self.weights.get(k,0)*v for k,v in feats.items())
        score  = 1.0 / (1.0 + math.exp(-linear))
        if self.calibrator.is_fitted:
            score = self.calibrator.calibrate(score)
        return round(score, 4), feats

    def predict_with_validation(self, events: list, patient_id: str) -> dict:
        score, feats = self.predict(events)
        class _E: pass
        se = _E()
        se.event_type = "RisikoScore"; se.t_start = datetime.now(timezone.utc)
        se.patient_id = patient_id;    se.attributes = {"risk_score": score}
        vr = self.validator.validate(se, confidence=1.0)
        return {
            "patient_id": patient_id,
            "risk_score": score,
            "risk_level": ("hoch" if score>0.6 else "mittel" if score>0.3 else "niedrig"),
            "features":   {k: round(v,4) for k,v in feats.items()},
            "n_events":   len(events),
            "validation": vr.to_dict(),
            "note": ("Kein zertifiziertes Medizinprodukt nach MDR 2017/745. "
                     "Nur fuer Forschungszwecke mit klinischer Aufsicht."),
        }


# ── §21.9 Uebersicht ──────────────────────────────────────────────────

AI_LAYER_OVERVIEW = {
    "layer_2": {
        "name":        "Ereignisextraktion",
        "input_space": "Sigma* (Freitext)",
        "output_space": "Delta(Ehat)",
        "class":       "EventExtractionComponent",
        "paper_ref":   "§21.4",
        "implemented": True,
    },
    "layer_3a": {
        "name":        "Episodenparameter (Delta-Lernen)",
        "input_space": "T x R^d",
        "output_space": "R>0 (Episodenabstand Delta)",
        "class":       "EpisodeDeltaLearner",
        "paper_ref":   "§21.5",
        "implemented": True,
    },
    "layer_3b": {
        "name":        "Trajektorienvorhersage",
        "input_space": "E^m (Teiltrajektorie)",
        "output_space": "Delta(T x R>=0)",
        "class":       "TrajectoryPredictor",
        "paper_ref":   "§21.5",
        "implemented": True,
    },
    "layer_4": {
        "name":        "Anomalieerkennung",
        "input_space": "E (ClinicalEvent)",
        "output_space": "[0,1] (Anomaliescore)",
        "class":       "AnomalyDetectionComponent",
        "paper_ref":   "§21.6",
        "implemented": True,
    },
    "layer_5": {
        "name":        "Risikoschatzung",
        "input_space": "R^d (Merkmalsvektor)",
        "output_space": "[0,1]",
        "class":       "RiskEstimationComponent",
        "paper_ref":   "§21.7",
        "implemented": True,
    },
    "layer_6": {
        "name":        "Regellernen",
        "input_space": "E_tau (Ereignisse eines Typs)",
        "output_space": "Regelwerk R",
        "class":       "RuleLearningComponent",
        "paper_ref":   "§21.8",
        "implemented": True,
    },
    "layer_comp": {
        "name":        "Schichtenkomposition",
        "input_space": "Sigma* x PatientID",
        "output_space": "Gesamtauswertung",
        "class":       "LayerComposer",
        "paper_ref":   "§21.9",
        "implemented": True,
    },
}

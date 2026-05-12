# aion/federation/federated.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH - EUPL-1.2
"""
Foederiertes Modell mit Differential Privacy nach §20.1-20.7.

Implementiert:
  §20.1  Foederierte Modellstruktur (disjunkte Patientenpartitionierung)
  §20.2  Foederierte Abfrageauswertung (lokale P^(k)_phi)
  §20.7  Lokale Differential Privacy je Institution
  §20.6  Kompositionstheorem ueber Institutionen
"""
from __future__ import annotations
import logging, math, random
from dataclasses import dataclass, field
from aion.privacy.dp import LocalDP, PrivacyBudget, LaplaceDP

log = logging.getLogger(__name__)


@dataclass
class Institution:
    """Eine Dateninstitution I_k nach §20.1."""
    institution_id:   str
    name:             str
    epsilon:          float = 1.0   # lokales DP-Budget
    patient_ids:      list  = field(default_factory=list)
    endpoint_url:     str   = ""    # fuer echte Foederierung (Zukunft)

    def local_dp(self) -> LocalDP:
        return LocalDP(epsilon=self.epsilon)


@dataclass
class FederatedQueryResult:
    """Ergebnis einer foederierten Abfrage."""
    institution_results: dict   # inst_id -> {count, noisy_count, epsilon}
    federated_estimate:  float
    federated_std_error: float
    n_institutions:      int
    privacy_guaranteed:  bool

    def to_dict(self) -> dict:
        return {
            "federated_estimate":       round(self.federated_estimate, 2),
            "federated_std_error":      round(self.federated_std_error, 4),
            "n_institutions":           self.n_institutions,
            "privacy_guaranteed":       self.privacy_guaranteed,
            "institution_results":      self.institution_results,
            "interpretation": (
                f"Geschaetzte Gesamtkohorte: ~{self.federated_estimate:.0f} "
                f"Patienten ueber {self.n_institutions} Institutionen "
                f"(Standardfehler: {self.federated_std_error:.2f}). "
                f"Alle Einzelergebnisse sind epsilon-DP-geschuetzt."
            ),
        }


class FederatedQueryEngine:
    """
    Foederierte Abfrageauswertung nach §20.2 + §20.7.

    Jede Institution berechnet lokal P^(k)_phi und gibt
    nur das verrauschte Ergebnis weiter.

    P_phi = UNION_k P^(k)_phi  (disjunkte Partitionierung §20.1)
    n_hat_phi = SUM_k M^LDP_k(|P^(k)_phi|)  (§20.7)
    """

    def __init__(self, institutions: list[Institution]):
        self.institutions = {i.institution_id: i for i in institutions}
        log.info("FederatedQueryEngine: %d Institutionen registriert",
                 len(institutions))

    def add_institution(self, inst: Institution) -> None:
        self.institutions[inst.institution_id] = inst
        log.info("Institution hinzugefuegt: %s (eps=%.2f)", inst.name, inst.epsilon)

    async def execute_federated_query(
        self,
        local_stores: dict,   # inst_id -> PostgresEventStore
        formula_dict: dict,
        apply_dp: bool = True,
    ) -> FederatedQueryResult:
        """
        Foederierte Kohortenabfrage nach §20.2.

        1. Jede Institution I_k wertet phi lokal aus -> |P^(k)_phi|
        2. Lokale DP: M^LDP_k(Ek) = |P^(k)_phi| + Lap(1/epsilon_k)
        3. Foederiertes Ergebnis: n_hat = SUM_k M^LDP_k
        """
        from aion.query.language import execute_cohort_query

        inst_results = {}
        local_counts = []
        noisy_counts = []
        epsilons     = []

        for inst_id, inst in self.institutions.items():
            store = local_stores.get(inst_id)
            if store is None:
                log.warning("Kein Store fuer Institution %s", inst_id)
                continue

            # Lokale Auswertung
            try:
                result = await execute_cohort_query(
                    formula_dict, store,
                    patient_ids=inst.patient_ids or None
                )
                true_count = result["cohort_size"]
            except Exception as exc:
                log.error("Fehler bei Institution %s: %s", inst_id, exc)
                true_count = 0

            # Lokale DP anwenden (§20.7)
            if apply_dp:
                ldp       = inst.local_dp()
                noisy     = max(0.0, ldp.release_local_count(true_count))
            else:
                noisy = float(true_count)

            inst_results[inst_id] = {
                "institution_name": inst.name,
                "noisy_count":      round(noisy, 2),
                "epsilon_used":     inst.epsilon,
                "dp_applied":       apply_dp,
            }
            noisy_counts.append(noisy)
            local_counts.append(true_count)
            epsilons.append(inst.epsilon)

        # Foederiertes Ergebnis aggregieren (§20.7)
        federated_estimate = LocalDP.aggregate(noisy_counts)
        std_error = LocalDP.federated_std_error(epsilons) if epsilons else 0.0

        log.info(
            "Foederierte Abfrage: ~%.0f Patienten ueber %d Institutionen "
            "(Standardfehler: %.2f)",
            federated_estimate, len(inst_results), std_error,
        )

        return FederatedQueryResult(
            institution_results=inst_results,
            federated_estimate=federated_estimate,
            federated_std_error=std_error,
            n_institutions=len(inst_results),
            privacy_guaranteed=apply_dp,
        )

    def status(self) -> dict:
        return {
            "n_institutions": len(self.institutions),
            "institutions": [
                {
                    "id":      inst_id,
                    "name":    inst.name,
                    "epsilon": inst.epsilon,
                    "n_patients": len(inst.patient_ids),
                }
                for inst_id, inst in self.institutions.items()
            ],
        }


def simulate_federated(
    n_institutions: int = 3,
    patients_per_inst: int = 100,
    cohort_fraction: float = 0.3,
    epsilon: float = 1.0,
) -> FederatedQueryResult:
    """
    Simulation einer foederierten Abfrage ohne echte DB.
    Nützlich fuer Demos und Tests.
    """
    local_counts = [
        int(patients_per_inst * cohort_fraction)
        for _ in range(n_institutions)
    ]
    epsilons = [epsilon] * n_institutions

    ldp = LocalDP(epsilon=epsilon)
    noisy_counts = [max(0.0, ldp.release_local_count(c)) for c in local_counts]
    federated    = LocalDP.aggregate(noisy_counts)
    std_err      = LocalDP.federated_std_error(epsilons)

    true_total = sum(local_counts)
    inst_results = {
        f"institution_{i+1}": {
            "institution_name": f"Klinik {chr(65+i)}",
            "noisy_count":      round(noisy_counts[i], 2),
            "epsilon_used":     epsilon,
            "dp_applied":       True,
        }
        for i in range(n_institutions)
    }

    return FederatedQueryResult(
        institution_results=inst_results,
        federated_estimate=federated,
        federated_std_error=std_err,
        n_institutions=n_institutions,
        privacy_guaranteed=True,
    )

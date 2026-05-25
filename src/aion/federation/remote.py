# aion/federation/remote.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""
Echte Multi-Institutionen-Föderierung nach §20.7.

Jede Institution exponiert ihre AION-API. Der Coordinator ruft
diese APIs auf und aggregiert die DP-geschützten Ergebnisse.

Sicherheit:
  - Jede Institution wendet eigene Local-DP an (rohe Daten verlassen Institution NIE)
  - Coordinator sieht nur verrauschte Aggregate
  - Auth: Bearer-Token je Institution
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
import urllib.request
import json
import ssl

from aion.api.config import settings
from aion.privacy.dp import LocalDP

log = logging.getLogger(__name__)


@dataclass
class RemoteInstitution:
    """
    Externe AION-Instanz einer Partnerinstitution.

    Beispiel:
      RemoteInstitution(
        institution_id="charite",
        name="Charité Berlin",
        endpoint_url="https://aion.charite.de",
        bearer_token="...",
        epsilon=1.0,
      )
    """
    institution_id: str
    name:           str
    endpoint_url:   str                    # https://aion-instance.klinik.de
    bearer_token:   str = ""
    epsilon:        float = 1.0            # Lokales DP-Budget
    timeout:        float = 30.0
    verify_ssl:     bool  = True

    async def query_cohort_count(self, formula_dict: dict) -> dict:
        """
        Ruft Remote-Endpoint /cohorts/count auf.
        Die Remote-Instanz wendet eigene Local-DP an.
        """
        url     = f"{self.endpoint_url.rstrip('/')}/cohorts/count"
        payload = json.dumps({
            "formula": formula_dict,
            "epsilon": self.epsilon,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        def _request():
            ctx = ssl.create_default_context() if self.verify_ssl else ssl._create_unverified_context()
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    return {
                        "status_code": resp.status,
                        "body":        json.loads(resp.read()),
                        "error":       None,
                    }
            except Exception as exc:
                return {
                    "status_code": 0,
                    "body":        {},
                    "error":       str(exc),
                }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _request)

    async def health_check(self) -> bool:
        """Prüft Erreichbarkeit der Remote-Instanz."""
        url = f"{self.endpoint_url.rstrip('/')}/health"

        def _request():
            ctx = ssl.create_default_context() if self.verify_ssl else ssl._create_unverified_context()
            try:
                with urllib.request.urlopen(url, timeout=5.0, context=ctx) as resp:
                    body = json.loads(resp.read())
                    return body.get("status") == "ok"
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _request)

    def to_dict(self) -> dict:
        return {
            "institution_id": self.institution_id,
            "name":           self.name,
            "endpoint_url":   self.endpoint_url,
            "epsilon":        self.epsilon,
            "has_token":      bool(self.bearer_token),
            "verify_ssl":     self.verify_ssl,
        }


class FederatedCoordinator:
    """
    Koordiniert echte Multi-Institutionen-Föderierung über HTTPS.

    Ablauf:
      1. POST /cohorts/count an jede RemoteInstitution
      2. Sammle verrauschte Counts (je Institution eigene DP)
      3. Aggregiere: n_hat = Σ_k M_k^LDP(|P_k^φ|)
    """

    def __init__(self, remotes: list[RemoteInstitution]):
        self.remotes = {r.institution_id: r for r in remotes}
        log.info("FederatedCoordinator: %d Remote-Institutionen", len(remotes))

    def add_remote(self, remote: RemoteInstitution) -> None:
        self.remotes[remote.institution_id] = remote

    def remove_remote(self, institution_id: str) -> None:
        self.remotes.pop(institution_id, None)

    async def execute_query(self, formula_dict: dict) -> dict:
        """
        Sendet Abfrage parallel an alle Remote-Institutionen.
        """
        tasks = [
            r.query_cohort_count(formula_dict)
            for r in self.remotes.values()
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        institution_results = {}
        noisy_counts = []
        epsilons     = []
        n_errors     = 0

        for (inst_id, remote), resp in zip(self.remotes.items(), responses):
            if isinstance(resp, Exception) or resp.get("error"):
                n_errors += 1
                institution_results[inst_id] = {
                    "institution_name": remote.name,
                    "endpoint":         remote.endpoint_url,
                    "error":            str(resp) if isinstance(resp, Exception) else resp.get("error"),
                    "status":           "unreachable",
                }
                continue

            body = resp["body"]
            noisy = float(body.get("value", 0))
            institution_results[inst_id] = {
                "institution_name": remote.name,
                "endpoint":         remote.endpoint_url,
                "noisy_count":      round(noisy, 2),
                "epsilon_used":     body.get("epsilon_used", remote.epsilon),
                "privacy_level":    body.get("privacy_level", "unknown"),
                "status":           "ok",
            }
            noisy_counts.append(noisy)
            epsilons.append(remote.epsilon)

        federated = LocalDP.aggregate(noisy_counts) if noisy_counts else 0.0
        std_err   = LocalDP.federated_std_error(epsilons) if epsilons else 0.0

        return {
            "federated_estimate":   round(federated, 2),
            "federated_std_error":  round(std_err, 4),
            "n_institutions":       len(self.remotes),
            "n_responding":         len(noisy_counts),
            "n_errors":             n_errors,
            "institution_results":  institution_results,
            "privacy_guaranteed":   True,
            "interpretation": (
                f"Geschaetzte Gesamtkohorte ueber {len(noisy_counts)} "
                f"erreichbare Institutionen (von {len(self.remotes)}): "
                f"~{federated:.0f} Patienten "
                f"(Standardfehler: {std_err:.2f})"
            ),
        }

    async def health_check_all(self) -> dict:
        """Prüft Erreichbarkeit aller Remote-Institutionen."""
        tasks  = [r.health_check() for r in self.remotes.values()]
        states = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "n_total":      len(self.remotes),
            "n_reachable":  sum(1 for s in states if s is True),
            "institutions": {
                inst_id: {
                    "name":      remote.name,
                    "endpoint":  remote.endpoint_url,
                    "reachable": state is True,
                }
                for (inst_id, remote), state in zip(self.remotes.items(), states)
            },
        }

    def status(self) -> dict:
        return {
            "n_remotes": len(self.remotes),
            "remotes": [r.to_dict() for r in self.remotes.values()],
        }

# aion/federation/__init__.py
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Foederation nach §20.7 (FM-3)."""
from aion.federation.federated import (
    Institution, FederatedQueryEngine, FederatedQueryResult,
)
from aion.federation.remote import (
    RemoteInstitution, FederatedCoordinator,
)
__all__ = [
    "Institution", "FederatedQueryEngine", "FederatedQueryResult",
    "RemoteInstitution", "FederatedCoordinator",
]

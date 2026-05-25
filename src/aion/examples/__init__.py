# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""AION Clinical — End-to-End-Beispiele.

Diese Skripte demonstrieren typische Anwendungsfälle und sind
ausführbar via ``python -m aion.examples.<name>``, z.B.::

    python -m aion.examples.hl7v2_demo
    python -m aion.examples.mllp_demo
    python -m aion.examples.auth_demo
    python -m aion.examples.fhir_demo

Verfügbare Demos:
    basic_usage          Typ-Hierarchie, Allen-Algebra, ClinicalEvent
    cardiology_demo      Kardiologie-spezifischer Workflow
    causal_inference_demo  Kausale Inferenz mit DoWhy-Bridge
    dowhy_demo           Sensitivitätsanalyse
    fhir_demo            FHIR-R4 Roundtrip
    hl7v2_demo           HL7 v2 Datei-Import
    mllp_demo            HL7 v2 MLLP-Live-Listener
    auth_demo            Authentifizierung (API-Key + MLLP)
    sqlite_demo          SQLite-EventStore
    synthea_demo         Synthea-Bundle-Import
    phase_a_demo         Phase-A-Demo (vollständiger Workflow)
"""

# AION Clinical

**Algebraic Interval Ontology for Clinical Networks — FM-3 Referenzimplementierung**

Formal temporal and causal structure for consistent clinical data across systems, including HL7 v2, FHIR and MLLP contexts.

[![Version](https://img.shields.io/badge/version-2.0.1-blue.svg)](https://github.com/fmatten/aion/releases)
[![Licence: EUPL-1.2](https://img.shields.io/badge/Licence-EUPL--1.2-blue.svg)](https://eupl.eu/1.2/en/)
[![PyPI](https://img.shields.io/pypi/v/aion-clinical.svg)](https://pypi.org/project/aion-clinical/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19553130.svg)](https://doi.org/10.5281/zenodo.19553130)

> GitHub: [fmatten/aion](https://github.com/fmatten/aion) · Codeberg: [iscad/aion](https://codeberg.org/iscad/aion) · PyPI: [aion-clinical](https://pypi.org/project/aion-clinical/)

This repository is the public source for AION Clinical — licensing setup, contribution rules and release metadata.

## Installation

```bash
pip install aion-clinical==2.0.1
pip install aion-clinical[full]==2.0.1   # komplettes Produktionspaket
```

## Verwandte Projekte

| Projekt | Beschreibung | Link |
|---|---|---|
| **FM-1** | Grundlagen zur wissenschaftlichen Auswertung klinischer Informationen | [10.5281/zenodo.19205557](https://doi.org/10.5281/zenodo.19205557) |
| **CAIRN** | FM-2: Clinical Interoperability Reference Architecture | [github.com/fmatten/CAIRN](https://github.com/fmatten/CAIRN) |
| **SILD** | FM-4: Signal-Loss Inspection at Data-boundaries | [github.com/fmatten/SILD](https://github.com/fmatten/SILD) |
| **FM-3 Paper** | Formale Wissensrepräsentation klinischer Verläufe | [10.5281/zenodo.19553130](https://doi.org/10.5281/zenodo.19553130) |

## Licensing

AION Clinical is offered under a dual-license model:

- **Open Source:** European Union Public Licence v. 1.2 (EUPL-1.2)
- **Commercial:** proprietary commercial licensing by **Iscad GmbH**

You may use, modify and distribute the software under the EUPL-1.2. Alternatively, commercial licensing terms are available from Iscad GmbH for use cases such as proprietary integration, redistribution under non-EUPL terms, OEM embedding, warranty/support arrangements or other negotiated commercial conditions.

See:

- `LICENSE.md`
- `LICENSES/EUPL-1.2.txt`
- `LICENSE-COMMERCIAL.md`
- `NOTICE`

## Medical and regulatory status

AION Clinical is provided as a research and clinical informatics software component. It is **not certified as a medical device under Regulation (EU) 2017/745 (MDR)** unless a specific certified distribution or deployment context explicitly states otherwise.

Use in clinical care, patient-facing workflows, diagnostic decision-making, therapy control or regulated operational environments requires appropriate governance, validation, risk management and, where applicable, separate certification.

## Repository role

This repository may be used to maintain:

- source code and documentation,
- licensing and dual-license setup,
- contribution rules,
- release notes,
- PyPI packaging metadata,
- public issue tracking.

## Contribution policy

External contributions are accepted only under the contribution terms in `CONTRIBUTING.md`. Contributors must confirm that their contributions may be distributed under the same dual-license model: EUPL-1.2 or commercial Iscad GmbH license.

## SPDX header

Recommended source file header:

```text
SPDX-FileCopyrightText: 2026 Iscad GmbH
SPDX-License-Identifier: EUPL-1.2 OR LicenseRef-Iscad-Commercial
```

## Contact

Commercial licensing and governance questions:

**Iscad GmbH**  
contact: `info@iscad-it.de`

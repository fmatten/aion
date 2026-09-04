# AION Clinical

> ## Rolle dieses Repos
>
> **Dies ist das veröffentlichte PyPI-Paket `aion-clinical`.** Der Paketname in
> `pyproject.toml` ist bewusst so und bleibt es — dieses Repo führt die
> Versionsgeschichte (Tags `v1.10.1` … `v2.0.5-quelle`).
>
> * **Messbaum:** Repo **`aion-clinical`** — dort liegt der Messcode (u. a.
>   `DocumentReference`), und alle Messwerkzeuge des Bestands nennen dessen Pfad.
> * **Schnappschussbaum:** Repo **`aion-full`** (Paketname seit 04.09.2026
>   `aion-full-snapshot`, PyPI-Release-Job stillgelegt).
>
> Drei Repos trugen bis zum 04.09.2026 denselben Paketnamen. Grundlage der Trennung:
> FM-Entscheide ①–④ zur Tafel `content/aion-verwechslungsflaeche-vorlage-2026-09.md`
> im Neuanfang-Bestand.


**Algebraic Interval Ontology for Clinical Networks — FM-3 Referenzimplementierung**

Formal temporal and causal structure for consistent clinical data across systems, including HL7 v2, FHIR and MLLP contexts.

[![Version](https://img.shields.io/badge/version-2.0.1-blue.svg)](https://github.com/fmatten/aion/releases)
[![Licence: AGPL-3.0](https://img.shields.io/badge/Licence-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0) [![Licence: Commercial](https://img.shields.io/badge/Licence-Commercial-orange.svg)](mailto:licensing@iscad-it.de)
[![PyPI](https://img.shields.io/pypi/v/aion-clinical.svg)](https://pypi.org/project/aion-clinical/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21254124.svg)](https://doi.org/10.5281/zenodo.21254124)

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
| **SILD** | FM-4: Signal-Loss Inspection at Data-boundaries | [github.com/fmatten/SILD](https://github.com/fmatten/SILD) · [10.5281/zenodo.20375435](https://doi.org/10.5281/zenodo.20375435) |
| **FM-3 Paper** | Formale Wissensrepräsentation klinischer Verläufe | [10.5281/zenodo.21255844](https://doi.org/10.5281/zenodo.21255844) |

## Licensing

AION Clinical is **dual-licensed**: **AGPL-3.0-only** (open source) **OR Commercial** (ISCaD GmbH).

### Open Source — AGPL-3.0-only

- Free to use, modify, and distribute
- Modifications **must be contributed back** under AGPL-3.0
- Copyleft covers **network use (SaaS)**
- Full text: [`LICENSES/AGPL-3.0.txt`](./LICENSES/AGPL-3.0.txt)

### Commercial Licence

A commercial licence is available for:
- Proprietary integration or redistribution
- Deployments where AGPL-3.0 copyleft obligations are not suitable
- OEM embedding, support & warranty arrangements

Contact: **friedhelm.matten@iscad-it.de**  
Details: [`LICENSE-COMMERCIAL.md`](./LICENSE-COMMERCIAL.md)

### SPDX

```text
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

See also: [`LICENSE.md`](./LICENSE.md) · [`NOTICE`](./NOTICE)

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

External contributions are accepted only under the contribution terms in `CONTRIBUTING.md`. Contributors must confirm that their contributions may be distributed under the same dual-license model: AGPL-3.0-only OR commercial ISCaD GmbH license.

## SPDX header

Recommended source file header:

```text
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

## Contact

Commercial licensing and governance questions:

**Iscad GmbH**  
contact: `info@iscad-it.de`

---

## Klonen

**Klon-URL:** `git@github.com:fmatten/aion.git`

Falls in einer vorhandenen Arbeitskopie ein abweichender `origin` eingetragen ist, kann dort ein
SSH-Alias aus einer maschinenlokalen `~/.ssh/config` stehen. Solche Aliasse lösen auf anderen
Rechnern nicht auf; ein `git clone` über die Aliasform scheitert dann an der **Namensauflösung**,
nicht an fehlender Berechtigung — was die Fehlersuche in die falsche Richtung schickt. Zum Klonen
deshalb immer die URL oben verwenden.

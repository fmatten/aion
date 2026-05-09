# AION — Algebraic Interval Ontology for Clinical Networks

**Formal model for clinical information systems.**
Foundation Module FM-3. Dual-licensed: EUPL-1.2 / Commercial.

---

## Repository Status

This Codeberg repository contains the **initial concept commit** of AION
from April 2026, comprising the foundation module (FM-3), the
Contributor License Agreement, the dual-license declaration, and the
file-header template.

The **active software development has continued elsewhere.** The current
release is published on PyPI; this repository serves as a historical
anchor for the original concept and the dual-licensing setup.

## Current Software — install from PyPI

The actively maintained software is published on PyPI:

```
pip install aion-clinical
```

- **PyPI:** <https://pypi.org/project/aion-clinical/>
- **Latest release:** 1.10.1 (May 2026)
- **License badge:** EUPL-1.2

The PyPI distribution includes:

- Type hierarchy and Allen interval algebra
- Temporal Conditional Frequency Graphs (TCFG) for pattern mining
- FHIR R4 import/export
- HL7 v2 file import
- HL7 v2 MLLP live listener (real-time)
- Pluggable authentication (API-Key, LDAP/AD, OIDC)
- Append-only audit trail
- SQLite storage (PostgreSQL backend planned)
- Optional GUI (PySide6) and Jupyter integration
- Optional causal inference via DoWhy

For a complete release history and the full changelog, see the PyPI
project page or the package's own `CHANGELOG.md`.

## Theoretical Foundation

The mathematical foundation of AION — type hierarchy semantics,
Allen-algebra interval relations, TCFG semantics, and the causal
inference framework — is documented as a separate scholarly artifact
and archived on Zenodo with its own DOI:

**DOI:** [10.5281/zenodo.19548857](https://doi.org/10.5281/zenodo.19548857)

Please cite the Zenodo record when referring to the **theoretical model**.
The software itself currently does not have a separate software-DOI;
when citing a specific software version, the canonical reference is
the PyPI release identifier (e.g. `aion-clinical 1.10.1`).

## Licensing

AION is offered under a **dual license**:

- **EUPL-1.2** (European Union Public Licence v1.2) for open-source use.
  Full text: see `LICENSE` in the PyPI distribution and at
  <https://joinup.ec.europa.eu/collection/eupl/>
- **Commercial license** available for proprietary integration,
  redistribution under non-EUPL terms, or settings where EUPL
  obligations are not desired.

For commercial licensing inquiries, please contact:

> **ISCaD GmbH**
> 30900 Wedemark, Germany
> [licensing@iscad-it.de](mailto:licensing@iscad-it.de)

The Contributor License Agreement (`CLA.md`) and the commercial
license terms (`LICENSE-COMMERCIAL.md`) in this repository document
the dual-licensing setup as established at project initiation.

## Disclaimer

AION Clinical is **not a certified medical device** under the EU Medical
Device Regulation (MDR 2017/745). It is provided as a research and
informatics tool. Use in patient care requires appropriate clinical
governance, validation, and — where applicable — separate regulatory
certification.

See the `NOTICE` file for the full disclaimer.

## Contact

| Topic | Contact |
| --- | --- |
| Commercial licensing, pilot inquiries, partnerships | <licensing@iscad-it.de> |
| Bug reports, feature requests | via PyPI release notes (preferred) |
| Theoretical / academic correspondence | <licensing@iscad-it.de> |

---

*Repository maintained by Friedhelm Matten / ISCaD GmbH.
Last updated: May 2026.*

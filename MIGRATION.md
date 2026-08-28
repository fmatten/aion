# Migration: AION Clinical 1.0.x → 1.10.x

This file documents API differences between the **early reference
implementation** (1.0.0–1.0.6, April 2026) and the **current platform
release** (1.10.x, May 2026).

The 1.0.x line was a mathematics-focused reference for Allen-Algebra
intervals and type hierarchies. The 1.10.x line is a kernel+plugin
architecture covering HL7 v2 import, MLLP live listening, FHIR
roundtrip, authentication, audit trail, and SQLite persistence.

## API changes at a glance

| Concern | 1.0.x | 1.10.x |
|---|---|---|
| Interval | `from aion.core import Interval` | `from aion import AllenInterval` |
| Allen relation | `Interval.classify(other)` | `AllenInterval.relation_to(other)` |
| Event model | informal | `from aion import ClinicalEvent` |
| Storage | (none built-in) | `from aion import SQLiteEventStore` |
| Type hierarchy | inline YAML loading | `from aion import TypeHierarchy` |
| Causal graph | n/a | `from aion import CausalGraph` |
| Pattern mining | n/a | `from aion import TCFG` |
| FHIR | n/a | `from aion.fhir import to_fhir_bundle, from_fhir_bundle` |
| HL7 v2 | n/a | `from aion.hl7v2 import parse_message` |
| MLLP | n/a | `from aion.hl7v2.mllp import serve_mllp` |
| Auth | n/a | `from aion.auth import create_auth_backend` |

## Concrete migration examples

### Allen-Algebra interval comparison

**1.0.x:**

```python
from aion.core import Interval

i1 = Interval(start=0, end=10)
i2 = Interval(start=5, end=15)
relation = i1.classify(i2)   # → "overlaps" or similar string
```

**1.10.x:**

```python
from aion import AllenInterval, AllenRelation

i1 = AllenInterval(start=0, end=10)
i2 = AllenInterval(start=5, end=15)
relation = i1.relation_to(i2)   # → AllenRelation.OVERLAPS (enum)
```

The relation is now a typed enum (`AllenRelation.BEFORE`,
`OVERLAPS`, `CONTAINS`, etc.) instead of a string, which catches
typos at type-check time.

### Loading a type hierarchy

**1.0.x** (manual YAML loading):

```python
import yaml
with open("schemas/clinical_base.yaml") as f:
    data = yaml.safe_load(f)
# … your own classification logic
```

**1.10.x** (built-in, with hierarchy queries):

```python
from aion import TypeHierarchy
from importlib.resources import files

base_path = files('aion.schemas').joinpath('clinical_base.yaml')
h = TypeHierarchy.from_yaml(base_path)

# Now query the DAG:
ancestors = h.ancestors_of("Troponin")        # → frozenset of TypeNodes
descendants = h.descendants_of("Diagnose")
is_subtype = h.is_subtype_of("Troponin", "Laborwert")  # → True
```

### Modelling a clinical event

**1.10.x** (no equivalent in 1.0.x):

```python
from aion import ClinicalEvent, AllenInterval, EventRelation
from datetime import datetime

event = ClinicalEvent(
    event_id="E-001",
    type_name="Herzinfarkt",
    patient_id="P-001",
    timestamp=datetime(2026, 5, 6, 14, 30),
    interval=AllenInterval(start=..., end=...),
    payload={"loinc": "30148-7"},
)
```

### Persistence

**1.10.x** (no equivalent in 1.0.x):

```python
from aion import SQLiteEventStore, ClinicalEvent

with SQLiteEventStore("klinik.db") as store:
    store.add(event)
    events = store.query(patient_id="P-001")
```

### FHIR roundtrip

**1.10.x** (no equivalent in 1.0.x):

```python
from aion.fhir import to_fhir_bundle, from_fhir_bundle, bundle_to_file
bundle = to_fhir_bundle(events, type_hierarchy=h)
bundle_to_file(bundle, "export.json")

# Re-import:
from aion.fhir import bundle_from_file
events_back = from_fhir_bundle(bundle_from_file("export.json"))
```

Supported resource types: `Observation`, `Condition`,
`MedicationAdministration`, `Procedure`. Other types
(`Patient`, `Encounter`, `DiagnosticReport`) are silently
ignored on import rather than rejected.

### HL7 v2 file import

**1.10.x** (new):

```python
from aion.hl7v2 import parse_message, message_to_event

msg = parse_message(open("adt_a01.hl7").read())
event = message_to_event(msg)  # → ClinicalEvent or None
```

CLI: `aion import /path/to/hl7-files --hl7v2 --db klinik.db`

### MLLP live listener

**1.10.x** (new):

```python
from aion import SQLiteEventStore, AuditLog
from aion.hl7v2.mllp import serve_mllp

with SQLiteEventStore("klinik.db") as store:
    audit = AuditLog("audit.db")
    serve_mllp(host="0.0.0.0", port=2575, store=store, audit=audit)
```

CLI: `aion mllp-listen --port 2575 --db klinik.db --audit audit.db`

### Authentication (API-Key example)

**1.10.x** (new):

```python
from aion.auth import APIKeyBackend, APIKeyCredentials

backend = APIKeyBackend("/etc/aion/api-keys.yaml")
principal = backend.authenticate(APIKeyCredentials("aion_J7K9X2..."))
print(principal.user_id, principal.roles)
```

CLI: `aion auth keygen --name mirth-1 --roles ingest --expires 2027-12-31`

## What you should do when upgrading

1. **Replace `from aion.core import Interval` with `from aion import AllenInterval`**.
   The old `aion.core` module no longer exists.
2. **Replace `.classify()` calls with `.relation_to()`** and update
   downstream code to use the `AllenRelation` enum instead of strings.
3. **Adopt `ClinicalEvent`** as the canonical event type if you were
   using ad-hoc dictionaries. The dataclass is frozen and hashable.
4. **Switch to `SQLiteEventStore`** for persistence instead of rolling
   your own SQLite wrapper.
5. **Load schemas via `importlib.resources`** instead of relative
   filesystem paths — schemas now ship inside the package.

## What didn't change

- `AGPL-3.0-only / commercial dual-license` model
- `Friedhelm Matten / ISCaD GmbH` as copyright holder
- Python 3.10+ as minimum
- `aion-clinical` as the PyPI package name

## Asking for help

For commercial licensing or migration support, contact
<licensing@iscad-it.de>.

For non-commercial questions, the source repository at
<https://codeberg.org/iscad/aion> documents the initial concept;
the active development continues on PyPI.

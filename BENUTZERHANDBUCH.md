# AION Clinical — Benutzerhandbuch

Praktische Schritt-für-Schritt-Anleitung: vom leeren Terminal bis zur
laufenden GUI. Kein Vorwissen außer Python 3.10+ vorausgesetzt.

---

## Inhalt

1. [Voraussetzungen](#1-voraussetzungen)
2. [Installation in lokaler Python-Umgebung (venv)](#2-installation-in-lokaler-python-umgebung-venv)
3. [Tests ausführen](#3-tests-ausführen)
4. [Beispiel-Skripte](#4-beispiel-skripte)
5. [GUI starten und bedienen](#5-gui-starten-und-bedienen)
6. [Eigenes Schema erstellen](#6-eigenes-schema-erstellen)
7. [Programmatische Nutzung](#7-programmatische-nutzung)
8. [Häufige Probleme](#8-häufige-probleme)

---

## 1. Voraussetzungen

| Komponente | Mindestversion | Prüfen mit |
|---|---|---|
| Python | 3.10 | `python3 --version` |
| pip | 22 | `pip --version` |
| venv | (Teil von Python) | `python3 -m venv --help` |

**Linux/Debian/Ubuntu:** falls `venv` fehlt:
```bash
sudo apt install python3-venv python3-pip
```

**macOS:** Python via [python.org-Installer](https://www.python.org/downloads/)
oder `brew install python@3.12`.

**Windows:** Python via [python.org-Installer](https://www.python.org/downloads/),
Häkchen bei „Add Python to PATH" setzen.

---

## 2. Installation in lokaler Python-Umgebung (venv)

### 2.1 ZIP entpacken

```bash
unzip aion-clinical.zip
cd aion-clinical
```

Du solltest jetzt diese Struktur sehen:

```
aion-clinical/
├── BENUTZERHANDBUCH.md
├── README.md
├── LICENSE
├── pyproject.toml
├── src/aion/...
├── tests/...
├── schemas/...
└── examples/...
```

### 2.2 venv erstellen und aktivieren

```bash
# venv anlegen (legt Ordner ./venv/ an)
python3 -m venv venv

# Aktivieren
source venv/bin/activate          # Linux/macOS
# bzw.
venv\Scripts\activate.bat         # Windows cmd
venv\Scripts\Activate.ps1         # Windows PowerShell
```

Erfolgreich aktiviert ist die Umgebung, wenn das Terminal-Prompt mit
`(venv)` beginnt:

```
(venv) user@host:~/aion-clinical$
```

**Wichtig:** alle folgenden Befehle laufen IM aktivierten venv.
Beim nächsten Terminal-Start musst Du `source venv/bin/activate`
erneut ausführen.

### 2.3 Installation auswählen

AION hat einen minimalen Kern und mehrere Optional-Pakete. Wähle eine
der folgenden Varianten:

| Variante | Befehl | Was Du bekommst |
|---|---|---|
| **Minimal** | `pip install -e .` | Kern + PyYAML, ohne GUI |
| **Mit GUI** | `pip install -e ".[gui]"` | + PySide6 (Qt) |
| **Mit Verifikation** | `pip install -e ".[verify]"` | + Z3-SMT-Solver |
| **Alles** | `pip install -e ".[gui,verify,dev]"` | + Tests + Linter |

**Empfehlung für den Start:**

```bash
pip install -e ".[gui,verify,dev]"
```

Das zieht alle Pakete für GUI, Schema-Verifikation und Tests in einem
Schritt. Dauer: ca. 1–2 Minuten je nach Internet-Verbindung. PySide6
ist mit ~80 MB der größte Brocken.

### 2.4 Installation prüfen

```bash
# Public-API smoke test
python -c "import aion; print('AION', aion.__version__, 'OK')"
```

Erwartete Ausgabe:
```
AION 1.10.3 OK
```

```bash
# CLI-Eintrag verfügbar?
which aion-gui
```

Erwartete Ausgabe (Pfad mit `venv/bin`):
```
/path/to/aion-clinical/venv/bin/aion-gui
```

---

## 3. Tests ausführen

```bash
python -m pytest tests/
```

Erwartete Ausgabe (kompakter Default-Modus):
```
================== test session starts ==================
collected 155 items

tests/test_causal.py .............                [ 10%]
tests/test_fhir.py .....................          [ 27%]
tests/test_logging.py .......                     [ 33%]
tests/test_persistence.py ...............         [ 45%]
tests/test_schema.py ...                          [ 48%]
tests/test_tcfg.py .................              [ 62%]
tests/test_temporal.py .............              [ 72%]
tests/test_types.py ................              [ 86%]
tests/test_verify.py .................            [100%]

============= 364 passed, 1 skipped in 0.5s =============
```

Wenn alle Tests grün durchlaufen, ist die Installation erfolgreich.

> **Hinweis:** Die genauen Test-Anzahlen pro Datei können je nach Version
> leicht abweichen. Entscheidend ist, dass alle Tests grün sind und
> *keine* `failed` oder `error` erscheint. Ohne `[verify]`-Extra werden
> die zwei Z3-Tests übersprungen.

**Mit Coverage-Report:**

```bash
pip install pytest-cov                  # falls nicht via [dev] installiert
python -m pytest tests/ --cov=aion --cov-report=term-missing
```

**Einzelne Test-Datei:**

```bash
python -m pytest tests/test_verify.py -v
```

---

## 4. Beispiel-Skripte

Vier Demo-Skripte zeigen die Hauptfeatures. Jedes ist eigenständig
ausführbar.

### 4.1 Grundlagen

```bash
python examples/basic_usage.py
```

Zeigt: TypeHierarchy programmatisch + via Builder + via `@aion_type`-Decorator,
plus Erzeugung eines `ClinicalEvent`s.

### 4.2 SQLite-Persistenz mit typisierten Referenzen

```bash
python examples/sqlite_demo.py
```

Zeigt: Ein Sepsis-Patient mit Laktatmessung, Diagnose und Antibiotikum.
Beziehungen (`observation_of`, `response_to`) werden persistiert und
in beide Richtungen abgefragt.

### 4.3 Kausale Inferenz

```bash
python examples/causal_inference_demo.py
```

Zeigt: Klinisches Konfounder-Beispiel (Frühe Antibiose → 30-Tage-Mortalität,
SOFA als Confounder), inklusive Backdoor-Adjustierung und ATE-Berechnung.

### 4.4 Phase-A-Featureschau

```bash
python examples/phase_a_demo.py
```

Zeigt die Phase-A-Erweiterungen (typisierte Referenzen, Pattern-Mining,
formale Verifikation) in einem Skript:

- Knowledge-Graph mit typisierten Beziehungen
- Pattern-Mining auf Patientensequenzen (findet `Fieber → SIRS → Sepsis`)
- Multi-Inheritance-Konfliktcheck (mit Z3-Erfüllbarkeitsprüfung, falls verfügbar)
- Formale Backdoor-Validierung via d-Separation

### 4.5 FHIR-Round-Trip

```bash
python examples/fhir_demo.py
```

Zeigt: 4 Patientenereignisse (Laktatmessung, Sepsis-Diagnose, ZVK-Anlage,
Antibiotikum) → FHIR-Bundle → JSON-Datei → Bundle → Events. Die generierte
JSON-Datei landet unter `/tmp/aion-fhir-demo/patient_p77_bundle.json` und
kann mit jedem FHIR-Validator (z. B. dem öffentlichen
[validator.fhir.org](https://validator.fhir.org/)) geprüft werden. Voraussetzung:
`pip install -e ".[fhir]"`.

### 4.6 Kardiologie — STEMI-Verlauf

```bash
python examples/cardiology_demo.py
```

Zeigt: realistischer Verlauf einer 67-jährigen Patientin mit ST-Hebungs-
Infarkt. Lädt `clinical_base.yaml` und `cardiology_extension.yaml`
gemeinsam (32 Typen), legt 12 typisierte Ereignisse über 140 Minuten an
(EKG, Troponin, Diagnose, Antikoagulation, PCI, Echo, Statin) und
extrahiert den Qualitätsindikator **Door-to-Balloon-Zeit** aus den
Daten. Demonstriert auch die typisierten Beziehungen:
EKG `confirms` STEMI, PCI `response_to` STEMI, Herzinsuffizienz
`caused_by` STEMI.

---

## 5. GUI starten und bedienen

Nur möglich, wenn mit `[gui]`-Extra installiert.

### 5.1 Start

```bash
# In-Memory-Datenbank (alle Daten weg beim Beenden)
aion-gui

# Persistente Datenbank in Datei
aion-gui patients.db
```

Es öffnet sich ein Fenster ca. 1200 × 780 px mit fünf Tabs.

### 5.2 Tab „Typ-Hierarchie"

**Zweck:** Klinische Ereignistypen anlegen und in einer Baumstruktur ordnen.

**Linke Seite:** Tree-Ansicht aller Typen, Wurzel ist `⊤`.
**Rechte Seite:** Detail-Panel des markierten Typs.

| Knopf | Funktion |
|---|---|
| **+ Typ** | Neuen Top-Level-Typ anlegen |
| **+ Subtyp** | Subtyp unter dem aktuell markierten Typ |
| **+ Attribut** | Attribut zum markierten Typ hinzufügen |
| **– Löschen** | Markierten Typ entfernen (Kinder werden zu ⊤ umgehängt) |
| **Validieren** | Konsistenzcheck mit Tiefenangabe |

**Workflow für einen ersten Typ:**

1. **+ Typ** → Name eingeben, z. B. `Diagnose` → OK
2. Tree zeigt jetzt `Diagnose` unter `⊤`
3. `Diagnose` markieren
4. **+ Subtyp** → `Herzinfarkt` → OK
5. `Herzinfarkt` markieren → **+ Attribut** → Name `troponin`,
   Typ `float`, Einheit `ng/ml`, Min `0`, Max `100` → Speichern
6. Im Detail-Panel sollten nun unter „Attribute" `troponin [float] (ng/ml) [0.0, 100.0]`
   erscheinen

### 5.3 Tab „Ereignisse"

**Zweck:** Klinische Ereignisse erfassen und in SQLite ablegen.

| Knopf | Funktion |
|---|---|
| **+ Ereignis** | Neues Ereignis anlegen (Dialog) |
| **– Löschen** | Markierte Zeile(n) entfernen |
| **↻ Aktualisieren** | Tabelle neu laden |
| **Filter Patient** | Nur Ereignisse eines Patienten zeigen |

**Workflow:**

1. **+ Ereignis** → Dialog erscheint
2. Patient-ID: `P001`
3. Typ: aus Combobox wählen (alle Typen aus der Hierarchie)
4. Zeitstempel im ISO-Format: `2026-02-15T08:30`
5. Aufenthalts-Start/-Ende: muss das Ereignis-Intervall enthalten
6. Attribute als JSON: `{"troponin": 5.4, "stemi": true}`
7. Konfidenz: `1.0` für sichere Ereignisse
8. **Speichern** → erscheint in Tabelle

**Tipp:** Liegt Aufenthalt-Start nach Ereignis-Start, fragt der Dialog
nochmal nach. Das ist die `is_temporally_embedded`-Prüfung —
mathematische Wohlgeformtheit `[t_B, t_E] ⊆ a`.

### 5.4 Tab „Allen-Relationen"

**Zweck:** Die 13 Allen-Beziehungen interaktiv erkunden.

- **8 Slider:** Start/Ende für I1 und I2, plus optionale Unschärfen `ε`
- **Canvas:** zeigt beide Intervalle übereinander auf einer Zeitachse
- **Label:** zeigt die aktuell zutreffende Allen-Relation
- **Tabelle unten:** wenn `ε > 0`, zeigt Wahrscheinlichkeitsverteilung
  über alle 13 Relationen (Monte-Carlo, n=1000)

**Schnell-Tour:**

1. I1-Slider so setzen, dass `[1, 4]`
2. I2-Slider auf `[3, 6]` → Label sagt `overlaps`
3. I2-Start auf `4` → Label wechselt zu `meets`
4. I1-ε_e auf `0.5` ziehen → Tabelle zeigt etwa `overlaps ≈ 0.98, before ≈ 0.02`.
   `meets` taucht **nicht** in der Tabelle auf, obwohl sie konzeptuell „benachbart"
   ist: die Relation verlangt `end_I1 == start_I2` exakt, und bei stetiger
   Normalverteilung ist die Wahrscheinlichkeit jedes einzelnen Punktwerts null.
   Das ist mathematisch korrekt, nicht ein Bug.

### 5.5 Tab „Kausalgraph"

**Zweck:** Kausale Modelle skizzieren und Backdoor-Sets visualisieren.

| Aktion | Effekt |
|---|---|
| **Doppelklick** auf leere Fläche | Neuer Knoten |
| **Klick + Ziehen** auf Knoten | Knoten verschieben |
| **Shift+Klick** auf zwei Knoten | Gerichtete Kante (1.→2.) |
| **Rechtsklick** auf Knoten oder Kante | Löschen |
| **Treatment / Outcome** im Side-Panel | Backdoor-Highlight |

**Farbcodierung nach Auswahl von Treatment X / Outcome Y:**

- **Blau** = Treatment X
- **Orange** = Outcome Y
- **Rot** = Backdoor-Adjustment-Set Z (Konfounder)
- **Grau** = Nachfahre von X (darf NICHT in Z)
- **Rote Kanten** = Backdoor-Pfad (geht in X hinein)

**Schnell-Tour:**

1. Toolbar: **Beispiel laden** → klassisches Konfounder-Setup mit
   Z1, Z2, X, M, Y wird angelegt
2. Side-Panel: Treatment = `X`, Outcome = `Y`
3. Z1 und Z2 färben sich rot (im Adjustment-Set)
4. M färbt sich grau (Mediator, Nachfahre von X)
5. **Berechnen (exakt)** → Demo-Inferenz `P(Y=1 | do(X=1)) ≈ 0.69`
   (Sigmoid-Modell mit synthetischen Daten — uniformes P(Z₁) = P(Z₂) = 0.5,
   Logit = 0.5·X + 0.3·(Z₁+Z₂))
6. **JSON exportieren** → Graph + Knotenpositionen als Datei
7. **DOT kopieren** → Graphviz-Syntax in der Zwischenablage

### 5.6 Tab „Schema-Editor"

**Zweck:** Typ-Hierarchie als YAML editieren.

| Knopf | Funktion |
|---|---|
| **↻ Aus Hierarchie laden** | Aktuellen Stand als YAML anzeigen |
| **✓ Validieren** | Syntax + DAG-Konsistenz prüfen |
| **↑ Übernehmen** | YAML → ersetzt aktuelle Hierarchie (mit Bestätigung) |

**Workflow „Schema importieren":**

1. **Datei → Schema laden (YAML)…** im Hauptmenü
2. Wähle `schemas/clinical_base.yaml`
3. Tab „Typ-Hierarchie" zeigt nun 13 vordefinierte klinische Typen
4. Wechsel auf „Schema-Editor" → der YAML-Inhalt erscheint zum Editieren

**Workflow „Eigenes Schema":**

1. Im Schema-Editor YAML eintippen oder aus `clinical_base.yaml` kopieren
2. **Validieren** → Statusleiste grün/rot
3. **Übernehmen** bei Erfolg → Tab „Typ-Hierarchie" aktualisiert sich

### 5.7 Datei-Menü

| Eintrag | Tastenkürzel | Funktion |
|---|---|---|
| Schema laden (YAML)… | Ctrl+O | YAML-Datei → Hierarchie |
| Schema speichern… | Ctrl+S | Aktuelle Hierarchie → YAML |
| Datenbank öffnen… | — | Bestehende SQLite-DB öffnen |
| Datenbank exportieren… | — | DB-Backup in andere Datei |
| Beenden | Ctrl+Q | Programm schließen |

---

## 6. Eigenes Schema erstellen

### 6.1 YAML-Format

Erstelle `mein_schema.yaml`:

```yaml
types:
  - name: Diagnose
    fhir: Condition
    description: "Klinische Diagnose"
    attributes:
      code:
        type: string
        required: true
      severity:
        type: enum
        values: [mild, moderate, severe]

  - name: Pneumonie
    parent: Diagnose
    description: "Lungenentzündung"
    attributes:
      pathogen:
        type: string
      crp:
        type: float
        unit: "mg/l"
        range: [0, 500]
```

**Felder pro Typ:**

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `name` | ja | eindeutiger Bezeichner |
| `parent` | nein | Name des Eltern-Typs (default: ⊤) |
| `fhir` | nein | FHIR-Ressource für späteren Mapper |
| `description` | nein | Freitext für Domain-Experten |
| `attributes` | nein | Schema der erlaubten Attribute |

**Felder pro Attribut:**

| Feld | Bedeutung |
|---|---|
| `type` | `int`, `float`, `string`, `bool`, `enum` |
| `unit` | physikalische Einheit (Freitext) |
| `range` | `[min, max]` für int/float |
| `values` | Liste erlaubter Werte (nur für `enum`) |
| `required` | `true`/`false` |

### 6.2 Schema laden

**In der GUI:** Datei → Schema laden (YAML)…

**Programmatisch:**
```python
from aion import TypeHierarchy
h = TypeHierarchy.from_yaml("mein_schema.yaml")
print(f"{len(h)} Typen geladen")
```

### 6.3 Schema verifizieren

```python
from aion import check_inheritance_conflicts, check_required_attributes

report = check_inheritance_conflicts(h)
print(report.summary())  # findet Multi-Inheritance-Probleme

# Welche Attribute MUSS ein Pneumonie-Ereignis ausfüllen?
print(check_required_attributes(h, "Pneumonie"))  # → {'code'}
```

---

## 7. Programmatische Nutzung

### 7.1 Ereignis erfassen und persistieren

```python
from datetime import datetime
from aion import (
    ClinicalEvent, EventRelation,
    SQLiteEventStore, TypeHierarchy,
)

# Schema laden
h = TypeHierarchy.from_yaml("schemas/clinical_base.yaml")

# Ereignisse erzeugen
base = datetime(2026, 3, 1, 10, 0)
diagnose = ClinicalEvent(
    patient_id="P-42",
    event_type="Sepsis",
    t_start=base,
    t_end=base,
    stay_start=datetime(2026, 3, 1, 8, 0),
    stay_end=datetime(2026, 3, 5, 12, 0),
    attributes={"sofa_score": 9, "lactate": 4.5},
)

laktat = ClinicalEvent(
    patient_id="P-42",
    event_type="Laktatmessung",
    t_start=base,
    t_end=base,
    stay_start=datetime(2026, 3, 1, 8, 0),
    stay_end=datetime(2026, 3, 5, 12, 0),
    attributes={"value": 4.5},
)

# Typisierte Beziehung: Laktatmessung bestätigt Diagnose
diagnose.add_reference(laktat, EventRelation.CONFIRMS)

# Persistieren
with SQLiteEventStore("clinical.db") as store:
    store.add_many([laktat, diagnose])

    # Abfragen
    events = store.find_by_patient("P-42")
    print(f"{len(events)} Ereignisse für P-42")

    # Wer bestätigt was?
    pairs = store.find_by_relation("confirms")
    for evt_id, ref_id in pairs:
        print(f"  {store.get(evt_id).event_type} confirms {store.get(ref_id).event_type}")
```

### 7.2 Pattern-Mining auf Patientensequenzen

```python
from aion import TCFG

# Sequenzen aus der DB rekonstruieren (chronologisch nach t_start)
with SQLiteEventStore("clinical.db") as store:
    sequences = []
    for patient_id in ["P-42", "P-43", "P-44"]:
        events = store.find_by_patient(patient_id)
        sequences.append([e.event_type for e in events])

# Frequente Phasen finden
patterns = TCFG.mine_patterns(
    sequences,
    min_length=2, max_length=4,
    min_support=0.5,
)
for pattern, support in patterns.items():
    print(f"  [{support:.0%}]  {' → '.join(pattern)}")
```

### 7.3 Backdoor-Analyse

```python
from aion import CausalGraph, is_valid_backdoor_set

g = CausalGraph()
g.add_edge("Severity", "Treatment")
g.add_edge("Severity", "Outcome")
g.add_edge("Treatment", "Outcome")

# Heuristik (schnell, meist richtig)
heuristic_z = g.find_backdoor_adjustment_set("Treatment", "Outcome")
print(f"Heuristisches Z: {heuristic_z}")

# Formale Validierung (langsamer, garantiert korrekt)
report = is_valid_backdoor_set(g, "Treatment", "Outcome", heuristic_z)
print(report)  # ✅ Z = ['Severity'] für Treatment → Outcome
```

### 7.4 FHIR-Export und -Import

```python
from aion import TypeHierarchy
from aion.fhir import (
    to_fhir_bundle, from_fhir_bundle,
    bundle_to_file, bundle_from_file,
)

# 1. Hierarchie mit FHIR-Resource-Mapping
h = TypeHierarchy.from_yaml("schemas/clinical_base.yaml")

# 2. Events sammeln (z. B. aus SQLiteEventStore)
from aion import SQLiteEventStore
with SQLiteEventStore("clinical.db") as store:
    events = store.find_by_patient("P-42")

# 3. Export als FHIR-Bundle
bundle = to_fhir_bundle(events, type_hierarchy=h)
bundle_to_file(bundle, "P-42_export.json")

# 4. Reimport (z. B. von Synthea oder HAPI-FHIR-Server)
bundle = bundle_from_file("synthea_patient.json")
events = from_fhir_bundle(bundle)
# Nicht unterstützte Resourcen (Patient, Encounter) werden mit Warnung übersprungen.
```

**Round-Trip-Stabilität:** AION-spezifische Felder (typisierte Referenzen,
Konfidenzmaß, Aufenthalts-Periode) bleiben über Export → JSON → Import
erhalten. Sie werden als FHIR-Extensions mit eindeutigen System-URLs
gespeichert (siehe `aion.fhir.codes`).

### 7.5 Sensitivitätsanalyse mit DoWhy (ab 1.1.0)

AIONs Backdoor-Validierung beweist, dass ein Adjustment-Set
*identifizierend* ist. Sie sagt aber nichts darüber, wie *robust* die
geschätzte Effektgröße gegen unbeobachtete Confounder oder methodische
Wahl ist. Das macht DoWhy.

```python
from aion import CausalGraph, has_dowhy

if has_dowhy():
    from aion.dowhy import to_dowhy_model, estimate_ate, refute_estimate
    import pandas as pd

    # 1. AION-Graph (wie üblich)
    g = CausalGraph()
    g.add_edge("Z", "T"); g.add_edge("Z", "Y"); g.add_edge("T", "Y")

    # 2. DataFrame mit Spalten = Knoten-Namen
    df = pd.read_csv("studie.csv")  # Spalten: Z, T, Y

    # 3. DoWhy-Modell + Schätzung
    model = to_dowhy_model(g, df, treatment="T", outcome="Y")
    estimate = estimate_ate(model, "backdoor.linear_regression")
    print(f"ATE = {estimate.value}")

    # 4. Refutation: zufälliger Confounder darf Schätzung kaum verändern
    identified = model.identify_effect(proceed_when_unidentifiable=True)
    refutation = refute_estimate(model, identified, estimate, "random_common_cause")
    print(f"Original: {refutation.estimated_effect}, mit Random-CC: {refutation.new_effect}")
```

**Voraussetzung:** `pip install -e ".[dowhy]"` — zieht numpy, pandas,
scipy, networkx, scikit-learn, statsmodels (~200 MB). DoWhy bleibt
optional; AION-Core funktioniert ohne. Komplettes Beispiel in
`examples/dowhy_demo.py`.

**Verfügbare Refutation-Methoden:**

- `random_common_cause` — robust gegen unbekannte Confounder?
- `placebo_treatment_refuter` — fällt der Effekt auf 0, wenn das Treatment durch Zufall ersetzt wird?
- `data_subset_refuter` — bleibt der Effekt über Subsamples stabil?
- `add_unobserved_common_cause` — quantitative Sensitivitätsanalyse für Confounder bekannter Stärke

### 7.6 CLI-Werkzeug `aion` (ab 1.2.0)

Nach `pip install -e .` steht das Kommando `aion` zur Verfügung. Vollständig
scriptbar, ohne GUI-Abhängigkeit.

```bash
# Schema-Konsistenz prüfen
aion validate schemas/clinical_base.yaml

# Typhierarchie als Baum
aion types schemas/clinical_base.yaml

# FHIR-Bundle in DB importieren
aion import patients.json --db klinik.db

# DB-Statistik
aion stats klinik.db

# Pattern-Mining
aion mine klinik.db --min-support 0.3 --min-length 3

# DB als FHIR exportieren
aion export klinik.db --patient P-001 --out p001.json
```

**Alternative:** `python -m aion <subcommand>` — funktioniert ohne
`pip install`, direkt aus dem Quellverzeichnis.

**Exit-Codes** für Pipeline-Integration:
- `0` — Erfolg
- `1` — Fachlicher Fehler (Datei nicht gefunden, Validierung fehlgeschlagen)
- `2` — Ungültige Kommandozeilen-Argumente
- `130` — Mit Strg+C abgebrochen

### 7.7 Jupyter-Notebooks (ab 1.3.0)

Für statistische Workflows ist Jupyter oft die natürlichere Umgebung als
ein Skript oder die GUI. AION 1.3.0 bringt Helper für HTML-Rendering und
Plotting:

```python
from aion import TypeHierarchy, has_notebook
from aion.notebook import (
    display_hierarchy, display_events,
    plot_pattern_support, plot_causal_graph,
    sequences_from_store,
)

# 1. Hierarchie als HTML-Tabelle anzeigen
h = TypeHierarchy.from_yaml('schemas/clinical_base.yaml')
display_hierarchy(h)

# 2. Patientensequenzen aus DB → Pattern-Mining → Plot
from aion import SQLiteEventStore, TCFG

with SQLiteEventStore('klinik.db') as store:
    sequences = sequences_from_store(store)

patterns = TCFG.mine_patterns(sequences, min_support=0.3)
fig = plot_pattern_support(patterns, top=10)
fig  # Inline-Plot in Jupyter

# 3. Kausalgraph mit Backdoor-Visualisierung
from aion import CausalGraph

g = CausalGraph()
g.add_edge('Z', 'T'); g.add_edge('Z', 'Y'); g.add_edge('T', 'Y')
bs = g.find_backdoor_adjustment_set('T', 'Y')

plot_causal_graph(g, treatment='T', outcome='Y', backdoor_set=bs)
```

**Voraussetzung:** `pip install -e ".[notebook]"` — zieht jupyter,
ipython, matplotlib, networkx. Vollständiges Beispiel-Notebook unter
`examples/aion_jupyter_demo.ipynb`.

**Notebook-Pattern für eigene Demos:**

```bash
cd examples/
jupyter notebook aion_jupyter_demo.ipynb
```

Das Notebook wird ohne ausgeführte Outputs ausgeliefert (Best Practice
für Versionierung). Beim ersten Run erscheinen alle Plots.

### 7.8 Synthea-Import (ab 1.4.0)

[Synthea](https://github.com/synthetichealth/synthea) ist ein
Open-Source-Generator für synthetische Patientenverläufe als FHIR-
Bundles. AION 1.4.0 liest diese direkt ein:

```python
from aion import SQLiteEventStore
from aion.synthea import synthea_import_bundle, synthea_import_directory

# Eine Datei
events = synthea_import_bundle("output/fhir/Patient_Mary123.json")

# Ganzes Verzeichnis batch
events = synthea_import_directory("output/fhir/", limit=100)

# Mit eigenem Code-Mapping
extra = {
    "91302008": "Sepsis",          # SNOMED
    "73211009": "Diabetes",        # SNOMED
}
events = synthea_import_bundle(path, code_map=extra)

# Direkt in DB
with SQLiteEventStore("klinik.db") as store:
    store.add_many(events)
```

**Code-Mapping-Strategie (Lesart C):**

AION liefert ein **bewusst minimales** Default-Mapping mit. Eingebaut sind
nur Codes, die zwei Bedingungen erfüllen:

1. Eindeutige klinische Bedeutung (kein Spielraum für Fehlinterpretation)
2. Häufig in Synthea-Default-Output

Das umfasst etwa 13 LOINC-Codes (Vitalzeichen, häufige Labortests) und
12 SNOMED-Codes (Demografie, Encounter-Klassen).

**Was nicht eingebaut ist:**

- Spezifische Diagnose-Codes (Sepsis, Diabetes, …) — die brauchen
  klinische Validierung, die AION nicht ohne Domain-Experten leisten kann
- Medikamenten-Codes (RxNorm, ATC) — sehr kontextabhängig
- ICD-10-GM-Spezifika

**Fallback statt Verlust:** Codes ohne Mapping werden als
`FHIR_<ResourceType>` (z. B. `FHIR_Condition`) gespeichert, mit den
ursprünglichen Code-Angaben (`fhir_code`, `fhir_system`, `fhir_display`)
als Attributen. So gehen keine Daten verloren, und ein nachträgliches
Mapping ist möglich.

**CLI-Integration:**

```bash
aion import patients/ --synthea --db klinik.db --limit 100
aion stats klinik.db
aion mine klinik.db --min-support 0.3 --min-length 3
```

**Wichtig:** Das eingebaute Default-Mapping ist nicht klinisch
validiert. Vor produktivem Einsatz in einer Klinik sollte ein
Domain-Experte die Mappings in `aion.synthea.codes` prüfen.

### 7.9 Audit-Trail (ab 1.5.0)

DSGVO Art. 30 verlangt eine Dokumentation von Verarbeitungstätigkeiten
personenbezogener Daten. Das `aion.audit`-Modul deckt die technische
Säule davon ab.

```python
from aion import AuditLog, AuditAction

audit = AuditLog("/var/lib/aion/audit.db")

# Bei kritischen Operationen Audit-First-Pattern verwenden
audit.record(
    action=AuditAction.READ,
    user="dr.mueller",
    ip="10.0.1.42",
    resource_type="ClinicalEvent",
    resource_id=event.event_id,
    patient_id=event.patient_id,  # wird intern pseudonymisiert
    details="Visite",
)

# Auswertung
verdaechtige_logins = audit.query(
    action="login_failed",
    since=datetime(2026, 4, 1),
)

# Export für Compliance-Berichte
audit.export_csv("audit_2026-Q2.csv")
```

**Eigenschaften:**

- **Append-only auf DB-Ebene** — UPDATE/DELETE auf der Audit-Tabelle
  schlagen fehl (SQLite-Trigger). Audit-Einträge können nur eingefügt,
  nicht verändert werden.
- **Pseudonymisierte Patient-IDs** — der Audit-Log enthält nie
  Klartext-Patient-IDs. Suche per Klartext-ID erfolgt via Hash-Lookup,
  Reidentifikation aus dem Audit-Log allein ist nicht möglich.
- **Eigene SQLite-Datei** — getrennt von der Patient-DB, damit Audit
  unabhängig gesichert/exportiert werden kann.

### 7.10 Konfigurations-Schicht (ab 1.6.0)

Statt Settings über env-vars zu verstreuen, gibt es ab 1.6.0 eine
zentrale YAML-Konfiguration.

```python
from aion import AionConfig, get_config, load_config, set_config

# Aus Datei laden (mit env-Substitution und Validierung)
cfg = load_config("aion-prod.yaml")
print(cfg.storage.database)
print(cfg.logging.level)

# Globalen Singleton überschreiben (z. B. in Tests)
set_config(cfg)

# Aus dem Anwendungscode darauf zugreifen
cfg = get_config()
audit = AuditLog(cfg.storage.audit)
```

**YAML-Beispiel** (`aion-prod.yaml`):

```yaml
storage:
  database: /var/lib/aion/aion.db
  audit: /var/lib/aion/audit.db

privacy:
  salt: ${AION_PRIVACY_SALT}      # aus env zur Laufzeit
  audit_retention_days: 3650

logging:
  level: INFO
  format: json

auth:
  backend: ldap
  ldap_server: ldaps://ldap.klinik.de
  ldap_base_dn: ou=people,dc=klinik,dc=de
```

**env-Substitution:** `${VAR}` und `${VAR:-default}` werden beim Laden
ersetzt. Damit landen Secrets nicht im YAML, sondern werden zur
Laufzeit injiziert.

**CLI-Befehle:**

```bash
# Konfiguration validieren ohne sie zu nutzen
aion config validate aion-prod.yaml

# Aktive Konfiguration anzeigen (Defaults oder geladen)
aion config show
aion config show aion-prod.yaml
```

**Standard-Suchreihenfolge:**

1. Argument an `load_config(path)`
2. `$AION_CONFIG_FILE` Umgebungsvariable
3. Defaults (alle Felder auf Default-Werten)

**Hinweis:** In 1.6.0 ist die Schicht bereitgestellt, aber existierende
Module (FHIR, Synthea, Audit) konsumieren die Config noch nicht
zwingend. Vollständige Integration kommt in 1.7.0 mit der
PostgreSQL-Anbindung.

### 7.11 Storage-Abstraction (ab 1.7.0)

Statt `SQLiteEventStore` direkt zu instanziieren, kann ab 1.7.0 die
Factory genutzt werden, die anhand der Konfiguration das passende
Backend wählt:

```python
from aion import create_event_store, AionConfig
from aion.config import StorageConfig

# Aus Default-Config (SQLite mit Default-Pfad)
with create_event_store() as store:
    print(store.count())

# Aus expliziter Config
cfg = AionConfig(storage=StorageConfig(database="/var/lib/aion/aion.db"))
with create_event_store(cfg) as store:
    ...

# Mit Override (z. B. für Tests)
with create_event_store(cfg, database=":memory:") as store:
    ...
```

**Backend-Auswahl** anhand des Database-Strings:

| String | Backend |
|---|---|
| `:memory:` | SQLite (in-Memory) |
| `/pfad/zur/datei.db` | SQLite |
| `postgresql://user:pass@host/db` | PostgreSQLEventStore (Stub in 1.7.0) |

**EventStore als Protocol:** Die Abstraktion ist als
`typing.Protocol` mit `@runtime_checkable` implementiert. Wer eigene
Backends bauen will, muss nicht von einer Klasse erben — es reicht,
die richtigen Methoden mit den richtigen Signaturen zu haben:

```python
from aion.persistence.store import EventStore

# Strukturelle Konformität
store = SQLiteEventStore(":memory:")
assert isinstance(store, EventStore)
```

**PostgreSQL-Stub:** In 1.7.0 wirft `PostgreSQLEventStore` bei jedem
Methoden-Aufruf `NotImplementedError` mit klarer Botschaft. Volle
Anbindung folgt in 1.8.0.

### 7.12 HL7-v2-Datei-Import (ab 1.8.0)

Der größte Teil deutscher Krankenhausinformationssysteme spricht
**HL7 v2.5/2.7**, nicht FHIR. Das ist Pipe-delimited Text:

```
MSH|^~\&|KIS|KLINIK|AION|RZ|20260415083000||ADT^A01|MSG00001|P|2.5
EVN|A01|20260415083000
PID|1||P-12345||Mustermann^Max||19650315|M
PV1|1|I|3A^301^1|...|||V|...|20260415083000
```

Seit AION 1.8.0 importiert AION solche Nachrichten direkt:

```python
from aion import SQLiteEventStore
from aion.hl7v2 import (
    hl7v2_import_file,
    hl7v2_import_directory,
    hl7v2_import_string,
)

# Eine Datei (eine oder mehrere Nachrichten in einer Datei sind ok)
events = hl7v2_import_file("kis-export.hl7")

# Ganzes Verzeichnis
events = hl7v2_import_directory("/var/hl7-export/", limit=1000)

# Mit eigenem Code-Mapping
extra = {
    "A01": "Notaufnahme_Spezial",     # ADT-Trigger
    "1234-5": "Mein_Lab_Test",        # LOINC
}
events = hl7v2_import_file("kis-export.hl7", code_map=extra)

# Direkt in DB
with SQLiteEventStore("klinik.db") as store:
    store.add_many(events)
```

**Code-Mapping-Strategie (Lesart C, identisch mit Synthea):**

AION liefert ein bewusst minimales Default-Mapping mit:

- **11 ADT-Trigger** (A01-A13: Aufnahme, Verlegung, Entlassung,
  Patient-Update, Storno-Operationen)
- **18 LOINC-Codes** für Vitalzeichen und häufige Labortests
  (Herzfrequenz, Blutdruck, Hämoglobin, Glucose, Kreatinin etc.)

**Was nicht eingebaut ist:**

- ICD-10-Diagnosen — brauchen klinische Validierung
- OPS-Codes (Prozeduren) — sehr lokal, hauseigene Subcodes
- Medikamenten-Codes (RxNorm, ATC, PZN) — kontextabhängig

**Fallback statt Verlust:** Codes ohne Mapping werden zu
`HL7_<MessageType>_<Trigger>` (z. B. `HL7_ADT_A99` oder `HL7_ORU_R01`),
mit den Original-Werten in den Attributen. So gehen keine Daten
verloren.

**CLI-Integration:**

```bash
# Eine Datei
aion import patient_001.hl7 --hl7v2 --db klinik.db

# Verzeichnis-Batch mit Limit
aion import /var/hl7-export/ --hl7v2 --limit 1000 --db klinik.db

aion stats klinik.db
aion mine klinik.db --min-support 0.3
```

**Eigenschaften:**

- **Stdlib-only Parser** — keine externe Dependency wie `hl7apy`.
  Encoding-Zeichen werden aus MSH-1/MSH-2 gelesen (nicht hardcoded auf
  `|^~\&`).
- **Multi-Message-Dateien** — eine `.hl7`-Datei kann mehrere Nachrichten
  enthalten, jede neue MSH-Zeile beginnt eine neue.
- **Stay-Period aus PV1** — Aufnahme-Datum (PV1-44) und Entlassung
  (PV1-45) werden korrekt zu `stay_start`/`stay_end` gemappt.

**Wichtig:** Das eingebaute Default-Mapping ist nicht klinisch
validiert. Vor produktivem Einsatz in einer Klinik sollte ein
Domain-Experte die Mappings in `aion.hl7v2.codes` prüfen.

**Nicht enthalten in 1.8.0:**

- MLLP-Live-Listener (TCP-Socket-basiert) — geplant für 1.9.0
- Encoding ISO-8859-1 / Windows-1252 — wird beim ersten echten
  KIS-Datensatz nachgezogen
- ACK-Antworten an Sender — Teil der MLLP-Schicht

### 7.13 MLLP-Live-Listener (ab 1.9.0)

Mit 1.9.0 schließt AION die HL7-v2-Anbindung ab. Statt nur Dateien aus
einem Verzeichnis zu importieren, kann AION jetzt **direkt vom KIS oder
von Mirth Connect** Nachrichten per TCP empfangen — das ist der
übliche Klinik-Standard.

**Architektur:**

```
       KIS/Mirth ──TCP──→ AION-MLLP-Listener (port 2575) ──→ EventStore
                                       │
                                       └──→ ACK an Sender
                                       │
                                       └──→ Audit-Log
```

**CLI-Aufruf für lokale Tests:**

```bash
aion mllp-listen --host 0.0.0.0 --port 2575 \
                 --db /var/lib/aion-stack/aion-data/aion.db \
                 --audit /var/lib/aion-stack/aion-data/audit.db
```

Der Befehl blockt bis Strg+C. Pro eingehende Verbindung wird ein
Thread gestartet, mehrere Sender können gleichzeitig pushen.

**Programmatischer Einsatz:**

```python
from aion import create_event_store, AuditLog
from aion.hl7v2.mllp import serve_mllp

audit = AuditLog("audit.db")
with create_event_store() as store:
    serve_mllp(
        host="0.0.0.0",
        port=2575,
        store=store,
        audit=audit,
        block=True,    # Default: blockt bis Strg+C
    )
```

**Custom-Handler für eigene Verarbeitungs-Logik:**

```python
from aion.hl7v2.mllp import MLLPServer, MLLPHandler

class MyHandler:
    def handle(self, msg, raw):
        print(f"Empfangen: {msg.message_type}^{msg.trigger_event}")
        return "AA"   # oder "AE" / "AR"

server = MLLPServer(("0.0.0.0", 2575), handler=MyHandler())
server.serve_forever()
```

**ACK-Verhalten:**

| Situation | ACK-Code |
|---|---|
| Nachricht erfolgreich gespeichert | `AA` Application Accept |
| Syntaktisch ok, aber kein Patient/Zeit (Daten irrelevant für AION) | `AA` |
| Mapping- oder Store-Fehler | `AE` Application Error |
| Nachricht nicht parsbar (kein MSH, kaputt) | kein ACK, Verbindung wird beendet |

Der Sender (KIS) entscheidet bei `AE` selbst, ob er retransmittiert
oder den Fehler an seinen Operator meldet.

**Production-Deployment via systemd:**

Die mitgelieferte `systemd/aion-mllp.service` startet den Listener als
Systemdienst mit Sicherheits-Härtung:

```bash
sudo cp systemd/aion-mllp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aion-mllp.service
sudo systemctl status aion-mllp.service
journalctl -u aion-mllp.service -f
```

Die Service-Datei nutzt:

- `User=aion-admin`, kein Root-Zugriff
- `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=read-only`
- `RestrictAddressFamilies=AF_INET AF_INET6`
- `MemoryMax=2G`, `LimitNOFILE=4096`
- `Restart=on-failure` mit Backoff (max 5x in 60s)

**Test mit Mirth Connect:**

In Mirth einen Channel mit:
- Source: TCP Listener auf Port X (egal)
- Destination: TCP Sender → `aion-server:2575`
- Outbound Protocol: HL7 v2.x über MLLP
- ACK Mode: Process from Connector (damit Mirth die AION-ACKs
  korrekt verarbeitet)

**Was 1.9.0 *nicht* abdeckt:**

- TLS für die MLLP-Verbindung — gemäß HL7-Standard meist Klartext im
  internen Klinik-Netz, für externe Übertragung über Stunnel oder
  VPN-Tunnel realisieren
- Authentifizierung des Senders — kommt mit `aion.auth` in 1.10.0
- Retry-Persistenz bei DB-Ausfall — Nachrichten werden bei
  Store-Fehler mit AE quittiert, aber nicht in eine Dead-Letter-Queue
  geschrieben
- Live-Test gegen echtes KIS oder Mirth Connect — Tests laufen nur
  gegen synthetische Loopback-Clients

### 7.14 Auth-Backend-System (ab 1.10.0)

Ab 1.10.0 hat AION eine pluggable Auth-Schicht. Vier Backends:

| Backend | Wofür | Status |
|---|---|---|
| **none** | Default, keine Authentifizierung — für Dev/Lokal | ✅ vollständig |
| **apikey** | Service-zu-Service (Mirth → AION) | ✅ vollständig |
| **ldap** | Active Directory / LDAP, für interaktive User | ⚠ Live-Test ausstehend |
| **oidc** | OAuth2/OIDC, für Telekom-IDP oder Keycloak | ⚠ Live-Test ausstehend |

**Wo Auth in 1.10.0 greift:**

- ✅ MLLP-Listener (Mirth → AION)
- ❌ CLI und GUI (OS-User-Permissions reichen)
- ⏳ REST-API (gibt es noch nicht — bekommt Auth wenn es kommt)

#### API-Key-Backend (vollständig)

Erzeugen und in YAML-Datei einbauen:

```bash
# Schritt 1: Key erzeugen (gibt Klartext und Hash aus)
aion auth keygen --name mirth-channel-1 --roles ingest --expires 2027-12-31
```

Die Ausgabe enthält:
- **Klartext-Key** für den Sender (Mirth-Channel-Konfig oder env-Var)
- **YAML-Eintrag** mit gehashten Werten für `/etc/aion/api-keys.yaml`

Beispiel für die Key-Datei:

```yaml
keys:
  - name: mirth-channel-1
    hash: blake2b$1f048d05.../20fe61f6...
    roles: [ingest]
    expires: 2027-12-31
  - name: monitoring
    hash: blake2b$abc123.../def456...
    roles: [readonly]
```

**Wichtig:**
- Klartext-Keys nie in Git, Backups oder unverschlüsselte Dateien
- `/etc/aion/api-keys.yaml` mit `chmod 640` und Owner `root:aion-admin`
- Keys mit Ablaufdatum versehen (Best Practice: 1-2 Jahre)
- Hot-Reload: `backend.reload()` ohne Service-Neustart möglich

#### MLLP mit Auth aktivieren

Im CLI:

```bash
aion mllp-listen --auth-keys /etc/aion/api-keys.yaml \
                 --auth-role ingest \
                 --port 2575 \
                 --db /var/lib/aion-stack/aion-data/aion.db \
                 --audit /var/lib/aion-stack/aion-data/audit.db
```

Programmatisch:

```python
from aion import create_event_store, AuditLog
from aion.auth import APIKeyBackend
from aion.hl7v2.mllp import serve_mllp

with create_event_store() as store:
    audit = AuditLog("audit.db")
    auth = APIKeyBackend("/etc/aion/api-keys.yaml")
    serve_mllp(store=store, audit=audit,
               auth_backend=auth, required_role="ingest")
```

**API-Key in HL7-Nachricht:** AION erwartet den Key in **MSH-4 (Sending
Facility)**. Beispiel:

```
MSH|^~\&|KIS|aion_J7K9X2BFCE...|AION|RZ|20260430120000||ADT^A01|MSG-001|P|2.5
                ^^^^^^^^^^^^^^
                hier der API-Key
```

In Mirth Connect setzt man das im Channel-Source unter Outbound
Properties:
- Sending Facility: `aion_J7K9X2BFCE...`

#### Audit-Verhalten mit Auth

- **Erfolgreiche Auth:** Audit-User ist `mllp:<principal-name>` (z. B.
  `mllp:mirth-channel-1`), nicht der MSH-3-Header
- **Fehlgeschlagene Auth:** Audit-Eintrag mit `success=False`,
  `details=auth-failed/auth-missing/auth-no-role`
- **Fehlende Rolle:** wie fehlgeschlagene Auth, mit `details=auth-no-role`

#### Verify-Befehl (zum Testen)

```bash
aion auth verify --keyfile /etc/aion/api-keys.yaml --key aion_J7K9X2...
# Oder interaktiv (kein Echo):
aion auth verify --keyfile /etc/aion/api-keys.yaml
```

#### LDAP-Backend (Optional-Dependency)

Installation:
```bash
pip install -e ".[ldap]"
```

Konfiguration in `/etc/aion/aion.yaml`:

```yaml
auth:
  backend: ldap
  ldap_server: ldaps://ad.klinik.local
  ldap_use_ssl: true
  ldap_bind_dn_template: "${user}@klinik.local"  # UPN
  # Oder klassischer DN:
  # ldap_bind_dn_template: "cn=${user},ou=users,dc=klinik,dc=local"
  ldap_search_base: "dc=klinik,dc=local"
  ldap_group_filter: "(member=cn=${user},ou=users,dc=klinik,dc=local)"
  ldap_role_mapping:
    AION-Admins: admin
    AION-Aerzte: physician
    AION-Pflege: nurse
```

**Häufige Stolpersteine** (beim ersten Echt-Test zu erwarten):
- UPN vs. sAMAccountName (`alice@klinik.local` vs. `alice`)
- Referrals bei Multi-Forest-AD
- NTLM/Kerberos statt Simple Bind
- Server-Side-Limits für Suchergebnisse

#### OIDC-Backend (Optional-Dependency)

Installation:
```bash
pip install -e ".[oidc]"
```

Konfiguration:

```yaml
auth:
  backend: oidc
  oidc_issuer: "https://idp.telekom.healthcare/realms/aion"
  oidc_audience: "aion-clinical"
  oidc_roles_claim: "realm_access.roles"
  oidc_user_id_claim: "preferred_username"
  oidc_jwks_cache_ttl: 3600
  oidc_leeway: 30
```

JWKS-URI wird automatisch aus dem `.well-known/openid-configuration`
geholt. JWT-Validierung mit Signatur-Check, Issuer-Validation,
exp/nbf/iat-Check.

**Häufige Stolpersteine:**
- Audience-Format (string vs. array in `aud`-Claim)
- Custom-Claims-Pfade — `roles_claim: "realm_access.roles"` ist
  Keycloak-typisch, andere IDPs liegen anders
- Clock-Skew zwischen IDP und AION (`oidc_leeway` erhöhen)
- Token-Lifetime — kurze Tokens brauchen Refresh-Strategie im Client

---

## 8. Häufige Probleme

### „ModuleNotFoundError: No module named 'aion'"

venv nicht aktiviert oder `pip install -e .` nicht ausgeführt.

```bash
# Prüfen
which python
# Sollte auf venv/bin/python zeigen

# Wenn nicht: aktivieren
source venv/bin/activate

# Wenn doch, aber Modul fehlt:
pip install -e .
```

### „ModuleNotFoundError: No module named 'PySide6'" beim Start von `aion-gui`

Die GUI-Extra ist nicht installiert.

```bash
pip install -e ".[gui]"
```

### „ImportError: z3-solver ist nicht installiert"

Du nutzt das Z3-Plugin, ohne `[verify]` installiert zu haben.

```bash
pip install -e ".[verify]"
```

### GUI startet nicht — „qt.qpa.plugin: Could not load the Qt platform plugin"

Auf headless-Linux-Servern ohne Display. Die GUI braucht einen
Display-Server. Lösungen:

- Lokal: GUI-Workstation mit X11/Wayland nutzen
- Remote: SSH mit X-Forwarding (`ssh -X`)
- Container: `xvfb-run aion-gui` (nur für headless Tests sinnvoll)

### „PRAGMA journal_mode = WAL" Fehler

Tritt auf, wenn die DB-Datei auf einem Netzlaufwerk liegt. Lösung:
DB lokal ablegen, oder WAL deaktivieren:

```python
store = SQLiteEventStore("path/to/db", wal=False)
```

### Tests schlagen wegen YAML fehl

```
ImportError: PyYAML wird zum Lesen von YAML-Schemata benötigt
```

PyYAML ist Pflicht-Abhängigkeit, sollte mit `pip install -e .` automatisch
gezogen werden. Manuell:

```bash
pip install PyYAML
```

### „Schema-Editor zeigt PyYAML fehlt"

Gleiche Ursache wie oben — `pip install PyYAML` (oder kompletten
Install-Schritt wiederholen).

### venv-Pfade auf Windows

PowerShell verbietet Skript-Ausführung standardmäßig. Einmalig
freigeben:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

dann erneut `venv\Scripts\Activate.ps1`.

---

## 9. Production Deployment (ab 1.5.0)

Für Klinik-Einsatz oder Pilot-Phasen liefert AION ab 1.5.0 ein
Dockerfile und ein docker-compose.yml mit.

### 9.1 Container bauen

```bash
docker build -t aion-clinical:1.5.0 .
```

Resultat: ca. 180 MB Image basierend auf `python:3.12-slim-bookworm`.
Multi-stage Build, läuft als non-root User (uid 10001), enthält keine
Shell-Werkzeuge, alle Capabilities gedroppt.

### 9.2 Mit docker-compose starten

```bash
docker compose up -d
docker compose logs -f
docker compose exec aion aion --version
```

Persistente Volumes:
- `aion-data`: Patient-Datenbank
- `aion-audit`: Audit-Log (separat, damit unabhängig sicherbar)

### 9.3 Sicherheits-Härtung

Der Default-Container ist auf Sicherheit getrimmt:

- `read_only: true` — Container-Filesystem ist read-only
- `tmpfs:/tmp` — temporäre Schreibzugriffe gehen in RAM
- `cap_drop: ALL` — keine Linux-Capabilities
- `security_opt: no-new-privileges` — kein Rechte-Eskalation
- Resource-Limits: 1 GB RAM, 1 CPU (anpassbar)

### 9.4 Was Production NICHT abdeckt

**Wichtig zu wissen:** Die Container-Bereitstellung macht AION nicht
zu einem Medizinprodukt. Für echten Klinik-Einsatz fehlt weiterhin:

- **MDR-Zertifizierung** als Medizinprodukt nach EU-Verordnung 2017/745
- **ISO 13485** Qualitätsmanagement-System für Hersteller
- **IEC 62304** Software-Lebenszyklus-Prozesse
- **Klinische Validierung** durch ärztlichen Studienleiter
- **Authentifizierung** (geplant für 1.6.0 — aktuell keine Auth)
- **REST-API** als Long-Running-Service (geplant für 1.7.0)

Diese Aspekte sind je nach Einsatz-Szenario (Decision-Support vs.
autonomes Medizinprodukt) unterschiedlich relevant. Bei einer
Hosting-Partnerschaft mit zertifiziertem Provider übernimmt der
Provider die Hosting-Compliance (ISO 27001, BSI C5,
KRITIS-Krankenhaus-Anforderungen); MDR-Zertifizierung bleibt aber
Hersteller-Verantwortung.

---

## Anhang A: Pakete und Lizenzen

### AION Clinical selbst

**Lizenz:** Dual-License — AGPL-3.0-only (Open Source) + Kommerzielle Lizenz

Copyright © 2026 Friedhelm Matten / ISCaD GmbH, 30900 Wedemark, Germany.
Kontakt für kommerzielle Lizenz: licensing@iscad-it.de

Source-Dateien tragen SPDX-Header gemäß REUSE-Standard:

```
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

Vollständiger AGPL-3.0-Text in `LICENSE`. Hinweise zu
Drittkomponenten und Trademark in `NOTICE`.

### Drittkomponenten (zur Laufzeit)

| Paket | Version | Lizenz | Verwendung |
|---|---|---|---|
| Python stdlib | 3.10+ | PSF | Kern, sqlite3, socketserver, hashlib, secrets |
| PyYAML | ≥ 6.0 | MIT | Schema-Import, Config, API-Keys |
| PySide6 | ≥ 6.5 | LGPL-3.0 | GUI-Toolkit (optional) |
| z3-solver | ≥ 4.12 | MIT | SMT-Verifikation (optional) |
| fhir.resources | ≥ 7.0 | BSD-3 | FHIR-Mapper (optional) |
| dowhy | ≥ 0.11 | MIT | Sensitivitätsanalyse (optional) |
| jupyter, matplotlib, networkx | div. | BSD/PSF | Notebook-Integration (optional) |
| ldap3 | ≥ 2.9 | LGPL-3.0 | LDAP/AD-Backend (optional) |
| authlib, requests | ≥ 1.3 / ≥ 2.31 | BSD-3 / Apache-2.0 | OIDC-Backend (optional) |
| pytest, ruff, mypy | div. | MIT/Apache | Entwicklung (dev) |

LGPL ist für kommerzielle Weitergabe **unbedenklich**, solange die
LGPL-Komponente dynamisch gelinkt bleibt — was beim normalen
`pip install`-Setup automatisch der Fall ist.

### EUPL-Kompatibilität

EUPL-1.2 ist mit folgenden Lizenzen explizit kompatibel (Anhang der
Lizenz): GPL v2/v3, AGPLv3, LGPL v2.1/v3, MPL v2, EPL v1, OSL,
CeCILL, CC-BY-SA 3.0 (für Doku) und EUPL v1.1.

Praktisch heißt das: AION-Code darf mit Bibliotheken aus diesen
Lizenz-Familien kombiniert werden, ohne Lizenz-Konflikt. MIT- und
BSD-Bibliotheken sind ohnehin uneingeschränkt nutzbar
(permissive Lizenzen).

## Anhang B: Versionsstand & Test-Status

- **Version: 1.10.1 (April 2026)
- **Tests:** 364 grün, 2 skipped
- **Phase-A-Erweiterungen** (seit 0.3.0):
  - typisierte Referenzen `ρ : E → R` mit Vokabular `EventRelation`
  - TCFG Pattern-Mining (Apriori-artig, Klinische-Phasen-Erkennung)
  - `aion.verify` — Multi-Inheritance-Konsistenz, d-Separation,
    formale Backdoor-Validierung; optionales Z3-SMT-Plugin
- **FHIR-Anbindung** (seit 0.4.0):
  - `aion.fhir` — Round-Trip-Mapper für Observation, Condition,
    MedicationAdministration, Procedure
  - Bundle-IO mit JSON-Persistenz, FHIR-Validator-tauglich
- **Production-Readiness** (seit 1.0.0):
  - `aion.core.privacy` — Log-Pseudonymisierung
  - Migrations-Pfad für DBs aus 0.2.x bis 1.0.0 verifiziert
  - API-Stabilitäts-Versprechen (siehe Anhang D)
- **Sensitivitätsanalyse** (seit 1.1.0):
  - `aion.dowhy` — Bridge zu DoWhy für Refutation-Tests und Effekt-
    Schätzung mit verschiedenen Methoden
- **CLI-Werkzeug** (seit 1.2.0):
  - `aion` — sechs Subcommands: validate, types, stats, mine, import, export
  - vollständig scriptbar ohne GUI-Abhängigkeit
- **Jupyter-Integration** (seit 1.3.0):
  - `aion.notebook` — HTML-Tabellen für Hierarchien & Ereignisse,
    Plot-Funktionen für Patterns & Kausalgraphen
  - Demo-Notebook unter `examples/aion_jupyter_demo.ipynb`
- **Synthea-Importer** (seit 1.4.0):
  - `aion.synthea` — Standard-Synthea-FHIR-Bundles importieren
  - Default-Code-Mapping für ~25 unstrittige LOINC/SNOMED-Codes
  - Anwender-Mapping per `code_map=...` erweiterbar
  - CLI: `aion import --synthea <bundle-or-dir>`
- **Production-Vorbereitung** (seit 1.5.0):
  - `aion.audit` — append-only Audit-Trail (DSGVO-Art. 30)
  - SQLite-Trigger erzwingen append-only: UPDATE/DELETE verboten
  - Dockerfile mit non-root user, read-only filesystem, ressourcen-limitiert
  - docker-compose.yml für Production-Deployment
- **Konfigurations-Schicht** (seit 1.6.0):
  - `aion.config` — zentrale Settings via YAML
  - env-var-Substitution `${VAR}` und `${VAR:-default}`
  - CLI: `aion config validate`, `aion config show`
  - Validierung beim Laden, sammelt alle Fehler
- **Storage-Abstraction** (seit 1.7.0):
  - `EventStore`-Protocol als abstraktes Interface
  - `create_event_store(cfg)` als Factory mit automatischer
    Backend-Auswahl (SQLite vs. PostgreSQL)
  - `PostgreSQLEventStore` als Stub — Implementation in 1.8.0
- **HL7-v2-Datei-Import** (seit 1.8.0):
  - `aion.hl7v2` — stdlib-only Parser für HL7 v2.x Nachrichten
  - ADT (Aufnahme/Verlegung/Entlassung) und ORU (Befunde) gemappt
  - Default-Mapping für 11 ADT-Trigger und 18 LOINC-Codes
  - CLI: `aion import --hl7v2 <file-or-dir>`
- **MLLP-Live-Listener** (seit 1.9.0):
  - `aion.hl7v2.mllp` — TCP-Server für HL7-v2 über MLLP
  - ThreadingTCPServer, ein Thread pro Verbindung, stdlib-only
  - HL7-konforme ACK-Antworten (AA/AE/AR) mit Sender-Spiegelung
  - CLI: `aion mllp-listen --host 0.0.0.0 --port 2575 --db ... --audit ...`
  - systemd-Unit-Datei mit Härtung mitgeliefert
- **Auth-Backend-System** (seit 1.10.0):
  - `aion.auth` — pluggable Backends: None, API-Key, LDAP, OIDC
  - `AuthBackend`-Protocol als abstraktes Interface
  - API-Key-Backend vollständig (gehashte Keys, Rollen, Ablaufdatum)
  - LDAP/OIDC als optional-Backends mit Live-Test-Hinweis
  - MLLP-Integration: API-Key in MSH-4, required_role-Check
  - CLI: `aion auth keygen`, `aion auth verify`
- **Geplant für 1.11.0:** Plausibilitäts-Layer (Wertebereiche, Einheiten)
- **Roadmap Klinik-Produkt:** MDR-Zertifizierung, klinische
  Validierung — Partnerschaft mit zertifiziertem Hosting-Provider

## Anhang C: Wo bekomme ich Hilfe?

- **Bug-Reports:** im Tracker des Projekts (siehe `pyproject.toml`)
- **Mathematische Grundlagen:** AION_v1.0-PDF (Typ-Hierarchie, Allen,
  Causal, TCFG)
- **PySide6-Fragen:** [doc.qt.io/qtforpython](https://doc.qt.io/qtforpython/)
- **Z3-Fragen:** [microsoft.github.io/z3guide](https://microsoft.github.io/z3guide/)

---

## Anhang D: API-Stabilität (ab 1.0.0)

AION Clinical 1.0.0 garantiert Stabilität für die **öffentliche API**.
Was darunter zu verstehen ist:

### Stabil — bleibt erhalten in 1.x.y

Alles, was direkt aus `aion` importierbar ist:

```python
from aion import (
    TypeHierarchy, TypeNode, TypeHierarchyError,
    ClinicalEvent,
    EventRelation, is_valid_relation, inverse_of,
    AllenInterval, FuzzyAllenInterval, ALLEN_RELATIONS,
    CausalGraph,
    TCFG, TCFGResult,
    TypeBuilder, aion_type, AION_REGISTRY,
    SQLiteEventStore,
    setup_logging, get_logger,
    pseudonymize, safe_path, fingerprint_dict,
    check_inheritance_conflicts, check_required_attributes,
    d_separates, is_valid_backdoor_set, has_z3, has_fhir, has_dowhy,
)
```

Diese Symbole, ihre Signaturen und ihre Hauptverhalten bleiben über
alle 1.x-Versionen kompatibel. Erweiterungen (neue Parameter mit
Default-Werten, neue Methoden) sind erlaubt, Änderungen am Vertrag
nicht.

### Internal — kann sich ändern

Submodule unterhalb der Public API:

- `aion.core.*` — interne Implementierung, Refactoring jederzeit möglich
- `aion.gui.*` — GUI-Aufbau, Tab-Klassen, Layout-Details
- `aion.fhir.*` (außer `to_fhir`/`from_fhir`/Bundle-Top-Level) — interne Mapper
- `aion.verify.z3_plugin` — Plugin-Implementation
- `aion.persistence.sqlite_store._SCHEMA` — DB-Schema (Migration übernimmt
  die Anpassung, Anwendungscode soll nicht direkt darauf zugreifen)

Wer sich in solche Module einklinkt, riskiert beim Update auf 1.x.(y+1)
Brüche. Empfehlung: nur via `import aion` arbeiten.

### Versionierung

- **Patch-Bumps (1.0.x):** Bug-Fixes, keine API-Änderungen.
- **Minor-Bumps (1.x.0):** neue Features, abwärtskompatibel.
- **Major-Bumps (2.0.0):** API-Brüche möglich. Würden mit mindestens
  6 Monaten Vorlauf in einem `MIGRATION.md` angekündigt.

### Datenbank-Kompatibilität

Datenbanken aus aion-clinical >= 0.3.0 öffnen sich automatisch in 1.0.0
und werden bei Bedarf migriert. Alte 0.2.x-Datenbanken (ohne
`relation`-Spalte) werden ebenfalls migriert; siehe Migrations-Tests in
`tests/test_migration.py`.

### Datenschutz-Versprechen für Logs

Ab 1.0.0 enthalten Logs (`~/.aion/aion-gui.log` und alle stderr-Ausgaben
über das `aion.log`-Modul):

- **keine Klartext-Patient-IDs** — diese werden via `pseudonymize()` gehasht
- **keine vollen Datei-Pfade** — diese werden via `safe_path()` auf den
  Basisnamen reduziert
- **keine Werte aus `attributes`-Dicts** — falls geloggt, nur via
  `fingerprint_dict()` als Schlüssel-Liste

Wer eigenes Logging hinzufügt, sollte dieselben Helfer verwenden.

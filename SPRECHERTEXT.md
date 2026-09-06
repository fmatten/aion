# Sprechertext — AION Clinical Vorführung

**Slot:** 20–30 Minuten · **Publikum:** gemischt · **Highlight:** TCFG Pattern-Mining

---

## Vorbereitung (5 Min vor Beginn)

- [ ] Laptop am Beamer, Auflösung getestet, Schrift gut lesbar
- [ ] Zwei Terminal-Tabs offen:
  - **Tab 1:** im Projekt-Ordner mit aktiviertem `venv`, Schriftgröße 14–16pt
  - **Tab 2:** für GUI-Start
- [ ] `python tools/smoke_gui.py` einmal laufen lassen → muss grün sein
- [ ] `python tools/verify_handbook.py` → muss grün sein
- [ ] `aion-gui` einmal starten und schließen, damit Qt-Caches warm sind
- [ ] Wasser griffbereit
- [ ] Telefon stumm

---

## 0. Aufwärmen (1 Min)

> Guten Tag. Ich zeige Ihnen heute AION Clinical — ein System zur formalen
> Repräsentation klinischer Verläufe. Zwanzig Minuten, vier Akte, eine
> Live-Demo. Am Ende gerne Fragen.

**Folie 1 — Titelfolie**, oder einfach ein leeres Terminal mit großem Prompt.

---

## 1. Das Problem (2 Min)

> In der Klinik fallen pro Patient hunderte Ereignisse an: Diagnosen,
> Messungen, Medikationen, Prozeduren. Die meisten Systeme speichern das
> als flache Tabelle mit Zeitstempel — aber die *Bedeutung* der Beziehungen
> zwischen Ereignissen geht verloren.
>
> Eine Laktatmessung von 4,2 mmol/l neben einer Sepsis-Diagnose — bestätigt
> die Messung die Diagnose? Oder schließt sie eine andere aus? Eine
> Antibiotikagabe nach der Diagnose — ist sie eine Reaktion darauf, oder
> Routine? Ein flaches Schema kann das nicht beantworten.
>
> AION macht diese Beziehungen explizit und nutzt sie für drei Dinge:
> Wissensorganisation, automatisches Lernen klinischer Phasen, und
> kausale Inferenz.

**Folie 2 — Konzeptbild:** flache Liste vs. Knowledge-Graph (handgezeichnet
oder schematisch — wichtig ist nur, dass der Unterschied sofort sichtbar ist).

---

## 2. Akt 1 — Knowledge-Graph (4 Min)

> Lassen Sie mich das konkret zeigen.

**→ Tab 1: `python vorfuehrung.py` starten**

Enter, Enter — wir sehen die ersten Patienten.

> Drei Patienten, je fünf Ereignisse. Wichtig sind die Beziehungen
> zwischen ihnen: `confirms`, `response_to`, `observation_of`. Das sind
> *getypte* Kanten in einem Wissensgraphen.
>
> Eine technische Note: das Vokabular ist ein einfaches Set von
> Strings, plus ein paar Konstanten in `EventRelation`. Domain-Experten
> können eigene Beziehungstypen ergänzen, ohne dass am Code etwas geändert
> werden muss.

Enter — die Abfragen kommen.

> Wir können den Graphen in beide Richtungen abfragen. „Welche Messungen
> bestätigen welche Diagnosen?" Das ist eine SQL-Query unter der Haube,
> aber für den Anwender ist es eine semantische Frage.

**Tipp:** Wenn jemand fragt „warum nicht Neo4j?" — die Antwort:
„Wir haben hier nur SQLite. Keine zusätzliche Server-Infrastruktur,
funktioniert auf jedem Klinik-Laptop. Für unseren Skalenbereich ausreichend."

---

## 3. Akt 1½ — FHIR-Anschluss (2 Min)

> Bevor wir tiefer in die Verläufe einsteigen, ein kurzer Schwenk auf die
> Anschlussfähigkeit. In der Klinik kommen diese Ereignisse nicht
> programmatisch erzeugt, sondern aus einem KIS oder HIS — typischerweise
> als FHIR-Bundle, dem HL7-Standard für klinische Daten.

Enter — Akt 1½ läuft.

> AION mappt zwischen ClinicalEvent und FHIR-Resources direkt:
> Diagnose wird Condition, Beobachtung wird Observation, Medikation wird
> MedicationAdministration. Die typisierten Beziehungen, die wir gerade
> gesehen haben — `confirms`, `response_to` — werden als FHIR-Extensions
> mittransportiert, sodass beim Round-Trip nichts verloren geht.

Enter — Bundle wird gebaut, Round-Trip läuft.

> Praktisch heißt das: AION liest FHIR-Bündel direkt ein — die frei
> verfügbare MIMIC-IV-on-FHIR-Demo (PhysioNet, ODbL) ebenso wie
> Synthea-Datensätze, ohne vorgeschaltete Konvertierung. Die Ableitung
> klinischer Ereignisse daraus ist in Arbeit; der Stand steht im
> Messblatt. Und ebenso: Resultate als FHIR exportieren, etwa für Studien
> oder externe Analyse-Tools.

> Note: ein Stilhinweis. Wenn jemand fragt warum nicht direkt
> SQLAlchemy oder ein Mapping-Framework — wir nutzen `fhir.resources` als
> einzige Optional-Dependency für FHIR. Das hält die Abhängigkeitskette
> klein. Ohne dieses Paket läuft AION trotzdem, dieser Akt überspringt
> sich dann automatisch.

---

## 4. Akt 2 — Pattern-Mining (8 Min) — **HAUPTAKT**

Das ist der Kern der Vorführung. Hier nicht hetzen.

Enter — Akt 2 startet.

> Das ist jetzt der spannende Teil. In der traditionellen Medizin-Informatik
> modelliert *jemand* manuell, was eine „Sepsis-Phase" ist: erst SIRS, dann
> Sepsis, dann Schock. Diese Definitionen kommen aus Leitlinien und werden
> gepflegt — mit allen Schwierigkeiten manueller Pflege.
>
> AION dreht das um: aus echten Verlaufsdaten *lernt* das System die
> typischen Phasen automatisch.

Enter — 50 Verläufe werden generiert.

> Fünfzig synthetische Patienten. Die meisten haben einen Sepsis-Verlauf,
> ein Drittel nicht. Ich zeige Ihnen vier Beispiel-Verläufe.

Kurz innehalten, das Publikum die Verläufe lesen lassen.

> Sehen Sie die unterschiedlichen Längen, die unterschiedlichen Pfade.
> Manche Patienten gehen direkt von der Aufnahme zur Genesung, manche
> durchlaufen die ganze Sepsis-Kaskade.

Enter — Pattern-Mining wird angewendet.

> Pattern-Mining mit minimal 50 % Support. Das heißt: ein Muster zählt
> nur, wenn es in mindestens der Hälfte der Verläufe vorkommt. Apriori-
> artiger Algorithmus, läuft in Sekunden auf Tausenden Verläufen.

Enter — Top-Phasen erscheinen.

**Hier ist der Aha-Moment.** Pause machen. Auf den Output zeigen.

> *Fieber → SIRS → Sepsis* — 70 Prozent Support. Niemand hat dem System
> gesagt, dass das eine relevante Phase ist. Das System hat sie aus den
> Daten extrahiert. Klinisch: das ist die Sepsis-Trias aus der Sepsis-3-
> Definition.
>
> Was bedeutet das praktisch?
>
> Erstens: in einer neuen Klinik mit anderen Patientencharakteristika
> tauchen andere Phasen auf — das System passt sich an.
>
> Zweitens: emerging patterns. Wenn sich Patientenverläufe ändern, etwa
> durch eine neue Therapie oder einen neuen Erreger, sieht man das in
> den Mustern, bevor jemand eine Leitlinie schreibt.
>
> Drittens: die gefundenen Phasen können als neue Konzepte zurück in
> die Wissensbasis fließen — was wir gleich sehen.

**Wenn Zeit ist — Frage ans Publikum:** „Was würde passieren, wenn ich
hier statt 50 % Support nur 30 % verlange? Wer schätzt die Anzahl der
Patterns?"

Antwort: viel mehr, weil seltenere Phasen einbezogen werden. Trade-off
zwischen Spezifität und Vollständigkeit.

---

## 5. Akt 3 — Patterns werden Konzepte (3 Min)

Enter — Akt 3.

> Die gefundenen Phasen heben wir jetzt auf eine höhere Abstraktionsebene.
> Sie werden neue Typen in der Hierarchie — Subtypen einer
> abstrakten „Klinische_Phase".

Enter — neue Typen erscheinen.

> Damit haben wir einen Selbst-erweiternden Wissensgraphen: Daten kommen
> rein, Muster werden gefunden, Muster werden zu Vokabular, neue Daten
> können auf diesem Vokabular annotiert werden.
>
> Wichtig: das System prüft Konsistenz. Wenn zwei Phasen widersprüchliche
> Constraints haben, würde der Validator das melden. Hier ist alles okay.

---

## 6. Akt 4 — Kausale Inferenz (4 Min)

Enter — Akt 4.

> Letzter Akt: eine echte klinische Frage. Senkt frühe Antibiose die
> 30-Tage-Mortalität bei Sepsis?
>
> Die naive Antwort wäre: Patienten ohne frühe Antibiose vergleichen mit
> Patienten mit. Aber: schwerer kranke Patienten bekommen *häufiger*
> frühe Antibiose UND haben *höhere* Mortalität. Das ist ein klassischer
> Confounder.

Enter — Graph erscheint im Terminal.

> AION baut das als kausalen Graph. Die wichtige Eigenschaft: das System
> findet das Backdoor-Adjustment-Set automatisch — die Variablen, auf die
> wir konditionieren müssen, um den Confounder-Effekt rauszurechnen.

Enter — Backdoor-Set wird ermittelt und validiert.

> Und — und das ist mir wichtig — die Validierung ist *formal* nach
> Pearl. d-Separation per Lauritzen-Verfahren. Das System gibt nicht
> nur eine Heuristik aus, es prüft auch, dass die Heuristik korrekt ist.
> Wenn nicht, kommen konkrete Verletzungs-Reports zurück.

Enter — Effekt-Schätzung.

> Mit synthetischen Daten: ATE von minus 10 Prozentpunkten. In echten
> Daten würde hier eine reale Verteilung stehen, aus den persistierten
> Ereignissen. Mit DoWhy-Bridge ließe sich das mit Sensitivitätsanalysen
> und Refutation-Tests untermauern — aber das ist nicht heute.

---

## 7. Schluss (2 Min)

Enter — Zusammenfassung erscheint.

> Vier Bausteine, ein System.
>
> Was Sie *nicht* gesehen haben: schwere Dependencies. Der Kern ist
> Python stdlib plus PyYAML. Kein NetworkX, kein NumPy für die Kerne,
> keine SQLAlchemy. Das System läuft auf einem Embedded-Linux-Board,
> in einer Klinik-Workstation, oder in einem Container — überall.
>
> 364 Unit-Tests grün, formale Backdoor-Validierung mit konkreten
> Verletzungs-Reports, Pattern-Mining ohne Trainingsphase. Das alles in
> einer Code-Basis von ungefähr 2500 Zeilen.
>
> Vielen Dank. Fragen?

---

## Fragen-Antizipation

**„Wie skaliert das?"**
SQLite hat einen praktischen Skalierungsbereich von ungefähr 100 Millionen
Events. Darüber kommt PostgreSQL ins Spiel — die Persistenz-Schicht ist
abstrakt genug, das auszutauschen. Pattern-Mining ist O(N · L · k); konkret
gemessen: 10.000 Verläufe (Länge ~7) in unter 60 Millisekunden auf einem
normalen Laptop. Für typische Klinik-Datenmengen also Bruchteile von
Sekunden, nicht Minuten.

**„FHIR-Anbindung?"**
Vorhanden — gerade gezeigt in Akt 1½. `aion.fhir` macht Round-Trip
zwischen ClinicalEvents und FHIR-Resources (Observation, Condition,
MedicationAdministration, Procedure). Bundle-Persistenz als JSON.
Typisierte Beziehungen werden als FHIR-Extensions transportiert,
also ohne Datenverlust beim Import/Export.

**„Funktioniert das nur für Sepsis, oder auch für andere Bereiche?"**
Das Beispiel in der Demo war Sepsis, aber AION ist domain-agnostisch.
Im Repository liegt ein zweites Beispiel-Schema `cardiology_extension.yaml`
mit 19 kardiologischen Typen — STEMI, NSTEMI, PCI, Echokardiographie,
Vorhofflimmern, etc. Das Demo-Skript `examples/cardiology_demo.py`
zeigt den gleichen Workflow für STEMI-Verläufe mit Door-to-Balloon-Zeit
als Treatment und GRACE-Score als Confounder. Schemata sind YAML —
für einen neuen Fachbereich schreibt man die Typhierarchie hin und
bekommt Pattern-Mining, Knowledge-Graph und kausale Inferenz mit.

**„Wie unterscheidet sich das von SNOMED CT?"**
SNOMED ist eine Ontologie — ein festes, hierarchisches Vokabular.
AION ist ein *Repräsentations-Framework*. SNOMED-Codes können als
Attribut-Werte oder Typ-Referenzen in AION verwendet werden. AION
ergänzt SNOMED um die zeitliche Dimension und um typisierte Beziehungen
zwischen instanziierten Ereignissen.

**„Warum keine Machine-Learning-Modelle?"**
Es gibt sie, an den richtigen Stellen: Pattern-Mining, Monte-Carlo-
Schätzung für Allen-Relationen, kausale Effekt-Schätzung. Wir vermeiden
Black-Box-Modelle, weil im klinischen Kontext Erklärbarkeit wichtiger
ist als der letzte Prozentpunkt Genauigkeit. Wenn ein Arzt einer
Vorhersage folgt, muss er sie begründen können.

**„Datenschutz / DSGVO?"**
Lokale SQLite-DB, kein Netzwerkverkehr, keine Cloud. Pseudonymisierung
über die `patient_id`. Der ganze Code ist Open Source unter MIT
(LGPL für die Qt-Bindings). Keine Telemetrie.

**„Was passiert wenn die Daten falsch sind?"**
Eager-Validierung beim Anlegen. Die Schema-Verifikation findet
inkonsistente Multi-Inheritance-Definitionen. Mit Z3 SMT-Solver gibt
es sogar formale Erfüllbarkeitsprüfung. Das fängt nicht alle Fehler,
aber die strukturellen schon.

**„Code zum Anschauen?"**
[ZIP/Repository-Link]. README und ausführliches Benutzerhandbuch dabei.

---

## Notfall-Plan

**Wenn das Terminal nicht funktioniert:**
- Zweiter Plan: GUI nutzen (`aion-gui`). Tab „Kausalgraph" → „Beispiel laden"
  → Treatment X, Outcome Y → Backdoor-Visualisierung. Pattern-Mining
  fehlt in der GUI, müsste man dann erklären statt zeigen.

**Wenn die GUI nicht startet:**
- Dritter Plan: nur Demo-Skript ohne Pausen, dafür mehr Erklärung.

**Wenn gar nichts läuft:**
- Den Output von `python vorfuehrung.py --auto` als Datei mitnehmen
  (also `python vorfuehrung.py --auto > demo_output.txt` vorher), als
  PDF oder Textdatei zeigen, dabei reden.

**Wenn jemand technische Details fragt, die ich nicht weiß:**
- „Gute Frage. Das Projekt ist Open Source — ich antworte gerne nach
  dem Vortrag genauer, dann kann ich auch im Code nachschauen."

---

## Timing-Check

- Aufwärmen: 1 Min
- Problem: 2 Min
- Akt 1: 4 Min
- Akt 1½ (FHIR): 2 Min
- Akt 2 (Hauptakt): 8 Min
- Akt 3: 3 Min
- Akt 4: 4 Min
- Schluss: 2 Min
- **Summe: 26 Min**

Lässt 4 Min Puffer für Fragen im 30-Min-Slot. Falls knapp:
Akt 1½ (FHIR) lässt sich auf 1 Min kürzen oder ganz weglassen — der
FHIR-Akt überspringt sich automatisch, wenn `fhir.resources` nicht
installiert ist. Im Sprechertext für die FHIR-Sektion lässt sich
auch jeder Absatz einzeln streichen.

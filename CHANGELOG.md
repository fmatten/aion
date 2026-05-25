# Changelog

Alle nennenswerten Änderungen dieses Projekts werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung folgt [Semantic Versioning](https://semver.org/lang/de/).

---

## [2.0.2] — 2026-05-25

### PyPI & Repository Metadata

- Updated `description`: FM-3, Allen algebra, Shapley, differential privacy explizit benannt
- Updated `[project.urls]`: GitHub als primäre URL, Codeberg als Mirror
- README: Badges, GitHub-URL, verwandte Projekte (CAIRN, SILD)
- Zenodo `related_identifiers` aktualisiert

---

## [2.0.1] — 2026-05-12

**Major Release** — Vollständige Implementierung des Papers FM-3
(*Formale Wissensrepräsentation klinischer Verläufe*,
DOI: 10.5281/zenodo.19548857) durch additive Erweiterung von 1.10.3.

### Wichtig: vollständig abwärtskompatibel

Diese Veröffentlichung ist **rein additiv** — alle Module aus 1.10.3
sind unverändert enthalten. Bestehende Imports funktionieren weiter:
`aion.core.*`, `aion.fhir.*`, `aion.hl7v2.*`, `aion.auth.*`,
`aion.persistence.*`, `aion.gui.*`, `aion.verify.*`, `aion.cli`,
`aion.examples.*`.

### Hinzugefügt: Paper FM-3 §3–§22

**Kernmodule (stdlib-only, keine neuen Pflichtabhängigkeiten):**

- **`aion.privacy.dp`** — §20 Differential Privacy (`LocalDP`, `LaplaceDP`, `PrivacyBudget`)
- **`aion.causal_learn.pc_algorithm`** — §15 PC-Algorithmus + Bootstrap (zusätzlich zu `aion.core.causal`)
- **`aion.explain.shapley`** — §22 Shapley-Attribution, kontrafaktische Erklärung, suffiziente Erklärung, **§22.5 `bounded_explanation`** (|S| ≤ K_max)
- **`aion.ai.components`** — §21 KI-Komponenten (7 Schichten: Extraktion, Validierung, Anomalie, Risiko, Regeln, Komposition)
- **`aion.ai.trajectories`** — §21.5 Episoden + N-Gramm-Trajektorienvorhersage
- **`aion.query.language`** — §11 Formale Abfragesprache (Kohortenformeln, Algebra)
- **`aion.federation.federated`** — §20.7 Lokale Multi-Institutionen-Föderierung
- **`aion.federation.remote`** — §20.7 HTTPS-basierte Multi-Institutionen-Föderierung
- **`aion.schema_evolution`** — §18 Schemaevolution (7 Operationen)
- **`aion.schema_registry`** — §18.1 Versionierte Schema-Registry

**Optionale Extras (neue):**

- `pip install aion-clinical[api]` — REST-API mit FastAPI (57 Endpunkte)
- `pip install aion-clinical[postgres]` — `aion.persist.postgres_store` mit DP-Erweiterungen
- `pip install aion-clinical[mllp]` — HL7v2 MLLP-Listener mit 16 klinisch korrekten Nachrichtentypen
- `pip install aion-clinical[oidc-keycloak]` — Keycloak-Auth (zusätzlich zur bestehenden `[oidc]`)
- `pip install aion-clinical[monitoring]` — Prometheus-Metriken (16 Metriken)
- `pip install aion-clinical[federation]` — Multi-Institutionen-API
- `pip install aion-clinical[full]` — komplettes Produktionspaket

### Hinweis zu yanked 2.0.0

Eine vorzeitig veröffentlichte Version 2.0.0 wurde wegen unvollständiger
Paketstruktur (fehlende 1.10.3-Module) zurückgezogen. Diese 2.0.1 ist die
korrekte Veröffentlichung als vollständig abwärtskompatibler Major-Release.

### Wissenschaftliche Verknüpfung

Implementiert: Matten, F. (2026). *Formale Wissensrepräsentation klinischer
Verläufe* (Paper FM-3). DOI: [10.5281/zenodo.19548857](https://doi.org/10.5281/zenodo.19548857)

## [1.10.3] — 2026-05-06

Hygiene-Patch nach externem Smoke-Test (ChatGPT). Fokus: Wheel-Inhalt
für End-Anwender vollständig, README für `pip install aion-clinical`
geeignet, Migration-Guide 1.0.x → 1.10.x ergänzt.

### Hinzugefügt

- **`aion.examples`** — Demos sind jetzt Sub-Package und werden
  als Teil des Wheels mitausgeliefert. Direkt ausführbar via
  `python -m aion.examples.<name>`:
  - `basic_usage`, `sqlite_demo`, `cardiology_demo`,
    `causal_inference_demo`, `dowhy_demo`, `fhir_demo`, `hl7v2_demo`,
    `mllp_demo`, `auth_demo`, `synthea_demo`, `phase_a_demo`
- **`aion.schemas`** — Hierarchie-Schemas
  (`clinical_base.yaml`, `cardiology_extension.yaml`,
  `icu_extension.yaml`) sind als Package-Daten im Wheel enthalten.
  Zugriff via `importlib.resources.files('aion.schemas')`.
- **`aion.examples.fixtures`** — minimale HL7-v2-Test-Nachrichten
  (5 Dateien, ~7 KB), damit `hl7v2_demo` standalone läuft.
- **`MIGRATION.md`** — Mapping 1.0.x → 1.10.x mit konkreten Code-
  Beispielen für Allen-Interval, ClinicalEvent, SQLiteEventStore,
  FHIR-Roundtrip, HL7-v2, MLLP, Auth.
- **`pyproject.toml`** package-data um `*.yaml`, `*.ipynb`, `*.hl7`
  erweitert.

### Geändert

- **README.md Installations-Sektion** klar getrennt:
  - **Endanwender** mit `pip install aion-clinical[…]`-Befehlen
    (PyPI-üblich)
  - **Entwickler** mit `git clone` + `pip install -e .[dev]`
    (Source-Distribution)
- README-Verweis auf BENUTZERHANDBUCH.md mit Hinweis, dass es in der
  sdist (`pip download --no-binary :all:`) oder auf Codeberg liegt.
- Beispiele werden im README jetzt als `python -m aion.examples.X`
  aufgeführt (statt `python examples/X.py`), passend zur neuen
  Package-Struktur.
- `cardiology_demo` und `hl7v2_demo` Pfad-Logik an die neue
  Verzeichnis-Struktur angepasst (Schemas und Fixtures liegen jetzt
  im Package).

### Behoben

Externer Review-Befund (ChatGPT, 2026-05-06): das Wheel enthielt
keine `examples/`, `schemas/` oder `tests/` — was zu Frust bei
Anwendern führen konnte, weil README und Doku darauf verweisen.
**Stand 1.10.3:** `examples/` und `schemas/` sind als Sub-Packages im
Wheel; Tests bleiben wie üblich nur in der sdist (Standard-Praxis).

### Nicht geändert

- 364 Tests laufen unverändert
- API ist binär-kompatibel zu 1.10.2 (rein additive Änderungen)
- Lizenz-Setup, Author/Maintainer, alle SPDX-Header

---

## [1.10.2] — 2026-05-05

Hygiene-Patch: Verknüpfung mit dem Codeberg-Initial-Concept-Repo
und Klarstellung des Verhältnisses Software ↔ theoretisches Modell.
Kein Code-Inhalt geändert, alle 364 Tests laufen unverändert.

### Geändert

- **`pyproject.toml` `[project.urls]`** zeigt jetzt auf reale Anker:
  - `Source` → <https://codeberg.org/iscad/aion> (Initial-Concept-Repo)
  - `PyPI` → <https://pypi.org/project/aion-clinical/>
  - `Changelog` → PyPI-Release-History
  - `Theoretical Foundation` → <https://doi.org/10.5281/zenodo.19548857>
    (Mathematik-Modell, separat archiviert)

### Klarstellung — Software-DOI vs. Theory-DOI

Die DOI `10.5281/zenodo.19548857` referenziert das **theoretische
Mathematik-Modell** (Allen-Algebra, Typ-Hierarchie, TCFG-Semantik), nicht
die Software-Distribution. Die Software hat aktuell keinen separaten
Software-DOI; zur Versions-Identifikation einer konkreten Software-
Variante dient der PyPI-Release-Identifier (z. B. `aion-clinical 1.10.2`).
Eine Codeberg/Zenodo-Integration für Software-DOIs kann in Zukunft
ergänzt werden.

### Codeberg-Repo

Das Codeberg-Repo `iscad/aion` enthält den **Initial-Concept-Commit**
(FM-3) vom April 2026 mit `CLA.md`, `LICENSE-COMMERCIAL.md`, `NOTICE`
und dem File-Header-Template. Es ist als historischer Anker für die
Dual-License-Setzung erhalten und wird nicht aktiv mit der PyPI-
Entwicklung synchronisiert. Anwender sollten `pip install aion-clinical`
verwenden.

---

## [1.10.1] — 2026-05-03

Lizenz-Patch-Release. Kein Code-Inhalt geändert.

### Geändert

- **Lizenz** umgestellt von MIT auf **EUPL-1.2 mit Dual-Lizenz-Option**:
  - Open-Source unter European Union Public Licence v1.2
  - Kommerzielle Lizenz verfügbar über licensing@iscad-it.de
- **`LICENSE`** komplett überarbeitet — verweist auf EUPL-1.2
  Volltext in `LICENSES/EUPL-1.2.txt` und enthält Dual-License-Hinweis
- **`LICENSES/EUPL-1.2.txt`** neu — vollständiger EUPL-1.2-Text
  (englische SPDX-Standardfassung) für REUSE-Konformität
- **`NOTICE`** neu — Urheberrechtshinweis, Drittkomponenten-Liste,
  Trademark-Klarstellung, Warranty-Disclaimer
- **`pyproject.toml`** aktualisiert: `license = "EUPL-1.2"`,
  Classifier `License :: OSI Approved :: European Union Public
  Licence 1.2 (EUPL 1.2)`
- **README.md**: Lizenz-Sektion auf Dual-License umgestellt

### Hinzugefügt

- **SPDX-Header in alle 89 Source-Dateien** (Hybrid-Stil):
  ```
  # SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
  # SPDX-License-Identifier: EUPL-1.2
  ```
  Bestehende Modul-Docstrings bleiben unverändert. REUSE/SPDX-konform
  für automatisierte Lizenz-Scanner.
- **`tools/add_license_headers.py`** — idempotentes Werkzeug zum
  Hinzufügen/Prüfen von SPDX-Headern. Modus `--check` für CI.

### Hinweise

- **Urheberrecht und Verantwortung:** Friedhelm Matten / ISCaD GmbH
  ist Urheber von AION Clinical. Anwender, die unter EUPL-1.2 nutzen,
  erfüllen die Pflichten aus Artikel 5 (Hinweise erhalten,
  Bearbeitungen kennzeichnen, Quellcode bereitstellen, Copyleft).
- **Kompatible Lizenzen** (EUPL-1.2 Anhang) erlauben die Kombination
  mit GPL v2/v3, AGPLv3, LGPL v2.1/v3, MPL v2, EPL v1, OSL, CeCILL,
  CC-BY-SA 3.0 (für Doku) und EUPL v1.1.
- **Kein MDR-Status durch Lizenzwechsel.** AION ist und bleibt kein
  zertifiziertes Medizinprodukt. Siehe NOTICE und LICENSE Artikel 7+8.

### Was diese Version *nicht* ändert

- Keine Code-Änderungen — alle 364 Tests laufen unverändert grün
- Keine API-Änderungen
- Keine Konfigurations-Änderungen
- Keine Dependencies geändert

---

## [1.10.0] — 2026-04-30

Auth-Backend-System. Pluggable Authentifizierung — eine Schicht, die
ab heute auch der MLLP-Listener nutzen kann, und auf der zukünftig
REST-API-Endpunkte aufsetzen.

### Hinzugefügt

- **`aion.auth`** — Auth-Modul mit pluggable Backends:
  - `AuthBackend`-Protocol (typing.Protocol, runtime_checkable)
  - `Principal`-Datenklasse (user_id, display_name, backend, roles, extra)
  - Credential-Typen: `PasswordCredentials`, `APIKeyCredentials`,
    `TokenCredentials` — `__repr__` versteckt Secrets
  - Exception-Hierarchie: `AuthError`, `BadCredentials`, `BackendError`,
    `AuthDisabled`
- **`aion.auth.none_backend`** — `NoneAuthBackend` (Default, keine Auth)
- **`aion.auth.apikey`** — vollständiger API-Key-Backend:
  - Gehashte Keys in YAML-Datei
  - blake2b mit Per-Key-Salt, konstante Vergleichszeit (`hmac.compare_digest`)
  - Per-Key Metadaten: Name, Rollen, Ablaufdatum
  - `generate_api_key()`, `hash_api_key()`, `verify_api_key()` als Helfer
  - Hot-Reload via `backend.reload()`
- **`aion.auth.ldap_backend`** — LDAP/Active-Directory-Backend (Optional):
  - Optional-Dependency `ldap3` (Pure-Python)
  - Bind-DN per Template (UPN oder DN)
  - Group-Membership → Role-Mapping
  - TLS-Pflicht in Production (warnt bei `ldap://`)
- **`aion.auth.oidc`** — OIDC/OAuth2-Backend (Optional):
  - Optional-Dependencies `authlib + requests`
  - JWT-Validierung gegen JWKS-Endpoint mit TTL-Cache
  - Auto-Discovery via `.well-known/openid-configuration`
  - Konfigurierbare Claims für user_id, display_name, roles
  - Audience-Check, Clock-Skew-Toleranz
- **`create_auth_backend(cfg)`** — Factory wählt aus Config
- **`AuthConfig`-Erweiterung** in `aion.config`:
  - `apikey_file` für API-Key-Backend
  - LDAP: `ldap_bind_dn_template`, `ldap_use_ssl`, `ldap_start_tls`,
    `ldap_search_base`, `ldap_group_filter`, `ldap_role_mapping`
  - OIDC: `oidc_audience`, `oidc_client_id`, `oidc_jwks_uri`,
    `oidc_jwks_cache_ttl`, `oidc_roles_claim`, `oidc_user_id_claim`,
    `oidc_display_name_claim`, `oidc_leeway`
- **MLLP-Integration:**
  - `DefaultHandler` nimmt `auth_backend` und `required_role` Parameter
  - API-Key wird aus MSH-4 (Sending Facility) extrahiert
  - Convention: Mirth-Channel setzt MSH-4 auf `aion_<key>`
  - Fehlende/falsche Auth → `AR` (Application Reject)
  - Audit-Log nutzt Principal-Name statt Sender-Header
- **CLI:**
  - `aion auth keygen --name <name> [--roles ...] [--expires ...]`
  - `aion auth verify --keyfile <path> [--key <key>]` (interaktiv ohne `--key`)
  - `aion mllp-listen --auth-keys <yaml> --auth-role <role>`
- **systemd-Service** aktualisiert mit `--auth-keys` und `--auth-role`
- **`examples/auth_demo.py`** — End-to-End: Keygen, Backend-Auth,
  MLLP-Auth mit Erfolg/Fehlschlag
- **40 neue Tests:**
  - `tests/test_auth.py` (33 Tests): Hashing, Principal, NoneBackend,
    APIKey-Backend (Roundtrip, Expired-Keys, Hot-Reload, Wrong-Type),
    Factory, LDAP/OIDC-Mock-Tests
  - `tests/test_mllp_auth.py` (7 Tests): MLLP+APIKey-Integration —
    valider Key, ungültiger Key, fehlender Key, falsche Rolle,
    Audit-Loggt-Principal, kein-Backend-bedeutet-keine-Auth

### Entwurfsentscheidungen

- **API-Key in MSH-4** statt MSH-3, weil MSH-3 (Sending Application)
  semantisch der Channel-Name ist, nicht das Geheimnis. MSH-4 (Sending
  Facility) ist konfigurierbar in Mirth pro Channel.
- **Convention `aion_`-Prefix** macht den Key visuell unverwechselbar
  mit normalen MSH-4-Werten wie "KLINIK".
- **Konstante Verifikationszeit** auch über alle Keys hinweg —
  potenziell wichtig wenn Key-Datei wächst und Timing-Attacken
  relevanter werden.
- **Audit-Lücke gilt als unkritisch** für Auth-Failures: lieber
  reject + log als ablehnen wegen Audit-DB-Problem.

### Hinweise zu LDAP/OIDC — Live-Test-Limitierung

- **In meiner Build-Umgebung läuft kein LDAP, kein OIDC-IDP.** Diese
  Backends haben Mock-Tests, aber **kein einziger Aufruf gegen echte
  Server**. Erwartung: erster Test gegen echtes AD oder Telekom-IDP
  bringt Anpassungen.
- **Häufige LDAP-Stolpersteine** zu erwarten: UPN vs. sAMAccountName,
  Referrals (Multi-Forest-AD), NTLM/Kerberos statt Simple Bind,
  Server-Side-Limit für Suchergebnisse.
- **Häufige OIDC-Stolpersteine**: Audience-Format (string vs. array),
  Custom-Claims-Pfade, Clock-Skew zwischen IDP und AION.

### Was 1.10.0 *nicht* abdeckt

- TLS-Terminierung für die Auth-Endpunkte selbst — bleibt
  Aufgabe des Reverse-Proxy oder MLLP-Stunnel
- Audit-Log-RBAC (wer darf welche Audit-Einträge sehen) — kommt mit
  REST-API
- Token-Refresh-Handling im OIDC-Backend — Anwender ist verantwortlich,
  einen frischen Token zu schicken
- mTLS auf MLLP-Ebene — wäre Alternative zu API-Key, aber komplexer

### Migration

Bestehender Code, der `DefaultHandler` ohne Auth nutzt, läuft
unverändert. Wer Auth aktivieren will:

```yaml
# /etc/aion/aion.yaml
auth:
  backend: apikey
  apikey_file: /etc/aion/api-keys.yaml
```

Plus systemd-Service mit `--auth-keys` aufrufen oder
`aion mllp-listen --auth-keys ... --auth-role ingest` direkt.

---

## [1.9.0] — 2026-04-30

MLLP-Live-Listener (Phase 2 von 2). Schließt die HL7-v2-Anbindung ab —
KIS und HL7-Bridges können jetzt direkt per TCP-Socket an AION pushen,
nicht nur über Datei-Schnittstellen wie in 1.8.0.

### Hinzugefügt

- **`aion.hl7v2.mllp`** — TCP-Server für HL7-v2 über MLLP:
  - `MLLPServer` — basiert auf `socketserver.ThreadingTCPServer`,
    stdlib-only, ein Thread pro Verbindung
  - `MLLPHandler`-Protocol — austauschbare Verarbeitungs-Logik
  - `DefaultHandler` — speichert Events in EventStore + Audit-Log
  - `serve_mllp(host, port, store, audit)` — High-Level-API,
    blockt bis Strg+C
  - `build_ack(msg, ack_code)` — generiert HL7-konforme ACK-Antworten
    mit MSH-Sender/Receiver-Spiegelung und MSA|AA/AE/AR
- **CLI:** `aion mllp-listen --host 0.0.0.0 --port 2575 --db ... --audit ...`
- **`examples/mllp_demo.py`** — Server + Client in einem Prozess
- **`systemd/aion-mllp.service`** — produktionstaugliche systemd-Unit
  mit Härtung (NoNewPrivileges, ProtectSystem=strict, MemoryMax=2G,
  RestrictAddressFamilies=AF_INET AF_INET6)
- **16 neue Tests** in `tests/test_mllp.py` — ACK-Generierung
  (Sender/Receiver-Swap), DefaultHandler (Store-Insert, Audit, AE bei
  Store-Fehler), End-to-End (zwei Nachrichten in einer Verbindung,
  zwei gleichzeitige Clients, Müll vor Start-Block, ungültige
  Nachrichten, Custom-Handler-Protocol)

### Entwurfsentscheidungen

- **Stdlib-only.** Kein asyncio, kein twisted, kein hl7apy. Eine
  Verbindung ein Thread, einfach zu debuggen, vorhersehbares
  Verhalten unter Last bis ~50 gleichzeitige Verbindungen.
- **DefaultHandler liefert AA bei "no patient/time".** Eine
  syntaktisch korrekte Nachricht, die für AION keine relevanten Daten
  enthält, ist kein Fehler — KIS soll nicht retransmittieren.
- **AE nur bei echten Verarbeitungs-Fehlern.** Mapping-Exception,
  Store-Insert-Fehler — beides wird mit AE quittiert, das KIS kann
  retransmittieren oder den Fehler reporten.
- **Audit-Fehler verhindert kein ACK.** Wenn die Audit-DB Probleme
  hat, soll der KIS-Empfang nicht blockieren. Audit-Lücken werden
  geloggt aber nicht zum Show-Stopper.
- **MLLP-Frame-Extraktion robust.** Müll vor `<VT>` wird verworfen
  (kommt bei Reconnects vor), unvollständige Frames werden gepuffert
  bis vollständig.

### Hinweise

- **Kein Live-Test gegen echtes KIS** in dieser Phase. In meiner
  Build-Umgebung läuft nichts, was MLLP spricht. Tests laufen mit
  synthetischen TCP-Clients gegen Loopback. Beim ersten Test gegen
  ein echtes Mirth Connect oder KIS sind Edge-Cases zu erwarten —
  Encoding-Varianten, Connection-Reset-Verhalten, ACK-Timing.
- **systemd-Service ist neuer Boden.** Bisher war AION ein CLI-Tool;
  jetzt gibt es einen Long-Running-Service. Das systemd-Skript hat
  Härtung mit `ProtectSystem=strict` — beim Deployment auf neuen
  Systemen die `ReadWritePaths` ggf. anpassen.
- **PostgreSQL-Backend weiterhin Stub.** Wer Multi-User mit MLLP
  fahren will, braucht echte PG-Implementation — kommt in 1.10.0
  oder 1.11.0, je nach Bedarf.

---

## [1.8.0] — 2026-04-30

HL7-v2-Datei-Importer (Phase 1 von 2). Erste echte Klinik-Datenanbindung —
deutsche KIS sprechen v2.5/2.7, fast immer als Pipe-delimited Text.
MLLP-Live-Listener kommt in 1.9.0.

### Hinzugefügt

- **`aion.hl7v2`** — Parser und Mapper für HL7 v2.x:
  - `parse_message(raw)` und `parse_messages(raw)` — stdlib-only Parser
    für eine bzw. mehrere Nachrichten
  - `HL7Message`-Klasse mit `segment()`, `field()`, `patient_id()`,
    `message_type`, `trigger_event`, `event_datetime()`
  - `message_to_event(msg, code_map=)` — mappt eine Nachricht auf
    ClinicalEvent, mit korrekter Stay-Period aus PV1-44/45
  - High-level: `hl7v2_import_file(path)`, `hl7v2_import_string(raw)`,
    `hl7v2_import_directory(dir, limit=, pattern=)`
  - Encoding-Zeichen werden aus MSH-1/MSH-2 gelesen, nicht hardcoded
- **`aion.hl7v2.codes`** — minimales Default-Mapping (Lesart C wie bei Synthea):
  - 11 ADT-Trigger-Events (A01-A13: Aufnahme, Verlegung, Entlassung etc.)
  - 18 LOINC-Codes für Vitalzeichen und häufige Labortests
  - Diagnose-, Medikamenten- und lokale Codes absichtlich nicht eingebaut
- **`has_hl7v2()`** in der Public API
- **`aion import --hl7v2 [--limit N] <file-or-dir>`** — CLI-Integration,
  analog zu `--synthea`
- **5 Test-Fixtures** in `tests/fixtures/hl7v2/`: ADT^A01, ADT^A03,
  ORU^R01 (zwei verschiedene Tests), Multi-Message-Datei
- **`examples/hl7v2_demo.py`** — End-to-End-Demo
- **37 neue Tests** in `tests/test_hl7v2.py` — Code-Mapping, Parser
  (Encoding, MSH-Indizierung, Datetime, Multi-Message, Fehlerfälle),
  Mapper (ADT, ORU, Stay-Period, Fallback-Verhalten), Datei- und
  Verzeichnis-Import

### Entwurfsentscheidungen

- **Stdlib-only Parser.** Keine externe Dependency wie `hl7apy` oder
  `python-hl7`. Wir parsen die wenigen Felder, die wir brauchen, von
  Hand. Das macht den Code überschaubar und auditierbar.
- **Lesart C bei Code-Mapping.** Konsistent mit Synthea (1.4.0):
  minimales unstrittiges Default, Anwender erweitert via `code_map=`,
  Fallback `HL7_<Type>_<Trigger>` ohne Datenverlust.
- **Datei-Reader nur** in 1.8.0. MLLP-Listener (TCP-Socket-basiert)
  kommt in 1.9.0 — separater Risiko-Kontext, weil Live-Test gegen
  echtes KIS in Build-Umgebung nicht möglich.

### Hinweise

- **Kein Live-Test gegen echtes KIS** in dieser Phase. Die Test-Fixtures
  sind synthetisch (von Hand erzeugt) im HL7-Standard-Format.
  Verifikation gegen echtes KIS muss bei Anwender (Mirth Connect, HAPI,
  KIS-Testsystem) erfolgen.
- **MSH-Indizierung HL7-Konvention:** MSH-1 ist der Feldtrenner selbst,
  MSH-9 der Message-Type/Trigger. Unsere `field("MSH", n)`-Methode
  respektiert das.
- **Encoding:** UTF-8 mit `errors="replace"` beim Datei-Lesen. ISO-8859-1
  oder Windows-1252 (in deutschen Kliniken nicht selten) wird beim
  ersten echten Datensatz nachzuziehen sein.

---

## [1.7.0] — 2026-04-30

Storage-Abstraction-Layer. Vorbereitung für PostgreSQL-Backend, ohne
heute schon das Risiko ungetesteter Datenbankcode mitzuziehen.

### Hinzugefügt

- **`aion.persistence.store`** — Storage-Abstraction:
  - `EventStore` (Protocol) — definiert die Schnittstelle, die alle
    Storage-Backends erfüllen müssen
  - `create_event_store(cfg, *, database=None)` — Factory wählt
    automatisch das richtige Backend anhand `cfg.storage.database`:
    `postgresql://...` → `PostgreSQLEventStore`, sonst → `SQLiteEventStore`
- **`aion.persistence.postgres_store`** — `PostgreSQLEventStore` als Stub:
  - Erfüllt strukturell das `EventStore`-Protocol (für `isinstance`-Checks)
  - Alle Methoden außer `close()` werfen `NotImplementedError` mit
    klarer Roadmap-Botschaft (Workaround: SQLite verwenden)
  - Volle Implementation geplant für 1.8.0, dann mit psycopg3,
    Connection-Pool, JSONB-Spalten, PL/pgSQL-Audit-Triggern
- **14 neue Tests** in `tests/test_store_protocol.py` —
  Protocol-Konformität, Factory-Verhalten, Round-Trip via Factory,
  vollständige Stub-Coverage

### Geändert

- **Public API** erweitert um `EventStore`, `create_event_store`.
- `SQLiteEventStore` ist unverändert — erfüllt das `EventStore`-Protocol
  jetzt formal, ohne dass es davon erben muss (Protocol = strukturelle
  Kompatibilität).

### Hinweise

- **Kein Live-Test mit PostgreSQL.** In meiner Build-Umgebung läuft
  kein Postgres. Der Stub ist mit Mocks getestet — die echte
  Implementation in 1.8.0 muss gegen eine laufende Postgres-Instanz
  verifiziert werden.
- **Migration für Bestandscode**: keine. Wer heute `SQLiteEventStore`
  direkt instanziiert, kann das weiter tun. Die Factory ist
  *zusätzlich*, nicht *anstelle*.
- **Wann zu Factory wechseln?** Ab dem Tag, an dem PostgreSQL aktiv
  benötigt wird (Hosting-Partner, Pilot-Standort).

---

## [1.6.0] — 2026-04-30

Konfigurations-Schicht. Zentrale Stelle für alle Settings, mit
env-Substitution und Validierung. Voraussetzung für PostgreSQL (1.7.0)
und Auth-Integration (folgt).

### Hinzugefügt

- **`aion.config`** — Konfigurations-Schicht:
  - `AionConfig` mit sechs Sektionen (Storage, Privacy, Logging, Auth,
    Performance, Validation), als dataclass mit Default-Werten
  - `load_config(path)` lädt YAML, mit env-var-Substitution `${VAR}`
    und `${VAR:-default}`
  - `validate_config(cfg)` prüft Konsistenz; sammelt alle Fehler statt
    beim ersten abzubrechen
  - `get_config()` / `set_config()` / `reset_config()` als Singleton-API
  - `$AION_CONFIG_FILE` env var als alternativer Default-Pfad
  - Unbekannte YAML-Felder werden ignoriert (statt Fehler) — das macht
    Konfigurationen forwards-compatible
- **`aion config validate <yaml>`** — CLI-Befehl, prüft eine Datei
- **`aion config show [yaml]`** — zeigt aktive oder geladene Konfig als
  YAML-Output (oder JSON-Fallback ohne PyYAML)
- **35 neue Tests** in `tests/test_config.py` — env-Substitution,
  Defaults, Validierung, YAML-Laden, Singleton-Verhalten

### Geändert

- **Public API** erweitert um `AionConfig`, `get_config`, `load_config`,
  `set_config`, `ConfigError`.
- `pyproject.toml`: keine neuen Dependencies (PyYAML ist bereits da).

### Hinweise

- **Aktive Nutzung schrittweise.** In 1.6.0 stellt das Modul nur die
  Infrastruktur bereit. Existierende Module (Audit, FHIR, Synthea)
  konsumieren die Config noch nicht zwingend — das passiert in 1.7.0
  zusammen mit der PostgreSQL-Anbindung.
- **Beispiel**: die mitgelieferte `aion-prod.yaml` ist jetzt mit
  `aion config validate aion-prod.yaml` prüfbar.

---

## [1.5.0] — 2026-04-29

Production-Vorbereitung. Dockerfile, Audit-Trail, Konfigurations-
Schicht. Erster Schritt in Richtung Klinik-Einsatz im Container.

### Hinzugefügt

- **`aion.audit`** — append-only Audit-Trail:
  - `AuditLog`-Klasse mit eigener SQLite-DB, getrennt von Patient-Daten
  - `AuditAction`-Enum mit Standard-Vokabular (READ, CREATE, UPDATE,
    DELETE, EXPORT, IMPORT, LOGIN, LOGIN_FAILED, QUERY,
    PATTERN_MINING, CAUSAL_ANALYSIS)
  - SQLite-Trigger erzwingen append-only: UPDATE und DELETE auf
    `audit_log`-Tabelle werfen `DatabaseError`
  - Patient-IDs werden vor der Speicherung pseudonymisiert (über
    `aion.privacy.pseudonymize`), nie im Klartext
  - Suche per Klartext-Patient-ID via Hash-Lookup möglich
  - CSV-Export für Audit-Berichte
- **19 neue Tests** in `tests/test_audit.py` — append-only,
  Pseudonymisierung, Thread-Safety, Filter, Persistenz, Export
- **`Dockerfile`** — Multi-stage Build mit `python:3.12-slim-bookworm`:
  - Builder-Stage: kompiliert Wheel, installiert mit `[verify,fhir]`
  - Runtime-Stage: minimaler Footprint (~180 MB), non-root user
    (uid 10001), tini als PID-1, read-only filesystem, alle Capabilities
    gedroppt, no-new-privileges
  - HEALTHCHECK via `aion --version`
  - OCI-Labels für Registry-Integration
- **`docker-compose.yml`** — Production-Layout:
  - Persistente Volumes für Daten und Audit getrennt
  - Resource-Limits (1 GB RAM, 1 CPU)
  - Sicherheits-Härtung
- **`.dockerignore`** — schlanke Build-Context
- **`aion-prod.yaml`** — Beispiel-Production-Konfiguration
  (Dokumentation; aktive Konfigurations-Schicht in 1.6.0 geplant)

### Geändert

- **Public API** erweitert um `AuditLog` und `AuditAction`.

### Hinweise

- **Audit-Trail ist DSGVO-Mindeststandard.** Art. 30 DSGVO verlangt
  Verzeichnis von Verarbeitungstätigkeiten — der Audit-Trail
  dokumentiert WER, WANN, WAS getan hat. Andere DSGVO-Säulen
  (Zweckbindung, Löschkonzept, Rechtsgrundlage) sind organisatorisch.
- **Container ist nicht klinisch zertifiziert.** Production-tauglich
  im Sinne von Hosting-Compliance, nicht im Sinne MDR. Für echten
  Klinik-Einsatz fehlen weiterhin: MDR-Zertifizierung, klinische
  Validierung, IEC 62304-Lebenszyklus, ISO 13485-QM-System.
- **AION wird nicht als Long-Running-Service gestartet** im Default-
  Compose. Der Default-Befehl ist `aion --version`. Sobald
  `aion-api` als HTTP-Service existiert (geplant für 1.7.0), wird
  das geändert.

---

## [1.4.0] — 2026-04-29

Synthea-Importer für echte FHIR-Bundles. Pragmatische Code-Mapping-
Strategie (Lesart C aus dem Roadmap-Diskurs): minimales Default-Mapping
mit klarer Anwender-Erweiterung und Fallback ohne Datenverlust.

### Hinzugefügt

- **`aion.synthea`** — Importer für Standard-Synthea-FHIR-Bundles:
  - `synthea_import_bundle(path, *, code_map=None, include_encounters=True)`
    — eine Bundle-Datei einlesen, ClinicalEvents extrahieren.
  - `synthea_import_directory(dir, *, limit=None, code_map=None)` —
    Verzeichnis-Batch-Import, defekte Bundles werden geloggt aber
    überspringen das ganze Verzeichnis nicht.
  - Encounter-Auflösung: jeder Synthea-Encounter wird sowohl als
    `Aufnahme`-Event mitgeschrieben als auch als `stay_start`/`stay_end`
    aller darin enthaltenen Events eingetragen.
- **`aion.synthea.codes`** — minimales Default-Mapping
  (~13 LOINC-Codes für Vitalzeichen/Labor, ~12 SNOMED-Codes für
  unstrittige Demografie/Encounter). Codes mit klinischer Mehrdeutigkeit
  (Diagnosen, Medikamente) absichtlich nicht eingebaut — Anwender pflegt.
- **`has_synthea()`** in der Public API.
- **`aion import --synthea [--limit N] <path-or-dir>`** — CLI-Integration.
- **Test-Fixture** `tests/fixtures/synthea/Patient_001.json` —
  Synthea-realistisches Bundle mit Encounter, Observations,
  Condition, Procedure, MedicationRequest.
- **`examples/synthea_demo.py`** — End-to-End-Demo: Default-Mapping,
  Anwender-Mapping, Verzeichnis-Batch.
- **26 neue Tests** in `tests/test_synthea.py`.

### Entwurfsentscheidungen

- **Code-Mapping bleibt klein und unstrittig.** Klinische Domain-Arbeit
  (z. B. SNOMED-Diagnose-Codes) wird nicht ohne Validierung mitgeliefert.
- **Fallback statt Verlust.** Unbekannte Codes werden zu
  `FHIR_<ResourceType>`-Events mit Code als Attribut. Daten gehen nicht
  verloren, sind nur weniger semantisch annotiert.
- **`fhir_code`/`fhir_system`/`fhir_display`** als Attribute
  überleben Mapping — auch erfolgreich gemappte Events behalten ihren
  Original-Code für Audit und Anschluss-Mapping.

### Hinweise

- **Default-Mapping ist NICHT klinisch validiert.** Vor produktivem
  Einsatz in einer realen Klinik sollte ein Domain-Experte die
  `aion.synthea.codes`-Mappings prüfen.
- Test-Fixture ist synthetisch (von Hand erzeugt im Synthea-Format),
  nicht direkt aus Synthea selbst. Für echte Synthea-Daten siehe
  github.com/synthetichealth/synthea.

## [1.3.0] — 2026-04-29

Jupyter-Notebook-Integration. Macht AION nutzbar für statistische
Workflows in der gewohnten Notebook-Umgebung — HTML-Tabellen, Plots,
Pattern-Visualisierung.

### Hinzugefügt

- **`aion.notebook`** — Helfer-Modul für Jupyter:
  - `display_hierarchy(h)` / `hierarchy_to_html(h)` — TypeHierarchy als
    HTML-Tabelle
  - `display_events(events)` / `events_to_html(events)` — Ereignisliste
    als Tabelle
  - `plot_pattern_support(patterns, top=15)` — Top-N Patterns als
    horizontales Balkendiagramm
  - `plot_causal_graph(g, treatment, outcome, backdoor_set)` — Kausalgraph
    mit Farbcodierung (Treatment blau, Outcome orange, Backdoor rot,
    Mediatoren grau)
  - `sequences_from_store(store)` — extrahiert Patientensequenzen
    chronologisch für Pattern-Mining
- **`examples/aion_jupyter_demo.ipynb`** — End-to-End-Notebook: Schema
  laden → Daten erzeugen → Pattern-Mining → Kausalgraph → Validierung
- **`has_notebook()`** in der Public API — prüft Verfügbarkeit
- **14 neue Tests** (`tests/test_notebook.py`). Plot-Tests werden bei
  fehlendem matplotlib automatisch übersprungen.

### Geändert

- `pyproject.toml`: neues Optional-Extra `[notebook]` mit jupyter,
  ipython, matplotlib, networkx.

### Hinweise

- **HTML-Renderer funktionieren ohne IPython** — fallback liefert
  HTML-String statt Jupyter-Display. Nützlich für statische Reports.
- **Plot-Funktionen brauchen matplotlib** — klare ImportError-Meldung
  mit Installationshinweis, falls fehlt.
- **networkx ist optional** — wenn nicht da, fällt der Causal-Graph-
  Layout auf Kreis-Anordnung zurück (sieht weniger schön aus, läuft
  aber).
- Demo-Notebook unter `examples/aion_jupyter_demo.ipynb` — wird vom
  ZIP mitgeliefert, muss von Anwendern erst ausgeführt werden, um
  Plots zu sehen (Notebooks werden ohne Outputs versioniert).


## [1.2.0] — 2026-04-29

CLI-Werkzeug. Macht AION ohne GUI scriptbar — für CI-Pipelines, Server-
Setups, oder einfach als schnellen Befehl im Terminal.

### Hinzugefügt

- **`aion`-Kommandozeilen-Werkzeug** (`aion.cli`) mit sechs Subcommands:
  - `aion validate <schema.yaml>` — Schema-Konsistenzcheck
  - `aion types <schema.yaml>` — Typhierarchie als Baum ausgeben
  - `aion stats <db>` — Datenbank-Statistik (Patienten, Typen, Beziehungen)
  - `aion mine <db>` — Pattern-Mining auf Patientensequenzen, mit
    konfigurierbarem `--min-support`, `--min-length`, `--max-length`
  - `aion import <bundle.json> [--db ...]` — FHIR-Bundle in DB importieren
  - `aion export <db> [--patient ID] [--out file.json]` — DB als FHIR
    exportieren
- **`aion.__main__`** — `python -m aion ...` als Alternative zur
  installierten CLI.
- **`tests/test_cli.py`** mit 10 Tests, davon 1 nur bei FHIR aktiv.

### Geändert

- `pyproject.toml`: `aion = "aion.cli:main"` als Console-Script registriert.
  Nach `pip install -e .` ist `aion` direkt verfügbar (analog zu
  `aion-gui`).

### Hinweise

- **stdlib-only:** CLI verwendet argparse, kein click oder typer.
- **FHIR-Subcommands** (`import`, `export`) brauchen `[fhir]`-Extra.
  Klare Fehlermeldung mit Installationshinweis, falls fehlt.
- **Exit-Codes:** 0 = ok, 1 = Fehler, 2 = ungültige Argumente,
  130 = Strg+C abgebrochen.

---

## [1.1.0] — 2026-04-29

Additives Release: DoWhy-Bridge für Sensitivitätsanalyse kausaler
Schätzungen. Keine API-Brüche — wer DoWhy nicht braucht, merkt nichts
von der neuen Funktionalität.

### Hinzugefügt

- **`aion.dowhy`** — Plugin-Bridge zum [DoWhy](https://github.com/py-why/dowhy)-Paket.
  - `causal_graph_to_gml(graph)` — Konvertiert AION-CausalGraph in GML
    (DoWhy-kompatibles Graph-Format). Funktioniert ohne installiertes DoWhy.
  - `to_dowhy_model(graph, df, treatment, outcome)` — erzeugt
    `dowhy.CausalModel` aus AION-Graph und pandas-DataFrame.
  - `estimate_ate(model, method_name)` — bequemer Wrapper für
    Identification + Effekt-Schätzung in einem Schritt.
  - `refute_estimate(model, identified, estimate, method)` — wrappt
    DoWhys Refutation-Suite (Placebo, Random Common Cause, Data Subset,
    Add Unobserved Common Cause). Enthält Workaround für DoWhy-Bug 0.14
    mit `identifier_method=None` beim Placebo-Refuter.
- **`has_dowhy()`** in der Public API — prüft ob das Plugin verfügbar ist.
- **`examples/dowhy_demo.py`** — End-to-End-Demo: Confounder-Setup,
  vier Schätzmethoden, drei Refutation-Tests.
- **12 neue Tests** in `tests/test_dowhy_bridge.py`. Tests, die DoWhy
  brauchen, werden via `@skipUnless(has_dowhy())` übersprungen, wenn
  das Paket fehlt — wie bei den Z3-Tests.
- **Optional-Dependency `[dowhy]`** in `pyproject.toml`. Alias zu
  `[causal]` für klarere Benutzer-Erfahrung. Zieht numpy, pandas,
  scipy, networkx, scikit-learn, statsmodels (~200 MB).

### Geändert

- `pyproject.toml`: `[causal]`-Extra ergänzt um explizites `pandas>=2.0`
  (war implizit über DoWhy gezogen, ist jetzt deklariert).

### Hinweise zur Migration von 1.0.0 nach 1.1.0

- **Keine Breaking Changes.** Wer 1.0.0 nutzt, kann ohne Code-Änderung
  upgraden.
- **DoWhy bleibt optional.** AION-Core läuft weiter ohne DoWhy. Erst
  beim Aufruf von `aion.dowhy`-Funktionen wird das Paket gefordert,
  mit klarer ImportError-Meldung falls fehlt.
- **Bekannte Einschränkung:** DoWhy 0.14 hat einen Bug, der bei einigen
  Refutern `identifier_method=None` nicht behandelt. Die Bridge enthält
  einen Workaround dafür.

---

## [1.0.0] — 2026-04-29

Erste Version mit Produktivanspruch. Substantielle Neuerungen seit 0.4.0
betreffen Datenschutz, Migrations-Sicherheit und Logging-Disziplin.

### Hinzugefügt

- **`aion.core.privacy`** — Pseudonymisierung für Logs.
  - `pseudonymize(value)` — Session-stabiler Hash mit zufälligem Salt.
    Innerhalb einer Session korrelierbar, über Sessions hinweg nicht.
  - `safe_path(path)` — reduziert Datei-Pfade auf den Basisnamen,
    plattformunabhängig (POSIX und Windows).
  - `fingerprint_dict(d)` — Schlüssel-Fingerabdruck ohne Werte.
- **Migrations-Tests** (`tests/test_migration.py`) — sechs Tests für
  schemata aus aion-clinical < 0.3.0. Verifizieren Idempotenz,
  Daten-Integrität und Schreibbarkeit nach Migration.
- **`__version__`-Sichtbarkeit** im GUI-About-Dialog (zog vorher noch
  veraltete Konstante).

### Geändert

- **`SQLiteEventStore.connect()`** — Reihenfolge umgedreht: zuerst
  Migration, dann `_SCHEMA`. Vorher schlug das Öffnen einer
  0.2.x-DB fehl, weil `_SCHEMA` einen Index auf eine Spalte legte,
  die erst durch Migration entsteht. Backward-incompatible für niemanden,
  weil mit altem Code keine 0.2.x-DB überhaupt aufging.
- **GUI-Logging** durchgängig pseudonymisiert:
  - Patient-IDs in `events_tab.py` werden via `pseudonymize()` gehasht.
  - Datei-Pfade in `app.py`, `causal_tab.py` werden via `safe_path()`
    auf Basisnamen reduziert.
- **Public API** erweitert um `setup_logging`, `get_logger`,
  `pseudonymize`, `safe_path`, `fingerprint_dict`.

### Behoben

- **Migrations-Bug** in `SQLiteEventStore` — DBs aus aion-clinical < 0.3.0
  ließen sich nicht öffnen, weil das aktuelle `_SCHEMA` (mit
  `CREATE INDEX idx_relation`) vor der Migration angewendet wurde, die
  diese Spalte erst hinzufügt. Drei separate Bugs in einem:
  1. Schema vor Migration angewendet
  2. `_migrate()` prüfte nicht, ob die zu migrierende Tabelle überhaupt
     existiert (Crash bei leerer DB)
  3. `idx_relation` referenzierte eine Spalte, die in alten DBs fehlt
- **About-Dialog** in der GUI zeigte noch `v0.2.0` (statisch hardcodiert).
  Liest jetzt `aion.__version__` dynamisch.

### Hinweise zur Migration von 0.4.0 nach 1.0.0

- **Datenbanken** öffnen sich automatisch auf das neue Schema, sind aber
  vorwärts- und rückwärtskompatibel zu 0.3.0/0.4.0.
- **Logs** enthalten ab 1.0.0 keine Klartext-Patient-IDs mehr. Wer alte
  Logs mit neuen korrelieren will, muss eine eigene Mapping-Tabelle
  bauen (absichtlich nicht im Code enthalten — DSGVO-Hygiene).
- **Public API** ist stabil. Submodul-Internals (alles unterhalb von
  `aion.core`, `aion.gui`, `aion.fhir`, `aion.verify`) können sich
  weiter ändern; Anwendungen sollten nur über `import aion` zugreifen.

---

## [0.4.0] — 2026-04-15

### Hinzugefügt

- **`aion.fhir`** — Round-Trip-Mapper zwischen ClinicalEvent und
  FHIR-Resources. Unterstützte Ressourcentypen: Observation, Condition,
  MedicationAdministration, Procedure. Bundle-IO mit JSON-Persistenz.
  21 Round-Trip-Tests.
- **`aion.core.logging_setup`** — zentrales Logging-Modul (stdlib-basiert,
  idempotent, optionaler RotatingFileHandler nach `~/.aion/aion-gui.log`).
- **GUI-Fehlerklassifizierung** — alle `except Exception:`-Stellen in
  fünf Tabs durch präzise Exception-Typen ersetzt
  (`FileNotFoundError`, `JSONDecodeError`, `ValueError`,
  `TypeHierarchyError`, `CausalGraphError`).
- **`tools/check_consistency.py`** — Versions-String-Konsistenzcheck
  zwischen pyproject.toml und Doku.
- **`tools/verify_handbook.py`** — verifiziert numerische Behauptungen im
  Handbuch gegen tatsächlichen Code-Output.
- **`tools/perf_pattern_mining.py`** — Performance-Profilierung
  (10.000 Verläufe in ~67 ms gemessen).
- **`tools/smoke_gui.py`** — Offscreen-GUI-Test für Vorführungs-Setup.
- **`vorfuehrung.py`** — Live-Demo-Skript, sechs Akte mit
  Pattern-Mining als Hauptakt und FHIR-Roundtrip als Akt 1½.
- **`SPRECHERTEXT.md`** — Sprechertext für Vorträge mit Demo-Cues.
- **Beispiel-Schema `cardiology_extension.yaml`** — 19 kardiologische
  Typen (STEMI, NSTEMI, PCI, Echokardiographie, Vorhofflimmern, …).
- **Beispiel-Skript `examples/cardiology_demo.py`** — STEMI-Versorgungspfad
  mit Door-to-Balloon-Validierung.
- **Beispiel-Skript `examples/fhir_demo.py`** — End-to-End FHIR-Roundtrip.

### Geändert

- **TCFG Pattern-Mining** Performance: ~10.000 Sequenzen in unter 100 ms
  durch Apriori-artige Pruning-Optimierung.
- **GUI-About-Dialog** zeigt nun aktuelle Version dynamisch.

### Hinweise

- **Versionen 0.5.x bis 0.9.x wurden bewusst übersprungen.** 0.4.0 enthielt
  bereits substantielle Funktionalität (FHIR, Logging, Tooling); 1.0.0
  markiert die Anhebung der Disziplin (Datenschutz, Migrationspfad,
  API-Stabilitäts-Versprechen), nicht den Featurezuwachs.

---

## [0.3.0] — 2026-04-01

### Hinzugefügt

- **Phase-A-Erweiterungen:**
  - Typisierte Ereignis-Referenzen `ρ : E → R` mit Vokabular
    `EventRelation` (`confirms`, `rules_out`, `response_to`, `observation_of`,
    `part_of`, `references`).
  - **TCFG.mine_patterns()** — Apriori-artiges Pattern-Mining auf
    Sequenzen, Support-basiert.
  - **`aion.verify`** — formale Schema- und Graph-Verifikation:
    - `check_inheritance_conflicts` für Multi-Inheritance-DAGs.
    - `d_separates` und `is_valid_backdoor_set` mit
      Lauritzen-Algorithmus (ancestral subgraph + moralization).
    - Optionales Z3-Plugin (`aion.verify.z3_plugin`) für SMT-basierte
      Erfüllbarkeitsprüfung der Attribut-Ranges.

### Geändert

- **`SQLiteEventStore.event_references`** bekam Spalte `relation` mit
  Default `'references'`. Migrationsfunktion `_migrate()` aufgenommen.

---

## [0.2.0] — 2026-03-15

### Hinzugefügt

- **GUI** auf PySide6: 5 Tabs (Typ-Hierarchie, Ereignisse,
  Allen-Relationen, Kausalgraph, Schema-Editor).
- **Schema-YAML-Import** (`TypeHierarchy.from_yaml`) und -Export.
- **Allen-Algebra** (13 Relationen, Fuzzy-Variante mit Monte-Carlo).
- **Kausalgraph** mit Backdoor-Adjustment-Findung (Heuristik).
- **`aion.persistence.SQLiteEventStore`** — Persistenz für Events.

---

## [0.1.0] — 2026-03-01

Erste interne Version.

### Hinzugefügt

- **Typhierarchie** als DAG mit Multi-Inheritance.
- **ClinicalEvent**-Datenmodell `e = (p, a, τ, α)`.
- **TCFG-Grammatik** mit CYK-Parser und Beam-Search.

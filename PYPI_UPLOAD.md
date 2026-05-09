# PyPI-Upload für AION Clinical 1.10.1

**Stand:** Phase 1 abgeschlossen. dist/-Files gebaut und validiert.

Diese Anleitung beschreibt **Phase 2** (Test-Upload) und **Phase 3**
(echte Veröffentlichung). Beide musst Du selbst durchführen, weil die
PyPI-Credentials nur Du hast.

---

## Vor dem Upload — diese Files prüfen

Im Verzeichnis `dist/` sollten zwei Dateien liegen:

```
dist/
├── aion_clinical-1.10.1-py3-none-any.whl    (137 KB)
└── aion_clinical-1.10.1.tar.gz              (233 KB)
```

Wenn nicht: zuerst neu bauen mit
```bash
cd /pfad/zu/aion-clinical
rm -rf dist build *.egg-info
python3 -m build
```

---

## Phase 2 — Test-Upload zu test.pypi.org

`test.pypi.org` ist eine **separate** Registry für Tests. Was Du dort
hochlädst, ist **nicht** auf pypi.org sichtbar. Versionsnummer kann dort
auch wiederverwendet werden — Du kannst also experimentieren.

### Schritt 1: Account auf test.pypi.org

Falls noch nicht vorhanden:
- Registrieren auf https://test.pypi.org/account/register/
- 2FA aktivieren (PyPI-Pflicht)
- API-Token erstellen unter https://test.pypi.org/manage/account/token/
  - Scope: "Entire account" (für ersten Upload nötig)
  - Token-String kopieren (beginnt mit `pypi-`)

### Schritt 2: ~/.pypirc anlegen

```ini
# ~/.pypirc
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
# password wird interaktiv abgefragt (sicherer)

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
# password wird interaktiv abgefragt
```

`chmod 600 ~/.pypirc`

### Schritt 3: twine check

```bash
python3 -m twine check dist/*
```

Erwartung:
```
Checking dist/aion_clinical-1.10.1-py3-none-any.whl: PASSED
Checking dist/aion_clinical-1.10.1.tar.gz: PASSED
```

### Schritt 4: Upload zu test.pypi.org

```bash
python3 -m twine upload --repository testpypi dist/*
```

Du wirst nach dem Token gefragt — den Test-PyPI-Token einfügen
(oder das `password`-Feld in `.pypirc` setzen).

### Schritt 5: Verifizieren auf test.pypi.org

Browser öffnen:
- https://test.pypi.org/project/aion-clinical/

**Diese Punkte prüfen:**

1. ✓ Version `1.10.1` ist sichtbar
2. ✓ Description (englisch) erscheint korrekt
3. ✓ License-Badge zeigt `EUPL-1.2`
4. ✓ Maintainer wird angezeigt
5. ✓ Files-Tab zeigt sdist + wheel
6. ✓ Dependencies/Extras sichtbar

### Schritt 6: Test-Installation aus test.pypi.org

```bash
# Frische venv für Test
python3 -m venv /tmp/aion-pypi-test
/tmp/aion-pypi-test/bin/pip install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    aion-clinical==1.10.1

# Smoke-Test
/tmp/aion-pypi-test/bin/aion --version
# Erwartung: aion 1.10.1
```

**Hinweis:** `--extra-index-url https://pypi.org/simple/` ist nötig,
weil Test-PyPI keine Dependencies wie PyYAML hat — die holt pip dann
vom echten PyPI.

---

## Phase 3 — Echter Upload zu pypi.org

**WARNUNG:** Einmal auf pypi.org hochgeladen, kannst Du eine Version
**nicht** überschreiben oder löschen. Bei Fehler: 1.10.2 als Korrektur.

### Schritt 1: API-Token für pypi.org

Auf https://pypi.org/manage/account/token/:
- Scope: "Project: aion-clinical" (eingeschränkt — sicherer)
- Token kopieren

Token in `~/.pypirc` unter `[pypi]` als `password = pypi-...` setzen,
oder bei Upload interaktiv eingeben.

### Schritt 2: Upload

```bash
python3 -m twine upload dist/*
```

### Schritt 3: Verifizieren auf pypi.org

Browser:
- https://pypi.org/project/aion-clinical/

**Pflicht-Checks:**

1. ✓ Version `1.10.1` ist die "Latest"
2. ✓ Vorherige `1.0.6` ist unter "Release History" weiterhin sichtbar
3. ✓ License-Badge `EUPL-1.2`
4. ✓ Description erscheint vollständig
5. ✓ `pip install aion-clinical` (ohne Version) zieht 1.10.1

### Schritt 4: Frische Installation testen

```bash
python3 -m venv /tmp/aion-pypi-prod
/tmp/aion-pypi-prod/bin/pip install aion-clinical==1.10.1
/tmp/aion-pypi-prod/bin/aion --version
# Erwartung: aion 1.10.1
```

---

## Was nach Phase 3 noch sinnvoll ist

### Release-Tag dokumentieren

Wenn Du ein Git-Repo hast (auch privat):
```bash
git tag -a v1.10.3 -m "Release 1.10.2 — Codeberg-Verknüpfung&Metadata-Hygiene"
git push origin v1.10.3
```

### Zenodo-DOI aktualisieren

Auf PyPI 1.0.6 ist DOI `10.5281/zenodo.19548857` verlinkt. Falls Du
Zenodo nutzt, dort das neue Release archivieren — gibt eine neue DOI
für 1.10.1.

### Optional: GitHub-Spiegel

Wenn AION auf GitHub gehosted werden soll, kannst Du das Repo dort
mirroren und in `pyproject.toml` `[project.urls]` ergänzen:

```toml
[project.urls]
Repository = "https://github.com/<user>/aion-clinical"
Issues     = "https://github.com/<user>/aion-clinical/issues"
```

Das wird in 1.10.2 (oder 1.11.0) hochgezogen.

---

## Was wenn etwas schiefgeht

**Fehler: "File already exists"**
→ Versionsnummer hochziehen. Auf test.pypi.org darf 1.10.1 wiederverwendet
werden, auf pypi.org **nicht**. → 1.10.2 als Hotfix.

**Fehler: "403 Forbidden"**
→ Token-Scope prüfen. Bei "Project: aion-clinical" muss das Projekt schon
existieren. Beim allerersten Upload brauchst Du "Entire account"-Scope,
danach kannst Du auf "Project: aion-clinical" einschränken.

**Fehler: "Invalid description"**
→ `python3 -m twine check dist/*` lokal ausführen, Fehler beheben,
neu bauen.

**Description sieht falsch aus**
→ README.md hat ungültiges Markdown. PyPI nutzt CommonMark. Lokal
mit `python3 -m readme_renderer README.md` testen, wenn das Paket
installiert ist (`pip install readme_renderer`).

---

## Quick-Check vor dem echten Upload

Letzte Diagnose-Befehle:

```bash
cd /pfad/zu/aion-clinical

# 1. Build sauber?
rm -rf dist build *.egg-info
python3 -m build
ls -lh dist/
# Erwartung: 2 Files, sdist + wheel, Größen plausibel

# 2. Metadaten korrekt?
python3 -m twine check dist/*
# Erwartung: 2× PASSED

# 3. Wheel installierbar?
python3 -m venv /tmp/aion-test
/tmp/aion-test/bin/pip install dist/*.whl
/tmp/aion-test/bin/aion --version
# Erwartung: aion 1.10.1

# 4. Tests laufen aus dem installierten Wheel?
/tmp/aion-test/bin/pip install pytest
/tmp/aion-test/bin/python -m pytest /pfad/zu/aion-clinical/tests/ -x
# Erwartung: 364 passed
```

Wenn alle vier durchgehen: bereit für Phase 2.

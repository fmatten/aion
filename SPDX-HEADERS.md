# SPDX Header Templates

**Das Werkzeug ist die Referenz, diese Datei bildet es ab.** Maßgeblich ist
`tools/add_license_headers.py` (Konstanten `HEADER_PYTHON` / `HEADER_INI`); dieses
Dokument beschreibt, was das Werkzeug schreibt, und schreibt es nicht vor. Weichen
beide voneinander ab, gilt das Werkzeug — und die Abweichung ist ein Fehler *dieser*
Datei. Wer den Kopf von Hand setzt, nimmt den Wortlaut unten; wer viele Dateien
versorgt, lässt das Werkzeug laufen.

*Warum die Richtung so festgelegt ist: Am 28.08.2026 sind über eine abweichende
Vorlage 119 falsche Köpfe entstanden (Lizenz-Bericht, Befund B-2). Eine Vorlage, die
von dem abweicht, was tatsächlich geschrieben wird, erzeugt genau so lange falsche
Köpfe, wie jemand aus ihr abschreibt.*

## Python

```python
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

## INI / systemd-Units

```ini
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
#
```

## Markdown / Text

```text
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

## TOML

```toml
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

## Vier Stellen, an denen es regelmäßig verrutscht

1. **Reihenfolge:** `SPDX-FileCopyrightText` steht **vor** `SPDX-License-Identifier`.
2. **`SPDX-FileCopyrightText`, nicht `Copyright (c)`.** Nur die SPDX-Form ist
   maschinenlesbar; `reuse`, `scancode` und die Hauswerkzeuge finden die andere nicht.
3. **Das Jahr gehört dazu** — `2026`, ohne Bereich und ohne `(c)`.
4. **Firmenschreibweise `ISCaD`:** großes I, großes C, kleines a, großes D. Die
   Variante mit kleinem c und kleinem d ist ein bekannter Tippfehler. `only`, nicht
   `or-later`; das `ISCaD` gehört in die LicenseRef hinein.
   (Siehe `aion-doku/CONVENTIONS.md`, Abschnitt Lizenz — dort steht die
   **Lizenzkennung** als Vorschrift, hier die **Kopfform**.)

## Wichtiger Hinweis

`LicenseRef-ISCaD-Commercial` ist eine lokale SPDX-Lizenzreferenz für den getrennten
kommerziellen Lizenzweg. Sie ersetzt die kommerzielle Vereinbarung selbst nicht.

## Reichweite dieses Dokuments

Es beschreibt die Kopfform. Es sagt **nichts** über die Lizenzangabe in
`pyproject.toml`, `CITATION.cff` oder `LICENSE*`-Dateien — diese führen eigene
Felder mit eigenen Regeln und sind hier bewusst nicht geregelt.

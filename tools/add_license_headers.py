#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""Fügt SPDX-Lizenz-Header in alle Source-Dateien ein.

Idempotent: bereits vorhandene Header werden nicht dupliziert.

Hybrid-Stil (Option C): SPDX-Header oben, danach bestehender Modul-
Docstring unverändert.

Verwendung:
    python tools/add_license_headers.py [--check]

  --check: Nur prüfen, was geändert würde — keine Schreibvorgänge.
           Exit-Code 0 = alles ok, 1 = es gibt Dateien ohne Header.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


HEADER_PYTHON = """\
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""

HEADER_INI = """\
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
#
"""


# Marker-String, an dem Header erkannt wird (idempotent)
SPDX_MARKER = "SPDX-License-Identifier: EUPL-1.2"


# Welche Dateien werden gepatched (Glob-Pattern relativ zum Repo-Root)
SOURCE_PATTERNS = [
    "src/aion/**/*.py",
    "tests/*.py",
    "examples/*.py",
    "tools/*.py",
    "vorfuehrung.py",
]

INI_PATTERNS = [
    "systemd/*.service",
]

# Verzeichnisse, die ignoriert werden
EXCLUDE_DIR_PARTS = {
    "__pycache__", ".pytest_cache", "venv", "build", "dist",
    ".git", "node_modules",
}


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_PARTS for part in path.parts)


def add_python_header(content: str) -> Optional[str]:
    """Fügt Python-Header hinzu. Liefert neuen Inhalt oder None
    wenn Header schon vorhanden."""
    if SPDX_MARKER in content[:500]:
        return None  # Schon da

    lines = content.splitlines(keepends=True)
    insert_at = 0

    # Shebang in der ersten Zeile? Dann darunter einsetzen
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    # Coding-Hint in der ersten Zeile?
    elif lines and ("coding:" in lines[0] or "coding=" in lines[0]):
        insert_at = 1

    new_lines = lines[:insert_at] + [HEADER_PYTHON] + lines[insert_at:]
    return "".join(new_lines)


def add_ini_header(content: str) -> Optional[str]:
    """systemd-Service: Header oben."""
    if SPDX_MARKER in content[:500]:
        return None
    return HEADER_INI + content


def find_files(repo_root: Path) -> tuple[list[Path], list[Path]]:
    """Findet alle Python- und INI-Source-Dateien."""
    py_files: list[Path] = []
    ini_files: list[Path] = []

    for pattern in SOURCE_PATTERNS:
        for f in repo_root.glob(pattern):
            if f.is_file() and not is_excluded(f.relative_to(repo_root)):
                py_files.append(f)

    for pattern in INI_PATTERNS:
        for f in repo_root.glob(pattern):
            if f.is_file() and not is_excluded(f.relative_to(repo_root)):
                ini_files.append(f)

    return sorted(py_files), sorted(ini_files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                         help="Nur prüfen, nicht schreiben")
    parser.add_argument("--repo-root", type=Path,
                         default=Path(__file__).resolve().parent.parent,
                         help="Repo-Root (Default: Eltern-Verzeichnis von tools/)")
    args = parser.parse_args()

    repo_root = args.repo_root
    py_files, ini_files = find_files(repo_root)

    n_total = len(py_files) + len(ini_files)
    n_changed = 0
    n_already = 0
    missing: list[Path] = []

    for f in py_files:
        try:
            content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"  ⚠ skip (encoding): {f.relative_to(repo_root)}")
            continue
        new_content = add_python_header(content)
        if new_content is None:
            n_already += 1
            continue
        if args.check:
            missing.append(f)
            continue
        f.write_text(new_content, encoding="utf-8")
        n_changed += 1

    for f in ini_files:
        try:
            content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new_content = add_ini_header(content)
        if new_content is None:
            n_already += 1
            continue
        if args.check:
            missing.append(f)
            continue
        f.write_text(new_content, encoding="utf-8")
        n_changed += 1

    if args.check:
        if missing:
            print(f"✗ {len(missing)} Datei(en) OHNE SPDX-Header:")
            for f in missing:
                print(f"    {f.relative_to(repo_root)}")
            return 1
        print(f"✓ Alle {n_total} Source-Dateien haben SPDX-Header")
        return 0

    print(f"Source-Dateien insgesamt: {n_total}")
    print(f"  bereits Header:          {n_already}")
    print(f"  Header eingefügt:        {n_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

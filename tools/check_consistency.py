# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Konsistenz-Check: findet hardcodierte Version-Strings, die abweichen können.

Lauf:
    python tools/check_consistency.py

Bricht mit Exit-Code 1 ab, wenn Diskrepanzen gefunden werden.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def get_canonical_version() -> str:
    """Liest die kanonische Version aus pyproject.toml."""
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Version in pyproject.toml nicht gefunden")
    return match.group(1)


def find_version_strings_in_file(path: Path) -> list[tuple[int, str]]:
    """Liefert alle Stellen, an denen 'v0.x.y' oder 'v1.x.y' Strings hardcodiert sind."""
    findings: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return findings
    # Sucht v?.?.? oder X.Y.Z in Anführungszeichen — pragmatisch
    pattern = re.compile(r'v?\d+\.\d+\.\d+')
    for line_num, line in enumerate(text.splitlines(), start=1):
        for m in pattern.finditer(line):
            findings.append((line_num, m.group(0)))
    return findings


def check_versions(canonical: str) -> list[str]:
    """Sucht abweichende Versions-Strings in Source/Doku."""
    root = Path(__file__).resolve().parent.parent
    issues: list[str] = []

    # Akzeptierte Versionen: aktuelle, plus Migrations-Hinweise im Code
    # ("DBs aus < 0.3.0" ist ok, weil es ein historischer Fakt ist)
    bare = canonical.lstrip("v")
    accepted = {bare, f"v{bare}"}

    # Plus: Mindest-Versionen von Dependencies aus pyproject.toml ignorieren
    # (PyYAML>=6.0, PySide6>=6.5 etc.)
    dep_pattern = re.compile(r'>=\s*\d+\.\d+')

    paths_to_check = (
        list(root.glob("*.md"))
        + list((root / "src").rglob("*.py"))
        + list((root / "examples").rglob("*.py"))
        + list((root / "tools").rglob("*.py"))
    )

    for path in paths_to_check:
        # CHANGELOG enthält historische Versionsnummern absichtlich
        if path.name == "CHANGELOG.md":
            continue
        if "__pycache__" in str(path) or path.name == Path(__file__).name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_num, line in enumerate(text.splitlines(), start=1):
            # Dependency-Zeilen ignorieren
            if dep_pattern.search(line) and (">=" in line or "Mindestversion" in line):
                continue
            # Python-Versionen ignorieren (3.10, 3.11, 3.12, 3.13)
            if re.search(r'(?<!\d)3\.\d+(?:\.\d+)?(?!\d)', line) and "python" in line.lower():
                continue
            # AION-Version-Strings suchen
            for m in re.finditer(r'(?:v|AION\s+|version[^=]*=\s*"|Version\s+)(\d+\.\d+\.\d+)', line):
                ver = m.group(1)
                if ver not in accepted and not ver.startswith("3."):
                    # Ausnahme: historische Migrations-Hinweise mit < oder "vor" oder "seit"
                    context_before = line[:m.start()]
                    if any(marker in context_before.lower() for marker in ("<", "vor ", "seit ", "ab ", "<=")):
                        continue
                    # Ausnahme: historische "AION 1.x.0 bringt/führt ein"-Hinweise
                    context_after = line[m.end():]
                    if any(marker in context_after for marker in
                           (" bringt", " brachte", " führte", " führt", " enthielt",
                            " enthält", " liest", " war", " hatte")):
                        continue
                    rel = path.relative_to(root)
                    issues.append(f"  {rel}:{line_num}  fand '{ver}', erwartet '{bare}'")
                    issues.append(f"      → {line.strip()[:100]}")

    return issues


def check_spdx_headers() -> list[str]:
    """Prüft, ob alle Source-Dateien SPDX-Header tragen.

    Nutzt tools/add_license_headers.py im --check-Modus.
    """
    import subprocess
    repo_root = Path(__file__).resolve().parent.parent
    helper = repo_root / "tools" / "add_license_headers.py"
    if not helper.exists():
        return []  # Tool nicht da — Check übersprungen
    try:
        result = subprocess.run(
            [sys.executable, str(helper), "--check"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
    except Exception as e:
        return [f"  SPDX-Check fehlgeschlagen: {e}"]
    if result.returncode != 0:
        # Output enthält die Liste
        return [
            "  SPDX-Header fehlen in einigen Source-Dateien:",
            result.stdout.strip(),
        ]
    return []


def main() -> int:
    print("Konsistenz-Check der Versions-Strings\n" + "─" * 50)

    try:
        canonical = get_canonical_version()
    except Exception as e:
        print(f"{RED}✗ Kanonische Version nicht ermittelbar: {e}{RESET}")
        return 1

    print(f"Kanonische Version aus pyproject.toml: {GREEN}{canonical}{RESET}\n")

    issues = check_versions(canonical)
    issues.extend(check_spdx_headers())

    if not issues:
        print(f"{GREEN}✓ Alle Versions-Strings konsistent, alle SPDX-Header vorhanden.{RESET}")
        return 0

    print(f"{RED}✗ {len(issues)//2} Diskrepanz(en) gefunden:{RESET}\n")
    for issue in issues:
        print(issue)
    return 1


if __name__ == "__main__":
    sys.exit(main())

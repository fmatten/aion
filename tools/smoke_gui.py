# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""Smoke-Test für die GUI: lädt alle Tabs im Offscreen-Modus.

Zweck: prüfen, ob auf einem fremden Rechner (z. B. Vorführungs-Laptop)
PySide6 sauber installiert ist und die App ohne Fehler startet.

Lauf:
    PYTHONPATH=src python tools/smoke_gui.py

Setzt automatisch QT_QPA_PLATFORM=offscreen, damit kein Display nötig ist.
Bricht mit Exit-Code 1 ab, wenn etwas nicht lädt.
"""
from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    # Offscreen-Modus erzwingen — kein Display nötig
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    print("GUI-Smoke-Test\n" + "─" * 40)

    # ── 1. PySide6 importierbar? ──
    try:
        import PySide6
        print(f"✓ PySide6 importiert (Version {PySide6.__version__})")
    except ImportError:
        print("✗ PySide6 fehlt. Installation: pip install -e \".[gui]\"")
        return 1

    from PySide6.QtWidgets import QApplication

    # ── 2. AION-Modul importierbar? ──
    try:
        import aion
        print(f"✓ aion importiert (Version {aion.__version__})")
    except ImportError as e:
        print(f"✗ aion-Modul: {e}")
        return 1

    # ── 3. Hauptfenster konstruierbar? ──
    try:
        from aion.gui.app import AIONApp
        app = QApplication.instance() or QApplication(sys.argv)
        win = AIONApp(":memory:")
        print(f"✓ Hauptfenster instanziiert ({win.tabs.count()} Tabs)")
    except Exception as e:
        print(f"✗ AIONApp konstruieren: {e}")
        traceback.print_exc()
        return 1

    # ── 4. Alle Tabs laden ──
    expected_tabs = [
        "Typ-Hierarchie", "Ereignisse", "Allen-Relationen",
        "Kausalgraph", "Schema-Editor",
    ]
    actual = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    if actual != expected_tabs:
        print(f"✗ Tab-Liste weicht ab: {actual}")
        return 1
    for name in actual:
        print(f"  ✓ Tab '{name}' geladen")

    # ── 5. Schema-Loader funktioniert ──
    try:
        from pathlib import Path
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "clinical_base.yaml"
        if schema_path.exists():
            from aion.core.types import TypeHierarchy
            h = TypeHierarchy.from_yaml(str(schema_path))
            win._set_hierarchy(h)
            win.tab_schema.refresh()
            print(f"✓ clinical_base.yaml lädt ({len(h)} Typen)")
        else:
            print("⚠️  clinical_base.yaml nicht gefunden — Schema-Test übersprungen")
    except Exception as e:
        print(f"✗ Schema-Loader: {e}")
        return 1

    # ── 6. Causal-Beispiel laden ──
    try:
        if hasattr(win.tab_causal, "_load_example"):
            win.tab_causal._load_example()
            n = len(win.tab_causal.graph.nodes())
            print(f"✓ Causal-Beispiel ({n} Knoten)")
    except Exception as e:
        print(f"✗ Causal-Beispiel: {e}")
        return 1

    # ── 7. Event-Loop startet kurz ──
    try:
        app.processEvents()
        print("✓ Event-Loop reagiert")
    except Exception as e:
        print(f"✗ Event-Loop: {e}")
        return 1

    print("\n✅ GUI ist startfähig. Auf diesem Rechner sollte 'aion-gui' funktionieren.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

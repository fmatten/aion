# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-Iscad-Commercial
"""AION Clinical — Kommandozeilen-Werkzeug.

Subcommands:
    aion validate <schema.yaml>      Schema-Hierarchie validieren
    aion types <schema.yaml>         Typhierarchie als Baum ausgeben
    aion import <bundle.json> [--db patients.db]
                                     FHIR-Bundle importieren
    aion export <db> [--patient ID] [--out file.json]
                                     DB-Inhalt als FHIR-Bundle exportieren
    aion mine <db> [--min-support 0.5] [--min-length 2] [--max-length 5]
                                     Pattern-Mining auf Patientensequenzen
    aion stats <db>                  Statistik der Datenbank
    aion --version                   Versionsausgabe

Designentscheidungen:
    * stdlib-only — argparse, kein click oder typer
    * Stille Defaults — keine Banner, keine Werbung
    * Exit-Codes: 0 = ok, 1 = Fehler, 2 = ungültige Argumente
    * FHIR-Subcommands brauchen `[fhir]`-Extra; sauberer Fehler wenn fehlt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from aion import __version__
from aion.core.logging_setup import setup_logging, get_logger

log = get_logger(__name__)


# ────────────────────────────────────────────────────────────────────
#  Subcommands
# ────────────────────────────────────────────────────────────────────
def cmd_config(args: argparse.Namespace) -> int:
    """Konfigurations-Validierung und -Anzeige."""
    from aion.config import load_config, AionConfig, ConfigError

    if args.config_action == "validate":
        path = Path(args.path)
        if not path.exists():
            print(f"FEHLER: Datei nicht gefunden: {path}", file=sys.stderr)
            return 1
        try:
            cfg = load_config(path)
            print(f"✓ Konfiguration {path.name} valide")
            return 0
        except ConfigError as e:
            print(f"✗ Konfiguration ungültig:", file=sys.stderr)
            print(str(e), file=sys.stderr)
            return 1
        except FileNotFoundError as e:
            print(f"FEHLER: {e}", file=sys.stderr)
            return 1

    if args.config_action == "show":
        # Lädt aus optional angegebener Datei oder Defaults
        try:
            if args.path:
                cfg = load_config(args.path)
            else:
                cfg = load_config()  # nutzt $AION_CONFIG_FILE oder Defaults
        except ConfigError as e:
            print(f"FEHLER: {e}", file=sys.stderr)
            return 1
        except FileNotFoundError as e:
            print(f"FEHLER: {e}", file=sys.stderr)
            return 1

        # YAML-Dump
        try:
            import yaml
            print(yaml.safe_dump(cfg.to_dict(), default_flow_style=False,
                                 sort_keys=False, allow_unicode=True))
        except ImportError:
            # Fallback ohne YAML: pretty-print Dict
            import json
            print(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"Unbekannte config-Aktion: {args.config_action}", file=sys.stderr)
    return 2


def cmd_mllp_listen(args: argparse.Namespace) -> int:
    """Startet den MLLP-Listener (Long-Running, blockt bis Strg+C)."""
    from aion.hl7v2.mllp import serve_mllp
    from aion import SQLiteEventStore, AuditLog

    print(f"AION MLLP-Listener {__version__}")
    print(f"Lausche auf {args.host}:{args.port}")
    print(f"Datenbank: {args.db}")
    if args.audit:
        print(f"Audit:     {args.audit}")

    # Auth optional
    auth_backend = None
    if args.auth_keys:
        from aion.auth import APIKeyBackend
        auth_backend = APIKeyBackend(args.auth_keys)
        print(f"Auth:      apikey ({args.auth_keys}, "
              f"required_role={args.auth_role or '—'})")
    print(f"\nStrg+C zum Beenden.\n")

    audit = AuditLog(args.audit) if args.audit else None
    try:
        with SQLiteEventStore(args.db) as store:
            serve_mllp(
                host=args.host,
                port=args.port,
                store=store,
                audit=audit,
                auth_backend=auth_backend,
                required_role=args.auth_role,
                block=True,
            )
    finally:
        if audit is not None:
            audit.close()
    return 0


def cmd_auth_keygen(args: argparse.Namespace) -> int:
    """Erzeugt einen neuen API-Key und gibt ihn aus.

    KLARTEXT-AUSGABE — der Operator muss den Key sicher übermitteln und
    in eine YAML-Datei einfügen (gehashed).
    """
    from aion.auth import generate_api_key, hash_api_key
    import yaml

    key = generate_api_key()
    h = hash_api_key(key)

    # Klartext-Ausgabe nur einmal
    print("=" * 70)
    print("⚠  NEUEN API-KEY ERZEUGT — DIESEN KEY EINMALIG SICHER ÜBERMITTELN")
    print("=" * 70)
    print()
    print(f"  Klartext-Key (für den Sender, z. B. Mirth-Channel):")
    print(f"    {key}")
    print()
    print(f"  Eintrag für /etc/aion/api-keys.yaml (für AION-Server):")
    print()
    yaml_entry = {
        "name": args.name,
        "hash": h,
        "roles": args.roles.split(",") if args.roles else [],
    }
    if args.expires:
        yaml_entry["expires"] = args.expires
    print(yaml.safe_dump({"keys": [yaml_entry]},
                          default_flow_style=False, allow_unicode=True))
    print("=" * 70)
    print("Den Klartext-Key NICHT in Git, Backups oder unverschlüsselte Dateien!")
    return 0


def cmd_auth_verify(args: argparse.Namespace) -> int:
    """Prüft einen API-Key gegen die Key-Datei."""
    from aion.auth import APIKeyBackend, APIKeyCredentials, AuthError
    import getpass

    try:
        backend = APIKeyBackend(args.keyfile)
    except Exception as e:
        print(f"FEHLER: {e}", file=sys.stderr)
        return 1

    if args.key:
        key = args.key
    else:
        # Sicherer Eingabemodus (kein Echo)
        key = getpass.getpass("API-Key: ")

    try:
        principal = backend.authenticate(APIKeyCredentials(key))
    except AuthError as e:
        print(f"✗ Auth fehlgeschlagen: {e}")
        return 1

    print(f"✓ Authentifiziert als: {principal.user_id}")
    print(f"  Display-Name: {principal.display_name}")
    print(f"  Backend:      {principal.backend}")
    print(f"  Rollen:       {sorted(principal.roles) or '—'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Schema-YAML laden und auf Konsistenz prüfen."""
    from aion import TypeHierarchy, check_inheritance_conflicts

    path = Path(args.schema)
    if not path.exists():
        print(f"FEHLER: Datei nicht gefunden: {path}", file=sys.stderr)
        return 1

    try:
        h = TypeHierarchy.from_yaml(str(path))
    except ImportError:
        print("FEHLER: PyYAML nicht installiert. Installation: pip install PyYAML",
              file=sys.stderr)
        return 1
    except Exception as e:
        print(f"FEHLER beim Laden: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"✓ Schema geladen: {len(h)} Typen aus {path.name}")

    report = check_inheritance_conflicts(h)
    if report.ok:
        print("✓ Keine Multi-Inheritance-Konflikte")
        return 0

    print(f"✗ {len(report.conflicts)} Konflikt(e) gefunden:", file=sys.stderr)
    for conflict in report.conflicts:
        print(f"  - {conflict}", file=sys.stderr)
    return 1


def cmd_types(args: argparse.Namespace) -> int:
    """Typhierarchie als Baum ausgeben."""
    from aion import TypeHierarchy

    path = Path(args.schema)
    if not path.exists():
        print(f"FEHLER: Datei nicht gefunden: {path}", file=sys.stderr)
        return 1

    try:
        h = TypeHierarchy.from_yaml(str(path))
    except Exception as e:
        print(f"FEHLER: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    def print_subtree(name: str, depth: int = 0) -> None:
        indent = "  " * depth
        node = h.get(name)
        attrs = f"  [{', '.join(node.attributes)}]" if node.attributes else ""
        print(f"{indent}{name}{attrs}")
        for child in sorted(h.children_of(name)):
            print_subtree(child, depth + 1)

    # Wurzeln: Typen direkt unter ⊤
    if h.has("⊤"):
        roots = sorted(h.children_of("⊤"))
    else:
        roots = sorted(n for n in h.all_types() if not h.parents_of(n))
    for root in roots:
        print_subtree(root)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Statistik einer SQLite-DB ausgeben."""
    from aion import SQLiteEventStore

    path = Path(args.db)
    if not path.exists() and args.db != ":memory:":
        print(f"FEHLER: Datenbank nicht gefunden: {path}", file=sys.stderr)
        return 1

    with SQLiteEventStore(args.db) as store:
        all_events = store.all()
        if not all_events:
            print("Datenbank ist leer.")
            return 0

        # Patienten zählen
        patients = {e.patient_id for e in all_events}

        # Typen zählen
        type_counts: dict[str, int] = {}
        for e in all_events:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1

        # Relationen zählen
        n_refs = sum(len(e.references) for e in all_events)

        print(f"Datenbank: {path.name}")
        print(f"  Ereignisse:    {len(all_events):>6,}")
        print(f"  Patienten:     {len(patients):>6,}")
        print(f"  Beziehungen:   {n_refs:>6,}")
        print(f"  Ereignistypen: {len(type_counts):>6,}")
        print(f"\nTop-10-Typen:")
        for typ, n in sorted(type_counts.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {n:>6,}  {typ}")
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    """Pattern-Mining auf Patientensequenzen."""
    from aion import SQLiteEventStore, TCFG

    path = Path(args.db)
    if not path.exists() and args.db != ":memory:":
        print(f"FEHLER: Datenbank nicht gefunden: {path}", file=sys.stderr)
        return 1

    with SQLiteEventStore(args.db) as store:
        # Sequenzen pro Patient bauen
        all_events = store.all()
        if not all_events:
            print("Datenbank leer — nichts zu minen.", file=sys.stderr)
            return 1

        sequences: dict[str, list] = {}
        for e in sorted(all_events, key=lambda x: x.t_start):
            sequences.setdefault(e.patient_id, []).append(e.event_type)
        sequence_list = list(sequences.values())

        print(f"Mining auf {len(sequence_list)} Patienten-Sequenzen…")
        patterns = TCFG.mine_patterns(
            sequence_list,
            min_length=args.min_length,
            max_length=args.max_length,
            min_support=args.min_support,
        )

    if not patterns:
        print(f"Keine Patterns gefunden (min_support={args.min_support}).")
        return 0

    print(f"\n{len(patterns)} frequente Phasen (Support ≥ {args.min_support:.0%}):")
    print(f"{'Support':>8s}  Phase")
    for pattern, support in patterns.items():
        chain = " → ".join(pattern)
        print(f"{support:>7.0%}   {chain}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """FHIR-Bundle in DB importieren.

    Modus:
        --synthea: nutzt aion.synthea (mit Code-Mapping, Encounter-Auflösung)
        --hl7v2:   nutzt aion.hl7v2 (HL7-v2-Parser für Datei oder Verzeichnis)
        sonst:     nutzt aion.fhir.from_fhir_bundle (direktes FHIR-Mapping)
    """
    path = Path(args.bundle)
    if not path.exists():
        print(f"FEHLER: Bundle nicht gefunden: {path}", file=sys.stderr)
        return 1

    from aion import SQLiteEventStore

    if args.hl7v2:
        # HL7-v2-Importer (stdlib-only)
        from aion.hl7v2 import (
            hl7v2_import_file, hl7v2_import_directory,
        )
        try:
            if path.is_dir():
                events = hl7v2_import_directory(path, limit=args.limit)
            else:
                events = hl7v2_import_file(path)
        except Exception as e:
            print(f"FEHLER: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    elif args.synthea:
        # Synthea-Importer (stdlib-only)
        from aion.synthea import (
            synthea_import_bundle, synthea_import_directory,
        )
        try:
            if path.is_dir():
                events = synthea_import_directory(path, limit=args.limit)
            else:
                events = synthea_import_bundle(path)
        except Exception as e:
            print(f"FEHLER: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    else:
        # Generischer FHIR-Importer (braucht fhir.resources)
        from aion import has_fhir
        if not has_fhir():
            print("FEHLER: fhir.resources nicht installiert. Installation: pip install -e \".[fhir]\"",
                  file=sys.stderr)
            return 1

        from aion.fhir import from_fhir_bundle
        from aion.fhir.bundle import bundle_from_file

        try:
            bundle = bundle_from_file(str(path))
        except Exception as e:
            print(f"FEHLER beim Lesen des Bundles: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1
        try:
            events = from_fhir_bundle(bundle)
        except Exception as e:
            print(f"FEHLER bei Bundle-Konvertierung: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1

    with SQLiteEventStore(args.db) as store:
        store.add_many(events)
        total = store.count()

    print(f"✓ {len(events)} Events aus {path.name} importiert.")
    print(f"  Datenbank {args.db} hat jetzt {total} Events insgesamt.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """DB-Inhalt als FHIR-Bundle exportieren."""
    from aion import has_fhir
    if not has_fhir():
        print("FEHLER: fhir.resources nicht installiert. Installation: pip install -e \".[fhir]\"",
              file=sys.stderr)
        return 1

    from aion import SQLiteEventStore
    from aion.fhir import to_fhir_bundle
    from aion.fhir.bundle import bundle_to_file

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"FEHLER: Datenbank nicht gefunden: {db_path}", file=sys.stderr)
        return 1

    with SQLiteEventStore(args.db) as store:
        if args.patient:
            events = store.find_by_patient(args.patient)
        else:
            events = store.all()

    if not events:
        print("Keine Events zum Exportieren gefunden.", file=sys.stderr)
        return 1

    bundle = to_fhir_bundle(events)
    out_path = Path(args.out) if args.out else Path("aion-export.json")
    bundle_to_file(bundle, str(out_path))

    print(f"✓ {len(events)} Events nach {out_path.name} geschrieben "
          f"({len(bundle.entry)} FHIR-Resources).")
    return 0


# ────────────────────────────────────────────────────────────────────
#  Argparser
# ────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aion",
        description="AION Clinical — Kommandozeilen-Werkzeug",
    )
    parser.add_argument("--version", action="version",
                        version=f"aion {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Debug-Logging aktivieren")

    sub = parser.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    # config
    p_cfg = sub.add_parser("config", help="Konfigurations-Verwaltung")
    p_cfg_sub = p_cfg.add_subparsers(dest="config_action", required=True,
                                       metavar="ACTION")
    p_cfg_val = p_cfg_sub.add_parser("validate",
                                       help="YAML-Konfiguration validieren")
    p_cfg_val.add_argument("path", help="Pfad zur YAML-Datei")
    p_cfg_show = p_cfg_sub.add_parser("show",
                                        help="Aktive Konfiguration anzeigen")
    p_cfg_show.add_argument("path", nargs="?", default=None,
                             help="Optional: YAML-Datei laden statt Defaults")
    p_cfg.set_defaults(func=cmd_config)

    # validate
    p_val = sub.add_parser("validate", help="Schema-YAML validieren")
    p_val.add_argument("schema", help="Pfad zur YAML-Datei")
    p_val.set_defaults(func=cmd_validate)

    # types
    p_typ = sub.add_parser("types", help="Typhierarchie als Baum ausgeben")
    p_typ.add_argument("schema", help="Pfad zur YAML-Datei")
    p_typ.set_defaults(func=cmd_types)

    # stats
    p_stat = sub.add_parser("stats", help="Statistik einer Datenbank")
    p_stat.add_argument("db", help="Pfad zur SQLite-DB")
    p_stat.set_defaults(func=cmd_stats)

    # mine
    p_min = sub.add_parser("mine", help="Pattern-Mining auf DB-Sequenzen")
    p_min.add_argument("db", help="Pfad zur SQLite-DB")
    p_min.add_argument("--min-support", type=float, default=0.5,
                       help="Minimaler Support (default 0.5)")
    p_min.add_argument("--min-length", type=int, default=2,
                       help="Minimale Pattern-Länge (default 2)")
    p_min.add_argument("--max-length", type=int, default=5,
                       help="Maximale Pattern-Länge (default 5)")
    p_min.set_defaults(func=cmd_mine)

    # import
    p_imp = sub.add_parser("import", help="FHIR-Bundle importieren")
    p_imp.add_argument("bundle",
                       help="Pfad zum FHIR-Bundle (JSON) oder Verzeichnis (mit --synthea)")
    p_imp.add_argument("--db", default="aion.db",
                       help="Ziel-Datenbank (default: aion.db)")
    p_imp.add_argument("--synthea", action="store_true",
                       help="Synthea-Importer nutzen (Code-Mapping, "
                            "Encounter-Auflösung, Verzeichnis-Batch)")
    p_imp.add_argument("--hl7v2", action="store_true",
                       help="HL7-v2-Datei-Importer (ADT, ORU)")
    p_imp.add_argument("--limit", type=int, default=None,
                       help="Bei --synthea/--hl7v2 + Verzeichnis: max. Bundles/Dateien")
    p_imp.set_defaults(func=cmd_import)

    # mllp-listen
    p_mllp = sub.add_parser("mllp-listen",
                             help="HL7-v2 MLLP-Listener starten "
                                  "(Long-Running, blockt bis Strg+C)")
    p_mllp.add_argument("--host", default="0.0.0.0",
                         help="Bind-Adresse (default: 0.0.0.0 = alle Interfaces)")
    p_mllp.add_argument("--port", type=int, default=2575,
                         help="TCP-Port (default: 2575, HL7-v2-Standard)")
    p_mllp.add_argument("--db", default="aion.db",
                         help="Ziel-Datenbank (default: aion.db)")
    p_mllp.add_argument("--audit", default=None,
                         help="Audit-DB (optional, sonst kein Audit-Log)")
    p_mllp.add_argument("--auth-keys", default=None,
                         help="API-Key-Datei (YAML). Aktiviert Auth.")
    p_mllp.add_argument("--auth-role", default=None,
                         help="Erforderliche Rolle des Senders (z. B. 'ingest')")
    p_mllp.set_defaults(func=cmd_mllp_listen)

    # auth-Subcommands
    p_auth = sub.add_parser("auth", help="Auth-Verwaltung")
    p_auth_sub = p_auth.add_subparsers(dest="auth_cmd", required=True)

    p_keygen = p_auth_sub.add_parser("keygen",
                                      help="Neuen API-Key erzeugen")
    p_keygen.add_argument("--name", required=True,
                           help="Sprechender Name für den Key, z. B. 'mirth-1'")
    p_keygen.add_argument("--roles", default="",
                           help="Komma-Liste, z. B. 'ingest,readonly'")
    p_keygen.add_argument("--expires", default=None,
                           help="ISO-Datum YYYY-MM-DD (optional)")
    p_keygen.set_defaults(func=cmd_auth_keygen)

    p_verify = p_auth_sub.add_parser("verify",
                                      help="API-Key gegen Datei prüfen")
    p_verify.add_argument("--keyfile", required=True,
                           help="Pfad zur api-keys.yaml")
    p_verify.add_argument("--key", default=None,
                           help="API-Key zum Prüfen (sonst interaktiv)")
    p_verify.set_defaults(func=cmd_auth_verify)

    # export
    p_exp = sub.add_parser("export", help="DB als FHIR-Bundle exportieren")
    p_exp.add_argument("db", help="Quell-Datenbank")
    p_exp.add_argument("--patient", help="Nur Events dieses Patienten")
    p_exp.add_argument("--out", help="Ziel-JSON-Datei (default: aion-export.json)")
    p_exp.set_defaults(func=cmd_export)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(level="DEBUG" if args.verbose else "WARNING")

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130
    except Exception as e:
        log.exception("Unerwarteter Fehler")
        print(f"FEHLER: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

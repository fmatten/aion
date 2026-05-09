# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: EUPL-1.2
"""HL7 v2.x Parser und Mapper für AION Clinical.

Designentscheidungen (1.8.0):

  * **stdlib-only Parser** — keine externe Dependency wie `hl7apy` oder
    `python-hl7`. Wir parsen die wenigen Felder, die wir wirklich
    brauchen, von Hand. Das macht den Code überschaubar und auditierbar.
  * **Lesart C wie Synthea** — minimales Default-Code-Mapping in
    `aion.hl7v2.codes`, Anwender erweitert via `code_map=`.
  * **Datei-Reader nur** in 1.8.0 — MLLP-Listener kommt in 1.9.0.
    Damit lässt sich der Parser sauber testen, ohne TCP-Mocking.
  * **Encoding-Zeichen aus MSH** — wir respektieren MSH-1 (Field
    Separator) und MSH-2 (Component, Repetition, Escape, Subcomponent).
    Default ist `|^~\\&` aber das ist nicht garantiert.

Beispiel:

    from aion.hl7v2 import parse_messages, hl7v2_import_file

    # Aus String parsen
    raw = open("nachrichten.hl7").read()
    messages = parse_messages(raw)
    for msg in messages:
        print(msg.message_type, msg.trigger_event, msg.patient_id())

    # Direkt zu ClinicalEvents mappen
    events = hl7v2_import_file("nachrichten.hl7")

HL7 v2 Format-Reminder:
    Eine Nachricht besteht aus Segmenten, getrennt durch \\r (CR).
    Jedes Segment beginnt mit einem 3-Buchstaben-Code (MSH, PID, OBX, ...).
    Felder werden mit | getrennt, Komponenten mit ^, Wiederholungen mit ~,
    Subkomponenten mit &. Escape-Zeichen ist \\.

    Pflichtsegment ist MSH (immer das erste). MSH-1 IST der Feldtrenner,
    MSH-2 sind die anderen Encoding-Zeichen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Union

from aion.core.events import ClinicalEvent
from aion.core.logging_setup import get_logger
from aion.hl7v2.codes import lookup_adt, lookup_loinc, fallback_type_name

log = get_logger(__name__)


# Default-Encoding-Zeichen
_DEFAULT_FIELD_SEP = "|"
_DEFAULT_COMPONENT_SEP = "^"
_DEFAULT_REPETITION_SEP = "~"
_DEFAULT_ESCAPE = "\\"
_DEFAULT_SUBCOMPONENT_SEP = "&"


@dataclass
class HL7Message:
    """Eine geparste HL7-v2-Nachricht.

    Wir speichern Segmente als Liste von Listen (Felder als Strings).
    Komponenten/Subkomponenten werden bei Bedarf weiter zerlegt.
    """
    raw: str
    segments: list[list[str]]  # [[MSH, |, ^~\\&, ...], [PID, ...], ...]
    field_sep: str = _DEFAULT_FIELD_SEP
    component_sep: str = _DEFAULT_COMPONENT_SEP
    repetition_sep: str = _DEFAULT_REPETITION_SEP
    escape: str = _DEFAULT_ESCAPE
    subcomponent_sep: str = _DEFAULT_SUBCOMPONENT_SEP

    # ── Bequeme Zugriffsmethoden ─────────────────────────────────
    def segment(self, name: str) -> Optional[list[str]]:
        """Liefert das ERSTE Segment mit gegebenem Namen (z. B. 'PID')."""
        for seg in self.segments:
            if seg and seg[0] == name:
                return seg
        return None

    def all_segments(self, name: str) -> list[list[str]]:
        """Alle Segmente mit gegebenem Namen (z. B. mehrere 'OBX')."""
        return [seg for seg in self.segments if seg and seg[0] == name]

    def field(self, segment_name: str, field_index: int) -> Optional[str]:
        """Liefert ein Feld aus einem Segment.

        Args:
            segment_name: z. B. 'MSH', 'PID', 'OBX'
            field_index: 1-basierter Index. MSH-9 ist der 9. Feldwert
                         (zählt MSH-1 = Feldtrenner mit).

        WICHTIG: HL7-Konvention ist 1-basiert mit MSH-Sonderfall.
        MSH-1 ist der Feldtrenner '|', MSH-2 die anderen Encoding-Zeichen.
        """
        seg = self.segment(segment_name)
        if not seg or field_index >= len(seg):
            return None
        return seg[field_index]

    def get_components(self, value: str) -> list[str]:
        """Zerlegt ein Feld in Komponenten anhand component_sep."""
        if not value:
            return []
        return value.split(self.component_sep)

    # ── Domain-Helfer ────────────────────────────────────────────
    @property
    def message_type(self) -> str:
        """Liefert den Message Type aus MSH-9.1, z. B. 'ADT', 'ORU'."""
        msh9 = self.field("MSH", 9) or ""
        comps = self.get_components(msh9)
        return comps[0] if comps else ""

    @property
    def trigger_event(self) -> str:
        """Liefert das Trigger-Event aus MSH-9.2, z. B. 'A01', 'R01'."""
        msh9 = self.field("MSH", 9) or ""
        comps = self.get_components(msh9)
        return comps[1] if len(comps) > 1 else ""

    def patient_id(self) -> Optional[str]:
        """Liefert die Patient-ID aus PID-3.1.

        PID-3 kann mehrere Identifier enthalten (mit ~). Wir nehmen
        den ersten, weil das der "primary identifier" sein soll.
        """
        pid = self.segment("PID")
        if not pid or len(pid) <= 3:
            return None
        pid3 = pid[3] or ""
        # Mehrere Identifier mit ~ getrennt — den ersten
        first_id = pid3.split(self.repetition_sep)[0]
        # ID-Komponente (1.1) ist der eigentliche Wert
        comps = self.get_components(first_id)
        return comps[0] if comps else None

    @property
    def message_datetime(self) -> Optional[datetime]:
        """MSH-7 — Zeitstempel der Nachricht."""
        return _parse_hl7_datetime(self.field("MSH", 7))

    def event_datetime(self) -> Optional[datetime]:
        """Beste Schätzung für den Ereigniszeitpunkt.

        Priorität:
            1. EVN-2 (Recorded Date/Time) bei ADT
            2. PV1-44 (Admit Date/Time)
            3. OBX-14 (Observation Date/Time)
            4. OBR-7 (Observation Date/Time)
            5. MSH-7 (Message Date/Time) als Fallback
        """
        # EVN-2 für ADT
        evn = self.segment("EVN")
        if evn and len(evn) > 2:
            dt = _parse_hl7_datetime(evn[2])
            if dt: return dt

        # PV1-44 — Admit Date/Time
        pv1 = self.segment("PV1")
        if pv1 and len(pv1) > 44:
            dt = _parse_hl7_datetime(pv1[44])
            if dt: return dt

        # OBX-14 — Observation Date/Time
        obx = self.segment("OBX")
        if obx and len(obx) > 14:
            dt = _parse_hl7_datetime(obx[14])
            if dt: return dt

        # OBR-7
        obr = self.segment("OBR")
        if obr and len(obr) > 7:
            dt = _parse_hl7_datetime(obr[7])
            if dt: return dt

        return self.message_datetime


# ─────────────────────────────────────────────────────────────────────
#  Parser
# ─────────────────────────────────────────────────────────────────────
def _parse_hl7_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parst HL7 v2 Datum/Zeit (Format YYYYMMDDHHMMSS oder Teilformen)."""
    if not value:
        return None
    # Nur Ziffern behalten (Zeitzonen abschneiden)
    s = re.match(r"(\d+)", value.strip())
    if not s:
        return None
    digits = s.group(1)

    formats = [
        ("%Y%m%d%H%M%S", 14),
        ("%Y%m%d%H%M",   12),
        ("%Y%m%d%H",     10),
        ("%Y%m%d",        8),
        ("%Y%m",          6),
        ("%Y",            4),
    ]
    for fmt, n in formats:
        if len(digits) >= n:
            try:
                return datetime.strptime(digits[:n], fmt)
            except ValueError:
                continue
    return None


def parse_message(raw: str) -> HL7Message:
    """Parst eine einzelne HL7-Nachricht (String).

    Args:
        raw: Eine HL7-v2-Nachricht. Segmente getrennt durch \\r oder \\n.

    Returns:
        HL7Message mit den geparsten Segmenten und Encoding-Zeichen.

    Raises:
        ValueError: kein gültiges MSH-Segment am Anfang.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("Leere HL7-Nachricht")

    if not raw.startswith("MSH"):
        raise ValueError(f"Nachricht muss mit MSH beginnen, beginnt mit {raw[:3]!r}")

    # Encoding-Zeichen aus MSH herauslesen — MSH-1 ist der Trenner,
    # also das Zeichen direkt nach 'MSH'.
    field_sep = raw[3]
    # MSH-2: die nächsten 4 Zeichen sind component, repetition, escape, subcomponent
    if len(raw) < 8:
        raise ValueError("MSH zu kurz für Encoding-Zeichen")
    msh2 = raw[4:8]
    component_sep = msh2[0]
    repetition_sep = msh2[1]
    escape = msh2[2]
    subcomponent_sep = msh2[3]

    # Segment-Trennung: \r ist Standard, viele Tools machen \n oder \r\n
    raw_normalized = raw.replace("\r\n", "\r").replace("\n", "\r")
    segments_raw = [s for s in raw_normalized.split("\r") if s.strip()]

    segments: list[list[str]] = []
    for seg_str in segments_raw:
        # MSH ist Sonderfall: das erste Feld IST der Feldtrenner
        if seg_str.startswith("MSH"):
            # Aufteilen, dann den Trenner als zweites Feld einfügen
            parts = seg_str.split(field_sep)
            # parts[0] = "MSH", parts[1] = "^~\&", parts[2] = "sender", ...
            # In HL7 ist MSH-1 = field_sep selbst; wir setzen das ein
            segments.append([parts[0], field_sep] + parts[1:])
        else:
            segments.append(seg_str.split(field_sep))

    return HL7Message(
        raw=raw,
        segments=segments,
        field_sep=field_sep,
        component_sep=component_sep,
        repetition_sep=repetition_sep,
        escape=escape,
        subcomponent_sep=subcomponent_sep,
    )


def parse_messages(raw: str) -> list[HL7Message]:
    """Parst eine Datei mit mehreren HL7-Nachrichten.

    Trennzeichen für Nachrichten: jede neue MSH-Zeile beginnt eine
    neue Nachricht. Manchmal sind Nachrichten durch eine Leerzeile
    getrennt, manchmal direkt.
    """
    if not raw.strip():
        return []

    # Normalisieren und an MSH-Zeilen splitten
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    messages: list[HL7Message] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("MSH") and current:
            # Bisherige Nachricht abschließen
            try:
                messages.append(parse_message("\r".join(current)))
            except ValueError as e:
                log.warning("Nachricht übersprungen: %s", e)
            current = [line]
        elif line.strip() or current:
            current.append(line)

    # Letzte Nachricht
    if current:
        try:
            messages.append(parse_message("\r".join(current)))
        except ValueError as e:
            log.warning("Nachricht übersprungen: %s", e)

    return messages


# ─────────────────────────────────────────────────────────────────────
#  Mapping HL7 → ClinicalEvent
# ─────────────────────────────────────────────────────────────────────
def _resolve_event_type(
    msg: HL7Message,
    code_map: Optional[dict[str, str]] = None,
) -> str:
    """Bestimmt AION-Typname aus der HL7-Nachricht."""
    mtype = msg.message_type
    trigger = msg.trigger_event

    # ADT: Trigger-Event direkt gemappt
    if mtype == "ADT":
        if code_map and trigger in code_map:
            return code_map[trigger]
        mapped = lookup_adt(trigger)
        if mapped:
            return mapped
        return fallback_type_name(mtype, trigger)

    # ORU: OBX-3.1 ist der LOINC-Code
    if mtype == "ORU":
        obx = msg.segment("OBX")
        if obx and len(obx) > 3:
            obx3 = obx[3] or ""
            comps = msg.get_components(obx3)
            if comps:
                code = comps[0]
                mapped = lookup_loinc(code, extra_map=code_map)
                if mapped:
                    return mapped
        return fallback_type_name(mtype, trigger)

    # Andere: einfach Fallback
    return fallback_type_name(mtype, trigger)


def _extract_attributes(msg: HL7Message) -> dict[str, Any]:
    """Bündelt Werte als AION-Attribute aus den Segmenten."""
    attrs: dict[str, Any] = {}

    # OBX (Observation): OBX-2 = Datentyp, OBX-3 = Code, OBX-5 = Wert, OBX-6 = Einheit
    obx = msg.segment("OBX")
    if obx:
        if len(obx) > 5 and obx[5]:
            value_str = obx[5]
            # Bei NM (Numeric) nach float konvertieren
            if len(obx) > 2 and obx[2] == "NM":
                try:
                    attrs["value"] = float(value_str)
                except ValueError:
                    attrs["value"] = value_str
            else:
                attrs["value"] = value_str
        if len(obx) > 6 and obx[6]:
            unit_comps = msg.get_components(obx[6])
            attrs["unit"] = unit_comps[0] if unit_comps else obx[6]
        if len(obx) > 3 and obx[3]:
            comps = msg.get_components(obx[3])
            if comps:
                attrs["loinc_code"] = comps[0]
                if len(comps) > 1:
                    attrs["loinc_display"] = comps[1]

    # PV1 — Patient-Visit
    pv1 = msg.segment("PV1")
    if pv1:
        if len(pv1) > 2 and pv1[2]:
            attrs["patient_class"] = pv1[2]   # I=Inpatient, O=Outpatient, E=Emergency
        if len(pv1) > 3 and pv1[3]:
            comps = msg.get_components(pv1[3])
            if comps and comps[0]:
                attrs["station"] = comps[0]   # Point of Care

    return attrs


def _extract_stay_period(msg: HL7Message) -> tuple[Optional[datetime], Optional[datetime]]:
    """Bestimmt stay_start/stay_end aus PV1 oder MSH."""
    pv1 = msg.segment("PV1")
    if pv1:
        # PV1-44 Admit Date/Time, PV1-45 Discharge Date/Time
        if len(pv1) > 44:
            start = _parse_hl7_datetime(pv1[44])
            end = _parse_hl7_datetime(pv1[45]) if len(pv1) > 45 else None
            return start, end
    return None, None


def message_to_event(
    msg: HL7Message,
    *,
    code_map: Optional[dict[str, str]] = None,
) -> Optional[ClinicalEvent]:
    """Mappt eine HL7-Nachricht auf einen ClinicalEvent.

    Returns:
        ClinicalEvent, oder None wenn essentielle Daten fehlen
        (Patient-ID, Zeit).
    """
    pid = msg.patient_id()
    if not pid:
        log.debug("Nachricht ohne Patient-ID übersprungen: %s",
                  msg.message_type)
        return None

    t_event = msg.event_datetime()
    if not t_event:
        log.debug("Nachricht ohne Zeitstempel übersprungen: %s",
                  msg.message_type)
        return None

    stay_start, stay_end = _extract_stay_period(msg)
    if not stay_start:
        # Konservativ: Stay = Event ± 1h (so wie bei Synthea-Importer)
        stay_start = t_event - timedelta(hours=1)
    if not stay_end:
        stay_end = t_event + timedelta(hours=1)

    return ClinicalEvent(
        patient_id=pid,
        event_type=_resolve_event_type(msg, code_map),
        t_start=t_event,
        t_end=t_event,
        stay_start=stay_start,
        stay_end=stay_end,
        attributes=_extract_attributes(msg),
    )


# ─────────────────────────────────────────────────────────────────────
#  High-level API
# ─────────────────────────────────────────────────────────────────────
def hl7v2_import_string(
    raw: str,
    *,
    code_map: Optional[dict[str, str]] = None,
) -> list[ClinicalEvent]:
    """Liest einen String mit einer oder mehreren HL7-Nachrichten."""
    messages = parse_messages(raw)
    events: list[ClinicalEvent] = []
    for msg in messages:
        ev = message_to_event(msg, code_map=code_map)
        if ev:
            events.append(ev)
    log.info("HL7-Import: %d Nachrichten → %d Events", len(messages), len(events))
    events.sort(key=lambda e: e.t_start)
    return events


def hl7v2_import_file(
    path: Union[str, Path],
    *,
    code_map: Optional[dict[str, str]] = None,
) -> list[ClinicalEvent]:
    """Liest eine HL7-v2-Datei (eine oder mehrere Nachrichten)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HL7-Datei nicht gefunden: {path}")
    return hl7v2_import_string(
        path.read_text(encoding="utf-8", errors="replace"),
        code_map=code_map,
    )


def hl7v2_import_directory(
    directory: Union[str, Path],
    *,
    pattern: str = "*.hl7",
    limit: Optional[int] = None,
    code_map: Optional[dict[str, str]] = None,
) -> list[ClinicalEvent]:
    """Batch-Import aus einem Verzeichnis."""
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Verzeichnis nicht gefunden: {directory}")

    files = sorted(directory.glob(pattern))
    if limit is not None:
        files = files[:limit]

    all_events: list[ClinicalEvent] = []
    n_failed = 0
    for f in files:
        try:
            all_events.extend(hl7v2_import_file(f, code_map=code_map))
        except Exception as e:
            log.warning("Datei %s übersprungen: %s", f.name, e)
            n_failed += 1

    log.info("HL7-Verzeichnis: %d Events insgesamt, %d Datei(en) gescheitert",
             len(all_events), n_failed)
    return all_events


__all__ = [
    "HL7Message",
    "parse_message", "parse_messages",
    "message_to_event",
    "hl7v2_import_string", "hl7v2_import_file", "hl7v2_import_directory",
]

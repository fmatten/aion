# aion/api/mllp_worker.py
# Copyright 2026 Friedhelm Matten / ISCaD GmbH – AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
MLLP-Listener für HL7v2 – v1.1.0-B (klinisch korrekt).

Klinisch korrekte Zuordnung nach HL7 v2.5-Spezifikation:

  ADT^A01  Aufnahme (KEIN Diagnoseereignis)
  ADT^A02  Verlegung
  ADT^A03  Entlassung (gesicherte Diagnosen aus DG1 möglich)
  ADT^A04  Ambulante Registrierung / Notaufnahme
  ADT^A06  Ambulant → Stationär
  ADT^A07  Stationär → Ambulant
  ADT^A08  Patientenstammdaten-Update (nur Verwaltung)
  ADT^A11  Aufnahme storniert
  ADT^A12  Verlegung storniert
  ADT^A13  Entlassung storniert
  ADT^A28  Neuer Patient angelegt
  ADT^A40  Patientenzusammenführung (MPI-Merge)
  ORU^R01  Laborergebnis / Vitalzeichen (wichtigste klinische Quelle)
  ORU^R30  POCT-Messung am Patientenbett
  ORM^O01  Auftrag (Labor, Radiologie – NICHT das Ergebnis)
  OML^O21  Laboranforderung
  SIU^S12  Neuer Termin (OP, Konsil)
  SIU^S13  Termin verschoben
  SIU^S15  Termin abgesagt
  MDM^T02  Dokument (Arztbrief → Textextraktion §21.4)
  BAR^P01  Abrechnungsfall (gesicherte DRG-Diagnosen)
  BAR^P05  Abrechnungsfall-Update (gesicherte Diagnosen + OPS-Codes)
  DFT^P03  Einzelleistung (OPS-Prozedur, gesichert)

Architektur:
  TCP-Listener → MLLP-Frame → Redis-Queue → Consumer → PostgreSQL

Dead-Letter-Queue:
  aion:hl7v2:deadletter (Parse-Fehler)
  aion:hl7v2:processed  (Ring-Buffer 1000)
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aion.api.config import settings
from aion.api.metrics import mllp_messages

log = logging.getLogger(__name__)

MLLP_SB = b"\x0b"
MLLP_EB = b"\x1c"
MLLP_CR = b"\x0d"

QUEUE_KEY     = "aion:hl7v2:queue"
DLQ_KEY       = "aion:hl7v2:deadletter"
PROCESSED_KEY = "aion:hl7v2:processed"
PROCESSED_MAX = 1000


# ── MLLP Frame I/O ────────────────────────────────────────────────────

async def read_mllp_frame(reader: asyncio.StreamReader) -> bytes:
    await reader.readuntil(MLLP_SB)
    data = await reader.readuntil(MLLP_EB + MLLP_CR)
    return data[:-2]


def build_ack(msg_id: str = "", ack_code: str = "AA",
              error_msg: str = "") -> bytes:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    err = f"|{error_msg}" if error_msg else ""
    ack = (
        f"MSH|^~\\&|AION-CLINICAL|||{now}||ACK|ACK{now}|P|2.5\r"
        f"MSA|{ack_code}|{msg_id}{err}\r"
    ).encode("latin-1")
    return MLLP_SB + ack + MLLP_EB + MLLP_CR


# ── HL7v2-Parser ─────────────────────────────────────────────────────

class HL7Message:
    """Segment-basierter HL7v2-Parser."""

    def __init__(self, raw: str):
        self.raw = raw
        self.segments: dict[str, list[list[str]]] = {}
        self._parse()

    def _parse(self):
        for line in self.raw.strip().split("\r"):
            if not line.strip():
                continue
            parts = line.split("|")
            seg = parts[0]
            self.segments.setdefault(seg, []).append(parts)

    def get(self, segment: str, field: int,
            occurrence: int = 0, default: str = "") -> str:
        segs = self.segments.get(segment, [])
        if occurrence >= len(segs):
            return default
        parts = segs[occurrence]
        return parts[field] if field < len(parts) else default

    def field(self, segment: str, field: int,
              subfield: int = 0, occurrence: int = 0) -> str:
        """Gibt Teilfeld zurück (Trennzeichen ^)."""
        raw = self.get(segment, field, occurrence)
        parts = raw.split("^")
        return parts[subfield] if subfield < len(parts) else raw

    @property
    def msg_type(self) -> str:
        return f"{self.get('MSH',8).split('^')[0]}^{self.get('MSH',8).split('^')[1] if '^' in self.get('MSH',8) else ''}"

    @property
    def msg_type_raw(self) -> str:
        return self.get("MSH", 8)

    @property
    def msg_id(self) -> str:
        return self.get("MSH", 9)

    @property
    def sending_facility(self) -> str:
        return self.get("MSH", 3)

    @property
    def patient_id(self) -> str:
        pid = self.get("PID", 3)
        return pid.split("^")[0] if pid else "UNKNOWN"

    @property
    def patient_name(self) -> str:
        name = self.get("PID", 5)
        parts = name.split("^")
        if len(parts) >= 2:
            return f"{parts[1]} {parts[0]}".strip()
        return name

    @property
    def birth_date(self) -> str:
        return self.get("PID", 7)

    @property
    def sex(self) -> str:
        return self.get("PID", 8)

    @property
    def t_event(self) -> datetime:
        ts = self.get("EVN", 2) or self.get("MSH", 6) or ""
        return _parse_hl7_dt(ts)

    @property
    def admit_datetime(self) -> datetime | None:
        ts = self.get("PV1", 44)
        return _parse_hl7_dt(ts) if ts else None

    @property
    def discharge_datetime(self) -> datetime | None:
        ts = self.get("PV1", 45)
        return _parse_hl7_dt(ts) if ts else None

    @property
    def ward(self) -> str:
        return self.field("PV1", 3, 0)

    @property
    def patient_class(self) -> str:
        """I=Inpatient, O=Outpatient, E=Emergency, P=Preadmit"""
        return self.get("PV1", 2)

    @property
    def admit_source(self) -> str:
        return self.get("PV1", 14)

    @property
    def discharge_disposition(self) -> str:
        return self.get("PV1", 36)

    @property
    def attending_doctor(self) -> str:
        return self.field("PV1", 7, 0)

    def base_attrs(self) -> dict:
        return {
            "hl7_msg_type":        self.msg_type_raw,
            "hl7_sending_facility": self.sending_facility,
            "pid_name":            self.patient_name,
            "pid_birth_date":      self.birth_date,
            "pid_sex":             self.sex,
        }


def _parse_hl7_dt(ts: str) -> datetime:
    ts = ts.strip().split("+")[0].split("-")[0]
    for fmt in ["%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"]:
        try:
            length = len(fmt.replace("%Y","0000").replace("%m","00")
                           .replace("%d","00").replace("%H","00")
                           .replace("%M","00").replace("%S","00"))
            return datetime.strptime(ts[:length], fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return datetime.now(timezone.utc)


# ── Klinisch korrektes HL7v2 → ClinicalEvent Mapping ─────────────────

def parse_hl7v2(raw: str) -> list:
    """
    HL7v2 → ClinicalEvent-Liste (klinisch korrekt nach HL7 v2.5).

    Grundsätze:
    - ADT^A01 erzeugt KEIN Diagnoseereignis (Aufnahme ≠ Diagnose)
    - Gesicherte Diagnosen kommen aus BAR^P05, BAR^P01, DFT^P03
    - Laborwerte kommen aus ORU^R01 (wichtigste klinische Quelle)
    - ADT^A03 kann Entlassdiagnosen enthalten (DG1), diese werden
      als 'Entlassdiagnose' gespeichert (nicht als 'Diagnose')
    """
    from aion import ClinicalEvent

    msg    = HL7Message(raw)
    now    = datetime.now(timezone.utc)
    pid    = msg.patient_id
    mtype  = msg.msg_type_raw.upper()

    t_event    = msg.t_event
    admit_dt   = msg.admit_datetime or t_event
    discharge_dt = msg.discharge_datetime
    attrs_base = msg.base_attrs()

    events: list = []

    # ── ADT^A01: AUFNAHME (kein Diagnoseereignis) ────────────────────
    if "ADT" in mtype and "A01" in mtype:
        events.append(ClinicalEvent(
            patient_id=pid, event_type="Aufnahme",
            t_start=t_event, t_end=t_event,
            stay_start=admit_dt, stay_end=admit_dt,
            attributes={
                **attrs_base,
                "pv1_ward":             msg.ward,
                "pv1_patient_class":    msg.patient_class,
                "pv1_admit_source":     msg.admit_source,
                "pv1_attending_doctor": msg.attending_doctor,
                "adt_type": "A01",
            },
            confidence=1.0,
        ))

    # ── ADT^A02: VERLEGUNG ───────────────────────────────────────────
    elif "ADT" in mtype and "A02" in mtype:
        ward_from = msg.field("PV1", 3, 0)
        ward_to   = msg.field("PV1", 6, 0) or ward_from
        events.append(ClinicalEvent(
            patient_id=pid, event_type="Verlegung",
            t_start=t_event, t_end=t_event,
            stay_start=admit_dt, stay_end=t_event,
            attributes={
                **attrs_base,
                "pv1_ward_from":        ward_from,
                "pv1_ward_to":          ward_to,
                "pv1_attending_doctor": msg.attending_doctor,
                "adt_type": "A02",
            },
            confidence=1.0,
        ))

    # ── ADT^A03: ENTLASSUNG + ggf. gesicherte Entlassdiagnosen ──────
    elif "ADT" in mtype and "A03" in mtype:
        t_end = discharge_dt or t_event
        events.append(ClinicalEvent(
            patient_id=pid, event_type="Entlassung",
            t_start=t_event, t_end=t_end,
            stay_start=admit_dt, stay_end=t_end,
            attributes={
                **attrs_base,
                "pv1_discharge_disposition": msg.discharge_disposition,
                "pv1_discharge_datetime":    t_end.isoformat(),
                "adt_type": "A03",
            },
            confidence=1.0,
        ))
        # DG1 bei A03 = Entlassdiagnose (gesichert, da bei Entlassung codiert)
        for dg1 in msg.segments.get("DG1", []):
            dx_raw   = dg1[3] if len(dg1) > 3 else ""
            dx_code  = dx_raw.split("^")[0]
            dx_label = dx_raw.split("^")[1] if "^" in dx_raw else (dg1[4] if len(dg1) > 4 else "")
            dx_type  = dg1[5] if len(dg1) > 5 else ""  # F=final, W=working
            if dx_code:
                events.append(ClinicalEvent(
                    patient_id=pid, event_type="Entlassdiagnose",
                    t_start=t_end, t_end=t_end,
                    stay_start=admit_dt, stay_end=t_end,
                    attributes={
                        **attrs_base,
                        "dx_code":  dx_code,
                        "dx_label": dx_label,
                        "dx_type":  dx_type,  # F=final gesichert
                    },
                    confidence=0.95,
                ))

    # ── ADT^A04: AMBULANTE REGISTRIERUNG / NOTAUFNAHME ──────────────
    elif "ADT" in mtype and "A04" in mtype:
        events.append(ClinicalEvent(
            patient_id=pid, event_type="Registrierung",
            t_start=t_event, t_end=t_event,
            stay_start=t_event, stay_end=t_event,
            attributes={
                **attrs_base,
                "pv1_patient_class":    msg.patient_class,
                "pv1_attending_doctor": msg.attending_doctor,
                "adt_type": "A04",
            },
            confidence=1.0,
        ))

    # ── ADT^A06/A07: STATUSÄNDERUNG ─────────────────────────────────
    elif "ADT" in mtype and mtype.split("^")[1] in ("A06", "A07"):
        atype   = mtype.split("^")[1]
        ev_type = ("StatusaenderungAmbulantStationaer"
                   if atype == "A06" else "StatusaenderungStationaerAmbulant")
        events.append(ClinicalEvent(
            patient_id=pid, event_type=ev_type,
            t_start=t_event, t_end=t_event,
            stay_start=admit_dt, stay_end=t_event,
            attributes={**attrs_base, "pv1_ward": msg.ward, "adt_type": atype},
            confidence=1.0,
        ))

    # ── ADT^A08: STAMMDATEN-UPDATE (nur Verwaltung) ──────────────────
    elif "ADT" in mtype and "A08" in mtype:
        # Reine Verwaltungsnachricht – kein klinisches Ereignis
        # Nur als Verwaltungsprotokoll speichern
        events.append(ClinicalEvent(
            patient_id=pid, event_type="PatientenUpdate",
            t_start=t_event, t_end=t_event,
            stay_start=t_event, stay_end=t_event,
            attributes={**attrs_base, "adt_type": "A08"},
            confidence=1.0,
        ))

    # ── ADT^A11/A12/A13: STORNIERUNGEN ──────────────────────────────
    elif "ADT" in mtype and mtype.split("^")[1] in ("A11","A12","A13"):
        atype = mtype.split("^")[1]
        ev_map = {"A11":"AufnahmeStornierung","A12":"VerlegungStornierung",
                  "A13":"EntlassungStornierung"}
        events.append(ClinicalEvent(
            patient_id=pid, event_type=ev_map.get(atype,"Stornierung"),
            t_start=t_event, t_end=t_event,
            stay_start=t_event, stay_end=t_event,
            attributes={**attrs_base, "adt_type": atype},
            confidence=1.0,
        ))

    # ── ADT^A28: NEUER PATIENT ───────────────────────────────────────
    elif "ADT" in mtype and "A28" in mtype:
        events.append(ClinicalEvent(
            patient_id=pid, event_type="PatientenAnlage",
            t_start=t_event, t_end=t_event,
            stay_start=t_event, stay_end=t_event,
            attributes={**attrs_base, "adt_type": "A28"},
            confidence=1.0,
        ))

    # ── ADT^A40: MPI-MERGE ───────────────────────────────────────────
    elif "ADT" in mtype and "A40" in mtype:
        prior_id = msg.get("MRG", 1).split("^")[0]
        events.append(ClinicalEvent(
            patient_id=pid, event_type="PatientenMerge",
            t_start=t_event, t_end=t_event,
            stay_start=t_event, stay_end=t_event,
            attributes={**attrs_base, "mrg_prior_patient_id": prior_id},
            confidence=1.0,
        ))

    # ── ORU^R01/R30: LABORERGEBNISSE / VITALZEICHEN (wichtigste Quelle)
    elif "ORU" in mtype:
        for obx in msg.segments.get("OBX", []):
            obs_id   = obx[3]  if len(obx) > 3  else ""
            obs_val  = obx[5]  if len(obx) > 5  else ""
            obs_unit = obx[6]  if len(obx) > 6  else ""
            ref_range= obx[7]  if len(obx) > 7  else ""
            obs_flag = obx[8]  if len(obx) > 8  else ""
            obs_time = obx[14] if len(obx) > 14 else ""

            t_obs = _parse_hl7_dt(obs_time) if obs_time else t_event

            try:
                val_float = float(obs_val.replace(",", "."))
            except Exception:
                val_float = None

            loinc_code = obs_id.split("^")[0]
            loinc_name = obs_id.split("^")[1] if "^" in obs_id else obs_id

            LOINC_MAP = {
                "2524-7":  "qlaktat",
                "2160-0":  "kreatinin",
                "718-7":   "haemoglobin",
                "6690-2":  "leukozyten",
                "1988-5":  "crp",
                "10839-9": "troponin",
                "33959-8": "procalcitonin",
                "2951-2":  "natrium",
                "2823-3":  "kalium",
                "59408-5": "spo2",
                "8867-4":  "herzfrequenz",
                "8480-6":  "blutdruck_systolisch",
                "8462-4":  "blutdruck_diastolisch",
                "8310-5":  "koerpertemperatur",
                "29463-7": "koerpergewicht",
                "8302-2":  "koerpergroesse",
            }

            attrs = {
                **attrs_base,
                "loinc_code":  loinc_code,
                "loinc_name":  loinc_name,
                "obs_value":   obs_val,
                "obs_unit":    obs_unit,
                "ref_range":   ref_range,
                "obs_flag":    obs_flag,
            }
            if loinc_code in LOINC_MAP and val_float is not None:
                attrs[LOINC_MAP[loinc_code]] = val_float
                attrs["unit"] = obs_unit

            # Vitalzeichen vs. Laborbefund
            VITALS = {"59408-5","8867-4","8480-6","8462-4","8310-5",
                      "29463-7","8302-2"}
            ev_type = "Vitalzeichen" if loinc_code in VITALS else "Laborbefund"

            events.append(ClinicalEvent(
                patient_id=pid, event_type=ev_type,
                t_start=t_obs, t_end=t_obs,
                stay_start=admit_dt, stay_end=t_obs,
                attributes=attrs,
                confidence=0.98,
            ))

    # ── ORM^O01 / OML^O21: AUFTRÄGE ─────────────────────────────────
    elif "ORM" in mtype or "OML" in mtype:
        for obr in msg.segments.get("OBR", []):
            svc_raw   = obr[4] if len(obr) > 4 else ""
            svc_code  = svc_raw.split("^")[0]
            svc_label = svc_raw.split("^")[1] if "^" in svc_raw else ""
            priority  = obr[5] if len(obr) > 5 else ""
            events.append(ClinicalEvent(
                patient_id=pid, event_type="Auftrag",
                t_start=t_event, t_end=t_event,
                stay_start=admit_dt, stay_end=t_event,
                attributes={
                    **attrs_base,
                    "service_code":  svc_code,
                    "service_label": svc_label,
                    "priority":      priority,
                },
                confidence=0.95,
            ))

    # ── SIU^S12/S13/S15: TERMINPLANUNG ──────────────────────────────
    elif "SIU" in mtype:
        atype   = mtype.split("^")[1] if "^" in mtype else ""
        ev_map  = {"S12":"Termin","S13":"TerminAenderung","S15":"TerminStornierung"}
        ev_type = ev_map.get(atype, "Termin")
        apt_start = _parse_hl7_dt(msg.get("SCH", 11)) if msg.segments.get("SCH") else t_event
        events.append(ClinicalEvent(
            patient_id=pid, event_type=ev_type,
            t_start=apt_start, t_end=apt_start,
            stay_start=apt_start, stay_end=apt_start,
            attributes={
                **attrs_base,
                "sch_appointment_type": msg.get("SCH", 7),
                "siu_type": atype,
            },
            confidence=1.0,
        ))

    # ── MDM^T02: DOKUMENT (Arztbrief / Befundbericht) ───────────────
    elif "MDM" in mtype:
        doc_type = msg.get("TXA", 2)
        doc_date = msg.get("TXA", 4)
        obx_text = " ".join(
            obx[5] for obx in msg.segments.get("OBX", [])
            if len(obx) > 5
        )
        events.append(ClinicalEvent(
            patient_id=pid, event_type="Dokument",
            t_start=t_event, t_end=t_event,
            stay_start=admit_dt, stay_end=t_event,
            attributes={
                **attrs_base,
                "txa_document_type": doc_type,
                "txa_activity_date": doc_date,
                "document_text":     obx_text[:2000],  # Basis für §21.4
            },
            confidence=0.90,
        ))

    # ── BAR^P01/P05: GESICHERTE DIAGNOSEN (Abrechnungsfall) ─────────
    elif "BAR" in mtype:
        for dg1 in msg.segments.get("DG1", []):
            dx_raw   = dg1[3] if len(dg1) > 3 else ""
            dx_code  = dx_raw.split("^")[0]
            dx_label = dx_raw.split("^")[1] if "^" in dx_raw else (dg1[4] if len(dg1) > 4 else "")
            dx_type  = dg1[5] if len(dg1) > 5 else "F"  # F=Final (gesichert)
            if dx_code:
                events.append(ClinicalEvent(
                    patient_id=pid, event_type="Diagnose",
                    t_start=t_event, t_end=t_event,
                    stay_start=admit_dt, stay_end=t_event,
                    attributes={
                        **attrs_base,
                        "dx_code":   dx_code,
                        "dx_label":  dx_label,
                        "dx_type":   dx_type,
                        "dx_source": "BAR",  # Abrechnungsdiagnose = gesichert
                    },
                    confidence=0.99,
                ))
        # OPS-Prozeduren aus PR1-Segment
        for pr1 in msg.segments.get("PR1", []):
            # PR1.3 = Procedure Code (HL7 v2.3+)
            ops_raw   = pr1[3] if len(pr1) > 3 else (pr1[4] if len(pr1) > 4 else "")
            if not ops_raw.strip() and len(pr1) > 4:
                ops_raw = pr1[4]
            ops_code  = ops_raw.split("^")[0]
            ops_label = ops_raw.split("^")[1] if "^" in ops_raw else ""
            if ops_code:
                events.append(ClinicalEvent(
                    patient_id=pid, event_type="Prozedur",
                    t_start=t_event, t_end=t_event,
                    stay_start=admit_dt, stay_end=t_event,
                    attributes={
                        **attrs_base,
                        "ops_code":   ops_code,
                        "ops_label":  ops_label,
                        "ops_source": "BAR",
                    },
                    confidence=0.99,
                ))

    # ── DFT^P03: EINZELLEISTUNG (OPS-Prozedur) ──────────────────────
    elif "DFT" in mtype:
        for ft1 in msg.segments.get("FT1", []):
            proc_raw   = ft1[19] if len(ft1) > 19 else ""
            proc_code  = proc_raw.split("^")[0]
            proc_label = proc_raw.split("^")[1] if "^" in proc_raw else ""
            if proc_code:
                events.append(ClinicalEvent(
                    patient_id=pid, event_type="Prozedur",
                    t_start=t_event, t_end=t_event,
                    stay_start=admit_dt, stay_end=t_event,
                    attributes={
                        **attrs_base,
                        "ops_code":   proc_code,
                        "ops_label":  proc_label,
                        "ops_source": "DFT",
                    },
                    confidence=0.99,
                ))

    # ── Fallback ────────────────────────────────────────────────────
    else:
        log.warning("Unbekannter HL7v2-Typ: %s – wird protokolliert", mtype)
        events.append(ClinicalEvent(
            patient_id=pid, event_type="HL7Unbekannt",
            t_start=t_event, t_end=t_event,
            stay_start=t_event, stay_end=t_event,
            attributes={**attrs_base, "hl7_raw_type": mtype},
            confidence=0.3,
        ))

    log.info("HL7v2 %s → %d ClinicalEvents für Patient %s", mtype, len(events), pid)
    return events


# ── MLLP Server (unverändert) ─────────────────────────────────────────

async def handle_connection(reader, writer, redis) -> None:
    peer = writer.get_extra_info("peername", ("?", 0))
    log.info("MLLP: Verbindung von %s:%s", *peer)
    try:
        while True:
            try:
                raw = await asyncio.wait_for(read_mllp_frame(reader), timeout=300.0)
            except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                break
            msg_id = ack_code = "AA"
            try:
                msg_id = HL7Message(raw.decode("latin-1")).msg_id
                await redis.rpush(QUEUE_KEY, raw)
                mllp_messages.labels(
                    message_type=HL7Message(raw.decode("latin-1")).msg_type_raw,
                    status="queued"
                ).inc()
            except Exception as exc:
                log.error("MLLP Queue-Fehler: %s", exc)
                ack_code = "AE"
            writer.write(build_ack(msg_id, ack_code))
            await writer.drain()
    finally:
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass


async def mllp_consumer(redis, store) -> None:
    log.info("MLLP-Consumer gestartet")
    while True:
        try:
            item = await redis.blpop(QUEUE_KEY, timeout=5)
            if item is None:
                continue
            _, raw = item
            raw_str = raw.decode("latin-1")
            try:
                events = parse_hl7v2(raw_str)
                saved = 0
                for ev in events:
                    try:
                        await store.add(ev, current_user="mllp-consumer")
                        saved += 1
                    except Exception as exc:
                        log.error("Store-Fehler: %s", exc)
                mllp_messages.labels(
                    message_type=HL7Message(raw_str).msg_type_raw,
                    status="processed"
                ).inc()
                await redis.lpush(PROCESSED_KEY, raw)
                await redis.ltrim(PROCESSED_KEY, 0, PROCESSED_MAX - 1)
                log.info("MLLP: %d Events gespeichert", saved)
            except Exception as exc:
                log.error("MLLP Parse-Fehler: %s", exc)
                await redis.lpush(DLQ_KEY, raw)
                mllp_messages.labels(message_type="UNKNOWN", status="deadletter").inc()
        except asyncio.CancelledError:
            log.info("MLLP-Consumer beendet")
            break
        except Exception as exc:
            log.error("MLLP unerwarteter Fehler: %s", exc)
            await asyncio.sleep(1)


async def start_mllp_server(store, redis) -> None:
    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, redis),
        settings.MLLP_HOST, settings.MLLP_PORT, reuse_address=True,
    )
    log.info("MLLP-Server bereit auf %s:%d", settings.MLLP_HOST, settings.MLLP_PORT)
    consumer_task = asyncio.create_task(mllp_consumer(redis, store))
    try:
        async with server:
            await server.serve_forever()
    finally:
        consumer_task.cancel()
        try: await consumer_task
        except asyncio.CancelledError: pass


async def mllp_status(redis) -> dict:
    try:
        return {
            "queue_length":       await redis.llen(QUEUE_KEY),
            "deadletter_length":  await redis.llen(DLQ_KEY),
            "processed_buffered": await redis.llen(PROCESSED_KEY),
            "host":               settings.MLLP_HOST,
            "port":               settings.MLLP_PORT,
            "supported_types":    [
                "ADT^A01 (Aufnahme)", "ADT^A02 (Verlegung)",
                "ADT^A03 (Entlassung + Entlassdiagnosen)",
                "ADT^A04 (Ambulant/Notaufnahme)",
                "ADT^A06/A07 (Statusänderung)",
                "ADT^A08 (Stammdaten)", "ADT^A11/12/13 (Stornierung)",
                "ADT^A28 (Neuanlage)", "ADT^A40 (MPI-Merge)",
                "ORU^R01 (Labor/Vitalzeichen)", "ORU^R30 (POCT)",
                "ORM^O01 (Auftrag)", "OML^O21 (Laboranforderung)",
                "SIU^S12/13/15 (Terminplanung)",
                "MDM^T02 (Dokument)",
                "BAR^P01/P05 (gesicherte Diagnosen/OPS)",
                "DFT^P03 (Einzelleistung/OPS)",
            ],
            "status": "ok",
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    async def _main():
        from aion.persist.postgres_store import PostgresEventStore
        import redis.asyncio as aioredis
        store = PostgresEventStore()
        await store.connect(settings.AION_DB_URL)
        r = aioredis.from_url(settings.AION_REDIS_URL)
        log.info("AION MLLP-Worker Port %d", settings.MLLP_PORT)
        await start_mllp_server(store, r)

    asyncio.run(_main())

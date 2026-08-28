# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""Tests für aion.hl7v2 — Parser und Mapper."""
import unittest
from datetime import datetime
from pathlib import Path

from aion.hl7v2 import (
    HL7Message,
    parse_message, parse_messages,
    message_to_event,
    hl7v2_import_string, hl7v2_import_file, hl7v2_import_directory,
)
from aion.hl7v2.codes import (
    DEFAULT_ADT_MAP, DEFAULT_LOINC_MAP,
    lookup_adt, lookup_loinc, fallback_type_name,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "hl7v2"


# ────────────────────────────────────────────────────────────────────
#  Code-Mapping-Tests
# ────────────────────────────────────────────────────────────────────
class TestCodeMapping(unittest.TestCase):

    def test_adt_a01_is_aufnahme(self):
        self.assertEqual(lookup_adt("A01"), "Aufnahme")

    def test_adt_a03_is_entlassung(self):
        self.assertEqual(lookup_adt("A03"), "Entlassung")

    def test_unknown_adt_returns_none(self):
        self.assertIsNone(lookup_adt("Z99"))

    def test_loinc_heart_rate(self):
        self.assertEqual(lookup_loinc("8867-4"), "Herzfrequenz")

    def test_loinc_hemoglobin(self):
        self.assertEqual(lookup_loinc("718-7"), "Hämoglobin")

    def test_loinc_extra_overrides(self):
        extra = {"8867-4": "MeineHerzfrequenz"}
        self.assertEqual(lookup_loinc("8867-4", extra_map=extra),
                         "MeineHerzfrequenz")

    def test_fallback_type_name(self):
        self.assertEqual(fallback_type_name("ADT", "A99"), "HL7_ADT_A99")
        self.assertEqual(fallback_type_name("ORU", ""), "HL7_ORU")


# ────────────────────────────────────────────────────────────────────
#  Parser-Tests (rein syntaktisch)
# ────────────────────────────────────────────────────────────────────
class TestParser(unittest.TestCase):

    def test_parse_minimal_msh(self):
        raw = "MSH|^~\\&|SENDER|FAC|RECV|FAC|20260101120000||ADT^A01|MSG1|P|2.5"
        msg = parse_message(raw)
        self.assertEqual(msg.message_type, "ADT")
        self.assertEqual(msg.trigger_event, "A01")

    def test_encoding_chars_extracted(self):
        raw = "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M|P|2.5"
        msg = parse_message(raw)
        self.assertEqual(msg.field_sep, "|")
        self.assertEqual(msg.component_sep, "^")
        self.assertEqual(msg.repetition_sep, "~")
        self.assertEqual(msg.escape, "\\")
        self.assertEqual(msg.subcomponent_sep, "&")

    def test_msh_field_indexing(self):
        """MSH-1 = Feldtrenner, MSH-9 = Message Type"""
        raw = "MSH|^~\\&|SENDER|FAC|RECV|FAC|20260101120000||ADT^A01|MSG1|P|2.5"
        msg = parse_message(raw)
        self.assertEqual(msg.field("MSH", 1), "|")  # Feldtrenner
        self.assertEqual(msg.field("MSH", 9), "ADT^A01")
        self.assertEqual(msg.field("MSH", 11), "P")
        self.assertEqual(msg.field("MSH", 12), "2.5")

    def test_message_datetime_parsed(self):
        raw = "MSH|^~\\&|S|F|R|F|20260415083045||ADT^A01|M|P|2.5"
        msg = parse_message(raw)
        self.assertEqual(msg.message_datetime,
                         datetime(2026, 4, 15, 8, 30, 45))

    def test_partial_datetime_parses(self):
        """YYYYMMDDHHMM ohne Sekunden, oder nur YYYYMMDD."""
        raw = "MSH|^~\\&|S|F|R|F|20260415||ADT^A01|M|P|2.5"
        msg = parse_message(raw)
        self.assertEqual(msg.message_datetime, datetime(2026, 4, 15))

    def test_carriage_return_separator(self):
        """\\r ist Standard-Trenner"""
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M|P|2.5\r"
            "PID|1||P-12345||Doe^John"
        )
        msg = parse_message(raw)
        self.assertEqual(msg.patient_id(), "P-12345")

    def test_newline_separator_also_works(self):
        """Viele Tools schicken \\n statt \\r."""
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M|P|2.5\n"
            "PID|1||P-12345||Doe^John"
        )
        msg = parse_message(raw)
        self.assertEqual(msg.patient_id(), "P-12345")

    def test_empty_raw_raises(self):
        with self.assertRaises(ValueError):
            parse_message("")

    def test_no_msh_raises(self):
        with self.assertRaises(ValueError):
            parse_message("PID|1||P-12345")

    def test_patient_id_with_repetition(self):
        """PID-3 kann mehrere IDs haben — wir nehmen die erste."""
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M|P|2.5\r"
            "PID|1||P-12345^^^KLINIK^MR~ALT-9999^^^OLDSYS^MR||Doe^John"
        )
        msg = parse_message(raw)
        self.assertEqual(msg.patient_id(), "P-12345")


# ────────────────────────────────────────────────────────────────────
#  Multi-Message-Parser-Tests
# ────────────────────────────────────────────────────────────────────
class TestMultiMessage(unittest.TestCase):

    def test_two_messages_in_one_string(self):
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M1|P|2.5\r"
            "PID|1||P-1||A\r"
            "MSH|^~\\&|S|F|R|F|20260102120000||ADT^A03|M2|P|2.5\r"
            "PID|1||P-1||A"
        )
        messages = parse_messages(raw)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].trigger_event, "A01")
        self.assertEqual(messages[1].trigger_event, "A03")

    def test_empty_string_returns_empty(self):
        self.assertEqual(parse_messages(""), [])

    def test_messages_separated_by_empty_lines(self):
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M1|P|2.5\n"
            "PID|1||P-1||A\n"
            "\n"
            "MSH|^~\\&|S|F|R|F|20260102120000||ADT^A03|M2|P|2.5\n"
            "PID|1||P-1||A"
        )
        messages = parse_messages(raw)
        self.assertEqual(len(messages), 2)


# ────────────────────────────────────────────────────────────────────
#  Mapper-Tests
# ────────────────────────────────────────────────────────────────────
class TestMessageToEvent(unittest.TestCase):

    def test_adt_a01_maps_to_aufnahme(self):
        path = FIXTURES / "adt_a01_aufnahme.hl7"
        events = hl7v2_import_file(path)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev.event_type, "Aufnahme")
        self.assertEqual(ev.patient_id, "P-12345")
        self.assertEqual(ev.t_start, datetime(2026, 4, 15, 8, 30))

    def test_adt_a03_maps_to_entlassung(self):
        path = FIXTURES / "adt_a03_entlassung.hl7"
        ev = hl7v2_import_file(path)[0]
        self.assertEqual(ev.event_type, "Entlassung")

    def test_oru_haemoglobin_maps_to_loinc_label(self):
        path = FIXTURES / "oru_r01_haemoglobin.hl7"
        ev = hl7v2_import_file(path)[0]
        self.assertEqual(ev.event_type, "Hämoglobin")
        self.assertEqual(ev.attributes["value"], 13.4)
        self.assertEqual(ev.attributes["unit"], "g/dL")
        self.assertEqual(ev.attributes["loinc_code"], "718-7")

    def test_oru_heart_rate_value_numeric(self):
        path = FIXTURES / "oru_r01_herzfrequenz.hl7"
        ev = hl7v2_import_file(path)[0]
        self.assertEqual(ev.event_type, "Herzfrequenz")
        self.assertEqual(ev.attributes["value"], 118.0)

    def test_pv1_extracts_stay_period(self):
        """ADT^A01 mit PV1-44 (Admit) und A03 mit PV1-44 + PV1-45."""
        ev_aufnahme = hl7v2_import_file(FIXTURES / "adt_a01_aufnahme.hl7")[0]
        # Stay-Start = Admit, Stay-End = nicht gesetzt → Fallback +1h
        self.assertEqual(ev_aufnahme.stay_start, datetime(2026, 4, 15, 8, 30))
        self.assertEqual(ev_aufnahme.stay_end, datetime(2026, 4, 15, 9, 30))

        ev_entlassung = hl7v2_import_file(FIXTURES / "adt_a03_entlassung.hl7")[0]
        self.assertEqual(ev_entlassung.stay_start, datetime(2026, 4, 15, 8, 30))
        self.assertEqual(ev_entlassung.stay_end, datetime(2026, 4, 19, 16, 0))

    def test_pv1_extracts_patient_class_and_station(self):
        ev = hl7v2_import_file(FIXTURES / "adt_a01_aufnahme.hl7")[0]
        self.assertEqual(ev.attributes["patient_class"], "I")
        self.assertEqual(ev.attributes["station"], "3A")

    def test_unknown_adt_uses_fallback(self):
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A99|M|P|2.5\r"
            "EVN|A99|20260101120000\r"
            "PID|1||P-1||Doe"
        )
        events = hl7v2_import_string(raw)
        self.assertEqual(events[0].event_type, "HL7_ADT_A99")

    def test_unknown_loinc_uses_fallback(self):
        raw = (
            "MSH|^~\\&|S|F|R|F|20260101120000||ORU^R01|M|P|2.5\r"
            "PID|1||P-1||Doe\r"
            "OBX|1|NM|99999-9^Unknown^LN||42|mg/dL|||||F|||20260101120000"
        )
        events = hl7v2_import_string(raw)
        self.assertEqual(events[0].event_type, "HL7_ORU_R01")
        self.assertEqual(events[0].attributes["loinc_code"], "99999-9")

    def test_extra_code_map_overrides_default(self):
        extra = {"A01": "MeineAufnahme"}
        events = hl7v2_import_file(
            FIXTURES / "adt_a01_aufnahme.hl7",
            code_map=extra,
        )
        self.assertEqual(events[0].event_type, "MeineAufnahme")

    def test_message_without_patient_id_is_skipped(self):
        raw = "MSH|^~\\&|S|F|R|F|20260101120000||ADT^A01|M|P|2.5\rEVN|A01|20260101"
        events = hl7v2_import_string(raw)
        self.assertEqual(events, [])

    def test_message_without_datetime_is_skipped(self):
        # Kein Datum in MSH-7 oder anderswo
        raw = "MSH|^~\\&|S|F|R|F|||ADT^A01|M|P|2.5\rPID|1||P-1||Doe"
        events = hl7v2_import_string(raw)
        self.assertEqual(events, [])


# ────────────────────────────────────────────────────────────────────
#  Datei- und Verzeichnis-Import-Tests
# ────────────────────────────────────────────────────────────────────
class TestFileImport(unittest.TestCase):

    def test_multi_message_file(self):
        events = hl7v2_import_file(FIXTURES / "multi_messages.hl7")
        self.assertEqual(len(events), 3)
        types = [e.event_type for e in events]
        self.assertIn("Aufnahme", types)
        self.assertIn("Hämoglobin", types)
        self.assertIn("Entlassung", types)

    def test_chronologically_sorted(self):
        events = hl7v2_import_file(FIXTURES / "multi_messages.hl7")
        for i in range(1, len(events)):
            self.assertLessEqual(events[i-1].t_start, events[i].t_start)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            hl7v2_import_file("/tmp/does-not-exist.hl7")

    def test_directory_import(self):
        """Importiert alle *.hl7 aus dem Fixture-Verzeichnis."""
        events = hl7v2_import_directory(FIXTURES)
        # 4 Einzeldateien (1 Event je) + multi_messages (3 Events) = 7
        self.assertEqual(len(events), 7)

    def test_directory_with_limit(self):
        events = hl7v2_import_directory(FIXTURES, limit=2)
        # Die ersten 2 Dateien (alphabetisch sortiert)
        self.assertGreater(len(events), 0)
        self.assertLessEqual(len(events), 4)

    def test_directory_not_found(self):
        with self.assertRaises(FileNotFoundError):
            hl7v2_import_directory("/tmp/does-not-exist-dir/")


if __name__ == "__main__":
    unittest.main()

"""Numerical and outcome invariants; no timing experiments or wording snapshots."""

import itertools
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_observations import observations, series, stats, reduction
from review_format import duration, number, time_unit
from review_helpers import csv_bytes, jsonl, sample, paired_rows


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [sample("control", 1, 10), sample("candidate", 2, 9),
                     sample("control", 2, 20), sample("candidate", 1, 11)]

    def parse(self, rows=None, configurations=("control", "candidate")):
        return observations(jsonl(self.rows if rows is None else rows), configurations, format="jsonl")

    def test_blocks_not_row_order(self):
        result = paired_rows(self.parse(), "control", "candidate")
        self.assertEqual(result["control"], dict(n=2, median=15, q1=12.5, q3=17.5, iqr=5, min=10, max=20))
        self.assertEqual(result["savings"], [-1, 11])
        self.assertEqual(result["candidate_faster"], 1)

    def test_csv_and_jsonl_share_numerical_model(self):
        csv = observations(csv_bytes(self.rows), ["control", "candidate"])
        a, b = paired_rows(csv, "control", "candidate"), paired_rows(self.parse(), "control", "candidate")
        for key in ("control", "candidate", "paired_saving_s", "pair_ids"):
            self.assertEqual(a[key], b[key])

    def test_csv_preserves_multiline_fields_and_physical_record_lines(self):
        for newline in (b"\n", b"\r\n", b"\r"):
            with self.subTest(newline=newline):
                rows = [sample("control", 1, note='first, "quoted" line\nsecond line'),
                        sample("control", 2, note="last line")]
                raw = csv_bytes(rows).replace(b"\n", newline)
                parsed = observations(b"\xef\xbb\xbf" + raw, ["control"], "capture.csv")
                self.assertEqual([r["line"] for r in parsed["control"]], [2, 4])
                self.assertEqual(parsed["control"][0]["note"], rows[0]["note"].replace("\n", newline.decode()))
                bad = csv_bytes([
                    rows[0], rows[1] | dict(exit_status="bad")
                ]).replace(b"\n", newline)
                with self.assertRaisesRegex(ValueError, r"capture\.csv:4: exit_status"):
                    observations(bad, ["control"], "capture.csv")

    def test_csv_blank_lines_do_not_become_observations(self):
        raw = csv_bytes([sample("control", 1)])
        header, row = raw.split(b"\n", 1)
        parsed = observations(header + b"\n\n\n" + row + b"\n", ["control"])
        self.assertEqual(len(parsed["control"]), 1)
        self.assertEqual(parsed["control"][0]["line"], 4)

    def test_csv_quoting_and_field_counts_have_source_context(self):
        raw = csv_bytes([sample("control", 1)])
        header = raw.split(b"\n", 1)[0] + b",note\n"
        row = raw.split(b"\n", 1)[1].rstrip(b"\n")
        for tail in (b',"unfinished', b',"closed"junk\n', b",extra,field\n", b"\n"):
            with self.subTest(tail=tail):
                with self.assertRaisesRegex(ValueError, r"capture\.csv:2:"):
                    observations(header + row + tail, ["control"], "capture.csv")
        with self.assertRaisesRegex(ValueError, r"capture\.csv:1: invalid CSV"):
            observations(b'"unfinished header', ["control"], "capture.csv")

    def test_both_formats_report_invalid_utf8_and_empty_datasets(self):
        header = csv_bytes([sample("control", 1)]).split(b"\n", 1)[0] + b"\n"
        for format, empty in (("csv", header), ("jsonl", b"\n\n")):
            with self.subTest(format=format):
                with self.assertRaisesRegex(ValueError, rf"capture\.{format}: invalid UTF-8"):
                    observations(b"\xff", ["control"], f"capture.{format}", format=format)
                with self.assertRaisesRegex(ValueError, "empty observation dataset"):
                    observations(empty, ["control"], format=format)

    def test_three_way_permutations_preserve_slots_and_explicit_contrasts(self):
        rows = []
        for block, order in enumerate(itertools.permutations(["a", "b", "c"]), 1):
            for slot, name in enumerate(order, 1):
                rows.append(sample(name, block, {"a": 10, "b": 8, "c": 7}[name] + block, slot=slot))
        groups = self.parse(rows, ["a", "b", "c"])
        self.assertEqual(paired_rows(groups, "a", "b")["savings"], [2] * 6)
        self.assertEqual(paired_rows(groups, "b", "c")["savings"], [1] * 6)
        self.assertEqual([r["slot"] for r in groups["a"]], [1, 1, 2, 3, 2, 3])

    def test_jsonl_preserves_nested_values_and_integer_clock_reading(self):
        ns = 2**53 + 1
        row = sample("control", 1, elapsed_ns=ns, argv=["tool", "file with spaces"],
                     validation={"scope": "fixture", "record": "/checks/0"})
        result = self.parse([row], ["control"])["control"][0]
        self.assertEqual(result["elapsed_ns"], ns)
        self.assertEqual(result["argv"], row["argv"])
        self.assertEqual(result["validation"], row["validation"])

    def test_jsonl_errors_identify_source_and_physical_line(self):
        prefix = jsonl([self.rows[0]]) + b"\n\n"
        for invalid in (b"{broken json}", b'{"id":1,"id":2}', b'{"extra":NaN}'):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, r"capture\.jsonl:4:"):
                    observations(prefix + invalid, ["control"], "capture.jsonl", format="jsonl")

    def test_warmup_timeout_is_not_a_measured_baseline(self):
        timeout = sample("control", 0, phase="warmup", outcome="timeout", timeout_s=60,
                         elapsed_ns=60_020_000_000, exit_status=None, included=False,
                         validated=False, exclude_reason="warmup timeout")
        groups = self.parse([timeout])
        values = series(groups["control"])
        self.assertEqual(values["statistics"], {})
        self.assertFalse(values["censored"])
        self.assertEqual(values["outcomes"][0]["phase"], "warmup")
        self.assertEqual(values["outcomes"][0]["timeout_s"], 60)
        self.assertIsNone(paired_rows(groups, "control", "candidate")["paired_saving_s"])

    def test_mixed_censoring_keeps_outcomes_without_survivor_speedup(self):
        timeout = sample("control", 3, outcome="timeout", timeout_s=60, wall_s=60.02,
                         exit_status=None, included=False, validated=False, exclude_reason="timeout")
        result = paired_rows(self.parse(self.rows + [timeout]), "control", "candidate")
        self.assertTrue(result["series"]["control"]["censored"])
        self.assertEqual(result["control"]["n"], 2)
        self.assertIsNone(result["paired_saving_s"])
        self.assertIsNone(result["median_reduction_pct"])

    def test_failed_third_configuration_does_not_change_other_contrast(self):
        rows = self.rows + [sample("third", 1, outcome="timeout", timeout_s=3,
                                   exit_status=None, included=False, validated=False, exclude_reason="timeout")]
        result = paired_rows(self.parse(rows, ["control", "candidate", "third"]), "control", "candidate")
        self.assertEqual(result["paired_saving_s"]["median"], 5)

    def test_unmatched_members_are_visible_not_silently_paired(self):
        result = paired_rows(self.parse(self.rows[:-1]), "control", "candidate")
        self.assertIsNone(result["paired_saving_s"])
        self.assertEqual(result["unmatched_blocks"], dict(control=["1"], candidate=[]))

    def test_explicit_exclusion_of_both_members_restores_pairing(self):
        rows = [r | dict(included=False, exclude_reason="declared pair exclusion")
                if r["block"] == "1" else r for r in self.rows]
        result = paired_rows(self.parse(rows), "control", "candidate")
        self.assertEqual(result["pair_ids"], ["2"])
        self.assertEqual(len(result["excluded"]), 2)

    def test_invalid_included_records_fail(self):
        for change in [dict(wall_s="nan"), dict(wall_s=0), dict(exit_status=1),
                       dict(validated=False), dict(included=False), dict(phase="warmup"),
                       dict(configuration="unknown"), dict(included="true"),
                       dict(exclude_reason="contradictory inclusion"), dict(accepted=True),
                       dict(outcome="timeout", timeout_s=60)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.parse([self.rows[0] | change] + self.rows[1:])

    def test_invalid_ids_blocks_slots_and_clock_fields_fail(self):
        bad_rows = [self.rows + [self.rows[0]], [self.rows[0] | dict(id=" ")] + self.rows[1:],
                    [r | dict(slot=1) for r in self.rows],
                    [self.rows[0] | dict(elapsed_ns=12)] + self.rows[1:],
                    [sample("control", 1, elapsed_ns=True)],
                    [sample("control", 1, elapsed_ns=10**400)],
                    [sample("control", 1, outcome="timeout", timeout_s=-1, included=False,
                            validated=False, exclude_reason="timeout")]]
        for rows in bad_rows:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(rows)

    def test_row_boundary_and_cohort_cannot_override_dataset(self):
        for key in ("boundary", "cohort"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                observations(jsonl([self.rows[0] | {key: "wrong"}]), ["control"],
                             format="jsonl", boundary="public", cohort="warm")

    def test_missing_validation_is_visible_but_not_included(self):
        row = sample("control", 1, validated=False, included=False, exclude_reason="unchecked output")
        result = series(self.parse([row])["control"])
        self.assertEqual(result["statistics"], {})
        self.assertEqual(len(result["outcomes"]), 1)

    def test_nonzero_expected_exit_is_explicit(self):
        groups = observations(jsonl([sample("control", 1, exit_status=7)]), ["control"],
                              format="jsonl", expected_exit_status=7)
        self.assertEqual(series(groups["control"])["statistics"]["wall_s"]["n"], 1)

    def test_resources_need_consistent_coverage(self):
        groups = self.parse([sample("control", 1, user_s=1), sample("control", 2)], ["control"])
        with self.assertRaises(ValueError):
            series(groups["control"])

    def test_singleton_overflow_and_display_units(self):
        self.assertEqual(stats([2]), dict(n=1, median=2, q1=2, q3=2, iqr=0, min=2, max=2))
        for values in ([], [float("nan")], [1e308, 1e308]):
            with self.assertRaises(ValueError):
                stats(values)
        with self.assertRaises(ValueError):
            reduction(1e-300, 1e300)
        s = stats([.0041, .0043, .0045])
        scale, unit = time_unit([s["max"]])
        self.assertEqual((scale, unit), (1000, "ms"))
        self.assertEqual(number(s["iqr"], scale), "0.2")
        self.assertEqual(time_unit([-0.00001, .00002]), (1_000_000, "µs"))
        self.assertEqual(duration(0), "0 s")
        self.assertNotEqual(number(.000000001), "0")

# AI-generated tests for measurement inclusion, pairing, and evidence preservation.
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
spec = importlib.util.spec_from_file_location(
    "build_review", SKILL / "scripts/build_review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

FIELDS = [
    "configuration",
    "pair",
    "wall_s",
    "exit_status",
    "phase",
    "validated",
    "accepted",
    "exclude_reason",
]


def sample(configuration, pair, wall, **overrides):
    return (
        dict(
            configuration=configuration,
            pair=str(pair),
            wall_s=str(wall),
            exit_status="0",
            phase="measured",
            validated="true",
            accepted="true",
            exclude_reason="",
        )
        | overrides
    )


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / "samples.csv"
        self.rows = [
            sample("control", 1, 10),
            sample("candidate", 2, 9),
            sample("control", 2, 20),
            sample("candidate", 1, 11),
        ]

    def write(self, rows=None):
        with self.csv.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(self.rows if rows is None else rows)

    def test_pair_ids_not_row_order(self):
        self.write()
        result = review.summarize(self.csv, "control", "candidate")
        self.assertEqual(
            result["control"],
            dict(n=2, median=15, q1=12.5, q3=17.5, iqr=5, min=10, max=20),
        )
        self.assertEqual(result["paired_saving_s"]["min"], -1)
        self.assertEqual(result["paired_saving_s"]["max"], 11)
        self.assertEqual(result["candidate_faster"], 1)

    def test_excluded_rows_and_warmups_do_not_bias_statistics(self):
        self.write(
            self.rows
            + [
                sample("control", 0, 999, phase="warmup"),
                sample(
                    "candidate",
                    0,
                    100,
                    accepted="false",
                    exclude_reason="output failed",
                ),
            ]
        )
        result = review.summarize(self.csv, "control", "candidate")
        self.assertEqual(result["candidate"]["median"], 10)
        self.assertEqual(len(result["excluded"]), 2)

    def test_invalid_accepted_evidence_fails(self):
        for change in [
            dict(wall_s="nan"),
            dict(wall_s="inf"),
            dict(wall_s="0"),
            dict(exit_status="1"),
            dict(validated="false"),
            dict(accepted="false"),
            dict(configuration="unknown"),
            dict(phase="typo"),
        ]:
            with self.subTest(change=change):
                self.write([self.rows[0] | change] + self.rows[1:])
                with self.assertRaises(ValueError):
                    review.summarize(self.csv, "control", "candidate")

    def test_missing_and_duplicate_pairs_fail(self):
        for rows in [self.rows[:-1], self.rows + [self.rows[0]], []]:
            self.write(rows)
            with self.assertRaises(ValueError):
                review.summarize(self.csv, "control", "candidate")

    def manifest(self):
        self.write()
        (self.root / "trace.json").write_text('{"traceEvents":[]}')
        data = dict(
            schema="lean-profile-review-v1",
            title="<script>bad()</script> {{PROFILES}}",
            summary="Retained evidence",
            comparisons=[
                dict(
                    title="Example",
                    boundary="public command",
                    cohort="edit",
                    identity="fixture commits",
                    command="make html",
                    decision="Inconclusive",
                    note="Fixture only",
                    control="control",
                    candidate="candidate",
                    samples="samples.csv",
                )
            ],
            profiles=[
                dict(
                    title="Profile",
                    boundary="diagnostic",
                    identity="fixture",
                    note="test",
                    kind="perfetto",
                    path="trace.json",
                )
            ],
        )
        path = self.root / "manifest.json"
        path.write_text(json.dumps(data))
        return path

    def test_output_preserves_evidence_and_escapes_content(self):
        manifest = self.manifest()
        out = self.root / "review"
        page = review.build(manifest, out).read_text()
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt; {{PROFILES}}", page)
        self.assertNotIn("<script>bad()", page)
        self.assertEqual((out / "samples-00.csv").read_bytes(), self.csv.read_bytes())
        self.assertEqual(
            (out / "source-manifest.json").read_bytes(), manifest.read_bytes()
        )
        self.assertIn('data-perfetto="../trace.json"', page)
        self.assertEqual(
            json.loads((out / "review-data.json").read_text())["comparisons"][0][
                "statistics"
            ]["control"]["median"],
            15,
        )
        with self.assertRaises(FileExistsError):
            review.build(manifest, out)

    def test_missing_artifact_fails_before_writing(self):
        manifest = self.manifest()
        (self.root / "trace.json").unlink()
        out = self.root / "review"
        with self.assertRaises(ValueError):
            review.build(manifest, out)
        self.assertFalse(out.exists())

    def test_symlink_link_preserves_server_path(self):
        manifest = self.manifest()
        (self.root / "mounted").symlink_to(self.root, target_is_directory=True)
        data = json.loads(manifest.read_text())
        data["profiles"][0]["path"] = "mounted/trace.json"
        manifest.write_text(json.dumps(data))
        page = review.build(manifest, self.root / "review").read_text()
        self.assertIn('data-perfetto="../mounted/trace.json"', page)


if __name__ == "__main__":
    unittest.main()

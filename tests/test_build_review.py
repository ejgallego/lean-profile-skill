"""Report rendering, input boundaries and artifact preservation."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import build_review as review
from review_data import SCHEMA
from review_helpers import csv_bytes, sample


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / "samples.csv"
        self.csv.write_bytes(csv_bytes([
            sample("control", 1, .0041), sample("candidate", 2, .0042),
            sample("control", 2, .0045), sample("candidate", 1, .0040),
        ]))
        (self.root / "trace.json").write_text('{"traceEvents":[]}')
        self.spec = dict(
            schema=SCHEMA, title="<script>bad()</script> {{SECTIONS}}",
            summary="Synthetic retained evidence",
            datasets=[dict(id="data", title="Fixture", configurations=["control", "candidate"],
                           samples="samples.csv", boundary="public command", cohort="warm",
                           identity="fixture only", command="tool 'file with spaces'")],
            comparisons=[dict(id="trial", title="Example", dataset="data",
                              control="control", candidate="candidate",
                              decision="Rejected despite valid observations",
                              decision_status="rejected", note="Fixture only")],
            profiles=[dict(title="Profile", boundary="diagnostic", identity="fixture",
                           note="test", kind="perfetto", path="trace.json")],
        )
        self.manifest = self.root / "manifest.json"
        self.out = self.root / "report"
        self.write()

    def write(self):
        self.manifest.write_text(json.dumps(self.spec))

    def test_preserves_snapshots_escapes_and_displays_nonzero_spread(self):
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt; {{SECTIONS}}", page)
        self.assertNotIn("<script>bad()", page)
        self.assertEqual((self.out / "dataset-00.csv").read_bytes(), self.csv.read_bytes())
        self.assertEqual((self.out / "source-manifest.json").read_bytes(), self.manifest.read_bytes())
        data = json.loads((self.out / "review-data.json").read_text())
        self.assertEqual(data["datasets"][0]["samples_sha256"], hashlib.sha256(self.csv.read_bytes()).hexdigest())
        self.assertIn("IQR, ms", page)
        self.assertIn("<td>0.2</td>", page)
        self.assertIn('data-decision="rejected"', page)
        self.assertIn('<details class="command"><summary>Exact command</summary>', page)
        self.assertIn('data-perfetto="../trace.json"', page)
        with self.assertRaises(FileExistsError):
            review.build(self.manifest, self.out)

    def test_missing_artifact_fails_before_output(self):
        (self.root / "trace.json").unlink()
        with self.assertRaises(ValueError):
            review.build(self.manifest, self.out)
        self.assertFalse(self.out.exists())

    def test_symlink_urls_remain_under_server_mount(self):
        (self.root / "mounted").symlink_to(self.root, target_is_directory=True)
        self.spec["profiles"][0]["path"] = "mounted/trace.json"
        self.write()
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn('data-perfetto="../mounted/trace.json"', page)

    def test_profile_only_report_has_no_filter(self):
        self.spec.pop("datasets")
        self.spec.pop("comparisons")
        self.write()
        page = review.build(self.manifest, self.out).read_text()
        self.assertNotIn('id="filter"', page)
        self.assertIn("data-perfetto=", page)

    def test_viewer_is_lazy_and_escaped(self):
        (self.root / "viewer #1.html").write_text("<!doctype html><title>Fixture</title>")
        self.spec["profiles"][0].update(kind="viewer", path="viewer #1.html",
                                       comparison="trial", note="<img src=x onerror=bad()>")
        self.write()
        page = review.build(self.manifest, self.out).read_text()
        self.assertIn('data-source="../viewer%20%231.html"', page)
        self.assertIn('aria-expanded="false"', page)
        self.assertNotIn("onerror=bad()>", page)
        self.assertIn("&lt;img", page)

    def test_unknown_attachment_decision_and_metadata_override_fail(self):
        changes = [
            ("profiles", dict(comparison="missing")),
            ("comparisons", dict(decision_status="faster")),
            ("comparisons", dict(boundary="different boundary")),
            ("comparisons", dict(dataset="missing")),
            ("comparisons", dict(candidate="control")),
        ]
        for key, change in changes:
            with self.subTest(change=change):
                original = self.spec[key][0].copy()
                self.spec[key][0].update(change)
                self.write()
                with self.assertRaises(ValueError):
                    review.build(self.manifest, self.out)
                self.assertFalse(self.out.exists())
                self.spec[key][0] = original

    def test_obsolete_alpha_input_fails_explicitly(self):
        self.spec["schema"] = "lean-profile-review-v1"
        self.write()
        with self.assertRaisesRegex(ValueError, "Unsupported review schema"):
            review.build(self.manifest, self.out)


if __name__ == "__main__":
    unittest.main()

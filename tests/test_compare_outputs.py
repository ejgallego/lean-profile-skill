import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_outputs.py"


def program(code):
    return json.dumps([sys.executable, "-c", code])


class CompareOutputsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name) / "outputs"

    def run_tool(self, baseline, candidate, *extra):
        result = subprocess.run([sys.executable, str(SCRIPT), "--baseline", baseline,
                                 "--candidate", candidate, "--out-dir", str(self.out), *extra],
                                capture_output=True, text=True)
        summary = self.out / "summary.json"
        return result, json.loads(summary.read_text()) if summary.exists() else None

    def test_matching_cases_pass_and_keep_every_output(self):
        echo = program("import sys; print(sys.argv[1:])")
        result, summary = self.run_tool(echo, echo, "--case", "[]", "--case", '["1", "two"]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(summary["all_match"])
        self.assertEqual([case["args"] for case in summary["cases"]], [[], ["1", "two"]])
        self.assertEqual((self.out / "002-candidate-1.stdout").read_text(), "['1', 'two']\n")
        runs = [json.loads(line) for line in (self.out / "runs.jsonl").read_text().splitlines()]
        self.assertEqual(len(runs), 4)
        self.assertEqual(runs[3]["argv"][-2:], ["1", "two"])

    def test_one_differing_case_fails_the_whole_check(self):
        result, summary = self.run_tool(
            program("import sys; print(sys.argv[1:])"),
            program("import sys; print(sys.argv[1:] or 'changed')"),
            "--case", '["same"]', "--case", "[]")
        self.assertEqual(result.returncode, 1)
        self.assertEqual([case["verdict"] for case in summary["cases"]], ["match", "differ"])
        self.assertIn("case 2 []: differ", result.stdout)

    def test_exit_status_is_part_of_the_comparison(self):
        _, summary = self.run_tool(program("raise SystemExit(0)"), program("raise SystemExit(4)"),
                                   "--case", "[]")
        self.assertEqual(summary["cases"][0]["verdict"], "differ")
        self.assertEqual(summary["cases"][0]["candidate"]["exit_codes"], [4])

    def test_stderr_counts_only_when_requested(self):
        quiet, noisy = program("print(1)"), program("import sys; print(1); print('x', file=sys.stderr)")
        result, _ = self.run_tool(quiet, noisy, "--case", "[]")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.out = self.out.with_name("strict")
        result, summary = self.run_tool(quiet, noisy, "--case", "[]", "--compare-stderr")
        self.assertEqual(summary["cases"][0]["verdict"], "differ")

    def test_varying_side_is_unstable_rather_than_compared(self):
        varying = program("import os; print(os.getpid())")
        result, summary = self.run_tool(varying, varying, "--case", "[]", "--repeat", "2")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(summary["cases"][0]["verdict"], "unstable")

    def test_timeout_is_an_error_not_a_difference(self):
        slow = program("import time; time.sleep(30)")
        result, summary = self.run_tool(slow, slow, "--case", "[]", "--timeout-seconds", "0.5")
        self.assertEqual(summary["cases"][0]["verdict"], "error")
        self.assertIn("baseline timed out", result.stdout)

    def test_existing_output_directory_is_refused(self):
        self.out.mkdir()
        result, _ = self.run_tool(program("pass"), program("pass"), "--case", "[]")
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing to overwrite", result.stderr)

    def test_case_must_be_a_json_array(self):
        result, _ = self.run_tool(program("pass"), program("pass"), "--case", '"1000"')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()

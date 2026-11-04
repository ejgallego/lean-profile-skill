from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_sampling as tool


def host(installed, permitted, diagnostic="refused"):
    """Fake `which` and probe for a host with the given tools and permissions."""
    which = lambda name: f"/opt/{name}" if name in installed else None
    probe = lambda argv: (0, "") if Path(argv[0]).name in permitted else (1, diagnostic)
    return which, probe


class CheckSamplingTests(unittest.TestCase):
    def test_samply_is_preferred_when_permitted(self):
        report = tool.assess(1, *host({"samply", "perf"}, {"samply", "perf"}))
        self.assertEqual(report["selected"], "samply")
        self.assertIn("`lake samply`", tool.describe(report, lake_samply=True))

    def test_level_two_falls_back_to_user_space_perf(self):
        report = tool.assess(2, *host({"samply", "perf"}, {"perf"}))
        self.assertEqual(report["selected"], "perf")
        self.assertIn("--user-callchains", tool.describe(report, lake_samply=None))

    def test_no_permitted_backend_is_blocked_with_the_owner_step(self):
        report = tool.assess(3, *host({"samply", "perf"}, set(), "Permission denied"))
        self.assertIsNone(report["selected"])
        message = tool.blocked_message(report)
        self.assertIn("native attribution stops here", message)
        self.assertIn("perf was refused (exit 1): Permission denied", message)
        self.assertIn("sudo sysctl kernel.perf_event_paranoid=1", message)
        self.assertIn("owner's decision", message)

    def test_refusal_at_a_permissive_level_points_past_the_sysctl(self):
        message = tool.blocked_message(tool.assess(0, *host({"samply", "perf"}, set())))
        self.assertIn("seccomp", message)
        self.assertNotIn("sysctl", message)

    def test_unknown_level_points_at_the_diagnostic(self):
        message = tool.blocked_message(tool.assess(None, *host({"samply"}, set())))
        self.assertIn("resolve the refusal shown above", message)
        self.assertNotIn("perf_event_open", message)

    def test_missing_tools_suggest_installing_rather_than_sysctl(self):
        message = tool.blocked_message(tool.assess(0, *host(set(), set())))
        self.assertIn("install samply", message)
        self.assertNotIn("sysctl", message)

    def test_level_two_without_perf_suggests_perf(self):
        message = tool.blocked_message(tool.assess(2, *host({"samply"}, set())))
        self.assertIn("install Linux perf", message)

    def test_probe_records_the_real_backend_command(self):
        calls = []
        tool.assess(None, lambda name: f"/opt/{name}", lambda argv: calls.append(argv) or (0, ""))
        self.assertEqual([Path(argv[0]).name for argv in calls], ["samply", "perf"])
        self.assertIn("--user-callchains", calls[1])
        self.assertEqual(calls[0][-len(tool.PROBE_TARGET):], tool.PROBE_TARGET)

    def test_unreadable_paranoid_is_none(self):
        self.assertIsNone(tool.read_paranoid(Path("/nonexistent/perf_event_paranoid")))


if __name__ == "__main__":
    unittest.main()

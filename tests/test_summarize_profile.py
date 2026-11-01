import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import summarize_profile as tool


def thread(names, stacks, samples, **extra):
    """Build one thread; stacks are (prefix, function index) rows."""
    return dict(
        name="tally", pid=7, tid=8,
        stackTable=dict(prefix=[s[0] for s in stacks], frame=[s[1] for s in stacks]),
        frameTable=dict(func=list(range(len(names)))),
        funcTable=dict(name=list(range(len(names)))),
        samples=dict(stack=samples, **extra),
    )


NAMES = ["main", "Hist.record", "lean_copy_expand_array"]
STACKS = [(None, 0), (0, 1), (1, 2)]


class SummarizeTests(unittest.TestCase):
    def profile(self, samples, names=NAMES, **extra):
        return dict(meta=dict(product="tally", interval=1.0), shared=dict(stringArray=names),
                    threads=[thread(names, STACKS, samples, **extra)])

    def summary(self, profile, **options):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "profile.json"
            path.write_text(json.dumps(profile))
            threads, source = tool.read_profile(path)
        return tool.summarize(threads, source, **options)

    def test_self_inclusive_and_weights(self):
        result = self.summary(self.profile([2, 2, 1, None], weight=[3, 2, 3, 9]))
        self.assertEqual(result["total"], 8)
        self.assertEqual(result["self"][0], dict(percent=62.5, name="lean_copy_expand_array"))
        # Hist.record and main tie at 100%; ties must rank the same in every process.
        self.assertEqual([row["name"] for row in result["inclusive"]],
                         ["Hist.record", "main", "lean_copy_expand_array"])
        self.assertEqual(result["stacks"][0]["name"], "lean_copy_expand_array <- Hist.record <- main")

    def test_per_thread_string_table_and_gzip_input(self):
        profile = self.profile([2])
        del profile["shared"]
        profile["threads"][0]["stringArray"] = NAMES
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "p.json.gz"
            path.write_bytes(gzip.compress(json.dumps(profile).encode()))
            result = tool.summarize(*tool.read_profile(path))
        self.assertEqual(result["self"][0]["name"], "lean_copy_expand_array")

    def test_unsymbolicated_capture_is_flagged(self):
        names = ["0x10", "0x20", "0x30"]
        result = self.summary(self.profile([2] * 200, names=names))
        self.assertEqual(result["unknown_leaf_percent"], 100.0)
        self.assertTrue(any("unsymbolicated" in warning for warning in result["warnings"]))

    def test_off_cpu_weight_is_reported_not_attributed(self):
        result = self.summary(self.profile([2, 1], threadCPUDelta=[0, None]))
        self.assertEqual(result["self"], [dict(percent=100.0, name="Hist.record")])
        self.assertTrue(any("off-CPU" in warning for warning in result["warnings"]))

    def test_thread_filter_and_empty_capture(self):
        self.assertEqual(self.summary(self.profile([2]), thread="tally")["total"], 1)
        with self.assertRaises(ValueError):
            self.summary(self.profile([2]), thread="absent")
        with self.assertRaises(ValueError):
            self.summary(self.profile([]))

    def perf(self, text):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "perf.script"
            path.write_text(text)
            return tool.summarize(*tool.read_profile(path))

    def test_perf_script_stacks_and_threads(self):
        result = self.perf(
            "tally  42 \n\t  10 lean_copy_expand_array+0x12\n\t  20 lp_tally_run\n"
            "\t  30 start_thread\n\n"
            "tally  43 \n\t  40 lean::lean_del_core_other(lean_object*, unsigned char, lean_object*)\n"
            "\t  50 _start\n\n"
        )
        self.assertEqual(result["self"][1]["name"], "lean_copy_expand_array")
        self.assertEqual(result["rooted_stack_percent"], 100.0)
        self.assertEqual(result["stack_depths"], [(2, 1), (3, 1)])
        self.assertEqual({row["tid"] for row in result["threads"]}, {"42", "43"})

    def test_clean_looking_truncated_stacks_are_flagged(self):
        result = self.perf("tally  42 \n\t  10 lean_copy_expand_array\n\t  20 lp_tally_run\n\n")
        self.assertEqual(result["unknown_leaf_percent"], 0.0)
        self.assertTrue(any("stop before a thread entry" in warning for warning in result["warnings"]))

    def test_lean_trace_scopes_are_not_presented_as_samples(self):
        profile = self.profile([2])
        profile["meta"] = dict(product="lean", interval=0)
        result = self.summary(profile)
        self.assertIn("scope milliseconds", result["source"])
        self.assertTrue(any("not samples" in warning for warning in result["warnings"]))
        self.assertFalse(any("thread entry" in warning for warning in result["warnings"]))

    def test_thread_entries_cover_the_frames_samply_reports(self):
        for frame in ("start", "_start", "clone3", "start_thread", "__libc_start_main_impl"):
            self.assertTrue(tool.THREAD_ENTRY.search(frame), frame)
        self.assertFalse(tool.THREAD_ENTRY.search("lean_task_restart"))

    def test_unrecognized_text_is_refused(self):
        with self.assertRaises(ValueError):
            self.perf("not a profile\n")

"""Exact tool-result joins. Fixtures are logs only and execute no commands."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kyma import agents, light, sources

TS = "2026-11-21T10:05:00Z"
POLICY = "- Never use sudo.\n"
SECRET = "PRIVATE_TOOL_OUTPUT_SENTINEL_8c72"
MISSING = object()


def result_metadata(held):
    return {key: held[4][key] for key in ("call_id", "status", "source")}


def call(cid, command="sudo -n true"):
    return {"type": "assistant", "timestamp": TS, "message": {"content": [
        {"type": "tool_use", "id": cid, "name": "Bash", "input": {"command": command}}
    ]}}


def result(cid, error=MISSING):
    block = {"type": "tool_result", "tool_use_id": cid, "content": SECRET}
    if error is not MISSING:
        block["is_error"] = error
    return {"type": "user", "timestamp": TS, "message": {"content": [block]}}


def codex_call(cid, name="exec_command", command="sudo -n true"):
    item = {"type": "function_call", "name": name, "call_id": cid,
            "arguments": json.dumps({"cmd": command})}
    return {"timestamp": TS, "type": "response_item", "payload": item}


def codex_result(cid, output):
    return {"timestamp": TS, "type": "response_item", "payload": {
        "type": "function_call_output", "call_id": cid, "output": output}}


class Results(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "session.jsonl")
        self.cache = Path(self.tmp.name) / "cache"
        self.cache.mkdir()
        self.cache_patch = patch.object(light, "CACHE", str(self.cache))
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.tmp.cleanup()

    def write(self, rows):
        Path(self.path).write_text("".join(json.dumps(row) + "\n" for row in rows))

    def cid(self, value):
        return sources.call_id(value, self.path)

    def consumer(self, rows, agent="claude"):
        self.write(rows)
        marks, done = light._judge((self.path, agent, POLICY))
        self.assertTrue(done)
        view = agents._session(self.path, agent, POLICY)
        self.assertIsNotNone(view)
        self.assertEqual(len(view["held"]), len(marks))
        return view

    def statuses(self, view):
        return {h[4]["call_id"]: h[4]["status"] for h in view["held"]}

    def test_identical_commands_same_hour_out_of_order_exact_ids(self):
        view = self.consumer([result("second", True), call("first"), call("second"), result("first", False)])
        self.assertEqual(self.statuses(view), {self.cid("first"): "tool_succeeded", self.cid("second"): "tool_failed"})
        self.assertEqual(view["held"][0][:4], view["held"][1][:4])

    def test_missing_and_nonboolean_flags_and_orphans_stay_unknown(self):
        rows = [call("missing"), result("missing"), call("string"), result("string", "false"),
                call("none"), result("orphan", False)]
        view = self.consumer(rows)
        self.assertEqual(set(self.statuses(view).values()), {"unknown"})
        self.assertNotIn(self.cid("orphan"), json.dumps(view))

    def test_duplicate_call_or_result_is_ambiguous_even_when_status_agrees(self):
        for rows in ([call("a"), call("a"), result("a", False)],
                     [call("a"), result("a", False), result("a", False)]):
            with self.subTest(rows=rows):
                view = self.consumer(rows)
                self.assertTrue(all(h[4]["status"] == "unknown" for h in view["held"]))
                self.assertTrue(all(h[4]["source"] == "ambiguous_result" for h in view["held"]))

    def test_escaped_duplicate_id_is_not_missed_by_prefilter(self):
        self.write([call("a"), result("a", False)])
        with open(self.path, "a") as fh:
            fh.write(json.dumps(call("a")).replace('"id": "a"', '"id": "\\u0061"') + "\n")
        log = agents._read_log(self.path, "claude", {self.cid("a")})
        self.assertEqual(log["results"][self.cid("a")], {"status": "unknown", "source": "ambiguous_result"})

    def test_ids_are_bounded_source_scoped_and_never_truncated(self):
        self.assertNotEqual(self.cid("same"), sources.call_id("same", self.path + "other"))
        self.assertEqual(len(self.cid("a" * 256)), 64)
        for invalid in (None, 4, {}, "", "a" * 257, "a\n", "a b", "a/else"):
            self.assertEqual(self.cid(invalid), "")
        view = self.consumer([call("a" * 257), result("a" * 257, False)])
        self.assertEqual(result_metadata(view["held"][0]),
                         {"call_id": "", "status": "unknown", "source": "unknown"})

    def test_codex_explicit_exit_error_and_conflicting_fields(self):
        cases = [("ok", {"exit_code": 0}, "tool_succeeded"),
                 ("fail", {"exit_code": 2}, "tool_failed"),
                 ("bool", {"is_error": True}, "tool_failed"),
                 ("false", {"is_error": False}, "tool_succeeded"),
                 ("conflict", {"exit_code": 0, "is_error": True}, "unknown"),
                 ("wrongtype", {"exit_code": "0"}, "unknown"),
                 ("noexit", {"session_id": 42}, "unknown")]
        rows = [r for cid, output, _ in cases for r in (codex_call(cid), codex_result(cid, dict(output, output=SECRET)))]
        view = self.consumer(rows, "codex")
        self.assertEqual(self.statuses(view), {self.cid(cid): status for cid, _, status in cases})
        self.assertEqual(sources._codex_result_status({"is_error": True, "output": {"exit_code": 0}}),
                         ("unknown", "conflicting_result"))

    def test_codex_shell_header_requires_shell_call_and_complete_header(self):
        header = "Chunk ID: abc_123\nWall time: 0.1 seconds\nProcess exited with code 0\nFinal output:\n" + SECRET
        rows = [codex_call("ok"), codex_result("ok", header),
                codex_call("bad"), codex_result("bad", header.replace("code 0", "code 2")),
                codex_call("fake"), codex_result("fake", "arbitrary output\n" + header),
                codex_call("running"), codex_result("running", "Chunk ID: abc\nWall time: 1 seconds\nSession ID: 12\n"),
                codex_call("mcp", "mcp__mail__send_email"), codex_result("mcp", header)]
        self.write(rows)
        log = agents._read_log(self.path, "codex", {self.cid(x) for x in ("ok", "bad", "fake", "running", "mcp")})
        self.assertEqual({cid: v["status"] for cid, v in log["results"].items()},
                         {self.cid(k): v for k, v in {"ok": "tool_succeeded", "bad": "tool_failed",
                          "fake": "unknown", "running": "unknown", "mcp": "unknown"}.items()})

    def test_outer_codex_exec_never_assigns_result_to_nested_actions(self):
        for script, count in [('await tools.exec_command({cmd: "sudo -n true"});', 1),
                              ('await tools.exec_command({cmd: "sudo -n true"}); await tools.exec_command({cmd: "sudo -n true"});', 2)]:
            row = codex_call("outer", "exec")
            row["payload"].update(type="custom_tool_call", input=script)
            del row["payload"]["arguments"]
            view = self.consumer([row, codex_result("outer", {"exit_code": 0})], "codex")
            self.assertEqual(len(view["held"]), count)
            self.assertTrue(all(result_metadata(h) == {"call_id": "", "status": "unknown", "source": "unknown"}
                                for h in view["held"]))

    def test_append_result_preserves_marks_counts_and_cursor(self):
        self.write([call("append")])
        marks, done = light._judge((self.path, "claude", POLICY))
        self.assertTrue(done)
        before = json.loads(Path(light._held_cache(self.path)).read_text())
        view = agents._session(self.path, "claude", POLICY)
        self.assertEqual(view["held"][0][4]["status"], "unknown")
        with open(self.path, "a") as fh:
            fh.write(json.dumps(result("append", False)) + "\n")
        again, done = light._judge((self.path, "claude", POLICY))
        after = json.loads(Path(light._held_cache(self.path)).read_text())
        self.assertTrue(done)
        self.assertEqual(marks, again)
        self.assertEqual(before["n"], after["n"])
        self.assertGreater(after["cursor"]["offset"], before["cursor"]["offset"])
        self.assertEqual(agents._session(self.path, "claude", POLICY)["held"][0][4]["status"], "tool_succeeded")

    def test_old_caches_are_invalidated_and_selected_scan_is_single_pass(self):
        self.write([call("old"), result("old", False)])
        marks, _ = light._judge((self.path, "claude", POLICY))
        cp = Path(light._held_cache(self.path))
        data = json.loads(cp.read_text())
        data["t"] = data["t"].replace(".4:", ".3:")
        data["m"] = [m[:4] for m in marks]
        cp.write_text(json.dumps(data))
        self.assertEqual(light.cached_marks(self.path, POLICY), [])
        marks, _ = light._judge((self.path, "claude", POLICY))
        self.assertEqual(marks[0][4]["call_id"], self.cid("old"))
        st = os.stat(self.path)
        ap = self.cache / ("agent-" + hashlib.sha1(self.path.encode()).hexdigest() + ".json")
        links_tag = hashlib.sha256(self.cid("old").encode()).hexdigest()[:16]
        ap.write_text(json.dumps({"s": f"a3:{st.st_mtime_ns}:{st.st_size}:{links_tag}", "v": {"task": SECRET}}))
        with patch.object(sources, "_log_lines", wraps=sources._log_lines) as scan:
            first = agents._session(self.path, "claude", POLICY)
            second = agents._session(self.path, "claude", POLICY)
            self.assertEqual(scan.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["held"][0][4]["status"], "tool_succeeded")
        self.assertNotIn(SECRET, ap.read_text())

    def test_nanosecond_change_invalidates_same_size_same_second_result(self):
        self.write([call("flip"), result("flip", False)])
        original = Path(self.path).read_text().replace('"is_error": false', '"is_error":false')
        Path(self.path).write_text(original)
        stamp = os.stat(self.path).st_mtime_ns
        self.assertEqual(agents._read(self.path, "claude", {self.cid("flip")})["results"][self.cid("flip")]["status"], "tool_succeeded")
        changed = original.replace('"is_error":false', '"is_error":true ')
        self.assertEqual(len(changed), len(original))
        Path(self.path).write_text(changed)
        os.utime(self.path, ns=(stamp + 1, stamp + 1))
        self.assertEqual(agents._read(self.path, "claude", {self.cid("flip")})["results"][self.cid("flip")]["status"], "tool_failed")

    def test_tool_content_and_native_identifiers_never_enter_cache_or_page(self):
        native = "NATIVE_ID_SECRET_2f9"
        view = self.consumer([call(native), result(native, False)])
        page = str(Path(self.tmp.name) / "picture.html")
        light.page({"agents": [view], "text": POLICY, "yours": False}, page)
        emitted = Path(page).read_text() + "".join(p.read_text() for p in self.cache.glob("*.json"))
        self.assertNotIn(SECRET, emitted)
        self.assertNotIn(native, emitted)
        self.assertIn(self.cid(native), emitted)
        self.assertIn("tool_succeeded", emitted)
        row = view["held"][0]
        poisoned = row[:4] + [dict(row[4], output=SECRET)]
        self.assertNotIn(SECRET, json.dumps(agents._linked_held([poisoned], {"results": {}})))
        fake = {"results": {row[4]["call_id"]: {"status": SECRET, "source": SECRET}}}
        self.assertNotIn(SECRET, json.dumps(agents._linked_held([poisoned], fake)))

    def test_byte_resume_preserves_exact_ids_inside_multi_call_record(self):
        blocks = [call("resume-" + str(i))["message"]["content"][0] for i in range(5)]
        self.write([{"type": "assistant", "timestamp": TS, "message": {"content": blocks}}])
        ticks = iter(range(1000))
        with patch.object(light.time, "monotonic", side_effect=lambda: next(ticks)), patch.object(light, "_FILE_BUDGET", 2):
            part, done = light._judge((self.path, "claude", POLICY))
        self.assertFalse(done)
        self.assertEqual(len(part), 2)
        full, done = light._judge((self.path, "claude", POLICY))
        self.assertTrue(done)
        self.assertEqual([r[4]["call_id"] for r in full], [self.cid("resume-" + str(i)) for i in range(5)])


if __name__ == "__main__":
    unittest.main(verbosity=2)

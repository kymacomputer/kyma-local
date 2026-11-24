"""Input evidence survives through cache and page without tool-output content."""
import _test_home  # isolate state before Kyma imports or subprocesses
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kyma import agents, light, sources

TS = "2026-11-21T10:05:00Z"
POLICY = "- Never use sudo.\n"
OUTPUT = "PRIVATE_OUTPUT_EVIDENCE_SENTINEL_d81a"
NATIVE_ID = "native-call-evidence-sentinel-8bf2"
TOKEN = "FakeInputToken79SecretOnly"


def claude(command, cid=NATIVE_ID, tool="Bash", paths=None):
    inp = {"command": command} if command is not None else paths or {}
    return {"type": "assistant", "timestamp": TS, "message": {"content": [
        {"type": "tool_use", "id": cid, "name": tool, "input": inp}]}}


def codex(command, cid=NATIVE_ID):
    return {"type": "response_item", "timestamp": TS, "payload": {
        "type": "function_call", "name": "exec_command", "call_id": cid,
        "arguments": json.dumps({"cmd": command})}}


class ActivityEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session.jsonl"
        self.cache = Path(self.tmp.name) / "cache"
        self.cache.mkdir()
        self.cache_patch = patch.object(light, "CACHE", str(self.cache))
        self.cache_patch.start()

    def tearDown(self):
        self.cache_patch.stop()
        self.tmp.cleanup()

    def write(self, rows):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def session(self, rows, agent="claude"):
        self.write(rows)
        marks, done = light._judge((str(self.path), agent, POLICY))
        self.assertTrue(done)
        view = agents._session(str(self.path), agent, POLICY)
        self.assertIsNotNone(view)
        return marks, view

    def emitted(self, view):
        page = Path(self.tmp.name) / "view.html"
        light.page({"agents": [view], "text": POLICY, "yours": False}, str(page))
        return page.read_text() + "".join(p.read_text() for p in self.cache.glob("*.json"))

    def test_original_pipeline_is_separate_from_unchanged_matched_fragment(self):
        command = "printf 'prefix' | sudo -n true && printf 'suffix'"
        marks, view = self.session([claude(command)])
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0][3], "sudo -n true")
        self.assertEqual(view["held"][0][3], marks[0][3])
        self.assertEqual(view["held"][0][4]["command"], command)
        self.assertFalse(view["held"][0][4]["command_clipped"])
        self.assertEqual(view["held"][0][4]["status"], "unknown")
        self.assertIn(command, self.emitted(view))

    def test_original_input_is_masked_before_cache_and_page(self):
        command = "sudo true; curl -H 'Authorization: Bearer " + TOKEN + "' https://example.invalid"
        _, view = self.session([claude(command)])
        held = view["held"][0]
        self.assertEqual(held[3], "sudo true")
        self.assertIn("curl", held[4]["command"])
        self.assertNotIn(TOKEN, held[4]["command"])
        self.assertNotIn(TOKEN, view["attempts"][0]["command"])
        self.assertNotIn(TOKEN, self.emitted(view))

    def test_evidence_clip_is_explicit_and_preserves_match(self):
        command = "sudo true; printf '" + "x" * 6000 + "'"
        marks, view = self.session([claude(command)])
        meta = view["held"][0][4]
        self.assertEqual(marks[0][3], "sudo true")
        self.assertEqual(meta["command"], command[:4096])
        self.assertTrue(meta["command_clipped"])
        self.assertEqual(view["attempts"][0]["command"], command[:4096])
        self.assertTrue(view["attempts"][0]["command_clipped"])

    def test_source_cap_and_control_cleanup_are_explicit(self):
        value = "echo " + "x" * sources.COMMAND_CAP
        evidence = light.command_evidence(value)
        self.assertEqual(len(evidence["command"]), 4096)
        self.assertTrue(evidence["command_clipped"])
        evidence = light.command_evidence("echo\x1b[2J safe\u202e")
        self.assertNotIn("\x1b", evidence["command"])
        self.assertNotIn("\u202e", evidence["command"])
        self.assertIn("\\x1b", evidence["command"])

    def test_upstream_truncation_stays_visible_after_secret_masking(self):
        command = "sudo true; API_TOKEN=" + "A" * sources.COMMAND_CAP + " && printf visible_tail"
        marks, view = self.session([claude(command)])
        self.assertEqual(len(marks), 1)
        meta = view["held"][0][4]
        self.assertLess(len(meta["command"]), 4096)
        self.assertNotIn("visible_tail", meta["command"])
        self.assertTrue(meta["command_clipped"])
        self.assertTrue(view["attempts"][0]["command_clipped"])

    def test_sparse_claude_inputs_reach_page_without_a_hold_or_task(self):
        _, view = self.session([claude("git status --short"), claude(None, "file-call", "Read",
                                                                   {"file_path": "src/main.py"})])
        self.assertEqual(view["task"], "")
        self.assertEqual(view["held"], [])
        self.assertEqual([a["command"] for a in view["attempts"]], ["git status --short", "src/main.py"])
        self.assertEqual([a["tool"] for a in view["attempts"]], ["Bash", "Read"])
        self.assertIn("git status --short", self.emitted(view))

    def test_sparse_codex_input_reaches_page_without_a_hold_or_task(self):
        _, view = self.session([codex("git diff --stat")], "codex")
        self.assertEqual(view["task"], "")
        self.assertEqual(view["held"], [])
        self.assertEqual(len(view["attempts"]), 1)
        attempt = view["attempts"][0]
        self.assertEqual({k: attempt[k] for k in ("tool", "command", "command_clipped")},
                         {"tool": "exec_command", "command": "git diff --stat", "command_clipped": False})
        self.assertEqual(attempt["status"], "unknown")
        self.assertEqual(len(attempt["call_id"]), 64)
        self.assertIn("git diff --stat", self.emitted(view))

    def test_first_forty_are_retained_in_order_without_normalizing_tail(self):
        blocks = [claude("echo item-" + str(i), "cid-" + str(i))["message"]["content"][0] for i in range(1000)]
        self.write([{"type": "assistant", "timestamp": TS, "message": {"content": blocks}}])
        with patch.object(light, "command_evidence", wraps=light.command_evidence) as normalize:
            log = agents._read_log(str(self.path), "claude")
        self.assertEqual([a["command"] for a in log["attempts"]], ["echo item-" + str(i) for i in range(40)])
        self.assertEqual(normalize.call_count, 40)

    def test_codex_nested_input_sample_stays_bounded(self):
        script = "".join('await tools.exec_command({cmd: "echo item-%d"});' % i for i in range(100))
        self.write([{"type": "response_item", "timestamp": TS, "payload": {
            "type": "custom_tool_call", "name": "exec", "call_id": NATIVE_ID, "input": script}}])
        with patch.object(light, "command_evidence", wraps=light.command_evidence) as normalize:
            log = agents._read_log(str(self.path), "codex")
        self.assertEqual([a["command"] for a in log["attempts"]], ["echo item-" + str(i) for i in range(40)])
        self.assertEqual(normalize.call_count, 40)
        self.assertNotIn(NATIVE_ID, json.dumps(log))

    def test_only_first_forty_codex_inputs_are_normalized_for_sample(self):
        self.write([codex("echo item-" + str(i), "id-" + str(i)) for i in range(250)])
        with patch.object(light, "command_evidence", wraps=light.command_evidence) as normalize:
            log = agents._read_log(str(self.path), "codex")
        self.assertEqual(len(log["attempts"]), 40)
        self.assertEqual(normalize.call_count, 40)
        self.assertEqual(log["calls"], 250)

    def test_only_first_sixty_holds_keep_original_input(self):
        self.write([claude("sudo true", "hold-" + str(i)) for i in range(65)])
        marks, done = light._judge((str(self.path), "claude", POLICY))
        self.assertTrue(done)
        self.assertEqual(len(marks), 65)
        self.assertTrue(all(m[4]["command"] == "sudo true" for m in marks[:60]))
        self.assertTrue(all("command" not in m[4] and m[3] == "" for m in marks[60:]))

    def test_call_shaped_tool_output_never_enters_input_sample(self):
        fake = claude(OUTPUT, "output-only-id")["message"]["content"][0]
        self.write([claude("pwd"), {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": NATIVE_ID, "content": [fake]}]}}])
        log = agents._read_log(str(self.path), "claude")
        self.assertEqual([a["command"] for a in log["attempts"]], ["pwd"])
        fake = codex(OUTPUT, "output-only-id")["payload"]
        self.write([codex("pwd"), {"type": "response_item", "payload": {
            "type": "function_call_output", "call_id": NATIVE_ID, "output": fake}}])
        log = agents._read_log(str(self.path), "codex")
        self.assertEqual([a["command"] for a in log["attempts"]], ["pwd"])

    def test_outputs_and_native_call_ids_never_enter_evidence_cache_or_page(self):
        for agent, rows in [
            ("claude", [claude("sudo true"), {"type": "user", "timestamp": TS, "message": {"content": [
                {"type": "tool_result", "tool_use_id": NATIVE_ID, "is_error": False, "content": OUTPUT}]}}]),
            ("codex", [codex("sudo true"), {"type": "response_item", "timestamp": TS, "payload": {
                "type": "function_call_output", "call_id": NATIVE_ID,
                "output": {"exit_code": 0, "output": OUTPUT}}}])]:
            with self.subTest(agent=agent):
                _, view = self.session(rows, agent)
                self.assertEqual(view["held"][0][4]["status"], "tool_succeeded")
                self.assertEqual(len(view["attempts"]), 1)
                attempt = view["attempts"][0]
                self.assertEqual(set(attempt), {"tool", "command", "command_clipped", "call_id", "actor_id", "status", "source"})
                self.assertEqual(attempt["status"], "tool_succeeded")
                self.assertEqual(len(attempt["call_id"]), 64)
                emitted = self.emitted(view)
                self.assertNotIn(OUTPUT, emitted)
                self.assertNotIn(NATIVE_ID, emitted)

    def test_unknown_result_is_not_inferred_from_input_evidence(self):
        _, view = self.session([claude("sudo true")])
        meta = view["held"][0][4]
        self.assertEqual(meta["status"], "unknown")
        self.assertEqual(meta["source"], "unknown")
        self.assertEqual(meta["command"], "sudo true")
        poisoned = view["held"][0][:4] + [dict(meta, output=OUTPUT)]
        linked = agents._linked_held([poisoned], {"results": {}})
        self.assertNotIn(OUTPUT, json.dumps(linked))
        self.assertEqual(linked[0][4]["status"], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)

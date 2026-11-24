"""Bounded own-history consumers. Fixtures never execute their commands."""
import _test_home  # isolate state before Kyma imports or subprocesses

import contextlib
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TEST_HOME = tempfile.TemporaryDirectory(prefix="kyma-quick-test-")
os.environ["HOME"] = TEST_HOME.name
os.environ["KYMA_HOME"] = str(Path(TEST_HOME.name) / ".kyma")
os.environ["CLAUDE_CONFIG_DIR"] = str(Path(TEST_HOME.name) / ".claude")
os.environ["CODEX_HOME"] = str(Path(TEST_HOME.name) / ".codex")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kyma import agents, cli, history_scope, light, sources


def call(cid="call", ts="2026-11-20T10:00:00Z"):
    return {"type": "assistant", "timestamp": ts, "message": {"model": "claude-opus-5",
            "content": [{"type": "tool_use", "id": cid, "name": "Bash", "input": {"command": "sudo true"}}]}}


class QuickStart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_HOME.name)
        self.base = Path(self.tmp.name)
        self.cache = self.base / "cache"
        self.cache.mkdir()
        self.cache_patch = patch.object(light, "CACHE", str(self.cache))
        self.cache_patch.start()
        self.pool_patch = patch.object(light, "_pool", lambda: ThreadPoolExecutor(max_workers=1))
        self.pool_patch.start()

    def tearDown(self):
        self.pool_patch.stop()
        self.cache_patch.stop()
        self.tmp.cleanup()

    def log(self, name, rows, age=0):
        path = self.base / name
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        os.utime(path, (time.time() - age, time.time() - age))
        return str(path)

    def test_selection_skips_large_and_compressed_without_reading(self):
        entries = []
        for index, (name, size) in enumerate((("huge.jsonl", 70), ("compressed.jsonl.zst", 1),
                                               ("a.jsonl", 40), ("b.jsonl", 40), ("c.jsonl", 10))):
            path = self.base / name
            with path.open("wb") as fh:
                fh.truncate(size)
            os.utime(path, (100 - index, 100 - index))
            entries.append((str(path), "codex"))
        work, scope = history_scope.select(entries, max_files=2, max_bytes=60, per_file=64)
        self.assertEqual([Path(p).name for p, _ in work], ["a.jsonl", "c.jsonl"])
        self.assertEqual((scope["selected_bytes"], scope["available_bytes"]), (50, 161))
        self.assertEqual((scope["skipped_large_files"], scope["skipped_compressed_files"], scope["skipped_budget_files"]), (1, 1, 1))
        self.assertFalse(scope["complete"])
        full, full_scope = history_scope.select(entries, all_history=True, limit=1)
        self.assertEqual(len(full), 5)
        self.assertTrue(full_scope["complete"])

    def test_explicit_history_filters_keep_their_scope(self):
        first = self.log("first.jsonl", [call()], age=100)
        old = self.log("old.jsonl", [call()], age=10 * 86400)
        work, scope = history_scope.select([(old, "claude"), (first, "claude")], since_days=1, per_file=1)
        self.assertEqual(work, [(first, "claude")])
        self.assertEqual(scope["mode"], "selected")
        self.assertEqual(history_scope.select([(first, "claude")], limit=0)[0], [])

    def test_scoped_gather_neither_imports_old_hours_nor_deletes_other_caches(self):
        old = self.log("old.jsonl", [call("old", "2026-10-01T10:00:00Z")])
        new = self.log("new.jsonl", [call("new")])
        with patch.object(light, "files", return_value=[(old, "claude")]):
            light.gather()
        sentinel = self.cache / ("agent-" + "f" * 40 + ".json")
        sentinel.write_text('{"private":"retained"}')
        Path(old).unlink()
        scoped = light.gather(work=[(new, "claude")])
        self.assertEqual(sum(scoped["a"].values()), 1)
        self.assertEqual(scoped["kept"], 0)
        self.assertEqual(sentinel.read_text(), '{"private":"retained"}')
        with patch.object(light, "files", return_value=[(new, "claude")]):
            full = light.gather()
        self.assertEqual(sum(full["a"].values()), 2)
        self.assertEqual(full["kept"], 1)

    def test_native_counts_ignore_quoted_call_structures(self):
        quoted = {"type": "user", "timestamp": "2026-11-20T10:00:00Z", "message": {"content": [
            {"type": "tool_result", "content": {"type": "tool_use", "name": "Bash"}}]}}
        path = self.log("native.jsonl", [quoted, call()])
        self.assertEqual(sum(light._scan(path, "claude")["a"].values()), 1)

    def test_missing_native_time_does_not_borrow_tool_input_time(self):
        row = call()
        row.pop("timestamp")
        row["message"]["content"][0]["input"]["timestamp"] = "2026-11-20T10:00:00Z"
        claude = self.log("no-time.jsonl", [row])
        data = light._scan(claude, "claude")
        self.assertEqual((data["a"], data["undated"]), ({}, 1))
        codex = self.log("no-time-codex.jsonl", [
            {"type": "session_meta", "timestamp": "2026-11-20T10:00:00Z", "payload": {}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                                                    "arguments": {"cmd": "true", "timestamp": "2026-11-20T10:00:00Z"}}}])
        data = light._scan(codex, "codex")
        self.assertEqual((data["a"], data["undated"]), ({}, 1))
        legacy = self.log("legacy-codex.jsonl", [
            {"id": "session", "timestamp": "2026-11-20T10:00:00Z"},
            {"type": "function_call", "name": "exec_command", "arguments": "{}"}])
        data = light._scan(legacy, "codex")
        self.assertEqual((sum(data["a"].values()), data["undated"]), (1, 0))

    def test_live_legacy_counts_refresh_and_deleted_legacy_hours_remain_explicit(self):
        path = self.log("native.jsonl", [call()])
        legacy = light._digest((path, "claude"))
        cell = next(iter(legacy["a"]))
        legacy["a"][cell] = 8
        legacy.pop("native_counts")
        cp = self.cache / (hashlib.sha1(path.encode()).hexdigest() + ".json")
        cp.write_text(json.dumps(legacy))
        fresh = light._digest((path, "claude"))
        self.assertEqual(sum(fresh["a"].values()), 1)
        self.assertTrue(fresh["native_counts"])
        cp.write_text(json.dumps(legacy))
        Path(path).unlink()
        with patch.object(light, "files", return_value=[]):
            retained = light.gather()
        self.assertEqual(sum(retained["a"].values()), 8)
        self.assertEqual((retained["kept"], retained["legacy_kept"]), (1, 1))
        view = light.shape(retained)
        self.assertEqual(view["legacy_kept"], 1)
        self.assertIn("retained log snapshots use legacy call counts", light.summary_block(view, color=False))

    def test_retained_legacy_alias_cannot_restore_false_counts_after_refresh(self):
        path = self.log("canonical.jsonl", [call()])
        alias = self.base / "alias.jsonl"
        os.link(path, alias)
        with patch.object(light, "files", return_value=[(path, "claude"), (str(alias), "claude")]):
            self.assertEqual(sum(light.gather()["a"].values()), 1)
        cp = self.cache / (hashlib.sha1(str(alias).encode()).hexdigest() + ".json")
        legacy = json.loads(cp.read_text())
        legacy["a"][next(iter(legacy["a"]))] = 8
        legacy.pop("native_counts")
        cp.write_text(json.dumps(legacy))
        alias.unlink()
        with patch.object(light, "files", return_value=[(path, "claude")]):
            data = light.gather()
        self.assertEqual(sum(data["a"].values()), 1)
        self.assertEqual(data["legacy_kept"], 0)

    def test_undated_import_retains_actions_matches_and_identity(self):
        rows = [{"schema": "kyma.history.v1", "type": "session", "host": "custom", "session_id": "s"},
                {"schema": "kyma.history.v1", "type": "action", "id": "c", "tool": "Bash", "command": "sudo true",
                 "model_id": "custom-model", "effort": "high"}]
        path = self.log("undated.jsonl", rows)
        work = [(path, "normalized")]
        with patch.object(light, "rules_text", return_value=("- Never use sudo.\n", True)):
            data = light.gather(work=work)
            data["held"] = light.held_moments(work=work, budget=1)
            view = agents.sessions(work=work, judged=data["held"]["paths"])
        shaped = light.shape(data)
        self.assertEqual(shaped["actions"], 1)
        self.assertEqual(shaped["undated_actions"], 1)
        self.assertEqual(shaped["held_past"], 1)
        self.assertTrue(shaped["marks"][0]["undated"])
        self.assertIsNone(shaped["marks"][0]["i"])
        self.assertEqual(sum(map(sum, shaped["A"])), 0)
        self.assertEqual(view[0]["held"][0][0], "")
        self.assertEqual(view[0]["held"][0][4]["actor"]["model_id"], "custom-model")
        self.assertIn("Time not recorded", light.summary_block(shaped, color=False))
        with patch.object(light, "files", return_value=work), patch.object(light, "page", return_value="report.html"), \
             patch.object(light, "offer", return_value=False), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(light.run(open_it=False, details=True), 0)
        self.assertIn("Recorded activity (times unavailable)", output.getvalue())
        self.assertNotIn("Since ", output.getvalue())

    def test_expired_replay_deadline_does_not_consume_a_new_action(self):
        path = self.log("expired.jsonl", [call()])
        marks, done = light._judge((path, "claude", "- Never use sudo.\n", time.monotonic() - 1))
        self.assertEqual(marks, [])
        self.assertFalse(done)
        receipt = json.loads(Path(light._held_cache(path)).read_text())
        self.assertEqual(receipt["checked"], 0)
        self.assertEqual(receipt["cursor"]["offset"], 0)

    def test_large_only_corpus_has_an_exact_full_history_route(self):
        path = self.base / "huge.jsonl"
        with path.open("wb") as fh:
            fh.truncate(history_scope.MAX_FILE_BYTES + 1)
        output = io.StringIO()
        with patch.object(light, "files", return_value=[(str(path), "claude")]), contextlib.redirect_stdout(output):
            self.assertEqual(light.run(open_it=False), 0)
        self.assertIn("No logs fit this recent sample", output.getvalue())
        self.assertIn("--all", output.getvalue())
        self.assertNotIn("No AI activity", output.getvalue())
        self.assertNotIn("no tool calls", output.getvalue())

    def test_cli_full_history_and_legacy_filters_reach_the_report(self):
        with patch.object(light, "run", return_value=0) as run:
            self.assertEqual(cli.main(["--all", "--no-open"]), 0)
            self.assertTrue(run.call_args.kwargs["all_history"])
            self.assertEqual(cli.main(["see", "--days", "7", "--limit", "9", "--no-open"]), 0)
            self.assertEqual((run.call_args.kwargs["since_days"], run.call_args.kwargs["limit"]), (7, 9))
            self.assertEqual(cli.main(["--all", "--no-open", "see"]), 0)
            self.assertTrue(run.call_args.kwargs["all_history"])
            self.assertFalse(run.call_args.kwargs["open_it"])

    def test_first_report_opens_before_the_optional_setup_question_once(self):
        path = self.log("first-run.jsonl", [call()])
        for open_it in (True, False):
            seen = []
            def page(_s):
                seen.append("page")
                return str(self.base / "report.html")
            def offer(_s):
                seen.append("offer")
                return True
            with patch.object(light, "files", return_value=[(path, "claude")]), \
                 patch.object(light, "_interactive", return_value=True), \
                 patch.object(light, "page", side_effect=page), \
                 patch.object(light, "offer", side_effect=offer), \
                 patch("webbrowser.open", side_effect=lambda _url: seen.append("open")), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(light.run(open_it=open_it), 0)
            self.assertEqual(seen, ["page", "open", "offer", "page"] if open_it else ["page", "offer", "page"])

    def test_cli_import_records_history_without_activation(self):
        path = self.log("export.jsonl", [
            {"schema": "kyma.history.v1", "type": "session", "host": "custom", "session_id": "export"},
            {"schema": "kyma.history.v1", "type": "action", "id": "one", "tool": "Bash", "command": "echo hello"}])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["import", path]), 0)
        self.assertIn("Imported 1 actions", output.getvalue())
        self.assertTrue(any(format == "normalized" for _, format in sources.history_files()))
        self.assertFalse((Path(os.environ["KYMA_HOME"]) / "RULES.md").exists())
        self.assertFalse((Path(os.environ["KYMA_HOME"]) / "log.jsonl").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

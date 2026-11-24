"""History adapters through the same Action/replay/actor path as the local report."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SANDBOX = tempfile.mkdtemp(prefix="kyma-test-adapters-")
os.environ["HOME"] = SANDBOX
os.environ["KYMA_HOME"] = os.path.join(SANDBOX, ".kyma")
os.environ.pop("CURSOR_CONFIG_DIR", None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from kyma import agents, history, light, sources

TS = "2026-11-20T10:00:00Z"


def row(typ, **fields):
    return dict(schema=history.SCHEMA, type=typ, **fields)


class HistoryAdapters(unittest.TestCase):
    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp(dir=SANDBOX))

    def write(self, records, name="session.jsonl"):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return str(path)

    def normalized(self, *actions):
        return self.write([row("session", host="opencode", session_id="session1", cwd="/project", task="Ship the patch"), *actions])

    def action(self, cid="one", **fields):
        return row("action", id=cid, timestamp=TS, tool="bash", command="sudo true", kind="shell", **fields)

    def test_arbitrary_models_replay_and_exact_actor(self):
        path = self.normalized(self.action(model_id="Qwen/Qwen3-Coder@Q4_K_M", provider="ollama", effort="balanced"),
                               row("result", id="one", status="tool_failed"),
                               self.action("two", model_id="deepseek/deepseek-r1", provider="openrouter"))
        imported = sources.import_history(path)
        self.assertEqual((imported["actions"], imported["results"]), (2, 1))
        target = imported["path"]
        acts = list(sources.reader("normalized")(target))
        self.assertEqual([a.agent for a in acts], ["opencode", "opencode"])
        self.assertTrue(all(a.call_id == a.actor_id and len(a.call_id) == 64 for a in acts))
        with patch.object(light, "CACHE", str(self.folder / "cache")):
            held, done = light._judge((target, "normalized", "Never use sudo"))
            self.assertTrue(done)
            self.assertEqual(len(held), 2)
            log = agents._read_log(target, "normalized", agents._held_ids(held))
            joined = agents._linked_held(held, log)
        self.assertEqual(joined[0][4]["actor"]["model_id"], "Qwen/Qwen3-Coder@Q4_K_M")
        self.assertEqual(joined[0][4]["actor"]["provider"], "ollama")
        self.assertEqual(joined[0][4]["actor"]["effort"], "balanced")
        self.assertEqual(joined[0][4]["status"], "tool_failed")
        self.assertEqual(joined[0][4]["source"], "normalized_result")
        self.assertEqual(joined[1][4]["actor"]["model_id"], "deepseek/deepseek-r1")
        self.assertEqual(joined[1][4]["status"], "unknown")
        self.assertEqual(agents.identity_label(log), "Mixed models · Mixed effort")
        self.assertEqual([a["status"] for a in agents._read_log(target, "normalized")["attempts"]], ["tool_failed", "unknown"])

    def test_unknown_fields_do_not_inherit(self):
        path = self.normalized(self.action(model_id="mistral/codestral-latest", provider="mistral", effort="high"), self.action("two"))
        log = agents._read_log(path, "normalized")
        self.assertEqual(log["identity"]["model_id"], "")
        self.assertEqual(log["identity"]["provider"], "")
        self.assertEqual(log["identity"]["effort"], "")
        self.assertNotIn("actor", log["attempts"][1])

    def test_import_is_private_minimal_and_idempotent(self):
        secret = "sk-proj-" + "A" * 70
        path = self.normalized(self.action(model_id=secret, provider=secret, effort=secret, private_blob=secret),
                               row("result", id="one", status="tool_succeeded", output=secret))
        one, two = sources.import_history(path), sources.import_history(path)
        self.assertEqual(one, two)
        text = pathlib.Path(one["path"]).read_text()
        self.assertNotIn(secret, text)
        self.assertNotIn("private_blob", text)
        self.assertNotIn("output", text)
        self.assertEqual(os.stat(one["path"]).st_mode & 0o777, 0o600)
        log = agents._read(one["path"], "normalized")
        self.assertNotIn(secret, json.dumps(log))

    def test_import_validation_and_duplicate_ids(self):
        for records in ([self.action()], [row("session", host="custom"), self.action(), self.action()],
                        [row("session", host="custom"), self.action(), row("session", host="custom")],
                        [row("session", host="custom"), row("action", id="bad id", tool="shell")],
                        [{"schema": "other", "type": "action"}]):
            with self.subTest(records=len(records)), self.assertRaises(ValueError):
                sources.import_history(self.write(records))
        bad = self.folder / "broken.jsonl"
        bad.write_text('{"schema":')
        with self.assertRaises(ValueError):
            sources.import_history(str(bad))

    def test_normalized_byte_cursor_keeps_context_once(self):
        path = self.normalized(self.action(), self.action("two"), self.action("three"))
        cursor = {"offset": 0, "item": 0}
        iterator = sources.reader("normalized")(path, cursor=cursor)
        first = next(iterator)
        iterator.close()
        rest = list(sources.reader("normalized")(path, cursor=cursor))
        self.assertEqual(len(rest), 2)
        self.assertTrue(all(a.agent == "opencode" and a.project == "/project" for a in rest))
        self.assertEqual(len({a.call_id for a in [first, *rest]}), 3)

    def test_normalized_ids_validate_before_any_truncation(self):
        prefix = "A" * 256
        cases = ((prefix + "action", prefix + "unrelated-result"),
                 (prefix, prefix + "unrelated-result"),
                 (prefix + "action", prefix))
        for action_id, result_id in cases:
            with self.subTest(action_id=action_id, result_id=result_id):
                path = self.normalized(self.action(action_id),
                                       row("result", id=result_id, status="tool_succeeded"))
                with self.assertRaisesRegex(ValueError, "stable action id"):
                    sources.import_history(path)
                # Direct files use the same reader, even if no importer validated them.
                log = agents._read_log(path, "normalized")
                self.assertEqual(log["attempts"][0]["status"], "unknown")
                if len(action_id) > 256:
                    self.assertEqual(log["attempts"][0]["call_id"], "")
                    self.assertEqual(list(sources.reader("normalized")(path))[0].call_id, "")

        path = self.normalized(self.action(prefix, model_id="local/custom-1"),
                               row("result", id=prefix, status="tool_succeeded"))
        direct = agents._read_log(path, "normalized")
        self.assertEqual(direct["attempts"][0]["status"], "tool_succeeded")
        imported = sources.import_history(path)
        log = agents._read_log(imported["path"], "normalized")
        self.assertEqual(log["attempts"][0]["status"], "tool_succeeded")
        self.assertEqual(log["attempts"][0]["actor"]["model_id"], "local/custom-1")

    def test_cursor_native_shape_and_unknown_metadata(self):
        path = self.write([{"role": "user", "message": {"content": [{"type": "text", "text": "Repair the build"}]}},
                           {"role": "assistant", "message": {"content": [
                               {"type": "tool_use", "name": "Shell", "input": {"command": "sudo true"}},
                               {"type": "tool_use", "name": "StrReplace", "input": {"path": "/project/app.py", "old_string": "a", "new_string": "b"}}]}},
                           {"status": "error", "error": {"model": "forged", "timestamp": TS}}])
        acts = list(sources.reader("cursor")(path))
        self.assertEqual([(a.agent, a.kind) for a in acts], [("cursor", "shell"), ("cursor", "write")])
        self.assertTrue(all(not a.ts and not a.call_id and not a.actor_id for a in acts))
        log = agents._read_log(path, "cursor")
        self.assertEqual(log["calls"], 2)
        self.assertEqual(log["task"], "Repair the build")
        self.assertEqual(log["identity"]["model_id"], "")
        self.assertEqual(log["results"], {})
        self.assertIsNone(log["start"])
        cursor = {"offset": 0, "item": 0}
        iterator = sources.reader("cursor")(path, cursor=cursor)
        next(iterator)
        iterator.close()
        self.assertEqual([a.kind for a in sources.reader("cursor")(path, cursor=cursor)], ["write"])

    def gemini_message(self, mid, cid, model="gemini-2.5-pro", status="success"):
        return {"id": mid, "type": "gemini", "timestamp": TS, "model": model, "content": [], "toolCalls": [
            {"id": cid, "name": "run_shell_command", "args": {"command": "sudo true"}, "status": status, "timestamp": TS}]}

    def test_gemini_json_model_switch_and_exact_status(self):
        records = [self.gemini_message("m1", "c1"), self.gemini_message("m2", "c2", "gemini-3-pro-preview", "error"),
                   self.gemini_message("m3", "c3", None, "cancelled")]
        path = self.write([], "session-native.json")
        pathlib.Path(path).write_text(json.dumps({"sessionId": "native", "projectHash": "opaque", "messages": records}))
        acts = list(sources.reader("gemini")(path))
        log = agents._read_log(path, "gemini", {a.call_id for a in acts})
        self.assertEqual([log["results"][a.call_id]["status"] for a in acts], ["tool_succeeded", "tool_failed", "unknown"])
        self.assertEqual([log["actors"][a.actor_id]["model_id"] for a in acts], ["gemini-2.5-pro", "gemini-3-pro-preview", ""])
        self.assertTrue(all(not i["effort"] and not i["provider"] for i in log["identities"]))
        self.assertEqual([a["status"] for a in agents._read_log(path, "gemini")["attempts"]], ["tool_succeeded", "tool_failed", "unknown"])

    def test_gemini_jsonl_rewinds_replacements_and_patches(self):
        path = self.write([{"sessionId": "native", "projectHash": "opaque"}, self.gemini_message("m1", "c1", status="executing"),
                           self.gemini_message("m2", "c2"), {"$rewindTo": "m2"},
                           {"$patch": {"id": "m1", "toolCalls": [{"id": "c1", "result": [{"text": "success"}]}]}},
                           self.gemini_message("m3", "c3"), {"$patch": {"removeIds": ["m3"]}},
                           self.gemini_message("m4", "c4", "gemini-3-flash"),
                           self.gemini_message("m4", "c4", "gemini-3-flash", "error")])
        acts = list(sources.reader("gemini")(path))
        log = agents._read_log(path, "gemini", {a.call_id for a in acts})
        self.assertEqual(len(acts), 2)
        self.assertEqual(log["results"][acts[0].call_id]["status"], "unknown")
        self.assertEqual(log["results"][acts[1].call_id]["status"], "tool_failed")

    def test_duplicate_join_is_unknown_even_when_models_agree(self):
        path = self.normalized(self.action(model_id="local/custom-1"), self.action(model_id="local/custom-1"),
                               row("result", id="one", status="tool_succeeded"))
        cid = sources.call_id("one", path)
        log = agents._read_log(path, "normalized", {cid})
        self.assertNotIn(cid, log["actors"])
        self.assertEqual(log["results"][cid], {"status": "unknown", "source": "ambiguous_result"})

    def test_discovery_only_known_transcripts_and_migrated_sibling(self):
        cursor = pathlib.Path(SANDBOX) / ".cursor/projects/project/agent-transcripts/session/session.jsonl"
        cursor.parent.mkdir(parents=True, exist_ok=True)
        cursor.write_text('{"role":"user"}\n')
        gemini = pathlib.Path(SANDBOX) / ".gemini/tmp/hash/chats/session-native.json"
        gemini.parent.mkdir(parents=True, exist_ok=True)
        gemini.write_text('{}\n')
        pathlib.Path(str(gemini) + "l").write_text('{}\n')
        creds = pathlib.Path(SANDBOX) / ".gemini/oauth_creds.json"
        creds.write_text('{}\n')
        work = sources.history_files()
        self.assertIn((str(cursor), "cursor"), work)
        self.assertIn((str(gemini) + "l", "gemini"), work)
        self.assertNotIn((str(gemini), "gemini"), work)
        self.assertFalse(any(p == str(creds) for p, _ in work))

    def test_scoped_actor_cards_never_read_omitted_sources(self):
        path = self.normalized(self.action(model_id="local/custom-1"))
        with patch.object(light, "files", side_effect=AssertionError("unbounded discovery")), \
             patch.object(light, "cached_marks", return_value=[]):
            cards = agents.sessions(work=[(path, "normalized")])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["agent"], "opencode")
        self.assertEqual(cards[0]["model_id"], "local/custom-1")

    def test_malformed_optional_fields_and_unknown_format(self):
        path = self.normalized(row("action", id="one", tool=[], paths=[1, "app.py"], model_id={}, provider=[], effort=1),
                               row("result", id="one", status=[]))
        self.assertEqual(len(list(sources.reader("normalized")(path))), 1)
        log = agents._read_log(path, "normalized", {sources.call_id("one", path)})
        self.assertEqual(log["identity"]["model_id"], "")
        with self.assertRaises(ValueError):
            sources.reader("not-a-host")

    def test_cli_scan_and_try_consume_all_new_adapters(self):
        # Isolate from all other cases, and from the owner's native log roots.
        home = self.folder / "cli-home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), KYMA_HOME=str(home / ".kyma"),
                   CLAUDE_CONFIG_DIR=str(home / ".claude"), CODEX_HOME=str(home / ".codex"),
                   CURSOR_CONFIG_DIR=str(home / ".cursor"),
                   PYTHONPATH=str(pathlib.Path(__file__).resolve().parents[1] / "src"))
        cursor = home / ".cursor/projects/project/agent-transcripts/session/session.jsonl"
        cursor.parent.mkdir(parents=True)
        cursor.write_text(json.dumps({"role": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Shell", "input": {"command": "sudo true"}}]}}) + "\n")
        gemini = home / ".gemini/tmp/project/chats/session-example.json"
        gemini.parent.mkdir(parents=True)
        gemini.write_text(json.dumps({"sessionId": "example", "projectHash": "opaque", "messages": [self.gemini_message("m1", "g1")]}))
        exported = self.normalized(self.action(model_id="local/custom-1", provider="local"))

        def cli(*args):
            run = subprocess.run([sys.executable, "-m", "kyma", *args], env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            return run.stdout

        self.assertIn("Imported 1 actions", cli("import", exported))
        scan = cli("scan", "--all")
        self.assertIn("Cursor", scan)
        self.assertIn("Gemini CLI", scan)
        self.assertIn("Imported history", scan)
        self.assertIn("3", scan)
        trial = cli("try", "Never use sudo", "--all")
        self.assertIn("3", trial)
        # A second independent consumer reads the cached command multiplicity.
        code = "from kyma import index; import json; d=index.build(jobs=1,limit=None); print(json.dumps({k:d[k] for k in ('actions','agents','commands')}))"
        check = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True, timeout=20)
        self.assertEqual(check.returncode, 0, check.stderr)
        result = json.loads(check.stdout)
        self.assertEqual(result["actions"], 3)
        self.assertEqual(result["agents"], {"cursor": 1, "gemini": 1, "opencode": 1})
        self.assertEqual(result["commands"], [["sudo true", 3]])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)

"""The public fictional example must exclude every caller history store."""
import _test_home  # isolate state before Kyma imports or subprocesses

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "scripts" / "example.py"


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mode, p.read_bytes())
            for p in root.rglob("*") if p.is_file()}


class ExampleIsolation(unittest.TestCase):
    def test_public_example_excludes_poisoned_roots_and_preserves_owner_bytes(self):
        with tempfile.TemporaryDirectory(prefix="kyma-example-isolation-") as folder:
            base = Path(folder)
            owner = base / "fictional-owner"
            owner.mkdir()
            claude, codex, cursor = (owner / name for name in ("claude-override", "codex-override", "cursor-override"))
            state, project = owner / ".kyma", owner / "project"
            project.mkdir()
            markers = {host: "FICTIONAL_OUTSIDE_EXAMPLE_" + host.upper() + "_7f4d"
                       for host in ("claude", "codex", "cursor", "gemini", "rules", "state")}
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()

            def put(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)

            def jsonl(path, *records):
                put(path, "".join(json.dumps(record) + "\n" for record in records))

            jsonl(claude / "projects/poison/owner.jsonl",
                  {"type": "user", "timestamp": stamp, "message": {"content": markers["claude"]}},
                  {"type": "assistant", "timestamp": stamp, "message": {"model": "claude-sonnet-4-5", "content": [
                      {"type": "tool_use", "id": "owner-claude", "name": "Bash",
                       "input": {"command": "sudo printf " + markers["claude"]}}]}})
            jsonl(codex / "sessions/rollout-owner.jsonl",
                  {"type": "session_meta", "timestamp": stamp, "payload": {"cwd": str(project)}},
                  {"type": "turn_context", "timestamp": stamp, "payload": {"model": "gpt-5.1-codex-max", "effort": "high"}},
                  {"type": "response_item", "timestamp": stamp, "payload": {"type": "function_call", "call_id": "owner-codex",
                   "name": "exec_command", "arguments": json.dumps({"cmd": "sudo printf " + markers["codex"]})}})
            jsonl(cursor / "projects/poison/agent-transcripts/owner.jsonl",
                  {"role": "assistant", "message": {"content": [{"type": "tool_use", "name": "Shell",
                   "input": {"command": "sudo printf " + markers["cursor"]}}]}})
            put(owner / ".gemini/tmp/project/chats/session-owner.json", json.dumps({"sessionId": "owner", "projectHash": "fictional-project", "messages": [
                {"id": "owner-gemini", "type": "gemini", "timestamp": stamp, "model": "gemini-2.5-pro", "toolCalls": [
                    {"id": "owner-tool", "name": "run_shell_command", "args": {"command": "sudo printf " + markers["gemini"]}}]}]}))
            put(state / "RULES.md", "- Never run `" + markers["rules"] + "`.\n")
            put(state / "log.jsonl", json.dumps({"verdict": "block", "subject": markers["state"]}) + "\n")
            put(claude / "settings.json", '{"env":{"FICTIONAL_OWNER":"preserve exactly"}}\n')
            put(codex / "config.toml", 'model = "fictional-owner-config"\n')
            put(cursor / "settings.json", '{"fictional_owner":true}\n')
            put(owner / "xdg-state/kyma-local/keep", "FICTIONAL_OWNER_ACCEPTED_PROOF\n")
            put(project / ".kyma/RULES.md", "- Never run `" + markers["rules"] + "`.\n")
            before = snapshot(owner)
            env = dict(os.environ, HOME=str(owner), KYMA_HOME=str(state), CLAUDE_CONFIG_DIR=str(claude),
                       CODEX_HOME=str(codex), CURSOR_CONFIG_DIR=str(cursor), XDG_STATE_HOME=str(owner / "xdg-state"),
                       XDG_CONFIG_HOME=str(owner / "xdg-config"), XDG_CACHE_HOME=str(owner / "xdg-cache"),
                       KYMA_NO_KEYCHAIN="", PYTHONDONTWRITEBYTECODE="1")
            for key in ("KYMA_TEST_SANDBOX_PID", "KYMA_TEST_SANDBOX_ROOT"):
                env.pop(key, None)
            # Prove that the poison is readable native history before its exclusion.
            control = ("import json,sys; sys.path.insert(0,sys.argv[1]); from kyma import sources; "
                       "print(json.dumps([a.command for p,f in sources.history_files() for a in sources.reader(f)(p)]))")
            exposed = subprocess.run([sys.executable, "-I", "-c", control, str(ROOT / "src")],
                                     cwd=project, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(exposed.returncode, 0, exposed.stderr)
            for host in ("claude", "codex", "cursor", "gemini"):
                self.assertIn(markers[host], exposed.stdout)
            output = base / "fictional-example.html"
            run = subprocess.run([sys.executable, str(EXAMPLE), str(output)], cwd=project, env=env,
                                 capture_output=True, text=True, timeout=90)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            html = output.read_text()
            data = json.JSONDecoder().raw_decode(html.split("const D = ", 1)[1])[0]
            self.assertTrue(data["example"])
            self.assertGreater(data["actions"], 1000)
            self.assertGreater(data["sessions"], 50)
            self.assertTrue(data["scope"]["complete"])
            for value in markers.values():
                self.assertNotIn(value, html)
            self.assertNotIn(str(owner), html)
            self.assertEqual(snapshot(owner), before)

            # Exercise the environment at the real enforcement consumer.
            spec = importlib.util.spec_from_file_location("example_isolation_probe", EXAMPLE)
            example = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(example)
            sandbox = base / "environment-consumer"
            sandbox.mkdir()
            with patch.dict(os.environ, env, clear=True):
                isolated = example.report_environment(str(sandbox))
            probe = ("import json,os,sys; sys.path.insert(0,sys.argv[1]); from kyma import enforce,guard,sources; "
                     "print(json.dumps({'disabled':os.environ.get('KYMA_NO_KEYCHAIN'), 'usable':enforce._keychain_usable(), "
                     "'roots':[sources.claude_dir(),sources.codex_dir(),guard.anchor_dir()]}))")
            checked = subprocess.run([sys.executable, "-I", "-c", probe, str(ROOT / "src")],
                                     cwd=sandbox, env=isolated, capture_output=True, text=True, timeout=20)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            actual = json.loads(checked.stdout)
            self.assertEqual((actual["disabled"], actual["usable"]), ("1", False))
            self.assertTrue(all(Path(p).is_relative_to(sandbox) for p in actual["roots"]))
            self.assertEqual(snapshot(owner), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)

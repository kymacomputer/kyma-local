"""Exercise agent setup through the CLI with disposable host configuration."""
import _test_home  # isolate before Kyma imports or subprocesses

import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "kyma"


class AgentSetup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kyma-agent-setup-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.home = base / "home with spaces"
        self.project = base / "project with spaces"
        self.cwd = self.project / "nested"
        self.bin_dir = base / "bin"
        self.claude_home = self.home / ".claude"
        self.state = self.home / ".kyma"
        self.project_settings = self.project / ".claude" / "settings.local.json"
        self.global_settings = self.claude_home / "settings.json"
        (self.project / ".git").mkdir(parents=True)
        self.cwd.mkdir()
        self.bin_dir.mkdir()
        self.claude_home.mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if k in ("LANG", "TMPDIR", "SYSTEMROOT")}
        self.env.update(HOME=str(self.home), KYMA_HOME=str(self.state),
                        PATH=str(self.bin_dir) + os.pathsep + "/usr/bin:/bin",
                        KYMA_NO_KEYCHAIN="1", KYMA_ALLOW_TEMP_HOME="1",
                        KYMA_TRUST_INSTALL_PATH="1", PYTHONDONTWRITEBYTECODE="1")

    def claude(self, output="2.1.295 (Claude Code)", exit_status=0):
        path = self.bin_dir / "claude"
        path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {exit_status}\n")
        path.chmod(0o700)

    def invoke(self, host, *options, expected=0, cwd=None, patch=""):
        argv = [sys.executable, str(ENTRY)]
        if patch:
            code = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
                    "from kyma import cli, enforce, light; " + patch + "; "
                    "raise SystemExit(cli.main(sys.argv[1:]))")
            argv = [sys.executable, "-c", code, str(ROOT / "src")]
        argv += ["setup", "--host", host, "--no-open", "--json", *options]
        proc = subprocess.run(argv, cwd=cwd or self.cwd, env=self.env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        self.assertEqual(len(proc.stdout.splitlines()), 1, proc.stdout)
        result = json.loads(proc.stdout)
        self.assertEqual(result["report_path"], str(self.state / "kyma.html"))
        self.assertFalse(result["opened"])
        self.assertTrue(result["next_action"])
        report_path = Path(result["report_path"])
        self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)
        html = report_path.read_text()
        report = json.loads(re.search(r"const D = (.*);\n", html).group(1))
        self.assertFalse(report.get("example"))
        self.assertEqual(report["setup_checks"], result["checks"])
        self.assertEqual(report["on"], result["checks"] == "on")
        return result, report

    def active_hook(self, path):
        rows = json.loads(path.read_text())["hooks"]["PreToolUse"]
        return next(h for group in rows for h in group["hooks"] if h.get("onFailure") == "block")

    def codex_history(self):
        folder = self.home / ".codex" / "sessions" / "2026" / "11" / "24"
        folder.mkdir(parents=True)
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [
            {"type": "session_meta", "timestamp": stamp,
             "payload": {"id": "setup-fixture", "cwd": str(self.cwd), "model": "gpt-fixture"}},
            {"type": "response_item", "timestamp": stamp,
             "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-one",
                         "arguments": json.dumps({"cmd": "printf ready"})}},
        ]
        (folder / "rollout-fixture.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        return folder

    def test_project_setup_defaults_to_git_root_and_repeats_without_settings_changes(self):
        self.claude()
        self.global_settings.write_text('{"model": "leave-me", "env": {"TEST": "fixture"}}\n')
        before = self.global_settings.read_bytes()
        receipt, report = self.invoke("claude")
        self.assertEqual(receipt["checks"], "on")
        self.assertEqual(receipt["scope"], "project")
        self.assertEqual(receipt["claude_version"], "2.1.295")
        self.assertEqual(receipt["settings_path"], str(self.project_settings))
        self.assertEqual(report["on_scope"], "project")
        self.assertEqual(self.active_hook(self.project_settings)["onFailure"], "block")
        self.assertEqual(self.global_settings.read_bytes(), before)
        snapshot = [path.read_bytes() for path in [self.project_settings, self.state / "RULES.md",
                                                self.state / "rules.seen"]]
        again, _ = self.invoke("claude")
        self.assertEqual(again["change"], "already on")
        self.assertEqual(snapshot, [path.read_bytes() for path in [self.project_settings, self.state / "RULES.md",
                                                                 self.state / "rules.seen"]])

    def test_outside_git_requires_explicit_global_scope(self):
        self.claude()
        blocked, _ = self.invoke("claude", expected=1, cwd=self.home)
        self.assertIn("--global", blocked["next_action"])
        self.assertFalse(self.global_settings.exists())
        receipt, report = self.invoke("claude", "--global", cwd=self.home)
        self.assertEqual(receipt["checks"], "on")
        self.assertEqual(receipt["settings_path"], str(self.global_settings))
        self.assertEqual(report["on_scope"], "global")
        self.assertFalse(self.project_settings.exists())

    def test_missing_old_unidentified_or_failed_claude_version_cannot_activate(self):
        for output, status, reason in (
            (None, 0, "not on PATH"),
            ("2.1.294 (Claude Code)", 0, "cannot block"),
            ("3.1.200 (Another CLI)", 0, "did not identify Claude Code"),
            ("2.1.400 (Claude Code)", 1, "exited 1"),
        ):
            with self.subTest(output=output):
                if output:
                    self.claude(output, status)
                receipt, report = self.invoke("claude", expected=1)
                self.assertEqual(receipt["checks"], "blocked")
                self.assertIn(reason, receipt["reason"])
                self.assertIn("2.1.295", receipt["next_action"])
                self.assertFalse(report["on"])
                self.assertFalse(self.project_settings.exists())
                self.assertFalse((self.state / "RULES.md").exists())

    def test_disabled_hooks_preserve_settings_and_generate_report(self):
        self.claude()
        self.project_settings.parent.mkdir()
        before = b'{\n  "disableAllHooks": true, "model": "keep"\n}\n'
        self.project_settings.write_bytes(before)
        receipt, report = self.invoke("claude", expected=1)
        self.assertEqual(receipt["checks"], "blocked")
        self.assertIn("disableAllHooks", receipt["reason"])
        self.assertTrue(report["hooks_off"])
        self.assertEqual(self.project_settings.read_bytes(), before)
        self.assertFalse((self.state / "RULES.md").exists())

    def test_other_hosts_do_not_mutate_any_host_settings(self):
        self.claude()
        paths = [self.global_settings, self.project_settings,
                 self.home / ".codex" / "config.toml", self.home / ".cursor" / "config.json",
                 self.home / ".gemini" / "settings.json"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n")
        before = {path: path.read_bytes() for path in paths}
        for host in ("codex", "cursor", "gemini"):
            with self.subTest(host=host):
                receipt, report = self.invoke(host)
                self.assertEqual((receipt["capability"], receipt["checks"], receipt["scope"]),
                                 ("report-only", "report-only", None))
                self.assertEqual(report["actions"], 0)
                self.assertIn("demo", receipt["next_action"])
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        self.assertFalse((self.state / "RULES.md").exists())

    def test_one_real_report_with_bounded_history_and_auto_host(self):
        logs = self.codex_history()
        with (logs / "rollout-large.jsonl").open("wb") as large:
            large.truncate(64 * 1024 * 1024 + 1)
        receipt, report = self.invoke("auto")
        self.assertEqual(receipt["host"], "codex")
        self.assertEqual(receipt["checks"], "report-only")
        coverage = receipt["coverage"]
        self.assertEqual((coverage["available_files"], coverage["selected_files"], coverage["actions"]), (2, 1, 1))
        self.assertEqual(coverage["available_by_host"], {"codex": 2})
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["skipped_large_files"], 1)
        self.assertEqual(report["scope"], coverage)
        self.assertIn("printf ready", json.dumps(report["agents"]))
        self.assertIn("setup --host claude --project", report["setup_modes"]["project"]["on"])

    def test_existing_accepted_rules_and_pending_relaxations_survive_setup(self):
        self.claude()
        self.invoke("claude")
        policy, accepted = self.state / "RULES.md", self.state / "rules.seen"
        saved = accepted.read_bytes()
        edited = policy.read_text().replace("- Never use sudo.\n", "")
        policy.write_text(edited)
        receipt, report = self.invoke("claude")
        self.assertEqual(receipt["pending_rule_changes"], 1)
        self.assertEqual(report["setup_rule_status"], "pending")
        self.assertEqual(policy.read_text(), edited)
        self.assertEqual(accepted.read_bytes(), saved)
        self.assertIn("terminal", receipt["next_action"])

        hook = self.active_hook(self.project_settings)
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "sudo -n true"}, "cwd": str(self.cwd)}
        proc = subprocess.run(["/bin/sh", "-c", hook["command"]], cwd=self.cwd, env=self.env,
                              input=json.dumps(payload), capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        verdict = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(verdict["permissionDecision"], "deny")
        self.assertIn("Never use sudo", verdict["permissionDecisionReason"])

    def test_failed_hook_readback_never_reuses_the_page_on_state(self):
        self.claude()
        self.invoke("claude")
        before = self.project_settings.read_bytes()
        receipt, report = self.invoke("claude", expected=1,
                                      patch="enforce.self_test = lambda *args: (False, 'fixture hook failed')")
        self.assertEqual(receipt["checks"], "blocked")
        self.assertIn("fixture hook failed", receipt["reason"])
        self.assertFalse(report["on"])
        self.assertEqual(report["on_scope"], "")
        self.assertEqual(self.project_settings.read_bytes(), before)

    def test_nonblocking_existing_kyma_hook_is_not_certified(self):
        self.claude()
        self.invoke("claude")
        settings = json.loads(self.project_settings.read_text())
        settings["hooks"]["PreToolUse"][0]["hooks"][0]["async"] = True
        self.project_settings.write_text(json.dumps(settings))
        before = self.project_settings.read_bytes()
        receipt, _ = self.invoke("claude", expected=1)
        self.assertIn("restricted coverage", receipt["reason"])
        self.assertEqual(self.project_settings.read_bytes(), before)

    def test_temporary_install_returns_a_pinned_durable_command(self):
        self.claude()
        spec = "git+https://example.invalid/kyma@123abc"
        receipt, _ = self.invoke("claude", expected=1, patch=(
            "enforce.install_is_durable = lambda: (False, '/tmp/kyma'); "
            f"enforce._source_spec = lambda: {spec!r}"))
        self.assertEqual(receipt["install_command"], "uv tool install " + spec)
        self.assertIn(receipt["install_command"], receipt["next_action"])
        self.assertFalse(self.project_settings.exists())


if __name__ == "__main__":
    unittest.main()

"""The generated setup page preserves its scope and never changes settings."""
import _test_home  # isolate state before Kyma imports or subprocesses

import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "kyma"
NODE = shutil.which("node")

# Execute the generated page's actual setup function. This small DOM adapter
# tests its command selection and scope changes without a browser or clipboard.
SETUP_HOST = r'''
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const D = JSON.parse(html.match(/const D = (.*);\n/)[1]);
const elements = new Map();
class Element {
  constructor() { this.children=[]; this.textContent=""; this.hidden=false; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  addEventListener() {}
  showModal() { this.open=true; }
  close() { this.open=false; }
}
const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const el = (tag, cls, text) => { const e=new Element(); e.textContent=text || ""; return e; };
$("setup-rule-status").hidden=true;
const radios=[{value:"project"},{value:"global"}];
const document={querySelectorAll:()=>radios};
const context={D,$,el,document};
vm.createContext(context);
const code=html.slice(html.indexOf("function setup() {"),html.indexOf("const wide =",html.indexOf("function setup() {")));
vm.runInContext(code,context);
const text = e => e.textContent + e.children.map(x => typeof x === "string" ? x : text(x)).join(" ");
const snapshot=()=>Object.fromEntries([...elements].map(([id,e])=>[id,{text:text(e),hidden:e.hidden}]));
const initial=snapshot();
radios[1].onchange();
const global=snapshot();
radios[0].onchange();
console.log(JSON.stringify({initial,global,project:snapshot()}));
'''


class SetupScope(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kyma-setup-scope-")
        self.base = Path(self.tmp.name)
        self.home = self.base / "home with spaces"
        self.project = self.base / "client project's [draft]"
        self.cwd = self.project / "source folder"
        self.other = self.base / "unrelated folder"
        (self.home / ".claude" / "projects" / "fixture").mkdir(parents=True)
        (self.project / ".git").mkdir(parents=True)
        self.cwd.mkdir()
        self.other.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k in ("LANG", "TMPDIR", "SYSTEMROOT")}
        self.env.update(PATH=os.path.dirname(sys.executable) + os.pathsep + "/usr/bin:/bin",
                        HOME=str(self.home), KYMA_HOME=str(self.home / ".kyma"), KYMA_NO_KEYCHAIN="1",
                        KYMA_ALLOW_TEMP_HOME="1", PYTHONDONTWRITEBYTECODE="1")
        self.global_settings = self.home / ".claude" / "settings.json"
        self.project_settings = self.project / ".claude" / "settings.local.json"
        self.global_rules = self.home / ".kyma" / "RULES.md"
        row = {"type": "assistant", "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
               "cwd": str(self.cwd), "sessionId": "fixture", "message": {"model": "claude-sonnet", "content": [
                   {"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": "printf ready"}}]}}
        (self.home / ".claude/projects/fixture/fixture.jsonl").write_text(json.dumps(row) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        candidates = [self.global_settings, self.project_settings,
                      self.project / ".claude/settings.json", self.global_rules,
                      self.home / ".kyma/rules.seen", Path(self.env["KYMA_HOME"]) / "rules.seen"]
        candidates += list(self.base.rglob("settings*.json"))
        candidates += list(self.home.glob("Library/Application Support/kyma-local/*"))
        candidates += list(self.home.glob(".local/state/kyma-local/*"))
        return {str(p): p.read_bytes() if p.is_file() else None for p in candidates}

    def page(self, managed=None):
        before = self.snapshot()
        command = [sys.executable, str(ENTRY), "--no-open"]
        if managed:
            code = ("import sys; sys.path.insert(0, sys.argv[1]); from kyma import enforce, light; "
                    "enforce.MANAGED_SETTINGS=[sys.argv[2]]; sys.argv=[sys.argv[3]]; "
                    "raise SystemExit(light.run(open_it=False))")
            command = [sys.executable, "-c", code, str(ROOT / "src"), str(managed), str(ENTRY)]
        p = subprocess.run(command, cwd=self.cwd, env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(before, self.snapshot(), "read-only report changed settings or accepted rules")
        path = Path(self.env["KYMA_HOME"]) / "kyma.html"
        html = path.read_text()
        data = json.loads(re.search(r"const D = (.*);\n", html).group(1))
        return path, data

    def ui(self, path):
        if not NODE:
            self.skipTest("Node is required for the setup-function consumer check")
        p = subprocess.run([NODE, "-e", SETUP_HOST, str(path)], capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def shell(self, command, terminal=False, env=None):
        slave = master = None
        if terminal:
            import pty
            master, slave = pty.openpty()
        try:
            p = subprocess.run(["/bin/sh", "-c", command], cwd=self.other, env=env or self.env, stdin=slave,
                               capture_output=True, text=True, timeout=30)
        finally:
            if slave is not None:
                os.close(slave)
                os.close(master)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout

    def accept(self, text):
        self.global_rules.parent.mkdir(parents=True, exist_ok=True)
        self.global_rules.write_text(text)
        code = "import sys; sys.path.insert(0, sys.argv[1]); from kyma import enforce; assert enforce.accept_rules(True)"
        p = subprocess.run([sys.executable, "-c", code, str(ROOT / "src")], cwd=self.cwd, env=self.env,
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)

    def assert_bound(self, command, folder, tail):
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
        self.assertEqual(tokens[0], "cd")
        self.assertEqual(Path(tokens[1]).resolve(), folder.resolve())
        self.assertEqual(tokens[2], "&&")
        self.assertEqual(tokens[3:5], ["(", "export"])
        end = tokens.index(";")
        values = dict(token.split("=", 1) for token in tokens[5:end])
        expected = {"KYMA_HOME": self.env["KYMA_HOME"],
                    "CLAUDE_CONFIG_DIR": self.env.get("CLAUDE_CONFIG_DIR", str(self.home / ".claude")),
                    "CODEX_HOME": self.env.get("CODEX_HOME", str(self.home / ".codex"))}
        self.assertEqual(set(values), set(expected))
        self.assertEqual({k: Path(v).resolve() for k, v in values.items()},
                         {k: Path(v).resolve() for k, v in expected.items()})
        self.assertEqual(tokens[end + 1:-1], [str(ENTRY.resolve()), *tail])
        self.assertEqual(tokens[-1], ")")

    def codex_log(self, root):
        logs = root / "sessions/2026/11/24"
        logs.mkdir(parents=True)
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [{"type": "session_meta", "timestamp": stamp,
                 "payload": {"id": "codex-fixture", "cwd": str(self.project)}},
                {"type": "response_item", "timestamp": stamp, "payload": {
                    "type": "function_call", "name": "exec_command", "call_id": "codex-call",
                    "arguments": json.dumps({"cmd": "pwd"})}}]
        (logs / "rollout-fixture.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_inactive_commands_bind_exact_scope_and_folder_with_spaces(self):
        path, data = self.page()
        self.assertFalse(data["on"])
        for scope, folder in (("project", self.project), ("global", self.home)):
            mode = data["setup_modes"][scope]
            self.assert_bound(mode["on"], folder, ["on", "--" + scope])
            self.assert_bound(mode["off"], folder, ["off", "--" + scope])
            self.assert_bound(mode["review"], folder, ["rules"])
        ui = self.ui(path)
        self.assertEqual(ui["initial"]["setup-command"]["text"], data["setup_modes"]["project"]["on"])
        self.assertEqual(ui["global"]["setup-command"]["text"], data["setup_modes"]["global"]["on"])
        self.assertEqual(ui["initial"]["refresh-command"]["text"], data["setup_modes"]["project"]["report"])
        self.assertTrue(ui["initial"]["refresh-help"]["hidden"])
        self.assertFalse(self.global_rules.exists())

    def test_project_management_reviews_rules_and_removes_only_project_hook(self):
        _, data = self.page()
        self.shell(data["setup_modes"]["project"]["on"])
        self.assertTrue(self.project_settings.exists())
        self.assertFalse(self.global_settings.exists())
        original_cwd = self.cwd
        second = self.base / "second project"
        (second / ".git").mkdir(parents=True)
        self.cwd = second
        _, other_data = self.page()
        self.shell(other_data["setup_modes"]["project"]["on"])
        second_settings = second / ".claude/settings.local.json"
        other_before = second_settings.read_bytes()
        self.cwd = original_cwd
        path, data = self.page()
        self.assertEqual(data["on_scope"], "project")
        ui = self.ui(path)["initial"]
        self.assertEqual(ui["setup-command"]["text"], data["setup_modes"]["project"]["review"])
        self.assertTrue(ui["setup-scopes"]["hidden"])
        self.assertIn("this project only", ui["setup-off-scope"]["text"])
        self.shell(ui["setup-off-command"]["text"], terminal=True)
        self.assertFalse(self.project_settings.exists())
        self.assertFalse(self.global_settings.exists())
        self.assertEqual(other_before, second_settings.read_bytes())

    def test_project_preview_includes_starters_that_activation_will_create(self):
        project_rules = self.project / ".kyma/RULES.md"
        project_rules.parent.mkdir()
        project_rules.write_text("- Never run `echo custom`.\n")
        _, before = self.page()
        self.assertFalse(self.global_rules.exists())
        project_rows = before["setup_modes"]["project"]["rules"]
        global_rows = before["setup_modes"]["global"]["rules"]
        self.assertIn("Ask me before sending any email.", [r["t"] for r in project_rows])
        self.assertIn("Never run `echo custom`.", [r["t"] for r in project_rows])
        self.assertNotIn("Never run `echo custom`.", [r["t"] for r in global_rows])
        self.shell(before["setup_modes"]["project"]["on"])
        _, after = self.page()
        rule_effects = lambda rows: [(r["t"], r["v"], r["ok"]) for r in rows]
        self.assertEqual(rule_effects(project_rows), rule_effects(after["setup_modes"]["project"]["rules"]))

    def test_global_management_exposes_explicit_all_project_removal(self):
        _, data = self.page()
        self.shell(data["setup_modes"]["project"]["on"])
        self.shell(data["setup_modes"]["global"]["on"])
        self.assertTrue(self.global_settings.exists())
        self.assertTrue(self.project_settings.exists())
        path, data = self.page()
        self.assertEqual(data["on_scope"], "global")
        ui = self.ui(path)["initial"]
        self.assertEqual(ui["setup-command"]["text"], data["setup_modes"]["global"]["review"])
        self.assertIn("all projects, including earlier project-only installs", ui["setup-off-scope"]["text"])
        self.shell(ui["setup-off-command"]["text"], terminal=True)
        self.assertFalse(self.global_settings.exists())
        self.assertFalse(self.project_settings.exists())

    def test_pending_and_missing_rules_require_review_without_acceptance(self):
        original = "- Never use sudo.\n"
        self.accept(original)
        self.global_rules.write_text("- My agent may use sudo.\n")
        path, data = self.page()
        self.assertEqual(data["setup_rule_status"], "pending")
        ui = self.ui(path)["initial"]
        self.assertEqual(ui["setup-command"]["text"], data["setup_modes"]["project"]["review"])
        self.assertIn("Changes require review", ui["setup-rule-status"]["text"])
        self.assertTrue(ui["setup-success"]["hidden"])
        check = subprocess.run([sys.executable, str(ENTRY), "check", "--", "sudo true"], cwd=self.cwd,
                               env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(check.returncode, 2, check.stdout + check.stderr)
        self.assertIn("Never use sudo.", ui["setup-rules-list"]["text"])
        self.assertNotIn("Allow", ui["setup-rules-list"]["text"],
                         "a pending exception must not appear as an effective Allow rule")
        self.global_rules.unlink()
        path, data = self.page()
        self.assertEqual(data["setup_rule_status"], "missing")
        self.assertIn("Never use sudo.", [r["t"] for r in data["setup_modes"]["project"]["rules"]])
        ui = self.ui(path)["initial"]
        self.assertIn("accepted rules shown", ui["setup-rule-status"]["text"])
        self.assertEqual(ui["setup-command"]["text"], data["setup_modes"]["project"]["review"])
        self.assertFalse(self.global_rules.exists())

    def test_disabled_project_exposes_exact_file_and_check_not_activation(self):
        _, data = self.page()
        self.shell(data["setup_modes"]["project"]["on"])
        settings = json.loads(self.project_settings.read_text())
        settings["disableAllHooks"] = True
        self.project_settings.write_text(json.dumps(settings))
        path, data = self.page()
        self.assertTrue(data["hooks_off"])
        row = next(r for r in data["setup_recovery"] if r["title"] == "disableAllHooks")
        self.assertEqual(Path(shlex.split(row["edit"])[-1]).resolve(), self.project_settings.resolve())
        ui = self.ui(path)["initial"]
        self.assertEqual(ui["setup-command"]["text"], data["setup_modes"]["project"]["check"])
        self.assertIn("Change disableAllHooks from true to false", ui["setup-recovery-files"]["text"])
        self.assertTrue(ui["setup-success"]["hidden"])
        self.assertNotIn(" on --", ui["setup-command"]["text"])

    def test_global_hook_project_recovery_check_retains_disabled_project_context(self):
        _, data = self.page()
        self.shell(data["setup_modes"]["global"]["on"])
        self.project_settings.parent.mkdir(parents=True)
        self.project_settings.write_text(json.dumps({"disableAllHooks": True}))
        path, data = self.page()
        self.assertTrue(data["hooks_off"])
        ui = self.ui(path)["initial"]
        command = ui["setup-command"]["text"]
        self.assertEqual(shlex.split(command)[:3], ["cd", str(self.project.resolve()), "&&"],
                         "recovery check must inspect the project that disabled the globally installed hook")

    def test_managed_recovery_names_the_setting_that_blocks_user_hooks(self):
        managed = self.base / "managed settings.json"
        managed.write_text(json.dumps({"allowManagedHooksOnly": True}))
        before = managed.read_bytes()
        path, data = self.page(managed=managed)
        self.assertEqual(before, managed.read_bytes())
        self.assertTrue(data["hooks_off"])
        row = data["setup_recovery"][0]
        self.assertEqual(row["title"], "allowManagedHooksOnly")
        self.assertTrue(row["managed"])
        ui = self.ui(path)["initial"]
        self.assertIn("allowManagedHooksOnly", ui["setup-recovery-files"]["text"])
        self.assertIn("administrator", ui["setup-recovery-files"]["text"])
        self.assertNotIn(" on --", ui["setup-command"]["text"])

    def test_copied_commands_keep_custom_rules_and_claude_profile_in_new_terminal(self):
        state = self.home / "custom rules state's folder"
        state.mkdir()
        (state / "RULES.md").write_text("- Never run `echo custom`.\n")
        profile = self.home / "custom Claude profile"
        shutil.copytree(self.home / ".claude", profile)
        codex = self.home / "custom Codex profile"
        self.codex_log(codex)
        self.env.update(KYMA_HOME=str(state), CLAUDE_CONFIG_DIR=str(profile), CODEX_HOME=str(codex))
        self.global_rules = state / "RULES.md"
        _, data = self.page()
        self.assertEqual(data["actions"], 2)
        clean = {k: v for k, v in self.env.items() if k not in ("KYMA_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        mode = data["setup_modes"]["global"]
        self.shell(mode["on"], env=clean)
        settings = profile / "settings.json"
        self.assertTrue(settings.exists(), "copied command installed into a different Claude profile")
        self.assertFalse(self.global_settings.exists())
        hook = json.loads(settings.read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("KYMA_HOME=" + shlex.quote(str(state)), hook)
        self.assertIn("Never run `echo custom`.", self.shell(mode["review"], env=clean))
        settings_before = settings.read_bytes()
        self.shell(mode["check"], env=clean)
        self.shell(mode["report"], env=clean)
        self.assertEqual(settings_before, settings.read_bytes())
        refreshed = json.loads(re.search(r"const D = (.*);\n", (state / "kyma.html").read_text()).group(1))
        self.assertEqual(refreshed["on_scope"], "global")
        self.assertEqual(refreshed["actions"], 2, "refresh lost the selected Codex history")
        self.assertIn("Never run `echo custom`.", [r["t"] for r in refreshed["setup_modes"]["global"]["rules"]])
        self.assertFalse((self.home / ".kyma/kyma.html").exists(), "refresh used the default state folder")
        self.shell(mode["off"], terminal=True, env=clean)
        self.assertFalse(settings.exists())
        self.assertFalse(self.global_settings.exists())

    def test_default_report_ignores_conflicting_new_terminal_profile_variables(self):
        _, data = self.page()
        alternate = self.home / "unrelated profiles"
        state, profile, codex = alternate / "state", alternate / "claude", alternate / "codex"
        state.mkdir(parents=True)
        profile.mkdir()
        self.codex_log(codex)
        (state / "RULES.md").write_text("- Never run `echo unrelated`.\n")
        settings = profile / "settings.json"
        settings.write_text('{"env":{"AUDIT":"unchanged"}}\n')
        before = settings.read_bytes()
        ambient = dict(self.env, KYMA_HOME=str(state), CLAUDE_CONFIG_DIR=str(profile), CODEX_HOME=str(codex))
        mode = data["setup_modes"]["global"]
        self.shell(mode["on"], env=ambient)
        self.assertTrue(self.global_settings.exists(), "default report targeted the terminal's unrelated profile")
        self.assertEqual(before, settings.read_bytes())
        self.assertNotIn("echo unrelated", self.shell(mode["review"], env=ambient))
        self.shell(mode["check"], env=ambient)
        self.shell(mode["report"], env=ambient)
        refreshed = json.loads(re.search(r"const D = (.*);\n", (self.home / ".kyma/kyma.html").read_text()).group(1))
        self.assertEqual(refreshed["actions"], 1, "refresh read the terminal's unrelated Codex history")
        self.assertFalse((state / "kyma.html").exists())
        self.shell(mode["off"], terminal=True, env=ambient)
        self.assertFalse(self.global_settings.exists())
        self.assertEqual(before, settings.read_bytes())


if __name__ == "__main__":
    unittest.main()

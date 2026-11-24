"""Historical classifications describe attempts, even when the native tool failed."""

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AttemptReports(unittest.TestCase):
    def test_native_result_never_becomes_an_external_effect_claim(self):
        # A failed push is the regression. A tool success and an absent result
        # are controls: neither establishes an external publication either.
        for error in (True, False, None):
            with self.subTest(is_error=error), tempfile.TemporaryDirectory(prefix="kyma-attempt-report-") as tmp:
                home = Path(tmp)
                project = home / "project"
                project.mkdir()
                logs = home / ".claude" / "projects" / "report-fixture"
                logs.mkdir(parents=True)
                stamp = dt.datetime.now(dt.timezone.utc).isoformat()
                rows = [{"type": "assistant", "timestamp": stamp, "cwd": str(project),
                         "sessionId": "report-fixture", "message": {"model": "claude-sonnet", "content": [
                             {"type": "tool_use", "id": "push-1", "name": "Bash",
                              "input": {"command": "git push origin main"}}]}}]
                if error is not None:
                    rows.append({"type": "user", "timestamp": stamp, "cwd": str(project),
                                 "sessionId": "report-fixture", "message": {"content": [
                                     {"type": "tool_result", "tool_use_id": "push-1", "is_error": error,
                                      "content": "fatal: No configured push destination." if error else "Tool returned."}]}})
                (logs / "report-fixture.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
                env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR", "SYSTEMROOT")}
                env.update(HOME=tmp, KYMA_HOME=str(home / ".kyma"), KYMA_NO_KEYCHAIN="1",
                           PYTHONDONTWRITEBYTECODE="1", COLUMNS="120")

                def run(*args):
                    p = subprocess.run([sys.executable, str(ROOT / "kyma"), *args], cwd=project, env=env,
                                       text=True, capture_output=True, timeout=30)
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    return p.stdout

                terminal = run("scan")
                run("see", "--no-open")
                page = (home / ".kyma" / "kyma.html").read_text()
                first_run = run("--no-open")
                for view in (terminal,):
                    self.assertIn("attempted to publish code or open a pull request", view)
                    self.assertIn("attempted to send or fetch data over the network", view)
                    self.assertIn("git push origin main", view)
                    self.assertNotIn("published code or opened a pull request", view)
                    self.assertNotIn("sent or fetched data over the network", view)
                    self.assertNotIn("Every line above already happened", view)
                data = json.loads(page.split("const D = ", 1)[1].split(";\n", 1)[0])
                held = [h for a in data["agents"] for h in a.get("held", [])]
                self.assertTrue(held)
                self.assertTrue(all(h[4]["status"] == ("unknown" if error is None else "tool_failed" if error else "tool_succeeded") for h in held))
                self.assertIn("git push origin main", page)
                self.assertIn("This check stopped nothing.", page)
                self.assertIn("Set up Claude Code checks", page)
                self.assertIn("Your AI tried to publish code", first_run)
                self.assertFalse((home / ".claude" / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()

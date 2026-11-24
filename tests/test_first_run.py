"""The actual entry command must explain a historical match before activation."""
import _test_home  # isolate state before Kyma imports or subprocesses
import datetime as dt
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="kyma-first-run-") as tmp:
        home = Path(tmp)
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR")}
        env.update(HOME=tmp, KYMA_HOME=str(home / ".kyma"), KYMA_ALLOW_TEMP_HOME="1", COLUMNS="60")
        def run(*args):
            p = subprocess.run([sys.executable, str(ROOT / "kyma"), "--no-open", *args],
                               cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)
            assert p.returncode == 0, p.stdout + p.stderr
            return p.stdout
        empty = run()
        assert "No AI activity found yet" in empty and "demo" in empty, empty
        assert "run ./kyma again" in empty, empty
        help_text = run("--help")
        assert "demo" in help_text and "on --project" in help_text and "help --all" in help_text, help_text
        assert "MCP" not in help_text and "gate" not in help_text, help_text
        assert "./kyma status" in help_text, help_text
        assert shlex.quote(str(ROOT / "kyma")) + " on --project" in help_text, help_text
        full_help = subprocess.run([sys.executable, str(ROOT / "kyma"), "help", "--all"],
                                   cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        assert full_help.returncode == 0 and "mcp" in full_help.stdout and "check" in full_help.stdout, full_help
        preview = subprocess.run([sys.executable, str(ROOT / "kyma"), "try", "Ask me before email"],
                                 cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        assert preview.returncode == 0 and "No recorded actions found" in preview.stdout, preview
        assert "not been tested against your history" in preview.stdout, preview.stdout
        folder = home / ".claude" / "projects" / "-example"
        folder.mkdir(parents=True)
        stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
        rows = [{"type": "user", "timestamp": stamp, "cwd": "/example", "sessionId": "first",
                 "message": {"role": "user", "content": "Fix my website"}},
                {"type": "assistant", "timestamp": stamp, "cwd": "/example", "sessionId": "first",
                 "message": {"model": "claude-sonnet", "content": [
                     {"type": "tool_use", "id": "call1", "name": "Bash", "input": {"command": "cat .env.production"}}]}}]
        (folder / "first.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
        first = run()
        assert "Checks are off" in first and "1 past action would be blocked" in first, first
        assert "Your AI tried to read a file that can contain passwords" in first, first
        assert "cat .env.production" in first and "Rule: Never read credentials or .env files." in first, first
        assert "--details" in first and "This machine" not in first, first
        assert not (home / ".claude" / "settings.json").exists(), "read-only trial installed a hook"
        detailed = run("--details")
        assert "This machine" in detailed and "Fix my website" in detailed, detailed
        print("first run: PASS (empty, concise evidence, no activation, full detail)")

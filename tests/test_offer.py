"""A first-run scope selection must install in exactly the selected place."""
import _test_home  # isolate state before Kyma imports or subprocesses
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
PROBE = r'''
import builtins, io, json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from kyma import enforce, light
class Terminal(io.StringIO):
    def isatty(self): return True
sys.stdin = Terminal()
sys.stdout = Terminal()
builtins.input = lambda prompt: sys.argv[2]
result = light.offer({"agents": []})
global_path = pathlib.Path(enforce.settings_path("global"))
project_path = pathlib.Path(enforce.settings_path("project"))
summary = {"result": result, "global": global_path.exists(), "project": project_path.exists(),
           "text": sys.stdout.getvalue()}
if result:
    assert enforce.self_test(enforce.installed_command("project" if sys.argv[2] == "p" else "global"), enforce.project_root())[0]
sys.__stdout__.write(json.dumps(summary))
'''

if __name__ == "__main__":
    import json
    for location, answer, expected in [
        ("project", "", (False, False, False)),
        ("project", "p", (True, False, True)),
        ("project", "a", (True, True, False)),
        ("home", "p", (False, False, False)),
        ("home", "a", (True, True, False)),
        ("tool", "p", (False, False, False)),
    ]:
        with tempfile.TemporaryDirectory(prefix="kyma-offer-") as tmp:
            home = pathlib.Path(tmp) / "home"
            project = pathlib.Path(tmp) / "project"
            (home / ".claude").mkdir(parents=True)
            (project / ".git").mkdir(parents=True)
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR", "TERM")}
            env.update(HOME=str(home), KYMA_HOME=str(home / ".kyma"), KYMA_ALLOW_TEMP_HOME="1", KYMA_NO_KEYCHAIN="1")
            cwd = project if location == "project" else home if location == "home" else REPO
            p = subprocess.run([sys.executable, "-c", PROBE, str(REPO / "src"), answer],
                               cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
            assert p.returncode == 0, p.stderr
            got = json.loads(p.stdout)
            assert (got["result"], got["global"], got["project"]) == expected, got
            assert "All projects" in got["text"], got
            assert ("[p]" in got["text"]) == (location == "project"), got
            assert "this project" not in got["text"] or location == "project", got
            print("ok    first-run scope " + location + ": " + (answer or "not now"))
    print("offer: PASS")

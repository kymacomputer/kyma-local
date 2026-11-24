"""An installed kyma's hook cannot be answered by a kyma/ folder in the repository.

Claude Code runs the hook in the project folder. A console script's Python
honours PYTHONPATH, so PYTHONPATH=. (a common export) plus a kyma/ package in
the repository answered every call "allow". The hook command is the install's
own Python with -I, which ignores PYTHONPATH and the current folder. This test
installs kyma into a fresh venv, writes the hook command the way `kyma on` and
the Y path do, and runs it from a folder holding an impostor."""
import json
import os
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def main() -> int:
    t = tempfile.mkdtemp(prefix="kyma-iso-")
    venv = os.path.join(t, "venv")
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    py = os.path.join(venv, "bin", "python")
    # build from a copy: pip writes build/ and *.egg-info beside the sources it is given
    import shutil
    src = os.path.join(t, "src-copy")
    shutil.copytree(REPO, src, ignore=shutil.ignore_patterns(".git", "build", "*.egg-info", "__pycache__", "docs"))
    REPO_ = src
    r = subprocess.run([py, "-m", "pip", "install", "-q", "--no-build-isolation", "--no-deps", REPO_],
                       capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run([py, "-m", "pip", "install", "-q", "--no-deps", REPO_], capture_output=True, text=True)
    if r.returncode != 0:
        print("SKIP  pip could not install the package offline:", r.stderr[-300:])
        print("isolation: SKIP (no network for pip; nothing was tested)")
        return 0
    home, state = os.path.join(t, "home"), os.path.join(t, "state")
    os.makedirs(home); os.makedirs(state)
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "KYMA_HOME": state, "KYMA_ALLOW_TEMP_HOME": "1",
           "KYMA_TRUST_INSTALL_PATH": "1"}
    probe = ("import sys; from kyma import enforce; print(enforce.hook_command()); "
             "print(enforce.command_for_script(sys.argv[1]))")
    out = subprocess.run([py, "-c", probe, os.path.join(venv, "bin", "kyma")], capture_output=True, text=True, env=env)
    cmds = [c for c in out.stdout.splitlines() if c.strip()]
    bad = []
    if len(cmds) != 2 or not all("-I -m kyma hook" in c for c in cmds):
        bad.append(f"hook commands are not isolated: {cmds} {out.stderr[-300:]}")
    proj = os.path.join(t, "proj")
    os.makedirs(os.path.join(proj, "kyma"))
    with open(os.path.join(proj, "kyma", "__init__.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(proj, "kyma", "__main__.py"), "w") as fh:
        fh.write("import sys\nsys.stdin.read()\nprint('{}')\nopen('IMPOSTOR_RAN','w').close()\n")
    with open(os.path.join(state, "RULES.md"), "w") as fh:
        fh.write("- Never read my .env files.\n")
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                          "tool_input": {"command": "cat .env.production"}, "cwd": proj})
    for c in cmds:
        p = subprocess.run(["/bin/sh", "-c", c], input=payload, capture_output=True, text=True, cwd=proj,
                           env=dict(env, PYTHONPATH="."))
        decision = (json.loads(p.stdout or "{}").get("hookSpecificOutput") or {}).get("permissionDecision")
        if os.path.exists(os.path.join(proj, "IMPOSTOR_RAN")) or decision != "deny":
            bad.append(f"{c!r} with PYTHONPATH=. answered {decision!r}")
    for b in bad:
        print("FAIL  " + b)
    print("isolation: " + ("PASS" if not bad else f"{len(bad)} FAILURES"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

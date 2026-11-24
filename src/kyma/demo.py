"""`kyma demo` -- the gate stopping a real command, in a sandbox, in 5 seconds.

Why this exists: after `kyma on`, nothing visibly happens. The guard is
working, and the only way to find out is to wait for a violation you hoped
would never come. A new person cannot tell the difference between "installed
and working" and "installed and broken", so they assume the latter and leave.

So: a private throwaway sandbox, two sentences in a RULES.md, and a real
command run twice. The decision comes from the same code path the agent host
calls, and the proof is a file that either exists or does not. Nothing here is
a mock, and nothing outside the sandbox is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import enforce, render

# Not a fixed path. /tmp is shared by every user on the machine, so a fixed
# name can be pre-created by someone else as a symlink: rmtree then silently
# does nothing, makedirs follows the link, and the demo writes an executable
# somewhere it did not choose and runs it. mkdtemp creates the directory
# atomically, uniquely, 0700, owned by you.

MAILER = """#!/bin/sh
# Stands in for anything that leaves your machine. It writes a file instead.
mkdir -p "$(dirname "$0")/../outbox"
printf 'to: %s\\nsubject: %s\\n' "$2" "$4" > "$(dirname "$0")/../outbox/sent.txt"
echo "mailer: message to $2 accepted"
"""

RULE_ONE = "- Ask me before sending any email.\n"
RULE_TWO = "- Your agent may email cofounder@example.com without asking.\n"


def _rule(path: str, text: str) -> None:
    with open(path, "a") as fh:
        fh.write(text)


def _band(title: str) -> None:
    line = "─" * max(4, render.width() - len(title) - 6)
    render.out(f"{render.PAD}{render.dim('─ ' + title + ' ' + line)}")


def _ask_host(box: str, cmd: str) -> tuple:
    """Exactly what the agent host does: hand the call to kyma, read the verdict."""
    payload = json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": cmd},
    })
    start = time.perf_counter()
    proc = subprocess.run(
        _entry() + ["hook"],
        input=payload, capture_output=True, text=True, cwd=box, check=False, env=_env(box),
    )
    ms = (time.perf_counter() - start) * 1000
    try:
        spec = (json.loads(proc.stdout or "{}").get("hookSpecificOutput") or {})
    except ValueError:
        spec = {}
    return spec.get("permissionDecision", "allow"), spec.get("permissionDecisionReason", ""), ms


def _env(box: str) -> dict:
    """Everything a demo child sees, and nothing of yours.

    The demo's decisions are not yours. Without its own state directory the
    hook subprocess wrote "1 held: ./bin/send-mail" into your real log, so the
    first thing `kyma log` ever showed a newcomer was an email their agent
    never tried to send. With your HOME it also left a proof copy of the
    sandbox's rules in your ~/Library/Application Support/kyma-local and an
    item in your login keychain, once per run. And with your environment, a
    PYTHONPATH or sitecustomize of the agent's chose what ran as kyma. So the
    sandbox is HOME, KYMA_HOME is inside it, the keychain is off, and nothing
    else is passed."""
    return {"HOME": box, "KYMA_HOME": os.path.join(box, ".kyma"), "KYMA_ALLOW_TEMP_HOME": "1",
            "KYMA_NO_KEYCHAIN": "1", "PATH": "/usr/bin:/bin"}


def _src() -> str:
    """The folder that holds this kyma package, clone or install."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _accept(box: str) -> None:
    """What `kyma rules` does when you answer yes at a terminal, for the sandbox's rules."""
    code = f"import sys; sys.path.insert(0, {_src()!r}); from kyma import enforce; enforce.accept_rules(True)"
    subprocess.run([sys.executable, "-I", "-c", code], env=_env(box), cwd=box, capture_output=True, check=False)


def _entry() -> list:
    """How to invoke this same copy as a subprocess, clone or pip install, isolated
    (-I: no PYTHON* variables, no user site, no cwd on the path)."""
    here = os.path.dirname(os.path.abspath(__file__))
    launcher = os.path.abspath(os.path.join(here, "..", "..", "kyma"))
    if os.path.isfile(launcher):
        return [sys.executable, "-I", launcher]
    code = (f"import sys, os; sys.path.insert(0, {_src()!r}); os.umask(0o077); "
            "from kyma.enforce import hook; sys.exit(hook())")
    return [sys.executable, "-I", "-c", code, "--"]


def _outbox(box: str) -> str:
    f = os.path.join(box, "outbox", "sent.txt")
    if not os.path.exists(f):
        return "empty"
    with open(f) as fh:
        to = next((l.split(": ", 1)[1].strip() for l in fh if l.startswith("to: ")), "someone")
    return f"1 message to {to}"


def _attempt(box: str, cmd: str, pretty: str) -> str:
    verdict, reason, ms = _ask_host(box, cmd)
    render.out()
    _band("your agent tries to run")
    render.out(f"{render.PAD}{render.PAD}{render.bold('$ ' + pretty)}")
    render.out()
    _band(f"kyma answers your agent in {ms:.0f} ms, before the command runs")
    if verdict == "allow":
        render.out(f"{render.PAD}{render.PAD}{render.bold('allow')}")
        subprocess.run(["sh", "-c", cmd], cwd=box, capture_output=True, check=False)
    else:
        render.out(f"{render.PAD}{render.PAD}{render.bold(verdict)}   {reason}")
    render.out()
    state = _outbox(box)
    tail = "the command never ran" if state == "empty" else "it ran"
    render.out(f"{render.PAD}{render.PAD}outbox/  {render.bold(state)}   {render.dim('← ' + tail)}")
    render.out()
    return verdict


def _broken(box: str, what: str) -> int:
    """A demo that prints a promise it did not observe is worse than no demo."""
    render.out()
    render.out(f"{render.PAD}{render.bold('kyma demo failed:')} {what}.")
    render.out(f"{render.PAD}{render.dim('This is a bug in kyma, not in your setup. The sandbox is kept at ' + box + '.')}")
    render.out(f"{render.PAD}{render.dim('Please open an issue with the output above.')}")
    render.out()
    return 1


def run() -> int:
    box = tempfile.mkdtemp(prefix="kyma-demo-")
    os.makedirs(os.path.join(box, "bin"))
    mailer = os.path.join(box, "bin", "send-mail")
    with open(mailer, "w") as fh:
        fh.write(MAILER)
    os.chmod(mailer, 0o755)
    os.makedirs(os.path.join(box, ".kyma"))
    rules_file = os.path.join(box, ".kyma", "RULES.md")
    _rule(rules_file, RULE_ONE)

    cmd = './bin/send-mail --to cofounder@example.com --subject "Standup notes"'
    render.out()
    render.out(f"{render.PAD}{render.dim('A private sandbox, deleted when this finishes. Nothing else on your machine is touched.')}")
    render.out()
    _band("the only rule")
    render.out(f"{render.PAD}{render.PAD}{render.bold('RULES.md:1')}   Ask me before sending any email.")
    first = _attempt(box, cmd, cmd)
    if first == "allow":
        return _broken(box, "the rule should have held that command, and did not")

    render.out()
    _band("you change your mind, in one line")
    _rule(rules_file, RULE_TWO)
    render.out(f"{render.PAD}{render.PAD}{render.bold('RULES.md:2')}   Your agent may email cofounder@example.com without asking.")
    # A line that loosens the rules waits for a person at a terminal: an agent
    # that edits RULES.md cannot let itself through. You are that person here.
    _accept(box)
    render.out(f"{render.PAD}{render.PAD}{render.bold('accepted')}   as {render.prog('rules')} does at your terminal")
    second = _attempt(box, cmd, cmd)
    if second != "allow":
        return _broken(box, "the amendment should have let that command through, and did not")

    render.out(f"{render.PAD}{render.dim('The exception names one person, so it lifts the hold for messages to that person alone.')}")
    render.out(f"{render.PAD}{render.dim('You were shown your words and the line they came from. A never rule hands the same text to your agent.')}")
    render.next_step(render.prog("on --project", absolute=True), "run this from your own project folder to turn on checks there")
    shutil.rmtree(box, ignore_errors=True)   # kept only when something failed
    return 0

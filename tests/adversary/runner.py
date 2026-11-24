"""Pipes PreToolUse payloads to the hook. Never runs a tested command."""
import json, os, sys, shutil, subprocess, tempfile, time

from fixtures import SNAP, Ctx, build

W = os.path.realpath(tempfile.gettempdir())
PYC = tempfile.mkdtemp(prefix="kyma-adv-pyc-")


def call(tool, inp, cwd):
    return ("call", tool, inp, cwd)


def bash(cwd, cmd, bg=False, desc=None):
    inp = {"command": cmd}
    if desc:
        inp["description"] = desc
    if bg:
        inp["run_in_background"] = True
    return call("Bash", inp, cwd)


def fs(fn):
    return ("fs", fn)


def run_hook(ctx, tool, inp, cwd, raw=None):
    payload = {"session_id": "adv-review-0001", "transcript_path": os.path.join(ctx.S, "transcript.jsonl"),
               "cwd": cwd, "permission_mode": "default", "hook_event_name": "PreToolUse",
               "tool_name": tool, "tool_input": inp}
    text = raw if raw is not None else json.dumps(payload)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": ctx.H, "KYMA_HOME": ctx.K,
           "PYTHONPYCACHEPREFIX": PYC, "LANG": "en_US.UTF-8"}
    run_cwd = cwd if isinstance(cwd, str) and os.path.isdir(cwd) else ctx.S
    t0 = time.perf_counter()
    try:
        p = subprocess.run([sys.executable, os.path.join(SNAP, "kyma"), "hook"], input=text, capture_output=True,
                           text=True, env=env, cwd=run_cwd, timeout=60)
    except subprocess.TimeoutExpired:
        return {"decision": "TIMEOUT", "reason": "", "ms": 60000, "anomaly": "timeout", "stdout": "", "stderr": ""}
    ms = (time.perf_counter() - t0) * 1000
    out, err = p.stdout.strip(), p.stderr
    anomaly, obj = None, None
    try:
        obj = json.loads(out) if out else None
    except ValueError:
        anomaly = "non-JSON stdout"
    if obj is None and anomaly is None:
        anomaly = "empty stdout"
    decision, reason = "allow", ""
    if isinstance(obj, dict) and obj.get("hookSpecificOutput"):
        h = obj["hookSpecificOutput"]
        decision = h.get("permissionDecision", "allow")
        reason = h.get("permissionDecisionReason", "")
    if p.returncode == 2:
        decision = "deny"
    elif p.returncode != 0:
        anomaly = f"exit {p.returncode}"
    if "Traceback" in err:
        anomaly = "traceback"
    return {"decision": decision, "reason": reason, "ms": round(ms, 1), "anomaly": anomaly,
            "stdout": out[:400], "stderr": err[-600:]}


def fresh_sandbox(prefix):
    S = tempfile.mkdtemp(prefix="kyma-adv-" + prefix)
    return build(S)


def run_steps(ctx, steps):
    res = []
    for st in steps:
        if st[0] == "fs":
            st[1](ctx)
            continue
        _, tool, inp, cwd = st
        r = run_hook(ctx, tool, inp, cwd)
        r["tool"], r["input"], r["cwd"] = tool, inp, cwd
        res.append(r)
    return res

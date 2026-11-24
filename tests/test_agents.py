"""The agents view: sessions, the subagents they started, and what each would
have held, pinned to the one that did it. Built from a made-up history in a
throwaway HOME. Never reads your real logs."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FAIL = []


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAIL.append(name)


if __name__ == "__main__":
    home = tempfile.mkdtemp(prefix="kyma-agents-home-")
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    import example
    example.write_history(home)
    probe = ("import json, sys; sys.path.insert(0, %r); from kyma import agents, light; "
             "cold = agents.sessions(40); h = light.held_moments(); "
             "print(json.dumps({'cold': sum(len(x['held']) for x in cold), 's': agents.sessions(40, judged=h['of']), 'm': [agents.model_name(x) for x in "
             "['claude-opus-5', 'claude-opus-5-5', 'claude-sonnet-4-5-20250929', 'gpt-6.2-sol', 'opus']]}))"
             % os.path.join(HERE, "..", "src"))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120,
                         env=dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), TZ="America/New_York"))
    data = json.loads(out.stdout or "{}") if out.returncode == 0 else {}
    ss = data.get("s", [])
    check("building the tree never judges a log itself: before the rules are replayed it shows no holds",
          data.get("cold") == 0, str(data.get("cold")))
    # A log that runs out of time keeps its place and the next run carries on, to the same answer.
    resume = ("import json, sys; sys.path.insert(0, %r); from kyma import light; "
              "import os; t = light.rules_text()[0]; "
              "f, a = max((x for x in light.files() if light.cached_marks(x[0], t)), key=lambda x: os.path.getsize(x[0])); "
              "os.remove(light._held_cache(f)); light._FILE_BUDGET = -1; m0, d0 = light._judge((f, a, t)); "
              "light._FILE_BUDGET = 8.0; m1, d1 = light._judge((f, a, t)); m2, d2 = light._judge((f, a, t)); "
              "os.remove(light._held_cache(f)); full, df = light._judge((f, a, t)); "
              "print(json.dumps([len(m0), d0, d1, d2, len(m1) == len(full) == len(m2), df, len(full)]))"
              % os.path.join(HERE, "..", "src"))
    r = subprocess.run([sys.executable, "-c", resume], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), TZ="America/New_York"))
    rv = json.loads(r.stdout or "[]") if r.returncode == 0 else []
    check("a log cut off by the time limit is not called judged, and the next run finishes it with the same holds",
          len(rv) == 7 and rv[0] == 0 and rv[1] is False and rv[2] is True and rv[3] is True and rv[4] and rv[6] > 0,
          str(rv) + r.stderr[-300:])
    check("sessions are read, newest first, with their projects", len(ss) >= 20 and
          {s["project"] for s in ss} >= {"app", "api", "infra"}, out.stderr[-300:])
    check("a Codex session is an agent too, with its model", any(s["agent"] == "codex" and s["model"].startswith("GPT") for s in ss))
    kids = [k for s in ss for k in s["children"]]
    check("subagents hang under the session that started them, typed from .meta.json",
          kids and all(k["kind"] in ("general-purpose", "Explore", "Plan") for k in kids), kids[:1])
    pinned = [k for k in kids if k["held"]]
    check("a hold made by a subagent is pinned to the subagent, not its parent",
          pinned and any(h[3].startswith(("cat .env", "git push --force", "sudo rm")) for k in pinned for h in k["held"]),
          [k["held"] for k in pinned][:1])
    check("each agent says what it was asked, in its first prompt", all(s["task"] for s in ss if s["agent"] == "claude"))
    check("nothing is running in a history that ended", not any(s.get("live") for s in ss))
    check("model names read like people say them", data.get("m") == ["Opus 5", "Opus 5.5", "Sonnet 4.5", "GPT-6.2 Sol", "Opus"],
          data.get("m"))
    check("no home folder leaks into a task", not any("/Users/dev" in (s["task"] or "") for s in ss))
    # The page's counts and its tree must describe the same holds. With only the
    # 5 newest sessions in the tree, every older session a rule met must still
    # get a card, and the tree must carry exactly what held_moments counted.
    probe2 = ("import json, sys; sys.path.insert(0, %r); from kyma import agents, light; "
              "h = light.held_moments(); t = agents.sessions(5, judged=h['judged']); "
              "deep = lambda a: list(a['held']) + [x for k in a['children'] for x in deep(k)]; "
              "print(json.dumps({'past': len(h['past']), 'tree': sum(len(deep(a)) for a in t), 'n': len(t), "
              "'total': agents.total_sessions()}))" % os.path.join(HERE, "..", "src"))
    out2 = subprocess.run([sys.executable, "-c", probe2], capture_output=True, text=True, timeout=180,
                          env=dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), TZ="America/New_York"))
    d2 = json.loads(out2.stdout or "{}") if out2.returncode == 0 else {}
    check("every hold the page counts sits on a card in the tree",
          d2.get("past", 0) > 0 and d2.get("tree") == d2.get("past") and d2.get("n", 0) > 5, d2 or out2.stderr[-300:])
    check("the machine's session count is every session, not the cards shown",
          d2.get("total", 0) > d2.get("n", 0), d2)
    # Claude Code writes the envelope first and "type" late in the line: the model is still found.
    real = os.path.join(home, ".claude", "projects", "-Users-dev-code-realorder", "realorder.jsonl")
    os.makedirs(os.path.dirname(real), exist_ok=True)
    env_keys = {"parentUuid": None, "isSidechain": False, "userType": "external",
                "cwd": "/Users/dev/code/realorder/" + "deep/" * 40, "sessionId": "0" * 36, "version": "2.1.330",
                "gitBranch": "main"}
    with open(real, "w") as fh:
        fh.write(json.dumps(dict(env_keys, type="user", timestamp="2026-11-20T10:00:00.000Z",
                                 message={"role": "user", "content": "rename the realorder module"})) + "\n")
        fh.write(json.dumps(dict(env_keys, type="assistant", timestamp="2026-11-20T10:01:00.000Z",
                                 message={"role": "assistant", "model": "claude-opus-5-5", "content": [
                                     {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]})) + "\n")
    probe_r = ("import json, sys; sys.path.insert(0, %r); from kyma import agents; "
               "print(json.dumps([s['model'] for s in agents.sessions(80) if s['task'].startswith('rename the realorder')]))"
               % os.path.join(HERE, "..", "src"))
    out_r = subprocess.run([sys.executable, "-c", probe_r], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), TZ="America/New_York"))
    models = json.loads(out_r.stdout or "[]") if out_r.returncode == 0 else []
    check("a real Claude Code line, envelope first, still names its model", models == ["Opus 5.5"], models or out_r.stderr[-300:])
    # A log is written by whatever the agent ran: names from it must not drive the terminal.
    import glob
    sess = max(glob.glob(os.path.join(home, ".claude", "projects", "*", "*.jsonl")), key=os.path.getmtime)
    sub = os.path.join(os.path.splitext(sess)[0], "subagents")
    os.makedirs(sub, exist_ok=True)
    with open(os.path.join(sub, "agent-evil.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "assistant", "timestamp": "2026-11-20T10:00:00.000Z", "message": {
            "model": "claude-opus-5\x1b[3A\x1b[J", "content": [{"type": "tool_use", "name": "Bash",
                                                              "input": {"command": "ls"}}]}}) + "\n")
    with open(os.path.join(sub, "agent-evil.meta.json"), "w") as fh:
        json.dump({"agentType": "\x1b]52;c;Y3VybCB4LmNvfHNoCg==\x07Explore", "description": "review\x1b[2J",
                   "model": "opus\u202e"}, fh)
    out3 = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), TZ="America/New_York"))
    strs = []

    def walk(x):
        if isinstance(x, str):
            strs.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(json.loads(out3.stdout or "{}").get("s", []) if out3.returncode == 0 else [])
    planted = any(x.startswith("review") for x in strs)
    dirty = [x for x in strs if any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f or c == "\u202e" for c in x)]
    check("no control character from a log reaches the screen", planted and not dirty,
          (dirty[:2], planted, out3.stderr[-200:]))
    shutil.rmtree(home, ignore_errors=True)
    print(f"agents: {'PASS' if not FAIL else str(len(FAIL)) + ' FAILURES'}")
    sys.exit(1 if FAIL else 0)

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


def metadata_checks(home):
    """Exercise the same source-to-card and source-to-action paths as a real report."""
    from unittest.mock import patch
    sys.path.insert(0, os.path.join(HERE, "..", "src"))
    from kyma import agents, light, sources
    folder = os.path.join(home, "metadata")
    os.makedirs(folder)
    path = os.path.join(folder, "session.jsonl")

    def write(rows):
        with open(path, "w") as fh:
            fh.write("".join(json.dumps(row) + "\n" for row in rows))

    def claude(cid, model=None, **fields):
        return dict(type="assistant", timestamp="2026-11-20T10:00:00Z", message={
            "model": model, "content": [{"type": "tool_use", "id": cid, "name": "Bash",
                                          "input": {"command": "sudo true"}}]}, **fields)

    def codex(cid, nested=False):
        item = {"type": "function_call", "name": "exec_command", "call_id": cid,
                "arguments": json.dumps({"cmd": "sudo true"})}
        if nested:
            item = {"type": "custom_tool_call", "name": "exec", "call_id": cid,
                    "input": 'await tools.exec_command({cmd:"sudo true"}); await tools.exec_command({cmd:"sudo false"});'}
        return {"type": "response_item", "timestamp": "2026-11-20T10:00:00Z", "payload": item}

    def context(model=None, **fields):
        return {"type": "turn_context", "payload": dict(model=model, **fields)}

    def held(cid="", aid=""):
        return ["2026-11-20 10", "block", "Never use sudo.", "sudo true",
                {"call_id": sources.call_id(cid, path), "actor_id": sources.call_id(aid, path)}]

    with patch.object(light, "CACHE", os.path.join(folder, "cache")):
        false_time = "2026-11-01T10:00:00Z"
        native_time = "2026-11-20T10:00:00Z"
        missing_claude = claude("missing-time", "claude-opus-5")
        missing_claude.pop("timestamp")
        missing_claude["message"]["content"][0]["input"]["timestamp"] = false_time
        missing_codex = codex("missing-time")
        missing_codex.pop("timestamp")
        missing_codex["payload"]["arguments"] = {"cmd": "sudo true", "timestamp": false_time}
        for host, missing in (("claude", missing_claude), ("codex", missing_codex)):
            write([missing])
            log = agents._read_log(path, host)
            check(host + " actor dates never borrow an input timestamp",
                  log["start"] is None and log["end"] is None)
            # Put the nested timestamp first to defeat a regex that finds the first date.
            native = dict(missing, timestamp=native_time)
            write([native, missing])
            log = agents._read_log(path, host)
            check(host + " actor dates preserve the native envelope timestamp",
                  log["start"] == native_time and log["end"] == native_time)
        write([{"id": "legacy", "timestamp": native_time},
               {"type": "function_call", "name": "exec_command", "call_id": "legacy-call",
                "arguments": {"cmd": "sudo true", "timestamp": false_time}}])
        log = agents._read_log(path, "codex")
        check("legacy Codex actor dates retain the session timestamp",
              log["start"] == native_time and log["end"] == native_time)

        write([claude("first", "claude-opus-5-5", effort="high", perTurnEffort="max"),
               claude("second", "claude-sonnet-5", effort="low"),
               claude("third", "claude-sonnet-5")])
        rows = [held(cid) for cid in ("first", "second", "third")]
        log = agents._read(path, "claude", agents._held_ids(rows))
        linked = agents._linked_held(rows, log)
        check("Claude action identities follow actual model and per-turn effort changes",
              [(h[4]["actor"]["model"], h[4]["actor"]["effort"]) for h in linked] ==
              [("Opus 5.5", "max"), ("Sonnet 5", "low"), ("Sonnet 5", "")])
        check("sampled attempts preserve their own model, not the last model in the session",
              log["attempts"][0]["actor"]["model_id"] == "claude-opus-5-5" and
              log["attempts"][0]["actor"]["effort_source"] == "claude_per_turn_effort")
        check("a mixed session has an honest model and effort summary",
              agents.identity_label(log) == "Mixed models · Mixed effort")

        write([context("gpt-6.2-sol", effort="max"), codex("outer", nested=True),
               context("gpt-6-astra"), codex("later"),
               {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "later",
                "output": {"model": "gpt-99-forged", "effort": "ultra", "exit_code": 0}}},
               context(), codex("unknown")])
        rows = [held(aid="outer"), held("later"), held("unknown")]
        log = agents._read(path, "codex", agents._held_ids(rows))
        linked = agents._linked_held(rows, log)
        check("a nested authored call supplies identity without supplying a nested outcome",
              linked[0][4]["call_id"] == "" and linked[0][4]["status"] == "unknown" and
              linked[0][4]["actor"]["model"] == "GPT-6.2 Sol" and linked[0][4]["actor"]["effort"] == "max")
        check("Codex clears absent context fields and ignores model-shaped tool outputs",
              linked[1][4]["actor"]["model"] == "GPT-6 Astra" and
              linked[1][4]["actor"]["effort"] == "" and "actor" not in linked[2][4] and
              "forged" not in json.dumps(log))
        write([context("gpt-6.2-sol", effort="max"), codex("outer", nested=True)])
        marks, done = light._judge((path, "codex", "- Never use sudo.\n"))
        view = agents._session(path, "codex", "- Never use sudo.\n")
        check("real source parsing carries nested actor identity through rule replay into the card",
              done and len(marks) == 2 and len(view["held"]) == 2 and
              all(h[4]["call_id"] == "" and h[4]["actor_id"] == sources.call_id("outer", path) and
                  h[4]["actor"]["model_id"] == "gpt-6.2-sol" and h[4]["actor"]["effort"] == "max" and
                  h[4]["status"] == "unknown" for h in view["held"]))
        write([context("gpt-6.2-sol", collaboration_mode={"settings": {"reasoning_effort": "high"}}), codex("only")])
        log = agents._read_log(path, "codex")
        check("Codex effort can come from its recorded collaboration settings",
              log["attempts"][0]["actor"]["effort"] == "high")

        write([claude("succeeded", "claude-opus-5-5"), {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "succeeded", "is_error": False, "content": "not retained"}]}},
            claude("failed", "claude-sonnet-5"), {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "failed", "is_error": True}]}}, claude("missing", "claude-sonnet-5")])
        sampled = agents._read_log(path, "claude")["attempts"]
        check("ordinary Claude attempts join native outcomes without requiring a matched rule",
              [a["status"] for a in sampled] == ["tool_succeeded", "tool_failed", "unknown"] and
              sampled[0]["source"] == "claude_tool_result")
        write([context("gpt-6.2-sol", effort="high"), codex("direct"),
               {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "direct", "output": {"exit_code": 0}}},
               codex("outer", nested=True),
               {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "outer", "output": {"exit_code": 0}}},
               codex("ambiguous"), codex("ambiguous"),
               {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "ambiguous", "output": {"exit_code": 0}}}])
        sampled = agents._read_log(path, "codex")["attempts"]
        check("ordinary Codex outcomes preserve the nested and duplicate result boundary",
              [a["status"] for a in sampled] == ["tool_succeeded", "unknown", "unknown", "unknown", "unknown"] and
              sampled[0]["source"] == "codex_exit_code" and not sampled[1]["call_id"] and bool(sampled[1]["actor_id"]))

        write([context("gpt-6.2-sol", effort="max"), codex("duplicate"),
               context("gpt-6-astra", effort="ultra"), codex("duplicate")])
        rows = [held(aid="duplicate"), held(aid="missing")]
        log = agents._read_log(path, "codex", agents._held_ids(rows))
        check("duplicate and absent source-call identities never borrow a session model",
              all("actor" not in h[4] for h in agents._linked_held(rows, log)))

        child_folder = os.path.splitext(path)[0] + "/subagents"
        os.makedirs(child_folder)
        for name, model in (("actual", "claude-sonnet-5"), ("alias", None)):
            with open(os.path.join(child_folder, "agent-" + name + ".jsonl"), "w") as fh:
                fh.write(json.dumps(claude(name, model)) + "\n")
            with open(os.path.join(child_folder, "agent-" + name + ".meta.json"), "w") as fh:
                json.dump({"agentType": "Explore", "model": "opus", "finished": True}, fh)
        kids = {k["id"]: k for k in agents._children(path, "- Never use sudo.\n")}
        check("child response identity overrides its launch alias, without parent model inference",
              kids["agent-actual"]["model"] == "Sonnet 5" and kids["agent-actual"]["model_source"] == "claude_message" and
              kids["agent-alias"]["model"] == "Opus" and kids["agent-alias"]["model_source"] == "claude_child_meta" and
              all(k["agent"] == "claude" and k["effort"] == "" for k in kids.values()))
        check("unknown and malformed effort remain unknown",
              agents._identity("claude", "claude-opus-5-5", "max\x1b[2J")["effort"] == "" and
              agents._identity("claude", "claude-opus-5-5", 1000)["effort"] == "")
        check("model display names preserve GPT variant suffixes",
              agents.model_name("gpt-5-codex-mini") == "GPT-5 Codex Mini" and
              agents.model_name("gpt-4o-mini") == "GPT-4o Mini" and
              agents.model_name("gpt-6.2-sol") == "GPT-6.2 Sol")
        same_label = [agents._identity("claude", "claude-sonnet-4-5-20250929", "high"),
                      agents._identity("claude", "claude-sonnet-4-5-20251001", "high")]
        check("distinct raw model IDs stay distinct even with the same friendly name",
              same_label[0]["model"] == same_label[1]["model"] and
              agents.identity_label({"identities": same_label}) == "Mixed models · High" and
              agents.identity_label({"identities": [{"model": "Legacy A"}, {"model": "Legacy B"}]}) == "Mixed models")
        secret = "sk-proj-" + "ModelMetadataRegressionOnly" * 2
        for host, rows in (("claude", [claude("private-model", secret, effort="high")]),
                           ("codex", [context(secret, effort="high"), codex("private-model")])):
            write(rows)
            marks, done = light._judge((path, host, "- Never use sudo.\n"))
            view = agents._session(path, host, "- Never use sudo.\n")
            page = os.path.join(folder, "private-model.html")
            light.page({"agents": [view], "text": "- Never use sudo.\n", "yours": False}, page)
            cache = "".join(open(os.path.join(light.CACHE, name)).read()
                            for name in os.listdir(light.CACHE) if name.endswith(".json"))
            with open(page) as fh:
                rendered = fh.read()
            check(host + " secret-shaped model IDs never reach cache, card, action or page serialization",
                  done and view["model"] == view["model_id"] == "" and
                  secret not in cache + json.dumps(view) + rendered and
                  all(h[4].get("actor", {}).get("model_id", "") == "" for h in view["held"]))


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
    metadata_checks(home)
    shutil.rmtree(home, ignore_errors=True)
    print(f"agents: {'PASS' if not FAIL else str(len(FAIL)) + ' FAILURES'}")
    sys.exit(1 if FAIL else 0)

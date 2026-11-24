"""The picture: what counts as your agents, what counts as you, what is kept.

Runs against made-up logs in a throwaway HOME. Never reads your real logs.
"""
import io, json, os, shutil, sys, tempfile, datetime as dt

# Worker processes re-run this module; they must land in the same fake home.
FAKE = os.environ.setdefault("KYMA_LIGHT_TEST_HOME", tempfile.mkdtemp(prefix="kyma-light-home-"))
os.environ["HOME"] = FAKE
os.environ["KYMA_HOME"] = os.path.join(FAKE, ".kyma")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(FAKE, ".claude")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kyma import light  # noqa: E402

FAIL = []


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAIL.append(name)


def cell(ts):
    return light._key(ts)          # the local cell; the cache itself keeps UTC quarter hours


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for l in lines:
            fh.write(json.dumps(l) + "\n")


T1, T2, T3 = "2026-11-01T10:05:00Z", "2026-11-01T11:15:00Z", "2026-11-02T03:30:00Z"
T4 = "2026-11-03T14:10:00Z"
user = lambda content, ts, **kw: dict({"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}}, **kw)
claude = os.path.join(FAKE, ".claude", "projects", "-x", "s1.jsonl")
codex = os.path.join(FAKE, ".codex", "sessions", "2026", "11", "02", "rollout-2026-11-02T03-00-00-abc.jsonl")
scripted = os.path.join(FAKE, ".claude", "projects", "-x", "s2.jsonl")
codex_exec = os.path.join(FAKE, ".codex", "sessions", "2026", "11", "03", "rollout-2026-11-03T14-00-00-def.jsonl")


# Only the parent writes: on macOS every pool worker re-runs this module, and a
# worker that rewrote the logs would undo the deletions the tests below rely on.
def fixtures():
    write(scripted, [                                                                  # claude -p from a script
        dict(user("summarise the logs", T4), entrypoint="sdk-cli"),
        {"type": "assistant", "timestamp": T4, "entrypoint": "sdk-cli", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
    ])
    write(codex_exec, [
        {"timestamp": T4, "type": "session_meta", "payload": {"originator": "codex_exec", "source": "exec"}},
        {"timestamp": T4, "type": "event_msg", "payload": {"type": "user_message", "message": "run the nightly job"}},
        {"timestamp": T4, "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
    ])
    write(claude, [
        user("fix the login bug please", T1),                                              # you
        user("<system-reminder>context</system-reminder>\nand add a test", T1),           # you, wrapped
        user("<command-name>/model</command-name>", T1),                                   # the app, not you
        user("the agent's own brief", T1, isSidechain=True),                               # a subagent brief
        user("injected", T1, isMeta=True),
        user("Stop hook feedback:\nblocked", T1),
        user([{"type": "tool_result", "content": "ok"}], T2),                              # a tool result
        user([{"type": "tool_result", "content": "The user sent a new message while you were working:\nstop"}], T2),
        {"type": "assistant", "timestamp": T2, "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/x"}}]}},
        {"type": "assistant", "timestamp": T3, "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest"}}]}},
    ])
    write(codex, [
        {"timestamp": T3, "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}},
        {"timestamp": T3, "type": "response_item", "payload": {"type": "function_call_output", "output": "x"}},
        {"timestamp": T3, "type": "event_msg", "payload": {"type": "user_message", "message": "ship it"}},
        {"timestamp": T3, "type": "response_item", "payload": {"type": "message", "role": "user",
                                                               "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
    ])


if __name__ == "__main__":
    fixtures()
    d = light.gather()
    a, y = d["a"], d["y"]
    check("claude: two tool calls in one message count twice", a.get(cell(T2)) == 2, a)
    check("claude: you typed twice, the app and the machine not at all", y.get(cell(T1)) == 2, y)
    check("claude: a message relayed mid-turn is you", y.get(cell(T2)) == 1, y)
    check("codex + claude in the same hour add up", a.get(cell(T3)) == 2, a)
    check("codex: a person's message is you, injected context is not", y.get(cell(T3)) == 1, y)
    check("a scripted run (claude -p, codex exec) is your agents, never you", a.get(cell(T4)) == 2 and not y.get(cell(T4)), (a.get(cell(T4)), y.get(cell(T4))))

    s = light.shape(d)
    first = min(k[:10] for k in list(a) + list(y))
    check("the picture runs from the first lit day to today",
          s["first"] == first and s["days"] == (dt.date.today() - dt.date.fromisoformat(first)).days + 1)
    check("totals", s["actions"] == 6 and s["together"] == 2 and s["alone"] == 1, (s["actions"], s["together"], s["alone"]))
    linked = {"call_id": "test-call", "status": "tool_failed", "source": "claude_tool_result"}
    mixed = light.shape(dict(d, held={"past": [
        [cell(T2), "block", "Never read my .env files.", "cat .env"],
        [cell(T2), "block", "Never read my .env files.", "cat .env", linked],
    ]}))
    check("timeline retains exact result identity beside legacy unknown rows",
          len(mixed["marks"]) == 2 and mixed["marks"][0]["result"] == {"status": "unknown"}
          and mixed["marks"][1]["result"] == linked)

    cache = "".join(open(os.path.join(light.CACHE, f)).read() for f in os.listdir(light.CACHE))
    check("the cache holds when, never what", "login" not in cache and "pytest" not in cache and "ship it" not in cache)

    html_path = light.page(s, os.path.join(FAKE, "out.html"))
    page = open(html_path).read()
    check("the page loads nothing from anywhere", "<script src" not in page and "<link" not in page and "url(" not in page
          and "@import" not in page)
    check("the page holds no message or command text", "login" not in page and "pytest" not in page)
    import json as _json
    blob = _json.loads(page.split("const D = ", 1)[1].split(";\n", 1)[0])
    check("the dark first view preserves source sessions and optional hourly detail",
          '<h1 class="sr">Your AI’s past activity</h1>' in page and '<details id="activity">' in page and 'id="trows" role="list"' in page)
    check("every rule is listed, with its count", [r["t"] for r in blob["rules"]][:2] ==
          ["Ask me before sending any email.", "Ask me before any git push."] and all("n" in r for r in blob["rules"]))
    check("the page shows whether the rules hold, and how to turn them on",
          blob["on"] is False and blob["cmd"].endswith(" on"))
    import re as _re, subprocess as _sp, shutil as _sh
    node = _sh.which("node")
    if node:
        js = os.path.join(FAKE, "page.js")
        open(js, "w").write("".join(_re.findall(r"<script>(.*?)</script>", page, _re.S)))
        r = _sp.run([node, "--check", js], capture_output=True, text=True)
        check("the page's script parses", r.returncode == 0, r.stderr[:300])
        titles = page.split("function attemptTitle(attempt) {", 1)[1].split("function showReceipt()", 1)[0]
        cases = [
            ({"tool": "Bash", "command": "git commit -m 'wip'"}, "Save code changes locally"),
            ({"tool": "Bash", "command": "git commit -m 'fix the menu'"}, "Save code changes locally"),
            ({"tool": "shell", "command": "git status --short"}, "Check changed files"),
            ({"tool": "exec_command", "command": "npm run build"}, "Run the build script"),
            ({"tool": "Bash", "command": "git commit -m wip; sudo true"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --dry-run"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --help"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --short"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --porcelain"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --long"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit -z"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit -azm wip"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --sho"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --por"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --lon"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit --dry"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit -m wip --sho"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit -m {message,--short}"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit -m *"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git\u00a0commit -m wip"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "npx tsc --noEmit --showConfig"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "npx tsc --noEmit --listFilesOnly"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit -m $(cat message)"}, "Recorded attempt"),
            ({"tool": "Bash", "command": "git commit", "command_clipped": True}, "Recorded attempt"),
            ({"tool": "Write", "command": "git commit"}, "Recorded attempt"),
        ]
        code = "function attemptTitle(attempt) {" + titles + "\nconsole.log(JSON.stringify(" + _json.dumps([c[0] for c in cases]) + ".map(attemptTitle)));"
        r = _sp.run([node, "-e", code], capture_output=True, text=True)
        check("action titles preserve unknown composite, preview and clipped commands",
              r.returncode == 0 and _json.loads(r.stdout) == [c[1] for c in cases], r.stderr[:300])
        identity_functions = page.split("const hostName = ", 1)[1].split("const deep = ", 1)[0]
        identity_probe = r'''
const nodes = {};
const $ = id => nodes[id] ||= {};
const GLYPH = {claude:"claude-mark", codex:"openai-mark", unknown:"neutral-mark"};
'''
        identity_probe += "const hostName = " + identity_functions
        identity_probe += r'''
const session = {agent:"codex", model:"GPT-6.2 Sol", effort:"max"};
showActor(session, {model:"GPT-5.6 Sol", model_id:"gpt-5.6-sol", effort:"high"}, true);
const exact = [nodes["event-agent"].textContent, nodes["event-model"].textContent, nodes["event-glyph"].innerHTML];
showActor(session, null, false);
const missing = nodes["event-model"].textContent;
showActor({agent:"unrecognized"}, {model:"Custom model", effort:""}, false);
console.log(JSON.stringify({exact, missing, unknown:[nodes["event-agent"].textContent,nodes["event-glyph"].innerHTML],
  mixed:modelLabel({identities:[{model:"Opus 5.5",effort:"high"},{model:"Sonnet 5",effort:"low"}]}),
  distinct:modelLabel({identities:[{model:"Model",model_id:"model-v1",effort:"high"},{model:"Model",model_id:"model-v2",effort:"high"}]}),
  single:modelLabel({model:"Opus 5.5",effort:"max"})}));
'''
        r = _sp.run([node, "-e", identity_probe], capture_output=True, text=True)
        identity = _json.loads(r.stdout) if r.returncode == 0 else {}
        check("selected action uses its recorded model and effort, not the session default",
              identity.get("exact") == ["GPT-5.6 Sol · helper", "High effort", "openai-mark"], r.stderr[:300])
        check("missing action identity stays unknown and unknown hosts keep a neutral mark",
              identity.get("missing") == "Effort not recorded"
              and identity.get("unknown") == ["Custom model", "neutral-mark"], identity)
        check("model and effort summaries preserve within-session changes",
              identity.get("mixed") == "Mixed models · Mixed effort" and identity.get("single") == "Opus 5.5 · Max"
              and identity.get("distinct") == "Mixed models · High", identity)
    else:
        print("skip  the page's script parses (no node on this machine)")
    check("the page is yours alone", oct(os.stat(html_path).st_mode & 0o777) in ("0o600",), oct(os.stat(html_path).st_mode & 0o777))

    # Consume the report's exact setup command from a fresh terminal folder.
    # A relative ./kyma would fail here even if the report itself parsed.
    import pty, shlex
    repo = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
    terminal_dir = os.path.join(FAKE, "new-terminal")
    project_dir = os.path.join(FAKE, "client-project")
    os.makedirs(terminal_dir)
    os.makedirs(project_dir)
    test_env = dict(os.environ, KYMA_ALLOW_TEMP_HOME="1", KYMA_TRUST_INSTALL_PATH="1")
    def run_at_terminal(argv, cwd):
        master, slave = pty.openpty()
        try:
            return _sp.run(argv, cwd=cwd, env=test_env, stdin=slave, capture_output=True, text=True, timeout=60)
        finally:
            os.close(master)
            os.close(slave)
    previous_cwd, previous_argv = os.getcwd(), sys.argv
    try:
        os.chdir(repo)
        sys.argv = ["./kyma"]
        source_page = open(light.page(s, os.path.join(FAKE, "source.html"))).read()
        source_data = _json.loads(source_page.split("const D = ", 1)[1].split(";\n", 1)[0])
        command = shlex.split(source_data["cmd"])
        check("source report supplies an absolute executable", command == [os.path.join(repo, "kyma"), "on"], command)
        activated = run_at_terminal(command, terminal_dir)
        check("copied source command activates from an unrelated terminal folder",
              activated.returncode == 0 and "On." in activated.stdout and "The hook answered its self-test." in activated.stdout,
              activated.stdout + activated.stderr)
        os.chdir(terminal_dir)
        global_page = open(light.page(s, os.path.join(FAKE, "global.html"))).read()
        global_data = _json.loads(global_page.split("const D = ", 1)[1].split(";\n", 1)[0])
        check("global setup reports all-project scope", global_data["on"] and global_data["on_scope"] == "global" and not global_data["hooks_off"])
        removed = run_at_terminal(command[:-1] + ["off", "--global"], terminal_dir)
        check("copied source runner can undo from the same unrelated folder", removed.returncode == 0, removed.stdout + removed.stderr)
        installed = run_at_terminal(command + ["--project"], project_dir)
        check("isolated project setup succeeds", installed.returncode == 0, installed.stdout + installed.stderr)
        settings_file = os.path.join(project_dir, ".claude", "settings.local.json")
        settings = _json.load(open(settings_file))
        settings["disableAllHooks"] = True
        with open(settings_file, "w") as fh:
            _json.dump(settings, fh)
        os.chdir(project_dir)
        disabled_page = open(light.page(s, os.path.join(FAKE, "project-disabled.html"))).read()
        disabled_data = _json.loads(disabled_page.split("const D = ", 1)[1].split(";\n", 1)[0])
        check("project-disabled report retains exact scope and disables the active badge",
              disabled_data["on"] and disabled_data["on_scope"] == "project" and disabled_data["on_project"] == "client-project"
              and disabled_data["hooks_off"] and "disableAllHooks" in disabled_data["hooks_off_reason"])
    finally:
        os.chdir(previous_cwd)
        sys.argv = previous_argv

    from kyma import enforce
    prior_rules = open(enforce.GLOBAL_RULES).read()
    accepted_custom = "# Rules\n- Never send email.\n- Ask me before any git push.\n"
    try:
        enforce._write_seen(accepted_custom)
        with open(enforce.GLOBAL_RULES, "w") as fh:
            fh.write("# Rules\n- Ask me before sending email.\n- Be extra thoughtful.\n")
        before_acceptance = open(enforce.SEEN, "rb").read()
        pending_page = open(light.page(s, os.path.join(FAKE, "pending.html"))).read()
        pending_data = _json.loads(pending_page.split("const D = ", 1)[1].split(";\n", 1)[0])
        pending_rules = {r["t"]: r for r in pending_data["setup_rules"]}
        check("setup retains accepted holds and marks pending review without acceptance",
              pending_data["setup_yours"] and pending_data["setup_rule_status"] == "pending"
              and pending_rules["Never send email."]["v"] == "block"
              and pending_rules["Ask me before any git push."]["v"] == "ask"
              and not pending_rules["Be extra thoughtful."]["ok"]
              and open(enforce.SEEN, "rb").read() == before_acceptance)
        os.remove(enforce.GLOBAL_RULES)
        missing_page = open(light.page(s, os.path.join(FAKE, "missing-rules.html"))).read()
        missing_data = _json.loads(missing_page.split("const D = ", 1)[1].split(";\n", 1)[0])
        check("setup preserves accepted custom rules when RULES.md is missing",
              missing_data["setup_yours"] and missing_data["setup_rule_status"] == "missing"
              and [r["t"] for r in missing_data["setup_rules"]] == ["Never send email.", "Ask me before any git push."]
              and not os.path.exists(enforce.GLOBAL_RULES)
              and open(enforce.SEEN, "rb").read() == before_acceptance)
    finally:
        with open(enforce.GLOBAL_RULES, "w") as fh:
            fh.write(prior_rules)
        enforce._write_seen(prior_rules)

    for cols, rows in ((40, 20), (80, 24), (120, 45), (300, 60)):
        os.environ["COLUMNS"], os.environ["LINES"] = str(cols), str(rows)
        buf = io.StringIO()
        try:
            light.draw(s, animate=False, out=buf)
            ok = "today" in buf.getvalue()
        except Exception as e:
            ok = False
        check(f"draws at {cols}x{rows}", ok)

    os.remove(claude)                                              # Claude Code's 30-day cleanup
    d2 = light.gather()
    check("hours stay drawn after the log is deleted", d2["a"].get(cell(T2)) == 2 and d2["y"].get(cell(T1)) == 2, d2["a"])
    from kyma import index
    os.makedirs(index.CACHE_DIR, exist_ok=True)
    with open(os.path.join(index.CACHE_DIR, "VERSION"), "w") as fh:  # an upgrade changes the format
        fh.write("0")
    index._purge_stale()                                           # so `kyma try` rebuilds its own cache
    d2b = light.gather()
    check("kept hours survive an index rebuild", d2b["a"].get(cell(T2)) == 2, d2b["a"])
    arch = os.path.join(FAKE, ".codex", "archived_sessions", os.path.basename(codex))
    os.makedirs(os.path.dirname(arch), exist_ok=True)
    shutil.move(codex, arch)                                       # Codex archives an old session
    d3 = light.gather()
    check("a moved log is counted once", d3["a"].get(cell(T3)) == 2, d3["a"].get(cell(T3)))

    empty = tempfile.mkdtemp(prefix="kyma-light-empty-")
    import subprocess
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from kyma import light; "
                          "sys.exit(light.run(open_it=False))" % os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")],
                         env=dict(os.environ, HOME=empty, KYMA_HOME=os.path.join(empty, ".kyma"), CLAUDE_CONFIG_DIR=os.path.join(empty, ".claude")),
                         capture_output=True, text=True, timeout=60)
    check("no logs: a kind word, no page, no error", out.returncode == 0 and "No AI activity found yet." in out.stdout
          and not os.path.exists(os.path.join(empty, ".kyma", "kyma.html")), out.stdout + out.stderr)

    source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    empty_env = dict(os.environ, HOME=empty, KYMA_HOME=os.path.join(empty, ".kyma"),
                     CLAUDE_CONFIG_DIR=os.path.join(empty, ".claude"),
                     CODEX_HOME=os.path.join(empty, ".codex"), PATH="/usr/bin:/bin")
    out = subprocess.run([sys.executable, "kyma"], cwd=source, env=empty_env,
                         capture_output=True, text=True, timeout=60)
    check("Python source entry gives a runnable first step", out.returncode == 0
          and "Try a safe example now:  ./kyma demo" in out.stdout
          and "run ./kyma again" in out.stdout, out.stdout + out.stderr)
    demo_command = out.stdout.split("Try a safe example now:  ", 1)[-1].splitlines()[0]
    demo_out = subprocess.run(demo_command, shell=True, cwd=source, env=empty_env,
                              capture_output=True, text=True, timeout=60)
    check("the printed source demo command executes without an installed kyma",
          demo_out.returncode == 0 and "outbox/  empty" in demo_out.stdout
          and "outbox/  1 message to cofounder@example.com" in demo_out.stdout,
          demo_out.stdout + demo_out.stderr)
    parent = os.path.dirname(source)
    out = subprocess.run([sys.executable, os.path.join(os.path.basename(source), "kyma")],
                         cwd=parent, env=empty_env, capture_output=True, text=True, timeout=60)
    import shlex
    run_command = out.stdout.split("task, run ", 1)[-1].split(" again.", 1)[0]
    check("a relative source entry keeps its launcher from the parent folder",
          out.returncode == 0 and shlex.split(run_command) == [os.path.join(source, "kyma")],
          out.stdout + out.stderr)
    repeated = subprocess.run(shlex.split(run_command), cwd=parent, env=empty_env,
                              capture_output=True, text=True, timeout=60)
    check("the printed refresh command executes from the original parent folder",
          repeated.returncode == 0 and "No AI activity found yet." in repeated.stdout,
          repeated.stdout + repeated.stderr)

    shutil.rmtree(FAKE, ignore_errors=True)
    shutil.rmtree(empty, ignore_errors=True)
    print(f"light: {'PASS' if not FAIL else str(len(FAIL)) + ' FAILURES'}")
    sys.exit(1 if FAIL else 0)

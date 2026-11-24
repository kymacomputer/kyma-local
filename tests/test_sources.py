"""The log readers, against the logs that broke them.

Every case below is a log someone actually had, or the exact shape a reviewer
used to break the reader: one malformed line crashed every report, Codex
history from 2025 read as nothing at all, a symlink loop counted one session 33
times, and a FIFO named like a log hung the scan forever. Each case builds its
own files in a temporary HOME, so the suite reads nothing of the machine it
runs on and passes the same way on any of them.
"""

import json, os, pickle, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")

# The roots are resolved at import, so HOME must point at the sandbox first:
# this suite must never list or read the real ~/.claude or ~/.codex.
SANDBOX = tempfile.mkdtemp(prefix="kyma-test-sources-")
os.environ["HOME"] = SANDBOX
os.environ["KYMA_HOME"] = os.path.join(SANDBOX, ".kyma")
sys.path.insert(0, SRC)
from kyma import sources  # noqa: E402

CLAUDE = os.path.join(SANDBOX, ".claude", "projects")
CODEX = os.path.join(SANDBOX, ".codex", "sessions")
ARCHIVE = os.path.join(SANDBOX, ".codex", "archived_sessions")
assert sources.CLAUDE_ROOT == CLAUDE and sources.CODEX_ROOT == CODEX, "roots escaped the sandbox"
assert sources.CODEX_ARCHIVE == ARCHIVE, "roots escaped the sandbox"
POSIX = hasattr(os, "mkfifo") and hasattr(os, "symlink")

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  -- {detail}"))
    if not cond:
        FAILS.append(name)


def J(o):
    return json.dumps(o, ensure_ascii=False)


def write(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        fh.write(data)
    return path


def reset():
    for d in (os.path.join(SANDBOX, ".claude"), os.path.join(SANDBOX, ".codex")):
        if not os.path.isdir(d):
            continue
        for here, dirs, files in os.walk(d):          # undo any chmod 000
            for n in dirs + files:
                p = os.path.join(here, n)
                if not os.path.islink(p):
                    try:
                        os.chmod(p, 0o700)
                    except OSError:
                        pass
        shutil.rmtree(d)


def claude_line(cmd="echo ok", ts="2026-11-23T15:00:00.000Z", name="Bash", inp=None, **over):
    rec = {"type": "assistant", "cwd": "/Users/dev/shop", "sessionId": "s1", "timestamp": ts,
           "message": {"role": "assistant", "content": [
               {"type": "tool_use", "id": "toolu_1", "name": name,
                "input": {"command": cmd} if inp is None else inp}]}}
    rec.update(over)
    return J(rec)


def claude_file(lines, slug="-Users-dev-shop", name="s1.jsonl", sub=""):
    return write(os.path.join(CLAUDE, slug, sub, name), "\n".join(lines) + "\n")


def wrapped(typ, payload, ts="2026-11-22T15:00:05.000Z"):
    return J({"timestamp": ts, "type": typ, "payload": payload})


CODEX_HEAD = [
    wrapped("session_meta", {"id": "x", "timestamp": "2026-11-22T15:00:00.000Z", "cwd": "/Users/dev/api"},
            ts="2026-11-22T15:00:00.000Z"),
    wrapped("turn_context", {"cwd": "/Users/dev/api", "model": "gpt-5"}),
]


def exec_js(js, ts="2026-11-22T15:00:05.000Z"):
    return wrapped("response_item", {"type": "custom_tool_call", "name": "exec", "call_id": "c1", "input": js}, ts)


def fn_call(name, arguments, ts="2026-11-22T15:00:05.000Z"):
    return wrapped("response_item", {"type": "function_call", "name": name, "call_id": "c2",
                                     "arguments": arguments if isinstance(arguments, str) else J(arguments)}, ts)


ROLLOUT = "rollout-2026-11-22T10-00-00-0199aaaa-bbbb-cccc-dddd-eeeeffff0001.jsonl"


def codex_file(lines, day="2026/11/22", name=ROLLOUT, root=None):
    return write(os.path.join(root or CODEX, day, name), "\n".join(lines) + "\n")


def read(path):
    reader = sources._read_claude if path.startswith(CLAUDE) else sources._read_codex
    return list(reader(path))


def typed(actions):
    for a in actions:
        for f in ("agent", "tool", "ts", "command", "project", "session", "kind"):
            if type(getattr(a, f)) is not str:
                return f"{f}={getattr(a, f)!r}"
        if type(a.paths) is not list or any(type(p) is not str for p in a.paths):
            return f"paths={a.paths!r}"
        hash((a.tool, a.project, a.ts))     # index.py counts by these
    return ""


# ------------------------------------------------------------ 1. bad content

def test_malformed_claude():
    deep = ('{"type":"assistant","cwd":"/x","message":{"content":[{"type":"tool_use","name":"Bash","input":'
            '{"command":"echo deep","x":' + "[" * 1200 + "]" * 1200 + "}}]}}")
    huge_int = ('{"type":"assistant","cwd":"/x","message":{"content":[{"type":"tool_use","name":"Bash",'
                '"input":{"command":"echo big","n":' + "7" * 200_000 + "}}]}}")
    shapes = {
        "input nested 1,200 deep": deep,
        "a 200,000-digit integer": huge_int,
        "record is a list": J(["tool_use", {"type": "tool_use"}]),
        "record is a string": J("tool_use"),
        "message is a string": J({"type": "assistant", "message": "tool_use"}),
        "content is a dict": J({"type": "assistant", "message": {"content": {"type": "tool_use", "name": "Bash"}}}),
        "blocks are not objects": J({"type": "assistant", "message": {"content": ["tool_use", 5, None]}}),
        "name is an int": claude_line(name=123),
        "name is a list": claude_line(name=["Bash"]),
        "name is a dict": claude_line(name={"n": "Bash"}),
        "timestamp is an int": claude_line(ts=1763910000),
        "timestamp is a list": claude_line(ts=["2026"]),
        "cwd is a list": claude_line(cwd=["/Users/dev"]),
        "cwd is a dict": claude_line(cwd={"p": 1}),
        "command is a list": claude_line(inp={"command": ["sudo", "ls"]}),
        "file_path is a list": claude_line(name="Read", inp={"file_path": ["/x/.env"]}),
        "input is a string": claude_line(inp="sudo ls"),
        "truncated line": claude_line()[:-9],
        "invalid JSON": 'not json at all "tool_use"',
    }
    for label, bad in shapes.items():
        reset()
        path = claude_file([bad, claude_line("sudo rm -rf /opt/old", ts="2026-11-23T15:01:00.000Z")])
        start = time.time()
        try:
            acts = read(path)
            err = typed(acts)
        except Exception as exc:     # the whole point: nothing here may raise
            acts, err = [], f"raised {type(exc).__name__}: {str(exc)[:80]}"
        took = time.time() - start
        valid = [a for a in acts if a.command == "sudo rm -rf /opt/old"]
        check(f"claude: {label}: no exception, valid line still read",
              not err and len(valid) == 1 and valid[0].ts == "2026-11-23T15:01:00.000Z" and took < 5,
              err or f"{len(valid)} valid actions, {took:.1f}s")

    reset()
    a = read(claude_file([claude_line(ts=1763910000, cwd=["/a"], name=7)]))[0]
    check("claude: bad field types become empty strings, cwd falls back to the slug",
          (a.ts, a.project, a.tool, a.kind) == ("", "-Users-dev-shop", "", "other"), repr(a))

    reset()
    acts = read(write(os.path.join(CLAUDE, "-Users-dev-shop", "s1.jsonl"),
                      ("﻿" + claude_line("echo after a BOM") + "\n").encode("utf-8"), "wb"))
    check("claude: a BOM on the first line does not cost that line", [a.command for a in acts] == ["echo after a BOM"],
          repr(acts))

    reset()
    raw = (b'{"type":"user","message":{"role":"user","content":"hi \xff\xfe"}}\n'
           + claude_line("echo PLACEHOLDER && ls").encode().replace(b"PLACEHOLDER", b"caf\xe9 \xc3\x28") + b"\n")
    acts = read(write(os.path.join(CLAUDE, "-Users-dev-shop", "s1.jsonl"), raw, "wb"))
    check("claude: invalid UTF-8 inside a command is replaced, not dropped",
          [a.command for a in acts] == ["echo caf� �( && ls"], repr(acts))


def test_malformed_codex():
    deep = ('{"type":"response_item","payload":{"type":"function_call","name":"shell","arguments":"x","z":'
            + "[" * 1200 + "]" * 1200 + "}}")
    shapes = {
        "nested 1,200 deep": deep,
        "record is a list": J([{"type": "function_call"}, "custom_tool_call"]),
        "payload is a list": J({"type": "response_item", "payload": ["function_call"]}),
        "payload is a string": J({"type": "response_item", "payload": "function_call"}),
        "type is a list": wrapped("response_item", {"type": ["function_call"], "name": "shell"}),
        "arguments is a list": wrapped("response_item", {"type": "function_call", "name": "shell", "arguments": ["ls"]}),
        "arguments is an int": wrapped("response_item", {"type": "function_call", "name": "shell", "arguments": 7}),
        "arguments is bad JSON": fn_call("shell", '{"command": ["bash", "-lc"'),
        "name is a list": wrapped("response_item", {"type": "function_call", "name": ["shell"], "arguments": "{}"}),
        "name is an int": wrapped("response_item", {"type": "function_call", "name": 5, "arguments": "{}"}),
        "turn_context cwd is a list": wrapped("turn_context", {"cwd": ["/a"]}),
        "timestamp is an int": J({"timestamp": 1763910000, "type": "response_item",
                                  "payload": {"type": "function_call", "name": "shell",
                                              "arguments": J({"command": "ls"})}}),
        "argv holds non-strings": fn_call("shell", {"command": ["bash", 5, None, {"x": 1}]}),
        "local_shell_call action is a string": wrapped("response_item", {"type": "local_shell_call", "action": "ls"}),
        "local_shell_call command is a dict": wrapped("response_item", {"type": "local_shell_call",
                                                                        "action": {"command": {"a": 1}}}),
        "an escape past U+10FFFF": exec_js('tools.exec_command({cmd: "echo \\u{FFFFFFFFFF}"})'),
    }
    for label, bad in shapes.items():
        reset()
        path = codex_file(CODEX_HEAD + [bad, exec_js('await tools.exec_command({cmd: "sudo rm -rf /opt/old"})',
                                                     ts="2026-11-22T15:00:09.000Z")])
        try:
            acts = read(path)
            err = typed(acts)
        except Exception as exc:
            acts, err = [], f"raised {type(exc).__name__}: {str(exc)[:80]}"
        valid = [a for a in acts if a.command == "sudo rm -rf /opt/old"]
        check(f"codex: {label}: no exception, valid line still read",
              not err and len(valid) == 1 and valid[0].project == "/Users/dev/api"
              and valid[0].ts == "2026-11-22T15:00:09.000Z",
              err or repr(valid))


def test_oversized_line():
    reset()
    keep = sources._MAX_LINE
    sources._MAX_LINE = 4096
    try:
        acts = read(claude_file([claude_line("x" * 20_000), claude_line("echo after")]))
    finally:
        sources._MAX_LINE = keep
    check("a line over the length limit is dropped whole and the next one read",
          [a.command for a in acts] == ["echo after"], repr([a.command[:20] for a in acts]))


def test_command_cap():
    reset()
    big = "echo " + "A" * 300_000
    acts = read(claude_file([claude_line(big)]))
    acts += read(codex_file(CODEX_HEAD + [exec_js("tools.exec_command({cmd: %s})" % json.dumps(big))]))
    check("a 300 KB command is capped at 256 KiB, in both readers",
          len(acts) == 2 and all(len(a.command) == 262144 and a.command.startswith("echo AAA") for a in acts),
          repr([len(a.command) for a in acts]))
    a = sources.Action(agent="claude", tool=["x"], ts=5, command=None, paths=["/a", 3, "", None],
                       project={"p": 1}, session=1.5, kind=None)
    check("Action normalizes fields it is handed directly",
          (a.tool, a.ts, a.command, a.paths, a.project, a.session, a.kind) == ("", "", "", ["/a"], "", "", "other"),
          repr(a))
    check("Action.label survives a whitespace-only command",
          sources.Action(agent="claude", tool="Bash", command=" \n ").label == "Bash")


# ------------------------------------------------- 2. every Codex generation

def test_codex_shapes():
    reset()
    patch = ("*** Begin Patch\n*** Update File: app/main.py\n@@\n-x = 1\n+x = 2\n*** Add File: app/new.py\n+y\n"
             "*** Delete File: app/old.py\n*** Update File: a.py\n*** Move to: b.py\n*** End Patch")
    lines = CODEX_HEAD + [
        fn_call("shell", {"command": ["bash", "-lc", "git status"], "workdir": "/Users/dev/api"}),
        fn_call("shell", {"command": ["rg", "--files", "-g", "*.py"]}),
        fn_call("shell", {"command": ["/bin/zsh", "-o", "pipefail", "-c", "make | tee log"]}),
        fn_call("shell_command", {"command": "ls -la", "workdir": "/Users/dev/api"}),
        fn_call("exec_command", {"cmd": "npm test", "yield_time_ms": 10000}),
        fn_call("container.exec", {"command": ["bash", "-lc", "pytest -q"]}),
        fn_call("exec_command", json.dumps(J({"cmd": "double encoded"}))),
        wrapped("response_item", {"type": "local_shell_call", "call_id": "c3", "status": "completed",
                                  "action": {"type": "exec", "command": ["bash", "-lc", "cargo build"],
                                             "working_directory": "/Users/dev/api"}}),
        wrapped("response_item", {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c4", "input": patch}),
        fn_call("shell", {"command": ["apply_patch", "*** Begin Patch\n*** Update File: AGENTS.md\n*** End Patch"]}),
        fn_call("update_plan", {"plan": [{"step": "x", "status": "pending"}]}),
    ]
    acts = read(codex_file(lines))
    got = [(a.tool, a.kind, a.command, a.paths) for a in acts]
    want = [
        ("shell", "shell", "git status", []),
        ("shell", "shell", "rg --files -g '*.py'", []),
        ("shell", "shell", "make | tee log", []),
        ("shell_command", "shell", "ls -la", []),
        ("exec_command", "shell", "npm test", []),
        ("container.exec", "shell", "pytest -q", []),
        ("exec_command", "shell", "double encoded", []),
        ("local_shell", "shell", "cargo build", []),
        ("apply_patch", "write", "", ["app/main.py", "app/new.py", "app/old.py", "a.py", "b.py"]),
        ("shell", "write", "", ["AGENTS.md"]),
        ("update_plan", "other", "", []),
    ]
    for g, w in zip(got, want):
        check(f"codex 2025: {w[0]} -> {w[2] or w[3]}", g == w, f"got {g}")
    check("codex 2025: one action per call", len(got) == len(want), f"{len(got)} != {len(want)}")
    check("codex: every action carries the turn_context cwd and its own time",
          all(a.project == "/Users/dev/api" and a.ts == "2026-11-22T15:00:05.000Z" for a in acts),
          repr({(a.project, a.ts) for a in acts}))
    argv_cases = [
        (["bash", "--login", "-c", "echo hi"], "echo hi"),
        (["bash", "script.sh", "-c", "x"], "bash script.sh -c x"),       # -c after a script file is its argument
        (["sh", "-c"], "sh -c"),
        (["powershell.exe", "-NoProfile", "-Command", "Get-ChildItem", "C:\\x"], "Get-ChildItem C:\\x"),
        (["C:\\Windows\\System32\\cmd.exe", "/c", "dir", "/s"], "dir /s"),
        (["git", "commit", "-m", "it's done"], "git commit -m 'it'\"'\"'s done'"),
    ]
    for argv, want in argv_cases:
        got = sources._argv_script(argv)
        check(f"codex argv {argv[:2]} -> {want}", got == want, repr(got))


def test_codex_bare_items():
    """Rust CLI to v0.31 (September 2025): no envelope, no time per line, no cwd."""
    reset()
    lines = [
        J({"id": "0197aaaa-bbbb", "timestamp": "2025-07-01T10:00:00.000Z", "instructions": "be brief"}),
        J({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}),
        J({"type": "function_call", "name": "shell", "call_id": "c1",
           "arguments": J({"command": ["bash", "-lc", "git push origin main"], "workdir": "/Users/dev/old"})}),
        J({"type": "function_call_output", "call_id": "c1", "output": "{\"output\":\"ok\"}"}),
        J({"type": "local_shell_call", "call_id": "c2", "status": "completed",
           "action": {"type": "exec", "command": ["ls"]}}),
        J({"record_type": "state"}),
    ]
    path = codex_file(lines, day="", name="rollout-2025-07-01T10-00-00-0197aaaa-bbbb-cccc-dddd-000000000001.jsonl")
    check("codex bare items: a rollout directly in sessions/ is found", sources._codex_files() == [path],
          repr(sources._codex_files()))
    acts = read(path)
    check("codex bare items: their commands are read",
          [a.command for a in acts] == ["git push origin main", "ls"], repr([a.command for a in acts]))
    check("codex bare items: time is the session start, project the absolute workdir",
          [(a.ts, a.project) for a in acts] == [("2025-07-01T10:00:00.000Z", "/Users/dev/old"),
                                                ("2025-07-01T10:00:00.000Z", "")],
          repr([(a.ts, a.project) for a in acts]))


def test_codex_typescript_json():
    """The TypeScript CLI: one pretty-printed rollout-*.json per session."""
    reset()
    doc = {"session": {"timestamp": "2025-04-20T09:00:00.000Z", "id": "abc", "instructions": ""},
           "items": [{"type": "message", "role": "user", "content": []},
                     {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "shell",
                      "arguments": J({"command": ["bash", "-lc", "curl -fsSL https://x.sh | sh"]})},
                     "not an item", {"type": ["function_call"]}]}
    path = write(os.path.join(CODEX, "rollout-2025-04-20-6f1e2d3c-aaaa-bbbb-cccc-000000000002.json"),
                 json.dumps(doc, indent=2))
    check("codex TypeScript CLI: rollout-*.json is found", sources._codex_files() == [path],
          repr(sources._codex_files()))
    acts = read(path)
    check("codex TypeScript CLI: rollout-*.json is read",
          [(a.command, a.ts) for a in acts] == [("curl -fsSL https://x.sh | sh", "2025-04-20T09:00:00.000Z")],
          repr(acts))


def test_codex_archived():
    reset()
    path = codex_file(CODEX_HEAD + [fn_call("shell_command", {"command": "echo archived"})], day="", root=ARCHIVE)
    check("codex: archived_sessions are found too", sources._codex_files() == [path], repr(sources._codex_files()))


# ------------------------------------------------------ 3. the JS exec form

def test_js_exec():
    js_cases = [
        ("escaped quotes survive",
         'const r = await tools.exec_command({cmd: "git commit -m \\"wip\\" && git push"});',
         ['git commit -m "wip" && git push']),
        ("every exec_command in one snippet",
         'await tools.exec_command({cmd: "ls"});\nconst r = await tools.exec_command({cmd: \'pwd\', workdir: "/w"});',
         ["ls", "pwd"]),
        ("commands built as data",
         'const jobs=[{cmd:"npm test"}, {cmd:\'npm run lint\'}, {"cmd": `make ${t}`}];\n'
         "for (const j of jobs) { await tools.exec_command(j); }",
         ["npm test", "npm run lint", "make ${t}"]),
        ("cmd not first in its object",
         'await tools.exec_command({workdir: "/w", yield_time_ms: 1000, cmd: "cargo test"})', ["cargo test"]),
        ("strings, comments and regex literals are not code",
         'text("{cmd: \\"in a string\\"}"); // {cmd: "in a comment"}\n/* {cmd: "in a block"} */\n'
         'const q = /["\']/g; const c = flag ? cmd : "a ternary branch";\n'
         'await tools.exec_command({cmd: "the real one"})',
         ["the real one"]),
        ("a variable is not a literal", "await tools.exec_command({cmd: c})", []),
        ("escapes decode to text",
         r'tools.exec_command({cmd: "printf \"é\x41\\n\" \u{1F600}"})', ['printf "éA\\n" \U0001F600']),
        ("shell_command inside a snippet", 'await tools.shell_command({command: "make -j8"})', ["make -j8"]),
    ]
    for label, js, want in js_cases:
        reset()
        acts = read(codex_file(CODEX_HEAD + [exec_js(js)]))
        got = [a.command for a in acts if a.command]
        check(f"codex JS: {label}", got == want, f"got {got}")
        if len(want) > 1:
            check(f"codex JS: {label}: one Action each, same ts, session, project",
                  len(acts) == len(want) and len({(a.ts, a.session, a.project, a.tool, a.kind) for a in acts}) == 1,
                  repr(acts))

    reset()
    acts = read(codex_file(CODEX_HEAD + [exec_js('tools.view_image({path: "/x.png"})')]))
    check("codex JS with no command still counts as one exec call",
          [(a.tool, a.command, a.kind) for a in acts] == [("exec", "", "shell")], repr(acts))

    reset()
    js = ('const p = `*** Begin Patch\n*** Update File: AGENTS.md\n@@\n-a\n+b\n*** End Patch`;\n'
          'await tools.apply_patch(p);\nawait tools.exec_command({cmd: "git diff"})')
    acts = read(codex_file(CODEX_HEAD + [exec_js(js)]))
    check("codex JS: apply_patch inside a snippet is a write of its paths",
          [(a.kind, a.command, a.paths) for a in acts] == [("write", "", ["AGENTS.md"]), ("shell", "git diff", [])],
          repr(acts))

    reset()
    patch = "*** Begin Patch\n*** Add File: tools.js\n+await tools.exec_command({cmd: 'rm -rf /'})\n*** End Patch"
    acts = read(codex_file(CODEX_HEAD + [wrapped("response_item", {"type": "custom_tool_call", "name": "apply_patch",
                                                                   "call_id": "c9", "input": patch})]))
    check("codex: a patch that adds exec_command code is a write, not a command",
          [(a.kind, a.command, a.paths) for a in acts] == [("write", "", ["tools.js"])], repr(acts))
    check("_js_unescape is still exported and decodes by character",
          sources._js_unescape("\\u2022 \\xe9") == "• é")


def test_non_ascii():
    reset()
    word = "Résumé — café 中文 \U0001F600"
    codex = codex_file(CODEX_HEAD + [
        exec_js('tools.exec_command({cmd: "echo %s"})' % word),
        exec_js(r'tools.exec_command({cmd: "echo Résumé"})'),
        fn_call("shell", {"command": ["bash", "-lc", "echo " + word]}),
        fn_call("shell_command", "{\"command\": \"echo R\\u00e9sum\\u00e9\"}"),
    ])
    claude = claude_file([claude_line("echo " + word)])
    want = ["echo " + word, "echo Résumé", "echo " + word, "echo Résumé", "echo " + word]
    got = [a.command for a in read(codex)] + [a.command for a in read(claude)]
    check("non-ASCII survives both readers", got == want, repr(got))

    # The old reader opened logs in the locale's encoding, so under a Latin-1
    # locale "Résumé" came out as "RÃ©sumÃ©". Read the same files in a child
    # whose locale is Latin-1 (or plain C, where that locale is not installed).
    probe = ("import json,sys; sys.path.insert(0, %r); from kyma import sources as s;"
             "print(json.dumps([a.command for p in sys.argv[1:] for a in "
             "(s._read_codex(p) if 'rollout-' in p else s._read_claude(p))]))") % SRC
    env = dict(os.environ, LC_ALL="en_US.ISO8859-1", LANG="en_US.ISO8859-1", PYTHONUTF8="0",
               PYTHONIOENCODING="utf-8", PYTHONCOERCECLOCALE="0")
    out = subprocess.run([sys.executable, "-c", probe, codex, claude], env=env, capture_output=True, timeout=60)
    try:
        got = json.loads(out.stdout.decode("utf-8"))
    except ValueError:
        got = out.stderr.decode("utf-8", "replace")[-300:]
    check("non-ASCII survives under a Latin-1 locale", got == want, repr(got))


# ---------------------------------------------------------- 4. finding files

def test_subagents():
    reset()
    main = claude_file([claude_line("echo main")], name="0b1e2a3c.jsonl")
    sub = claude_file([claude_line("echo from a subagent", cwd="/Users/dev/shop/pkg")],
                      sub="0b1e2a3c/subagents", name="agent-a1b2.jsonl")
    deeper = claude_file([claude_line("echo deeper", cwd=None)], sub="0b1e2a3c/subagents/x", name="agent-c3.jsonl")
    toodeep = claude_file([claude_line("echo too deep")], sub="a/b/c/d/e", name="z.jsonl")
    stray = write(os.path.join(CLAUDE, "stray.jsonl"), claude_line("echo stray") + "\n")
    files = sources._claude_files()
    check("claude: subagent transcripts are found", main in files and sub in files and deeper in files, repr(files))
    check("claude: depth is bounded, and a file outside any project is not a session",
          toodeep not in files and stray not in files, repr(files))
    a = read(sub)[0]
    check("claude: a subagent's actions belong to its parent session, at its own cwd",
          (a.command, a.session, a.project) == ("echo from a subagent", "0b1e2a3c", "/Users/dev/shop/pkg"), repr(a))
    a = read(deeper)[0]
    check("claude: with no cwd recorded, the project is the slug, not 'subagents'",
          (a.project, a.session) == ("-Users-dev-shop", "0b1e2a3c"), repr(a))
    check("read_all reads subagent files", sum(1 for _ in sources.read_all(agents=("claude",))) == 3)


def test_symlinks_and_links():
    if not POSIX:
        print("skip links: no symlinks on this platform")
        return
    reset()
    codex = codex_file(CODEX_HEAD + [fn_call("shell_command", {"command": "echo once"})])
    os.symlink("..", os.path.join(CODEX, "2026", "11", "loop"))           # the loop a reviewer found
    os.symlink(os.path.join(CODEX, "2026"), os.path.join(CODEX, "mirror"))
    check("codex: a symlink loop and a mirrored directory count one session once",
          sources._codex_files() == [codex], repr(sources._codex_files()))

    real = claude_file([claude_line("echo once")], slug="-Users-dev-shop")
    os.symlink("..", os.path.join(CLAUDE, "-Users-dev-shop", "loop"))
    os.makedirs(os.path.join(CLAUDE, "-Users-dev-aaa"))                    # sorts before the real one
    os.symlink(real, os.path.join(CLAUDE, "-Users-dev-aaa", "link.jsonl"))
    os.symlink(os.path.join(SANDBOX, "nowhere.jsonl"), os.path.join(CLAUDE, "-Users-dev-aaa", "dangling.jsonl"))
    check("claude: a symlink to a session and a dangling one add nothing; the real path is kept",
          sources._claude_files() == [real], repr(sources._claude_files()))
    hard = os.path.join(CLAUDE, "-Users-dev-zzz", "hard.jsonl")
    os.makedirs(os.path.dirname(hard))
    os.link(real, hard)
    files = sources._claude_files()
    check("claude: a hard link is the same file, counted once", len(files) == 1 and files[0] in (real, hard),
          repr(files))
    check("available() counts each session once", sources.available() == {"claude": 1, "codex": 1},
          repr(sources.available()))
    check("read_all reads each session once", [a.command for a in sources.read_all()] == ["echo once"] * 2)


def test_fifo_zero_and_dirs():
    if not POSIX:
        print("skip FIFOs: none on this platform")
        return
    reset()
    good = claude_file([claude_line("echo ok")])
    fifo = os.path.join(CLAUDE, "-Users-dev-shop", "pipe.jsonl")
    os.mkfifo(fifo)
    day = os.path.join(CODEX, "2026", "11", "22")
    os.makedirs(day)
    os.mkfifo(os.path.join(day, "rollout-2026-11-22T10-00-00-fifo.jsonl"))
    write(os.path.join(CLAUDE, "-Users-dev-shop", "empty.jsonl"), "")
    write(os.path.join(day, "rollout-2026-11-22T11-00-00-empty.jsonl"), "")
    os.makedirs(os.path.join(CLAUDE, "-Users-dev-shop", "notalog.jsonl"))
    os.makedirs(os.path.join(day, "rollout-2026-11-22T12-00-00-dir.jsonl"))
    # In a child, so that a regression hangs one subprocess for 30 seconds
    # instead of the whole suite forever.
    probe = ("import json,sys; sys.path.insert(0, %r); from kyma import sources as s\n"
             "r = []\n"
             "for p in sys.argv[1:]:\n"
             "    try:\n"
             "        list(s._read_claude(p)); r.append('read')\n"
             "    except s.Unreadable:\n"
             "        r.append('unreadable')\n"
             "print(json.dumps([s.available(), s._claude_files(), s._codex_files(), r]))") % SRC
    try:
        out = subprocess.run([sys.executable, "-c", probe, fifo], capture_output=True, timeout=30)
        avail, cfiles, xfiles, direct = json.loads(out.stdout.decode())
        hung = False
    except subprocess.TimeoutExpired:
        avail = cfiles = xfiles = direct = None
        hung = True
    check("a FIFO named like a log does not block discovery", not hung, "timed out after 30 s")
    if not hung:
        check("FIFOs, empty files and directories named *.jsonl are not sessions",
              avail == {"claude": 1, "codex": 0} and cfiles == [good] and xfiles == [],
              repr((avail, cfiles, xfiles)))
        check("reading a FIFO directly raises Unreadable at once", direct == ["unreadable"], repr(direct))


def test_unreadable():
    reset()
    path = claude_file([claude_line("echo secret")])
    xpath = codex_file(CODEX_HEAD + [fn_call("shell_command", {"command": "echo secret"})])
    exc = sources.Unreadable(path, "Permission denied")
    back = pickle.loads(pickle.dumps(exc))     # index.py reads logs in worker processes
    check("Unreadable crosses a process boundary intact",
          type(back) is sources.Unreadable and (back.path, back.reason) == (path, "Permission denied")
          and "Permission denied" in str(back), repr(back))
    if getattr(os, "geteuid", lambda: 1)() == 0:
        print("skip unreadable: root can read a mode-000 file")
        return
    os.chmod(path, 0)
    os.chmod(xpath, 0)
    try:
        for label, p, reader in (("claude", path, sources._read_claude), ("codex", xpath, sources._read_codex)):
            it = reader(p)
            try:
                got = f"yielded {next(it)!r}"
            except sources.Unreadable as e:
                got = e
            except StopIteration:
                got = "yielded nothing, as if the log were empty"
            check(f"{label}: an unreadable log raises Unreadable before yielding anything",
                  isinstance(got, sources.Unreadable) and got.path == p, repr(got))
        check("read_all passes over an unreadable log", list(sources.read_all()) == [])
        check("discovery still lists it, so a caller can tell it apart from an empty one",
              sources._claude_files() == [path] and sources._codex_files() == [xpath])
    finally:
        os.chmod(path, 0o600)
        os.chmod(xpath, 0o600)


def test_compressed():
    reset()
    plain = codex_file(CODEX_HEAD + [fn_call("shell_command", {"command": "echo plain"})],
                       name="rollout-2026-11-22T10-00-00-0199aaaa-bbbb-cccc-dddd-eeeeffff0003.jsonl")
    write(plain + ".zst", b"(\xb5/\xfd stale sibling", "wb")
    lone = os.path.join(CODEX, "2026", "11", "21",
                        "rollout-2026-11-21T10-00-00-0199aaaa-bbbb-cccc-dddd-eeeeffff0004.jsonl.zst")
    text = "\n".join(CODEX_HEAD + [exec_js('tools.exec_command({cmd: "echo Résumé compressed"})')] * 3) + "\n"
    zstd = shutil.which("zstd")
    if zstd:
        os.makedirs(os.path.dirname(lone), exist_ok=True)
        with open(lone, "wb") as fh:
            subprocess.run([zstd, "-q", "-c"], input=text.encode("utf-8"), stdout=fh, check=True)
    else:
        write(lone, b"(\xb5/\xfd placeholder", "wb")

    saved = os.environ.get("PATH", "")
    nozstd = os.path.join(SANDBOX, "empty-bin")                       # a PATH with no zstd on it
    os.makedirs(nozstd, exist_ok=True)
    os.environ["PATH"] = nozstd
    try:
        skipped, files = sources.compressed_skipped(), sources._codex_files()
        try:
            list(sources._read_codex(lone))
            direct = "read"
        except sources.Unreadable as exc:
            direct = exc.reason
    finally:
        os.environ["PATH"] = saved
    check("without zstd: compressed logs are counted, not silently dropped", skipped == 1, f"skipped={skipped}")
    check("without zstd: they are left out, and a plain sibling hides its stale .zst", files == [plain], repr(files))
    check("without zstd: reading one directly raises Unreadable", "zstd" in direct, repr(direct))
    check("available() keeps its two keys", set(sources.available()) == {"claude", "codex"})
    if not zstd:
        print("skip zstd read: no zstd on this machine")
        return
    check("with zstd: nothing is reported skipped", sources.compressed_skipped() == 0)
    check("with zstd: the compressed log is listed, its stale sibling is not",
          sources._codex_files() == sorted([plain, lone]), repr(sources._codex_files()))
    acts = read(lone)
    check("with zstd: a compressed log streams and decodes",
          [a.command for a in acts] == ["echo Résumé compressed"] * 3, repr(acts))
    it = sources._read_codex(lone)
    next(it)
    it.close()                                   # the caller stops early
    try:
        os.waitpid(-1, os.WNOHANG)
        leaked = True
    except ChildProcessError:
        leaked = False
    check("stopping a compressed read early leaves no zstd process behind", not leaked)


def test_since_days():
    reset()
    new = claude_file([claude_line("echo new")], name="new.jsonl")
    old = claude_file([claude_line("echo old")], name="old.jsonl")
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    check("since_days still filters by modification time",
          sources._claude_files(7) == [new] and sources._claude_files() == sorted([new, old]))


# --------------------------------------------- 5. what parsed before, still

def test_unchanged():
    """Shapes the old reader handled, with the Actions it produced. These must
    not move, except where the old value was a bug: Codex project was empty."""
    reset()
    lines = [
        J({"type": "user", "cwd": "/Users/dev/shop", "message": {"role": "user", "content": "fix it"}}),
        claude_line("git status"),
        claude_line(name="Read", inp={"file_path": "/Users/dev/shop/a.py"}),
        claude_line(name="Edit", inp={"file_path": "/Users/dev/shop/b.py", "old_string": "a", "new_string": "b"}),
        claude_line(name="mcp__gh__create_pr", inp={"title": "x"}),
        claude_line(name="Grep", inp={"pattern": "x", "path": "/Users/dev/shop/src"}),
        J({"type": "assistant", "timestamp": "2026-11-23T15:00:00.000Z",
           "message": {"content": [{"type": "text", "text": "two at once"},
                                   {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                                   {"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}}]}}),
    ]
    acts = read(claude_file(lines, name="7f3e.jsonl"))
    got = [(a.agent, a.tool, a.ts, a.command, a.paths, a.project, a.session, a.kind) for a in acts]
    T = "2026-11-23T15:00:00.000Z"
    want = [
        ("claude", "Bash", T, "git status", [], "/Users/dev/shop", "7f3e", "shell"),
        ("claude", "Read", T, "", ["/Users/dev/shop/a.py"], "/Users/dev/shop", "7f3e", "read"),
        ("claude", "Edit", T, "", ["/Users/dev/shop/b.py"], "/Users/dev/shop", "7f3e", "write"),
        ("claude", "mcp__gh__create_pr", T, "", [], "/Users/dev/shop", "7f3e", "mcp"),
        ("claude", "Grep", T, "", ["/Users/dev/shop/src"], "/Users/dev/shop", "7f3e", "other"),
        ("claude", "Bash", T, "ls", [], "-Users-dev-shop", "7f3e", "shell"),
        ("claude", "Bash", T, "pwd", [], "-Users-dev-shop", "7f3e", "shell"),
    ]
    check("claude: shapes that parsed before parse identically", got == want, f"\n  got  {got}\n  want {want}")

    reset()
    acts = read(codex_file(CODEX_HEAD + [exec_js('const r = await tools.exec_command({cmd: "rm -rf build", '
                                                 'workdir: "/Users/dev/api"});\nconsole.log(r.output);')]))
    got = [(a.agent, a.tool, a.ts, a.command, a.paths, a.session, a.kind) for a in acts]
    check("codex: the JS exec form parses as before",
          got == [("codex", "exec", "2026-11-22T15:00:05.000Z", "rm -rf build", [], "eeeeffff0001", "shell")],
          repr(got))
    check("codex: and now carries its project, which the old reader always left empty",
          [a.project for a in acts] == ["/Users/dev/api"], repr([a.project for a in acts]))
    check("the public tool sets are still exported",
          {"Bash", "exec", "shell"} <= sources.SHELL_TOOLS and "apply_patch" in sources.WRITE_TOOLS
          and "Read" in sources.READ_TOOLS)


def main():
    tests = [test_malformed_claude, test_malformed_codex, test_oversized_line, test_command_cap,
             test_codex_shapes, test_codex_bare_items, test_codex_typescript_json, test_codex_archived,
             test_js_exec, test_non_ascii, test_subagents, test_symlinks_and_links, test_fifo_zero_and_dirs,
             test_unreadable, test_compressed, test_since_days, test_unchanged]
    for t in tests:
        try:
            t()
        except Exception as exc:              # a crashing test is a failing test, not a dead suite
            import traceback
            traceback.print_exc()
            check(t.__name__ + " ran to completion", False, f"{type(exc).__name__}: {exc}")
    reset()
    shutil.rmtree(SANDBOX, ignore_errors=True)
    print()
    print("FAILURES:", len(FAILS))
    if not FAILS:
        print("PASS")
    return len(FAILS)


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)

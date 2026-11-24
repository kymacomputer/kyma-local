"""`kyma check` and `kyma mcp`: the same verdict as the hook, for every way in.

Each block below is a defect a reviewer found:
  * a shell tool by any other name (shell, exec_command, container.exec...) was
    read as a file path, so `sudo rm -rf /` came back allow, exit 0
  * argv was joined with spaces: `-- bash -lc 'git push'` lost its quoting
  * usage errors exited 1 or 2, the codes for ask and block
  * a vanished RULES.md answered allow; an allow gave no reason
  * the MCP server had no raw-input form, no structured answer, a version of
    its own, and a slow check kept `ping` waiting
  * `cd a; ` x 39,000 or 20,000 unterminated heredocs took seconds to minutes
Runs in a throwaway HOME. Never runs any command under test.
"""
import contextlib, io, json, os, shutil, sys, tempfile, threading, time

HOME = tempfile.mkdtemp(prefix="kyma-mcp-home-")
os.environ["HOME"] = HOME
for k in ("KYMA_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
    os.environ.pop(k, None)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import kyma  # noqa: E402
from kyma import cli, enforce, mcp, sources  # noqa: E402

bad = 0


def fail(msg):
    global bad
    bad += 1
    print("FAIL ", msg)


def run_cli(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as e:
                code = e.code
    finally:
        sys.stdin = old
    return code, out.getvalue().strip(), err.getvalue()


def rpc(*msgs, timeout=10.0):
    """Feed lines to the server; -> replies in the order the server wrote them."""
    src = io.StringIO("".join(json.dumps(m) + "\n" for m in msgs))
    out = io.StringIO()
    t = threading.Thread(target=mcp.serve, args=(src, out), daemon=True)
    t.start()
    t.join(timeout)
    return [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]


def call(args, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": "kyma_check", "arguments": args}}


def mcp_verdict(args):
    r = rpc(call(args))
    if len(r) != 1:
        return None, r
    res = r[0].get("result") or {}
    return (res.get("structuredContent") or {}).get("verdict"), res


def write_rules(text):
    os.makedirs(os.path.dirname(enforce.GLOBAL_RULES), exist_ok=True)
    with open(enforce.GLOBAL_RULES, "w") as fh:
        fh.write(text)


def main() -> int:
    write_rules(enforce.TEMPLATE + "- Never touch ~/.ssh.\n")
    os.chdir(HOME)

    # A missing or wrong JSON-RPC version cannot become a successful request.
    for msg in ({"id": 101, "method": "ping"}, {"jsonrpc": "1.0", "id": 102, "method": "ping"},
                {"jsonrpc": 2, "id": 103, "method": "ping"}):
        replies = rpc(msg)
        if len(replies) != 1 or replies[0].get("error", {}).get("code") != -32600:
            fail(f"invalid JSON-RPC envelope succeeded: {msg!r}: {replies!r}")

    # ---- 1. every shell tool name is a command, through check and MCP
    if not sources.SHELL_TOOLS <= enforce.shell.SHELL_TOOLS:
        fail(f"shell.SHELL_TOOLS misses {sorted(sources.SHELL_TOOLS - enforce.shell.SHELL_TOOLS)}")
    for name in sorted(sources.SHELL_TOOLS):
        code, out, _ = run_cli(["check", "--tool", name, "--", "sudo rm -rf /"])
        if code != 2 or not out.startswith("block"):
            fail(f"check --tool {name} sudo: exit {code} {out[:60]!r}")
        v, res = mcp_verdict({"tool": name, "command": "sudo rm -rf /"})
        if v != "block":
            fail(f"mcp tool={name} sudo: {v} {str(res)[:80]}")
        v, res = mcp_verdict({"tool": name, "input": {"command": "sudo rm -rf /"}})
        if v != "block":
            fail(f"mcp tool={name} raw input sudo: {v}")
    for tool in ("Glob", "Grep", "LS"):
        v, res = mcp_verdict({"tool": tool, "command": "$HOME/.ss?" if tool == "Glob" else "~/.ssh"})
        if v != "block":
            fail(f"mcp {tool} into ~/.ssh: {v}")
    code, out, _ = run_cli(["check", "--tool", "Glob", "--", "~/.ss?"])
    if code != 2:
        fail(f"check Glob ~/.ss?: exit {code} {out!r}")
    for tool in ("apply_patch", "create_file"):
        code, out, _ = run_cli(["check", "--tool", tool, "--", "~/.ssh/authorized_keys"])
        if code != 2:
            fail(f"check {tool} ~/.ssh/authorized_keys: exit {code} {out!r}")

    # ---- 2. argv keeps its quoting; one argument is taken as written
    for argv, want in ((["bash", "-lc", "git push origin main"], 1),
                       (["echo", "a; sudo ls"], 0),
                       (["echo a; sudo ls"], 2),
                       (["git", "commit", "-m", "remove sudo"], 0)):
        code, out, _ = run_cli(["check", "--"] + argv)
        if code != want:
            fail(f"check -- {argv}: exit {code}, meant {want} ({out[:60]!r})")

    # ---- 3. exit codes: 3 is usage, never a verdict
    for argv in (["check", "--", ""], ["check"], ["check", "--bogus"], ["nosuchcommand"]):
        code, out, err = run_cli(argv)
        if code != 3:
            fail(f"{argv}: exit {code}, meant 3")
    code, out, _ = run_cli(["check", "--json"], stdin="not json")
    if code != 3:
        fail(f"check --json with bad stdin: exit {code}")
    code, out, _ = run_cli(["check", "--json"], stdin=json.dumps(
        {"tool_name": "exec_command", "tool_input": {"command": "sudo ls"}}))
    if code != 2:
        fail(f"check --json exec_command sudo: exit {code} {out!r}")
    real = enforce.verdict_for
    enforce.verdict_for = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    try:
        code, out, _ = run_cli(["check", "--", "ls"])
    finally:
        enforce.verdict_for = real
    if code != 1 or not out.startswith("ask  kyma hit an error"):
        fail(f"internal error: exit {code} {out!r}")
    gone = tempfile.mkdtemp(prefix="kyma-gone-")
    os.chdir(gone)
    os.rmdir(gone)
    code, out, err = run_cli(["check", "--", "sudo ls"])
    os.chdir(HOME)
    if code != 2 or "Traceback" in err:
        fail(f"deleted cwd: exit {code} {err[-120:]!r}")

    # ---- 4. a vanished RULES.md asks, and every answer says why
    code, out, _ = run_cli(["check", "--", "echo hi"])
    if code != 0 or len(out) < len("allow  x") or "rules applies" not in out:
        fail(f"an allow without its reason: {out!r}")
    enforce.hook(io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": HOME})),
                 io.StringIO())                          # kyma has been used here
    os.rename(enforce.GLOBAL_RULES, enforce.GLOBAL_RULES + ".gone")
    code, out, _ = run_cli(["check", "--", "echo hi"])
    if code != 1 or "is gone" not in out:
        fail(f"check with RULES.md removed: exit {code} {out!r}")
    v, res = mcp_verdict({"command": "echo hi"})
    if v != "ask":
        fail(f"mcp with RULES.md removed: {v}")
    os.rename(enforce.GLOBAL_RULES + ".gone", enforce.GLOBAL_RULES)

    # ---- 5. the protocol: one version, structured answers, read-only tools
    with open(os.path.join(HERE, "..", "pyproject.toml")) as fh:
        py = fh.read()
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            call({"command": "git push origin main"}, 3),
            {"jsonrpc": "2.0", "id": 4, "method": "ping"})
    by = {x.get("id"): x for x in r}
    if len(r) != 4:
        fail(f"round trip: {len(r)} of 4 replies")
    info = (by.get(1, {}).get("result") or {}).get("serverInfo") or {}
    if info.get("version") != kyma.__version__ or 'attr = "kyma.__version__"' not in py:
        fail(f"serverInfo version {info.get('version')} is not the package's single version {kyma.__version__}")
    tools = {t["name"]: t for t in (by.get(2, {}).get("result") or {}).get("tools", [])}
    chk = tools.get("kyma_check", {})
    if not all(t.get("annotations", {}).get("readOnlyHint") is True for t in tools.values()) or len(tools) != 2:
        fail("tools are not all annotated readOnlyHint")
    if "input" not in chk.get("inputSchema", {}).get("properties", {}):
        fail("kyma_check has no `input` argument")
    sc = (by.get(3, {}).get("result") or {}).get("structuredContent") or {}
    if sc.get("verdict") != "ask" or "git push" not in (sc.get("rule") or "") or not sc.get("reason"):
        fail(f"structuredContent: {sc}")
    if by.get(4, {}).get("result") != {}:
        fail("ping did not answer")

    # ---- 6. slow input: answered in time, and never in the way of ping
    deep = "cd a; " * 39000                               # 234 KB
    for argv in (["check", "--", deep],):
        t0 = time.time()
        code, out, _ = run_cli(argv)
        if time.time() - t0 > 3 or code != 1:
            fail(f"234 KB of `cd a;`: exit {code} in {time.time() - t0:.1f}s")
    t0 = time.time()
    v, res = mcp_verdict({"command": deep})
    if time.time() - t0 > 3 or v != "ask":
        fail(f"mcp 234 KB of `cd a;`: {v} in {time.time() - t0:.1f}s")
    t0 = time.time()                                      # the reader itself, under any budget
    enforce.shell.units_for("Bash", {"command": "cd a; " * 2500}, HOME)
    if time.time() - t0 > 1:
        fail(f"2,500 `cd a;` took {time.time() - t0:.1f}s to read")
    t0 = time.time()
    enforce.shell.units_for("Bash", {"command": "cat <<A\n" * 20000}, HOME)
    if time.time() - t0 > 3:
        fail(f"20,000 unterminated heredocs took {time.time() - t0:.1f}s")
    slow = "cat <<A\n" * 20000 + "sudo ls"
    r = rpc(call({"command": slow}, 7), {"jsonrpc": "2.0", "id": 8, "method": "ping"}, timeout=10)
    ids = [x.get("id") for x in r]
    if ids[:1] != [8] or 7 not in ids:
        fail(f"ping waited behind a slow check: reply order {ids}")
    else:
        v = ((r[ids.index(7)].get("result") or {}).get("structuredContent") or {}).get("verdict")
        if v not in ("ask", "block"):
            fail(f"slow check answered {v}")

    # ---- 7. under load: one worker, the same verdicts, cancelled requests unanswered
    many = [call({"command": "sudo ls" if i % 2 else "ls"}, 100 + i) for i in range(24)]
    r = rpc(*many, timeout=60)
    got = {x["id"]: ((x.get("result") or {}).get("structuredContent") or {}).get("verdict") for x in r}
    want = {100 + i: ("block" if i % 2 else "allow") for i in range(24)}
    if got != want:
        fail(f"24 checks at once changed verdicts: {sorted(set(got.items()) ^ set(want.items()))[:4]}")
    r = rpc(call({"command": slow}, 9), {"jsonrpc": "2.0", "method": "notifications/cancelled",
                                          "params": {"requestId": 9}}, {"jsonrpc": "2.0", "id": 10, "method": "ping"})
    if [x.get("id") for x in r] != [10]:
        fail(f"a cancelled request was answered: {[x.get('id') for x in r]}")
    # Cancellation is a parsed notification, never text inside normal tool input.
    r = rpc(call({"command": "echo notifications/cancelled"}, 20),
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 21}},
            call({"command": "ls"}, 21),
            [{"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 999}},
             call({"command": "ls"}, 22)],
            {"jsonrpc": "2.0", "id": 23, "method": "notifications/cancelled", "params": {"requestId": 21}},
            call({"tool": "Bash", "input": {}}, 24))
    flat = [item for reply in r for item in (reply if isinstance(reply, list) else [reply])]
    by = {x.get("id"): x for x in flat}
    if set(by) != {20, 21, 22, 23, 24} or by.get(23, {}).get("error", {}).get("code") != -32600 \
            or by.get(24, {}).get("error", {}).get("code") != -32602:
        fail(f"cancel mention/batch/future id and empty input: {r}")
    r = rpc(call({"command": slow}, 25),
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 25}},
            call({"command": "ls"}, 25), timeout=60)
    if len(r) != 1 or r[0].get("id") != 25:
        fail(f"reused cancelled id lost its later reply: {r}")
    # ---- 8. protocol edges: echo the id, string versions only, deep JSON is a parse error, BOM accepted
    r = rpc({"jsonrpc": "2.0", "id": 11, "method": "initialize", "params": {"protocolVersion": ["2025-06-18"]}},
            {"jsonrpc": "2.0", "id": 12, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    by = {x.get("id"): x for x in r}
    if (by.get(11, {}).get("result") or {}).get("protocolVersion") != mcp.PROTOCOL or \
            (by.get(12, {}).get("result") or {}).get("protocolVersion") != "2025-11-25":
        fail(f"protocolVersion handling: {r}")
    src = io.StringIO("[" * 100000 + "\n" + "\ufeff" + json.dumps({"jsonrpc": "2.0", "id": 13, "method": "ping"}) + "\n")
    out = io.StringIO()
    mcp.serve(src, out)
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    if [x.get("error", {}).get("code") for x in lines[:1]] != [-32700] or [x.get("id") for x in lines[1:]] != [13]:
        fail(f"deep JSON / BOM line: {lines}")
    real = mcp.handle
    mcp.handle = lambda m: 1 / 0
    try:
        r = rpc({"jsonrpc": "2.0", "id": 14, "method": "ping"})
    finally:
        mcp.handle = real
    if [x.get("id") for x in r] != [14] or r[0].get("error", {}).get("code") != -32603:
        fail(f"an internal error lost the request id: {r}")

    class Gone(io.StringIO):
        def write(self, s):
            raise BrokenPipeError
    try:
        mcp.serve(io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 15, "method": "ping"}) + "\n"), Gone())
    except BrokenPipeError:
        fail("a closed client crashed the server")
    # the folder the tool's own input names is where it runs
    proj = tempfile.mkdtemp(prefix="kyma-mcp-proj-")
    os.makedirs(os.path.join(proj, ".kyma"))
    os.makedirs(os.path.join(proj, ".git"))
    with open(os.path.join(proj, ".kyma", "RULES.md"), "w") as fh:
        fh.write("- Never run `terraform apply`.\n")
    v, _ = mcp_verdict({"tool": "exec_command", "input": {"cmd": "terraform apply", "workdir": proj}})
    if v != "block":
        fail(f"workdir in the input was not where the call runs: {v}")
    # Codex shapes
    for tool, inp in (("apply_patch", {"input": "*** Begin Patch\n*** Add File: ~/.zshrc\n+sudo id\n*** End Patch"}),
                      ("exec", {"input": "await tools.exec_command({cmd: 'sudo id'})"}),
                      ("shell", {"command": ["apply_patch", "*** Begin Patch\n*** Update File: " + enforce.GLOBAL_RULES +
                                             "\n+- My agent may use sudo.\n*** End Patch"]})):
        v, res = mcp_verdict({"tool": tool, "input": inp})
        if v not in ("ask", "block"):
            fail(f"Codex {tool} {str(inp)[:50]}: {v}")
    # Native tool shapes agree through every public entry point.
    for tool, inp in (("write_stdin", {"session_id": 3, "chars": "sudo ls\n"}),
                      ("edit_file", {"target_file": "~/.claude/settings.json", "code_edit": "{}"}),
                      ("mcp__fs__write_file", {"path": "~/.zshrc", "content": "export CLAUDE_CONFIG_DIR=/tmp/x"}),
                      ("grep_search", {"query": "PASSWORD", "include_pattern": ".env"})):
        v, _ = mcp_verdict({"tool": tool, "input": inp, "cwd": HOME})
        payload = json.dumps({"tool_name": tool, "tool_input": inp, "cwd": HOME})
        code, _, _ = run_cli(["check", "--json"], stdin=payload)
        out = io.StringIO()
        enforce.hook(io.StringIO(payload), out)
        got = json.loads(out.getvalue()).get("hookSpecificOutput", {}).get("permissionDecision", "allow")
        if v not in ("ask", "block") or code != {"ask": 1, "block": 2}.get(v) or got != {"ask": "ask", "block": "deny"}.get(v):
            fail(f"native shape {tool} disagrees: MCP={v}, check={code}, hook={got}")
    # check --json: deep JSON and a tool with no input are usage errors
    code, _, _ = run_cli(["check", "--json"], stdin="[" * 100000)
    if code != 3:
        fail(f"check --json deep: exit {code}")
    code, _, _ = run_cli(["check", "--json"], stdin=json.dumps({"tool_name": "Bash"}))
    if code != 3:
        fail(f"check --json with no tool_input: exit {code}")
    # a KYMA_HOME other accounts can change is not trusted by check or MCP either, as the hook does not
    real = enforce.home_problem
    enforce.home_problem = lambda: "/x can be changed by other accounts on this machine"
    try:
        code, out, _ = run_cli(["check", "--", "echo hi"])
        v, _ = mcp_verdict({"command": "echo hi"})
    finally:
        enforce.home_problem = real
    if code != 1 or v != "ask":
        fail(f"check/MCP trusted a KYMA_HOME others can change: exit {code} {v}")

    print(f"mcp: {'PASS' if not bad else str(bad) + ' FAILURES'}")
    shutil.rmtree(HOME, ignore_errors=True)
    assert not bad
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""`kyma mcp` -- the same verdicts as the hook, over MCP, for harnesses with no hook.

What this is, said plainly: a consult surface, not enforcement. A PreToolUse
hook sits in the host's own path, so the agent cannot route around it. An MCP
tool is called only when the agent chooses to call it. Every description below
says so, because an agent told it is "constrained" by a tool it can skip has
been told something false.

Robustness rules, each from a reviewer who broke the first version:
  * no input line can crash the server: not a batch, not `42`, not bad UTF-8
  * stdout carries JSON-RPC messages and nothing else, ever
  * no rules are invented: the first version created five template rules on
    startup and then quoted them back as "the owner speaking". It now writes
    only what every verdict writes, the same files the hook keeps: the first check records
    the rules it read (rules.seen in KYMA_HOME, the proof copy kept outside it)
    and caches their compiled form (rules.compiled.*.json). No RULES.md, no
    settings file, nothing in the project.
"""

from __future__ import annotations

import json
import os
import sys
import threading

from . import __version__, enforce, rules

PROTOCOL = "2025-11-25"
CANCEL = "notifications/cancelled"
KNOWN = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
VERSION = __version__          # one version for the package and the server

INSTRUCTIONS = (
    "kyma_check tells you what the person's own RULES.md says about an action before you take it. "
    "It does not stop anything by itself: you decide whether to call it. Call it before commands that "
    "touch credentials, the network, messages to people, installs, deletions, sudo, scheduled jobs, or "
    "anything you cannot undo. A block or ask answer quotes a rule the person wrote: follow it, and tell "
    "them which rule it was."
)

TOOLS = [
    {
        "name": "kyma_check",
        "description": (
            "Ask what the person's RULES.md says about one action before you take it. Answers allow, "
            "ask, or block, and quotes the rule and the file and line it came from. Reporting only: it "
            "does not stop the action, you do."
        ),
        "annotations": {"title": "Check an action against RULES.md", "readOnlyHint": True,
                        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string",
                            "description": "The exact shell command, or the file path or URL the tool will use."},
                "tool": {"type": "string",
                         "description": "The tool about to be used: Bash, shell, exec_command, Write, Edit, Read, "
                                        "Glob, Grep, WebFetch. Default Bash."},
                "input": {"type": "object",
                          "description": "The tool's own arguments, exactly as it will receive them. When given, "
                                         "they are judged as they are and `command` is not needed."},
                "cwd": {"type": "string",
                        "description": "The folder the action runs in. Project rules are found from here."},
            },
        },
        "outputSchema": {
            "type": "object",
            "properties": {"verdict": {"type": "string", "enum": ["allow", "ask", "block"]},
                           "reason": {"type": "string"}, "rule": {"type": ["string", "null"]},
                           "source": {"type": "string"}, "approved": {"type": "string"}, "version": {"type": "string"}},
            "required": ["verdict", "reason"],
        },
    },
    {
        "name": "kyma_rules",
        "description": ("Read the person's rules, and exactly how each sentence is checked, so you learn the "
                        "boundaries once instead of one refusal at a time."),
        "annotations": {"title": "Read RULES.md", "readOnlyHint": True, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "properties": {"cwd": {"type": "string"}}},
    },
]


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _ok(mid, result) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _text(body: str, error: bool = False) -> dict:
    out = {"content": [{"type": "text", "text": body}]}
    if error:
        out["isError"] = True
    return out


def _input_for(tool: str, command: str) -> dict:
    return enforce.input_for(tool, command)


_SAY = {"block": "Do not do this; tell the person which rule stopped it.",
        "ask": "Stop and ask the person before doing this.", "allow": ""}


def _here() -> str:
    try:
        return os.getcwd()
    except OSError:          # the folder the server started in was deleted: judge from the top
        return "/"


def answer(tool: str, tool_input, cwd: str | None = None) -> dict:
    """The structured verdict, as the hook would give it. With no cwd, the
    folder the tool's own input names (Codex's cwd and workdir) is where it runs."""
    if not cwd and isinstance(tool_input, dict):
        for k in ("cwd", "workdir", "working_directory"):
            if isinstance(tool_input.get(k), str) and tool_input[k].strip():
                cwd = tool_input[k]
                break
    # Another agent's own tool shapes (Codex write_stdin, Cursor edit_file and
    # grep_search, an MCP filesystem write_file) are read through one table,
    # shell.normalise, inside the same evaluate() the hook uses: the original
    # call and the mapped one are both judged and the stricter answer is kept.
    return enforce.verdict_for(tool or "Bash", tool_input, cwd=cwd or _here())


def check(tool: str, command: str, cwd: str | None = None, tool_input=None) -> str:
    ans = answer(tool, tool_input if tool_input is not None else _input_for(tool or "Bash", command), cwd)
    return _render(ans)


def _render(ans: dict) -> str:
    text = f"{ans['verdict']} — {ans['reason']}"
    return text + (" " + _SAY[ans["verdict"]] if _SAY[ans["verdict"]] else "")


def read_rules(cwd: str | None = None) -> str:
    cwd = cwd or _here()
    try:
        loaded, files, missing = enforce.rules_view(cwd)
    except rules.RulesError as exc:
        return f"kyma cannot read the rules: {exc}"
    lines = []
    if missing:
        lines.append("RULES.md is missing. The accepted rules below still apply. "
                     "Run `kyma rules` in a terminal to restore the accepted copy.")
    for f in files:
        state = "  (missing; accepted copy active)" if missing and f == enforce.GLOBAL_RULES else \
            "" if os.path.exists(f) else "  (not written yet)"
        lines.append(f"{enforce._short(f)}{state}")
    lines.append("")
    if not loaded:
        lines.append("No rules yet.")
    for r in loaded:
        lines.append(f"  {r.text}   [{r.where}]" + (f"   from {r.cited}" if r.cite else ""))
        lines.append(f"      {r.explain()}")
    lines.append("")
    lines.append("These are enforced only where kyma's hook is installed (kyma on). This server reports "
                 "them; it cannot stop anything.")
    return "\n".join(lines)


def handle(msg) -> dict | None:
    """One message in. A reply out, or None for a notification."""
    if not isinstance(msg, dict):
        return _err(None, -32600, "Invalid Request: a message must be a JSON object")
    if msg.get("jsonrpc") != "2.0":
        return _err(_id_of(msg), -32600, 'Invalid Request: jsonrpc must be "2.0"')
    if "method" not in msg:
        return None if ("result" in msg or "error" in msg) else _err(msg.get("id"), -32600,
                                                                      "Invalid Request: no method")
    method = msg.get("method")
    if "id" not in msg:
        return None                                    # a notification: never answered
    mid = msg.get("id")
    if mid is None or isinstance(mid, (bool, dict, list, float)):
        return _err(None, -32600, "Invalid Request: id must be a string or an integer")
    if not isinstance(method, str):
        return _err(mid, -32600, "Invalid Request: method must be a string")
    if method == CANCEL:
        return _err(mid, -32600, "Invalid Request: notifications/cancelled is a notification and carries no id")
    params = msg.get("params")
    if params is not None and not isinstance(params, dict):
        return _err(mid, -32602, "Invalid params: params must be an object")
    params = params or {}

    if method == "initialize":
        want = params.get("protocolVersion")
        return _ok(mid, {
            "protocolVersion": want if isinstance(want, str) and want in KNOWN else PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "kyma", "version": VERSION},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if not isinstance(args, dict):
            return _err(mid, -32602, "Invalid params: arguments must be an object")
        if name == "kyma_check":
            cmd = args.get("command")
            tool = args.get("tool", "Bash")
            cwd = args.get("cwd")
            raw = args.get("input")
            if raw is not None and not isinstance(raw, dict):
                return _err(mid, -32602, "Invalid params: input must be an object")
            if raw == {}:
                # a tool with nothing to judge is a malformed request, as `kyma check --json` says (exit 3)
                return _err(mid, -32602, "Invalid params: input is empty; give the tool's own arguments")
            if raw is None and (not isinstance(cmd, str) or not cmd.strip()):
                return _err(mid, -32602, "Invalid params: command must be a non-empty string, or give input")
            if not isinstance(tool, str) or (cwd is not None and not isinstance(cwd, str)):
                return _err(mid, -32602, "Invalid params: tool and cwd must be strings")
            candidate = raw if raw is not None else _input_for(tool or "Bash", cmd)
            problem = enforce.input_problem(tool or "Bash", candidate)
            if problem:
                return _err(mid, -32602, "Invalid params: " + problem)
            try:
                ans = answer(tool, candidate, cwd)
            except Exception as exc:
                ans = {"verdict": "ask", "rule": None, "reason": f"kyma hit an error ({type(exc).__name__})."}
                out = _text(_render(ans), error=True)
                out["structuredContent"] = ans
                return _ok(mid, out)
            out = _text(_render(ans))
            out["structuredContent"] = {"verdict": ans["verdict"], "reason": ans["reason"], "rule": ans.get("rule"),
                                        **{k: ans[k] for k in ("source", "approved", "version") if ans.get(k)}}
            return _ok(mid, out)
        if name == "kyma_rules":
            cwd = args.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                return _err(mid, -32602, "Invalid params: cwd must be a string")
            try:
                return _ok(mid, _text(read_rules(cwd)))
            except Exception as exc:
                return _ok(mid, _text(f"kyma could not read the rules ({type(exc).__name__}).", error=True))
        return _err(mid, -32602, f"Unknown tool: {name}")
    return _err(mid, -32601, f"Method not found: {method}")


def _parse(line: str):
    """-> (message, None), or (None, a parse-error reply). Parsed once per line."""
    try:
        return json.loads(line), None
    except (ValueError, RecursionError):
        return None, _err(None, -32700, "Parse error")


def _is_cancel(msg) -> bool:
    """Only a real cancel notification: an object, that method, no id. A
    request that merely mentions the word (a Grep for it, a command) is not one."""
    return isinstance(msg, dict) and msg.get("jsonrpc") == "2.0" and msg.get("method") == CANCEL and "id" not in msg


def _id_of(msg):
    mid = msg.get("id") if isinstance(msg, dict) else None
    return mid if isinstance(mid, (str, int)) and not isinstance(mid, bool) else None


def _slow(msg) -> bool:
    """A tools/call does real work; everything else is answered on the spot."""
    if isinstance(msg, list):
        return any(_slow(m) for m in msg)
    return isinstance(msg, dict) and msg.get("method") == "tools/call" and "id" in msg


def _reply_for(line: str):
    msg, bad = _parse(line)
    return bad if bad is not None else _reply(msg)


def _reply(msg):
    if isinstance(msg, list):
        if not msg:
            return _err(None, -32600, "Invalid Request: empty batch")
        out = [r for r in (handle(m) for m in msg) if r is not None]
        return out or None
    return handle(msg)


def serve(stdin=None, stdout=None) -> int:
    """Newline-delimited JSON-RPC on stdio. Reads bytes, so bad UTF-8 is one
    bad message, not a dead server.

    Checks run one at a time, in order, on a single worker thread: two checks
    at once shared one time budget and one module state, and verdicts changed
    with load. `ping` and every other request are answered on the main thread
    meanwhile. A request cancelled while its check is still in flight gets no
    reply; an id is remembered only while its request is in flight, so a later
    request that reuses it is answered."""
    import queue
    src = stdin if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin)
    out = stdout or sys.stdout
    lock = threading.Lock()
    jobs = queue.Queue()
    inflight = {}                 # id -> how many queued requests carry it
    cancelled = {}                # id -> how many of those were cancelled
    gone = threading.Event()

    def write(reply) -> None:
        if reply is None or gone.is_set():
            return
        body = json.dumps(reply, ensure_ascii=False) + "\n"
        with lock:
            try:
                out.write(body)
                out.flush()
            except (BrokenPipeError, OSError, ValueError):
                gone.set()                       # the client left: stop quietly

    def reply_to(msg):
        try:
            return _reply(msg)
        except Exception as exc:                   # the server outlives any one message
            if isinstance(msg, list):
                return [_err(_id_of(m), -32603, f"Internal error: {type(exc).__name__}")
                        for m in msg if isinstance(m, dict) and "id" in m and not _is_cancel(m)] or None
            return _err(_id_of(msg), -32603, f"Internal error: {type(exc).__name__}")

    def cancel(msg) -> None:
        rid = (msg.get("params") or {}).get("requestId") if isinstance(msg.get("params"), dict) else None
        if not isinstance(rid, (str, int)) or isinstance(rid, bool):
            return
        with lock:
            if inflight.get(rid, 0) > cancelled.get(rid, 0):
                cancelled[rid] = cancelled.get(rid, 0) + 1

    def track(ids) -> None:
        with lock:
            for mid in ids:
                inflight[mid] = inflight.get(mid, 0) + 1

    def finish(ids) -> set:
        """Consume cancels and retire requests in one critical section.

        Otherwise a cancel between those steps survives into a reused id.
        """
        dropped = set()
        with lock:
            for mid in ids:
                n = cancelled.get(mid, 0)
                if n:
                    dropped.add(mid)
                    if n == 1:
                        del cancelled[mid]
                    else:
                        cancelled[mid] = n - 1
                inflight[mid] -= 1
                if not inflight[mid]:
                    del inflight[mid]
        return dropped

    def calls(msg) -> list:
        """The ids of the queued requests in a message, the ones a cancel can reach."""
        items = msg if isinstance(msg, list) else [msg]
        return [_id_of(m) for m in items if _slow(m) and _id_of(m) is not None]

    def worker():
        while True:
            msg = jobs.get()
            if msg is None:
                return
            ids = calls(msg)
            reply = reply_to(msg)
            dropped = finish(ids)
            if isinstance(reply, list):
                reply = [r for r in reply if r.get("id") not in dropped] or None
            elif isinstance(reply, dict) and reply.get("id") in dropped:
                reply = None
            write(reply)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        for raw in src:
            if gone.is_set():
                break
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            line = line.lstrip("\ufeff").strip()
            if not line:
                continue
            msg, bad = _parse(line)
            if bad is not None:
                write(bad)
                continue
            if isinstance(msg, list) and msg:
                rest = [m for m in msg if not _is_cancel(m)]
                for m in msg:
                    if _is_cancel(m):
                        cancel(m)                # a cancel in a batch is a cancel; the rest are answered
                if not rest:
                    continue                     # a batch of cancels only: nothing to answer
                msg = rest
            elif _is_cancel(msg):
                cancel(msg)
                continue
            if _slow(msg):
                track(calls(msg))
                jobs.put(msg)
            else:
                write(reply_to(msg))
    except (BrokenPipeError, KeyboardInterrupt):
        gone.set()
    jobs.put(None)                                 # end of input: let pending checks answer
    t.join()
    if gone.is_set() and stdout is None:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
        except OSError:
            pass
    return 0

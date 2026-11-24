"""Your agents as actors: each recent session, who it started, what each did.

The light picture answers *when*. This answers *who* and *what*: a session is
an agent with a model and a task, the subagents it launched hang beneath it,
and anything your rules would have stopped is pinned to the agent that did it.
Everything here is read from the logs Claude Code and Codex already keep:

  ~/.claude/projects/<project>/<session>.jsonl                    the session
  ~/.claude/projects/<project>/<session>/subagents/agent-<id>.*    who it started
      .meta.json  agentType, description, model, parentAgentId, finished
  ~/.codex/sessions/.../rollout-*.jsonl                           a Codex session

Bytes are scanned, not parsed, except the lines that carry a task or an
exact result for a displayed hold. A session log can be hundreds of megabytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile

from . import light, signals, sources

_TS = light._TS
_MODEL = re.compile(rb'"model"\s*:\s*"([A-Za-z0-9._:-]{3,60})"')
_ASSISTANT = re.compile(rb'"type"\s*:\s*"assistant"|"role"\s*:\s*"assistant"')
_CWD = re.compile(rb'"cwd"\s*:\s*"((?:[^"\\]|\\.){1,400})"')
_TOOL = (b'"type":"tool_use"', b'"type": "tool_use"')
SESSIONS = int(os.environ.get("KYMA_AGENT_SESSIONS", "24"))


def model_name(raw: str) -> str:
    """claude-opus-5-5 -> Opus 5.5; gpt-6.2-sol -> GPT-6.2 Sol. Unknown ids pass through."""
    m = re.match(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:[-.](\d{1,2})(?!\d))?", raw or "")
    if m:
        return f"{m.group(1).title()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
    m = re.match(r"gpt-([\d.]+)(?:-(\w+))?", raw or "")
    if m:
        return f"GPT-{m.group(1)}" + (f" {m.group(2).title()}" if m.group(2) else "")
    if (raw or "").lower() in ("opus", "sonnet", "haiku", "fable"):
        return raw.title()
    return raw or ""


# ESC, BEL, C1 and the rest: a log is written by whatever the agent ran, and a
# terminal obeys what it is sent. An agentType of "\x1b]52;c;..." would set
# your clipboard; a cwd ending in "\x1b[3A\x1b[J" would erase lines above it.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def label(text, n: int = 60) -> str:
    """Any name read from a log, made safe to print and to show."""
    text = _CONTROL.sub("", str(text or ""))
    text = " ".join(text.split())
    text = light._tilde(signals.clean(signals.redact(text)))
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _clip(text: str, n: int = 110) -> str:
    return label(text, n)


def _read(path: str, agent: str, call_ids=()) -> dict | None:
    """One log, read once per change: a 500 MB session log took a second on every run."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    wanted = set(call_ids)
    links_tag = hashlib.sha256("\n".join(sorted(wanted)).encode()).hexdigest()[:16]
    stamp = f"a3:{st.st_mtime_ns}:{st.st_size}:{links_tag}"
    cp = os.path.join(light.CACHE, "agent-" + hashlib.sha1(path.encode("utf-8", "replace")).hexdigest() + ".json")
    try:
        with open(cp, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("s") == stamp and isinstance(c.get("v"), dict):
            return c["v"]
    except (OSError, ValueError):
        pass
    out = _read_log(path, agent, wanted)
    if out is not None:
        try:
            os.makedirs(light.CACHE, mode=0o700, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=light.CACHE, prefix=".agent-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"s": stamp, "v": out}, fh)
            os.replace(tmp, cp)
        except OSError:
            pass
    return out


def _read_log(path: str, agent: str, wanted=()) -> dict | None:
    """One log -> {model, cwd, task, start, end, calls, you}. None if unreadable."""
    out = {"model": "", "cwd": "", "task": "", "start": None, "end": None, "calls": 0, "you": False}
    scripted, complete = False, True
    wanted, links = set(wanted), {}
    try:
        lines = sources._zstd_lines(path) if path.endswith(".zst") else sources._log_lines(path)
        for raw in lines:
            if wanted and sources.has_call_id(raw, path, wanted):
                for kind, cid, status, source in sources.result_links(sources._loads(raw), agent, path):
                    if cid not in wanted:
                        continue
                    entry = links.setdefault(cid, [0, 0, "unknown", "unknown", "unknown"])
                    entry[0 if kind == "call" else 1] += 1
                    if kind == "result":
                        entry[2:4] = [status, source]
                    else:
                        entry[4] = source
            if not scripted and light._SCRIPTED.search(raw[:4000]):
                scripted = True
            t = _TS.search(raw)
            if t:
                ts = t.group(1).decode()
                if light._utc(ts):
                    out["start"] = out["start"] or ts
                    out["end"] = ts
            if not out["cwd"]:
                c = _CWD.search(raw[:6000])
                if c:
                    try:
                        out["cwd"] = json.loads(b'"' + c.group(1) + b'"')
                    except ValueError:
                        pass
            if agent == "claude":
                out["calls"] += sum(raw.count(k) for k in _TOOL)
                # Real Claude Code lines open with parentUuid, isSidechain, userType, cwd, sessionId...
                # and only then "type": an assistant line is found by its type, wherever it sits.
                if not out["model"] and _ASSISTANT.search(raw):
                    m = _MODEL.search(raw)
                    if m and not m.group(1).startswith(b"<"):
                        out["model"] = m.group(1).decode()
                if not out["task"] and light._USER.search(raw) and b'"tool_result"' not in raw:
                    rec = sources._loads(raw)
                    if isinstance(rec, dict) and not (rec.get("isMeta") or rec.get("isCompactSummary")):
                        msg = rec.get("message")
                        text = light._human_text(msg.get("content")) if isinstance(msg, dict) else ""
                        if text:
                            out["task"] = text
                            out["you"] = True
            else:
                if (b'"function_call"' in raw or b'"custom_tool_call"' in raw or b'"local_shell_call"' in raw) \
                        and b'_output"' not in raw[:200]:
                    out["calls"] += 1
                if not out["model"] and b'"turn_context"' in raw[:200]:
                    m = _MODEL.search(raw)
                    if m:
                        out["model"] = m.group(1).decode()
                if not out["task"] and b'"user_message"' in raw:
                    rec = sources._loads(raw)
                    p = rec.get("payload") if isinstance(rec, dict) else None
                    if isinstance(p, dict) and p.get("type") == "user_message":
                        text = light._human_text(p.get("message"))
                        if text:
                            out["task"] = text
                            out["you"] = True
    except (sources.Unreadable, OSError):
        return None
    except Exception:
        complete = False
    if scripted:
        out["you"] = False
    out["task"] = _clip(out["task"].splitlines()[0] if out["task"] else "")
    out["results"] = {}
    for cid, (calls, results, status, source, call_source) in links.items():
        if source == "codex_shell_header" and call_source != "codex_shell":
            status, source = "unknown", "unknown"
        if complete and calls == results == 1:
            out["results"][cid] = {"status": status, "source": source}
        else:
            out["results"][cid] = {"status": "unknown", "source": "ambiguous_result" if calls > 1 or results > 1 else "unknown"}
    return out


def _held(path: str, agent: str, rules: str) -> list:
    """Cached holds: [local cell, verdict, rule, quote, optional result metadata]."""
    rows = light.cached_marks(path, rules)          # judged once, in the budget; never again here
    return [[light._local(r[0])] + list(r[1:]) for r in rows if light._local(r[0])]


def _held_ids(rows: list) -> set:
    return {r[4]["call_id"] for r in rows if len(r) > 4 and isinstance(r[4], dict)
            and type(r[4].get("call_id")) is str and re.fullmatch(r"[a-f0-9]{64}", r[4]["call_id"])}


def _linked_held(rows: list, log: dict) -> list:
    """Attach status to an exact source-scoped call. No time/command guessing."""
    results = log.get("results", {})
    out = []
    for row in rows:
        cid = row[4].get("call_id", "") if len(row) > 4 and isinstance(row[4], dict) else ""
        cid = cid if type(cid) is str and re.fullmatch(r"[a-f0-9]{64}", cid) else ""
        meta = {"call_id": cid}
        result = results.get(cid, {})
        result = result if isinstance(result, dict) else {}
        status, source = result.get("status"), result.get("source")
        meta["status"] = status if status in ("tool_succeeded", "tool_failed") else "unknown"
        meta["source"] = source if source in ("claude_tool_result", "codex_exit_code", "codex_is_error",
                                               "codex_shell_header", "conflicting_result", "ambiguous_result") else "unknown"
        out.append(list(row[:4]) + [meta])
    return out


def _children(session_path: str, rules: str) -> list:
    """The subagents a Claude Code session launched, nested as they were launched."""
    folder = os.path.join(os.path.splitext(session_path)[0], "subagents")
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".jsonl"))
    except OSError:
        return []
    nodes = {}
    for name in names:
        aid = name[:-6]
        meta = {}
        try:
            with open(os.path.join(folder, aid + ".meta.json"), encoding="utf-8") as fh:
                meta = json.load(fh) or {}
        except (OSError, ValueError):
            pass
        held = _held(os.path.join(folder, name), "claude", rules)
        log = _read(os.path.join(folder, name), "claude", _held_ids(held))
        if log is None:
            continue
        nodes[aid] = {
            "id": aid,
            "mins": _mins(log["start"], log["end"]),
            "kind": label(meta.get("agentType") or "subagent", 40),
            "task": _clip(str(meta.get("description") or ""), 80),
            "model": label(model_name(str(meta.get("model") or log["model"])), 30),
            "live": meta.get("finished") is False and _live(os.path.join(folder, name)),
            "calls": log["calls"], "start": log["start"], "end": log["end"],
            "done": meta.get("finished", True) is not False,
            "parent": str(meta.get("parentAgentId") or ""),
            "held": _linked_held(held, log),
            "children": [],
        }
    roots = []
    for node in sorted(nodes.values(), key=lambda n: n["start"] or ""):
        up = nodes.get(node.pop("parent"))
        (up["children"] if up else roots).append(node)
    return roots


def _mins(a, b) -> int:
    da, db = light._utc(a or ""), light._utc(b or "")
    return int((db - da).total_seconds() // 60) if da and db else 0


def _live(path: str) -> bool:
    """Written to in the last five minutes: the agent is probably still at it."""
    import time
    try:
        return time.time() - os.path.getmtime(path) < 300
    except OSError:
        return False


def _session(path: str, agent: str, rules: str) -> dict | None:
    held = _held(path, agent, rules)
    log = _read(path, agent, _held_ids(held))
    if not log or not log["calls"]:
        return None
    return {
        "id": os.path.basename(path)[:36],
        "agent": agent,
        "project": label(os.path.basename((log["cwd"] or "").rstrip("/")) or "", 40),
        "model": label(model_name(log["model"]) or ("Claude Code" if agent == "claude" else "Codex"), 30),
        "task": log["task"], "you": log["you"],
        "calls": log["calls"], "start": log["start"], "end": log["end"],
        "mins": _mins(log["start"], log["end"]), "live": _live(path),
        "held": _linked_held(held, log),
        "children": _same_family(_children(path, rules) if agent == "claude" else [],
                                 label(model_name(log["model"]) or "", 30)),
    }


def _same_family(kids: list, parent_model: str) -> list:
    """A subagent's meta says "opus"; its session says "Opus 5". Same model, one name."""
    fam = parent_model.split(" ")[0]
    for k in kids:
        if k.get("model") and " " not in k["model"] and k["model"] == fam:
            k["model"] = parent_model
        _same_family(k.get("children") or [], parent_model)
    return kids


def _top(path: str) -> str:
    """A subagent's log -> the session log that launched it."""
    if "/subagents/" not in path:
        return path
    base = path.split("/subagents/")[0]
    for ext in (".jsonl", ".jsonl.zst"):
        if os.path.exists(base + ext):
            return base + ext
    return ""


def sessions(limit: int = SESSIONS, judged: int | list = 0) -> list:
    """The newest sessions, plus every older one your rules would have met.

    The page counts what your rules would have held across every judged log.
    If the tree showed only the newest sessions, those counts would point at
    agents nobody can find, so a session with a hold always gets its card.
    """
    rules, _ = light.rules_text()
    out, seen = [], set()
    every = light.files()
    for path, agent in every:
        if len(out) >= limit:
            break
        if "/subagents/" in path:
            continue
        node = _session(path, agent, rules)
        if node:
            out.append(node)
            seen.add(path)
    selected = set(judged) if isinstance(judged, list) else None
    for path, agent in (every if judged else []):
        if selected is not None and path not in selected:
            continue
        top = _top(path)
        if not top or top in seen or not _held(path, agent, rules):
            continue
        seen.add(top)
        node = _session(top, agent, rules)
        if node:
            out.append(node)
    return out


def total_sessions() -> int:
    return sum(1 for p, _ in light.files() if "/subagents/" not in p)

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

from . import history, light, signals, sources

_ASSISTANT = re.compile(rb'"type"\s*:\s*"assistant"|"role"\s*:\s*"assistant"')
_CWD = re.compile(rb'"cwd"\s*:\s*"((?:[^"\\]|\\.){1,400})"')
SESSIONS = int(os.environ.get("KYMA_AGENT_SESSIONS", "24"))


def model_name(raw: str) -> str:
    """claude-opus-5-5 -> Opus 5.5; gpt-6.2-sol -> GPT-6.2 Sol. Unknown ids pass through."""
    m = re.match(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:[-.](\d{1,2})(?!\d))?", raw or "")
    if m:
        return f"{m.group(1).title()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
    m = re.fullmatch(r"gpt-([A-Za-z0-9.]+)(?:-([A-Za-z0-9._-]+))?", raw or "")
    if m:
        suffix = " ".join(part.title() for part in m.group(2).split("-")) if m.group(2) else ""
        return f"GPT-{m.group(1)}" + (f" {suffix}" if suffix else "")
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


def _identity(agent: str, model=None, effort=None, model_source="", effort_source="", provider=None) -> dict:
    """Only recorded model IDs and explicit effort levels, never current defaults."""
    model, effort = history.identifier(model), history.effort(effort)
    return {"agent": history.identifier(agent) or "unknown", "model": label(model_name(model), 100), "model_id": model,
            "provider": history.identifier(provider),
            "effort": effort, "model_source": model_source if model else "",
            "effort_source": effort_source if effort else ""}


def _record_identity(rec, agent: str) -> dict | None:
    """Return a new context only at a host-owned model metadata record."""
    if not isinstance(rec, dict):
        return None
    if agent == "claude" and rec.get("type") == "assistant":
        message = rec.get("message")
        if not isinstance(message, dict):
            return _identity(agent)
        effort = rec.get("perTurnEffort")
        source = "claude_per_turn_effort"
        if effort is None:
            effort, source = rec.get("effort"), "claude_effort"
        return _identity(agent, message.get("model"), effort, "claude_message", source)
    if agent == "codex" and rec.get("type") == "turn_context":
        context = rec.get("payload")
        if not isinstance(context, dict):
            return _identity(agent)
        # Both forms are recorded by Codex. A new context with a missing value
        # clears the prior turn rather than assigning its model to new calls.
        effort = context.get("effort", context.get("reasoning_effort"))
        mode = context.get("collaboration_mode")
        settings = mode.get("settings") if isinstance(mode, dict) else None
        if effort is None and isinstance(settings, dict):
            effort = settings.get("reasoning_effort")
        return _identity(agent, context.get("model"), effort, "codex_turn_context", "codex_turn_context")
    return None


def identity_label(actor: dict) -> str:
    """A card describes all recorded configurations, not an arbitrary first model."""
    identities = actor.get("identities")
    identities = identities if isinstance(identities, list) and identities else [actor]
    models = {i.get("model_id") or i.get("model", ""): i.get("model", "")
              for i in identities if isinstance(i, dict)}
    efforts = {i.get("effort", "") for i in identities if isinstance(i, dict)}
    model = "Mixed models" if len(models) > 1 else next(iter(models.values()), "")
    effort = "Mixed effort" if len(efforts) > 1 else next(iter(efforts), "").title()
    return " · ".join(v for v in (model, effort) if v)


def _native_calls(rec, agent: str) -> int:
    if not isinstance(rec, dict):
        return 0
    if agent == "claude":
        message = rec.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        return sum(isinstance(b, dict) and b.get("type") == "tool_use" for b in content) \
            if rec.get("type") == "assistant" and isinstance(content, list) else 0
    item = rec.get("payload", rec)
    return int(isinstance(item, dict) and item.get("type") in sources._CODEX_CALLS)


def _read(path: str, agent: str, call_ids=()) -> dict | None:
    """One log, read once per change: a 500 MB session log took a second on every run."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    wanted = set(call_ids)
    links_tag = hashlib.sha256("\n".join(sorted(wanted)).encode()).hexdigest()[:16]
    stamp = f"a10:{agent}:{st.st_mtime_ns}:{st.st_size}:{links_tag}"
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
    if agent in history.FORMATS:
        return _read_adapter(path, agent, wanted)
    out = {"model": "", "cwd": "", "task": "", "start": None, "end": None, "calls": 0, "you": False,
           "attempts": [], "identities": []}
    scripted, complete = False, True
    wanted, links, actors = set(wanted), {}, {}
    actor = _identity(agent)
    identity_keys = set()
    try:
        lines = sources._zstd_lines(path) if path.endswith(".zst") else sources._log_lines(path)
        for raw in lines:
            rec = None
            if (agent == "claude" and _ASSISTANT.search(raw)) or (agent == "codex" and b'"turn_context"' in raw[:200]):
                rec = sources._loads(raw)
                context = _record_identity(rec, agent)
                if context is not None:
                    actor = context
            has_calls = any(k in raw for k in
                            (b'"tool_use"', b'"function_call"', b'"custom_tool_call"', b'"local_shell_call"'))
            if has_calls and len(out["attempts"]) < 40:
                rec = rec if rec is not None else sources._loads(raw)
            if rec is not None:
                calls = _native_calls(rec, agent) if has_calls else 0
            elif agent == "claude":
                calls = 0
            else:
                # Keep the existing bounded input sampler: later Codex calls
                # need no input JSON parse to retain their current turn context.
                calls = int(has_calls and b'_output"' not in raw[:200])
            if calls and len(out["attempts"]) < 40:
                attempts = _attempts(rec, agent, 40 - len(out["attempts"]), path)
                if actor["model_id"] or actor["effort"]:
                    for attempt in attempts:
                        attempt["actor"] = dict(actor)
                out["attempts"].extend(attempts)
                wanted.update(a[key] for a in attempts for key in ("call_id", "actor_id") if a.get(key))
            if wanted and sources.has_call_id(raw, path, wanted):
                rec = rec if rec is not None else sources._loads(raw)
                for kind, cid, status, source in sources.result_links(rec, agent, path):
                    if cid not in wanted:
                        continue
                    entry = links.setdefault(cid, [0, 0, "unknown", "unknown", "unknown"])
                    entry[0 if kind == "call" else 1] += 1
                    if kind == "result":
                        entry[2:4] = [status, source]
                    else:
                        entry[4] = source
                        actors[cid] = dict(actor)
            if not scripted and light._SCRIPTED.search(raw[:4000]):
                scripted = True
            if b'"timestamp"' in raw:
                rec = rec if rec is not None else sources._loads(raw)
                ts = rec.get("timestamp") if isinstance(rec, dict) else None
                if isinstance(ts, str) and light._utc(ts):
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
                out["calls"] += calls
                if not out["task"] and light._USER.search(raw) and b'"tool_result"' not in raw:
                    rec = sources._loads(raw)
                    if isinstance(rec, dict) and not (rec.get("isMeta") or rec.get("isCompactSummary")):
                        msg = rec.get("message")
                        text = light._human_text(msg.get("content")) if isinstance(msg, dict) else ""
                        if text:
                            out["task"] = text
                            out["you"] = True
            else:
                out["calls"] += calls
                if not out["task"] and b'"user_message"' in raw:
                    rec = sources._loads(raw)
                    p = rec.get("payload") if isinstance(rec, dict) else None
                    if isinstance(p, dict) and p.get("type") == "user_message":
                        text = light._human_text(p.get("message"))
                        if text:
                            out["task"] = text
                            out["you"] = True
            if calls:
                key = (actor["model_id"], actor["effort"])
                if key not in identity_keys:
                    identity_keys.add(key)
                    out["identities"].append(dict(actor))
                out["identity"] = dict(actor)
    except (sources.Unreadable, OSError):
        return None
    except Exception:
        complete = False
    if scripted:
        out["you"] = False
    out.setdefault("identity", dict(actor))
    out["model"] = out["identity"]["model_id"]
    out["task"] = _clip(out["task"].splitlines()[0] if out["task"] else "")
    out["results"] = {}
    out["actors"] = {}
    for cid, (calls, results, status, source, call_source) in links.items():
        if source == "codex_shell_header" and call_source != "codex_shell":
            status, source = "unknown", "unknown"
        if complete and calls == results == 1:
            out["results"][cid] = {"status": status, "source": source}
        else:
            out["results"][cid] = {"status": "unknown", "source": "ambiguous_result" if calls > 1 or results > 1 else "unknown"}
        if complete and calls == 1 and cid in actors:
            out["actors"][cid] = actors[cid]
    _attempt_results(out)
    return out


def _attempt_results(log: dict) -> None:
    for attempt in log.get("attempts", []):
        result = log.get("results", {}).get(attempt.get("call_id", ""), {})
        attempt["status"] = result.get("status", "unknown")
        attempt["source"] = result.get("source", "unknown")


def _read_adapter(path: str, format: str, wanted=()) -> dict | None:
    out = {"model": "", "cwd": "", "task": "", "start": None, "end": None, "calls": 0, "you": False,
           "attempts": [], "identities": [], "results": {}, "actors": {}}
    actor, identities, links, actors = _identity(format), set(), {}, {}
    wanted = set(wanted)
    try:
        for event in sources.history_events(path, format):
            typ = event["type"]
            ts = event.get("timestamp", "")
            if light._utc(ts):
                out["start"] = out["start"] or ts
                out["end"] = ts
            if typ == "session":
                out["cwd"] = event.get("cwd", "")
                out["task"] = event.get("task", "")
                actor = _identity(event.get("host", format))
            elif typ == "user" and not out["task"]:
                text = light._human_text(event.get("text", ""))
                if text:
                    out["task"], out["you"] = text, True
            elif typ == "action":
                source = event.get("source", "")
                actor = _identity(event.get("host", format), event.get("model_id"), event.get("effort"),
                                  source, source, event.get("provider"))
                out["calls"] += 1
                out["cwd"] = out["cwd"] or event.get("cwd", "")
                if len(out["attempts"]) < 40:
                    paths = event.get("paths", [])
                    attempt = dict(light.command_evidence(event.get("command") or (paths[0] if paths else event.get("tool", ""))),
                                   tool=label(event.get("tool"), 80))
                    cid = sources.call_id(event.get("id"), path)
                    attempt.update(call_id=cid, actor_id=cid)
                    if cid:
                        wanted.add(cid)
                    if actor["model_id"] or actor["effort"] or actor["provider"]:
                        attempt["actor"] = dict(actor)
                    out["attempts"].append(attempt)
                key = (actor["agent"], actor["provider"], actor["model_id"], actor["effort"])
                if key not in identities:
                    identities.add(key)
                    out["identities"].append(dict(actor))
            if typ in ("action", "result"):
                for kind, cid, status, source in sources.result_links(event, format, path):
                    if not cid or cid not in wanted:
                        continue
                    entry = links.setdefault(cid, [0, 0, "unknown", "unknown"])
                    entry[0 if kind == "call" else 1] += 1
                    if kind == "call":
                        actors[cid] = dict(actor)
                    else:
                        entry[2:] = [status, source]
    except (sources.Unreadable, OSError):
        return None
    out["identity"] = actor
    out["model"] = actor["model_id"]
    out["task"] = _clip(out["task"].splitlines()[0] if out["task"] else "")
    for cid, (calls, results, status, source) in links.items():
        out["results"][cid] = {"status": status, "source": source} if calls == results == 1 else \
            {"status": "unknown", "source": "ambiguous_result" if calls > 1 or results > 1 else "unknown"}
        if calls == 1 and cid in actors:
            out["actors"][cid] = actors[cid]
    _attempt_results(out)
    return out


def _attempts(rec, agent: str, limit: int = 40, path: str = "") -> list:
    """Only tool inputs, never tool outputs, retained for a bounded activity sample."""
    if not isinstance(rec, dict):
        return []
    calls = []
    if agent == "claude":
        if rec.get("type") != "assistant":
            return []
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        for block in content if isinstance(content, list) else []:
            if len(calls) >= limit:
                break
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inp = block.get("input")
            inp = inp if isinstance(inp, dict) else {}
            tool = block.get("name") if isinstance(block.get("name"), str) else "Tool"
            command = inp.get("command") if isinstance(inp.get("command"), str) else ""
            cid = sources.call_id(block.get("id"), path) if path else ""
            calls.append((tool, command, sources._paths_from_input(inp), cid, cid))
    else:
        item = rec.get("payload", rec)
        if isinstance(item, dict) and item.get("type") in sources._CODEX_CALLS:
            tool, parsed, _ = sources._codex_call(item, item["type"])
            cid = sources.codex_call_id(item, path, tool, parsed) if path else ""
            aid = sources.call_id(item.get("call_id"), path) if path else ""
            calls.extend((tool, command, paths, cid, aid) for _, command, paths in parsed[:limit])
    return [dict(light.command_evidence(command or (paths[0] if paths else tool)), tool=label(tool, 80), call_id=cid, actor_id=aid)
            for tool, command, paths, cid, aid in calls]


def _held(path: str, agent: str, rules: str) -> list:
    """Cached holds: [local cell, verdict, rule, quote, optional result metadata]."""
    rows = light.cached_marks(path, rules)          # judged once, in the budget; never again here
    return [[light._local(r[0]) if r[0] else ""] + list(r[1:]) for r in rows if not r[0] or light._local(r[0])]


def _held_ids(rows: list) -> set:
    return {r[4][key] for r in rows if len(r) > 4 and isinstance(r[4], dict)
            for key in ("call_id", "actor_id")
            if type(r[4].get(key)) is str and re.fullmatch(r"[a-f0-9]{64}", r[4][key])}


def _linked_held(rows: list, log: dict) -> list:
    """Attach status to an exact source-scoped call. No time/command guessing."""
    results = log.get("results", {})
    out = []
    for row in rows:
        cid = row[4].get("call_id", "") if len(row) > 4 and isinstance(row[4], dict) else ""
        cid = cid if type(cid) is str and re.fullmatch(r"[a-f0-9]{64}", cid) else ""
        meta = {"call_id": cid}
        original = row[4] if len(row) > 4 and isinstance(row[4], dict) else {}
        aid = original.get("actor_id")
        aid = aid if type(aid) is str and re.fullmatch(r"[a-f0-9]{64}", aid) else ""
        if aid:
            meta["actor_id"] = aid
        if isinstance(original.get("command"), str):
            meta.update(light.command_evidence(original["command"]))
            meta["command_clipped"] = meta["command_clipped"] or original.get("command_clipped") is True
        result = results.get(cid, {})
        result = result if isinstance(result, dict) else {}
        status, source = result.get("status"), result.get("source")
        meta["status"] = status if status in ("tool_succeeded", "tool_failed") else "unknown"
        meta["source"] = source if source in ("claude_tool_result", "codex_exit_code", "codex_is_error",
                                               "codex_shell_header", "conflicting_result", "ambiguous_result",
                                               "normalized_result", "gemini_tool_status") else "unknown"
        actor = log.get("actors", {}).get(aid or cid)
        if isinstance(actor, dict) and (actor.get("model_id") or actor.get("effort") or actor.get("provider")):
            meta["actor"] = dict(actor)
        out.append(list(row[:4]) + [meta])
    return out


def _children(session_path: str, rules: str, allowed=None) -> list:
    """The subagents a Claude Code session launched, nested as they were launched."""
    folder = os.path.join(os.path.splitext(session_path)[0], "subagents")
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".jsonl"))
    except OSError:
        return []
    nodes = {}
    for name in names:
        if allowed is not None and os.path.join(folder, name) not in allowed:
            continue
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
        identity = dict(log["identity"])
        # Child launch aliases are a fallback, not evidence for a parent's exact
        # version. Actual child responses take precedence over launch metadata.
        if not identity["model_id"] and meta.get("model"):
            fallback = _identity("claude", meta.get("model"), model_source="claude_child_meta")
            identity.update({k: fallback[k] for k in ("model", "model_id", "model_source")})
        nodes[aid] = {
            **identity,
            "id": aid,
            "mins": _mins(log["start"], log["end"]),
            "kind": label(meta.get("agentType") or "subagent", 40),
            "task": _clip(str(meta.get("description") or ""), 80),
            "identities": log["identities"] if any(i["model_id"] or i["effort"] for i in log["identities"]) else [identity],
            "live": meta.get("finished") is False and _live(os.path.join(folder, name)),
            "calls": log["calls"], "start": log["start"], "end": log["end"],
            "done": meta.get("finished", True) is not False,
            "parent": str(meta.get("parentAgentId") or ""),
            "held": _linked_held(held, log),
            "attempts": log.get("attempts", []),
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


def _session(path: str, agent: str, rules: str, allowed=None) -> dict | None:
    held = _held(path, agent, rules)
    log = _read(path, agent, _held_ids(held))
    if not log or not log["calls"]:
        return None
    return {
        **log["identity"],
        "id": os.path.basename(path)[:36],
        "agent": log["identity"].get("agent", agent), "format": agent,
        "project": label(os.path.basename((log["cwd"] or "").rstrip("/")) or "", 40),
        "identities": log["identities"],
        "task": log["task"], "you": log["you"],
        "calls": log["calls"], "start": log["start"], "end": log["end"],
        "mins": _mins(log["start"], log["end"]), "live": _live(path),
        "held": _linked_held(held, log),
        "attempts": log.get("attempts", []),
        "children": _children(path, rules, allowed) if agent == "claude" else [],
    }


def _top(path: str) -> str:
    """A subagent's log -> the session log that launched it."""
    if "/subagents/" not in path:
        return path
    base = path.split("/subagents/")[0]
    for ext in (".jsonl", ".jsonl.zst"):
        if os.path.exists(base + ext):
            return base + ext
    return ""


def sessions(limit: int = SESSIONS, judged: int | list = 0, work=None) -> list:
    """The newest sessions, plus every older one your rules would have met.

    The page counts what your rules would have held across every judged log.
    If the tree showed only the newest sessions, those counts would point at
    agents nobody can find, so a session with a hold always gets its card.
    """
    rules, _ = light.rules_text()
    out, seen = [], set()
    every = light.files() if work is None else list(work)
    allowed = None if work is None else {p for p, _ in every}
    for path, agent in every:
        if len(out) >= limit:
            break
        if "/subagents/" in path and (allowed is None or _top(path) in allowed):
            continue
        node = _session(path, agent, rules, allowed)
        if node:
            out.append(node)
            seen.add(path)
    selected = set(judged) if isinstance(judged, list) else None
    for path, agent in (every if judged else []):
        if selected is not None and path not in selected:
            continue
        top = _top(path)
        if allowed is not None and top not in allowed:
            top = path
        if not top or top in seen or not _held(path, agent, rules):
            continue
        seen.add(top)
        node = _session(top, agent, rules, allowed)
        if node:
            out.append(node)
    return out


def total_sessions(work=None) -> int:
    return sum(1 for p, _ in (light.files() if work is None else work) if "/subagents/" not in p)

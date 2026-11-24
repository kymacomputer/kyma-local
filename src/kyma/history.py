"""Read-only history adapters and the provider-neutral JSONL interchange format.

These records describe tool attempts and recorded tool outcomes. They do not
attest that kyma enforced a rule or that an external side effect occurred.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from . import sources, signals

SCHEMA = "kyma.history.v1"
FORMATS = ("cursor", "gemini", "normalized")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+ -]{0,255}\Z")
_EFFORT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}\Z")
_STATUS = {"tool_succeeded", "tool_failed", "unknown"}


def identifier(value) -> str:
    """Reject unsafe identity metadata before either raw or friendly display."""
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        return ""
    return value if signals.clean(signals.redact(value)) == value else ""


def effort(value) -> str:
    if not isinstance(value, str) or not _EFFORT.fullmatch(value):
        return ""
    return value.lower() if signals.clean(signals.redact(value)) == value else ""


def _text(value, cap=4096) -> str:
    return sources._text(value, cap)


def _content(value) -> str:
    if isinstance(value, str):
        return value
    return " ".join(b["text"] for b in value if isinstance(b, dict) and isinstance(b.get("text"), str)) \
        if isinstance(value, list) else ""


def _call(tool, args, **fields) -> dict:
    args = args if isinstance(args, dict) else {}
    command = args.get("command", args.get("cmd"))
    command = command if isinstance(command, str) else ""
    return dict(type="action", tool=_text(tool, 512), command=command[:sources.COMMAND_CAP],
                paths=sources._paths_from_input(args), kind=sources._kind(_text(tool)), **fields)


def files(since_days=None) -> list:
    """Only known transcript locations. No settings, credentials or databases."""
    from . import HOME
    work = []
    cursor_root = os.path.expanduser(os.environ.get("CURSOR_CONFIG_DIR") or "~/.cursor")
    best = {}
    sources._discover(os.path.join(cursor_root, "projects"), lambda n: n.endswith(".jsonl"), 1, best)
    work.extend((p, "cursor") for p in sources._fresh(list(best.values()), since_days)
                if "agent-transcripts" in p.split(os.sep))
    for root in (os.path.expanduser("~/.gemini/tmp"), os.path.expanduser("~/.cache/.gemini/tmp")):
        best = {}
        sources._discover(root, lambda n: n.startswith("session-") and n.endswith((".json", ".jsonl")), 1, best)
        found = sources._fresh(list(best.values()), since_days)
        # Gemini migrates a legacy JSON file to a JSONL sibling when resumed.
        present = set(found)
        work.extend((p, "gemini") for p in found if os.path.basename(os.path.dirname(p)) == "chats"
                    and not (p.endswith(".json") and p + "l" in present))
    best = {}
    sources._discover(os.path.join(HOME, "imports"), lambda n: n.endswith(".jsonl"), 0, best)
    work.extend((p, "normalized") for p in sources._fresh(list(best.values()), since_days))
    return work


def _normalized_record(rec: dict, context: dict) -> dict | None:
    if rec.get("schema") != SCHEMA:
        return None
    typ = rec.get("type")
    if typ == "session":
        return {"type": typ, "host": identifier(rec.get("host")) or "unknown",
                "session_id": _text(rec.get("session_id"), 512), "cwd": _text(rec.get("cwd")),
                "task": _text(rec.get("task")), "timestamp": _text(rec.get("timestamp"), 64)}
    # A truncated ID can join two unrelated records. Invalid raw IDs have no
    # join key, including when a file reaches the reader without import_file.
    cid = rec.get("id")
    cid = cid if isinstance(cid, str) and sources._CALL_ID.fullmatch(cid) else ""
    if typ == "action":
        kind = rec.get("kind")
        tool = _text(rec.get("tool"), 512)
        return {"type": typ, "id": cid, "host": identifier(rec.get("host")) or context.get("host", "unknown"),
                "session_id": context.get("session_id", ""), "cwd": _text(rec.get("cwd")) or context.get("cwd", ""),
                "timestamp": _text(rec.get("timestamp"), 64), "tool": tool,
                "command": _text(rec.get("command"), sources.COMMAND_CAP), "paths": sources._clean_paths(rec.get("paths")),
                "kind": kind if kind in ("shell", "read", "write", "mcp", "other") else sources._kind(tool),
                "model_id": identifier(rec.get("model_id")), "provider": identifier(rec.get("provider")),
                "effort": effort(rec.get("effort")), "source": "normalized_import"}
    if typ == "result":
        status = rec.get("status")
        return {"type": typ, "id": cid,
                "status": status if isinstance(status, str) and status in _STATUS else "unknown", "source": "normalized_result"}
    return None


def _normalized(path, cursor=None):
    context = dict(cursor.get("context", {})) if cursor else {}
    for raw in sources._log_lines(path, cursor):
        rec = sources._loads(raw)
        if not isinstance(rec, dict):
            continue
        event = _normalized_record(rec, context)
        if event is None:
            continue
        if event["type"] == "session":
            context = event
            if cursor is not None:
                cursor["context"] = context
        if cursor is not None:
            if cursor.get("item", 0):
                continue
            cursor["item"] = 1
        yield event


def _cursor(path, cursor=None):
    # Cursor's exported transcript is intentionally sparse. No file-time or
    # current setting substitutes for absent recorded metadata.
    session = os.path.splitext(os.path.basename(path))[0]
    yield {"type": "session", "host": "cursor", "session_id": session}
    for raw in sources._log_lines(path, cursor):
        rec = sources._loads(raw)
        if not isinstance(rec, dict):
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue
        if rec.get("role") == "user":
            yield {"type": "user", "text": _content(msg["content"]), "timestamp": ""}
        if rec.get("role") != "assistant":
            continue
        skip = cursor.get("item", 0) if cursor is not None else 0
        for i, block in enumerate(msg["content"]):
            if i < skip or not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if cursor is not None:
                cursor["item"] = i + 1
            yield _call(block.get("name"), block.get("input"), host="cursor", session_id=session,
                        id="", timestamp="", model_id="", provider="", effort="", source="cursor_transcript")


def _gemini_document(path) -> dict:
    """Materialize the current native snapshot, including rewinds and patches."""
    with sources._open_log(path) as fh:
        try:
            raw = fh.read(sources._MAX_JSON_FILE + 1)
        except OSError as exc:
            raise sources.Unreadable(path, sources._why(exc)) from exc
    if len(raw) > sources._MAX_JSON_FILE:
        raise sources.Unreadable(path, "Gemini history exceeds the 64 MiB snapshot limit")
    doc = sources._loads(raw)
    if isinstance(doc, dict) and isinstance(doc.get("messages"), list):
        return doc
    metadata, messages = {}, {}
    for line in raw.split(b"\n"):
        rec = sources._loads(line)
        if not isinstance(rec, dict):
            continue
        rewind = rec.get("$rewindTo")
        patch = rec.get("$patch")
        update = rec.get("$set")
        if isinstance(rewind, str):
            keys = list(messages)
            for key in keys[keys.index(rewind):] if rewind in messages else keys:
                messages.pop(key, None)
        elif isinstance(patch, dict):
            updates = ([patch] if isinstance(patch.get("id"), str) else []) + \
                (patch["updates"] if isinstance(patch.get("updates"), list) else [])
            for item in updates:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                old = messages.get(item["id"])
                if old and "content" in item:
                    old["content"] = item["content"]
                # Result patches change output content only, not host status.
                # We never retain that content or infer success from it.
            for key in patch.get("removeIds", []) if isinstance(patch.get("removeIds"), list) else []:
                if isinstance(key, str):
                    messages.pop(key, None)
            for key in patch.get("orderIds", []) if isinstance(patch.get("orderIds"), list) else []:
                if isinstance(key, str) and key in messages:
                    messages[key] = messages.pop(key)
        elif isinstance(rec.get("id"), str):
            messages[rec["id"]] = rec
        elif isinstance(update, dict) or (isinstance(rec.get("sessionId"), str) and isinstance(rec.get("projectHash"), str)):
            values = update if isinstance(update, dict) else rec
            metadata.update({k: v for k, v in values.items() if k != "messages"})
            if isinstance(values.get("messages"), list):
                if update is not None:
                    messages.clear()
                for msg in values["messages"]:
                    if isinstance(msg, dict) and isinstance(msg.get("id"), str):
                        messages[msg["id"]] = msg
    return dict(metadata, messages=list(messages.values()))


def _gemini(path):
    doc = _gemini_document(path)
    if not isinstance(doc.get("sessionId"), str) or not isinstance(doc.get("projectHash"), str):
        return
    session = doc["sessionId"]
    # directories are additional workspace roots, not the original cwd.
    yield {"type": "session", "host": "gemini", "session_id": session}
    for message in doc.get("messages", []):
        if not isinstance(message, dict):
            continue
        ts = _text(message.get("timestamp"), 64)
        if message.get("type") == "user":
            yield {"type": "user", "text": _content(message.get("content")), "timestamp": ts}
        if message.get("type") != "gemini":
            continue
        calls = message.get("toolCalls")
        for call in calls if isinstance(calls, list) else []:
            if not isinstance(call, dict):
                continue
            cid = _text(call.get("id"), 256)
            yield _call(call.get("name"), call.get("args"), id=cid, host="gemini", session_id=session,
                        timestamp=_text(call.get("timestamp"), 64) or ts, model_id=identifier(message.get("model")),
                        provider="", effort="", source="gemini_message")
            status = {"success": "tool_succeeded", "error": "tool_failed"}.get(_text(call.get("status")))
            if status:
                yield {"type": "result", "id": cid, "status": status, "source": "gemini_tool_status"}


def events(path: str, format: str, cursor=None):
    """Canonical adapter events. Raw output and configuration files stay unread."""
    if format == "normalized":
        yield from _normalized(path, cursor)
    elif format == "cursor":
        yield from _cursor(path, cursor)
    elif format == "gemini":
        yield from _gemini(path)
    else:
        raise ValueError("unsupported history format")


def actions(path: str, format: str, cursor=None):
    for event in events(path, format, cursor):
        if event["type"] != "action":
            continue
        cid = sources.call_id(event.get("id"), path)
        yield sources.Action(agent=event.get("host", format), tool=event.get("tool", ""),
                             ts=event.get("timestamp", ""), command=event.get("command", ""),
                             paths=event.get("paths", []), project=event.get("cwd", ""),
                             session=event.get("session_id", ""), kind=event.get("kind", "other"),
                             call_id=cid, actor_id=cid)


def import_file(path: str) -> dict:
    """Validate, minimize, redact and atomically import one normalized session."""
    from . import HOME, ensure_home, state_write, _safe_dirs
    context, records, ids = {}, [], set()
    counts = {"actions": 0, "results": 0}
    with sources._open_log(path) as fh:
        try:
            data = fh.read(sources._MAX_JSON_FILE + 1)
        except OSError as exc:
            raise sources.Unreadable(path, sources._why(exc)) from exc
    if len(data) > sources._MAX_JSON_FILE:
        raise ValueError("history import exceeds 64 MiB")
    for number, raw in enumerate(data.split(b"\n"), 1):
        if number > 100_000:
            raise ValueError("history import exceeds 64 MiB or 100,000 records")
        if not raw.strip():
            continue
        rec = sources._loads(raw)
        if not isinstance(rec, dict):
            raise ValueError(f"invalid JSON object at line {number}")
        event = _normalized_record(rec, context)
        if event is None:
            raise ValueError(f"unsupported schema or record type at line {number}")
        typ = event["type"]
        if typ == "session":
            if records:
                raise ValueError("one session record must appear first")
            context = event
        elif typ in ("action", "result"):
            if not context:
                raise ValueError("a session record must appear first")
            cid = event["id"]
            if not sources._CALL_ID.fullmatch(cid):
                raise ValueError(f"a stable action id is required at line {number}")
            if typ == "action":
                if cid in ids:
                    raise ValueError(f"duplicate action id at line {number}")
                ids.add(cid)
            # Preserve joins without retaining source IDs, which may hold secrets.
            event["id"] = hashlib.sha256(cid.encode()).hexdigest()
            counts["actions" if typ == "action" else "results"] += 1
        event.pop("source", None)
        event = {key: signals.clean(signals.redact(value)) if isinstance(value, str) else
                 [signals.clean(signals.redact(v)) for v in value] if isinstance(value, list) else value
                 for key, value in event.items()}
        records.append(dict(event, schema=SCHEMA))
    if not counts["actions"]:
        raise ValueError("history import contains no actions")
    content = "".join(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n" for rec in records)
    digest = hashlib.sha256(content.encode()).hexdigest()
    ensure_home()
    target = os.path.join(HOME, "imports", digest + ".jsonl")
    _safe_dirs(target)
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    state_write(target, content)
    return dict(counts, path=target, format="normalized")

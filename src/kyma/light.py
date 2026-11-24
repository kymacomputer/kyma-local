"""Every hour your agents have worked on this machine, as light.

`kyma` replays it: one column per day, one row per hour, from the first day
an agent touched this computer to tonight. Cool light is your agents. Warm
light is you, typing to them. Where both are lit, you worked together.

The picture needs only *when*, never *what*: no command, path or message
text is read into it, kept, or drawn. That is also why it is fast. The hot
path is a byte search for timestamps; JSON is parsed only for the rare lines
that might be a person typing.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import stat
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor


def _quiet_worker() -> None:
    """Ctrl-C reaches every process in the group. Only the parent should
    answer it; a worker answering prints a traceback per core."""
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _pool():
    return ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 2), initializer=_quiet_worker)

from . import HOME, ensure_home, sources, state_write

# Not inside .kyma-cache: index rebuilds that folder whenever its format
# changes, and these digests are the only copy of hours whose logs the agent
# has since deleted.
CACHE = os.path.join(HOME, "hours")
_OLD_CACHE = os.path.join(HOME, ".kyma-cache", "light")


def _adopt_old_cache() -> None:
    if os.path.isdir(_OLD_CACHE) and not os.path.isdir(CACHE):
        try:
            ensure_home()
            os.replace(_OLD_CACHE, CACHE)
        except OSError:
            pass
VERSION = 5          # 5: UTC quarter-hour keys; scripted sessions (claude -p, the SDK, codex exec) are not you

_TS = re.compile(rb'"timestamp"\s*:\s*"(\d{4}-\d\d-\d\dT[0-9:.]+(?:Z|[+-]\d\d:?\d\d)?)"')
# A prompt a script sends is not a person at the keyboard: the session says so
# itself, on its first lines.
_SCRIPTED = re.compile(rb'"entrypoint"\s*:\s*"sdk-|"originator"\s*:\s*"codex_exec"|"source"\s*:\s*"exec"')
_RELAYED = b"The user sent a new message while you were working"
_USER = re.compile(rb'"type"\s*:\s*"user"')
_TAGS = re.compile(r"^\s*(?:<([a-z][\w-]*)[^>]*>.*?</\1>\s*)+", re.S)
_MACHINE = ("Caveat:", "[Request interrupted", "This session is being continued", "Base directory for this skill",
            "Stop hook feedback", "<", "[", "# AGENTS.md", "# Context from my IDE")


_ISO = re.compile(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d)(?:[.,]\d+)?)?\s*(Z|[+-]\d\d:?\d\d)?$")
_EARLIEST = _dt.datetime(2020, 1, 1, tzinfo=_dt.timezone.utc)      # no coding agent wrote a log before this


def _utc(ts: str):
    """A log timestamp as an aware UTC datetime, or None. Parsed by hand:
    Python 3.9's fromisoformat rejects fractions that are not 3 or 6 digits
    and offsets without a colon. A clock reading 1970 or next year is a
    broken clock, not a day to draw."""
    m = _ISO.match(ts.strip())
    if not m:
        return None
    try:
        y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
        d = _dt.datetime(y, mo, d, h, mi, tzinfo=_dt.timezone.utc)
        z = m.group(7)
        if z and z != "Z":
            sign = -1 if z[0] == "-" else 1
            z = z[1:].replace(":", "")
            d -= sign * _dt.timedelta(hours=int(z[:2]), minutes=int(z[2:]))
    except (ValueError, OverflowError):
        return None
    if not (_EARLIEST <= d <= _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1)):
        return None
    return d


def _ukey(ts: str):
    """What the cache keeps: the UTC quarter hour. Every time zone on Earth is
    a whole number of quarter hours from UTC, so this converts exactly to the
    local hour of whatever zone the laptop is in when the picture is drawn."""
    d = _utc(ts)
    return d.strftime("%Y-%m-%dT%H:") + "%02d" % (d.minute - d.minute % 15) if d else None


def _local(k: str):
    """A cached UTC quarter key -> the local 'YYYY-MM-DD HH' cell it falls in now."""
    try:
        d = _dt.datetime(int(k[:4]), int(k[5:7]), int(k[8:10]), int(k[11:13]), int(k[14:16]), tzinfo=_dt.timezone.utc)
        return d.astimezone().strftime("%Y-%m-%d %H")
    except (ValueError, OverflowError, OSError, IndexError):
        return None


def _key(ts: str):
    k = _ukey(ts)
    return _local(k) if k else None


def _localize(counts: dict) -> Counter:
    out = Counter()
    for k, n in counts.items():
        c = _local(k)
        if c:
            out[c] += n
    return out


def _human_text(content) -> str:
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return ""
    t = _TAGS.sub("", content).strip()      # the app's own wrappers come first; the person comes after
    return "" if not t or t.startswith(_MACHINE) else t


def _scan(path: str, agent: str, prior: dict | None = None) -> dict:
    agents, you = Counter(), Counter()
    undated = 0
    scripted = False
    last = ""                        # older Codex logs stamp the session once, not every item
    digest, prefix, size = hashlib.sha256(), hashlib.sha256(), 0
    prior = prior or {}
    prior_size = prior.get("bytes", 0)
    prior_size = prior_size if type(prior_size) is int and prior_size >= 0 else 0
    try:
        lines = sources._zstd_lines(path) if path.endswith(".zst") else sources._log_lines(path)
    except Exception:
        return None                    # could not read is not the same as empty: never cache it
    try:
        for raw in lines:
            first_line = size == 0
            digest.update(raw)
            if size < prior_size:
                prefix.update(raw[:prior_size - size])
            size += len(raw)
            if not scripted and _SCRIPTED.search(raw[:4000]):
                scripted = True
            if agent == "claude":
                rec = sources._loads(raw) if b'"tool_use"' in raw else None
                message = rec.get("message") if isinstance(rec, dict) and rec.get("type") == "assistant" else None
                content = message.get("content") if isinstance(message, dict) else None
                n = sum(isinstance(b, dict) and b.get("type") == "tool_use" for b in content) if isinstance(content, list) else 0
                person = _USER.search(raw) is not None and b'"tool_result"' not in raw
                relayed = _RELAYED in raw
                if not (n or person or relayed):
                    continue
                rec = rec if isinstance(rec, dict) else sources._loads(raw)
                ts = rec.get("timestamp") if isinstance(rec, dict) else ""
                ts = ts if isinstance(ts, str) else ""
                k = _ukey(ts)
                if not k:
                    undated += n
                    continue
                if n:
                    agents[k] += n
                if relayed:
                    you[k] += 1
                elif person:
                    rec = sources._loads(raw)
                    if isinstance(rec, dict) and not (rec.get("isSidechain") or rec.get("isMeta")
                                                      or rec.get("isCompactSummary")):
                        msg = rec.get("message")
                        if isinstance(msg, dict) and _human_text(msg.get("content")):
                            you[k] += 1
            elif agent == "codex":
                if first_line:
                    _, last = sources._codex_meta(raw)
                call = (b'"function_call"' in raw or b'"custom_tool_call"' in raw or b'"local_shell_call"' in raw)
                rec = None
                if call:
                    rec = sources._loads(raw)
                    item = rec.get("payload", rec) if isinstance(rec, dict) else None
                    call = isinstance(item, dict) and item.get("type") in sources._CODEX_CALLS
                person = b'"user_message"' in raw or (b'"role":"user"' in raw and b'"compacted"' not in raw[:120])
                if not (call or person):
                    continue
                rec = rec if isinstance(rec, dict) else sources._loads(raw)
                ts = rec.get("timestamp") if isinstance(rec, dict) and "payload" in rec else last
                k = _ukey(ts) if isinstance(ts, str) else None
                if not k:
                    undated += int(call)
                    continue
                if call and b'_output"' not in raw[:200]:
                    agents[k] += 1
                elif person:
                    rec = sources._loads(raw)
                    p = rec.get("payload") if isinstance(rec, dict) else None
                    if not isinstance(p, dict):
                        continue
                    if p.get("type") == "user_message":
                        text = p.get("message")
                    elif p.get("type") == "message" and p.get("role") == "user":
                        text = [{"type": "text", "text": b.get("text", "")} for b in p.get("content") or []
                                if isinstance(b, dict) and b.get("type") in ("input_text", "text")]
                    else:
                        continue
                    if _human_text(text):
                        you[k] += 1
        if agent not in ("claude", "codex"):
            for event in sources.history_events(path, agent):
                kind = event.get("type")
                ts = event.get("timestamp")
                k = _ukey(ts) if isinstance(ts, str) else None
                if kind == "action":
                    if k:
                        agents[k] += 1
                    else:
                        undated += 1
                elif kind == "user" and k:
                    you[k] += 1
    except (sources.Unreadable, OSError):
        return None                    # permission, a missing zstd, a vanished file: try again next run
    except Exception:
        pass
    finally:
        try:
            lines.close()
        except Exception:
            pass
    return {"a": dict(agents), "y": {} if scripted else dict(you), "undated": undated,
            "native_counts": True, "h": digest.hexdigest(), "bytes": size,
            "_continues": bool(prior.get("h")) and size >= prior_size and prefix.hexdigest() == prior["h"]}


_SESSION_ID = r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}"


def _history_identity(d: dict, intrinsic: bool = False) -> str:
    """One transcript across aliases, native moves and compression.

    Codex preserves its rollout basename when it archives or compresses a log.
    Claude's UUID identifies a session; subagent names belong to that session.
    Keep each native store separate. Unknown names use their canonical path,
    so unrelated projects with a file named session.jsonl do not collapse.
    Persist this digest while an alias still resolves, before its deletion.
    """
    key = d.get("i" if intrinsic else "k")
    if isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key):
        return key
    path = d.get("r") or os.path.abspath(str(d.get("p", "")))
    name = os.path.basename(path)
    key = "path:" + path + (":" + d["h"] if d.get("h") else "")
    plain = name[:-4] if name.endswith(".zst") else name
    if sources._is_rollout(plain):
        for marker in (os.sep + "sessions" + os.sep, os.sep + "archived_sessions" + os.sep):
            if marker in path:
                key = "codex:" + os.path.realpath(path.rsplit(marker, 1)[0]) + ":" + plain
                break
    elif os.sep + "projects" + os.sep in path:
        store, relative = path.rsplit(os.sep + "projects" + os.sep, 1)
        store = os.path.realpath(store)
        if re.fullmatch(_SESSION_ID + r"\.jsonl", name):
            key = "claude:" + store + ":" + name
        else:
            parts = relative.split(os.sep)
            if len(parts) >= 4 and parts[-2] == "subagents" and re.fullmatch(_SESSION_ID, parts[-3]):
                key = "claude-child:" + store + ":" + parts[-3] + ":" + name
    return hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()


def _hour_stamp(st) -> str:
    return f"{VERSION}:{int(st.st_mtime)}:{st.st_size}"


def _hour_file(st) -> list:
    return [st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size]


def _hour_current(d: dict, st) -> bool:
    # Older hour snapshots have only second-resolution mtime and size.
    # New snapshots also require exact file identity and nanosecond mtime.
    return d.get("s") == _hour_stamp(st) and ("f" not in d or d["f"] == _hour_file(st))


def _digest(item) -> dict:
    path, agent = item
    try:
        st = os.stat(path)
    except OSError:
        return {"a": {}, "y": {}}
    stamp = _hour_stamp(st)
    cp = os.path.join(CACHE, hashlib.sha1(path.encode("utf-8", "replace")).hexdigest() + ".json")
    c = {}
    try:
        with open(cp) as fh:
            c = json.load(fh)
        if _hour_current(c, st) and c.get("h") and c.get("f") and c.get("i") and c.get("native_counts"):
            if not c.get("k"):
                c["k"] = _history_identity(c)
                state_write(cp, json.dumps(c, separators=(",", ":")))
            return c
    except (OSError, ValueError):
        pass
    d = _scan(path, agent, c)
    if d is None:
        return {"a": {}, "y": {}}
    d["s"] = stamp
    d["p"] = path
    d["b"] = os.path.basename(path)
    d["r"] = os.path.realpath(path)
    d["f"] = _hour_file(st)
    continued = d.pop("_continues", False)
    same_file = c.get("f", [])[:2] == d["f"][:2]
    # A prior alias owner survives append only when the observed old bytes are
    # still the prefix of this same file. Unchanged legacy stamps retain their
    # existing identity at the old mtime/size precision, without content proof.
    prior_current = bool(c) and _hour_current(c, st)
    if prior_current or (same_file and continued):
        d["i"] = _history_identity(c, intrinsic=True)
        d["k"] = _history_identity(c)
    else:
        d["i"] = _history_identity(d, intrinsic=True)
        d["k"] = d["i"]
    try:
        if c.get("p") and _history_identity(c) != d["k"]:
            # Preserve a replaced generic transcript separately. Its pathname
            # now belongs to the new file, but its old hours still belong here.
            old = dict(c, k=_history_identity(c), i=_history_identity(c, intrinsic=True))
            old_cp = os.path.join(CACHE, "past-" + os.path.basename(cp)[:-5] + "-" + old["k"] + ".json")
            state_write(old_cp, json.dumps(old, separators=(",", ":")))
        state_write(cp, json.dumps(d, separators=(",", ":")))
    except OSError:
        pass
    return d


def files() -> list:
    out = sources.history_files()
    def m(item):
        try:
            return os.path.getmtime(item[0])
        except OSError:
            return 0.0
    out.sort(key=m, reverse=True)
    return out


def gather(progress=None, work=None) -> dict:
    """{'a': {cell: n}, 'y': {cell: n}} over every log, newest first, cached."""
    ensure_home()
    _adopt_old_cache()
    os.makedirs(CACHE, exist_ok=True)
    scoped = work is not None
    work = list(work) if scoped else files()
    a, y = Counter(), Counter()
    snapshots, rows = {}, []

    def merge(d, key, live=False):
        # Snapshots of one append-only transcript overlap. Maxima retain its
        # older hours and later appends without counting either snapshot twice.
        # Different transcript identities still add, even in the same hour.
        group = snapshots.setdefault(key, {"a": {}, "y": {}, "undated": 0, "live": False,
                                           "native_cells": set(), "legacy": False})
        group["live"] |= live
        group["undated"] = max(group["undated"], d.get("undated", 0))
        for field, total in (("a", a), ("y", y)):
            for cell, n in d.get(field, {}).items():
                if field == "a":
                    if d.get("native_counts"):
                        group["native_cells"].add(cell)
                    elif cell in group["native_cells"]:
                        continue
                prior = group[field].get(cell, 0)
                if n > prior:
                    total[cell] += n - prior
                    group[field][cell] = n
                    if field == "a" and not d.get("native_counts"):
                        group["legacy"] = True

    done = 0
    with _pool() as pool:
        for d in (pool.map(_digest, work, chunksize=4) if work else ()):
            if d.get("p"):
                rows.append((d, True, None))
                a.update(d.get("a", {}))
                y.update(d.get("y", {}))
            done += 1
            if progress and (done % 25 == 0 or done == len(work)):
                progress(done, len(work), a, y)
    # Claude Code deletes transcripts after 30 days by default. The hours a
    # log once held stay in the picture after the log is gone: kyma keeps the
    # *when*, which is all the picture ever needed.
    live = {hashlib.sha1(f.encode("utf-8", "replace")).hexdigest() + ".json" for f, _ in work}
    try:
        names = [] if scoped else os.listdir(CACHE)
    except OSError:
        names = []
    for name in names:
        # held-* and agent-* are caches of other things; only hour digests are kept hours.
        # Theirs hold masked command excerpts, so they go when their log goes.
        if name.startswith(("held-", "agent-")):
            if work and name.split("-", 1)[1] not in live:
                try:
                    os.remove(os.path.join(CACHE, name))
                except OSError:
                    pass
            continue
        if not name.endswith(".json") or name in live:
            continue
        try:
            with open(os.path.join(CACHE, name)) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if str(d.get("s", "")).startswith(f"{VERSION}:") and d.get("p"):
            rows.append((d, False, os.path.join(CACHE, name)))
    # A current snapshot can prove that different names are the same file.
    # A retained path may now refer to unrelated content, so its exact prior
    # file stamp must match before its inode can establish a new alias relation.
    # Legacy snapshots without that evidence remain separate unless their
    # native transcript identities already establish the relation.
    # Persist the source key. An inode is only freshness evidence, never a
    # durable transcript identity: the filesystem can reuse it after deletion.
    owners, parents = {}, {}

    def owner(key):
        parents.setdefault(key, key)
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for d, _, _ in rows:
        # Native identity survives an alias-owner change: an archive under the
        # original rollout name can still join the previously established set.
        original = owner(_history_identity(d, intrinsic=True))
        parents[original] = owner(_history_identity(d))
    for d, _, _ in rows:
        key = owner(_history_identity(d))
        try:
            st = os.stat(d["p"])
            if d.get("f") and _hour_current(d, st) and st.st_ino and stat.S_ISREG(st.st_mode):
                inode = (st.st_dev, st.st_ino)
                parents[key] = owner(owners.setdefault(inode, key))
        except OSError:
            pass
    a.clear()
    y.clear()
    # An exact native count supersedes an older byte-match count for the same
    # transcript and cell. Keep legacy-only hours when their source is gone.
    for d, is_live, stored_path in sorted(rows, key=lambda row: not row[0].get("native_counts")):
        key = owner(_history_identity(d))
        merge(d, key, is_live)
        if d.get("k") != key or not d.get("i"):
            d["i"] = _history_identity(d, intrinsic=True)
            d["k"] = key
            cp = stored_path or os.path.join(CACHE, hashlib.sha1(d["p"].encode("utf-8", "replace")).hexdigest() + ".json")
            try:
                state_write(cp, json.dumps(d, separators=(",", ":")))
            except OSError:
                pass
    kept = sum(not d["live"] for d in snapshots.values())
    return {"a": dict(_localize(a)), "y": dict(_localize(y)), "files": len(work), "kept": kept,
            "legacy_kept": sum(d["legacy"] for d in snapshots.values()),
            "undated_actions": sum(d["undated"] for d in snapshots.values())}


# ------------------------------------------------- what your rules would hold

# Every log by default: the newest 400 were 17 of 731 days on a heavy machine, and the
# counts came out six times too low with nothing saying so. The budget below bounds it.
HELD_FILES = int(os.environ.get("KYMA_HELD_FILES", "0")) or None
_FILE_BUDGET = 8.0        # a byte cursor carries unfinished logs into the next pass
_PARSED: dict = {}
_DECISIONS: dict = {}
HELD_BUDGET = float(os.environ.get("KYMA_HELD_SECONDS", "12"))          # newest logs judged against the rules; cached per log and per rule text
MARKS_KEPT = 400


def rules_text() -> tuple:
    """-> (text, yours). Your ~/.kyma/RULES.md, else the rules kyma starts with."""
    from . import enforce
    try:
        with open(enforce.GLOBAL_RULES, encoding="utf-8", errors="replace") as fh:
            return fh.read(), True
    except OSError:
        return enforce.TEMPLATE, False


_HOMES = re.compile(r"/(?:Users|home)/[^/\s'\"]+")


def _tilde(text: str) -> str:
    """Quoted commands show ~, never a home folder: it names the person."""
    return _HOMES.sub("~", text.replace(os.path.expanduser("~"), "~"))


def _held_cache(path: str) -> str:
    return os.path.join(CACHE, "held-" + hashlib.sha1(path.encode("utf-8", "replace")).hexdigest() + ".json")


def _head(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read(256)).hexdigest()[:12]
    except OSError:
        return ""


def _tag(text: str) -> str:
    return f"h{VERSION}.6:{hashlib.sha1(text.encode()).hexdigest()[:12]}"


def command_evidence(value: str) -> dict:
    """Bounded original input for disclosure, separate from the matched fragment."""
    from . import signals
    clipped = len(value) >= sources.COMMAND_CAP
    value = _tilde(signals.clean(signals.redact(value[:sources.COMMAND_CAP])))
    return {"command": value[:4096], "command_clipped": clipped or len(value) > 4096}


def _timestamp_order(ts: str) -> float:
    try:
        parsed = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)).timestamp()
    except (ValueError, OSError):
        parsed = _utc(ts)
        return parsed.timestamp() if parsed else 0.0


def cached_marks(path: str, text: str) -> list:
    """What these rules were already found to hold in this log. Never judges:
    building the agent tree must not re-read logs the budget already passed over."""
    try:
        with open(_held_cache(path)) as fh:
            c = json.load(fh)
    except (OSError, ValueError):
        return []
    return c.get("m", []) if isinstance(c, dict) and c.get("t") == _tag(text) else []


def _judge_file(item) -> list:
    return _judge(item)[0]


def _judge(item) -> tuple:
    """-> ([[cell, verdict, rule, excerpt, result metadata], ...], done) for one log.
    History mode: today's project files are never read.

    A log that runs out of time keeps how far it got, and the next run
    carries on from there. A log that only grew (a live session) is judged
    from where it was, not from the top."""
    path, agent, text = item[:3]
    deadline = item[3] if len(item) > 3 else None
    from . import rules, shell, signals
    try:
        st = os.stat(path)
    except OSError:
        return [], True
    tag, cp, head = _tag(text), _held_cache(path), _head(path)
    size, mtime = st.st_size, st.st_mtime_ns
    seekable = agent != "gemini" and not path.endswith((".zst", ".json"))
    marks, start, cursor = [], 0, {"offset": 0, "item": 0}
    first, last, checked = "", "", 0
    try:
        with open(cp) as fh:
            c = json.load(fh)
        if isinstance(c, dict) and c.get("t") == tag and c.get("head") == head and isinstance(c.get("n"), int):
            same = c.get("size") == size and c.get("mtime") == mtime
            grew = size > (c.get("size") or 0) and seekable
            if same and c.get("done"):
                return c.get("m", []), True
            if same or grew:
                marks, start = list(c.get("m", [])), c["n"]
                cursor = c.get("cursor") or cursor
                first, last = c.get("first", ""), c.get("last", "")
                checked = c.get("checked", 0)
    except (OSError, ValueError, TypeError):
        pass
    first_order = _timestamp_order(first) if first else float("inf")
    last_order = _timestamp_order(last) if last else float("-inf")
    active = _PARSED.get(text)
    if active is None:                       # once per worker, not once per log
        active = [r for r in rules.parse(text) if r.enforced]
        active = _PARSED[text] = getattr(rules, "prepare_rules", list)(active)
    reader = sources.reader(agent)
    previous_fs, shell._FS[0] = shell._FS[0], False
    stop_at = time.monotonic() + _FILE_BUDGET
    if deadline is not None:
        stop_at = min(stop_at, deadline)
    n, done = start, True

    def keep():
        try:
            ensure_home()
            os.makedirs(CACHE, exist_ok=True)
            state_write(cp, json.dumps({"t": tag, "head": head, "size": size, "mtime": mtime, "n": n,
                                        "done": done, "m": marks, "cursor": cursor,
                                        "first": first, "last": last, "checked": checked}, separators=(",", ":")))
        except OSError:
            pass
    iterator = reader(path, cursor=cursor) if seekable else reader(path)
    try:
        i = 0
        while True:
            if deadline is not None and time.monotonic() > deadline:
                done = False
                break
            before = dict(cursor)
            try:
                act = next(iterator)
            except StopIteration:
                break
            if not seekable and i < start:
                i += 1
                continue
            if not seekable and i == start:
                # A compressed stream must decode its old prefix to resume.
                # Charge the budget to new work after reaching the next action;
                # otherwise a prefix slower than the budget stalls every pass.
                stop_at = min(time.monotonic() + _FILE_BUDGET, deadline) if deadline is not None else time.monotonic() + _FILE_BUDGET
            if time.monotonic() > stop_at:
                cursor, done = before, False
                break
            i += 1
            n += 1
            k = (_ukey(act.ts) if act.ts else None) or ""
            if act.command:
                inp, tool = {"command": act.command[:shell.MAX]}, "Bash"
            elif act.paths:
                inp, tool = {"file_path": act.paths[0]}, (act.tool or "Read")
            else:
                inp, tool = {}, act.tool or ""
            try:
                subject = next(iter(inp.values()), "")
                key = (tag, tool, hashlib.sha256(subject.encode("utf-8", "surrogatepass")).digest())
                result = _DECISIONS.get(key)
                if result is None:
                    units = shell.units_for(tool, inp)
                    d = rules.decide_units(active, units)
                    seen = act.paths[0] if (act.paths and not act.command) else tool
                    if d.verdict != "allow":
                        for u in units:
                            if rules.decide_units(active, [u]).verdict != "allow":
                                seen = " ".join((u.raw or u.text).split())
                                break
                    excerpt = _tilde(signals.clean(signals.redact(seen)))[:140] if d.verdict != "allow" else ""
                    result = (d.verdict, d.rule.text if d.rule else "", excerpt)
                    if len(_DECISIONS) >= 8192:
                        _DECISIONS.clear()
                    _DECISIONS[key] = result
            except Exception:
                n -= 1
                cursor, done = before, False
                break
            verdict, rule_text, seen = result
            checked += 1
            order = _timestamp_order(act.ts) if k else None
            if order is not None and order < first_order:
                first, first_order = act.ts, order
            if order is not None and order > last_order:
                last, last_order = act.ts, order
            if verdict == "allow" or not rule_text:
                continue
            # Every hold is counted; only the first 60 in a log keep a quote.
            ex = seen if len(marks) < 60 else ""
            meta = {"call_id": act.call_id, "actor_id": act.actor_id, "status": "unknown", "source": "unknown"}
            if ex:
                meta.update(command_evidence(act.command or (act.paths[0] if act.paths else act.tool)))
            marks.append([k, verdict, rule_text, ex, meta])
    except Exception:
        done = False
    finally:
        iterator.close()
        shell._FS[0] = previous_fs
    keep()
    return marks, done


def _judge_coverage(item) -> tuple:
    marks, done = _judge(item)
    try:
        with open(_held_cache(item[0])) as fh:
            c = json.load(fh)
        coverage = {"n": c.get("checked", 0), "first": c.get("first", ""), "last": c.get("last", "")}
    except (OSError, ValueError, TypeError):
        coverage = {"n": 0, "first": "", "last": ""}
    return marks, done, coverage


def held_moments(progress=None, work=None, budget=None) -> dict:
    """What your rules would have stopped in your newest logs, and what the
    hook has actually stopped since you plugged it in."""
    from . import enforce, signals
    text, yours = rules_text()
    scoped = work is not None
    bounded = scoped and budget is not None
    selected = list(work) if scoped else files()[:HELD_FILES]
    deadline = time.monotonic() + (HELD_BUDGET if budget is None else budget)
    work = [(f, a, text, deadline) if scoped and budget is not None else (f, a, text) for f, a in selected]
    total = len(work)
    past = []
    inspected, partial_logs, checked = [], 0, 0
    first, last = "", ""
    if work:
        # A budget: a first run on a heavy history must not sit for minutes. Logs
        # are taken as they finish, not in order, so one huge log cannot hold the
        # rest back; whatever was judged in time is the judged window, and the
        # page and the terminal say which days it covers.
        from concurrent.futures import as_completed, TimeoutError as _Timeout
        pool = _pool()
        finished = []
        try:
            futs = {pool.submit(_judge_coverage, w): w for w in work}
            try:
                for n, fut in enumerate(as_completed(futs, timeout=None if bounded else max(0.1, deadline - time.monotonic())), 1):
                    try:
                        m, whole, coverage = fut.result()
                    except Exception:
                        m, whole, coverage = [], False, {}
                    past += [[_local(r[0]) or ""] + list(r[1:]) for r in m if not r[0] or _local(r[0])]
                    inspected.append(futs[fut][0])
                    checked += coverage.get("n", 0)
                    partial_logs += not whole
                    if coverage.get("first"):
                        first = min(first, coverage["first"], key=_timestamp_order) if first else coverage["first"]
                    if coverage.get("last"):
                        last = max(last, coverage["last"], key=_timestamp_order) if last else coverage["last"]
                    if whole:
                        finished.append(futs[fut])
                    if progress and n % 10 == 0:
                        progress(n, total)
                    if not bounded and time.monotonic() > deadline:
                        break
            except _Timeout:
                pass
        finally:
            try:
                pool.shutdown(wait=bounded, cancel_futures=True)
            except TypeError:
                pool.shutdown(wait=bounded)
        work = finished
    live = []
    for e in enforce.held(2000):
        if e.get("verdict") not in ("block", "ask") or not e.get("ts"):
            continue
        k = _key(e["ts"])
        if k:
            live.append([k, e["verdict"], e.get("rule", ""),
                         _tilde(signals.clean(signals.redact(str(e.get("subject", "")))))[:140]])
    return {"past": past, "live": live, "yours": yours, "judged": len(work), "of": total,
            "since": (_key(first) or "")[:10] if first else None, "paths": inspected,
            "partial_logs": partial_logs, "checked_calls": checked,
            "checked_first": first, "checked_last": last, "hook": _hook_totals()}


def _hook_totals() -> dict:
    """Exact verdict and rule totals, with an append cursor over complete records."""
    from . import enforce, state_read, signals
    out = {"block": 0, "ask": 0, "by_rule": {}}
    cp = os.path.join(CACHE, "hook-counts.json")
    try:
        fd = os.open(enforce.LOG, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return out
    with os.fdopen(fd, "rb") as fh:
        import stat
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            return out
        identity = [st.st_dev, st.st_ino]
        head = fh.read(min(64, st.st_size)).hex()
        try:
            c = json.loads(state_read(cp) or "{}")
            offset = c.get("offset", 0)
            totals = c.get("totals", {})
            valid = isinstance(totals, dict) and all(type(totals.get(k)) is int and totals[k] >= 0 for k in ("block", "ask"))
            valid = valid and isinstance(totals.get("by_rule"), dict) and all(
                isinstance(k, str) and type(n) is int and n >= 0 for k, n in totals["by_rule"].items())
            if valid and type(offset) is int and c.get("identity") == identity and c.get("head") == head and 0 <= offset <= st.st_size:
                out = c["totals"]
            else:
                offset = 0
        except (ValueError, TypeError, KeyError):
            offset = 0
        fh.seek(offset)
        labels = {}
        while True:
            raw = fh.readline()
            if not raw or not raw.endswith(b"\n"):
                break
            offset = fh.tell()
            try:
                e = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            if not isinstance(e, dict) or e.get("verdict") not in ("block", "ask"):
                continue
            out[e["verdict"]] += 1
            r = e.get("rule", "")
            if isinstance(r, str):
                if r not in labels:
                    labels[r] = signals.clean(signals.redact(r))
                label = labels[r]
                out["by_rule"][label] = out["by_rule"].get(label, 0) + 1
        try:
            ensure_home()
            os.makedirs(CACHE, exist_ok=True)
            state_write(cp, json.dumps({"identity": identity, "head": head, "offset": offset, "totals": out}))
        except OSError:
            pass
    return out


# ------------------------------------------------------------------ the shape

def shape(data: dict) -> dict:
    """Days from the first lit hour to today, 24 hours each."""
    a, y = data.get("a", {}), data.get("y", {})
    undated = data.get("undated_actions", 0)
    keys = list(a) + list(y) + [m[0] for m in data.get("held", {}).get("live", [])]
    if not keys and not undated:
        return {}
    first = min(k[:10] for k in keys) if keys else _dt.date.today().isoformat()
    d0 = _dt.date.fromisoformat(first)
    today = _dt.date.today()
    days = (today - d0).days + 1
    A = [[0] * 24 for _ in range(days)]
    Y = [[0] * 24 for _ in range(days)]
    for src, dst in ((a, A), (y, Y)):
        for k, n in src.items():
            try:
                i = (_dt.date.fromisoformat(k[:10]) - d0).days
                h = int(k[11:13])
            except ValueError:
                continue
            if 0 <= i < days and 0 <= h < 24:
                dst[i][h] += n
    marks = []
    for kind, rows in (("past", data.get("held", {}).get("past", [])), ("live", data.get("held", {}).get("live", []))):
        for row in rows:
            k, verdict, rule, ex = row[:4]
            result = row[4] if len(row) > 4 and isinstance(row[4], dict) else {"status": "unknown"}
            if not k:
                marks.append({"i": None, "h": None, "undated": True, "v": verdict, "r": rule,
                              "c": ex, "live": kind == "live", "result": result})
                continue
            try:
                i = (_dt.date.fromisoformat(k[:10]) - d0).days
                h = int(k[11:13])
            except (ValueError, TypeError):
                continue
            if 0 <= i < days and 0 <= h < 24:
                result = row[4] if len(row) > 4 and isinstance(row[4], dict) else {"status": "unknown"}
                marks.append({"i": i, "h": h, "v": verdict, "r": rule, "c": ex, "live": kind == "live", "result": result})
    marks.sort(key=lambda m: (m["live"], m["i"] if m["i"] is not None else -1,
                              m["h"] if m["h"] is not None else -1), reverse=True)
    # One example per rule, the clearest: something stopped live first, then the shortest quote.
    by_rule = {}
    for m in marks:
        by_rule.setdefault(m["r"], []).append(m)
    examples = []
    for m in marks:
        m["away"] = not m.get("undated") and not Y[m["i"]][m["h"]]
    for r, ms in sorted(by_rule.items(), key=lambda kv: (-any(m["live"] for m in kv[1]),
                                                         -any(m["away"] for m in kv[1]), -len(kv[1]))):
        # The clearest proof, not the shortest: something stopped live, then
        # something done while you were away, then a hard block, then the
        # most forceful (a force push over a plain one), then the most recent.
        loud = lambda c: any(k in c for k in ("--force", " -f ", "-rf", "sudo", ".env", "| sh", "| bash"))
        best = min(ms, key=lambda m: (not m["c"], not m["live"], not m["away"], m["v"] != "block", not loud(m["c"]),
                                      len(m["c"]) > 90, -(m["i"] if m["i"] is not None else -1),
                                      -(m["h"] if m["h"] is not None else -1)))
        examples.append(dict(best, n=len(ms)))
        if len(examples) == 3:
            break
    together = sum(1 for i in range(days) for h in range(24) if A[i][h] and Y[i][h])
    alone = sum(1 for i in range(days) for h in range(24) if A[i][h] and not Y[i][h])
    past_marks = [m for m in marks if not m["live"]]
    live_marks = [m for m in marks if m["live"]]
    # Reserve room for both kinds. A full hook tail cannot erase replay from
    # the picture. Spread the samples through each cohort's observed times.
    past_n = min(len(past_marks), max(MARKS_KEPT // 2, MARKS_KEPT - len(live_marks)))
    live_n = min(len(live_marks), MARKS_KEPT - past_n)
    def sample(rows, n):
        return [rows[i * len(rows) // n] for i in range(n)] if n else []
    shown = sample(live_marks, live_n) + sample(past_marks, past_n)
    past_counts = Counter(m["r"] for m in past_marks)
    live_counts = data.get("held", {}).get("hook", {}).get("by_rule")
    if live_counts is None:
        live_counts = dict(Counter(m["r"] for m in live_marks))
    return {"first": first, "days": days, "A": A, "Y": Y, "actions": sum(map(sum, A)) + undated,
            "undated_actions": undated, "legacy_kept": data.get("legacy_kept", 0),
            "together": together, "alone": alone, "you": sum(1 for r in Y for v in r if v),
            "marks": shown, "examples": examples, "by_rule": dict(past_counts), "live_by_rule": live_counts,
            "marks_total": len(past_marks) + sum(live_counts.values()),
            "more": max(0, len(marks) - sum(e["n"] for e in examples)), "held_past": sum(1 for m in marks if not m["live"]),
            "held_live": max(sum(1 for m in marks if m["live"] and m["v"] == "block"),
                             data.get("held", {}).get("hook", {}).get("block", 0)),
            "asked_live": max(sum(1 for m in marks if m["live"] and m["v"] != "block"),
                              data.get("held", {}).get("hook", {}).get("ask", 0)),
            "away_past": sum(1 for m in marks if not m["live"] and m["away"]),
            "stop_past": sum(1 for m in marks if not m["live"] and m["v"] == "block"),
            "ask_past": sum(1 for m in marks if not m["live"] and m["v"] != "block"),
            "yours": data.get("held", {}).get("yours", False),
            "judged": data.get("held", {}).get("judged", 0),
            "judged_of": data.get("held", {}).get("of", 0),
            "partial_logs": data.get("held", {}).get("partial_logs", 0),
            "checked_calls": data.get("held", {}).get("checked_calls", 0),
            "checked_first": data.get("held", {}).get("checked_first", ""),
            "checked_last": data.get("held", {}).get("checked_last", ""),
            "judged_from": max(0, (_dt.date.fromisoformat(data["held"]["since"]) - d0).days)
            if data.get("held", {}).get("since") else 0,
            "today": _dt.date.today().isoformat()}


def when(iso: str) -> str:
    d = _dt.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


# --------------------------------------------------------------- the terminal

# One color for each half of the story, as on the page: cool is your agents,
# from a dim slate for a quiet hour to pale lavender for a busy one. Warm is
# any hour you were there. A third "both" tint read as empty space.
_COOL = [236, 237, 24, 25, 31, 32, 33, 39, 75, 117]   # one hue, the page's agent blue
_WARM = 215
_BOTH = _WARM
_HELD = 168          # what your rules would have stopped: rose
_LIVE = 204          # what they did stop, since you plugged kyma in: bright rose


def _tty() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "") not in ("", "dumb") and not os.environ.get("NO_COLOR")


# Rows run from 6am down to 5am. Midnight at the top split every night across
# the top and bottom edges, and a reader saw two different things.
ORDER = list(range(6, 24)) + list(range(0, 6))


def _columns(s: dict, width: int) -> tuple:
    """Fold days into at most `width` columns.

    -> (cols, per): cols[c][h] = (agent calls, share of the folded days you were there)."""
    days = s["days"]
    per = max(1, math.ceil(days / width))
    cols = []
    for c in range(math.ceil(days / per)):
        col = []
        for h in range(24):
            a = lit = you = 0
            for i in range(c * per, min(days, (c + 1) * per)):
                if s["A"][i][h] or s["Y"][i][h]:
                    lit += 1
                    a += s["A"][i][h]
                    you += 1 if s["Y"][i][h] else 0
            col.append((a, you / lit if lit else 0.0))
        cols.append(col)
    return cols, per


def _color(a: int, share: float, top: float):
    if share >= 0.5:
        return _WARM                     # you were there on most of these days, at this hour
    if a:
        v = math.log1p(a) / math.log1p(top) if top else 0
        return _COOL[min(len(_COOL) - 1, int(v * (len(_COOL) - 1) + 0.5))]
    return None


def _glyph(a: int, share: float, top: float) -> str:
    c = _color(a, share, top)
    if c is None:
        return " "
    if c == _WARM:
        return f"\x1b[38;5;{c}m●\x1b[0m"
    v = math.log1p(a) / math.log1p(top) if top else 0
    g = "·" if v < .34 else ("•" if v < .67 else "●")
    return f"\x1b[38;5;{c}m{g}\x1b[0m"


def _cell(top_c, bot_c) -> str:
    if top_c is None and bot_c is None:
        return " "
    if bot_c is None:
        return f"\x1b[38;5;{top_c}m▀\x1b[0m"
    if top_c is None:
        return f"\x1b[38;5;{bot_c}m▄\x1b[0m"
    return f"\x1b[38;5;{top_c};48;5;{bot_c}m▀\x1b[0m"


def draw(s: dict, animate: bool = True, out=None) -> None:
    """The light, in the terminal: one column per day (or a few), one row per
    hour, swept in from the first day to today."""
    out = out or sys.stdout
    size = shutil.get_terminal_size((100, 40))
    if size.columns < 24:
        return               # too narrow for one row of hours plus its label; the counts follow on their own
    if size.columns < 40:
        animate = False      # cursor-addressed glyphs pile up at the right edge of a very narrow window
    left = 6
    width = max(10, min(size.columns - left - 6, 180))
    cols, per = _columns(s, width)
    stretch = max(1, min(3, width // max(1, len(cols))))
    top = max((a for col in cols for a, _ in col), default=1)
    marked = {}
    for m in s.get("marks", []):
        if m.get("undated"):
            continue
        key = (m["i"] // per, m["h"])
        marked[key] = _LIVE if (m["live"] or marked.get(key) == _LIVE) else _HELD
    dots = size.lines >= 34
    rows = 24 if dots else 12
    grid = []
    for r in range(rows):
        row = []
        for col in cols:
            c = len(row)
            if dots:
                h = ORDER[r]
                a, share = col[h]
                g = (f"\x1b[38;5;{marked[(c, h)]}m\u25c6\x1b[0m" if (c, h) in marked else _glyph(a, share, top))
                row.append(g + " " * (stretch - 1))
            else:
                h1, h2 = ORDER[2 * r], ORDER[2 * r + 1]
                (a1, s1), (a2, s2) = col[h1], col[h2]
                t = marked.get((c, h1)) or _color(a1, s1, top)
                b = marked.get((c, h2)) or _color(a2, s2, top)
                row.append(_cell(t, b) * stretch)
        grid.append(row)
    marks = {0: " 6am", 6: "12pm", 12: " 6pm", 18: "12am"} if dots else {0: " 6am", 3: "12pm", 6: " 6pm", 9: "12am"}
    pad = "  "
    w = len(cols) * stretch
    lead = lambda r: f"{pad}\x1b[2m{marks.get(r, ''):>4}\x1b[0m  "
    if size.lines < rows + 4:
        animate = False      # a sweep moves the cursor up; it cannot climb past the top of a short window
    out.write("\n")
    if not animate:
        for r in range(rows):
            out.write(lead(r) + "".join(grid[r]) + "\n")
    else:
        for r in range(rows):
            out.write(lead(r) + " " * w + "\n")
        out.write("\x1b[?25l")
        out.flush()
        total = min(6.0, max(2.4, len(cols) * 0.035))
        step = total / max(1, len(cols))
        try:
            for c in range(len(cols)):
                buf = []
                for r in range(rows):
                    up = rows - r
                    buf.append(f"\x1b[{up}A\x1b[{len(pad) + 6 + c * stretch + 1}G{grid[r][c]}\x1b[{up}B")
                out.write("".join(buf) + "\r")
                out.flush()
                time.sleep(step)
        except KeyboardInterrupt:
            # Quit, as Ctrl-C should, but never leave half a picture behind.
            out.write(f"\x1b[{rows}A")
            for r in range(rows):
                out.write("\r" + lead(r) + "".join(grid[r]) + "\n")
            out.write("\x1b[?25h")
            out.flush()
            raise
        finally:
            out.write("\x1b[?25h")
    start = _dt.date.fromisoformat(s["first"])
    a_lbl = f"{start.day} {start.strftime('%b %Y')}"
    if w - len(a_lbl) < 7:
        a_lbl = f"{start.day} {start.strftime('%b')}"
    out.write(f"{pad}      \x1b[2m{a_lbl}{'today'.rjust(max(6, w - len(a_lbl)))}\x1b[0m\n\n")
    out.flush()


def facts_line(s: dict, color: bool = True, width: int | None = None) -> str:
    def dot(c):
        return "\x1b[38;5;%dm\u25cf\x1b[0m " % c if color else ""
    def b(n):
        t = "{:,}".format(n)
        return "\x1b[1m%s\x1b[0m" % t if color else t
    calls = "tool call" if s["actions"] == 1 else "tool calls"
    parts = [b(s["actions"]) + f" {calls}", dot(_BOTH) + b(s["together"]) + " active h with you",
             dot(_COOL[8]) + b(s["alone"]) + " active h alone"]
    for n, glyph, c, word in ((s.get("stop_past", 0), "\u25b2", _HELD, "would stop"), (s.get("ask_past", 0), "\u25f7", 215, "would ask")):
        if n:
            parts.append(("\x1b[38;5;%dm%s\x1b[0m " % (c, glyph) if color else glyph + " ") + b(n) + " " + word)
    if width is None:
        return "  " + "    ".join(parts)
    seen = lambda t: len(re.sub(r"\x1b\[[0-9;]*m", "", t))
    lines, cur = [], ""
    for p in parts:                       # a narrow terminal gets two lines, not one that wraps mid-word
        if cur and 2 + seen(cur) + 4 + seen(p) > width:
            lines.append(cur)
            cur = p
        else:
            cur = cur + "    " + p if cur else p
    return "\n".join("  " + x for x in lines + [cur])


# ------------------------------------------------------------------- the page

OUT = os.path.join(HOME, "kyma.html")

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>kyma</title>
<style>
*,*::before,*::after{box-sizing:border-box}
[hidden]{display:none!important}
:root{--page:#161618;--panel:#1b1b1e;--line:#2a2a2c;--hair:#232326;--ink:#fff;--task:#b4b4b9;--meta:#a2a2a8;
  --agent:#74b6f9;--agent2:#508fdb;--you:#ffb86e;--held:#ff6f91;--away:#b79cff;--chip:#232327}
html,body{margin:0;background:var(--page);color:var(--ink);-webkit-font-smoothing:antialiased;overflow-x:clip}
body{font:13px/1.45 ui-sans-serif,-apple-system,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.mono{font-family:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
main{max-width:1180px;margin:0 auto;padding:clamp(.75rem,3vw,2.5rem) clamp(.5rem,2.5vw,2rem)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:0 1px 2px rgba(0,0,0,.35)}
.bar{display:flex;align-items:center;gap:.9rem;flex-wrap:wrap;padding:.7rem .9rem;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:.45rem;font-weight:600}
.brand svg{width:14px;height:14px;color:var(--ink)}
.count{display:flex;align-items:center;gap:.4rem;color:var(--task);white-space:nowrap}
.count b{color:var(--ink);font-weight:500;font-variant-numeric:tabular-nums}
.dot{width:7px;height:7px;border-radius:50%;flex:none}
.ring{width:9px;height:9px;border-radius:50%;border:1.6px solid var(--held);flex:none}
.ring.live{background:var(--held);box-shadow:0 0 6px var(--held)}
.ring.vstop{border-color:#f07a5e}.ring.vask{border-color:#f0a845}
.spacer{flex:1}
.state{display:flex;align-items:center;gap:.35rem;border-radius:5px;padding:.14rem .45rem;font-size:12px;background:#26262a;color:var(--task)}
.state.on{background:#12321f;color:#5fd08a}.state.on .dot{background:#5fd08a;width:6px;height:6px}
.go{display:flex;align-items:center;gap:.4rem;font-size:12px;height:28px;padding:0 .6rem;border-radius:7px;border:0;cursor:pointer;
  background:#f2f2f3;color:#111;transition:background .15s}
.go:hover{background:#fff}.go:focus-visible{outline:2px solid var(--agent2);outline-offset:2px}.go svg{width:13px;height:13px}
.go.done{background:#12321f;color:#5fd08a}
.chip{border-radius:6px;background:var(--chip);color:var(--task);padding:.18rem .5rem;font-size:12px;white-space:nowrap}
.icon{display:grid;place-items:center;width:28px;height:28px;border-radius:7px;border:1px solid var(--line);background:transparent;
  color:var(--task);cursor:pointer;padding:0;transition:background .15s,color .15s,border-color .15s}
.icon:hover{background:#242428;color:var(--ink);border-color:#3a3a3e}
.icon:focus-visible,.rule:focus-visible{outline:2px solid var(--agent2);outline-offset:2px}
.icon svg{width:14px;height:14px}
.icon.ok{color:#5fd08a;border-color:#245238}
.stage{position:relative;padding:.6rem .9rem .2rem;overflow-x:auto;overscroll-behavior-x:contain}
@media (max-width:620px){.stage{-webkit-mask-image:linear-gradient(to right,transparent 0,#000 14px,#000 calc(100% - 28px),transparent);
  mask-image:linear-gradient(to right,transparent 0,#000 14px,#000 calc(100% - 28px),transparent)}}
canvas{display:block;width:100%;touch-action:pan-x pan-y}
.yax{position:sticky;left:0;width:0;height:0;z-index:3}
.yax span{position:absolute;left:-.9rem;transform:translateY(-50%);font:10px ui-monospace,Menlo,monospace;color:#838385;
  background:#1b1b1e;padding:1px 4px 1px .9rem;border-radius:0 4px 4px 0}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
#tip{position:absolute;pointer-events:none;opacity:0;transform:translate(0,-118%);max-width:min(30rem,88vw);z-index:6;isolation:isolate;
  background:#202024;border:1px solid #34343a;border-radius:8px;padding:.4rem .6rem;font-size:12px;transition:opacity .12s;
  box-shadow:0 6px 20px rgba(0,0,0,.45)}
#tip .t{display:flex;align-items:center;gap:.45rem;color:var(--task);white-space:nowrap}
#tip .r{margin-top:.3rem;color:var(--ink);display:flex;gap:.45rem;align-items:center}
#tip .c{margin-top:.15rem;color:var(--meta);word-break:break-all}

/* the agent tree: cards on a slightly lighter surface, hairline wires, dark */
.tree{position:relative;padding:1.1rem .9rem 1.4rem;overflow-x:auto;border-bottom:1px solid var(--line);background:#1e1e21}
.tree svg.wires{position:absolute;left:0;top:0;pointer-events:none;overflow:visible}
@media (min-width:1200px){
  .split{display:grid;grid-template-columns:minmax(0,1fr) minmax(400px,36%);align-items:start}
  .side{position:sticky;top:0;border-left:1px solid var(--line);max-height:100vh;overflow:auto}
  .tree{border-bottom:0}
}
.wires .glabel{font:11px ui-monospace,Menlo,monospace;fill:#8e8e91}
.wires .glabel.stop{fill:#f07a5e}.wires .glabel.ask{fill:#f0a845}
.troot{display:flex;justify-content:center}
.trow{display:flex;gap:18px;justify-content:flex-start;align-items:flex-start;margin-top:48px;flex-wrap:nowrap}
#trows{padding-left:24px}
#trows{width:fit-content;max-width:100%;margin:0 auto}
.tcol{display:flex;flex-direction:column;align-items:flex-start;width:248px;flex:0 0 248px}
.ag{position:relative;z-index:1;width:100%;background:#1b1b1e;border:1px solid #2a2a2c;border-radius:8px;padding:10px 10px 8px;
  box-shadow:0 1px 2px rgba(0,0,0,.4);opacity:.4;transform:translateY(4px);transition:opacity .3s,transform .3s,border-color .15s}
.ag.in{opacity:1;transform:none}
.ag.can{cursor:pointer}
.ag.can:hover{border-color:#3d3d42}
.ag:has(.ob:focus-visible){box-shadow:0 0 0 2px #508fdb}
.ob{all:unset;display:block;max-width:100%;cursor:pointer}
.ag.dim{opacity:.4}
.ag.hit{border-color:#f07a5e;box-shadow:0 0 0 1px #f07a5e}
.wires path.draw{transition:stroke-dashoffset .26s ease-out}
.ag.root{width:340px;max-width:100%}
.ag-h{display:flex;align-items:flex-start;gap:9px}
.tile{flex:none;width:28px;height:28px;border-radius:7px;border:1px solid #2f2f33;display:grid;place-items:center;background:#202024}
.tile svg{width:16px;height:16px}
.tile img{display:block;object-fit:contain;flex:none}.tile img.provider-mark{max-width:none}
.tile svg.claude-mark{width:18px;height:18px}.tile svg.codex-mark{width:32px;height:32px}
.tt{min-width:0;flex:1}
.ti{font-weight:500;font-size:13px;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#fff}
.ob{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mo{font-size:12px;color:#8a8a8d;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.st{flex:none;display:inline-flex;align-items:center;gap:4px;height:19px;padding:0 6px;border-radius:4px;font-size:11px;white-space:nowrap}
.st svg{width:12px;height:12px}
.st.done{background:#232327;color:#8f8f94}.st.on{background:#12321f;color:#5fd08a}.st.run{background:#153253;color:#74b6f9}
.st.ask{background:#3a2a10;color:#f0a845}.st.stop{background:#3a1a14;color:#f07a5e}
.st.off{background:#26262a;color:#a5a5a7}
.st.run svg{animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.task{font-size:13px;color:#a5a5a7;margin-top:9px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.8em}
.ft{display:flex;align-items:center;justify-content:space-between;margin-top:9px;font-size:12px;color:#838385}
.ft>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ft b{color:#fff;font-weight:500}
.kids{display:inline-flex;align-items:center;gap:3px;border:0;background:transparent;color:#a5a5a7;font:inherit;font-size:12px;
  cursor:pointer;padding:2px 6px;min-height:24px;border-radius:5px}
.kids:focus-visible{outline:2px solid #508fdb}
.kids:hover{background:#26262a;color:#fff}.kids svg{width:11px;height:11px;transition:transform .2s}
.kids[aria-expanded="false"] svg{transform:rotate(-90deg)}
.sub{display:flex;flex-direction:column;gap:14px;margin-top:14px;padding-left:34px;width:100%}
.sub[hidden]{display:none}
.more-row{display:flex;justify-content:center;margin-top:18px}
.chipbtn{border:1px solid #2a2a2c;background:#1b1b1e;color:#a5a5a7;border-radius:7px;padding:.3rem .7rem;font:inherit;font-size:12px;cursor:pointer}
.chipbtn:focus-visible,.kids:focus-visible,.ag:focus-visible{outline:2px solid #508fdb;outline-offset:2px}
.chipbtn:hover{color:#fff;border-color:#3d3d42}
.still .ag{transition:none;opacity:1;transform:none}.still .wires path{transition:none}
@media (prefers-reduced-motion:reduce){.ag{transition:none;opacity:1;transform:none}.st.run svg{animation:none}}
@media (max-width:620px){.tree{overflow:visible}.trow{flex-direction:column;align-items:stretch;margin-top:14px;gap:14px}.tcol{max-width:none;width:auto;flex:1 1 auto}.ag.root{width:100%}
  #trows{padding-left:0;width:auto}
  .trow[data-label]{margin-top:30px}.sub{margin-top:14px;gap:14px}
  .rules{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}.rules::-webkit-scrollbar{display:none}
  .rule{flex:0 0 auto;max-width:78vw}
}
.lanebtn{border:1px solid transparent;background:transparent;color:inherit;font:inherit;cursor:pointer;border-radius:6px;padding:.1rem .4rem;margin:-.1rem -.4rem}
.lanebtn:hover,.lanebtn[aria-pressed="true"]{border-color:#3f6fa8;background:#16263a}
.lanebtn:focus-visible{outline:2px solid #508fdb}
.lane{display:flex;gap:.9rem;flex-wrap:wrap;align-items:center;padding:.8rem .9rem 0;font-size:12px}
.bar .st b{font-weight:600}
.evs:empty{display:none}
.ev{margin-top:9px;padding:7px 8px;border-radius:7px;background:rgba(224,96,62,.07);border:1px solid rgba(224,96,62,.18)}
.ag[data-st="ask"] .ev{background:rgba(240,168,69,.07);border-color:rgba(240,168,69,.2)}
.ev-c{color:#f1e6e2;font-size:12px;overflow-wrap:anywhere}
.older{font-size:12px;color:#929296}
.flag.rulef{background:#26262a;color:#e8e8ea;max-width:22rem}
.flag.rulef span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev-r{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:12px;color:#b9b9bd}
.ev-r i{font-style:normal;color:#838385;margin-left:auto;white-space:nowrap;font-size:11px}
.ev-more{font-size:11px;color:#838385;margin-top:5px}
.ev-t{font-size:11px;color:#838385;margin-top:4px}
.ev-away{font-size:11px;color:var(--away);margin-top:4px;display:flex;align-items:center;gap:5px}
.ev-away::before{content:"";width:7px;height:7px;border-radius:50%;border:1.5px solid #74b6f9}
.ev.away{border-color:rgba(116,182,249,.35)}
.all{display:flex;flex-direction:column;gap:6px;margin-top:10px;padding-top:10px;border-top:1px solid #2a2a2c}
.all .ev{margin-top:0}
.ag.open{border-color:#46464c}
.ag.open .evs{display:none}
.st.via{background:transparent;box-shadow:inset 0 0 0 1px currentColor}
.task{min-height:0}
.flag{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 8px;border-radius:6px;border:1px solid transparent;
  font:inherit;font-size:12px;cursor:pointer}
.flag svg{width:12px;height:12px}.flag b{font-weight:600}
.flag.stop{background:#3a1a14;color:#f07a5e}.flag.ask{background:#3a2a10;color:#f0a845}
.flag[aria-pressed="true"]{border-color:currentColor;background:currentColor}
.flag[aria-pressed="true"] b,.flag[aria-pressed="true"]{color:#111}
.flag.stop[aria-pressed="true"]{background:#f07a5e}.flag.ask[aria-pressed="true"]{background:#f0a845}
.flag:focus-visible,.cmd:focus-visible{outline:2px solid #508fdb;outline-offset:2px}
.cmd{display:inline-flex;align-items:center;gap:8px;min-height:28px;max-width:100%;padding:0 9px;border-radius:7px;border:1px solid #34353b;
  background:#101113;color:#e8e8ea;font-size:12px;cursor:pointer;align-self:flex-start;text-align:left}
.cmd span{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmd svg{width:13px;height:13px;color:#838385;flex:none}.cmd:hover{border-color:#4a4b52}
.cmd.done{color:#5fd08a;border-color:#245238}
.cmd-hint{font-size:11px;color:#74b6f9;margin-left:6px;align-self:center}
.cmd-f{height:28px;padding:0 9px;border-radius:7px;border:1px solid #508fdb;background:#101113;color:#e8e8ea;font-size:12px;width:12rem}
.pill{font-size:11px;border-radius:5px;padding:.08rem .4rem;background:#3a1c1a;color:#f59b85;margin-left:.5rem;white-space:nowrap}
.more{color:var(--meta);padding:.2rem .9rem .1rem calc(.9rem + .3rem + 16px + .75rem)}
/* the rules sit under the header as filters: the cause of every pill, beside the tree */
.rules{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:.6rem .9rem;border-bottom:1px solid var(--line)}
.rule{display:inline-flex;align-items:center;gap:7px;padding:.28rem .6rem;border:1px solid #2a2a2c;border-radius:7px;
  font:inherit;font-size:12px;color:inherit;background:transparent;cursor:pointer;text-align:left}
.rule.zero{cursor:default;border-style:dashed}
.rule:hover,.rule.on,.rule[aria-pressed="true"]{background:#212125}
.rule[aria-pressed="true"]{box-shadow:inset 2px 0 0 var(--held)}
.rule .n{font-weight:600;color:var(--ink)}
.rule.zero .txt,.rule.zero .n{color:var(--meta)}
.rule .ring.vstop{border-color:#f07a5e}.rule .ring.vask{border-color:#f0a845}
.rule.out{opacity:.4}
.flag.out{opacity:.45}
/* a group's name, drawn on the wires when wide; a heading of its own on a phone */
.glab{display:none;font-size:11px;color:var(--meta);margin:20px 0 -4px}
.glab.stop{color:#f07a5e}.glab.ask{color:#f0a845}
/* sessions with nothing held, after +N: one line each, not a wall of cards */
.quiet{display:flex;flex-direction:column;margin-top:28px;border-top:1px solid var(--hair)}
.qrow{display:grid;grid-template-columns:minmax(0,14rem) minmax(0,1fr) auto;gap:12px;align-items:baseline;padding:7px 2px;
  border-bottom:1px solid var(--hair);font-size:12.5px}
.qrow .qt{color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qrow .qt{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.qrow .qt i{font-style:normal;color:var(--meta)}
.qrow .qt .tile{width:20px;height:20px;flex:none}.qrow .qt .tile svg{width:16px;height:16px}
.qrow .qt .tile svg.codex-mark{width:28px;height:28px}
.qrow .qk{color:var(--task);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.qrow .qm{color:var(--meta);white-space:nowrap}
.qrow .ob{font:inherit;text-align:left;border:0;background:none;padding:0;cursor:pointer}.qrow .ob:hover{text-decoration:underline}.qrow .all{grid-column:1 / -1}
@media (max-width:1199px){.split{display:flex;flex-direction:column}.side{order:-1;border-bottom:1px solid var(--line)}}
@media (max-width:620px){.glab{display:block}.qrow{grid-template-columns:minmax(0,1fr) auto}.qrow .qk{grid-column:1 / -1;grid-row:2}}
/* Keep the original tree and its spatial hierarchy. Explain the event at its source. */
.context-line{display:flex;justify-content:space-between;gap:16px;padding:10px 15px 0;font-size:12px;color:var(--task)}
.context-line #date-range{white-space:nowrap;color:var(--meta)}
.coverage{margin:8px 15px 0;color:#c5a876;font-size:11px;line-height:1.5}
.scan-scope{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 15px 0;font-size:11px;color:var(--task)}.scan-scope[hidden]{display:none}.scan-scope .chipbtn{margin-left:auto}.scope-tag{border:1px solid #49443a;color:#d8c49e;border-radius:4px;padding:3px 6px}
.live-note{margin:10px 15px 0;padding:8px 10px;border:1px solid #31533c;border-radius:6px;background:#17261d;color:#8ed6a7;font-size:12px}
.local-note{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:12px 1px;color:var(--meta);font-size:11px}.local-note a{color:var(--meta);text-underline-offset:3px}
.ag.root{width:360px}.ag.root .evs{margin-top:10px}.ag.root .ft{font-size:11px}.ag.root .ft>span{white-space:normal}
.ag.root .go{height:32px;font:inherit;font-size:12px;padding:0 12px}
.ag:not(.root) .ag-h{position:relative;padding-bottom:17px}
.ag:not(.root) .mo{position:absolute;left:37px;bottom:0;max-width:calc(100% - 37px)}
.task{color:#c4c4c9}.ag.focused{border-color:#f07a5e;box-shadow:0 0 0 1px #f07a5e,0 0 20px #f07a5e0d}
.ag.focused[data-st="done"],.ag.focused[data-st="run"]{border-color:#8c9eaf;box-shadow:0 0 0 1px #8c9eaf}.ag.focused[data-st="ask"]{border-color:#f0a845;box-shadow:0 0 0 1px #f0a845}
.artifact-chip{display:flex;align-items:center;gap:8px;background:#242025;padding:8px 9px}
.artifact-chip code{font-size:12px;overflow-wrap:anywhere;color:#e8dcd8}
.filter-label{font-size:11px;color:var(--meta);margin-right:4px}
.inspector{padding:20px 18px 18px;border-bottom:1px solid var(--line)}
.inspect-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:24px}
.inspect-head h2{font-size:16px;line-height:1.3;font-weight:550;margin:0;letter-spacing:-.2px}
.inspect-nav{display:flex;align-items:center;gap:8px;color:var(--meta);font-size:10px}.inspect-nav button{font-size:20px}
.inspect-source{display:flex;align-items:center;gap:10px}.inspect-source strong{font-size:14px;font-weight:500;display:block}.inspect-source span:not(.tile){font-size:11px;color:var(--meta);display:block;margin-top:2px}
.inspect-arrow{font-size:11px;color:var(--meta);padding:14px 0 14px 13px}
.inspect-artifact{display:flex;align-items:center;gap:12px;padding:15px;border:1px solid #4c4040;background:#252126;border-radius:8px}
.inspect-artifact svg{width:27px;height:32px;flex:none;color:#e0b4a6}.inspect-artifact code{font-size:16px;color:#f7ece8;overflow-wrap:anywhere}
.inspect-verdict{border-left:2px solid #f07a5e;padding:9px 0 9px 13px}.inspect-verdict strong{display:block;font-weight:550;font-size:16px;color:#f18a70}.inspect-verdict span{display:block;font-size:12px;color:#c5b9b6;line-height:1.5;margin-top:5px}
.inspect-verdict.ask{border-color:#f0a845}.inspect-verdict.ask strong{color:#f0b958}
.inspect-verdict.ordinary{border-color:#8c9eaf}.inspect-verdict.ordinary strong{color:#d2dce6}.qrow.focused{border-left:2px solid #8c9eaf;padding-left:10px}
.inspect-outcome{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:10px;color:var(--meta);margin:21px 0 12px}
.inspect-outcome>span{background:#29292e;padding:2px 6px;border-radius:4px}
.inspect-evidence{font-size:11px;color:var(--meta);margin-bottom:20px}.inspect-evidence summary{cursor:pointer;padding:6px 0}.inspect-evidence code{display:block;white-space:pre-wrap;overflow-wrap:anywhere;max-height:140px;overflow:auto;padding:10px;background:#121215;border:1px solid var(--line);border-radius:6px;color:#ddd}.inspect-evidence p{font-size:11px;line-height:1.5}
.inspector .setup-primary{margin-top:4px}
.ag:not(.root) .ag-h{padding-bottom:0}.ag:not(.root) .mo{position:static;max-width:100%;font-size:11px;margin-top:5px}
.ag:not(.root) .mo{white-space:normal;line-height:1.45;overflow-wrap:anywhere}
.ag:not(.root) .st{display:none}.ag:not(.root) .ti,.ag:not(.root) .ob{white-space:normal;font-size:13px;line-height:1.4}
.ag:not(.root) .ob{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
#activity>summary{cursor:pointer;padding:15px;list-style:disclosure-closed}#activity[open]>summary{list-style:disclosure-open}
.ev-title{font-size:12px;font-weight:550;color:#f0d7ce;margin-bottom:5px}
.ev-r{align-items:flex-start}.ev-r .ring{margin-top:4px}
.ev-result{color:var(--meta);font-size:11px;margin-top:7px;line-height:1.5}
.ev-c{font-size:11px;color:#b9aca8}.ev-t{line-height:1.5}
.ev-extra{margin-top:7px}.ev-extra>summary{cursor:pointer;font-size:11px;color:#b9b9bd}
.ev-extra .ev-r{font-size:11px}.ev-extra p{font-size:11px;color:var(--meta);margin:6px 0}
.sub-label{font-size:10px;color:var(--meta);margin:0 0 -5px}.branch{width:100%}
.rule .n{font-size:11px}.live-n{font-size:10px;color:#8ed6a7}
.rules{padding-top:12px}.flag{height:28px}.bar{gap:10px}
#activity>summary{padding:14px 15px 0;list-style:none;font-weight:500;font-size:12px;color:var(--ink)}
#activity>summary::-webkit-details-marker{display:none}
.chart-note{font-size:11px;line-height:1.5;color:var(--meta);margin:9px 15px 0}
.side .lane{gap:9px 16px;font-size:11px}.side #held-fact{display:none}.side #away-fact{display:none}
.side #live-fact,.side #ask-fact{display:none}
#cmdslot{display:none}
.setup-dialog{border:1px solid #3a3a3f;border-radius:12px;padding:0;width:min(500px,calc(100vw - 28px));max-height:calc(100dvh - 32px);overflow:auto;color:var(--ink);background:var(--panel);box-shadow:0 24px 100px #0008}
.setup-dialog::backdrop{background:#09090bd9;backdrop-filter:blur(3px)}
.setup-dialog header{display:flex;justify-content:space-between;align-items:center;padding:19px 22px;border-bottom:1px solid var(--line)}
.setup-dialog h2{font-size:17px;font-weight:550;letter-spacing:-.3px;margin:0}
.setup-close{border:0;background:none;color:var(--task);cursor:pointer;width:30px;height:30px;border-radius:6px;font-size:24px;line-height:1}
.setup-body{padding:22px}.setup-body p{font-size:13px;line-height:1.6;color:var(--task);margin:0 0 20px}
#refresh-help{color:var(--task);font-size:13px;margin-top:16px}#refresh-help>summary{cursor:pointer}#refresh-help p{margin:12px 0 0;font-size:12px}
.example-badge{width:fit-content;margin:0 0 20px;padding:6px 9px;border:1px solid #424248;border-radius:4px;color:var(--task);font-size:11px}
.setup-scopes{display:flex;gap:8px;border:0;padding:0;margin:0 0 16px}.setup-scopes legend{font-size:12px;color:var(--task);margin-bottom:8px}.setup-scopes label{flex:1;border:1px solid var(--line);border-radius:7px;padding:10px;font-size:12px;cursor:pointer}.setup-scopes label:has(:checked){border-color:#e3e3e8;background:#29292e}.setup-scopes input{accent-color:#ddd;margin-right:5px}.setup-scopes label span{overflow-wrap:anywhere}
.attempt-command{display:block;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--ink);padding:10px 0}.setup-body h3{font-size:13px}.setup-file{border-left:2px solid var(--line);padding-left:12px;margin:12px 0}.setup-file>code{display:block;overflow-wrap:anywhere;font-size:12px;color:var(--ink)}.setup-file p{font-size:12px;margin:6px 0}
.setup-body ol{list-style:none;margin:0;padding:0}.setup-body li{position:relative;padding-left:32px;margin:0 0 22px;font-size:13px;line-height:1.5}
.setup-step{position:absolute;left:0;top:0;border:1px solid #45454b;color:var(--task);border-radius:50%;width:21px;height:21px;display:grid;place-items:center;font-size:10px}
.setup-command{display:flex;align-items:center;gap:8px;padding:12px;background:#111114;border:1px solid #34343a;border-radius:7px;margin:12px 0}
.setup-command code{min-width:0;flex:1;font-size:12px;overflow-wrap:anywhere;white-space:pre-wrap}
.plain-button{font:inherit;font-size:12px;border:1px solid #46464d;border-radius:5px;background:#28282e;color:var(--ink);min-height:32px;padding:0 12px;cursor:pointer}
.setup-done{font-size:12px!important;margin:10px 0 0!important;color:#8ed6a7!important}.setup-done:empty{display:none}
.setup-body li p{font-size:12px;margin:5px 0 0;line-height:1.5}.setup-success{font-size:12px;color:var(--task)}.setup-success strong{font-weight:500;color:#8ed6a7}
.setup-rules{border:1px solid var(--line);border-radius:7px;padding:12px;margin-bottom:20px}.setup-rules h3{font-size:12px;font-weight:550;margin:0 0 10px}
.setup-rules ul{list-style:none;margin:0;padding:0}.setup-rules li{display:grid;grid-template-columns:65px minmax(0,1fr);gap:10px;align-items:start;padding:7px 0;margin:0;font-size:12px;line-height:1.5;border-top:1px solid var(--line)}.setup-rules li:first-child{border-top:0;padding-top:0}.setup-rules li:last-child{padding-bottom:0}
.setup-rule-kind{border-radius:4px;padding:2px 6px;text-align:center;font-size:10px;font-weight:550;background:#29292f;color:var(--task)}.setup-rule-kind.ask{background:#372a15;color:#e8bd72}.setup-rule-kind.block{background:#3c241f;color:#f1977d}.setup-rule-kind.allow{background:#1d3328;color:#8ed6a7}.setup-rule-text{overflow-wrap:anywhere;color:var(--task)}
.setup-rule-status{font-size:11px;color:#e8bd72;margin:-3px 0 10px}
.setup-more{border-bottom:1px solid var(--line);margin-bottom:10px;font-size:12px}.setup-more>summary{cursor:pointer;padding:10px 0;color:var(--task)}.setup-more p{font-size:12px;line-height:1.5;margin:4px 0 10px}
.setup-primary{display:flex;justify-content:center;align-items:center;width:100%;min-height:40px;border:0;border-radius:6px;background:#f2f2f3;color:#161618;font:inherit;font-size:12px;cursor:pointer}
.setup-primary:focus-visible,.plain-button:focus-visible,.setup-close:focus-visible,summary:focus-visible{outline:2px solid var(--agent);outline-offset:3px}
@media(max-width:1199px){.side{order:0;width:100%;border-top:1px solid var(--line);border-bottom:0}#activity>summary{padding:14px 15px;cursor:pointer;list-style:disclosure-closed}#activity[open]>summary{list-style:disclosure-open}}
@media(max-width:620px){.context-line{flex-direction:column;gap:3px;font-size:11px}.bar{gap:8px}.bar .brand{width:100%;margin-bottom:2px}.rules{flex-wrap:wrap;overflow:visible}.rule{max-width:100%;font-size:11px}.trow[data-label]{margin-top:16px}.tree{padding-top:16px}.sub{padding-left:24px}.tcol{min-width:0}.ag-h{gap:7px}.st{font-size:10px}.mo{font-size:11px}.ft{font-size:11px}.setup-body{padding:20px}.setup-dialog header{padding:16px 20px}.setup-dialog h2{font-size:16px}}
@media(max-width:620px){.side{order:-1;border-top:0;border-bottom:1px solid var(--line)}}
</style></head>
<body><main>
<section class="panel" aria-label="kyma">
  <h1 class="sr">Your AI’s past activity</h1>
  <div class="bar">
    <span class="brand"><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0c.4 3.9 2.1 5.6 6 6-3.9.4-5.6 2.1-6 6-.4-3.9-2.1-5.6-6-6 3.9-.4 5.6-2.1 6-6Z" transform="translate(0 2)"/></svg>kyma</span>
    <button class="flag stop" id="g-stop" hidden aria-pressed="false"><svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" aria-hidden="true"><path d="M6 1.6l4.6 8.2H1.4z"/><path d="M6 5v2" stroke-linecap="round"/></svg><b></b> actions would be blocked</button>
    <button class="flag ask" id="g-ask" hidden aria-pressed="false"><svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><circle cx="6" cy="6" r="4.5"/><path d="M6 3.6V6l1.6 1"/></svg><b></b> would need permission</button>
    <button class="flag rulef" id="g-rule" hidden aria-label="Clear rule filter"><span></span><svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6"/></svg></button>
    <span class="spacer"></span>
    <button class="chipbtn" id="refresh-open" aria-haspopup="dialog">Refresh report</button>
    <span class="sr" id="live" aria-live="polite"></span>
    <span id="cmdslot"></span>
  </div>
  <div class="context-line"><span id="past-note"></span><span id="date-range"></span></div>
  <div class="live-note" id="live-note" hidden></div>
  <div class="scan-scope" id="scan-scope" hidden><span class="scope-tag">Recent sample</span><span id="scan-count"></span><button class="chipbtn" id="scan-all">Scan all history</button></div>
  <p class="coverage" id="coverage" hidden></p>
  <h2 class="sr">Filter past attempts</h2>
  <div class="rules" id="rules" hidden role="group" aria-label="Your rules"></div>
  <h2 class="sr">Agents</h2>
  <div class="split">
  <section class="tree" id="tree" aria-label="Agents">
    <div class="troot" id="troot" role="list" aria-label="This machine"></div>
    <div id="trows" role="list" aria-label="Sessions"></div>
    <div class="more-row" id="tmore" hidden><button class="chipbtn" id="tmore-b"></button><span class="older mono" id="tmore-o" hidden></span></div>
  </section>
  <aside class="side">
  <section class="inspector" id="inspector" aria-labelledby="event-title">
    <header class="inspect-head"><h2 id="event-title">Selected attempt</h2><div class="inspect-nav"><button class="icon" id="event-prev" aria-label="Previous attempt">‹</button><span class="mono" id="event-position"></span><button class="icon" id="event-next" aria-label="Next attempt">›</button></div></header>
    <div class="inspect-source"><span class="tile" id="event-glyph"></span><div><strong id="event-agent"></strong><span id="event-model"></span><span id="event-project"></span></div></div>
    <div class="inspect-arrow" id="event-action"></div>
    <div class="inspect-artifact"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6"/></svg><code id="event-target"></code></div>
    <div class="inspect-outcome"><span id="event-outcome">Outcome unknown</span><time id="event-time"></time></div>
    <details class="inspect-evidence" open><summary id="event-evidence-title">Command &amp; tool result</summary><code id="event-command" tabindex="0"></code><p id="event-result-note">This report records the attempt. It does not include the tool result.</p></details>
    <div class="inspect-arrow" id="event-rule-owner"></div>
    <div class="inspect-verdict" id="event-verdict"><strong id="event-result"></strong><span id="event-rule"></span></div>
    <button class="setup-primary" id="setup-open" aria-haspopup="dialog">Set up Claude Code checks</button>
  </section>
  <details id="activity"><summary>Activity by hour</summary>
  <div class="lane mono">
    <span class="count"><span class="dot" style="background:var(--you)"></span><b id="f-t"></b>hours with your prompts</span>
    <span class="count"><span class="dot" style="background:var(--agent)"></span><b id="f-o"></b>hours without your prompts</span>
    <span class="count" id="held-fact" hidden><span class="ring vstop" id="f-hs-r"></span><b id="f-hs"></b><span id="f-hs-t">would stop</span><span class="ring vask" id="f-ha-r" style="margin-left:.55rem"></span><b id="f-ha"></b><span id="f-ha-t">would ask</span></span>
    <button class="count lanebtn" id="away-fact" hidden aria-pressed="false"><span class="ring" style="border-color:var(--away)"></span><b id="f-aw"></b>matches without a prompt that hour</button>
    <span class="count" id="live-fact" hidden><span class="ring live"></span><b id="f-lv"></b>stopped</span>
    <span class="count" id="ask-fact" hidden><span class="ring live"></span><b id="f-la"></b>asked you</span>
    <span class="spacer"></span>
    <button class="icon" id="replay" aria-label="Replay" title="Replay"><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5 3.2v9.6c0 .5.5.8.9.5l7.3-4.8c.4-.3.4-.8 0-1L5.9 2.7c-.4-.3-.9 0-.9.5z"/></svg></button>
    <button class="icon" id="save" aria-label="Save image" title="Save image"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2v8M4.5 6.8 8 10.3l3.5-3.5M2.5 13.5h11"/></svg></button>
  </div>
  <p class="chart-note">Each dot is an active clock hour, not an hour of work. A ring marks a rule match.</p>
  <div class="stage" id="stage" tabindex="0" aria-label="Hours, by day. Arrow keys step through what would have been held; Enter opens it."><div class="yax" id="yax" aria-hidden="true"></div><canvas id="c" role="img" aria-label="Active clock hours by day, with and without your prompts, and rule matches" aria-describedby="sr"></canvas><div id="tip" class="mono" aria-hidden="true"></div></div>
  <p id="sr" class="sr"></p>
  </details>
  </aside>
  </div>
</section>
<footer class="local-note"><span>Local report · Nothing uploaded</span><a href="https://www.kyma.stream/clearance" target="_blank" rel="noopener noreferrer">Contract review from $1,000 ↗</a></footer>
<dialog class="setup-dialog" id="refresh-dialog" aria-labelledby="refresh-title">
<header><h2 id="refresh-title">Refresh your activity</h2><button class="setup-close" id="refresh-close" aria-label="Close refresh">×</button></header>
<div class="setup-body"><p>Open a terminal outside your agent conversation. Paste this command and press Enter.</p><div class="setup-command"><code id="refresh-command"></code><button class="plain-button" id="refresh-copy" aria-label="Copy report command">Copy</button></div><p class="setup-done" id="refresh-feedback" aria-live="polite"></p><details id="refresh-help"><summary>Command not found? Start with Python</summary><p>Requires Git and Python 3.9 or later.</p><div class="setup-command"><code id="refresh-python-command"></code><button class="plain-button" id="refresh-python-copy" aria-label="Copy Python setup command">Copy</button></div><p class="setup-done" id="refresh-python-feedback" aria-live="polite"></p></details></div></dialog>
<dialog class="setup-dialog" id="setup-dialog" aria-labelledby="setup-dialog-title">
<header><h2 id="setup-dialog-title">Turn rules on in Claude Code</h2><button class="setup-close" id="setup-close" aria-label="Close setup">×</button></header>
<div class="setup-body">
<fieldset class="setup-scopes" id="setup-scopes"><legend>Where rules apply</legend><label><input type="radio" name="setup-scope" value="project"> <span id="setup-project-label">This project</span></label><label><input type="radio" name="setup-scope" value="global"> All projects</label></fieldset>
<p id="setup-scope">All Claude Code projects on this computer. Codex stays report-only.</p>
<section class="setup-rules" aria-labelledby="setup-rules-title"><h3 id="setup-rules-title"></h3><div class="setup-rule-status" id="setup-rule-status" hidden></div><ul id="setup-rules-list"></ul></section>
<ol>
<li><span class="setup-step" aria-hidden="true">1</span>Open a new terminal, outside your Claude conversation.</li>
<li><span class="setup-step" aria-hidden="true">2</span><section id="setup-recovery" hidden><h3>Claude Code has disabled these checks</h3><div id="setup-recovery-files"></div></section><span id="setup-action">Paste this command and press Enter.</span><div class="setup-command"><code id="setup-command"></code><button class="plain-button" id="setup-copy" aria-label="Copy setup command">Copy</button></div>
<p class="setup-done" id="setup-feedback" aria-live="polite"></p>
<div class="setup-success" id="setup-success">Success shows <strong>“On.”</strong> and <strong>“The hook answered its self-test.”</strong></div></li>
</ol>
<details class="setup-more" id="setup-edit"><summary>Edit rules</summary><div id="setup-rule-files"></div><p>Need rules from customer contracts? <a href="https://www.kyma.stream/clearance" target="_blank" rel="noopener noreferrer">Kyma contract review</a> starts at $1,000 for up to 25 agreement sets. Local checks stay free.</p></details>
<details class="setup-more"><summary>Check setup &amp; refresh this report</summary><p>Claude Code normally loads the change automatically. This command checks the rules and opens a fresh report.</p><div class="setup-command"><code id="setup-check-command"></code><button class="plain-button" id="setup-check-copy" aria-label="Copy check and refresh command">Copy</button></div><p class="setup-done" id="setup-check-feedback" aria-live="polite"></p></details>
<details class="setup-more"><summary>Turn rules off</summary><p id="setup-off-scope"></p><div class="setup-command"><code id="setup-off-command"></code><button class="plain-button" id="setup-off-copy" aria-label="Copy turn-off command">Copy</button></div><p class="setup-done" id="setup-off-feedback" aria-live="polite"></p></details>
<button class="setup-primary" id="setup-return">Back to report</button>
</div></dialog>
</main>
<script>
const D = __DATA__;
if (D.example) { const badge = document.createElement("div"); badge.className = "example-badge"; badge.textContent = "Example activity · fictional data"; document.querySelector("main").prepend(badge); }
if (location.hash.includes("still")) document.documentElement.classList.add("still");
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const fmt = n => n.toLocaleString();
const day0 = new Date(D.first + "T00:00:00");
const dateOf = i => new Date(day0.getFullYear(), day0.getMonth(), day0.getDate() + i);
const short = d => d.toLocaleDateString(undefined, {day: "numeric", month: "short"});
const long = d => d.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"});
const hr = h => (h % 12 || 12) + (h < 12 ? "am" : "pm");
const at = (i, h) => dateOf(i).toLocaleDateString(undefined, {weekday: "short", day: "numeric", month: "short"}) + " · " + hr(h);
$("f-t").textContent = fmt(D.together); $("f-o").textContent = fmt(D.alone);
const M = (D.marks || []).filter(m => !m.undated && m.i != null && m.h != null);
$("past-note").textContent = D.checked_calls ? `Past actions checked against ${D.yours ? "your" : "starter"} rules. This check stopped nothing.` : "No actions checked yet.";
$("event-rule-owner").textContent = D.yours ? "↓  matched your rule" : "↓  matched a starter rule";
const datedActivity = (D.actions || 0) > (D.undated_actions || 0);
$("date-range").textContent = datedActivity ? short(day0) + " – " + long(new Date(D.today + "T00:00:00")) : "Dates not recorded";
$("activity").hidden = !datedActivity;
const liveReceipt = [];
if (D.held_live) liveReceipt.push(`${fmt(D.held_live)} actually stopped`);
if (D.asked_live) liveReceipt.push(`${fmt(D.asked_live)} required permission`);
if (liveReceipt.length) { $("live-note").hidden = false; $("live-note").textContent = "Live protection recorded: " + liveReceipt.join(" · ") + "."; }
const markAt = {}; for (const m of M) { const k = m.i * 24 + m.h; if (!markAt[k] || m.live) markAt[k] = m; }
$("sr").textContent = `${fmt(D.actions)} tool calls from ${long(day0)} to ${long(new Date(D.today + "T00:00:00"))}: ${fmt(D.together)} active clock hours with your prompts, ${fmt(D.alone)} active clock hours without your prompts` +
  (D.held_past ? `, ${fmt(D.held_past)} would have been held` : "") + (D.held_live ? `, ${fmt(D.held_live)} stopped` : "") + ".";
if (D.held_live) { $("live-fact").hidden = false; $("f-lv").textContent = fmt(D.held_live); }
if (D.asked_live) { $("ask-fact").hidden = false; $("f-la").textContent = fmt(D.asked_live); }
{ const away = D.away_past || 0;
  if (away && D.held_past) { $("away-fact").hidden = false; $("f-aw").textContent = fmt(away); } }
if (D.held_past) { $("held-fact").hidden = false;
  for (const [k, n] of [["hs", D.stop_past], ["ha", D.ask_past]]) { $("f-" + k).textContent = fmt(n || 0); for (const x of ["f-" + k, "f-" + k + "-r", "f-" + k + "-t"]) $(x).hidden = !n; }
}
const scope = [];
if (D.quick && D.scope) {
  $("scan-scope").hidden = false;
  const size = D.scope.selected_bytes < 1048576 ? "<1 MB" : `${Math.ceil(D.scope.selected_bytes / 1048576)} MB`;
  $("scan-count").textContent = `${fmt(D.scope.selected_files)} of ${fmt(D.scope.available_files)} logs · ${size}`;
  $("scan-count").title = "Newest logs within the first-run size limit. Larger and older logs remain available through Scan all history.";
}
if (D.undated_actions) scope.push(`${fmt(D.undated_actions)} ${D.undated_actions === 1 ? "action has" : "actions have"} no recorded time`);
if (D.legacy_kept) scope.push(`${fmt(D.legacy_kept)} retained log snapshots use legacy call counts`);
if (D.judged_of && (D.judged < D.judged_of || D.partial_logs)) {
  scope.push(`${fmt(D.checked_calls || 0)} actions replayed · ${fmt(D.judged)} complete` +
    (D.partial_logs ? ` + ${fmt(D.partial_logs)} partial` : "") + ` of ${fmt(D.judged_of)} available logs`);
}
if (D.marks_total > (D.marks || []).length) scope.push(`${fmt((D.marks || []).length)} of ${fmt(D.marks_total)} moments shown`);
const unsupportedRules = (D.rules || []).filter(r => !r.ok).length;
if (unsupportedRules) scope.push(`${fmt(unsupportedRules)} rules could not be evaluated`);
if (scope.length) { $("coverage").hidden = false; $("coverage").textContent = scope.join(" · "); }
let lit = null, one = null;
function light(rule, mark) { lit = rule; one = mark; render(drawn, null);
  for (const r of document.querySelectorAll(".rule")) r.classList.toggle("on", rule != null && r.dataset.r === rule); }
// Every rule you have, with what it would have held. A rule at zero is still
// shown: it is the one you would otherwise wonder about.

// ---------------------------------------------------------------- the agents
// Who did the work: each session an agent, the subagents it started under it,
// and what your rules would have held pinned to the one that did it. The
// evidence sits on the card itself; a card's colour is the worst thing in it
// or anything it started.
const AG = D.agents || [];
const actionNames = {
  "Never read my .env files.": ["Private files", "Tried to read a private file"],
  "Never read credentials or .env files.": ["Private files", "Tried to read a private file"],
  "Ask me before any git push.": ["Code uploads", "Tried to upload code changes"],
  "Ask me before sending any email.": ["Email", "Tried to send email"],
  "Ask me before setting anything to run on a schedule or at startup.": ["Scheduled tasks", "Tried to schedule a task"],
  "Never use sudo.": ["Admin access", "Tried to use administrator access"]
};
const receipts = [];
const collectReceipts = (a, root, parent) => { for (const h of a.held || []) receipts.push({a, h, root, parent}); for (const k of a.children || []) collectReceipts(k, root, a); };
function firstAttempt(roots) {
  const visit = (a, root, parent) => {
    if (a.attempts?.length) return {a, root, parent, attempt:a.attempts[0]};
    for (const child of a.children || []) { const found = visit(child, root, a); if (found) return found; }
    return null;
  };
  for (const root of roots) { const found = visit(root, root, null); if (found) return found; }
  return null;
}
AG.forEach(a => collectReceipts(a, a, null)); receipts.sort((a,b) => b.h[0].localeCompare(a.h[0]));
let selectedReceipt = receipts[0] || null, selectedRoot = selectedReceipt?.root, receiptOptions = receipts;
const targetOf = h => {
  const category = actionNames[h[2]]?.[0];
  if (category === "Private files") { const m = /^(?:cat|Read)\s+(?:["']([^"']+)["']|([^\s-][^\s]*))\s*$/.exec(h[3] || ""); return m ? (m[1] || m[2]) : "Private file"; }
  if (category === "Email" && /^gog\s+gmail\s+send\s/.test(h[3] || "")) {
    const m = /(?:^|\s)--to(?:=|\s+)(?:"([^"]+)"|'([^']+)'|([^\s]+))/.exec(h[3]);
    const address = m && (m[1] || m[2] || m[3]);
    if (address && /^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$/.test(address)) return address;
  }
  return {"Code uploads":"Code changes", "Email":"Email", "Scheduled tasks":"Scheduled task", "Admin access":"Administrator access"}[category] || "Tool action";
};
// First-party identification assets and provenance: docs/agent-marks.md.
const GLYPH = {
  unknown: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="#a7a7b0" stroke-width="1.3"><rect x="3" y="4" width="10" height="9" rx="2"/><path d="M8 1.5V4M5.5 8h.01M10.5 8h.01M6 10.5h4" stroke-linecap="round"/></svg>',
  claude: "<svg class=\"claude-mark\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 248 248\" fill=\"none\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M52.4285 162.873L98.7844 136.879L99.5485 134.602L98.7844 133.334H96.4921L88.7237 132.862L62.2346 132.153L39.3113 131.207L17.0249 130.026L11.4214 128.844L6.2 121.873L6.7094 118.447L11.4214 115.257L18.171 115.847L33.0711 116.911L55.485 118.447L71.6586 119.392L95.728 121.873H99.5485L100.058 120.337L98.7844 119.392L97.7656 118.447L74.5877 102.732L49.4995 86.1905L36.3823 76.62L29.3779 71.7757L25.8121 67.2858L24.2839 57.3608L30.6515 50.2716L39.3113 50.8623L41.4763 51.4531L50.2636 58.1879L68.9842 72.7209L93.4357 90.6804L97.0015 93.6343L98.4374 92.6652L98.6571 91.9801L97.0015 89.2625L83.757 65.2772L69.621 40.8192L63.2534 30.6579L61.5978 24.632C60.9565 22.1032 60.579 20.0111 60.579 17.4246L67.8381 7.49965L71.9133 6.19995L81.7193 7.49965L85.7946 11.0443L91.9074 24.9865L101.714 46.8451L116.996 76.62L121.453 85.4816L123.873 93.6343L124.764 96.1155H126.292V94.6976L127.566 77.9197L129.858 57.3608L132.15 30.8942L132.915 23.4505L136.608 14.4708L143.994 9.62643L149.725 12.344L154.437 19.0788L153.8 23.4505L150.998 41.6463L145.522 70.1215L141.957 89.2625H143.994L146.414 86.7813L156.093 74.0206L172.266 53.698L179.398 45.6635L187.803 36.802L193.152 32.5484H203.34L210.726 43.6549L207.415 55.1159L196.972 68.3492L188.312 79.5739L175.896 96.2095L168.191 109.585L168.882 110.689L170.738 110.53L198.755 104.504L213.91 101.787L231.994 98.7149L240.144 102.496L241.036 106.395L237.852 114.311L218.495 119.037L195.826 123.645L162.07 131.592L161.696 131.893L162.137 132.547L177.36 133.925L183.855 134.279H199.774L229.447 136.524L237.215 141.605L241.8 147.867L241.036 152.711L229.065 158.737L213.019 154.956L175.45 145.977L162.587 142.787H160.805V143.85L171.502 154.366L191.242 172.089L215.82 195.011L217.094 200.682L213.91 205.172L210.599 204.699L188.949 188.394L180.544 181.069L161.696 165.118H160.422V166.772L164.752 173.152L187.803 207.771L188.949 218.405L187.294 221.832L181.308 223.959L174.813 222.777L161.187 203.754L147.305 182.486L136.098 163.345L134.745 164.2L128.075 235.42L125.019 239.082L117.887 241.8L111.902 237.31L108.718 229.984L111.902 215.452L115.722 196.547L118.779 181.541L121.58 162.873L123.291 156.636L123.14 156.219L121.773 156.449L107.699 175.752L86.304 204.699L69.3663 222.777L65.291 224.431L58.2867 220.768L58.9235 214.27L62.8713 208.48L86.304 178.705L100.44 160.155L109.551 149.507L109.462 147.967L108.959 147.924L46.6977 188.512L35.6182 189.93L30.7788 185.44L31.4156 178.115L33.7079 175.752L52.4285 162.873Z\" fill=\"#D97757\" /></svg>",
  codex: "<svg class=\"codex-mark\" xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 716 716\" fill=\"none\" aria-hidden=\"true\" focusable=\"false\"><path d=\"M508.749 317.399C516.777 287.314 508.991 253.884 485.389 230.282C461.788 206.681 428.36 198.895 398.273 206.923C376.231 184.928 343.39 174.956 311.148 183.596C278.906 192.234 255.45 217.292 247.36 247.361C217.291 255.451 192.233 278.91 183.595 311.149C174.957 343.391 184.927 376.232 206.924 398.274C198.896 428.359 206.683 461.789 230.284 485.391C253.885 508.992 287.313 516.779 317.401 508.75C339.442 530.745 372.286 540.717 404.525 532.079C436.767 523.441 460.223 498.384 468.313 468.315C498.383 460.224 523.44 436.766 532.078 404.526C540.716 372.285 530.747 339.443 508.749 317.402V317.399ZM470.899 244.776C486.892 260.77 493.488 282.601 490.687 303.412L415.577 260.046C412.411 258.218 408.509 258.218 405.345 260.046L317.401 310.82V277.526C317.401 275.191 318.652 273.005 320.676 271.837L387.644 233.174C414.178 218.353 448.346 222.223 470.901 244.776H470.899ZM357.837 311.144L398.275 334.491V381.185L357.837 404.532L317.398 381.185V334.491L357.837 311.144ZM264.776 269.693C265.207 239.305 285.644 211.649 316.453 203.393C338.3 197.54 360.505 202.744 377.127 215.573L302.014 258.937C298.848 260.764 296.898 264.144 296.898 267.798V369.346L268.065 352.699C266.043 351.531 264.776 349.353 264.776 347.017V269.691V269.693ZM203.391 316.454C209.244 294.608 224.854 277.978 244.276 269.999V356.73C244.276 360.384 246.226 363.763 249.392 365.591L337.337 416.365L308.503 433.013C306.481 434.181 303.961 434.188 301.939 433.02L234.971 394.357C208.868 378.789 195.138 347.261 203.391 316.454ZM244.775 470.9C228.781 454.906 222.186 433.075 224.986 412.264L300.096 455.63C303.263 457.457 307.164 457.457 310.328 455.63L398.273 404.856V438.149C398.273 440.485 397.022 442.671 394.997 443.839L328.029 482.502C301.495 497.322 267.327 493.452 244.772 470.9H244.775ZM450.897 445.982C450.466 476.371 430.029 504.027 399.22 512.283C377.373 518.136 355.168 512.932 338.547 500.102L413.659 456.738C416.826 454.911 418.775 451.532 418.775 447.877V346.329L447.609 362.977C449.631 364.145 450.897 366.323 450.897 368.659V445.985V445.982ZM512.282 399.221C506.429 421.068 490.819 437.697 471.397 445.676V358.946C471.397 355.292 469.448 351.912 466.281 350.085L378.336 299.311L407.17 282.663C409.192 281.495 411.712 281.487 413.734 282.655L480.702 321.318C506.805 336.887 520.536 368.415 512.282 399.221Z\" fill=\"white\" /></svg>",
  home: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="#74b6f9" stroke-width="1.4" stroke-linejoin="round"><rect x="2.5" y="3.5" width="11" height="7.5" rx="1.3"/><path d="M6 13.5h4M8 11v2.5"/></svg>'};
Object.assign(GLYPH, __PROVIDER_MARKS__);
const ICON = {
  done: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.3l2.2 2.2 4.8-5"/></svg>',
  off: '',
  on: '<svg viewBox="0 0 12 12" fill="currentColor"><circle cx="6" cy="6" r="3.2"/></svg>',
  run: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M6 1.5a4.5 4.5 0 1 1-4.5 4.5"/></svg>',
  ask: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="6" cy="6" r="4.5"/><path d="M6 3.6V6l1.6 1"/></svg>',
  stop: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><path d="M6 1.6l4.6 8.2H1.4z"/><path d="M6 5v2" stroke-linecap="round"/></svg>',
  chev: '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5l3 3 3-3"/></svg>'};
const kindName = k => (!k || k === "subagent") ? "Agent" : k === "general-purpose" ? "General" : k;
const hostName = a => ({claude:"Claude Code", codex:"Codex"}[a.agent] || "Agent");
function providerOf(a) {
  const identities = a.identities?.length ? a.identities : [a];
  const providers = identities.map(i => {
    const raw = (i.model_id || i.model || "").toLowerCase();
    const model = raw.replace(/^(anthropic|openai|google|deepseek|xai|mistral|meta-llama|qwen)\//, "");
    if (/^(claude-|opus\b|sonnet\b|haiku\b)/.test(model)) return "anthropic";
    if (/^(gpt-|chatgpt-|o[134](?:-|$))/.test(model)) return "openai";
    if (/^gemini/.test(model)) return "gemini";
    if (/^gemma/.test(model)) return "google";
    if (/^deepseek/.test(model)) return "deepseek";
    if (/^grok/.test(model)) return "xai";
    if (/^(mistral|mixtral|codestral|devstral|ministral)/.test(model)) return "mistral";
    if (/^(llama|meta-llama)/.test(model)) return "meta";
    if (/^qwen/.test(model)) return "qwen";
    return (i.provider || "unknown").toLowerCase();
  });
  return new Set(providers).size === 1 ? providers[0] : "unknown";
}
const glyphFor = a => GLYPH[({anthropic:"claude", openai:"codex"}[providerOf(a)] || providerOf(a))] || GLYPH.unknown;
const effortName = value => value ? value[0].toUpperCase() + value.slice(1) : "";
function displayModel(value) {
  const raw = value || "";
  const known = raw.replace(/^(?:google|deepseek|qwen|meta-llama)\//i, "");
  const match = /^(gemini|deepseek|qwen\d*|llama|grok)-([a-z0-9.-]+)$/i.exec(known);
  if (!match) return raw;
  const family = {gemini:"Gemini", deepseek:"DeepSeek", llama:"Llama", grok:"Grok"}[match[1].toLowerCase()] || match[1].replace(/^qwen/i, "Qwen");
  const suffix = match[2].split("-").map(part => /^[rv]\d+$|^\d+b$/i.test(part) ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1));
  return [family, ...suffix].join(" ");
}
function modelParts(a) {
  const identities = a.identities?.length ? a.identities : [a];
  const models = [...new Set(identities.map(i => i.model_id || i.model || ""))];
  const efforts = [...new Set(identities.map(i => i.effort || ""))];
  return [models.length > 1 ? "Mixed models" : displayModel(identities[0].model) || "Model not recorded",
    efforts.length > 1 ? "Mixed effort" : effortName(efforts[0])];
}
function modelLabel(a, exact = false) {
  const [model, effort] = modelParts(a);
  return [model, effort || (exact ? "Effort not recorded" : "")].filter(Boolean).join(" · ");
}
function identityTitle(a) {
  return (a.identities?.length ? a.identities : [a]).map(i => modelLabel(i, true) + (i.model_id ? ` [${i.model_id}]` : "")).join("\n");
}
function showActor(a, actor, helper) {
  const exact = actor || {}, [model, effort] = modelParts(exact);
  $("event-glyph").innerHTML = glyphFor(exact);
  $("event-glyph").title = hostName(a);
  $("event-agent").textContent = model + (helper ? " · helper" : "");
  $("event-model").textContent = effort ? effort + " effort" : "Effort not recorded";
  $("event-model").title = actor?.model_id || "";
}
const deep = a => (a.held || []).concat(...(a.children || []).map(deep));
const RANK = {stop: 3, ask: 2, run: 1, done: 0};
function stateOf(a) {
  const h = deep(a);
  if (h.some(x => x[1] === "block")) return ["stop", "Would block"];
  if (h.some(x => x[1] === "ask")) return ["ask", "Would ask"];
  if (a.live || (a.children || []).some(k => k.live)) return ["run", "Recent log"];
  return ["done", "No match"];
}
// A card's pill: what this agent itself did, or "Via <subagent>" when the call was
// one it started. The call is shown once, on the agent that made it.
function pillOf(a) {
  const own = a.held || [];
  if (own.some(x => x[1] === "block")) return ["stop", `${own.length} ${own.length === 1 ? "match" : "matches"}`];
  if (own.some(x => x[1] === "ask")) return ["ask", `${own.length} ${own.length === 1 ? "match" : "matches"}`];
  const kid = (a.children || []).find(k => deep(k).length);
  if (kid) return [stateOf(kid)[0] + " via", "Helper match"];
  if (a.live || (a.children || []).some(k => k.live)) return ["run", "Recent log"];
  return ["done", "No match"];
}
// No start or end in the log: say nothing rather than "<1m".
const dur = a => !(a.start && a.end) ? "" : a.mins >= 60 ? Math.round(a.mins / 60) + "h" : (a.mins ? a.mins + "m" : "<1m");
const dayOf = a => a.end ? new Date(a.end).toLocaleDateString(undefined, {day: "numeric", month: "short"}) : "";
const when = k => { if (!k) return "Time not recorded"; const d = new Date(k.slice(0, 10) + "T00:00:00"), h = +k.slice(11, 13);
  return d.toLocaleDateString(undefined, {weekday: "short", day: "numeric", month: "short"}) + " · " + hr(h); };
const cellOf = k => { if (!k) return [NaN, NaN]; const d = new Date(k.slice(0, 10) + "T00:00:00"); return [Math.round((d - day0) / 864e5), +k.slice(11, 13)]; };
const isAway = h => { if (!h[0]) return false; const [i, hh] = cellOf(h[0]); return !(D.Y[i] || [])[hh]; };
function evidence(h, by) {
  const e = el("div", "ev artifact-chip");
  e.append(el("span", "ring " + (h[1] === "block" ? "vstop" : "vask")), el("code", "", targetOf(h)));
  return e;
}
function card(a, kind, count) {
  const c = el("div", "ag"); c.setAttribute("role", "listitem"); c.tabIndex = -1;
  // On only when the hook will run: disableAllHooks turns it off however it is installed.
  const [pill, label] = kind === "root" ? (D.hooks_off ? ["stop", "Rules disabled here"] : D.on ? ["on", "Rules on"] : ["off", "Rules off"]) : pillOf(a);
  const st = kind === "root" ? pill : stateOf(a)[0];
  c.dataset.st = st;
  // A subagent with no type of its own goes by its model; its task sits under it.
  const gen = kind === "sub" && kindName(a.kind) === "Agent";
  const name = kind === "root" ? (D.example ? "Example computer" : "This computer") : a.task || (kind === "sub" ? kindName(a.kind) : (a.project || hostName(a)));
  const held = kind === "root" ? [] : deep(a);
  const opens = kind === "root" ? false : (held.length > 0 || (a.attempts || []).length > 0 || !!(a.start && a.end));
  if (opens) c.classList.add("can");
  c.innerHTML = `<div class="ag-h"><span class="tile">${kind === "root" ? GLYPH.home : glyphFor(a)}</span>` +
    `<div class="tt"><div class="ti"></div><div class="mo"></div></div><span class="st ${pill}">${ICON[pill.split(" ")[0]]}<span></span></span></div>` +
    `<div class="task"></div><div class="evs"></div><div class="ft"><span class="mono"></span></div>`;
  const ti = c.querySelector(".ti"), text = name + (count > 1 ? "  ×" + count : "");
  if (opens) {
    const b = el("button", "ob", text); b.type = "button"; b.setAttribute("aria-expanded", "false");
    b.setAttribute("aria-label", [name, kind === "root" ? "" : hostName(a), kind === "root" ? "" : identityTitle(a), a.task !== name ? a.task : "", label].filter(Boolean).join(", "));
    b.onclick = e => { e.stopPropagation(); toggleOpen(a, c, kind); };
    ti.append(b);
  } else ti.textContent = text;
  c.querySelector(".mo").textContent = kind === "root" ? (D.on_scope === "global" ? "All Claude Code projects" : D.on_scope === "project" ? "Project: " + D.on_project : "") : modelLabel(a);
  if (kind !== "root") { c.querySelector(".mo").title = identityTitle(a); c.querySelector(".tile").title = hostName(a); }
  if (!c.querySelector(".mo").textContent) c.querySelector(".mo").remove();
  c.querySelector(".st span").textContent = label;
  const task = c.querySelector(".task");
  if (kind === "root") { task.remove();
    if (D.claude === false) c.querySelector(".evs").append(el("div", "ev-result", "Report only")); }
  else if (!a.task || a.task === name) task.remove();
  else task.textContent = a.task;
  const ft = c.querySelector(".ft span");
  if (kind === "root") {
    const calls = D.checked_calls || 0, sessions = D.sessions || AG.length;
    ft.append(el("b", "", fmt(calls)), (calls === 1 ? " action" : " actions") + " checked · ", el("b", "", fmt(sessions)), sessions === 1 ? " session" : " sessions");
    c.classList.add("root");
  } else {
    const ownDay = (a.held || [])[0]?.[0] ? dateOf(cellOf(a.held[0][0])[0]).toLocaleDateString(undefined, {day: "numeric", month: "short"}) : dayOf(a);
    ft.append(el("b", "", fmt(a.calls)), (a.calls === 1 ? " action" : " actions") + [kind === "session" ? ownDay : ""].filter(Boolean).map(x => " · " + x).join(""));
    // the first thing it (or something it started) did that a rule would have met, on the card
    // the call is shown once, on the agent that made it; a parent wears its subagents' state in the pill
    const own = a.held || [];
    if (own[0]) c.querySelector(".evs").append(evidence(own[0], ""));
    if (own.length > 1) c.querySelector(".evs").append(el("div", "ev-more mono", "+" + (own.length - 1)));
  }
  if (opens) c.addEventListener("click", e => { if (!e.target.closest("button, input, details")) toggleOpen(a, c, kind); });
  c.addEventListener("pointerenter", () => lightAgent(a));
  c.addEventListener("pointerleave", () => lightAgent(null));
  c.addEventListener("focusin", () => lightAgent(a));
  c.addEventListener("focusout", e => { if (!c.contains(e.relatedTarget)) lightAgent(null); });
  c._a = a;
  return c;
}
// Identical runs side by side read as one card with a count.
function merged(list) {
  const out = [];
  for (const k of list) {
    const key = [k.agent, k.kind, k.task, stateOf(k)[0], identityTitle(k)].join("|");
    const m = out.find(x => x.key === key && !deep(k).length);
    if (m) m.n++; else out.push({key, a: k, n: 1});
  }
  return out;
}
const expandedHelpers = new Set();
function column(a, kind = "session") {
  const col = el("div", kind === "session" ? "tcol" : "branch"); col._a = a; col.setAttribute("role", "presentation"); const c = card(a, kind); c.setAttribute("role", "listitem"); col.append(c);
  const kids = (a.children || []).filter(k => (!filter && !ruleOn) || passes(k)).map(a => ({a, n:1}));
  if (kids.length) {
    const sub = el("div", "sub"); sub.setAttribute("role", "list"); sub.id = "sub-" + Math.random().toString(36).slice(2, 9);
    c.setAttribute("aria-owns", sub.id);
    sub.setAttribute("aria-label", "Helpers started by " + (a.project || kindName(a.kind)));
    sub.append(el("div", "sub-label", `Started ${kids.length} ${kids.length === 1 ? "helper" : "helpers"}`));
    // the ones a rule met first; a run that fanned out to 200 shows 8 and the rest on request
    kids.sort((x, y) => RANK[stateOf(y.a)[0]] - RANK[stateOf(x.a)[0]]);
    const SHOW = expandedHelpers.has(a) ? kids.length : 8;
    for (const k of kids.slice(0, SHOW)) sub.append(column(k.a, "sub"));
    if (kids.length > SHOW) {
      const more = el("button", "chipbtn", "+" + fmt(kids.length - SHOW)); more.type = "button";
      more.setAttribute("aria-label", `Show ${kids.length - SHOW} more subagents of ${a.project || "this session"}`);
      more.onclick = e => { e.stopPropagation(); expandedHelpers.add(a); more.remove();
        const added = kids.slice(SHOW).map(k => column(k.a, "sub")); sub.append(...added); reveal(); wire();
        (added[0].querySelector(".ob") || added[0]).focus(); };
      sub.append(more);
    }
    const quiet = [...sub.children].filter(x => x.classList.contains("branch") && !deep(x._a).length);
    const n = kids.filter(k => !deep(k.a).length).reduce((x, k) => x + k.n, 0), who = a.project || "this session";
    if (n) {
      const t = el("button", "kids"); t.type = "button"; t.setAttribute("aria-expanded", "true");
      const named = open => t.setAttribute("aria-label", `${open ? "Hide" : "Show"} ${n} subagent${n === 1 ? "" : "s"} of ${who}`);
      named(true);
      t.innerHTML = `<span>${n} ${n === 1 ? "helper" : "helpers"}</span>` + ICON.chev;
      t.onclick = e => { e.stopPropagation(); const open = t.getAttribute("aria-expanded") === "true";
        t.setAttribute("aria-expanded", String(!open)); named(!open);
        for (const x of quiet) x.hidden = open;
        wire(); };
      c.querySelector(".ft").append(t);
    }
    col.append(sub);
  }
  return col;
}
// Sessions where something would have been held come first: that is the news.
// What is running now comes first, then what your rules would have met, then the rest.
const isLive = a => !!(a.live || (a.children || []).some(k => k.live));
const awayIn = a => deep(a).some(isAway);
const ALL = AG.map((a, i) => [a, i]).sort((x, y) => (isLive(y[0]) - isLive(x[0])) ||
  RANK[stateOf(y[0])[0]] - RANK[stateOf(x[0])[0]] || (awayIn(y[0]) - awayIn(x[0])) || x[1] - y[1]).map(x => x[0]);
let filter = null, showAll = false, ruleOn = null;
const passes = a => (!filter || (filter === "away" ? awayIn(a) : stateOf(a)[0] === filter)) && (!ruleOn || deep(a).some(h => h[2] === ruleOn));
function attemptTitle(attempt) {
  const command = attempt.command.replace(/^[ \t]+|[ \t]+$/g, "");
  if (attempt.command_clipped || !["Bash", "shell", "exec_command"].includes(attempt.tool) || /[\n;&|<>`$]/.test(command)) return "Recorded attempt";
  const names = [
    [/^git[ \t]+commit[ \t]+-m[ \t]+(?:'[^'\\]*'|"[^"\\]*"|[\w.,:/@%+=][\w.,:/@%+=-]*)$/, "Save code changes locally"],
    [/^git[ \t]+status(?:[ \t]+--short)?$/, "Check changed files"],
    [/^git[ \t]+diff$/, "Compare file changes"],
    [/^npm[ \t]+(?:run[ \t]+)?test$/, "Run the test script"],
    [/^npm[ \t]+run[ \t]+build$/, "Run the build script"]
  ];
  return names.find(([pattern]) => pattern.test(command))?.[1] || "Recorded attempt";
}
function showReceipt() {
  const entry = selectedReceipt;
  const ordinary = !!entry?.attempt;
  const options = ordinary ? entry.a.attempts : receiptOptions;
  for (const node of document.querySelectorAll("#inspector > .inspect-source, #inspector > .inspect-arrow, #inspector > .inspect-artifact, #inspector > .inspect-verdict, #inspector > .inspect-outcome, #inspector > .inspect-evidence")) node.hidden = !entry;
  $("event-title").textContent = entry ? "Selected attempt" : D.checked_calls ? "No rule matches" : "No actions checked yet";
  $("event-position").textContent = entry ? `${options.indexOf(ordinary ? entry.attempt : entry) + 1} / ${options.length}` : "";
  for (const id of ["event-prev", "event-next"]) $(id).disabled = options.length < 2;
  for (const card of document.querySelectorAll("#trows .ag, #trows .qrow")) {
    const chosen = !!entry && card._a === entry.a; card.classList.toggle("focused", chosen);
    if (deep(card._a).length) { const b = card.querySelector(".ob"); b?.removeAttribute("aria-expanded"); b?.setAttribute("aria-pressed", String(chosen)); }
  }
  if (!entry) return;
  $("event-verdict").classList.toggle("ordinary", ordinary);
  if (ordinary) {
    const {a, attempt, parent} = entry;
    const title = attemptTitle(attempt);
    $("event-title").textContent = title;
    showActor(a, attempt.actor, parent);
    $("event-project").textContent = a.task || a.project || "Session";
    $("event-action").textContent = "↓  " + (title === "Recorded attempt" ? attempt.tool : "attempted command");
    $("event-target").textContent = attempt.command.split("\n")[0].slice(0, 90) || attempt.tool;
    $("event-rule-owner").textContent = "↓  This session";
    $("event-result").textContent = "No recorded rule match";
    $("event-rule").textContent = "No match appears in this session’s checked activity.";
    $("event-verdict").classList.remove("ask");
    $("event-command").textContent = attempt.command;
    $("event-evidence-title").textContent = attempt.command_clipped ? "Command excerpt" : "Command";
    $("event-time").textContent = "";
    const result = attempt.status === "tool_succeeded" ? "Tool reported success" : attempt.status === "tool_failed" ? "Tool reported failure" : null;
    $("event-outcome").textContent = result || "Outcome unknown";
    $("event-result-note").textContent = result ? result + ". External outcome not verified." : "This recorded input has no linked tool result in the report.";
    return;
  }
  const {a, h, root, parent} = entry, category = actionNames[h[2]]?.[0];
  $("event-title").textContent = {"Private files":"File read attempt", "Code uploads":"Code upload attempt", "Email":"Email attempt", "Scheduled tasks":"Scheduled task attempt", "Admin access":"Administrator access attempt"}[category] || "Selected attempt";
  showActor(a, h[4]?.actor, parent);
  $("event-project").textContent = a.task || root.task || root.project || "Session";
  $("event-action").textContent = "↓  " + ({"Private files":"tried to read", "Code uploads":"tried to upload", "Email":"tried to send", "Scheduled tasks":"tried to create", "Admin access":"tried to use"}[category] || "attempted");
  $("event-target").textContent = targetOf(h);
  $("event-result").textContent = h[1] === "block" ? "Would block" : "Would ask your permission";
  $("event-verdict").classList.toggle("ask", h[1] !== "block");
  $("event-rule").textContent = h[2];
  $("event-rule-owner").textContent = D.yours ? "↓  matched your rule" : "↓  matched a starter rule";
  $("event-command").textContent = h[4]?.command || h[3] || "Command not retained";
  $("event-evidence-title").textContent = h[4]?.command_clipped ? "Command excerpt & tool result" : h[4]?.command ? "Command & tool result" : "Matched fragment & tool result";
  $("event-time").textContent = when(h[0]);
  const result = h[4]?.status === "tool_succeeded" ? "Tool reported success" : h[4]?.status === "tool_failed" ? "Tool reported failure" : null;
  $("event-outcome").textContent = result || "Outcome unknown";
  $("event-result-note").textContent = result ? result + ". External outcome not verified." : "This report records the attempt. It does not include the tool result.";
}
function selectReceipt(entry) {
  selectedReceipt = entry; selectedRoot = entry.root;
  const card = [...document.querySelectorAll("#trows .ag, #trows .qrow")].find(c => c._a === entry.a && c.getBoundingClientRect().height);
  if (card) showReceipt(); else {
    const path = a => { if (a === entry.a || (a.children || []).some(path)) { expandedHelpers.add(a); return true; } return false; };
    path(entry.root); buildTree();
  }
  lightAgent(entry.a);
  $("live").textContent = [$("event-title").textContent, $("event-target").textContent, $("event-result").textContent, $("event-outcome").textContent].join(". ");
  if (matchMedia("(max-width: 1199px)").matches) {
    requestAnimationFrame(() => $("inspector").scrollIntoView({block:"start", behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"}));
  }
}
for (const [id, step] of [["event-prev", -1], ["event-next", 1]]) $(id).onclick = () => {
  if (selectedReceipt?.attempt) {
    const e = selectedReceipt, options = e.a.attempts;
    selectReceipt({...e, attempt:options[(options.indexOf(e.attempt) + step + options.length) % options.length]});
    return;
  }
  if (!receiptOptions.length) return;
  selectReceipt(receiptOptions[(receiptOptions.indexOf(selectedReceipt) + step + receiptOptions.length) % receiptOptions.length]);
};
// The same breakpoint as the stylesheet: a phone gets one column.
function perRow() { return matchMedia("(max-width: 620px)").matches ? 1 : Math.max(1, Math.min(4, Math.floor(($("tree").clientWidth - 54 + 18) / 266))); }
function buildTree() {
  closeOpen();
  $("troot").replaceChildren(card({}, "root"));
  const rows = $("trows"); rows.replaceChildren();
  const list = ALL.filter(passes);
  receiptOptions = receipts.filter(e => list.includes(e.root) && (!ruleOn || e.h[2] === ruleOn) && (!filter || (filter === "away" ? isAway(e.h) : (e.h[1] === "block") === (filter === "stop"))));
  if (!receiptOptions.includes(selectedReceipt) && !(selectedReceipt?.attempt && list.includes(selectedReceipt.root) && !filter && !ruleOn)) { selectedReceipt = receiptOptions[0] || null; selectedRoot = selectedReceipt?.root; }
  if (!selectedReceipt && !filter && !ruleOn) { selectedReceipt = firstAttempt(list); selectedRoot = selectedReceipt?.root; }
  if (selectedRoot && list.includes(selectedRoot)) { list.splice(list.indexOf(selectedRoot), 1); list.unshift(selectedRoot); }
  const n = perRow(), flagged = list.filter(a => RANK[stateOf(a)[0]] >= 2 || isLive(a)).length;
  // what your rules would have met is never behind "+N"
  const first = n;
  const shown = showAll ? list.length : Math.min(list.length, first);
  const groupOf = a => isLive(a) ? "run" : stateOf(a)[0];
  let row = null, rowGroup = null, inRow = 0, quiet = null;
  for (const [ix, a] of list.slice(0, shown).entries()) {
    const g = groupOf(a);
    if (g === "done" && ix >= first && !(a.children || []).length) {
      if (!quiet) { quiet = el("div", "quiet"); quiet.setAttribute("role", "list"); }
      const q = el("div", "qrow"); q._a = a; q.setAttribute("role", "listitem");
      const qt = el("span", "qt"); const mark = el("span", "tile"); mark.innerHTML = glyphFor(a); mark.title = hostName(a);
      qt.append(mark, el("span", "", a.project || hostName(a)), el("i", "", modelLabel(a))); qt.title = identityTitle(a);
      const when = a.end || a.start;
      const inspect = el("button", "qk ob", a.task || "Inspect actions"); inspect.type = "button";
      inspect.setAttribute("aria-label", "Inspect actions: " + (a.task || a.project || "session"));
      inspect.setAttribute("aria-expanded", "false"); inspect.onclick = () => toggleOpen(a, q, "session");
      q.append(qt, inspect, el("span", "qm mono", fmt(a.calls || 0) + " calls" + (when ? " · " + short(new Date(when)) : "")));
      quiet.append(q); continue;
    }
    if (!row || g !== rowGroup || inRow >= n) {
      const first = g !== rowGroup;
      row = el("div", "trow"); row.setAttribute("role", "presentation"); row.dataset.g = g;
      if (first) { const k = list.slice(0, shown).filter(x => groupOf(x) === g).length;
        row.dataset.label = ({stop: "Would block", ask: "Would ask permission", run: "Recent activity", done: "No rule match"}[g] || g);
        const lab = el("div", "glab mono " + g, row.dataset.label); lab.setAttribute("aria-hidden", "true"); rows.append(lab); }
      rows.append(row); rowGroup = g; inRow = 0;
    }
    row.append(column(a)); inRow++;
  }
  if (quiet) rows.append(quiet);
  const left = list.length - shown;
  const older = !filter && !ruleOn ? Math.max(0, (D.sessions || 0) - AG.length) : 0;
  const fewer = showAll && !filter && !ruleOn && list.length > first;
  $("tmore").hidden = left <= 0 && !older && !fewer;
  $("tmore-b").hidden = left <= 0 && !fewer; $("tmore-b").textContent = left > 0 ? "Show " + fmt(left) + " more sessions" : "Show fewer";
  $("tmore-b").setAttribute("aria-label", left > 0 ? `Show ${left} more sessions` : "Show fewer sessions");
  $("tmore-o").hidden = left > 0 || !older;
  $("tmore-o").textContent = older ? fmt(older) + " older " + (older === 1 ? "session" : "sessions") + " not shown" : "";
  for (const r of document.querySelectorAll(".rule")) r.classList.toggle("out",
    (filter === "stop" && r.dataset.v !== "block") || (filter === "ask" && r.dataset.v !== "ask"));
  { const gr = $("g-rule"), what = ruleOn || ({away: "without a prompt that hour", stop: "would stop", ask: "would ask"}[filter] || "");
    gr.hidden = !what; gr.querySelector("span").textContent = what; gr.setAttribute("aria-label", what ? "Clear filter: " + what : "Clear filter"); }
  recount(list);
  reveal(); wire(true);
  showReceipt();
  try { render(drawn, null); } catch (e) { /* the picture is drawn after the tree on first load */ }
  if (filter || ruleOn) $("live").textContent = `${fmt(list.length)} ${list.length === 1 ? "session" : "sessions"} shown`;
  return shown;
}
$("tmore-b").onclick = () => {
  if ($("tmore-b").textContent === "Show fewer") { showAll = false; buildTree(); $("tree").scrollIntoView({block: "start"}); $("tmore-b").focus({preventScroll: true}); return; }
  const y = scrollY, before = document.querySelectorAll("#trows > .trow > .tcol").length;
  showAll = true; buildTree(); scrollTo(0, y);
  const first = document.querySelectorAll("#trows > .trow > .tcol")[before]?.firstChild;
  if (first) { (first.querySelector(".ob") || first).focus({preventScroll: true}); }
};
function reveal() {
  const fresh = [...document.querySelectorAll(".ag:not(.in)")];
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.classList.contains("still");
  const step = Math.min(30, 600 / Math.max(1, fresh.length));
  fresh.forEach((c, k) => still ? c.classList.add("in") : setTimeout(() => c.classList.add("in"), step * k));
}
// The wires sit under the cards: a dot under each parent, a bus to the row,
// rounded elbows into each child; on a phone, only the spines to subagents.
function wire(grow) {
  const tree = $("tree"); tree.querySelector("svg.wires")?.remove();
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.classList.contains("still");
  const box = tree.getBoundingClientRect(), sx = tree.scrollLeft;
  const pos = e => { const r = e.getBoundingClientRect(); return {l: r.left - box.left + sx, t: r.top - box.top, w: r.width, h: r.height}; };
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "wires"); svg.setAttribute("width", tree.scrollWidth); svg.setAttribute("height", tree.scrollHeight);
  const path = (d, hot) => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("fill", "none");
    p.setAttribute("stroke", hot === "stop" ? "#c4583f" : hot === "ask" ? "#b98232" : "#45464d"); p.setAttribute("stroke-width", hot ? "1.8" : "1.4");
    if (grow && !calm) { p.setAttribute("pathLength", "1"); p.style.strokeDasharray = "1"; p.style.strokeDashoffset = "1"; p.classList.add("draw");
      requestAnimationFrame(() => requestAnimationFrame(() => { p.style.strokeDashoffset = "0"; })); }
    svg.append(p); };
  const dot = (x, y) => { const c = document.createElementNS(NS, "circle"); c.setAttribute("cx", x); c.setAttribute("cy", y);
    c.setAttribute("r", 4); c.setAttribute("fill", "#17181b"); c.setAttribute("stroke", "#5a5b63"); c.setAttribute("stroke-width", "1.4"); svg.append(c); };
  const rootC = $("troot").firstChild; if (!rootC) return;
  const narrow = matchMedia("(max-width: 620px)").matches;
  const R = pos(rootC), rx = R.l + R.w / 2, ry = R.t + R.h;
  if (!narrow) {
    // the trunk runs down a gutter left of the cards; each row hangs off it, named where its group starts
    const rowsEl = [...document.querySelectorAll("#trows .trow")].filter(r => r.children.length);
    const lone = rowsEl.length === 1 && rowsEl[0].children.length === 1 ? rowsEl[0].firstChild.firstChild : null;
    if (lone) {
      const t = pos(lone), cx = t.l + t.w / 2;
      path(`M${rx} ${ry} V${t.t - 22} H${cx} V${t.t}`, RANK[lone.dataset.st] >= 2 ? lone.dataset.st : null); dot(rx, ry);
    } else if (rowsEl.length) {
      const gx = Math.min(...rowsEl.map(r => pos(r.firstChild.firstChild).l)) - 16, r = 8;
      let lastBy = ry;
      rowsEl.forEach(row => {
        const cards = [...row.children].map(col => col.firstChild), tops = cards.map(pos), by = tops[0].t - 22;
        const far = Math.max(...tops.map(t => t.l + t.w / 2));
        path(`M${gx} ${by - r} Q${gx} ${by} ${gx + r} ${by} H${far}`);
        tops.forEach((t, k) => path(`M${t.l + t.w / 2} ${by} V${t.t}`, RANK[cards[k].dataset.st] >= 2 ? cards[k].dataset.st : null));
        if (row.dataset.label) {
          const tx = document.createElementNS(NS, "text"); tx.setAttribute("x", gx + 12); tx.setAttribute("y", by + 15);
          tx.setAttribute("class", "glabel " + row.dataset.g); tx.textContent = row.dataset.label; svg.append(tx);
        }
        lastBy = by;
      });
      path(`M${rx} ${ry} V${ry + 14} H${gx + r} Q${gx} ${ry + 14} ${gx} ${ry + 14 + r} V${lastBy - r}`);
      dot(rx, ry);
    }
  }
  document.querySelectorAll("#trows .tcol, #trows .branch").forEach(col => {
    const sub = col.querySelector(":scope > .sub"); if (!sub || sub.hidden || !col.getBoundingClientRect().height) return;
    const P = pos(col.firstChild), x = P.l + 26, top = P.t + P.h;
    const kids = [...sub.children].filter(k => k.classList.contains("branch") && !k.hidden).map(k => k.firstChild);
    if (!kids.length) return;
    const ks = kids.map(k => { const K = pos(k); return {y: K.t + Math.min(22, K.h / 2), l: K.l, st: k.dataset.st}; });
    path(`M${x} ${top} V${ks[ks.length - 1].y - 8}`);
    ks.forEach(k => path(`M${x} ${k.y - 8} Q${x} ${k.y} ${x + 8} ${k.y} H${k.l}`, RANK[k.st] >= 2 ? k.st : null));
    dot(x, top);
  });
  tree.prepend(svg);
}
// A card opens in place: every moment it would have held, with when.
let openCard = null, openFrom = null;
function closeOpen(back) {
  if (!openCard) return;
  openCard.querySelector(".all")?.remove(); openCard.classList.remove("open");
  const c = openCard; openCard = null; lightAgent(null); wire();
  const b = c.querySelector(".ob"); if (b) b.setAttribute("aria-expanded", "false");
  if (back && openFrom === "stage") $("stage").focus();
  else if (back && b) b.focus();
  openFrom = null;
}
function toggleOpen(a, c, kind) {
  const matched = receipts.find(e => deep(a).includes(e.h) && receiptOptions.includes(e));
  if (matched) { selectReceipt(matched); return; }
  if (openCard === c) { closeOpen(true); return; }
  closeOpen();
  const held = kind === "root" ? [] : (a.held || []);
  const box = el("div", "all");
  if (kind === "root") {
    box.append(cmdChip());
  } else if (held.length) {
    for (const h of held.slice(0, 12)) {
      const row = evidence(h, ""); row.append(el("div", "ev-t mono", when(h[0]))); box.append(row);
    }
    if (held.length > 12) box.append(el("div", "ev-more mono", "+" + (held.length - 12)));
    // the hook goes into Claude Code; a Codex session is read, not gated

  } else if ((a.attempts || []).length || (a.start && a.end)) {
    const attempts = a.attempts || [];
    if (attempts.length) {
      const contains = node => node === a || (node.children || []).some(contains);
      const root = AG.find(contains) || a;
      const entry = attempt => ({a, root, parent:root !== a, attempt});
      selectReceipt(entry(attempts[0]));
      box.append(el("div", "ev-t mono", attempts.length < a.calls ? `First ${attempts.length} recorded attempts` : "Recorded attempts"));
      for (const attempt of attempts) {
        const detail = el("details", "ev-extra");
        detail.append(el("summary", "", attempt.command.split("\n")[0].slice(0, 90) || attempt.tool));
        detail.querySelector("summary").onclick = () => selectReceipt(entry(attempt));
        detail.append(el("code", "attempt-command", attempt.command));
        if (attempt.command_clipped) detail.append(el("p", "", "Command excerpt · 4,096 characters retained"));
        box.append(detail);
      }
    }
    if (a.start && a.end) {
    // nothing held: when it ran, and its hours lit in the picture
    const f = new Date(a.start), t = new Date(a.end);
    const day = d => d.toLocaleDateString(undefined, {weekday: "short", day: "numeric", month: "short"});
    const tm = d => (d.getHours() % 12 || 12) + ":" + String(d.getMinutes()).padStart(2, "0") + (d.getHours() < 12 ? "am" : "pm");
    const nb = x => x.replace(/ /g, "\u00a0");
    const span = nb(day(f) + " · " + tm(f)) + " → " + nb((day(t) === day(f) ? "" : day(t) + " · ") + tm(t));
    box.append(el("div", "ev-t mono", span));
    }
  } else {
    return;
  }
  c.insertBefore(box, c.querySelector(".ft")); c.classList.add("open"); openCard = c;   // same order, open or shut
  c.querySelector(".ob")?.setAttribute("aria-expanded", "true");
  lightAgent(a); wire();
}
addEventListener("keydown", e => {
  if (e.key !== "Escape" || $("setup-dialog").open) return;
  if (openCard) closeOpen(true);
  else if (ruleOn) { const t = ruleOn; setRule(null); document.querySelector(`.rule[data-r="${CSS.escape(t)}"]`)?.focus(); }
  else if (filter) { const was = filter; filter = null; showAll = false;
    for (const x of ["g-stop", "g-ask", "away-fact"]) $(x).setAttribute("aria-pressed", "false");
    buildTree(); ({stop: $("g-stop"), ask: $("g-ask"), away: $("away-fact")})[was]?.focus(); }
});
// The one action: a command you paste. Its state changes where you clicked it.
function cmdChip() {
  const b = el("button", "go", D.on && !D.hooks_off ? "Manage rules" : "Turn rules on");
  b.type = "button"; b.id = "setup-open"; b.setAttribute("aria-haspopup", "dialog");
  b.onclick = e => { e.stopPropagation(); $("setup-dialog").showModal(); };
  return b;
}
// One rule at a time narrows the tree and lights its moments in the picture; the header shows it and clears it.
function setRule(t) {
  ruleOn = t; showAll = !!t;
  if (t && filter) {
    const v = (RL.find(r => r.t === t) || {}).v;
    if ((filter === "stop" && v !== "block") || (filter === "ask" && v !== "ask") ||
        (filter === "away" && !ALL.some(a => awayIn(a) && deep(a).some(h => h[2] === t)))) {
      filter = null; for (const x of ["g-stop", "g-ask", "away-fact"]) $(x).setAttribute("aria-pressed", "false");
    }
  }
  for (const x of document.querySelectorAll(".rule[aria-pressed]")) x.setAttribute("aria-pressed", String(x.dataset.r === t));
  light(t, null); buildTree();
}
$("away-fact").onclick = () => { filter = filter === "away" ? null : "away"; showAll = filter !== null;
  $("away-fact").setAttribute("aria-pressed", String(filter === "away"));
  for (const x of ["g-stop", "g-ask"]) $(x).setAttribute("aria-pressed", "false");
  buildTree(); $("tree").scrollIntoView({block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}); };
$("g-rule").onclick = () => {
  if (ruleOn) { const t = ruleOn; setRule(null); document.querySelector(`.rule[data-r="${CSS.escape(t)}"]`)?.focus(); return; }
  if (filter) { const b = ({away: $("away-fact"), stop: $("g-stop"), ask: $("g-ask")})[filter]; b.click(); b.focus(); } };
// The header counts what the tree shows: under a filter, the filtered cards.
function recount(list) {
  for (const [id, n, label] of [["g-stop", D.stop_past || 0, "actions would be blocked"], ["g-ask", D.ask_past || 0, "actions would need permission"]]) {
    const b = $(id); b.hidden = !n; b.querySelector("b").textContent = fmt(n);
    if (id === "g-stop") b.lastChild.textContent = n === 1 ? " action would be blocked" : " actions would be blocked";
    b.setAttribute("aria-label", `${fmt(n)} past ${n === 1 ? label.replace("actions", "action") : label}`);
  }
}
// The header's flags filter the tree to what they count.
(function header() {
  // Global action totals stay fixed while filters select their source sessions.
  const every = []; const walk = a => { every.push(a); (a.children || []).forEach(walk); }; AG.forEach(walk);
  const own = (a, v) => (a.held || []).some(h => h[1] === v);
  const stop = D.stop_past || 0, ask = D.ask_past || 0;
  const chip = (id, n, st) => {
    const b = $(id); if (!n) return; b.hidden = false; b.querySelector("b").textContent = fmt(n);
    b.setAttribute("aria-label", `${fmt(n)} agents ${st === "stop" ? "would stop" : "would ask"}`);
    b.onclick = () => { filter = filter === st ? null : st; showAll = filter !== null;
      if (filter && ruleOn && !ALL.some(a => stateOf(a)[0] === filter && deep(a).some(h => h[2] === ruleOn))) setRule(null);
      for (const x of ["g-stop", "g-ask"]) $(x).setAttribute("aria-pressed", String(filter === (x === "g-stop" ? "stop" : "ask")));
      $("away-fact").setAttribute("aria-pressed", "false");
      buildTree(); };
  };
  chip("g-stop", stop, "stop"); chip("g-ask", ask, "ask");

})();
// A card and the picture point at the same moments.
let litCells = null, litSpan = false;
// The hours a session ran, as cells of the picture: where it sits in your days.
function spanCells(a) {
  const out = new Set();
  if (!a || !a.start || !a.end) return out;
  const s = new Date(a.start), e = new Date(a.end);
  if (isNaN(s) || isNaN(e)) return out;
  for (let t = new Date(s.getFullYear(), s.getMonth(), s.getDate(), s.getHours()), k = 0; t <= e && k < 240; t = new Date(t.getTime() + 36e5), k++) {
    const i = Math.round((new Date(t.getFullYear(), t.getMonth(), t.getDate()) - day0) / 864e5);
    out.add(i + "," + t.getHours());
  }
  return out;
}
function lightAgent(a) {
  const held = a ? deep(a) : [];
  const names = new Set(held.map(h => h[2]));
  for (const r of document.querySelectorAll(".rule")) r.classList.toggle("on", names.has(r.dataset.r) || (ruleOn === r.dataset.r));
  litSpan = !!a && !held.length;
  litCells = a ? (held.length ? new Set(held.filter(h => h[0]).map(h => cellOf(h[0]).join(","))) : spanCells(a)) : null;
  if (litCells && !litCells.size) litCells = null;
  render(drawn, null);
}
const RL = D.rules || [];
if (RL.length) {
  const box = $("rules"); box.hidden = false;
  box.append(el("span", "filter-label", D.yours ? "Your rules · attempts" : "Starter rules · attempts"));
  box.setAttribute("aria-label", D.yours ? "Your rules" : "Starter rules");
  box.title = D.yours ? "~/.kyma/RULES.md" : "Starter rules; kyma on writes them to ~/.kyma/RULES.md";
  const SHOWN = 10, extra = [];
  for (const [ri, r] of [...RL].sort((x, y) => y.n - x.n).entries()) {
    const row = el(r.n ? "button" : "div", "rule" + (r.n ? "" : " zero")); row.dataset.r = r.t;
    if (ri >= SHOWN) { row.hidden = true; extra.push(row); }
    if (r.n) { row.type = "button"; row.setAttribute("aria-pressed", "false");
      row.setAttribute("aria-label", `${actionNames[r.t]?.[0] || r.t}: ${fmt(r.n)} past ${r.n === 1 ? "attempt" : "attempts"}, would ${r.v === "block" ? "block" : "ask permission"}`);
      row.onclick = () => setRule(ruleOn === r.t ? null : r.t); }
    const g = el("span", r.ok ? "ring " + (r.v === "block" ? "vstop" : r.v === "ask" ? "vask" : "") : ""); if (!r.ok) g.style.cssText = "width:9px;height:9px";
    row.dataset.v = r.v;
    const t = el("span", "txt", actionNames[r.t]?.[0] || r.t); if (r.w) row.title = r.w;
    if (!r.ok) t.append(el("span", "pill", "not understood"));
    row.append(g, t, el("span", "n mono", r.ok ? fmt(r.n) : "–"));
    if (r.live) row.append(el("span", "live-n mono", `${fmt(r.live)} ${r.v === "block" ? "stopped" : "asked"}`));
    if (r.ok && !r.w) row.title = `${fmt(r.n)} ${r.n === 1 ? "call" : "calls"} would ${r.v === "block" ? "stop" : "ask"} in the replay` +
      (r.live ? ` · ${fmt(r.live)} ${r.v === "block" ? "stopped" : "asked"} by the live hook` : "");
    box.append(row);
    const dim = on => document.querySelectorAll("#trows .ag").forEach(c => c.classList.toggle("dim", on && !deep(c._a).some(h => h[2] === r.t)));
    row.addEventListener("pointerenter", () => { light(r.t, null); dim(r.n > 0); }); row.addEventListener("pointerleave", () => { light(ruleOn, null); dim(false); });
    row.addEventListener("focus", () => { light(r.t, null); dim(r.n > 0); }); row.addEventListener("blur", () => { light(ruleOn, null); dim(false); });
  }
  if (extra.length) {
    const more = el("button", "rule zero", "+" + fmt(extra.length)); more.type = "button";
    more.setAttribute("aria-expanded", "false"); more.setAttribute("aria-label", `${fmt(extra.length)} more rules`);
    more.onclick = () => { const open = more.getAttribute("aria-expanded") !== "true";
      extra.forEach(x => { x.hidden = !open; }); more.setAttribute("aria-expanded", String(open));
      more.textContent = open ? "Show fewer" : "+" + fmt(extra.length); box.append(more); };
    more.style.cursor = "pointer"; box.append(more);
  }
}
let peak = 1; for (const r of D.A) for (const v of r) if (v > peak) peak = v;
const LT = Math.log1p(peak);
const cv = $("c"), ctx = cv.getContext("2d");
const field = document.createElement("canvas"), fx = field.getContext("2d");
let W, H, L = 38, R = 4, T = 22, B = 24, cw, rh, dpr, FS = 10;
function layout() {
  if (!$("activity").open) return;
  dpr = Math.min(2, window.devicePixelRatio || 1);
  // A phone gets a picture it can pan, not one squeezed into dust.
  const avail = $("stage").clientWidth - 2 * parseFloat(getComputedStyle($("stage")).paddingLeft);
  // beside the tree the picture fits its column and stands taller; alone, a phone pans it
  const side = matchMedia("(min-width: 1200px)").matches;
  W = side ? avail : Math.max(avail, Math.min(D.days * (avail < 620 ? 2.5 : 6) + L + R, 720));
  cv.style.width = W + "px";
  // beside the tree the picture fills the column down to the window's foot, on the first screen and once it sticks
  const above = side ? Math.max(0, $("stage").getBoundingClientRect().top) : 0;
  H = Math.round(side ? Math.max(380, Math.min(980, innerHeight - above - 24)) : Math.max(300, Math.min(520, avail * (avail < 620 ? .95 : .42))));
  cv.style.height = H + "px";
  for (const c of [cv, field]) { c.width = W * dpr; c.height = H * dpr; }
  for (const x of [ctx, fx]) x.setTransform(dpr, 0, 0, dpr, 0, 0);
  cw = (W - L - R) / D.days; rh = (H - T - B) / 24;
  $("stage").scrollLeft = $("stage").scrollWidth;      // a narrow screen opens on today, and pans back
  const yax = $("yax"); yax.replaceChildren();
  if (W > avail + 1) for (const [h, t] of [[0, "6am"], [6, "12pm"], [12, "6pm"], [18, "12am"]]) {
    const s = el("span", "", t); s.style.top = (T + h * rh + rh / 2) + "px"; yax.append(s); }
}
const row = h => (h + 18) % 24;      // 6am at the top; the night is one band below the day
const X = i => L + (i + .5) * cw, Y = h => T + (row(h) + .5) * rh;
function chipAt(g, x, y, text, bg, fg, align) {
  g.font = FS + "px ui-monospace,Menlo,monospace";
  const w = g.measureText(text).width + 10, h = FS + 8;
  let x0 = align === "right" ? x - w : x - w / 2; x0 = Math.max(L, Math.min(W - R - w, x0));
  g.fillStyle = bg; g.beginPath(); g.roundRect ? g.roundRect(x0, y - h / 2, w, h, 4) : g.rect(x0, y - h / 2, w, h); g.fill();
  g.fillStyle = fg; g.textBaseline = "middle"; g.fillText(text, x0 + 5, y + .5); g.textBaseline = "alphabetic";
}
function frame(g, under) {
  if (under) { g.fillStyle = under; g.fillRect(0, 0, W, H); } else g.clearRect(0, 0, W, H);
  g.font = FS + "px ui-monospace,Menlo,monospace"; g.textBaseline = "middle";
  [[0, "6am"], [6, "12pm"], [12, "6pm"], [18, "12am"]].forEach(([h, t]) => {
    g.fillStyle = "#26262a"; g.fillRect(L, T + h * rh, W - L - R, 1);
    g.fillStyle = "#838385"; g.fillText(t, 0, T + h * rh + rh / 2);
  });
  g.textBaseline = "alphabetic";
  const years = dateOf(0).getFullYear() !== dateOf(D.days - 1).getFullYear();
  const months = D.days > 45;
  g.font = FS + "px ui-monospace,Menlo,monospace";
  let last = -1e9; const stop = W - R - g.measureText("today").width - 18;
  for (let i = 0; i < D.days; i++) {
    const d = dateOf(i);
    const tick = months ? (d.getDate() === 1 || i === 0) : (d.getDay() === 1 || i === 0);
    if (!tick) continue;
    const x = L + i * cw;
    const t = months ? d.toLocaleDateString(undefined, years && (d.getMonth() === 0 || i === 0) ? {month: "short", year: "numeric"} : {month: "short"})
                     : d.toLocaleDateString(undefined, {day: "numeric", month: "short"});
    const tw = g.measureText(t).width;
    if (x - last > tw + FS && x + tw <= stop) { g.fillStyle = "#838385"; g.fillText(t, x, H - 6); last = x; }
  }
  chipAt(g, W - R, H - 6 - FS / 2 + 1, "today", "#153253", "#74b6f9", "right");
}
function dots(g, i, glow) {
  const base = Math.min(cw, rh);
  for (let h = 0; h < 24; h++) {
    const a = D.A[i][h], y = D.Y[i][h];
    if (a && !y) {
      const v = Math.log1p(a) / LT;
      g.shadowColor = "rgba(80,143,219,.9)"; g.shadowBlur = 3 + 7 * v;
      g.fillStyle = `rgba(116,182,249,${(.28 + .72 * v) * glow})`;
      g.beginPath(); g.arc(X(i), Y(h), Math.max(.8, base * (.16 + .30 * v)), 0, 7); g.fill();
    }
    if (y) {
      const v = a ? Math.log1p(a) / LT : .3;
      g.shadowColor = "rgba(255,160,70,.95)"; g.shadowBlur = 6 + 8 * v;
      g.fillStyle = `rgba(255,184,110,${.95 * glow})`;
      g.beginPath(); g.arc(X(i), Y(h), Math.max(1, base * (.22 + .22 * v)), 0, 7); g.fill();
    }
  }
  for (let h = 0; h < 24; h++) {
    const m = markAt[i * 24 + h]; if (!m) continue;
    const rr = Math.max(2.8, base * .62);
    g.shadowBlur = 0; g.fillStyle = "#141416"; g.beginPath(); g.arc(X(i), Y(h), rr + 1.2, 0, 7); g.fill();
    g.shadowColor = "rgba(255,111,145,1)"; g.shadowBlur = m.live ? 14 : 8;
    g.beginPath(); g.arc(X(i), Y(h), rr, 0, 7);
    if (m.live) { g.fillStyle = "rgba(255,120,150,1)"; g.fill(); }
    else { g.strokeStyle = "rgba(255,130,160,1)"; g.lineWidth = 2; g.stroke(); }
  }
  g.shadowBlur = 0;
}
let raf = 0, drawn = 0;
function render(upto, sweep) {
  if (!W || !H) return;
  ctx.clearRect(0, 0, W, H);
  ctx.drawImage(field, 0, 0, W, H);
  if (sweep != null) {
    const x = L + sweep * cw;
    const grd = ctx.createLinearGradient(x - 60, 0, x, 0);
    grd.addColorStop(0, "rgba(116,182,249,0)"); grd.addColorStop(1, "rgba(116,182,249,.10)");
    ctx.fillStyle = grd; ctx.fillRect(x - 60, T, 60, H - T - B);
    ctx.fillStyle = "rgba(116,182,249,.7)"; ctx.fillRect(x, T, 1, H - T - B);
    chipAt(ctx, x, T / 2, short(dateOf(Math.min(D.days - 1, sweep))), "#153253", "#74b6f9");
  }
  if (filter && !lit && !litCells) {
    // the header's filter: its marks stay, the rest step back
    ctx.save(); ctx.fillStyle = "rgba(23,24,28,.55)"; ctx.fillRect(L, T, W - L - R, H - T - B);
    ctx.strokeStyle = filter === "stop" ? "rgba(240,122,94,1)" : filter === "ask" ? "rgba(240,168,69,1)" : "rgba(183,156,255,1)"; ctx.lineWidth = 2;
    for (const m of M) if (filter === "away" ? !m.live && !(D.Y[m.i] || [])[m.h] : (m.v === "block") === (filter === "stop")) {
      ctx.beginPath(); ctx.arc(X(m.i), Y(m.h), Math.max(4, Math.min(cw, rh) * .7), 0, 7); ctx.stroke(); }
    ctx.restore();
  }
  if (litCells && !lit) {
    // A card's moments in the picture: the rest steps back.
    ctx.save(); ctx.fillStyle = "rgba(23,24,28,.55)"; ctx.fillRect(L, T, W - L - R, H - T - B);
    ctx.shadowColor = litSpan ? "rgba(116,182,249,1)" : "rgba(255,111,145,1)"; ctx.shadowBlur = 14;
    ctx.strokeStyle = litSpan ? "rgba(150,200,250,1)" : "rgba(255,150,175,1)"; ctx.lineWidth = 2.2;
    for (const k of litCells) { const [i, h] = k.split(",").map(Number);
      if (i >= 0 && i < D.days) { ctx.beginPath(); ctx.arc(X(i), Y(h), Math.max(4, Math.min(cw, rh) * .75), 0, 7); ctx.stroke(); } }
    ctx.restore();
  }
  if (lit) {
    // What a rule holds lights up; everything else steps back.
    ctx.save(); ctx.fillStyle = "rgba(27,27,30,.55)"; ctx.fillRect(L, T, W - L - R, H - T - B);
    ctx.shadowColor = "rgba(255,111,145,1)"; ctx.shadowBlur = 14;
    ctx.strokeStyle = "rgba(255,150,175,1)"; ctx.lineWidth = 2.2;
    for (const m of M) if (m.r === lit && (!one || (m.i === one.i && m.h === one.h))) {
      ctx.beginPath(); ctx.arc(X(m.i), Y(m.h), Math.max(4, Math.min(cw, rh) * .75), 0, 7); ctx.stroke(); }
    ctx.restore();
    if (one) chipAt(ctx, X(one.i), T / 2, at(one.i, one.h), "#3a1c26", "#ff9cb4");
  }
}
function play() {
  cancelAnimationFrame(raf); layout(); frame(fx); drawn = 0;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || location.hash.includes("still");
  if (still) { for (let i = 0; i < D.days; i++) dots(fx, i, 1); drawn = D.days; render(D.days, null); return; }
  const dur = Math.min(9000, Math.max(3000, D.days * 28)); const t0 = performance.now();
  const ease = t => 1 - Math.pow(1 - t, 2.2);
  const tick = now => {
    const p = Math.min(1, (now - t0) / dur), upto = Math.floor(ease(p) * D.days);
    while (drawn < upto) dots(fx, drawn++, 1);
    render(upto, p < 1 ? upto : null);
    if (p < 1) raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
}
const tip = $("tip");
function tipAt(e) {
  if (drawn < D.days) return;
  const bb = cv.getBoundingClientRect(), x = e.clientX - bb.left, y = e.clientY - bb.top;
  const i = Math.floor((x - L) / cw), r = Math.floor((y - T) / rh), h = (r + 6) % 24;
  if (i < 0 || i >= D.days || r < 0 || r > 23) { tip.style.opacity = 0; return; }
  const a = D.A[i][h], yy = D.Y[i][h], m = markAt[i * 24 + h];
  tip.replaceChildren();
  const t = el("div", "t");
  if (a || yy) { const d = el("span", "dot"); d.style.background = yy ? "var(--you)" : "var(--agent)"; t.append(d); }
  t.append(at(i, h) + (a ? " · " + fmt(a) + (a === 1 ? " call" : " calls") : ""));
  tip.append(t);
  if (m) { const rr = el("div", "r"); rr.append(el("span", "ring" + (m.live ? " live" : m.v === "block" ? " vstop" : " vask")), el("span", "", m.r)); tip.append(rr, el("div", "c", m.c)); }
  for (const r of document.querySelectorAll(".rule")) r.classList.toggle("on", !!m && r.dataset.r === m.r || ruleOn === r.dataset.r);
  for (const c of document.querySelectorAll("#trows .ag")) c.classList.toggle("hit", !!m && (c._a.held || []).some(x => cellOf(x[0]).join(",") === i + "," + h));
  tip.style.left = "0px"; tip.style.top = (y + parseFloat(getComputedStyle($("stage")).paddingTop)) + "px"; tip.style.opacity = 1;
  const tw = tip.offsetWidth, sw = $("stage").clientWidth;
  tip.style.left = Math.max(0, Math.min(sw - tw, x + 14 - tw / 2 - $("stage").scrollLeft)) + "px";
}
cv.addEventListener("pointermove", tipAt);
cv.addEventListener("pointerdown", tipAt);
{ let k = -1;
  const held = () => M.slice().sort((a, b) => a.i - b.i || a.h - b.h);
  const at = m => { const bb = cv.getBoundingClientRect(), r = (m.h - 6 + 24) % 24;
    return {clientX: bb.left + L + (m.i + .5) * cw, clientY: bb.top + T + (r + .5) * rh}; };
  $("stage").addEventListener("keydown", e => {
    const ms = held(); if (!ms.length || drawn < D.days) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault(); k = (k + (e.key === "ArrowRight" ? 1 : ms.length - 1)) % ms.length;
      const p = at(ms[k]); const x = p.clientX - cv.getBoundingClientRect().left;
      $("stage").scrollLeft = Math.max(0, x - $("stage").clientWidth / 2);
      tipAt(at(ms[k])); $("live").textContent = tip.innerText.replace(/\n/g, ", ");
    } else if (e.key === "Enter" && k >= 0) { e.preventDefault(); openMark(ms[k]); }
    else if (e.key === "Escape") { tip.style.opacity = 0; }
  });
  $("stage").addEventListener("blur", () => { tip.style.opacity = 0; });
}
cv.addEventListener("pointerleave", () => { tip.style.opacity = 0;
  for (const c of document.querySelectorAll("#trows .ag.hit")) c.classList.remove("hit");
  for (const r of document.querySelectorAll(".rule")) r.classList.toggle("on", ruleOn === r.dataset.r); });
function openMark(m) {
  const id = m.result?.call_id;
  const matches = receipts.filter(e => id ? e.h[4]?.call_id === id : cellOf(e.h[0]).join(",") === m.i + "," + m.h && e.h[1] === m.v && e.h[2] === m.r && e.h[3] === m.c);
  if (matches.length !== 1) return;
  const entry = matches[0];
  if (filter || ruleOn) { filter = null; setRule(null); }
  selectReceipt(entry);
  const c = [...document.querySelectorAll("#trows .ag")].find(x => x._a === entry.a);
  if (!c) return;
  if (matchMedia("(min-width: 1200px)").matches) c.scrollIntoView({block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
  (c.querySelector(".ob") || c).focus({preventScroll: true});
}
cv.addEventListener("click", e => {
  if (drawn < D.days) return;
  const bb = cv.getBoundingClientRect(), i = Math.floor((e.clientX - bb.left - L) / cw), r = Math.floor((e.clientY - bb.top - T) / rh);
  const h = (r + 6) % 24, m = markAt[i * 24 + h]; if (m) openMark(m);
});
$("replay").onclick = play;          // it sits beside the picture it replays
$("save").onclick = () => {
  if (!confirm("Save an image of your activity dates and hours? Keep it private if you do not want to share your work patterns.")) return;
  // Drawn from the data, not copied off the screen: the same card from any
  // window, mid-replay or not, crisp at 2x, labels sized for a feed.
  const S = 2, w = 1600, h = 900, out = document.createElement("canvas"); out.width = w * S; out.height = h * S;
  const g = out.getContext("2d"); g.setTransform(S, 0, 0, S, 0, 0);
  g.fillStyle = "#161618"; g.fillRect(0, 0, w, h);
  g.fillStyle = "#1b1b1e"; g.strokeStyle = "#2a2a2c"; g.lineWidth = 2;
  g.beginPath(); g.roundRect ? g.roundRect(40, 40, w - 80, h - 80, 22) : g.rect(40, 40, w - 80, h - 80); g.fill(); g.stroke();
  const keep = [W, H, L, R, T, B, cw, rh, FS];
  W = w - 160; H = 600; L = 80; R = 0; T = 0; B = 44; FS = 19;
  cw = (W - L - R) / D.days; rh = (H - T - B) / 24;
  g.save(); g.translate(80, 180); frame(g, "#1b1b1e"); for (let i = 0; i < D.days; i++) dots(g, i, 1); g.restore();
  [W, H, L, R, T, B, cw, rh, FS] = keep;
  g.textBaseline = "alphabetic"; g.font = "600 30px -apple-system,Segoe UI,Helvetica,sans-serif"; g.fillStyle = "#fff";
  g.fillText("kyma", 116, 112); g.fillStyle = "#74b6f9"; g.beginPath(); g.arc(96, 102, 7, 0, 7); g.fill();
  let x = 220, fs = 26;
  const facts = [[fmt(D.actions), "tool calls", null], [fmt(D.together), "clock h with prompts", "#ffb86e"], [fmt(D.alone), "clock h without prompts", "#74b6f9"]];
  if (D.held_live) facts.push([fmt(D.held_live), "stopped", "#ff6f91"]);
  if (D.asked_live) facts.push([fmt(D.asked_live), "asked you", "#ff6f91"]);
  if (!D.held_live && !D.asked_live && D.stop_past) facts.push([fmt(D.stop_past), "would stop", "#f07a5e"]);
  if (!D.held_live && !D.asked_live && D.ask_past) facts.push([fmt(D.ask_past), "would ask", "#f0a845"]);

  // the facts fit inside the card: a long run of them gets a smaller size, not a cut
  const room = w - 96 - x, width = () => facts.reduce((t, [n, l, c]) => t + (c ? 26 : 0) + g.measureText(n).width + 10 + g.measureText(l).width + 44, -44);
  do { g.font = fs + "px Menlo,monospace"; } while (width() > room && --fs > 14);
  for (const [n, l, c] of facts) {
    if (c) { g.fillStyle = c; g.beginPath(); g.arc(x + 8, 103, 8, 0, 7); g.fill(); x += 26; }
    g.fillStyle = "#fff"; g.fillText(n, x, 112); x += g.measureText(n).width + 10;
    g.fillStyle = "#a5a5a7"; g.fillText(l, x, 112); x += g.measureText(l).width + 44;
  }
  // the dates on a line of their own: on the facts' line a long run of facts wrote over them
  g.fillStyle = "#838385"; g.font = "22px Menlo,monospace";
  g.fillText(long(day0) + " → " + long(new Date(D.today + "T00:00:00")), 96, 154);
  g.textAlign = "right"; g.fillText("github.com/kymacomputer/kyma-local", w - 96, 822); g.textAlign = "left";
  out.toBlob(b => { const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "my-agent-hours.png"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    const s = $("save"); s.classList.add("ok"); $("live").textContent = "Saved my-agent-hours.png"; setTimeout(() => s.classList.remove("ok"), 1600); });
};
const redraw = () => { if (!$("activity").open) return; layout(); frame(fx); for (let i = 0; i < drawn; i++) dots(fx, i, 1); render(drawn, null); };
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { buildTree(); redraw(); }, 150); });
// when the picture sticks to the top it has more room: it grows into it, and gives it back at the top of the page
let stuck = false; addEventListener("scroll", () => {
  if (!matchMedia("(min-width: 1200px)").matches) return;
  const now = document.querySelector(".side").getBoundingClientRect().top <= 1;
  if (now !== stuck) { stuck = now; setTimeout(redraw, 0); }
}, {passive: true});

function setup() {
  const active = D.on && !D.hooks_off;
  const rulesStatus = D.setup_rule_status || "";
  const modes = D.setup_modes;
  let scope = D.on_scope || "project";
  const dialog = $("setup-dialog");
  $("setup-open").onclick = () => dialog.showModal();
  $("setup-open").textContent = D.hooks_off ? "Restore Claude Code checks" : active ? "Manage Claude Code rules" : "Set up Claude Code checks";
  $("setup-dialog-title").textContent = D.hooks_off ? "Restore Claude Code checks" : active ? "Manage Claude Code rules" : "Turn rules on in Claude Code";
  $("setup-scopes").hidden = !!D.on;
  $("setup-project-label").textContent = "This folder · " + modes.project.name;
  if (D.claude === false) $("setup-open").hidden = true;
  $("setup-close").onclick = $("setup-return").onclick = () => dialog.close();
  dialog.addEventListener("click", e => { if (e.target === dialog) { const r = dialog.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close(); } });
  const copyCommand = (name, value) => {
    $(name + "-command").textContent = value;
    $(name + "-copy").textContent = "Copy";
    $(name + "-feedback").textContent = "";
    $(name + "-copy").onclick = async () => {
      try { await navigator.clipboard.writeText(value); $(name + "-copy").textContent = "Copied"; $(name + "-feedback").textContent = "Copied. Paste at your terminal command prompt."; }
      catch (e) { const selection = window.getSelection(), range = document.createRange(); range.selectNodeContents($(name + "-command")); selection.removeAllRanges(); selection.addRange(range); $(name + "-feedback").textContent = "Select the command and copy it with your keyboard."; }
    };
  };
  const fileRow = (file, recovery = false) => {
    const row = el("div", "setup-file"); row.append(el("code", "", file.path));
    row.append(el("p", "", recovery ? file.managed ? file.title === "allowManagedHooksOnly" ? "allowManagedHooksOnly is true. Your administrator must permit Kyma’s user-installed hook." : "disableAllHooks is true. Your administrator must enable hooks in this managed file." : "Change disableAllHooks from true to false, then save." : file.title));
    if (file.edit && !file.managed) {
      const command = el("div", "setup-command"), code = el("code", "", file.edit), b = el("button", "plain-button", "Copy open command");
      b.onclick = async () => { try { await navigator.clipboard.writeText(file.edit); b.textContent = "Copied"; } catch (e) { const r = document.createRange(); r.selectNodeContents(code); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); } };
      command.append(code, b); row.append(command);
    }
    return row;
  };
  $("setup-recovery").hidden = !D.hooks_off;
  for (const file of D.setup_recovery || []) $("setup-recovery-files").append(fileRow(file, true));
  function refreshSetup() {
  const mode = modes[scope], setupRules = mode.rules;
  for (const input of document.querySelectorAll('[name="setup-scope"]')) input.checked = input.value === scope;
  $("setup-scope").textContent = (D.on ? "Rules are installed for " : "Apply rules to ") + (scope === "project" ? "“" + mode.name + "” in Claude Code only." : "all Claude Code projects.") + " Other agents stay report-only.";
  $("setup-rules-list").replaceChildren();
  $("setup-rules-title").textContent = mode.title;
  if (rulesStatus) {
    $("setup-rules-title").textContent += rulesStatus === "missing" ? " · restore required" : " · pending review";
    $("setup-rule-status").hidden = false;
    $("setup-rule-status").textContent = {pending:"Changes require review · current checks shown",missing:"RULES.md is missing · accepted rules shown",review:"Rule acceptance requires review in terminal"}[rulesStatus];
  }
  for (const rule of setupRules) {
    const kind = rule.ok && ["ask", "block", "allow"].includes(rule.v) ? rule.v : "unsupported";
    const label = {ask:"Ask",block:"Block",allow:"Allow",unsupported:"Not applied"}[kind];
    const row = el("li");
    row.append(el("span", "setup-rule-kind " + kind, label), el("span", "setup-rule-text", rule.t));
    if (kind === "unsupported") row.append(el("span", "sr", "Rule not understood"));
    $("setup-rules-list").append(row);
  }
  if (!setupRules.length) $("setup-rules-list").append(el("li", "", "No rules configured"));
  $("setup-action").textContent = D.hooks_off ? "After the repair, check again:" : active || rulesStatus ? "Review the rules in this terminal:" : "Paste this command and press Enter.";
  $("setup-success").hidden = active || !!D.hooks_off || !!rulesStatus;
  $("setup-off-scope").textContent = scope === "project" ? "Remove Kyma’s checks from this project only." : "Remove Kyma’s checks from all projects, including earlier project-only installs.";
  $("setup-rule-files").replaceChildren(...mode.files.map(f => fileRow(f)));
  $("setup-edit").hidden = !active;
  copyCommand("setup", D.hooks_off ? mode.check : active || rulesStatus ? mode.review : mode.on);
  copyCommand("setup-check", mode.check);
  copyCommand("setup-off", mode.off);
  }
  for (const input of document.querySelectorAll('[name="setup-scope"]')) input.onchange = () => { scope = input.value; refreshSetup(); };
  refreshSetup();
  const refresh = $("refresh-dialog");
  const reportCommand = D.example ? D.cmd.replace(/ on$/, "") : modes.project.report;
  $("refresh-open").onclick = () => {
    $("refresh-title").textContent = D.example ? "See your own activity" : "Refresh your activity";
    copyCommand("refresh", reportCommand);
    refresh.showModal();
  };
  $("scan-all").onclick = () => {
    $("refresh-title").textContent = "Scan all history · Free";
    copyCommand("refresh", modes.project.report_all);
    refresh.showModal();
  };
  $("refresh-close").onclick = () => refresh.close();
  copyCommand("refresh", reportCommand);
  $("refresh-help").hidden = !D.example;
  copyCommand("refresh-python", "git clone https://github.com/kymacomputer/kyma-local && cd kyma-local && python3 kyma");
  if (D.example) {
    $("refresh-open").textContent = "Check my activity";
    $("refresh-title").textContent = "See your own activity";
    $("setup-open").textContent = "Try on my computer";
    $("setup-open").onclick = () => refresh.showModal();
  }
}
setup();
const wide = matchMedia("(min-width: 1200px)");
$("activity").open = false;
$("activity").addEventListener("toggle", () => { if ($("activity").open) redraw(); });
drawn = D.days;
buildTree();
if ($("activity").open) redraw();
</script></body></html>
"""


def rule_rows(s: dict) -> list:
    """Every rule you have, where it is, and how many past calls it would have held."""
    from . import rules as _rules
    text, yours = rules_text()
    counts = s.get("by_rule") or Counter(m["r"] for m in s.get("marks", []))
    out = []
    for r in _rules.parse(text, source="RULES.md"):
        out.append({"t": r.text, "w": f"RULES.md:{r.line}" if yours else "", "n": counts.get(r.text, 0),
                    "live": s.get("live_by_rule", {}).get(r.text, 0),
                    "v": r.verdict, "ok": bool(r.enforced)})
    return out


def setup_modes(data: dict, loaded: list, files: list) -> dict:
    """Commands bind scope to the report's folder, not the next terminal's cwd."""
    import shlex
    from . import enforce
    root = enforce.project_root()
    command = data["cmd"]
    runner = command[:-3] if command.endswith(" on") else command
    environment = []
    for key, value in (("KYMA_HOME", enforce.HOME), ("CLAUDE_CONFIG_DIR", sources.claude_dir()),
                       ("CODEX_HOME", sources.codex_dir())):
        environment.append(key + "=" + shlex.quote(os.path.abspath(value)))

    def bound(folder, commands):
        if environment:
            commands = "( export " + " ".join(environment) + "; " + commands + " )"
        return "cd " + shlex.quote(folder) + " && " + commands
    editor = "open -e" if sys.platform == "darwin" else "xdg-open" if shutil.which("xdg-open") else "vi"

    def file_row(path, title):
        return {"path": enforce._short(path), "title": title,
                "edit": editor + " " + shlex.quote(path) if os.path.isfile(path) else ""}

    recovery = []
    paths = [(p, True) for p in enforce.MANAGED_SETTINGS]
    paths += [(enforce.settings_path("global"), False)]
    paths += [(os.path.join(root, ".claude", n), False) for n in ("settings.json", "settings.local.json")]
    for path, managed in paths:
        try:
            settings, _ = enforce._read_settings(path)
        except (OSError, enforce.InstallError):
            continue
        keys = [k for k in ("disableAllHooks", "allowManagedHooksOnly")
                if settings.get(k) is True and (managed or k == "disableAllHooks")]
        for key in keys:
            row = file_row(path, key)
            row["managed"] = managed
            recovery.append(row)
    data["setup_recovery"] = recovery
    modes = {}
    for scope in ("project", "global"):
        folder = root if scope == "project" else os.path.expanduser("~")
        project = [r for r in loaded if r.trust != "global"] if scope == "project" else []
        rows = data["setup_rules"] + [{"t": r.text, "v": r.verdict, "ok": bool(r.enforced)} for r in project]
        rule_files = [file_row(enforce.GLOBAL_RULES, "Your rules · shared by active projects")]
        if scope == "project":
            rule_files += [file_row(p, "Project rules") for p in files if p != enforce.GLOBAL_RULES]
        modes[scope] = {"name": os.path.basename(root) if scope == "project" else "All projects",
                        "title": "Your rules" if data["setup_yours"] else "Starter + project rules" if project else "Starter rules",
                        "rules": rows, "files": rule_files,
                        "on": bound(folder, runner + " on --" + scope),
                        "review": bound(folder, runner + " rules"),
                        "check": bound(root, runner + " status && " + runner),
                        "report": bound(root, runner),
                        "report_all": bound(root, runner + " --all"),
                        "off": bound(folder, runner + " off --" + scope)}
    return modes


def page(s: dict, path: str = OUT) -> str:
    data = {k: s.get(k) for k in ("first", "days", "A", "Y", "actions", "together", "alone",
                                  "marks", "examples", "more", "held_past", "held_live", "asked_live", "away_past", "stop_past", "ask_past", "yours", "judged",
                                  "judged_from", "judged_of", "today", "partial_logs", "checked_calls",
                                  "checked_first", "checked_last", "marks_total", "live_by_rule", "quick", "scope", "undated_actions", "legacy_kept")}
    data["rules"] = rule_rows(s)
    from . import enforce, render
    # Setup previews global rules, independent of the retrospective filter.
    # Readback must not seed or accept rule changes as enforcement does.
    data["setup_rules"], data["setup_yours"] = data["rules"], bool(s.get("yours"))
    data["setup_rule_status"] = ""
    loaded, rule_files = [], []
    try:
        loaded, rule_files, missing = enforce.rules_view()
        accepted, bad = enforce.accepted()
        custom = os.path.lexists(enforce.GLOBAL_RULES) or accepted is not None or bool(bad)
        if custom:
            data["setup_yours"] = True
            data["setup_rules"] = [{"t": r.text, "v": r.verdict, "ok": bool(r.enforced)}
                                   for r in loaded if r.trust == "global"]
        data["setup_rule_status"] = "review" if bad else "missing" if missing else "pending" if enforce.pending_changes() else ""
        if data["setup_rule_status"] == "pending" and accepted is not None:
            # Match held_back's effective rules without its acceptance writes.
            effective = enforce._parse_global(accepted) + [r for r in loaded if r.trust == "global" and r.verdict != "allow"]
            data["setup_rules"] = list({(r.text, r.verdict): {"t": r.text, "v": r.verdict, "ok": bool(r.enforced)} for r in effective}.values())
    except Exception:
        data["setup_rule_status"] = "review"
    try:
        data["on_scope"] = "global" if enforce.is_installed("global") else "project" if enforce.is_installed("project") else ""
        data["on"] = bool(data["on_scope"])
        data["on_project"] = os.path.basename(enforce.project_root())
        data["hooks_off_reason"] = enforce.hooks_off_reason()
        data["hooks_off"] = bool(data["hooks_off_reason"])
    except Exception:
        data["on"], data["hooks_off"] = False, False
        data["on_scope"], data["on_project"], data["hooks_off_reason"] = "", "", ""
    data["claude"] = os.path.isdir(sources.claude_dir())
    data["roots"] = [r for r, a in (("~/.claude/projects", "claude"), ("~/.codex/sessions", "codex"))
                     if any(x.get("agent") == a for x in (s.get("agents") or []))]
    data["cmd"] = turn_on_command()
    data["setup_modes"] = setup_modes(data, loaded, rule_files)
    data["agents"] = s.get("agents") or []
    data["sessions"] = s.get("sessions") or len(data["agents"])
    where = {r["t"]: r["w"] for r in data["rules"]}
    data["examples"] = [dict(m, w=where.get(m["r"], "")) for m in data.get("examples") or []]
    # A logged command can hold `</script>`; inside a script block it must not close it.
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--")
    from .brand_marks import PROVIDER_MARKS
    html = PAGE.replace("__DATA__", blob).replace("__PROVIDER_MARKS__", json.dumps(PROVIDER_MARKS))
    ensure_home()
    state_write(path, html)
    return path


def _at(s: dict, m: dict) -> str:
    if m.get("undated") or m.get("i") is None:
        return "Time not recorded"
    d = _dt.date.fromisoformat(s["first"]) + _dt.timedelta(days=m["i"])
    h = m["h"]
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')} \u00b7 {h % 12 or 12}{'am' if h < 12 else 'pm'}"


_RING, _DOT, _LINE = "\u25cb", "\u25cf", "\u2501"


def summary_block(s: dict, color: bool = True) -> str:
    """One concrete past action before the full agent topology and chart."""
    import textwrap
    from . import enforce, rules, signals
    width = max(24, shutil.get_terminal_size((80, 24)).columns - 4)
    bold = (lambda t: f"\x1b[1m{t}\x1b[0m") if color else (lambda t: t)
    out = ["", "  " + bold("kyma"), ""]
    def line(text=""):
        out.extend("  " + t for t in textwrap.wrap(signals.clean(text), width) or [""])
    on = (enforce.is_installed("global") or enforce.is_installed("project")) and not enforce.hooks_off_reason()
    line("Claude Code checks are on." if on else "Checks are off. This is your past activity.")
    line()
    stop, ask = s.get("stop_past", 0), s.get("ask_past", 0)
    if stop or ask:
        if stop:
            line(f"{stop:,} past action{'s' if stop != 1 else ''} would be blocked.")
        if ask:
            line(f"{ask:,} would need your approval.")
    else:
        line("No past action matched these rules.")
    if s.get("held_live") or s.get("asked_live"):
        line(f"Live checks: {s.get('held_live', 0):,} stopped, {s.get('asked_live', 0):,} asked for approval.")
    examples = [m for m in s.get("examples", []) if not m.get("live")]
    if examples:
        m = min(examples, key=lambda m: (m.get("v") != "block", -(m.get("i") or 0), -(m.get("h") or 0)))
        compiled = rules.parse("- " + m["r"])
        topics = compiled[0].topics if compiled else []
        labels = {"secrets": "Your AI tried to read a file that can contain passwords.",
                  "dotenv": "Your AI tried to read a .env configuration file.",
                  "email": "Your AI tried to send an email.",
                  "git_push": "Your AI tried to publish code to a remote repository.",
                  "privilege": "Your AI tried to run a command with administrator access.",
                  "schedule": "Your AI tried to set up a task to run automatically.",
                  "destructive": "Your AI tried to delete files.",
                  "deploy": "Your AI tried to deploy an app or change infrastructure."}
        label = next((labels[t] for t in topics if t in labels), "Your AI tried an action that matches this rule.")
        line()
        line(label)
        line("Time not recorded" if m.get("undated") else _at(s, m))
        if m.get("c"):
            line(m["c"])
        line("Rule: " + m["r"])
    line()
    scope = f"{s.get('checked_calls', 0):,} past actions checked"
    if s.get("judged_of") and (s.get("judged", 0) < s["judged_of"] or s.get("partial_logs")):
        scope += f" · {s.get('judged', 0):,} complete"
        if s.get("partial_logs"):
            scope += f" + {s['partial_logs']:,} partial"
        scope += f" of {s['judged_of']:,} available logs"
    line(scope + ".")
    selected = s.get("scope") or {}
    if selected:
        label = "Recent sample" if s.get("quick") else "Selected history" if not selected.get("complete") else "Full available history"
        line(f"{label}: {selected.get('selected_files', 0):,} of {selected.get('available_files', 0):,} logs "
             f"({selected.get('selected_bytes', 0) / (1024 * 1024):.1f} MiB).")
        if not selected.get("complete"):
            from . import render
            line("Full history: " + render.prog("--all"))
    if s.get("undated_actions"):
        line(f"{s['undated_actions']:,} actions have no recorded time.")
    if s.get("legacy_kept"):
        line(f"{s['legacy_kept']:,} retained log snapshots use legacy call counts.")
    return "\n".join(out) + "\n"


def tree_block(s: dict, color: bool = True, limit: int = 6) -> str:
    """The agents as the page draws them: sessions, the subagents they started,
    and what each would have held, in the owner's words."""
    from .agents import identity_label
    ags = s.get("agents") or []
    if not ags:
        return ""
    esc = (lambda c, t: f"\x1b[{c}m{t}\x1b[0m") if color else (lambda c, t: t)
    dim = lambda t: esc("2", t)
    width = shutil.get_terminal_size((100, 40)).columns
    cut = lambda t, n: t if len(t) <= n else t[:max(1, n - 1)] + "\u2026"
    def deep(a):
        return list(a.get("held") or []) + [h for k in a.get("children") or [] for h in deep(k)]
    def rank(a):
        # a session wears the worst thing it, or anything it started, would have met
        h = deep(a)
        return 3 if any(x[1] == "block" for x in h) else 2 if any(x[1] == "ask" for x in h) else 1 if a.get("live") else 0
    def state(a):
        own = a.get("held") or []
        if not own and rank(a) >= 2:
            kid = next((k for k in a.get("children") or [] if deep(k)), None)
            kname = (kid.get("kind") or "") if kid else ""
            name = (kid.get("model") or "subagent") if kname in ("", "subagent") else ("General" if kname == "general-purpose" else kname)
            return esc("38;5;203" if rank(a) == 3 else "38;5;215", "\u21b3 via " + name)
        return {3: esc("38;5;203", "\u25b2 would stop"), 2: esc("38;5;215", "\u25f7 would ask"),
                1: esc("38;5;75", "\u25cc running"), 0: dim("done")}[rank(a)]
    def dur(a):
        m = a.get("mins", 0)
        if not (a.get("start") and a.get("end")):
            return ""
        return f"{m // 60}h {m % 60}m" if m >= 60 else (f"{m}m" if m else "<1m")
    order = sorted(range(len(ags)), key=lambda i: (-rank(ags[i]), -len(deep(ags[i])), i))
    out = []
    def line(prefix, a, sub=False):
        kind = a.get("kind") or ""
        generic = sub and kind in ("", "subagent")
        kind = "General" if kind == "general-purpose" else kind
        if generic:                                   # an untyped subagent goes by its model
            title = identity_label(a) or "Agent"
        else:
            name = kind if sub else (a.get("project") or a.get("agent"))
            title = f"{name} \u00b7 {identity_label(a)}".rstrip(" \u00b7")
        stats = f"{a.get('calls', 0):,} calls" + (f" \u00b7 {dur(a)}" if dur(a) else "")
        cont = prefix.replace("\u251c\u2500 ", "\u2502  ").replace("\u2514\u2500 ", "   ")
        if width < 80:                                # narrow: the name whole, the numbers on the line below
            out.append(f"  {prefix}{esc('1', title)}  {state(a)}")
            out.append(f"  {cont}   {dim(stats)}")
        else:
            room = max(10, min(40, width - 40) - len(prefix))          # the status column lines up at every depth
            out.append(f"  {prefix}{esc('1', cut(title, room).ljust(room))}  {state(a)}  {dim(stats)}")
        if a.get("task"):
            out.append(f"  {cont}   {dim(cut(a['task'], max(20, width - len(cont) - 8)))}")
        for h in (a.get("held") or [])[:2]:
            s.setdefault("_on_tree", set()).add(h[3] or "")
            ring = esc('38;5;167', "\u25b2") if h[1] == "block" else esc('38;5;215', "\u25f7")    # stop, ask: as everywhere
            if len(cont) + len(h[3] or "") + len(h[2]) + 12 <= width:
                out.append(f"  {cont}   {h[3] or ''}  {ring} {dim(h[2])}")
            else:                          # too narrow for both: the rule gets its own line, whole
                out.append(f"  {cont}   {cut(h[3] or '', max(16, width - len(cont) - 8))}")
                out.append(f"  {cont}   {ring} {dim(cut(h[2], max(16, width - len(cont) - 10)))}")
        return cont
    shown = order[:limit]
    for n, i in enumerate(shown):
        a = ags[i]
        last = n == len(shown) - 1 and len(ags) <= limit
        cont = line("\u2514\u2500 " if last else "\u251c\u2500 ", a)
        kids = a.get("children") or []
        for k, kid in enumerate(kids[:3]):
            klast = k == min(len(kids), 3) - 1 and len(kids) <= 3
            line(cont + ("\u2514\u2500 " if klast else "\u251c\u2500 "), kid, sub=True)
        if len(kids) > 3:
            out.append(f"  {cont}\u2514\u2500 {dim('+' + str(len(kids) - 3))}")
    if len(ags) > limit:
        older = max(0, (s.get("sessions") or 0) - len(ags))
        note = f"all {len(ags):,} on the page" + (f", {older:,} older with nothing held" if older else "")
        out.append(f"  \u2514\u2500 {dim(note)}")
    every = []
    def walk(a):
        every.append(a)
        for k in a.get("children") or []:
            walk(k)
    for a in ags:
        walk(a)
    # agents by their own calls, as the page counts them: a subagent's call is the subagent's
    own = lambda a, v: any(h[1] == v for h in a.get("held") or [])
    stop = sum(1 for a in every if own(a, "block"))
    ask = sum(1 for a in every if not own(a, "block") and own(a, "ask"))
    total = s.get("sessions") or len(ags)
    head = [esc("38;5;75", "\u2726") + " " + esc("1", "This machine"), dim(f"{total:,} session" + ("" if total == 1 else "s"))]
    if stop:
        # these count agents; the facts line above counts calls
        head.append(esc("38;5;203", f"{stop:,} agent{'' if stop == 1 else 's'} would stop"))
    if ask:
        head.append(esc("38;5;215", f"{ask:,} would ask"))
    return "  " + "   ".join(head) + "\n" + "\n".join(out) + "\n"


def held_block(s: dict, color: bool = True) -> str:
    """Every rule with what it would have held, then the moments themselves:
    the same two groups as the page, in the same order."""
    esc = (lambda c, t: f"\x1b[{c}m{t}\x1b[0m") if color else (lambda c, t: t)
    dim = lambda t: esc("2", t)
    rose = lambda t, c=_HELD: esc(f"38;5;{c}", t)
    rows = rule_rows(s)
    ex = s.get("examples", [])
    if not rows and not ex:
        return ""
    partial = s.get("judged_of") and s.get("judged", 0) < s["judged_of"]
    width = shutil.get_terminal_size((100, 40)).columns
    cut = lambda t, n: t if len(t) <= n else t[:max(1, n - 1)] + "\u2026"
    out = []
    from . import enforce as _e
    path = _e.GLOBAL_RULES.replace(os.path.expanduser("~"), "~", 1)          # wherever KYMA_HOME puts it
    claude = os.path.isdir(sources.claude_dir())
    if s.get("yours"):
        out.append("  " + dim(path))
    if partial:
        scope = f"{s['judged']:,} complete"
        if s.get("partial_logs"):
            scope += f" + {s['partial_logs']:,} partial"
        out.append("  " + dim(f"{s.get('checked_calls', 0):,} actions checked · {scope} of {s['judged_of']:,} available logs replayed"))
    hidden = 0
    if len(rows) > 8:                    # 2,000 rules printed 2,061 lines: show the ones that met something
        keep = sorted(rows, key=lambda r: (r["ok"], -r["n"]))[:8]
        hidden, rows = len(rows) - len(keep), [r for r in rows if r in keep]
    top = max([r["n"] for r in rows] + [1])
    nw = max([len(f"{r['n']:,}") for r in rows] + [1])
    barw = 12 if width >= 72 and color else 0
    tw = max(12, min(max((len(r["t"]) for r in rows), default=12), width - nw - barw - 10))
    for r in rows:
        if not r["ok"]:
            out.append(f"  {esc('38;5;203', '?')} {cut(r['t'], tw).ljust(tw)}  " + esc("38;5;203", "not understood"))
            continue
        bar = ""
        if barw:
            k = round(barw * r["n"] / top)
            bar = rose(_LINE * k) + esc("38;5;236", _LINE * (barw - k)) + "  "
        n = f"{r['n']:,}".rjust(nw)
        import textwrap
        lines = textwrap.wrap(r["t"], tw) or [""]
        text = lines[0].ljust(tw)
        mark = rose("\u25b2") if r["v"] == "block" else esc("38;5;215", "\u25f7")     # the tree's marks: stop, ask
        out.append(f"  {mark} {dim(text) if not r['n'] else text}  {bar}{dim(n) if not r['n'] else n}")
        for more in lines[1:]:
            out.append(f"    {dim(more) if not r['n'] else more}")
    if hidden:
        from . import render
        out.append("    " + dim(f"+{hidden:,} more rules · {render.prog('rules')}"))
    # what the tree already quoted is not quoted twice, unless it happened while you were away
    shown_above = s.get("_on_tree") or set()
    ex = [m for m in ex if m.get("away") or m.get("live") or m.get("c") not in shown_above]
    if ex:
        out.append("")
        ex = sorted(ex, key=lambda m: (m.get("i", 0), m.get("h", 0)), reverse=True)
        for m in ex:
            when = _at(s, m) + (" \u00b7 away" if m.get("away") else "")
            dot = esc(f"38;5;{141 if m.get('away') else _WARM}", _DOT)       # away has its own colour, as on the page
            room = max(10, width - len(when) - 10)
            glyph = rose(_DOT, _LIVE) if m.get("live") else (rose("\u25b2") if m.get("v") == "block" else esc("38;5;215", "\u25f7"))
            if width < 80:                       # narrow: the command whole, its time and rule beneath
                out.append(f"  {glyph} {cut(m['c'], width - 6)}")
                out.append(f"    {dot} {dim(when)}")
            else:
                out.append(f"  {glyph} {cut(m['c'], room).ljust(min(room, max(len(x['c']) for x in ex)))}  {dot} {dim(when)}")
            out.append("    " + dim(cut(m.get("r", ""), width - 6)))
        rest = (s.get("held_past", 0) or 0) + (s.get("held_live", 0) or 0) + (s.get("asked_live", 0) or 0) - len(ex)
        if rest > 0:
            out.append("    " + dim(f"+{rest:,} more on the page"))
    return "\n".join(out) + "\n"


SOURCE = "git+https://github.com/kymacomputer/kyma-local"


def turn_on_command() -> str:
    """The one command that turns the rules on, the same on every surface.
    A copy in a throwaway folder with no uv to keep it cannot plug itself in."""
    from . import enforce, render
    durable, _ = enforce.install_is_durable()
    if durable or shutil.which("uv"):
        return render.prog("on", absolute=True)
    return "uv tool install " + SOURCE + " && kyma on"


def offer(s: dict) -> bool:
    """One question, one key: plug kyma into Claude Code so the rules hold from now on."""
    import shlex
    from . import enforce, render
    bold = (lambda t: f"\x1b[1m{t}\x1b[0m") if _tty() else (lambda t: t)
    dimc = (lambda t: f"\x1b[2m{t}\x1b[0m") if _tty() else (lambda t: t)
    mark = f"\x1b[38;5;{_LIVE}m\u25c6\x1b[0m" if _tty() else "\u25c6"
    if not os.path.isdir(sources.claude_dir()):
        # the hook is Claude Code's; with no Claude Code here, an "On" would be false
        if any(a.get("agent") == "codex" for a in s.get("agents") or []):
            sys.stdout.write("  " + dimc("Kyma reads Codex history. Automatic checks currently support Claude Code. "
                                         "Codex can request advice through MCP:") + "  " + bold(render.prog("mcp")) + "\n\n")
        return False
    if enforce.hooks_disabled("global"):
        sys.stdout.write(f"  Claude Code has {bold('disableAllHooks')} on in {dimc(enforce.settings_path('global'))}: "
                         "no hook runs, kyma's included.\n\n")
        return False
    if enforce.is_installed("global") or enforce.is_installed("project"):
        return False
    durable, where = enforce.install_is_durable()
    if not durable and enforce._launcher() and where == enforce._launcher():
        # a clone in a temp folder cannot be kept by uv either: say so, do not ask a question Y cannot answer
        sys.stdout.write(f"\n  This clone is in a temporary folder, which gets cleaned up. Move it somewhere permanent, "
                         f"then:  {bold('./kyma on')}\n\n")
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or os.environ.get("CI") or (not durable and not shutil.which("uv")):
        cmd = turn_on_command()
        if len(cmd) + 24 > shutil.get_terminal_size((100, 40)).columns and " && " in cmd:
            a, b = cmd.split(" && ", 1)               # a narrow window breaks it where a shell can, not mid-URL
            sys.stdout.write(f"\n  Turn these rules on:\n    {bold(a + ' &&')}\n    {bold(b)}\n\n")
        else:
            sys.stdout.write(f"\n  Turn these rules on:  {bold(cmd)}\n\n")
        return False
    try:
        root = enforce.project_root()
        label = enforce._short(root)
        package_root = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        project_choice = root not in (os.path.realpath(os.path.expanduser("~")), package_root)
        sys.stdout.write("\n  Add checks to Claude Code?\n")
        sys.stdout.write(f"  {bold('[a]')} All projects\n")
        if project_choice:
            sys.stdout.write(f"  {bold('[p]')} Only {bold(label)}\n")
        sys.stdout.write("  [Enter] Not now\n")
        answer = input("  Choice: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        sys.stdout.write("\n")
        return False
    if answer not in ("p", "project", "a", "all") or (answer in ("p", "project") and not project_choice):
        sys.stdout.write(f"\n  Later, for all Claude Code projects:  {bold(render.prog('on --global'))}\n  {dimc('Or test one rule first:')}  "
                         f"{bold(render.prog('try ' + chr(34) + 'never use sudo' + chr(34)))}\n\n")
        return False
    scope = "project" if answer in ("p", "project") else "global"
    command = None
    if not durable:
        sys.stdout.write("  " + dimc("keeping a copy of kyma…"))
        sys.stdout.flush()
        def ask(q):
            sys.stdout.write("\r\x1b[K")
            try:
                return input("  " + q).strip().lower() in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                return False
        kept, why = enforce.keep_copy(ask=ask)
        sys.stdout.write("\r\x1b[K")
        if not kept:
            sys.stdout.write(f"  Not turned on: {why}.\n  To keep a copy yourself:  {bold('uv tool install ' + SOURCE)}\n\n")
            return False
        command = enforce.command_for_script(kept)
        if os.environ.get("KYMA_HOME"):
            command = f"KYMA_HOME={shlex.quote(enforce.HOME)} {command}"      # absolute, as `kyma on` writes it
    try:
        from .cli import version_warning
        warn = version_warning()
        if warn:
            sys.stdout.write("  " + dimc(warn) + "\n")
    except Exception:
        pass
    try:
        enforce.ensure_rules()
        enforce.accept_rules(True)          # a person selected the scope at the terminal
        path, how = enforce.install(scope, command=command)
    except Exception as e:                 # InstallError says exactly what it refused and why
        sys.stdout.write(f"  Not turned on: {e}\n\n")
        return False
    short = lambda p: p.replace(os.path.expanduser("~"), "~", 1)
    sys.stdout.write(f"\n  {mark} On · {'this project' if scope == 'project' else 'all projects'}   {dimc(short(path))}\n")
    sys.stdout.write("  Continue in Claude Code. It asks you before an action that matches an ask rule. A never rule blocks it.\n")
    stop = render.prog("stop")
    if command:                         # the kept copy, not the uvx line, which would fetch the default branch
        on_path = shutil.which("kyma")
        stop = "kyma stop" if on_path and os.path.realpath(on_path) == os.path.realpath(kept) else shlex.quote(kept) + " stop"
    sys.stdout.write(f"  {dimc('To hold every call at once:')}  {bold(stop)}\n\n")
    return True


NOTHING = """
  No AI activity found yet.

  Kyma reads Claude Code, Codex, Cursor, and Gemini CLI history.
  Try a safe example now:  {demo}
  After your next agent task, run {run} again.
"""


def _nothing() -> str:
    from . import render
    return NOTHING.replace("{demo}", render.prog("demo")).replace("{run}", render.prog())


def _bar(done: int, total: int, color: int, what: str = "") -> str:
    """Progress as a bar and a count, cut to the window: a wrapped line cannot
    be rewritten in place, and a narrow pane filled up with stale copies."""
    cols = shutil.get_terminal_size((80, 24)).columns
    count = f"{done:,} / {total:,}" + (f" {what}" if what else "")
    w = max(0, min(24, cols - len(count) - 6))
    k = round(w * done / max(1, total))
    bar = f"\x1b[38;5;{color}m" + _LINE * k + "\x1b[38;5;236m" + _LINE * (w - k) + "\x1b[0m" if w else ""
    return f"\r  {bar}  \x1b[2m{count}\x1b[0m\x1b[K"


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty() and not os.environ.get("CI")


def run(open_it: bool = True, details: bool = False, all_history: bool = False,
        since_days=None, limit=None) -> int:
    import webbrowser
    from . import history_scope
    # Never die on the way to the picture: a locale that cannot print a dot
    # gets a "?", a folder deleted under the shell gets home.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        os.getcwd()
    except OSError:
        os.chdir(os.path.expanduser("~"))
    tty = _tty()
    available = files()
    work, scope = history_scope.select(available, all_history=all_history, since_days=since_days, limit=limit)
    quick = scope["mode"] == "recent"
    scoped = scope["mode"] != "all"
    n_files = len(available)
    if not n_files and not os.path.isdir(CACHE):
        sys.stdout.write(_nothing() + "\n")
        return 0
    if scoped and not work:
        from . import render
        sys.stdout.write(f"\n  No logs fit this {'recent sample' if quick else 'history selection'}. "
                         f"{n_files:,} logs are available.\n")
        if scope["skipped_large_files"] or scope["skipped_compressed_files"]:
            sys.stdout.write(f"  The sample excludes files above {history_scope.MAX_FILE_BYTES // (1024 * 1024)} MiB "
                             "and compressed logs.\n")
        sys.stdout.write("  Read full available and retained history: " + render.prog("--all") + "\n\n")
        return 0
    def progress(done, total, a, y):
        if tty:
            sys.stdout.write(_bar(done, total, _COOL[8], "logs"))
            sys.stdout.flush()
    try:
        data = gather(progress, work=work) if scoped else gather(progress)
    except OSError as e:
        sys.stdout.write(f"\r\x1b[K  kyma cannot write to {HOME}: {e.strerror or e}\n" if tty else
                         f"kyma cannot write to {HOME}: {e.strerror or e}\n")
        return 1
    def judging(done, total):
        if tty:
            sys.stdout.write(_bar(done, total, _HELD, "logs against your rules"))
            sys.stdout.flush()
    data["held"] = held_moments(judging, work=work,
                                budget=history_scope.REPLAY_SECONDS if quick else None) if scoped else held_moments(judging)
    if tty:
        sys.stdout.write("\r\x1b[K")
    s = shape(data)
    if s:
        s["quick"], s["scope"] = quick, scope
    if s and s.get("actions"):
        try:
            from . import agents
            # the newest 200 and every one a rule met: the page's "+N" reaches all of them
            s["agents"] = agents.sessions(limit=200, judged=data["held"].get("paths", []), work=work if scoped else None)
            s["sessions"] = len(work) if scoped else agents.total_sessions()
        except Exception:
            s["agents"] = []
    if not s or not s["actions"]:
        if n_files:
            from . import render
            msg = (f"No tool calls found in {len(work):,} selected logs of {n_files:,} available." if scoped else
                   "1 agent log here, no tool calls in it yet." if n_files == 1 else
                   f"{n_files:,} agent logs here, no tool calls in them yet.")
            nxt = ("Read full history: " + render.prog("--all") if scoped else
                   f"To watch a rule hold a command now:  {render.prog('demo')}")
            sys.stdout.write(f"\n  {msg}\n  {nxt}\n\n" if tty else msg + "\n" + nxt + "\n")
        else:
            sys.stdout.write(_nothing() + "\n")
        return 0
    unread = sources.compressed_skipped()
    if not details:
        sys.stdout.write(summary_block(s, color=tty))
    elif tty:
        sys.stdout.write("\n" + facts_line(s, width=shutil.get_terminal_size((100, 40)).columns) + "\n")       # the legend first: warm is you, blue is them
        if any(any(row) for row in s["A"]):
            draw(s, animate=True)
        tb = tree_block(s)
        if tb:
            sys.stdout.write(tb + "\n")
        block = held_block(s)
        if block:
            sys.stdout.write(block + "\n")
    else:
        # piped, NO_COLOR, or an agent running kyma: the same facts, the tree and the rules, in plain text
        heading = f"Since {when(s['first'])}:" if any(any(row) for row in s["A"]) else "Recorded activity (times unavailable):"
        sys.stdout.write(heading + "\n" + facts_line(s, color=False, width=shutil.get_terminal_size((100, 40)).columns) + "\n\n")
        tb = tree_block(s, color=False)
        if tb:
            sys.stdout.write(tb + "\n")
        block = held_block(s, color=False)
        if block:
            sys.stdout.write(block)
    if details and scoped:
        from . import render
        sys.stdout.write(f"\n  {'Recent sample' if quick else 'Selected history'}: {len(work):,} of {n_files:,} logs.\n"
                         "  Full history: " + render.prog("--all") + "\n")
    if details and s.get("undated_actions"):
        sys.stdout.write(f"  {s['undated_actions']:,} actions have no recorded time.\n")
    if details and s.get("legacy_kept"):
        sys.stdout.write(f"  {s['legacy_kept']:,} retained log snapshots use legacy call counts.\n")
    if unread:
        msg = f"{unread:,} older Codex logs are compressed and need zstd to be drawn:  brew install zstd"
        sys.stdout.write(f"  \x1b[2m{msg}\x1b[0m\n\n" if tty else msg + "\n")
    try:
        path = page(s)                 # written before the question, so Ctrl-C there still leaves a page
    except OSError as e:
        sys.stdout.write(f"  kyma could not write its page to {HOME}: {e.strerror or e}\n")
        return 1
    if open_it and _interactive():
        try:
            webbrowser.open("file://" + path)
        except Exception:
            pass
    if _interactive():
        if offer(s):
            try:
                path = page(s)         # the answer changed the state the page shows
            except OSError:
                pass
    else:
        offer(s)                       # not interactive: it prints the one command instead of asking
    if not details:
        from . import render
        sys.stdout.write("  Detailed report: " + render.prog("--details" + (" --all" if not scoped else "")) + "\n")
    shown = path.replace(os.path.expanduser("~"), "~", 1)
    sys.stdout.write(f"  \x1b[2m{shown}\x1b[0m\n\n" if tty else f"{shown}\n")
    return 0

"""Turn 2 GB of agent logs into something you can look at in two seconds.

The first working version of the scanner took 90 seconds on one laptop. A
product whose promise is "see it immediately" cannot take 90 seconds, so the
reader runs once per log file and its result is cached by (mtime, size). A
second scan, and every rule you try afterwards, reads the cache instead.

The cached unit is a digest, not a copy of the transcript: counts, the signal
hits with their command line, and a deduplicated sample of commands. Agents
repeat themselves heavily, so dedup does most of the compression for free.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from . import HOME, _ours, ensure_home, shell, signals, sources


def _local_key(ts: str):
    """'YYYY-MM-DD HH' in local time, the cell a moment falls in."""
    try:
        from datetime import datetime
        d = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return d.strftime("%Y-%m-%d %H")
    except (ValueError, TypeError, OSError, AttributeError):
        return None


def _local_hour(ts: str):
    """Local hour of a log timestamp, for the "while you were asleep" count."""
    try:
        from datetime import datetime
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return d.astimezone().hour
    except (ValueError, TypeError, OSError):
        return None

# A name nobody else uses: KYMA_HOME may point at a folder that already has a
# "cache" of its own, and kyma must never purge what it did not write.
CACHE_DIR = os.path.join(HOME, ".kyma-cache")
LEGACY_CACHE = os.path.join(HOME, "cache")
# 8: secret values are masked before anything is stored. Caches written by
# earlier versions may hold them in clear, so a version change purges the whole
# directory once (see _purge_stale) rather than merely ignoring old entries.
CACHE_VERSION = 15        # provider-neutral adapters and their native tool kinds
#        # 12: a day-by-hour grid of agent work and of you
#        # 11: commands carry how often they ran; file reads and writes kept
HITS_PER_SIGNAL = 25      # enough to show, cheap to store


def _purge_stale() -> None:
    """Destroy, rather than merely ignore, caches from an older format.

    Ignoring is not enough: entries for logs that have since been deleted are
    never rewritten, so an unredacted cache from a previous version would sit
    on disk indefinitely. One marker file makes this a single stat per run.
    """
    import shutil
    # Only in a folder that is provably kyma's (its marker, yours, writable by
    # no one else). A VERSION file proves nothing: KYMA_HOME=~/MyStuff once
    # deleted ~/MyStuff/cache/ because a VERSION file sat in it.
    if not _ours():
        return
    if os.path.isfile(os.path.join(LEGACY_CACHE, "VERSION")) and not os.path.islink(LEGACY_CACHE):
        shutil.rmtree(LEGACY_CACHE, ignore_errors=True)
    marker = os.path.join(CACHE_DIR, "VERSION")
    try:
        with open(marker) as fh:
            if fh.read().strip() == str(CACHE_VERSION):
                _prune()
                return
    except OSError:
        pass
    if not os.path.islink(CACHE_DIR):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
    try:
        ensure_home()
        os.makedirs(CACHE_DIR, exist_ok=True)
        from . import state_write
        state_write(marker, str(CACHE_VERSION))
    except OSError:
        pass


def _prune() -> None:
    """Drop cached digests whose log is gone, at most once a day.

    A digest holds masked excerpts of the commands in one log. When that log
    is deleted, keeping its digest would keep the excerpts forever.
    """
    stamp = os.path.join(CACHE_DIR, "PRUNED")
    try:
        import time
        if time.time() - os.path.getmtime(stamp) < 86400:
            return
    except OSError:
        pass
    for root, _dirs, files in os.walk(CACHE_DIR):
        for f in files:
            if not f.endswith(".json"):
                continue
            p = os.path.join(root, f)
            try:
                with open(p) as fh:
                    src = json.load(fh).get("src")
                if src and not os.path.exists(src):
                    os.unlink(p)
            except (OSError, ValueError, AttributeError):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    try:
        from . import state_write
        state_write(stamp, "")
    except OSError:
        pass


def _cache_path(path: str) -> str:
    key = hashlib.sha1(path.encode()).hexdigest()
    return os.path.join(CACHE_DIR, key[:2], key + ".json")


def _blank() -> dict:
    return {
        "v": CACHE_VERSION,
        "actions": 0,
        "shell": 0,
        "tools": {},
        "agents": {},
        "projects": {},
        "hits": {},
        "hours": {},
        "commands": [],          # [masked line, times it ran]
        "touched": [],           # [kind, path, times], for replaying file rules
        "sessions": 0,
        "unkept": 0,             # compatibility with older consumers; no sampling cap
        "first_ts": "",
        "last_ts": "",
        "grid": {},              # "YYYY-MM-DD HH" local -> agent tool calls
        "you": {},               # "YYYY-MM-DD HH" local -> messages a person typed
    }


def digest_file(args) -> dict:
    """Digest one log file. Runs in a worker process."""
    path, agent = args
    cp = _cache_path(path)
    try:
        st = os.stat(path)
        stamp = f"{agent}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return _blank()
    try:
        with open(cp) as fh:
            cached = json.load(fh)
        if cached.get("v") == CACHE_VERSION and cached.get("stamp") == stamp:
            return cached
    except (OSError, ValueError):
        pass

    d = _blank()
    d["stamp"] = stamp
    d["src"] = path
    d["sessions"] = 1
    reader = sources.reader(agent)
    unreadable = getattr(sources, "Unreadable", ())
    try:
        actions = list(reader(path))
    except unreadable:
        return _blank()          # not cached: fixing the permission fixes the report
    tools, agents, projects, hours = Counter(), Counter(), Counter(), Counter()
    grid, you = Counter(), Counter()
    for ts in sources.human_times(path, agent):
        k = _local_key(ts)
        if k:
            you[k] += 1
    hits: dict = {}
    seen_cmd = {}
    commands = []
    touched = {}
    for a in actions:
        d["actions"] += 1
        tools[a.tool] += 1
        agents[a.agent] += 1
        if a.project:
            projects[signals.clean_label(a.project)] += 1
        if a.ts:
            if not d["first_ts"] or a.ts < d["first_ts"]:
                d["first_ts"] = a.ts
            if a.ts > d["last_ts"]:
                d["last_ts"] = a.ts
            h = _local_hour(a.ts)
            if h is not None:
                hours[h] += 1
            k = _local_key(a.ts)
            if k:
                grid[k] += 1
        subject = (a.subject or "")[:shell.MAX]
        if a.kind == "shell" and a.command:
            d["shell"] += 1
            # Mask the whole command first, then cut: cutting first left the
            # tail of a token that no longer matched its prefix. Heredoc
            # bodies written to prose files are not kept: they are not
            # actions, and they are often someone's whole document.
            body = signals.redact(shell._strip_heredocs(a.command[:shell.MAX]))
            line = signals.clean(body.strip().replace("\n", " ⏎ "))
            if line in seen_cmd:
                seen_cmd[line][1] += 1
            elif line:
                entry = [line, 1]
                seen_cmd[line] = entry
                commands.append(entry)
        elif a.kind in ("write", "read") and a.paths:
            shown_path = signals.clean(signals.redact(a.paths[0]))
            key = (a.kind, shown_path)
            if key in touched:
                touched[key][2] += 1
            else:
                touched[key] = [a.kind, shown_path, 1]
            if signals.noise(subject, cwd=a.project):
                subject = ""
        if not subject:
            continue
        shown = signals.executed(subject) if a.kind == "shell" else subject
        flat = signals.clean(signals.redact(" ".join(shown.split())))
        for sid in signals.match(subject, a.kind, cwd=a.project):
            bucket = hits.setdefault(sid, {"n": 0, "examples": []})
            bucket["n"] += 1
            # Keep the clearest examples, not the first ones seen.
            score = signals.example_score(flat, sid)
            ex = signals.excerpt(flat, sid)
            if not ex:
                continue
            kept = bucket["examples"]
            if any(e[1][:50] == ex[:50] for e in kept):
                continue
            kept.append([round(score, 2), ex, a.ts or ""])   # the time makes a quote real
            if len(kept) > HITS_PER_SIGNAL:
                kept.sort(key=lambda e: -e[0])
                del kept[HITS_PER_SIGNAL:]

    d["hours"] = {str(k): v for k, v in hours.items()}
    d["grid"] = dict(grid)
    d["you"] = dict(you)
    d["tools"] = dict(tools)
    d["agents"] = dict(agents)
    d["projects"] = dict(projects.most_common(20))
    d["hits"] = hits
    d["commands"] = commands
    d["touched"] = list(touched.values())

    try:
        ensure_home()
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        from . import state_write
        state_write(cp, json.dumps(d))
    except OSError:
        pass
    return d


def _merge(total: dict, d: dict) -> None:
    total["actions"] += d["actions"]
    total["shell"] += d["shell"]
    total["sessions"] += d.get("sessions", 0)
    total["unkept"] += d.get("unkept", 0)
    for key in ("tools", "agents", "projects", "hours", "grid", "you"):
        dst = total[key]
        for k, v in d.get(key, {}).items():
            dst[k] = dst.get(k, 0) + v
    for sid, b in d.get("hits", {}).items():
        dst = total["hits"].setdefault(sid, {"n": 0, "examples": []})
        dst["n"] += b["n"]
        for ex in b["examples"]:
            if any(e[1][:50] == ex[1][:50] for e in dst["examples"]):
                continue
            dst["examples"].append(ex)
        if len(dst["examples"]) > 60:
            dst["examples"].sort(key=lambda e: -e[0])
            del dst["examples"][60:]
    seen = total.setdefault("_seen", {})
    for entry in d.get("commands", []):
        line, n = (entry, 1) if isinstance(entry, str) else (entry[0], entry[1])
        if line in seen:
            seen[line][1] += n
        else:
            seen[line] = [line, n]
            total["commands"].append(seen[line])
    tseen = total.setdefault("_tseen", {})
    for kind, path, n in d.get("touched", []):
        key = (kind, path)
        if key in tseen:
            tseen[key][2] += n
        else:
            tseen[key] = [kind, path, n]
            total["touched"].append(tseen[key])
    for field in ("first_ts", "last_ts"):
        v = d.get(field) or ""
        if not v:
            continue
        cur = total[field]
        if not cur or (v < cur if field == "first_ts" else v > cur):
            total[field] = v


DEFAULT_LIMIT = 400


def build(since_days: int | None = None, agents: tuple | None = None,
          jobs: int | None = None, progress=None, limit: int | None = DEFAULT_LIMIT) -> dict:
    """Digest log files, newest first, in parallel, cached.

    The limit exists because the first run is the whole product. A heavy user
    of this machine had 4,891 session logs and a full pass took 49 seconds --
    long enough that nobody would ever see the output. Newest-first with a cap
    gives a true number in a few seconds, and the fact that it was capped is
    itself worth printing: "most recent 400 of 4,891 sessions" says something.
    """
    _purge_stale()
    found = [(path, format) for path, format in sources.history_files(since_days)
             if agents is None or format in agents]

    def mtime(item):
        try:
            return os.path.getmtime(item[0])
        except OSError:
            return 0.0

    found.sort(key=mtime, reverse=True)
    work = found[:limit] if limit else found

    total = _blank()
    total["files"] = len(work)
    total["files_found"] = len(found)
    if not work:
        total.pop("_seen", None)
        total.pop("_tseen", None)
        return total

    jobs = jobs or min(8, (os.cpu_count() or 4))
    done = 0
    if jobs > 1 and len(work) > 4:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for d in pool.map(digest_file, work, chunksize=8):
                _merge(total, d)
                done += 1
                if progress:
                    progress(done, len(work))
    else:
        for item in work:
            _merge(total, digest_file(item))
            done += 1
            if progress:
                progress(done, len(work))
    total.pop("_seen", None)
    total.pop("_tseen", None)
    return total

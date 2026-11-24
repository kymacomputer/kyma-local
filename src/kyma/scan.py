"""`kyma` -- the first fifteen seconds.

The report classifies attempted actions from the recorded calls, not their
external effects. The matchers distinguish requested actions from quoted
mentions. Raw volume appears once, dimmed, because it supplies context.
"""

from __future__ import annotations

import re
import time

from . import index, render, rules, shell, signals, sources

NOTHING = """  No agent logs on this machine yet.

  kyma reads local Claude Code, Codex, Cursor, and Gemini CLI history.
  Import another host's JSONL history with kyma import <file>.

  {demo}   watch the gate stop a command, without any logs
"""

LEAD = [
    "secrets_and_egress",
    "secrets_and_outbound",
    "self_modify",
    "curl_pipe_shell",
    "shell_profile",
    "persistence",
    "destructive_and_privilege",
]

ALSO = {
    "egress": "network access attempts",
    "secrets": "credential access attempts",
    "destructive": "deletion attempts",
    "supplychain": "package installation attempts",
    "outbound": "message send attempts",
    "publish": "publication attempts",
    "privilege": "privilege use or change attempts",
    "database": "database access attempts",
    "git_history": "git history rewrite attempts",
}

ROWS = 5          # the terminal and the page show the same rows


def best(examples: list, limit: int = 2, taken: set | None = None) -> list:
    """Clean examples only, each quoted once across the whole report."""
    out = []
    for e in sorted(examples, key=lambda e: -e[0]):
        if e[0] < 0:
            break
        key = e[1][:60]
        if taken is not None and key in taken:
            continue
        out.append(e)
        if taken is not None:
            taken.add(key)
        if len(out) >= limit:
            break
    return out


def select(data: dict) -> tuple:
    """-> (rows, promoted). rows: [(signal id, count, [examples])].

    Findings come first: they are precise now, so any one of them is worth a
    line, quote or no quote. When there are fewer than four, ordinary
    categories fill in, so a newcomer with five sessions still sees evidence.
    """
    hits = data.get("hits", {})
    taken: set = set()
    rows = []
    for sid in LEAD:
        b = hits.get(sid) or {}
        if b.get("n"):
            rows.append((sid, b["n"], best(b.get("examples", []), taken=taken)))
    promoted = False
    if len(rows) < 4:
        seen = {r[0] for r in rows}
        extra = []
        for sid in signals.SHARP:
            b = hits.get(sid) or {}
            if sid in seen or not b.get("n"):
                continue
            extra.append((sid, b["n"], best(b.get("examples", []), taken=set(taken))))
        extra.sort(key=lambda r: (-len(r[2]), -r[1]))
        for sid, n, _ in extra[: 4 - len(rows)]:
            b = hits.get(sid) or {}
            rows.append((sid, n, best(b.get("examples", []), taken=taken)))
            promoted = True
    return rows[:ROWS], promoted


def asleep(hours: dict) -> int:
    return sum(int(v) for k, v in hours.items() if 1 <= int(k) <= 5)


def scope_line(data: dict, live: tuple) -> str:
    names = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini CLI",
             "normalized": "Imported history"}
    files = data.get("files", 0)
    scope = f"{files:,} {render.plural(files, 'session')}"
    if data.get("files_found", 0) > files:
        scope = f"newest {files:,} of {data['files_found']:,} sessions"
    bits = [" · ".join(names.get(a, signals.clean_label(a)) for a in live), scope]
    start = render.when(data.get("first_ts", ""))
    if start:
        bits.append(f"since {start}")
    return "    ·    ".join(bits)


def headline(data: dict) -> str:
    n = render.n(data["actions"])
    if data.get("files_found", 0) > data.get("files", 0):
        return f"In your last {data['files']:,} sessions, your agents made {n} tool calls."
    return f"Your agents have made {n} tool calls on this machine."


def scan(since_days: int | None = None, agents: tuple | None = None,
         limit: int | None = index.DEFAULT_LIMIT) -> dict:
    found = sources.available()
    live = tuple(a for a in (found if agents is None else agents) if found.get(a))
    skipped = getattr(sources, "compressed_skipped", lambda: 0)()
    if not live:
        render.out(NOTHING.format(demo=render.bold(render.prog("demo"))))
        return {}

    render.out()
    data = index.build(since_days=since_days, agents=live, limit=limit,
                       progress=lambda d, t: render.progress(d, t, f"reading {t:,} session logs"))
    render.clear_progress()
    if not data.get("actions"):
        render.out(f"{render.PAD}No tool calls recorded"
                   + (f" in the last {since_days} days." if since_days else " yet."))
        render.out()
        return data

    render.out(f"{render.PAD}{render.dim(scope_line(data, live))}")
    render.out()
    render.out(f"{render.PAD}{headline(data)}")
    render.out()

    rows, _promoted = select(data)
    night = asleep(data.get("hours", {}))
    if rows:
        pad = max([len(render.n(c)) for _, c, _ in rows] + [len(render.n(night))])
        for sid, count, shown in rows:
            render.out(f"{render.PAD}{render.bold(render.n(count).rjust(pad))}  {signals.BY_ID[sid][0]}")
            for e in shown:
                render.out(f"{render.PAD}{' ' * pad}  {render.dim(render.fit(e[1], pad + 4))}")
            render.out()
        if night:
            render.out(f"{render.PAD}{render.bold(render.n(night).rjust(pad))}  calls recorded between 1am and 6am, your time")
            render.out()
    else:
        render.out(f"{render.PAD}{render.dim('No recorded attempts matched the watched categories.')}")
        render.out()

    shown_ids = {r[0] for r in rows}
    also = sorted(((data["hits"][s]["n"], t) for s, t in ALSO.items()
                   if data.get("hits", {}).get(s, {}).get("n") and s not in shown_ids), reverse=True)
    if also:
        line = " · ".join(f"{render.n(c)} {t}" for c, t in also[:5])
        render.out(f"{render.PAD}{render.dim(render.fit('also   ' + line))}")
        render.out()
    if skipped:
        render.out(f"{render.PAD}{render.dim(f'{skipped:,} compressed Codex logs were skipped: install zstd to read them.')}")
        render.out()
    render.out(f"{render.PAD}{render.dim('Read from your disk. Nothing was sent anywhere.')}")
    render.next_step(render.prog("demo"), "watch the gate stop a command · 5 seconds, nothing installed")
    if data.get("files_found", 0) > data["files"]:
        render.out(f"{render.PAD}{render.dim(render.prog('scan --all'))}   {render.dim('every session ever, not just the newest')}")
        render.out()
    return data


# ---------------------------------------------------------- replaying history

def replay(rule_list: list, data: dict, budget: float = 8.0, progress=None) -> dict:
    """What these rules would have done to the history already on disk.

    -> {"held": {rule: occurrences}, "examples": {rule: [(score, excerpt)]},
        "checked": commands looked at, "total": commands available}
    Most recent first, inside a time budget, so the answer arrives while the
    person is still looking. When the budget runs out the reply says so.
    """
    cmds = data.get("commands", [])
    touched = data.get("touched", [])
    held = {id(r): 0 for r in rule_list}
    examples = {id(r): [] for r in rule_list}
    start = time.time()
    checked = 0
    items = [("cmd", c) for c in cmds] + [("file", t) for t in touched]
    total = len(items)
    for k, (what, item) in enumerate(items):
        if time.time() - start > budget:
            break
        if what == "cmd":
            text, n = (item, 1) if isinstance(item, str) else (item[0], item[1])
            units = shell.history_units(text.replace(" ⏎ ", "\n"))
        else:
            kind, path, n = item
            text = path
            units = [shell.Unit("Read" if kind == "read" else "Write", kind, f"{kind} {path}",
                                paths=[path], writes=[path] if kind == "write" else [])]
        checked += 1
        cats = [(u, rules.categories(u)) for u in units]
        for r in rule_list:
            if any(r.applies(u, c) for u, c in cats):
                held[id(r)] += n
                if len(examples[id(r)]) < 40:
                    examples[id(r)].append((signals.example_score(text, (r.topics or ["egress"])[0]),
                                            rules.excerpt(r, text)))
        if progress and k % 200 == 0:
            progress(k, total)
    return {"held": held, "examples": examples, "checked": checked, "total": total}


SUGGEST = [
    (r"\b(prod|production|live\s+(?:db|database|site))\b", "never touch production"),
    (r"\b(database|\bdb\b|psql|mysql|postgres)\b", "ask me before touching the database"),
    (r"\b(secret|credential|password|api\s*key|token|\.env|dotenv)\b", "never read my .env files"),
    (r"\b(email|mail|message|slack|dm|text)\b", "ask me before sending any email"),
    (r"\b(push|deploy|ship|release|publish|pr\b)\b", "ask me before any git push"),
    (r"\b(delete|remove|rm\b|wipe|destroy|erase)\b", "never delete files outside ~/code"),
    (r"\b(install|package|dependency|npm|pip)\b", "ask me before installing packages"),
    (r"\b(sudo|root|admin|privilege)\b", "never use sudo"),
    (r"\b(curl\s*\|\s*(?:ba)?sh|pipe\s+to\s+shell|run\s+downloaded)\b", "never run code piped from curl"),
    (r"\b(internet|network|upload|download|curl|fetch)\b", "ask me before using the network"),
    (r"\b(cron|schedule|startup|daemon|launchd)\b", "ask me before scheduling anything"),
    (r"\b(background|nohup)\b", "ask me before leaving anything running in the background"),
]


def suggest_for(text: str) -> str | None:
    for pat, rule in SUGGEST:
        if re.search(pat, text, re.I):
            return rule
    return None


def try_rule(text: str, since_days: int | None = None, limit: int | None = index.DEFAULT_LIMIT,
             keep: bool = False) -> int:
    rule = rules.compile_rule(text, 1, source="(typed)")
    render.out()
    if rule is None or not rule.enforced:
        render.out(f"{render.PAD}{render.dim(signals.clean(text))}")
        render.out()
        why = rule.problem if rule is not None else "it is empty"
        if rule is not None and rule.problem == rules.DATA_USE_PROBLEM:
            # the rule a company most wants: not a gap to hide, the way to the part that reads contracts
            render.out(f"{render.PAD}That is a data-use rule. kyma checks what your agent does, not what data is used for.")
            render.out()
            # what the paid side returns for such a sentence: the rule, its clause, who approved it (an example)
            render.out(f"{render.PAD}In Kyma, a rule like it comes from a contract, with its clause and who approved it:")
            render.out(f"{render.PAD}{render.PAD}{render.bold(signals.clean(text).strip().rstrip('.').capitalize() + '.')}")
            render.out(f"{render.PAD}{render.PAD}{render.dim('MSA §7.2 · approved by your legal lead · contract version 3   (an example)')}")
            render.out()
            render.out(f"{render.PAD}{render.bold('https://kyma.stream')}")
            render.out()
            return 2
        render.out(f"{render.PAD}kyma cannot check that sentence: {why}.")
        alt = suggest_for(text)
        if alt:
            render.out()
            render.out(f"{render.PAD}{render.PAD}{render.bold(render.prog('try ' + chr(34) + alt + chr(34)))}")
        render.out()
        render.out(f"{render.PAD}{render.dim('A rule needs a verdict (never, ask me before, may) and a thing: a category')}")
        render.out(f"{render.PAD}{render.dim('like email, push, secrets, sudo, installs, deletes; a path like ~/.ssh;')}")
        render.out(f"{render.PAD}{render.dim('or an exact `command`. kyma rules shows how each line is read.')}")
        render.out()
        return 2

    render.out(f"{render.PAD}{render.bold(rule.text)}")
    render.out(f"{render.PAD}{render.dim('Rule meaning: ' + rule.explain())}")
    render.out()
    data = index.build(since_days=since_days, limit=limit,
                       progress=lambda d, t: render.progress(d, t, "reading your history"))
    render.clear_progress()
    res = replay([rule], data, progress=lambda d, t: render.progress(d, t, "replaying the rule"))
    render.clear_progress()
    n = res["held"][id(rule)]
    verb = {"block": "stopped", "ask": "held for your approval", "allow": "let through"}[rule.verdict]
    partial = res["checked"] < res["total"]
    scope = (f" ({res['checked']:,} of {res['total']:,} distinct commands and paths checked; it ran out of time)"
             if partial else "")
    if data.get("files", 0) < data.get("files_found", 0):
        scope += f" in your newest {data['files']:,} of {data['files_found']:,} logs"
    if not res["total"]:
        render.out(f"{render.PAD}No recorded actions found. This rule has not been tested against your history.")
    elif n:
        render.headline([(n, f"{render.plural(n, 'call')} in your history would have been {verb}{scope}")])
        render.out()
        render.quote([t for _, t in sorted(res["examples"][id(rule)], key=lambda e: -e[0])], 4)
    else:
        render.out(f"{render.PAD}{render.dim('Nothing in your recorded history would have been ' + verb + scope + '.')}")
    if data.get("files", 0) < data.get("files_found", 0):
        render.out(f"{render.PAD}{render.dim(render.prog('try --all ' + chr(34) + rule.text + chr(34)) + ' reads every log.')}")
    render.out()
    if keep:
        from . import enforce
        path = enforce.ensure_rules()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"- {rule.text}\n")
        render.out(f"{render.PAD}Saved to {render.dim(path)}. It applies from the next tool call wherever kyma is on.")
        render.next_step(render.prog("on"), "check every tool call from now on")
    else:
        from . import light
        norm = lambda t: " ".join(t.lower().rstrip(".").split())
        text_now, yours = light.rules_text()
        if any(norm(r.text) == norm(rule.text) for r in rules.parse(text_now)):
            render.out(f"{render.PAD}{render.dim('Already one of your rules.' if yours else 'Already one of the starter rules.')}")
            render.next_step(light.turn_on_command(), "check every tool call from now on")
        else:
            render.out(f"{render.PAD}{render.dim('Not saved yet.')}")
            render.next_step(render.prog("try --keep " + chr(34) + rule.text + chr(34)), "add it to your rules")
    return 0

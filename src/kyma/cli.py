"""kyma -- see what your agents did, then hold the parts you don't want.

    kyma              see what your agents did     (reads logs already on disk)
    kyma see          the same, as a page
    kyma demo         watch the gate stop a command, in a sandbox
    kyma try "..."    replay one rule against your own history
    kyma on / off     check every tool call / stop checking
    kyma stop / go    hold everything, at once / let it run again
    kyma status       is it on, where, and does the hook answer
    kyma rules        how each sentence is read
    kyma log          what was held

Nothing here needs an account, a server, a key, or a config file of ours.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import UnsafeHome

import importlib


class _Later:
    """A module imported on first use. The hook runs on every tool call and
    needs none of the page, demo or scan code; importing it all cost the
    hook a third of its start-up time."""

    def __init__(self, name: str):
        self.__dict__["_name"] = name

    def _mod(self):
        return importlib.import_module("kyma." + self.__dict__["_name"])

    def __getattr__(self, attr):
        return getattr(self._mod(), attr)

    def __setattr__(self, attr, value):
        setattr(self._mod(), attr, value)


demo, enforce, index, mcp, page, render, rules, scan, signals = (
    _Later(n) for n in ("demo", "enforce", "index", "mcp", "page", "render", "rules", "scan", "signals"))

EPHEMERAL_HELP = """  This copy of kyma lives in a cache that gets cleaned up, so a hook
  pointing at it would stop working without a word. Install it first:

      uv tool install git+https://github.com/kymacomputer/kyma-local
      kyma on

  Everything else (kyma, kyma demo, kyma try) works fine from here."""


def _limit(args):
    return None if getattr(args, "all", False) else (getattr(args, "limit", None) or index.DEFAULT_LIMIT)


def cmd_scan(args) -> int:
    scan.scan(since_days=args.days, limit=_limit(args))
    return 0


def cmd_see(args) -> int:
    return page.run(since_days=args.days, limit=_limit(args), open_it=not args.no_open)


def cmd_demo(args) -> int:
    return demo.run()


def cmd_try(args) -> int:
    return scan.try_rule(" ".join(args.rule), since_days=args.days, limit=_limit(args), keep=args.keep)


def _review_changes(where: str, tty=None, ask=input) -> list:
    """Show edits to RULES.md that loosen it; accept them only from a person.

    -> the changes still held back. `tty` and `ask` exist so the tests can
    stand in for the person; in use they are the real terminal."""
    changes = enforce.pending_changes()
    if not changes:
        return []
    tty = sys.stdin.isatty() if tty is None else tty
    render.out(f"{render.PAD}{render.bold(enforce._short(enforce.GLOBAL_RULES) + ' was loosened since you last accepted it:')}")
    for c in changes:
        render.out(f"{render.PAD}{render.PAD}{signals.clean(c)}")
    if not tty:
        render.out(f"{render.PAD}{render.dim('kyma keeps enforcing the rules you accepted. Run ' + render.prog(where) + ' in a terminal to accept.')}")
        render.out()
        return changes
    try:
        yes = ask(f"{render.PAD}Accept these changes? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        yes = False
    if yes and enforce.accept_rules(interactive=True):
        render.out(f"{render.PAD}{render.dim('Accepted. The rules below apply from the next tool call.')}")
        render.out()
        return []
    render.out(f"{render.PAD}{render.dim('Not accepted: the rules you accepted earlier still apply.')}")
    render.out()
    return changes


# `onFailure: "block"` arrived in Claude Code 2.1.295. Before it, a hook that
# cannot start, times out or crashes lets the tool call run.
_FAIL_CLOSED = (2, 1, 295)


def claude_version(run=None):
    """-> (version tuple, text) from `claude --version`, or (None, why). Never raises."""
    import re
    import shutil
    import subprocess
    exe = shutil.which("claude")
    if not exe and run is None:
        return None, "not on PATH"
    try:
        if run is None:
            p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=3)
            text = (p.stdout or p.stderr or "").strip()
        else:
            text = run()
    except Exception as exc:          # a slow or broken binary must not stop `kyma on`
        return None, type(exc).__name__
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return None, (text or "no answer")[:40]
    return tuple(int(x) for x in m.groups()), m.group(0)


def version_warning(run=None) -> str:
    """One line when this Claude Code may run a call whose hook failed, else ''."""
    ver, text = claude_version(run)
    want = ".".join(map(str, _FAIL_CLOSED))
    if ver is None:
        return (f"Claude Code version unknown ({text}). Before {want}, a call runs when the hook "
                f"itself fails. Run `claude update`, then `{render.prog('status')}` to check the version.")
    if ver < _FAIL_CLOSED:
        return (f"Claude Code {text} runs a tool call when the hook itself fails (crash, timeout). "
                f"{want} and later hold it instead. Run `claude update`, then `{render.prog('status')}` to check the version.")
    return ""


def _yes(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{render.PAD}{prompt}").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def cmd_on(args) -> int:
    scope = "project" if getattr(args, "project_only", False) else "global"
    root = enforce.project_root()
    off = enforce.hooks_off_reason(root)
    if off:
        render.out()
        render.out(f"{render.PAD}{render.bold('Not turned on.')} {signals.clean(off)}.")
        render.out()
        return 1
    command = None
    durable, where = enforce.install_is_durable()
    if not durable and enforce._launcher() and where == enforce._launcher():
        # A clone in a temp folder: uv cannot keep a lasting copy of it either.
        render.out()
        render.out(f"{render.PAD}{render.bold('Not turned on.')} This clone is in a temporary folder "
                   f"({signals.clean(enforce._short(os.path.dirname(where)))}), which gets cleaned up, and a hook "
                   "pointing into it would stop working. Move the clone somewhere permanent, then run "
                   f"{render.prog('on')} from there.")
        render.out()
        return 3
    if not durable:
        # The same as answering Y on the first screen: keep a copy, point the hook at it.
        render.out()
        render.out(f"{render.PAD}{render.dim('This copy of kyma lives in a cache. Keeping a copy with uv…')}")
        kept, why = enforce.keep_copy(ask=_yes)
        if not kept:
            render.out()
            render.out(EPHEMERAL_HELP)
            render.out()
            render.out(f"{render.PAD}{render.dim('running from ' + where + ' · ' + why)}")
            render.out()
            return 3
        import shlex
        command = f"{shlex.quote(kept)} hook"
        if os.environ.get("KYMA_HOME"):
            command = f"KYMA_HOME={shlex.quote(enforce.HOME)} {command}"
    fresh = not os.path.lexists(enforce.GLOBAL_RULES)
    try:
        rules_file = enforce.ensure_rules()
    except OSError as exc:
        render.out(f"{render.PAD}{render.bold('Not turned on.')} {signals.clean(exc)}")
        return 1
    if fresh:
        enforce.accept_rules(interactive=True)      # kyma's own template, not an edit
    try:
        path, what = enforce.install(scope, root, command=command)
    except (enforce.InstallError, OSError) as exc:
        if fresh:
            enforce.forget_rules()      # nothing was turned on: leave no RULES.md behind either
        render.out()
        render.out(f"{render.PAD}{render.bold('Not turned on.')} {signals.clean(exc)}")
        render.out()
        return 1
    try:
        loaded, files = enforce.load_rules(root)
    except rules.RulesError as exc:
        loaded, files = [], [rules_file]
        render.out(f"{render.PAD}{render.dim(str(exc))}")
    active = [r for r in loaded if r.enforced]

    where_text = "every project" if scope == "global" else enforce._short(root)
    render.out()
    render.out(f"{render.PAD}{render.bold('On.')}  Every Claude Code tool call in {where_text} is checked "
               f"first. {render.dim('The hook answered its self-test.')}")
    render.out(f"{render.PAD}Continue in Claude Code. It asks you before an action that matches an ask rule. A never rule blocks it.")
    warn = version_warning()
    if warn:
        render.out(f"{render.PAD}{render.dim(warn)}")
    render.out()
    _review_changes("on")

    # A guard that shows nothing looks the same as a broken one. So say what
    # these rules would already have held in the history on this machine.
    data = index.build(limit=index.DEFAULT_LIMIT,
                       progress=lambda d, t: render.progress(d, t, "reading your history"))
    render.clear_progress()
    res = scan.replay(active, data, budget=6.0,
                      progress=lambda d, t: render.progress(d, t, "replaying your rules"))
    render.clear_progress()
    pad = max([len(r.verdict) for r in active] or [5])
    for r in active:
        n = res["held"][id(r)]
        tail = render.dim(f"{n:,} in your history") if n else render.dim("none in your history")
        render.out(f"{render.PAD}{render.PAD}{render.bold(r.verdict.rjust(pad))}  {r.text[:56]:<56} {tail}")
    render.out()
    if res["checked"] < res["total"]:
        note = "Counted over the newest {:,} of {:,} commands.".format(res["checked"], res["total"])
        render.out(f"{render.PAD}{render.dim(note)}")
        render.out()
    skipped = [r for r in loaded if not r.enforced]
    if skipped:
        render.out(f"{render.PAD}{render.dim('Not applied, because kyma cannot check them as written:')}")
        for r in skipped:
            render.out(f"{render.PAD}{render.PAD}{render.dim(r.text)}  {render.dim('(' + r.problem + ')')}")
        render.out()
    render.out(f"{render.PAD}{render.dim('rules')}  {enforce._short(rules_file)}")
    render.out(f"{render.PAD}{render.dim('hook ')}  {enforce._short(path)}  {render.dim(what)}")
    if scope == "project":
        render.out(f"{render.PAD}{render.dim('Only Claude Code sessions started in this project. For every project: ' + render.prog('on --global'))}")
    render.next_step(render.prog("stop"), "if an agent ever needs stopping right now, this holds everything")
    return 0


def _person(what: str) -> bool:
    """Turning kyma off, or letting held calls run again, is a person's act.
    An agent's shell has no terminal; one faked with `script` or `expect` is
    asked about by the hook before it runs."""
    if sys.stdin.isatty():
        return True
    render.out()
    render.out(f"{render.PAD}{render.bold('Not done.')} {render.prog(what)} needs a person at a terminal: "
               "run it yourself in one.")
    render.out()
    return False


def cmd_off(args) -> int:
    if not _person("off"):
        return 1
    scope = "project" if getattr(args, "project_only", False) else "global"
    root = enforce.project_root()
    targets = [(enforce.settings_path(scope, root), scope)]
    if scope == "global":
        # `kyma on --project` installs are recorded; switching off everywhere includes them. So are
        # global installs made under another CLAUDE_CONFIG_DIR, which this shell may not have set.
        targets += [(p, "project") for p, _r in enforce.project_installs() if p != targets[0][0]]
        targets += [(p, "global") for p in _recorded_globals() if p not in [t[0] for t in targets]]
    code = 0
    render.out()
    for path, sc in targets:
        try:
            path, what = enforce.uninstall(sc, root, path=path)
        except (OSError, enforce.InstallError) as exc:
            render.out(f"{render.PAD}Not turned off: {signals.clean(exc)}  {render.dim(signals.clean(enforce._short(path)))}")
            code = 1
            continue
        if what.startswith("left alone"):
            code = 1                          # the hook is still there: not a success
        said = "removed kyma's hook from" if what == "removed" else signals.clean(what)
        render.out(f"{render.PAD}{said}  {render.dim(signals.clean(enforce._short(path)))}")
    render.out()
    return code


def _recorded_globals() -> list:
    """Global installs kyma recorded at a settings file other than today's ~/.claude one."""
    here = enforce.settings_path("global")
    return [p for p, e in enforce._ledger().items() if e.get("scope") == "global" and p != here]


def _command_in(path: str):
    """kyma's hook command in one settings file, or None."""
    try:
        data, _ = enforce._read_settings(path)
    except enforce.InstallError:
        return None
    hooks = data.get("hooks")
    for group in ((hooks.get("PreToolUse") or []) if isinstance(hooks, dict) else []):
        for h in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if isinstance(h, dict) and enforce.is_ours(h.get("command")):
                return h.get("command")
    return None


def _waiting(loaded: list) -> tuple:
    """-> (ids of the RULES.md lines held back until `kyma rules` accepts them, how many
    changes wait, how many lost lines are still applied from the accepted copy)."""
    seen, bad = enforce.accepted()
    text = enforce._read_text(enforce.GLOBAL_RULES)
    if bad or seen is None or text is None or seen == text:
        return set(), 0, 0
    before = enforce._parse_global(seen)
    now = [r for r in loaded if r.trust == "global"]
    changes = enforce.loosened(before, now)
    if not changes:
        return set(), 0, 0
    allow = {enforce._sig(b) for b in before if b.enforced and b.verdict == rules.ALLOW}
    held = set()
    for r in now:
        if not r.enforced:
            continue
        if r.verdict == rules.ALLOW:
            if enforce._sig(r) not in allow:
                held.add(id(r))
            continue
        same = [b for b in before if b.enforced and b.verdict != rules.ALLOW and enforce._sig(b) == enforce._sig(r)]
        if same and max(rules.STRICT[b.verdict] for b in same) > rules.STRICT[r.verdict]:
            held.add(id(r))
    lost = len([c for c in changes if c.startswith("lost ")])
    return held, len(changes), lost


def _lifted(r, loaded: list) -> str:
    """-> how a project's `may` line is limited, or ''. It can never lift a hold
    of yours; with no hold of the project's own to lift, it does nothing."""
    if not (r.enforced and r.trust != "global" and r.verdict == rules.ALLOW):
        return ""
    own = [h for h in loaded if h.enforced and h.trust != "global" and h.verdict != rules.ALLOW]
    return "only" if own else "ignored"


def cmd_stop(args) -> int:
    enforce.halt(" ".join(args.why))
    render.out()
    render.out(f"{render.PAD}{render.bold('Stopped.')}  Every tool call is held from the next one, everywhere kyma is on.")
    render.next_step(render.prog("go"), "let your agents run again")
    return 0


def cmd_go(args) -> int:
    if not _person("go"):
        return 1
    was = enforce.release()
    render.out()
    render.out(f"{render.PAD}{render.bold('Running.') if was else 'Nothing was stopped.'}")
    render.out()
    return 0


def cmd_status(args) -> int:
    root = enforce.project_root()
    clean = signals.clean
    render.out()
    stop = enforce.halted()
    if stop is not None:
        render.out(f"{render.PAD}{render.bold('Stopped')}  every tool call is held · {render.prog('go')} releases it")
        render.out()
    off = enforce.hooks_off_reason(root)
    if off:
        render.out(f"{render.PAD}{render.bold('Off')}   {clean(off)}")
        render.out()
    want = enforce.hook_command()
    mine = enforce.hook_identity(want)
    tested = []

    def state(path: str, cmd: str) -> tuple:
        """-> (word, note) for one installed hook command. Never runs the stored
        string unless it is exactly kyma's own: a cloned repo's settings.local.json
        can hold any command that ends in `kyma hook`."""
        theirs = enforce.hook_identity(cmd)
        if theirs and theirs[0] == "missing":
            return "BROKEN", (f"· its hook runs {clean(theirs[1])[:100]}, which is not there · "
                              f"{render.prog('on')} replaces it")
        if theirs != mine:
            return "OTHER", (f"· its hook command is not this kyma: {clean(cmd)[:120]} · "
                             f"{render.prog('on')} replaces it")
        if not tested:
            tested.append(enforce.self_test(cmd, root, path))
        ok, why = tested[0]
        if not ok:
            return "BROKEN", "· the hook does not run: " + clean(why)
        return ("off" if off else "on "), ""

    gpath = enforce.settings_path("global", root)
    ppath = enforce.settings_path("project", root)
    gcmd, pcmd = enforce.installed_command("global", root), enforce.installed_command("project", root)
    gstate = state(gpath, gcmd) if gcmd else None
    pstate = state(ppath, pcmd) if pcmd else None
    rows = [("this project  " + clean(enforce._short(root)), pstate),
            ("every project  " + clean(enforce._short(gpath)), gstate)]
    for p in _recorded_globals():
        cmd = _command_in(p)
        rows.append(("every project  " + clean(enforce._short(p)) + "  (CLAUDE_CONFIG_DIR)",
                     state(p, cmd) if cmd else None))
    shown_on = False
    for i, (label, st) in enumerate(rows):
        if st is None:
            if i == 0 and gstate and gstate[0].strip() == "on":
                word = "on (global)"
            elif i == 0 and gstate:
                word = f"off (the global hook is {gstate[0].strip()})"
            else:
                word = "off"
            render.out(f"{render.PAD}{render.dim(word)}   {label}")
            continue
        shown_on = True
        render.out(f"{render.PAD}{render.bold(st[0])}   {label}  {render.dim(st[1])}".rstrip())
    if shown_on:
        warn = version_warning()
        if warn:
            render.out(f"{render.PAD}{render.dim(warn)}")
    render.out()
    held = enforce.pending_changes()
    if held:
        render.out(f"{render.PAD}{render.bold('held back:')} {clean(held[0])}"
                   f"{render.dim(' · ' + render.prog('rules') + ' in a terminal to accept')}")
        render.out()
    try:
        loaded, files = enforce.load_rules(root)
        waiting, n_wait, lost = _waiting(loaded)
        for f in files:
            if os.path.exists(f):
                mine_f = [r for r in loaded if r.enforced and os.path.join(r.base, 'RULES.md') == f]
                n = len([r for r in mine_f if id(r) not in waiting and _lifted(r, loaded) != "ignored"])
                tail = ""
                if f == enforce.GLOBAL_RULES or os.path.realpath(f) == os.path.realpath(enforce.GLOBAL_RULES):
                    n += lost                     # a line taken out stays applied until you accept that
                    if n_wait:
                        tail = f", {n_wait} waiting for you"
                ignored = len([r for r in mine_f if _lifted(r, loaded) == "ignored"])
                if ignored:
                    tail += f", {ignored} ignored (a project cannot lift your holds)"
                said = "applied" if shown_on else "not checked: kyma is off"
                render.out(f"{render.PAD}{render.dim(clean(enforce._short(f)))}  {n} {render.plural(n, 'rule')} {said}{tail}")
    except rules.RulesError as exc:
        render.out(f"{render.PAD}{render.bold('rules unreadable:')} {clean(exc)}")
    render.out(f"{render.PAD}{render.dim(f'{enforce.checked_total():,} tool calls checked so far')}")
    render.out()
    return 0


def cmd_rules(args) -> int:
    root = enforce.project_root()
    render.out()
    _review_changes("rules")
    try:
        loaded, files, missing = enforce.rules_view(root)
    except rules.RulesError as exc:
        render.out(f"{render.PAD}{render.bold('kyma cannot read your rules:')} {signals.clean(exc)}")
        render.out()
        return 1
    if missing:
        render.out(f"{render.PAD}{render.bold('RULES.md is missing.')} The accepted rules below still apply.")
        if _yes("Restore the accepted RULES.md? [y/N] "):
            restored = enforce.restore_accepted_rules(interactive=True)
            try:
                loaded, files, missing = enforce.rules_view(root)
            except rules.RulesError as exc:
                render.out(f"{render.PAD}No file was overwritten. {signals.clean(exc)}")
                return 1
            if restored:
                render.out(f"{render.PAD}Restored the accepted RULES.md.")
            elif not missing:
                render.out(f"{render.PAD}RULES.md changed while you chose. No file was overwritten.")
                changes, effective = enforce.held_back(loaded, write=False)
                if changes:
                    loaded = effective
                    render.out(f"{render.PAD}The accepted holds below still apply. Run {render.prog('rules')} again to review the new file.")
            else:
                render.out(f"{render.PAD}The accepted file could not be restored. Its rules still apply.")
        else:
            render.out(f"{render.PAD}Run {render.prog('rules')} in a terminal to restore the accepted copy.")
        render.out()
    for f in files:
        state = "  (missing; accepted copy active)" if missing and f == enforce.GLOBAL_RULES else \
            "" if os.path.exists(f) else "  (not written yet)"
        render.out(f"{render.PAD}{render.dim(signals.clean(enforce._short(f)) + state)}")
    render.out()
    if not loaded:
        # nothing written: show the starter rules kyma is applying, numbered as it cites them
        render.out(f"{render.PAD}{render.dim('starter rules, written to ~/.kyma/RULES.md by ' + render.prog('on'))}")
        render.out()
        for r in enforce.starter_rules():
            render.out(f"{render.PAD}{r.line}  {r.text}")
            render.out(f"{render.PAD}   {render.dim(r.explain())}")
        render.next_step(render.prog('try "ask me before any git push"'), "test a rule against your history")
        return 0
    waiting, _n, _lost = _waiting(loaded)
    for r in loaded:
        lift = _lifted(r, loaded)
        mark = " " if r.enforced and id(r) not in waiting and lift != "ignored" else "·"
        note = ("  " + render.dim("(waiting: " + render.prog("rules") + " to accept)") if id(r) in waiting else
                "  " + render.dim("(ignored: a project cannot lift your holds)") if lift == "ignored" else
                "  " + render.dim("(this project's own rules only: a project cannot lift your holds)") if lift else "")
        render.out(f"{render.PAD}{mark} {signals.clean(r.text)}{note}")
        render.out(f"{render.PAD}   {render.dim(r.explain())}")
    render.out()
    return 0


def cmd_log(args) -> int:
    entries = enforce.held(args.limit)
    totals = enforce.log_totals()
    checked = enforce.checked_total()
    render.out()
    if not entries:
        render.headline([(checked, "tool calls checked")])
        render.out()
        render.out(f"{render.PAD}{render.dim('Nothing held.')}")
        render.out()
        return 0
    # The headline counts the whole log; the list below is only its newest page.
    n_held, n_err = totals["held"], totals["errors"]
    render.headline([(checked, "tool calls checked"), (n_held, "held")]
                    + ([(n_err, "kyma errors, each held for your approval")] if n_err else []))
    if n_held + n_err > len(entries):
        render.out(f"{render.PAD}{render.dim(f'showing the last {len(entries):,} of {n_held + n_err:,}')}")
    render.out()
    for e in entries:
        what = e.get("verdict", "")
        when = signals.clean(e.get("ts", ""))
        try:
            from datetime import datetime
            when = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            when = when[:16]
        render.out(f"{render.PAD}{render.PAD}{when}  {render.bold(what)}  "
                   f"{render.dim(render.fit(e.get('subject') or e.get('error') or '', 30))}")
        if e.get("rule"):
            render.out(f"{render.PAD}{render.PAD}{render.dim('  ' + signals.clean(e.get('rule', '')) + '  [' + signals.clean(e.get('where', '')) + ']')}")
    render.out()
    return 0


EXIT = {"allow": 0, "ask": 1, "block": 2}
USAGE = 3                  # never 1 or 2: a script reading the exit code must not take a typo for a verdict


def _here() -> str:
    try:
        return os.getcwd()
    except OSError:          # the folder was deleted under us: judge from the top, no project rules
        return "/"


def cmd_check(args) -> int:
    """For any agent that is not Claude Code: one call in, a verdict and an exit code out.

    Exit 0 allow, 1 ask, 2 block, 3 a usage error. Anything kyma cannot finish
    is an ask, never an allow."""
    import json
    import shlex
    if args.json:
        try:
            payload = json.loads(sys.stdin.read() or "null")
        except (ValueError, RecursionError):
            payload = None
        # a tool with nothing to judge is a malformed request, not a harmless call
        if not isinstance(payload, dict) or enforce.input_problem(payload.get("tool_name"), payload.get("tool_input")):
            print('usage: kyma check --json  reads {"tool_name": "...", "tool_input": {...}} on stdin',
                  file=sys.stderr)
            return USAGE
        tool, inp = payload["tool_name"], payload.get("tool_input")
        if inp is None:
            inp = {}
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else _here()
    else:
        words = list(args.command)
        # One argument is the command exactly as written. Several are argv,
        # so they are quoted back: `-- bash -lc 'git push'` must stay one -lc
        # script, and `-- echo 'a; sudo ls'` one harmless echo.
        text = words[0] if len(words) == 1 else shlex.join(words)
        if not text.strip():
            print("usage: kyma check [--tool NAME] -- COMMAND   (or --json on stdin)", file=sys.stderr)
            return USAGE
        tool, cwd = args.tool, _here()
        inp = enforce.input_for(tool, text)
    try:
        ans = enforce.verdict_for(tool, inp, cwd=cwd)
    except Exception as exc:
        print(f"ask  kyma hit an error ({type(exc).__name__}), so this needs your approval. [kyma]")
        return EXIT["ask"]
    print(ans["verdict"] + "  " + signals.clean(ans["reason"]))
    return EXIT[ans["verdict"]]


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kw):
        self.beginner = kw.pop("beginner", False)
        kw.setdefault("allow_abbrev", False)     # `kyma try x --kee` must not be `--keep` behind a reader's back
        super().__init__(*args, **kw)

    def format_help(self):
        if not self.beginner:
            return super().format_help()
        text = """Kyma shows what Claude Code and Codex tried on this computer.

  kyma                          See your past activity. Changes nothing.
  kyma demo                     Try a safe example with no setup.
  kyma try "Ask me before email" Test a rule against your past activity.

Turn checks on:

  kyma on --global              Add checks to all Claude Code projects.
  kyma status                   See whether checks are on and where.
  kyma off --global             Remove all checks.

For one project, open its folder in your terminal and use PROJECT_ON_COMMAND.
Use PROJECT_OFF_COMMAND from the same folder to remove those checks.

Claude Code asks you before an action that matches an "ask" rule.
Codex history is visible here. Automatic checks support Claude Code.

  kyma --details                Show the full terminal report.
  kyma help --all               Show every command and option.
  kyma COMMAND --help           Show options for one command.
"""
        return (text.replace("kyma ", render.prog() + " ")
                .replace("PROJECT_ON_COMMAND", render.prog("on --project", absolute=True))
                .replace("PROJECT_OFF_COMMAND", render.prog("off --project", absolute=True)))

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="kyma", beginner=True, description="See the agents you have run and what your rules would have stopped. "
                                         "Then turn the rules on.")
    from . import __version__
    p.add_argument("--version", action="version", version=f"kyma {__version__}")
    p.add_argument("--details", action="store_true", help="show the complete terminal history view")
    p.add_argument("--no-open", action="store_true", help="write the page, do not open it")
    sub = p.add_subparsers(dest="cmd", metavar="command", parser_class=_Parser)

    def with_history(sp):
        sp.add_argument("--days", type=int, default=None, help="only the last N days")
        sp.add_argument("--all", action="store_true", help="every session, not just the newest 400")
        sp.add_argument("--limit", type=int, default=None, help="how many recent sessions to read")
        return sp

    with_history(sub.add_parser("scan", help="what your agents did, as text")).set_defaults(func=cmd_scan)
    v = with_history(sub.add_parser("see", help="the same, as a page you can keep"))
    v.add_argument("--no-open", action="store_true", help="write the page, do not open it")
    v.set_defaults(func=cmd_see)
    sub.add_parser("demo", help="try a safe example with no setup").set_defaults(func=cmd_demo)
    t = with_history(sub.add_parser("try", help='replay a rule against your history: kyma try "never use sudo"'))
    t.add_argument("rule", nargs="+")
    t.add_argument("--keep", action="store_true", help="add the rule to your rules")
    t.set_defaults(func=cmd_try)
    o = sub.add_parser("on", help="turn on checks for Claude Code")
    o.add_argument("--global", dest="globally", action="store_true", help="every project (the default)")
    o.add_argument("--project", dest="project_only", action="store_true", help="only this project")
    o.set_defaults(func=cmd_on)
    f = sub.add_parser("off", help="stop checking")
    f.add_argument("--global", dest="globally", action="store_true", help="every project (the default)")
    f.add_argument("--project", dest="project_only", action="store_true", help="only this project")
    f.set_defaults(func=cmd_off)
    s = sub.add_parser("stop", help="hold every tool call, at once, until kyma go")
    s.add_argument("why", nargs="*", help="a note for your agent")
    s.set_defaults(func=cmd_stop)
    sub.add_parser("go", help="let your agents run again").set_defaults(func=cmd_go)
    sub.add_parser("status", help="see whether checks are on and where").set_defaults(func=cmd_status)
    sub.add_parser("rules", help="how each rule is read").set_defaults(func=cmd_rules)
    lg = sub.add_parser("log", help="what was held")
    lg.add_argument("--limit", type=int, default=20)
    lg.set_defaults(func=cmd_log)
    c = sub.add_parser("check", help="a verdict for one call, for agents without hooks")
    c.add_argument("--tool", default="Bash", help="the tool about to run (Bash, shell, exec_command, Write, Read, Glob...)")
    c.add_argument("--json", action="store_true", help='read {"tool_name", "tool_input"} from stdin')
    c.add_argument("command", nargs="*")
    c.set_defaults(func=cmd_check)
    sub.add_parser("mcp", help="serve the same verdicts over MCP (reporting only)")
    return p


def main(argv=None) -> int:
    # Everything kyma writes holds excerpts of shell history: owner-only.
    os.umask(0o077)
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["hook"]:
        from . import enforce as _enforce
        return _enforce.hook()
    try:
        rc = _main(argv)
        sys.stdout.flush()           # a closed pipe surfaces here, not at exit
        return rc
    except BrokenPipeError:
        # `kyma try … | head`: the reader left; leave quietly, as other tools do.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 0
    except UnsafeHome as exc:
        print(f"kyma: {exc}.", file=sys.stderr)
        return 1


def _main(argv) -> int:
    if argv[:1] not in (["check"], ["mcp"]):
        from . import remask_log
        remask_log()             # history migration must not delay a decision or MCP initialization
    try:
        for gone in enforce.removed_hooks():
            # kyma off forgets an install; anything else that took the hook out is reported, every run
            print(f"kyma: its hook was taken out of {enforce._short(gone)} by something other than "
                  f"`kyma off`, so nothing is being checked there. `kyma on` puts it back.", file=sys.stderr)
    except Exception:
        pass
    if argv[:1] == ["mcp"] and not any(a in ("-h", "--help") for a in argv[1:]):
        return mcp.serve()
    parser = build_parser()
    if argv == ["help", "--all"] or argv == ["--help-all"]:
        parser.beginner = False
        parser.print_help()
        return 0
    if argv == ["help"]:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if args.cmd is None:
        from . import light
        try:
            return light.run(open_it=not args.no_open, details=args.details)
        except KeyboardInterrupt:
            # Leave the terminal as it was: cursor shown, a clean line, no traceback.
            if sys.stdout.isatty():
                sys.stdout.write("\x1b[?25h\r\x1b[K")
            sys.stdout.write("\n")
            return 130
        except BrokenPipeError:
            # `kyma | head`: the reader left. Quietly, and without a second error at exit.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            return 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)

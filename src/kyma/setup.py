"""Noninteractive setup for an agent that acts on the user's behalf."""

from __future__ import annotations

import json
import os
import shlex
from collections import Counter
from pathlib import Path

from . import enforce, history_scope, light, render, rules, signals, sources
from .cli import _FAIL_CLOSED, claude_version


HOST_NAMES = {
    "claude": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini CLI",
}
HOST_MARKERS = {
    "claude": "CLAUDECODE", "codex": "CODEX_THREAD_ID", "cursor": "CURSOR_AGENT", "gemini": "GEMINI_CLI",
}


def _auto_host(available: Counter) -> str:
    # The calling session is stronger evidence than the other hosts' old logs.
    found = [host for host, marker in HOST_MARKERS.items() if os.environ.get(marker)]
    found = found or [host for host in HOST_NAMES if available[host]]
    return found[0] if len(found) == 1 else "auto"


def _clean_error(error) -> str:
    return signals.clean(signals.redact(str(error)))


def _hook_entries(path: str) -> list:
    settings, _ = enforce._read_settings(path)
    hooks = settings.get("hooks")
    groups = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    entries = []
    for group in groups if isinstance(groups, list) else ():
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        entries.extend((group, hook) for hook in group["hooks"]
                       if isinstance(hook, dict) and enforce.is_ours(hook.get("command")))
    return entries


def _all_calls(group: dict, hook: dict) -> bool:
    return (group.get("matcher") in (None, "", "*", ".*") and hook.get("type") == "command"
            and not hook.get("if") and not hook.get("async") and not hook.get("asyncRewake"))


def _enable_claude(root: str, scope: str | None) -> dict:
    def blocked(reason, next_action, **details):
        return {"checks": "blocked", "reason": _clean_error(reason), "next_action": next_action, **details}

    if scope is None or (scope == "project" and not os.path.exists(os.path.join(root, ".git"))):
        again = render.prog("setup --host claude --global")
        return blocked("Claude Code project setup needs a Git project.",
                       f"Run setup from a Git project, or run {again} for all projects.")
    again = render.prog(f"setup --host claude --{scope}", absolute=True)
    off = enforce.hooks_off_reason(root)
    if off:
        return blocked(off, f"Review the Claude Code hook policy, then rerun {again}.", hooks_disabled=True)
    version, detail = claude_version(verify_host=True)
    minimum = ".".join(str(part) for part in _FAIL_CLOSED)
    if version is None or version < _FAIL_CLOSED:
        reason = (f"Claude Code {detail} cannot block a tool call when the hook fails." if version else
                  f"Claude Code version unverified ({detail}).")
        return blocked(reason, f"Use Claude Code {minimum} or later, then rerun {again}.", claude_version=detail if version else None)
    host = {"claude_version": detail}
    if not os.path.isdir(sources.claude_dir()):
        return blocked("Claude Code has no local configuration directory.",
                       f"Start Claude Code once, then rerun {again}.", **host)
    durable, _ = enforce.install_is_durable()
    if not durable:
        spec = enforce._source_spec() or (str(Path(__file__).resolve().parents[2]) if enforce._launcher() else light.SOURCE)
        install = f"uv tool install {shlex.quote(spec)}"
        return blocked("The running copy of Kyma lives in a temporary location.",
                       f"Run {install}, then kyma setup --host claude --{scope}.",
                       install_command=install, **host)
    path = os.path.abspath(enforce.settings_path(scope, root))
    if scope == "project" and os.path.commonpath([root, os.path.realpath(path)]) != root:
        return blocked("Claude Code project settings resolve outside this Git project.",
                       f"Review {path}, then rerun {again}.", **host)

    try:
        # Serialize setup's own contenders for the shared rule file and the installs ledger.
        with enforce._Locked(enforce.INSTALLS):
            existing = _hook_entries(path)
            if existing and not any(_all_calls(group, hook) for group, hook in existing):
                return blocked("The existing Kyma hook has restricted coverage.",
                               f"Review the Kyma PreToolUse entry in {path}, then rerun {again}.", **host)
            accepted, bad = enforce.accepted()
            review = render.prog("rules", absolute=True)
            if bad:
                return blocked(bad, f"Run {review} in a terminal to review the rules.", **host)
            if accepted is None:
                enforce.ensure_rules()  # Only the shipped starter, and only when the file is absent.
            enforce.load_rules(root)
            command = enforce.hook_command()
            path, change = enforce.install(scope, root, command=command)
            if not any(_all_calls(group, hook) and hook.get("command") == command and hook.get("onFailure") == "block"
                       for group, hook in _hook_entries(path)):
                return blocked("The verified Kyma hook does not match the saved PreToolUse entry.",
                               f"Review {path}, then rerun {again}.", **host)
            off = enforce.hooks_off_reason(root)
            if off:
                return blocked(off, f"Review the Claude Code hook policy, then rerun {again}.", hooks_disabled=True, **host)
            pending = len(enforce.pending_changes())
    except (OSError, enforce.InstallError, rules.RulesError) as exc:
        return blocked(exc, f"Resolve the reported issue, then rerun {again}.", **host)

    next_action = "Continue in Claude Code. The installed hook answered its self-test."
    if pending or not os.path.lexists(enforce.GLOBAL_RULES):
        next_action = f"Run {review} in a terminal to review the rules. The accepted rules still apply."
    return {"checks": "on", "settings_path": os.path.abspath(path), "change": change,
            "pending_rule_changes": pending, "next_action": next_action, **host}


def _emit(receipt: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(receipt, separators=(",", ":")))
    else:
        name = HOST_NAMES.get(receipt["host"], "Kyma")
        coverage = receipt["coverage"]
        checks = receipt["checks"]
        status = f"Checks on ({receipt['scope']})" if checks == "on" else (
            "Checks unverified" if checks == "blocked" else "Report only")
        render.out(f"{name} · {status} · {coverage['actions']:,} recorded calls in "
                   f"{coverage['selected_files']:,} of {coverage['available_files']:,} logs.")
        for key in ("reason", "report_error"):
            if receipt.get(key):
                render.out(receipt[key])
        if receipt["report_path"]:
            render.out(f"Report  {signals.clean(receipt['report_path'])}")
        render.out(receipt["next_action"])
    return int(receipt["checks"] == "blocked" or receipt["report_path"] is None)


def run(args) -> int:
    available = light.files()
    counts = Counter(host for _, host in available)
    host = _auto_host(counts) if args.host == "auto" else args.host
    root = enforce.project_root()
    scope = args.setup_scope or ("project" if os.path.exists(os.path.join(root, ".git")) else None)
    work, coverage = history_scope.select(available)
    coverage.update(available_by_host=dict(sorted(counts.items())), actions=0, checked_calls=0)
    receipt = {"host": host, "scope": scope if host == "claude" else None,
               "capability": "automatic-checks" if host == "claude" else "report-only",
               "checks": "blocked" if host == "claude" else "report-only",
               "report_path": None, "opened": False, "coverage": coverage}
    try:
        report = light.report_data(work, coverage, include_empty=True)
    except OSError as exc:
        receipt.update(report_error=_clean_error(exc), next_action="Resolve the report error, then rerun setup.")
        return _emit(receipt, args.json)
    coverage.update(actions=report["actions"], checked_calls=report["checked_calls"],
                    replayed_files=report["judged"], partial_logs=report["partial_logs"])

    if host == "claude":
        receipt.update(_enable_claude(root, scope))
    elif host == "auto":
        receipt["next_action"] = "Choose an explicit --host to set up a specific agent."
    elif report["actions"]:
        receipt["next_action"] = "Inspect a recorded tool call in the local report."
    else:
        receipt["next_action"] = f"Run an agent task, then repeat {render.prog(f'setup --host {host}')}. "
        receipt["next_action"] += f"Use {render.prog('demo')} to see an example now."

    try:
        receipt["report_path"] = os.path.abspath(light.page(report, setup_checks=receipt))
    except OSError as exc:
        receipt.update(report_error=_clean_error(exc), next_action="Resolve the report error, then rerun setup.")
    if receipt["report_path"] and not args.no_open:
        import webbrowser
        try:
            receipt["opened"] = bool(webbrowser.open(Path(receipt["report_path"]).as_uri()))
        except (OSError, webbrowser.Error):
            pass
    return _emit(receipt, args.json)

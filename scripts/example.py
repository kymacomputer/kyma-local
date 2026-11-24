"""The README picture: a made-up developer, never anyone's real history.

A real picture is someone's working and sleeping hours, so the README shows
an invented person: 110 days with Claude Code, weekdays beside the agent,
then the nights it was left running, and a few moments the starting rules
would have stopped. Seeded, so the picture is reproducible:

    python3 scripts/example.py docs/example.html

It writes real transcripts into a throwaway home and runs kyma on them.
"""
import datetime as dt
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


PROJECTS = ["app", "api", "infra"]
MODELS = ["claude-opus-5", "claude-opus-5", "claude-sonnet-5"]
TASKS = ["add the export button to the reports page", "why is test_checkout flaky on CI", "refactor the auth middleware",
         "migrate the billing tables to the new schema", "ship the onboarding flow", "fix the deploy script for staging",
         "upgrade to React 19", "make the search endpoint paginate", "write the webhook retry logic",
         "move the cron jobs to the queue", "add rate limiting to the public API", "clean up the feature flags",
         "port the CLI to Go", "find the memory leak in the worker", "add SSO with Okta", "speed up the test suite",
         "localise the dashboard into French", "replace moment with date-fns", "add a dark mode toggle",
         "set up preview deploys", "document the REST API", "fix the CSV import encoding bug",
         "add audit logging to admin actions", "split the monolith's billing module"]
SUBAGENTS = [("general-purpose", "Review the diff for regressions", "opus"),
             ("Explore", "Find every caller of the auth middleware", "sonnet"),
             ("general-purpose", "Run the test suite and fix failures", "opus"),
             ("Plan", "Plan the billing migration", "opus"),
             ("Explore", "Map where feature flags are read", "sonnet"),
             ("general-purpose", "Reproduce the flaky checkout test", "opus"),
             ("general-purpose", "Check the deploy script against staging", "sonnet"),
             ("Plan", "Plan the queue migration", "opus"),
             ("Explore", "Find slow queries in the search endpoint", "sonnet"),
             ("general-purpose", "Write tests for the webhook retries", "opus")]


# Each session its own first ask: a repeated title reads as a duplicate card.
TASK_POOL = TASKS + [
    "the invoice PDF cuts off the last line", "why does signup send two emails", "add an audit log for admin actions",
    "search ranks old posts above new ones", "CSV import chokes on quoted commas", "mobile nav covers the logo on iOS",
    "lower the rate limit for anonymous users", "uploads over 10 MB time out", "sessions expire while people type",
    "the billing webhook retries forever", "dark mode toggle forgets the choice", "team invites land in spam",
    "paginate /api/orders", "the 404 page has no way home", "cache the pricing table for an hour",
    "split utils.ts, it's 2k lines", "write a migration to drop legacy_users", "flaky snapshot in Header.test.tsx",
    "bump node to 22 in CI", "the onboarding checklist skips step 3", "port the cron script to a queue worker",
    "why is the dashboard slow on Mondays", "add Sentry to the worker", "replace lodash.get with optional chaining",
    "make the settings form keyboard friendly", "stop logging request bodies", "dedupe the customer import",
    "add a health check for the queue", "fix the timezone bug in reports", "rename Account to Workspace in the UI",
    "the export button is disabled for admins", "turn off the old feature flag for search", "tidy the Dockerfile",
    "make tests run in parallel", "the email preview breaks in Outlook", "add an index for orders.created_at",
    "investigate the memory leak in the worker", "write docs for the webhook API", "the password reset link expires instantly",
    "translate the error messages", "move secrets to the vault", "the chart tooltips overlap on mobile",
    "lint warnings in the auth module", "set up preview deploys", "add retries to the S3 client",
    "drag and drop reorders the wrong item", "make the CLI print JSON with --json", "graphql query is n+1 on comments",
    "bump the API version header", "a test for the refund edge case", "the sitemap misses blog posts",
    "update the privacy page copy", "remove the unused admin routes", "make the logo crisp on retina",
    "load testing for checkout", "the queue backs up after deploys", "replace moment in the date picker",
    "check why builds take 14 minutes", "add a CSV export to the audit log", "fix the off-by-one in pagination",
    "make the empty state friendlier", "SSO users can't change their email", "make the API key page show last used",
    "archive projects older than a year", "the invoice totals round wrong in EUR", "draft the release notes for 2.4",
]


def _write(path: str, lines: list) -> None:
    # a made-up night that runs past now has not happened yet; and the example
    # history has ended, so its last call is well outside "still running"
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
    lines = [l for l in lines if l.get("timestamp", "")[:19] <= cut]
    native = []
    for i, line in enumerate(lines):
        native.append(line)
        if line.get("type") != "assistant":
            continue
        results = []
        for j, block in enumerate(line.get("message", {}).get("content", [])):
            if block.get("type") != "tool_use":
                continue
            block["id"] = f"example-{i}-{j}"
            command = block.get("input", {}).get("command", "")
            # These invented results show the native join, not a real effect.
            # Scheduled tasks deliberately retain a missing result.
            if command.startswith(("cat .env", "git push", "sudo ", "gog gmail send")):
                results.append({"type": "tool_result", "tool_use_id": block["id"],
                                "is_error": command.startswith("sudo ") or "--force" in command,
                                "content": "Synthetic tool result."})
        if results:
            native.append({"timestamp": line["timestamp"], "type": "user",
                           "message": {"role": "user", "content": results}})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in native:
            fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    # a real log was last written at its last event, not when this script ran
    last = max((l.get("timestamp", "") for l in lines), default="")
    if last:
        t = dt.datetime.strptime(last[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
        os.utime(path, (t, t))


def write_history(home: str) -> None:
    """A made-up developer: three projects, Opus and Sonnet, subagents, one Codex habit."""
    rng = random.Random(11)
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    work = ["npm test", "npm run build", "git status", "git diff", "pytest -q", "ls src", "cat package.json",
            "git add -A", "git commit -m 'wip'", "rg TODO src", "npx tsc --noEmit", "docker compose up -d db"]
    risky = {12: "cat .env", 30: "git push origin main", 41: "sudo chown -R me /usr/local",
             55: "git push --force origin main", 63: "crontab -l | { cat; echo '0 3 * * * ~/bin/sync.sh'; } | crontab -",
             77: "cat .env.local", 88: "git push origin main",
             97: "gog gmail send --to team@acme.dev --subject 'nightly report' --body done", 104: "cat .env"}
    # risky acts done by a subagent, not the session itself: who started whom matters
    sub_risky = {6: "cat .env.production", 14: "git push --force origin main", 3: "sudo rm -rf /usr/local/lib/node_modules"}
    for d in range(110, 0, -1):
        day = now - dt.timedelta(days=d)
        if day.weekday() >= 5 and rng.random() < .7:
            continue
        proj = PROJECTS[d % 3]
        cwd = f"/Users/dev/code/{proj}"
        model = MODELS[d % 3]
        lines = []
        start = day.replace(hour=14 + rng.choice([0, 0, 1]))          # 9-10am in New York
        meta = lambda ts: {"timestamp": ts, "cwd": cwd, "entrypoint": "cli", "sessionId": f"s{d:03d}"}
        for k in range(rng.randint(5, 9)):
            t = start + dt.timedelta(hours=k, minutes=rng.randint(0, 50))
            ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            ask = TASK_POOL[d % len(TASK_POOL)] if not k else rng.choice(["now add tests", "ship it", "why did that fail", "try again", "looks good, continue"])
            lines.append(dict(meta(ts), type="user", message={"role": "user", "content": ask}))
            for _ in range(rng.randint(2, 9)):
                lines.append(dict(meta(ts), type="assistant", message={"model": model, "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": rng.choice(work)}}]}))
            if k == 2 and d in risky:
                lines.append(dict(meta(ts), type="assistant", message={"model": model, "content": [
                    {"type": "tool_use", "name": "Bash", "input": {"command": risky[d]}}]}))
        if d < 70 and rng.random() < min(.95, (70 - d) / 30):        # the nights left running
            for h in range(rng.randint(3, 8)):
                t = start + dt.timedelta(hours=10 + h + rng.randint(0, 2))
                ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                if h == 2 and d in (22, 9):
                    lines.append(dict(meta(ts), type="assistant", message={"model": model, "content": [{"type": "tool_use",
                        "name": "Bash", "input": {"command": "git push --force origin main" if d == 22 else "cat .env.production"}}]}))
                for _ in range(rng.randint(5, 30)):
                    lines.append(dict(meta(ts), type="assistant", message={"model": model, "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": rng.choice(work)}}]}))
        session = os.path.join(home, ".claude", "projects", f"-Users-dev-code-{proj}", f"s{d:03d}.jsonl")
        _write(session, lines)
        # the recent sessions start subagents, as real ones do
        if d <= 20 and d % 2 == 0 or d in sub_risky:
            for n in range(1 + d % 3):
                kind, task, sub_model = SUBAGENTS[(d * 3 + n) % len(SUBAGENTS)]
                aid = f"agent-a{d:03d}{n}"
                t = start + dt.timedelta(hours=1 + n, minutes=15)
                ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                sub = [dict(meta(ts), type="user", isSidechain=True, agentId=aid, message={"role": "user", "content": task})]
                for _ in range(rng.randint(4, 20)):
                    t += dt.timedelta(seconds=rng.randint(20, 150))      # subagents take minutes, not an instant
                    ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    sub.append(dict(meta(ts), type="assistant", isSidechain=True, agentId=aid, message={
                        "model": "claude-opus-5" if sub_model == "opus" else "claude-sonnet-5",
                        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": rng.choice(work)}}]}))
                if n == 0 and d in sub_risky:
                    sub.append(dict(meta(ts), type="assistant", isSidechain=True, agentId=aid, message={
                        "model": "claude-opus-5", "content": [{"type": "tool_use", "name": "Bash",
                                                               "input": {"command": sub_risky[d]}}]}))
                folder = os.path.join(os.path.splitext(session)[0], "subagents")
                _write(os.path.join(folder, aid + ".jsonl"), sub)
                with open(os.path.join(folder, aid + ".meta.json"), "w") as fh:
                    json.dump({"agentType": kind, "description": task, "model": sub_model, "spawnDepth": 1,
                               "finished": True}, fh)
    # a Codex habit: a few long sessions on infra
    for d in (5, 2):
        t0 = now - dt.timedelta(days=d, hours=-16)
        ts0 = t0.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        rows = [{"timestamp": ts0, "type": "session_meta", "payload": {"cwd": "/Users/dev/code/infra", "originator": "codex_cli_rs"}},
                {"timestamp": ts0, "type": "turn_context", "payload": {"model": "gpt-6.2-sol", "cwd": "/Users/dev/code/infra"}},
                {"timestamp": ts0, "type": "event_msg", "payload": {"type": "user_message", "message": {5: "tidy the terraform modules", 2: "rotate the staging certificates"}[d]}}]
        for k in range(rng.randint(20, 40)):
            ts = (t0 + dt.timedelta(minutes=3 * k)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            rows.append({"timestamp": ts, "type": "response_item", "payload": {"type": "function_call", "name": "shell",
                         "arguments": json.dumps({"command": ["bash", "-lc", rng.choice(["terraform plan", "git diff", "ls"])]})}})
        day = t0.strftime("%Y/%m/%d")
        _write(os.path.join(home, ".codex", "sessions", day, f"rollout-{t0:%Y-%m-%dT%H-%M-%S}-cdx{d}.jsonl"), rows)


if __name__ == "__main__":
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "docs", "example.html"))
    home = tempfile.mkdtemp(prefix="kyma-example-")
    write_history(home)
    env = dict(os.environ, HOME=home, KYMA_HOME=os.path.join(home, ".kyma"), TZ="America/New_York")
    subprocess.run([sys.executable, os.path.join(HERE, "..", "kyma"), "--no-open"], env=env, check=True,
                   stdout=subprocess.DEVNULL)
    with open(os.path.join(home, ".kyma", "kyma.html"), encoding="utf-8") as fh:
        page = fh.read()
    # The shared example must not inherit the author's local executable path.
    prefix, marker, tail = page.partition("const D = ")
    if not marker:
        raise ValueError("Example page has no data payload")
    data, end = json.JSONDecoder().raw_decode(tail)
    data["cmd"] = "uvx --from git+https://github.com/kymacomputer/kyma-local kyma on"
    data["example"] = True
    runner = data["cmd"][:-3]
    data["on"], data["on_scope"], data["on_project"] = False, "", "app"
    data["hooks_off"], data["hooks_off_reason"], data["setup_recovery"] = False, "", []
    for scope, mode in data["setup_modes"].items():
        scope_prefix = 'cd "$HOME/code/app" && ' if scope == "project" else 'cd "$HOME" && '
        mode.update(name="app" if scope == "project" else "All projects",
                    on=scope_prefix + runner + " on --" + scope,
                    review=scope_prefix + runner + " rules", check=runner + " status && " + runner, report=runner,
                    off=scope_prefix + runner + " off --" + scope,
                    files=[{"path": "~/.kyma/RULES.md", "title": "Your rules · shared by active projects", "edit": ""}])
    page = prefix + marker + json.dumps(data, separators=(",", ":")) + tail[end:]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    shutil.rmtree(home, ignore_errors=True)
    print(out)

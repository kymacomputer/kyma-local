# Changelog

## 0.5.0 — 2026-11-24

The repository's product changes from the contract kit to a local check for coding agents.

- `kyma`: a local report of what Claude Code and Codex tried, with the exact command and rule for each match. The terminal starts with one concrete example. Agent relationships and activity hours remain in the detailed view.
- The dark report connects a task, its agent, an attempted action, and its rule. Native results join through exact call IDs. Missing or ambiguous results stay unknown.
- First-run setup offers this project, all projects, or no change. `kyma --help` starts with the common commands. `kyma help --all` retains every option.
- `kyma on`: one Claude Code `PreToolUse` hook checks every tool call before it runs, and cites the sentence that held it. A rule can be loosened only by a person at a terminal.
- `kyma demo`, `kyma try`, `kyma rules`, `kyma check`, `kyma mcp`, `kyma stop` / `kyma go`.
- Reads what a call would run through wrappers, escapes, variables, interpreters and launchers; `tests/test_adversary.py` keeps a blind reviewer's 173 attempts and 181 ordinary calls.
- No network module, no account, no dependencies. Python 3.9 or later.

The complete earlier contract kit, including the November 9 AI terms reader, remains on the [`contract-kit` branch](https://github.com/kymacomputer/kyma-local/tree/contract-kit). Its earlier releases, including [`v0.4.2`](https://github.com/kymacomputer/kyma-local/releases/tag/v0.4.2), remain available. The [contract example](docs/contract-bridge.md) demonstrates a reviewed rule, a customer grant, and its withdrawal with real local commands. Contract interpretation continues in [Kyma](https://kyma.stream).

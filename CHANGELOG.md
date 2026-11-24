# Changelog

## 0.6.0 — 2026-11-24

- First run opens a bounded sample of the user's actual logs with starter checks. No rules file or previous block history is required.
- The recent sample reads up to 25 logs within 128 MiB. `--all` keeps complete local history free.
- Native history adapters add Cursor and Gemini CLI. A documented JSONL import accepts other agents and model identifiers.
- Commands and recorded outcomes appear before retrospective rule verdicts. Reports with no matches open a real ordinary attempt.
- Local remains free. The paid route covers contract interpretation, source citations, approval, and maintained agreement rules.
- Authentic provider marks identify recorded models in the report.
- Agent cards and selected actions show the model and effort recorded in their own transcripts.
- Model changes within a session remain visible. Missing metadata stays unknown.
- Nested Codex actions retain the model that authored the wrapper without an invented tool outcome.
- Child models no longer inherit an assumed version from their parent.
- Compressed history resumes after its saved position. Literal backslashes survive shell-function expansion.
- Native Codex result headers preserve explicit exit status, including headers with token counts. Nested actions do not inherit wrapper outcomes.
- Import IDs receive validation before normalization. Missing actor times cannot come from nested tool input.

## 0.5.1 — 2026-11-24

- The example's trial dialog includes Python setup when its first command is unavailable.
- Common ordinary commands have readable action titles. Exact commands and unknown outcomes remain visible.
- Compound, clipped and unrecognized commands retain their original generic title.
- A Python source launch gives runnable next-step commands without a separate installation.

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

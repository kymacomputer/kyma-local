# Security

## Reporting a problem

Report it privately with **Report a vulnerability** on this repository's Security tab. Please do not open a public issue for a way past the gate or a leak of history.

A useful report has the payload you piped to `kyma hook` (with fake secrets), the RULES.md it ran against, the verdict you got, and the one you expected.

## What kyma defends, and what it does not

kyma has two parts with two different promises.

**The reader** (`kyma`, `kyma see`, `kyma try`) reads the logs Claude Code and Codex keep on your disk.
- It opens no network connection. The README shows how to check the code for one.
- It writes under `~/.kyma` (or `$KYMA_HOME`), as `0700` with files `0600`. Outside it: one copy of the rules you accepted (and on macOS a hash in your keychain), and the hook entry `kyma on` adds to Claude Code's settings. The README lists each file.
- It masks known secret formats before it writes an excerpt.

A report that kyma sends data off the machine, writes outside its folder, or stores an unmasked secret value is in scope.

**The gate** (`kyma on`) is a Claude Code `PreToolUse` hook. It reads each tool call before it runs and returns allow, ask, or block, citing your sentence.
- It assumes the agent is *not* hostile. It is built for an agent that makes a mistake, not one that works to get past it.
- It reads shell, scripts on disk, inline code and launchers, and holds the forms it cannot read when they touch a rule's topic.
- A call that loosens your rules waits until you accept it with `kyma rules` at your terminal.

In scope:
- an ordinary-looking call that does what a rule forbids and is allowed;
- an agent turning the hook off, or loosening the rules, without you accepting it.

Out of scope:
- an agent that runs arbitrary code and deliberately hides what it does. A rule engine over text cannot close every route. For a hard boundary, run the agent in a container or a VM;
- agents with no hook (Codex today). `kyma check` and `kyma mcp` give verdicts, and the agent decides whether to ask;
- anything done with `disableAllHooks` set, or outside Claude Code.

## Tests that hold the line

- `tests/test_adversary.py`: 173 escape attempts that must be held and 181 ordinary calls that must pass.
- `tests/test_escapes.py`: routes the gate was fixed against, and innocent twins that must still pass.
- `tests/test_selfguard.py`: attempts to switch kyma off or edit its rules.

A fix for a reported escape adds the payload to one of these files.

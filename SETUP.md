# Set up Kyma for this user

You are the user's agent. Complete the install and show the result. The user should not need to follow terminal instructions.

Kyma reads local agent history. It can add automatic checks to Claude Code. Codex, Cursor, and Gemini CLI have history support. Their checker integrations are advisory.

## 1. Identify the host and project

Use your actual host, not your model name: `claude`, `codex`, `cursor`, or `gemini`.
Keep the user's current project as the working directory. If it is a Git checkout, use project scope.
Do not treat Kyma's installation folder as the user's project.
For Claude outside a Git project, use global scope. Respect an explicit request for report-only use or an existing disabled-hook setting.

## 2. Install a lasting copy

If `uv` is available:

```sh
uv tool install git+https://github.com/kymacomputer/kyma-local
```

Use the installed executable from `uv tool dir --bin` if it is not on PATH. Do not ask the user to change their shell.
If an older Kyma is already installed, update it with the same source through `uv tool upgrade kyma-local`.

If `uv` is absent, use Git and Python 3.9 or later. Clone into a lasting, user-owned folder, such as `~/.local/share/kyma-local`.
Check an existing folder's origin and uncommitted changes before reuse. Do not overwrite it.
The clone's `kyma` launcher has no dependencies. Invoke it with the full Python and launcher paths.

If neither route is available, install uv from [Astral's official instructions](https://docs.astral.sh/uv/getting-started/installation/), then use the first route.
Install in the user's account. Do not use sudo, add a paid service, or install another agent host.

## 3. Run setup from the user's project

For Codex, for example:

```sh
kyma setup --host codex --json
```

For Claude Code in a Git project:

```sh
kyma setup --host claude --project --json
```

For Claude Code outside a Git project, use `--global` instead of `--project`.
Use `--host cursor` or `--host gemini` for those hosts. Do not substitute the model's provider.
Use `--no-open` only when you must open the returned report through your own browser tool.
For report-only use, run `kyma --no-open` and open the generated local report without an `on` command.

Setup finds native history, produces a bounded local report, and returns one JSON receipt.
Read `report_path`, `coverage`, `capability`, `checks`, and `next_action`.
Open the actual `report_path` if the automatic browser launch did not reach the user.
Follow a recoverable error's exact remedy, then rerun setup. Never report success from the install command alone.

## 4. Verify and finish

Use the receipt to tell the user what is ready. Inspect one actual action in their report when history exists.
Name the recorded outcome separately from what a starter rule would have caught.
If no history exists, say so and run `kyma demo`. That demonstration stays in a throwaway folder.

For Claude, say checks are on only when setup verifies the installed hook, supported host version, and selected scope.
For other hosts, say the history report is ready and automatic checks are unavailable for that host.
Do not add advisory MCP instructions and describe them as automatic protection.

Preserve existing rules and unrelated host settings. Do not accept pending rule relaxations for the user, fake a terminal, or override a disabled-hook setting.
Do not upload transcripts or request an API key. Do not run a real harmful command to test a rule.

Finish with the report link, the exact check status, and one concrete result. Keep it to a few sentences.

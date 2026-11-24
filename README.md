# Kyma Local

Kyma shows what your AI agents did on your computer: the command, the model, and what happened. You can also give Claude Code rules it checks before each action.

For example, with `Never read .env files` enabled:

```text
Claude Code tries:  cat .env.production
Kyma blocks it:     Never read .env files.
```

## Give this to your agent

```text
Set up Kyma for me. Follow https://raw.githubusercontent.com/kymacomputer/kyma-local/main/SETUP.md
```

Your agent installs Kyma, finds your history, and opens your report. Setup verifies whether automatic checks are on. No account or API key. Your logs stay on your computer.

![Kyma shows recorded models, commands, outcomes, and rule matches.](docs/example.jpg)

*Example data. Your report uses your own history.*

History works with Claude Code, Codex, Cursor, and Gemini CLI. Automatic checks run in Claude Code. Other agents can call the [checker](docs/usage.md#other-agents).

Kyma Local is free and open source. Our [agreement reader](https://kyma.stream) turns customer contracts into rules for approval. This repo runs the checks.

[Try a contract grant and revocation](docs/contract-bridge.md) · [Commands](docs/usage.md) · [Limits](SECURITY.md) · [Apache-2.0](LICENSE)

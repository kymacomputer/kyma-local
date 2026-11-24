# Rules from contracts

Version 0.5.0 adds a direct route for people who use coding agents: inspect local history, write a rule, then check it before a tool call. It does not read agreements. Contract interpretation and source updates remain [Kyma](https://kyma.stream)'s paid work.

The complete earlier contract kit remains on the [`contract-kit` branch](https://github.com/kymacomputer/kyma-local/tree/contract-kit), pinned to commit `9138e00`. It includes the November 9 AI terms reader. The earlier [`v0.4.2`](https://github.com/kymacomputer/kyma-local/releases/tag/v0.4.2), `v0.4.1` and `v0.4.0` releases remain available.

Existing contract-kit users can retain their workflow:

```sh
git clone --branch contract-kit https://github.com/kymacomputer/kyma-local.git
```

Version 0.5.0 installs the `kyma` command. It does not migrate contract inputs, prior decisions or OpenFeature exports. Keep an existing contract-kit environment for the `kyma-local` command.

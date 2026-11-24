# A contract clause reaches a real command

Run this from a fresh checkout with Python 3.9 or later. No package install, account or network request is required.

```sh
python3 examples/contract_rule.py
```

The command creates an isolated directory and prints its receipt path. It leaves the directory for inspection. Your real rules and keychain remain untouched.

| Step | Runtime verdict | Actual local result |
|---|---|---|
| Acme has its fixture grant | `allow` | `customers/acme/ai-summary/before.txt` contains the fixture summary |
| Acme withdraws that grant | `ask` | The next shell command does not execute. `after.txt` is absent |
| Beta retains its independent grant | `allow` | `customers/beta/baseline-report/report.txt` contains the fixture report |
| An Acme command claims a Beta label | `ask` | Its Acme path still matches the hold. `mislabeled.txt` is absent |

The host runs the real `kyma check --json` process before each command. It executes `/bin/sh` only after exit code `0`.
The receipt retains the exact command, runtime reason, exit code, file contents, source, review label and rule version.
An `ask` remains a hold in this host. The fixture does not approve that held command automatically.

## Source and explicit review fixture

The source is [Bonterms Standard AI Addendum Version 2.0, Signable Version](https://bonterms.com/standard/ai-addendum-v2-signable-version).
The selected clause is **AI Features / New AI Features / (b) Opt-Out**:

> (b) Opt-Out. Customer will have the ability to decline or disable any New AI Feature through administrative controls in the Cloud Service (or other reasonable measure made available by Provider) at the account, organization or equivalent administrator level.

Copyright 2026 Bonterms, Inc. The source retains its [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/).
Bonterms does not endorse this example. The new code and authored explanation use the repository's Apache-2.0 license.

The [fixture](../examples/fixtures/contract-rule.json) identifies its source, excerpt, assumptions, customer paths and review record.
Its review identity is fictional. It represents the human approval step without a claim that a person approved this example or any customer contract.
Acme and Beta are fictional. Their initial permissions are fixture decisions, not grants created by the public clause.

The source snapshot comes from the earlier public contract kit at commit `9138e0039f5e81b1dd3716a2b127927f2ba73c19`.
Its original path is `standard-packs/originals/bonterms-ai-v2-signable.txt`.
Its SHA-256 is `e431231237bb0e9451925eafc3b6c74fd4a7da104dfab8531d3760a6717b5109`.
The example preserves the complete plain-text source and checks its hash and exact excerpt before execution.
The source context includes notice and functionality provisions. This example does not establish compliance with those separate obligations.

The mapping uses only supported write actions and local paths:

```md
- Ask me before writing `~/../workspace/customers/acme/ai-summary`.
- My agent may write `~/../workspace/customers/acme/ai-summary`.
```

Both lines carry the source URL, source identifier, fictional reviewer and version as citation metadata.
Withdrawal removes Acme's `may` line and raises its hold's version. Beta's independent lines remain unchanged.
The parser verifies that every line compiles to one write action and one absolute path before the first command.

## What the test proves

It proves one explicit source-to-rule mapping, two separate local paths, runtime withdrawal, preserved Beta execution and source provenance in actual verdicts.
The host supplies the customer-to-path relation. A caller's customer label and the citation metadata confer no trust.
It does not infer customer identity, purpose, contract applicability or arbitrary data-use semantics from a sentence.
It is not a sandbox or a production integration. A host must invoke the check and honor its result.

The earlier public kit, this local checker and Kyma's current paid contract reader are separate artifacts.
This bridge tests the executable handoff after review. It does not test the paid reader, prove paid demand or establish novice usability.

```sh
python3 tests/run.py contract_bridge
```

The regression test uses a fresh copy without Git, a directory with spaces, actual shell outputs and the real CLI.
It also rejects altered source bytes, an invented excerpt, an escaped customer path, an unsupported purpose rule and reuse of old output.

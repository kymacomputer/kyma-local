# Kyma Local

Use complete local contract sets and a named feature to produce source-bound decisions and useful engineering outputs.
Your existing agent performs the interpretation and chooses the work.
The kit verifies quotations, writes proposed controls and tests their actual OpenFeature result.

Your files do not go to Kyma.
The first route below uses ChatGPT-authenticated Codex and its existing native credential store.
Codex sends source contents to your ChatGPT provider under your account and its settings.
The current-agent and MCP routes use your chosen host and its provider policies.

## Get the kit

```sh
git clone https://github.com/kymacomputer/kyma-local.git
cd kyma-local
```

## First run

Use Python 3.10 or later and the [official Codex CLI](https://learn.chatgpt.com/docs/cli).
Sign in to Codex with your ChatGPT account.

```sh
python3 scripts/bootstrap.py
.venv/bin/kyma-local doctor
.venv/bin/kyma-local analyze --contracts sample/contracts --feature sample/feature.json --out runs/my-first-run
.venv/bin/kyma-local verify runs/my-first-run
```

Open `runs/my-first-run/DECISIONS.md`.
The same folder contains exact source evidence, precedence, unknowns, engineering outputs and an importable OpenFeature rule file.
The model runs the compiler and reads the receiving result itself.
The verifier independently checks the durable result and the real OpenFeature SDK.

The bootstrap selects an installed Python 3.10 or later.
It also works when macOS's default Python is older.
It installs this kit and its pinned dependencies into `.venv`.

The sample contains complete original public SEC exhibits from two negotiated relationships.
One set contains a joint-venture agreement and two amendments.
Public redactions and missing referenced documents remain explicit limits.
The proposed feature is hypothetical.
`sample/source-acquisition.json` retains the original HTTP results, acquisition clocks and byte hashes.
The original source URLs also remain in each customer folder's `_sources.json`.
The complete public sample is already in the kit.
Use your own `SEC_USER_AGENT` only if you choose to refresh the public originals with `acquire_sample.py`.

The [completed sample packet](runs/fresh-user-run/DECISIONS.md) shows the output before a model run.
Your new run folders and the example private input paths are excluded from Git.
The published sample results remain tracked.

## Use your current Claude or other agent

The current-agent route uses your existing model directly.
It creates no additional model call or developer API request.
The same source validator, proposed exports, OpenFeature checks, and SQLite receiver serve this route.

For Claude Code, copy `skills/kyma-local` into your project's `.claude/skills/kyma-local` folder.
Keep an existing skill of that name before a replacement.
Activate this kit's environment before you start Claude:

```sh
source .venv/bin/activate
claude
```

Ask Claude to use `/kyma-local` with your contract folder, feature JSON, and a new output folder.
The skill uses the current model to read the sources and author the assessment.
Its local tool commands are:

```sh
kyma-local-agent prepare --contracts sample/contracts --feature sample/feature.json --out runs/agent-first-run
kyma-local-agent source --work runs/agent-first-run --document-id DOCUMENT_ID
kyma-local-agent submit --work runs/agent-first-run --assessment assessment.json
kyma-local-agent readback --work runs/agent-first-run
```

The preparation result contains every document ID and the complete assessment schema.
Read each source before the assessment. The source command returns the complete extracted text and original provenance.
The submit command verifies your assessment and creates the engineering packet.
The final command reads its exact durable result and checks the real SDK again.

### MCP server

Install the optional MCP adapter:

```sh
python3 scripts/bootstrap.py --mcp
python3 scripts/mcp_config.py
```

The second command prints the exact configuration for this installed copy.
Add that entry to your chosen host through its normal MCP configuration.
The server uses local stdio. It has no HTTP listener or model-provider connection.
The six tools import local exports, prepare first or revision jobs, return a complete document, submit your assessment, and read the result.
Your host model performs the interpretation under its existing account and provider policies.
The adapter records no model identity or complete-reading attestation from a successful tool response.

The adapter uses the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
The skill follows the [Claude Code skill format](https://code.claude.com/docs/en/skills).

## Your own contract sets

For an existing contract-system export or review table, use the [local importer](docs/contract-imports.md).
It preserves your originals, record metadata and explicit missing-file state.

For Common Paper or Bonterms paper, use the [standard contract packs](standard-packs/README.md).
The packs preserve version-specific choices and prepare separate references for your actual contract review.

For a reusable public-source review file, use the [AI-terms format and offline reader](ai-terms/README.md).
The Intercom example joins seven Index fields to detailed decisions, source spans and unresolved questions.
You can edit a copy for another vendor without a model call or account connection.

Create one folder per customer.
Include the complete MSA, DPA, orders, AI riders, amendments and incorporated documents that apply to the named feature.
The model resolves express amendments, incorporated terms and scoped precedence from their text.

```text
my-contracts/
  customer-a/
    signed-msa.pdf
    dpa.pdf
    order.docx
    amendment.pdf
  customer-b/
    agreement.html
    ai-rider.txt
```

Copy `examples/feature-template.json` to your own feature file.
State the actual actor, data, purpose, provider, region, retention and training facts for each operation.
Keep proposals and unknowns separate from observed facts.
Then run:

```sh
.venv/bin/kyma-local analyze --contracts my-contracts --feature my-feature.json --out runs/my-feature
```

The kit includes every supported file in each customer folder.
Supported formats are PDF, DOCX, HTML, Markdown and plain text.
It reports unreadable pages, unsupported files and tracked revisions.
PDF citations retain real page numbers.
PDF form values retain their field names, actual values, defaults and verified page locations.
Other formats retain exact line and character spans.

The output folder contains source text and model input.
Keep that folder under the same custody as your contracts.

## A capable native comparison

The native route receives the same complete sources, feature facts, model, output schema and tools.
It uses its own strongest method.
It can use all source relationships and capabilities.

```sh
.venv/bin/kyma-local analyze --contracts sample/contracts --feature sample/feature.json --out runs/native --mode native
```

Use the same `--model` and `--effort` settings for both routes.
The defaults follow `KAI_CODEX_MODEL` when present, otherwise `gpt-6.1-sol`, with `ultra` effort.

## A changed contract, feature or supplier disclosure

Use the previous completed run as the baseline:

```sh
.venv/bin/kyma-local watch --before runs/my-first-run --contracts my-contracts --feature my-feature.json --out runs/my-update
```

The command compares complete source hashes and feature facts.
An unchanged snapshot returns the previous verified engineering packet.
A changed snapshot sends the complete current sources and previous assessment to your Codex model.
The model selects the material source effect and the useful engineering revision.

Open `runs/my-update/CHANGES.md` for the source effects, engineering work and customers whose status changed.
`change-summary.json` contains the importable revision event.
The model commits that event to SQLite and reads the receiving result.

For your current Claude or other connected agent, use the revision adapter:

```sh
kyma-local-agent revision --before runs/agent-first-run --contracts my-contracts --feature my-feature.json --out runs/agent-update
```

The equivalent MCP tool is `prepare_revision_job`.
Read every returned source, including retained prior versions, before you author the revised assessment.
The returned schema includes `revision_impacts` for every observed change.
Use the same submit and readback commands as the first job.
The general `kyma-local verify` command accepts both supported assessment routes.

`changed-customer-segments.json` contains only customers whose proposed status changed.
It includes their current rules, removed rules, and conditional notice or consent drafts.
`downstream-diff.json` separately records changed conditions, controls, engineering work, and drafts.
A useful engineering change can occur while every status stays the same.
The complete current assessment remains in `model-decisions.json`.

Keep shared supplier documents in a separate folder:

```text
supplier-references/
  analytics-vendor/
    subprocessor-list.html
    _sources.json
```

Add `--references supplier-references` to the command.
Each `_sources.json` record can retain the original URL, capture time, source type and scope.
The model derives applicability from the actual contracts and feature facts.

### Observe the next natural change

The observer is an explicit local foreground process.
Start it after your first useful run, with your next expected event and its date:

```sh
kyma-local follow --opt-in --before runs/agent-first-run --contracts my-contracts --feature my-feature.json --references supplier-references --out local-observer --next-event 'New customer amendment' --event-date 2026-11-06 --prepare-only
```

Keep `local-observer` outside your source folders.
`--prepare-only` prepares changed jobs for your current agent and waits for its submit and readback.
That route records agent-assisted completion, rather than an automatic completed job.
Use `kyma-local-agent job --work JOB_FOLDER` to read a pending job's complete schema, source IDs, and revision context.
Without `--prepare-only`, each stable source change invokes your existing ChatGPT-authenticated Codex CLI.
The same complete-source interpretation and local receiver checks apply.
Unchanged polls invoke no model.
Failed unchanged jobs remain available and do not cause model retries.

The observer captures exact input copies before analysis.
A change during analysis remains available for the next job.
Only one foreground observer can own a given output folder.
No background service, Kai job, remote observer, or telemetry sender is installed.
The process stops when its host stops.
Restart the same observer with:

```sh
kyma-local follow --out local-observer
```

Its saved configuration retains the original model route, source folders, and next event.
Use `--once` for one check.
One-shot checks and explicit failed-job retries count as prompted work.
Use `--retry-failed` after the recorded failure is resolved.
A pending job needs its actual receiver result or a terminal failed CLI launch before a retry.

### Supplier source refresh

Local supplier capture changes use the same observer.
For automatic HTTPS acquisition, supply an explicit JSON source list through `--reference-sources` at initial setup.
Each entry has `url` and `path` fields.
The path must name a supported file inside one vendor folder, such as `analytics-vendor/subprocessors.html`.
Use the vendor's actual source URL.
The observer sends conditional GET requests and retains the acquired bytes, URL, hash, and capture clock.
It sends no contract text in those requests.
Acquisition errors remain visible. They cannot establish a current supplier list.

### Local repeat-job evidence

Read the installation's actual completed jobs:

```sh
kyma-local activity --out local-observer
```

Record useful work through the returned exact job ID:

```sh
kyma-local activity --out local-observer --confirm-job JOB_ID --useful-note 'Used the revised notice draft for the amendment review.'
```

This statement stays local and can arrive while the observer is active.
A qualified local repeat needs both first and later usefulness statements.
The later job must have distinct inputs, a verified receiver, a downstream delta, and automatic source-triggered completion.
At least 24 hours must separate the first observed useful packet and the later completed job.
Process uptime, repeated packets, manual prompts, and zero-output changes do not qualify.
These records retain local statements. Outside-user identity and independent adoption require their own evidence.

The bundled Fullstory case includes two complete captured versions with the same printed revision date:

```sh
.venv/bin/kyma-local watch --before runs/fresh-user-run --contracts sample/contracts --feature sample/feature.json --references sample/references-after --reference-baseline sample/references-before --out runs/my-source-update
```

`--reference-baseline` imports an independently captured historical source.
Both complete versions remain available to the model.
The original observation clocks stay with their source records.

## Engineering consumer

`openfeature-rules.json` contains model-selected per-customer, per-operation controls.
`openfeature-consumer.json` records actual OpenFeature SDK evaluations.
Unknown customers and absent required facts return false.
`feature-policy.rego` and `opa-data.json` provide the same rule set for Open Policy Agent.
These exports are proposed assessments.
Import them into your chosen application after the source-bound decision resolves its prerequisites.

Import the provider into your existing application's OpenFeature domain:

```python
import json
from openfeature import api
from kyma_local.tool import build_provider

with open("runs/my-first-run/openfeature-rules.json") as source:
    export = json.load(source)
api.set_provider_and_wait(build_provider(export), domain="my-feature-contracts")
client = api.get_client("my-feature-contracts")
```

The constructor preserves your application's existing default provider.
Use the named domain for these flags.
Your application supplies actual customer identity and verified operation facts at evaluation.
The example below checks the complete real export through that separate domain:

```sh
.venv/bin/python examples/openfeature_consumer.py runs/my-first-run
```

Useful artifacts also include:

- `model-decisions.json`: the complete model-authored decision and engineering work.
- `validated-source-evidence.json`: exact quotes and their original hashes, lines and spans.
- `source-manifest.json`: every acquired source and extraction limit.
- `model-input.txt`: the complete source input given to Codex.
- `observable-transcript.jsonl`: actual model messages and tool calls.
- `model-receiving-readback.json`: the model's actual receiving read.
- `local-results.sqlite3`: the durable local consumer.
- `verified-consumer.json`: independent source, runtime and receiving checks.

Private model event files stay local and are excluded from the shareable sample bundle.

## Runtime and reproducibility

The CLI uses an ephemeral local Codex turn and your existing ChatGPT login.
The kit retains the complete task input, model result, tool trace and receiving state.
Codex may also load your existing user and project instructions.

Run the focused source, target, type and replay checks:

```sh
.venv/bin/python scripts/check_boundaries.py runs/my-first-run
.venv/bin/python scripts/compare_runs.py runs/my-first-run runs/native --out comparison.json
```

The public sample's six original proposals remain unavailable under both actual model runs.
Their engineering outputs develop distinct useful routes and the missing facts for each route.
`evidence/` contains the complete comparison and the exact execution scope.

Official OpenAI documentation supports the existing login and ephemeral invocation path:

- [Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)

## Share a result

Use the repository's **Completed run** issue form after useful work.
Include the entry route, time to first value, useful result and next actual task.
The **Bug report** form captures an exact failed command or tool call.
Keep private contracts, credentials and model transcripts on your computer.
The kit sends no telemetry report.

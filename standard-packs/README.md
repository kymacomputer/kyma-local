# Standard contract packs

Run a clause matrix for four pinned standards:

- Common Paper AI Addendum 1.0
- Common Paper Cloud Service Agreement 3.0
- Common Paper Data Processing Agreement 1.1
- Bonterms AI Addendum 2.0

The matrices preserve each actor, data class, purpose, choice and source condition.
Model training and system improvement have separate predicates.
An Input grant includes user prompts. A prompts-only grant does not include other Input.
Bonterms has separate restrictions for human authorship and Provider approval claims.

## Try the examples

Use Python 3.10 or later. Run these commands from the kit root.

```sh
python3 scripts/bootstrap.py --mcp
.venv/bin/python standard-packs/check.py --out /tmp/kyma-standard-check
```

The check runs the complete example population through the native contract tools, OpenFeature SDK and SQLite receiver.
It also tests source tampering, invented quotations, missing decisions, unresolved inputs and private amendments.
Each example produces `cover-choice-matrix.json` and `native-runtime/DECISIONS.md`.

For one AI Addendum example:

```sh
.venv/bin/python standard-packs/pack.py \
  --cover standard-packs/examples/no-training.json \
  --facts standard-packs/examples/facts.json \
  --out /tmp/kyma-ai-example
```

For another standard, use `standard_packs.py --paper csa3`, `dpa11` or `bonterms2` with its example choices and facts.
The source examples have no customer identity or executed agreement. Their customer flags remain disabled.
The clause matrix retains useful conditional results separately from the complete-agreement assessment.

## Use your own contract set

```sh
.venv/bin/python standard-packs/prepare_actual.py \
  --contracts YOUR_COMPLETE_CONTRACT_SET \
  --feature YOUR_FEATURE.json \
  --papers common-ai1 csa3 dpa11 bonterms2 \
  --out /tmp/kyma-standard-review
```

This command prepares your actual documents and separate standard references for your current agent.
Your agent reads every source, resolves private amendments and completes the native assessment schema.
It then submits that assessment and verifies the actual result.
The command does not upload documents or invoke a model.

The finite packs cover the choices listed in `COVER-CHOICES.json`.
Other choices require the current agent and complete source documents.
Unknown fields, custom terms and unsupported versions do not become automatic permission.
Actual execution, incorporation, private amendments, selected policies and feature facts remain part of the assessment.

## Sources

`SOURCE-PINS.json` records each source URL, version, hash, license and transformation.
`SOURCE-LICENSES.md` records attribution and the source publication scope.
The Common Paper originals retain their complete Cover Pages and license notices.
The Bonterms reference retains the complete agreement, its attribution and a matching original PDF.
The CC0 Additional Terms examples retain all clause text with publisher attribution removed as the source requests.
Website navigation, site scripts, private run records and historical runtime copies are excluded.

These are independent interpretations. Neither publisher endorses them.
The packs provide source-bound assessments. They do not establish legal clearance or an outside customer result.

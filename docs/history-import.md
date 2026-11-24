# History imports

Kyma reads local Claude Code, Codex, Cursor, and Gemini CLI history.
The `kyma.history.v1` JSONL format supports other hosts, providers, and models.
It requires no provider account, model call, or network connection.

Import an export from another agent, then open its report:

```sh
kyma import /path/to/history.jsonl
kyma
```

Native adapters discover their local histories automatically. They need no import command.
The import format below lets another agent or exporter supply recorded events without a Kyma-specific model integration.

Each file describes one session. The first line identifies its host.
Each later action supplies its own recorded model, provider, and effort.
Kyma does not inherit these fields from another action or from current settings.
Omit unknown fields. A host name does not establish the model provider.

```jsonl
{"schema":"kyma.history.v1","type":"session","host":"opencode","session_id":"example-session","cwd":"/project","task":"Repair the build"}
{"schema":"kyma.history.v1","type":"action","id":"call-1","timestamp":"2026-11-24T15:00:00Z","tool":"bash","kind":"shell","command":"npm test","model_id":"Qwen/Qwen3-Coder-30B-A3B-Instruct","provider":"ollama"}
{"schema":"kyma.history.v1","type":"result","id":"call-1","status":"tool_succeeded"}
```

| Record | Fields |
| --- | --- |
| Every line | `schema: "kyma.history.v1"`, `type` |
| Session | `host`, optional `session_id`, `cwd`, `task`, `timestamp` |
| Action | Unique `id`, `tool`, optional `timestamp`, `command`, `paths`, `kind`, `host`, `cwd`, `model_id`, `provider`, `effort` |
| Result | Exact action `id`, `status`: `tool_succeeded`, `tool_failed`, or `unknown` |

Action IDs accept 1–256 ASCII letters, digits, underscores, dots, colons, or hyphens.
`kind` accepts `shell`, `read`, `write`, `mcp`, or `other`.
`paths` contains file paths. `command` contains the recorded shell command.
`effort` contains a recorded level such as `high`, `max`, or `balanced`.
An effort value describes the recorded setting. It is not an intelligence score.

The Python entry point is `sources.import_history(path, format="normalized")`.
Its receipt contains `path`, `format`, `actions`, and `results`.
The importer validates the file, removes unused fields, masks recognized secrets, and writes a private file under `KYMA_HOME/imports`.
It hashes original action IDs and preserves exact result joins.
Repeated imports of the same content resolve to the same file.
Files must fit within 64 MiB and 100,000 records.

Imported result status remains an imported claim. Kyma does not treat it as native enforcement evidence.
A successful tool result does not prove that an external effect completed.
Missing or duplicate result joins remain unknown.
Kyma never infers success from output prose.

## Native adapter boundaries

Cursor transcripts expose tool inputs under `~/.cursor/projects/**/agent-transcripts/**/*.jsonl`.
The inspected format omits timestamps, model IDs, effort, tool IDs, and results.
Kyma retains those actions with unknown metadata. It never substitutes the file modification time.

Gemini CLI stores sessions under `~/.gemini/tmp/*/chats/session-*`.
Kyma supports legacy JSON and current JSONL snapshots, including message replacement, rewinds, removal, and order patches.
An existing JSONL sibling supersedes a migrated JSON file.
Gemini message fields establish the model. Tool status establishes success or failure only for the exact tool ID.
Cancelled or incomplete tools remain unknown. The schema does not record effort or provider fields.

The Gemini adapter follows the official [record types](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/services/chatRecordingTypes.ts),
[snapshot loader](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/services/chatRecordingService.ts),
and [tool states](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/scheduler/types.ts).

OpenCode supports [custom provider and model IDs](https://opencode.ai/docs/models/).
Its histories can enter through the normalized format. Kyma does not currently scan OpenCode databases.

## Adapter integration

`sources.history_files(since_days=None)` returns `(path, format)` pairs.
`sources.reader(format)(path, cursor=None)` yields the existing `Action` structure.
`sources.history_events(path, format)` exposes session, user, action, and result records for the additional adapters.
Formats are `claude`, `codex`, `cursor`, `gemini`, and `normalized`.
The event interface supports the last three formats. Existing native parsers retain their optimized paths.

Cursor and normalized readers support byte and item cursors.
Normalized cursors also preserve session context.
Gemini JSONL requires a complete snapshot read because later records can change earlier messages.
Invalidate its cached snapshot whenever the source changes. Do not resume Gemini by byte offset.

The discovery format selects the parser. `Action.agent` identifies the recorded host.
Those values can differ for a normalized import.
Each actor exposes `model_id`, friendly `model`, `provider`, `effort`, `model_source`, and `effort_source`.
The source provenance is `normalized_import`, `gemini_message`, or the existing native source name.

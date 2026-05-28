# Chat Bridge Contracts Design

Date: 2026-05-28

## Goal

Define the first stable contract for moving chat sessions between Codex Desktop
and Factory Droid.

The first implementation should be conservative:

- read-only discovery and preview before any import writes;
- one-shot export/import before mirror sync;
- no new external dependencies;
- no auth, API key, PIN, cache, binary, telemetry, or log migration;
- lossless preservation of raw source events where the destination format cannot
  represent a field directly.

The contract must also preserve code work context. A single chat may span
multiple Git branches or commits, so the bridge format stores both a current
snapshot and a timeline of observed repository state changes.

## Observed Source Formats

### Codex

Codex session state is split between SQLite and JSONL rollout files:

- `.codex/state_5.sqlite`, table `threads`;
- `.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`;
- important `threads` columns include `id`, `rollout_path`, `title`, `cwd`,
  `model_provider`, `model`, `created_at_ms`, `updated_at_ms`, `git_branch`,
  `git_sha`, `git_origin_url`, `first_user_message`, and `preview`;
- observed rollout event types include `session_meta`, `turn_context`,
  `event_msg`, and `response_item`;
- observed payload types include `message`, `user_message`, `agent_message`,
  `reasoning`, `function_call`, `function_call_output`, `custom_tool_call`,
  `custom_tool_call_output`, and `token_count`.

Codex has a native place for the latest Git branch/SHA in `threads`. Rollouts
can contain additional Git metadata, especially in `session_meta.payload.git`.
If a branch changed during the chat and the source rollout records multiple Git
snapshots, the bridge must preserve them in order. If the old source data only
contains the latest DB snapshot, the bridge must mark the timeline as incomplete
instead of inventing history.

### Droid

Factory Droid session state is file-based:

- `.factory/sessions/<uuid>.jsonl`;
- `.factory/sessions/<uuid>.settings.json`;
- `.factory/sessions-index.json`;
- observed JSONL event types include `session_start`, `message`, and
  `todo_state`;
- observed message content part types include `text`, `tool_use`, and
  `tool_result`;
- observed companion settings include `assistantActiveTimeMs`, `providerLock`,
  `providerLockTimestamp`, and `tokenUsage`.

No native Droid Git context field has been confirmed yet. The bridge must
support Droid Git context if a future sample exposes it, but the first version
should store imported work context in bridge sidecar metadata rather than adding
unverified fields to Droid-owned session JSON.

## Non-Goals

- No cloud relay, mesh, WebSocket, or live bidirectional sync in the first chat
  conversion phase.
- No automatic Git checkout, branch creation, reset, merge, or worktree mutation.
- No attempt to reconstruct missing historical branch changes from current file
  system state.
- No parsing of auth files or secret-bearing config.
- No full-fidelity rendering of every Codex internal event in Droid UI.
- No full-fidelity rendering of every Droid internal event in Codex UI.

## Bridge Package Layout

Use a ZIP package for one-shot transfer. The package root is `chat-bridge/`.

```text
chat-bridge/
  manifest.json
  sessions/
    <bridge_id>.json
  raw/
    codex/
      <bridge_id>.jsonl
      <bridge_id>.db-meta.json
    droid/
      <bridge_id>.jsonl
      <bridge_id>.settings.json
```

`manifest.json` contains package metadata, source app, creation time, session
count, contract version, and warning counts. It does not contain message bodies
or secrets.

`sessions/<bridge_id>.json` contains the normalized contract described below.
Raw files are optional but strongly preferred. They make round-tripping safer
and allow future bridge versions to recover data the first version does not
understand.

## Canonical Session Contract

Each normalized session uses this shape:

```json
{
  "format": "codex-droid-chat-bridge",
  "version": 1,
  "source": {
    "app": "codex",
    "session_id": "source-session-id",
    "path": "source-path",
    "exported_at": "2026-05-28T00:00:00Z"
  },
  "session": {
    "bridge_id": "stable-bridge-id",
    "title": "Session title",
    "created_at": "2026-05-28T00:00:00Z",
    "updated_at": "2026-05-28T00:00:00Z",
    "provider": "openai",
    "model": "gpt-5.5"
  },
  "work_context": {
    "primary_cwd": "C:/Research/project",
    "current": {
      "cwd": "C:/Research/project",
      "git_branch": "main",
      "git_sha": "abc123",
      "git_origin_url": "https://example/repo.git",
      "dirty_state": "unknown",
      "source": "codex_threads",
      "confidence": "observed"
    },
    "timeline_complete": false,
    "snapshots": []
  },
  "messages": [],
  "extras": {},
  "raw_event_refs": []
}
```

### Work Context Snapshot

`work_context.current` is the best latest-known state for destination metadata.

`work_context.snapshots[]` stores ordered repository state observations:

```json
{
  "id": "work-snapshot-1",
  "observed_at": "2026-05-28T00:00:00Z",
  "event_index": 42,
  "message_id": "message-before-or-after-this-state",
  "cwd": "C:/Research/project",
  "git_branch": "feature/chat-bridge",
  "git_sha": "abc123",
  "git_origin_url": "https://example/repo.git",
  "dirty_state": "unknown",
  "source": "codex_session_meta",
  "confidence": "observed"
}
```

Allowed `confidence` values:

- `authoritative`: the source explicitly recorded this exact state for the
  event or turn;
- `observed`: the source recorded this state, but not necessarily at every
  message boundary;
- `inferred`: the exporter inferred this from current file system or companion
  metadata;
- `unknown`: the field is unavailable.

Allowed `dirty_state` values:

- `clean`;
- `dirty`;
- `unknown`.

`timeline_complete=false` is important. It means consumers must not assume the
absence of a branch-change snapshot means the branch did not change. This is the
expected state for many existing Codex and Droid sessions.

The destination app uses the latest snapshot at or before a message timestamp
when it needs per-message repository context. If there is no such snapshot, it
falls back to `work_context.current`.

## Message Contract

Each message uses this shape:

```json
{
  "id": "message-id",
  "parent_id": "optional-parent-id",
  "role": "user",
  "created_at": "2026-05-28T00:00:00Z",
  "work_snapshot_id": "work-snapshot-1",
  "parts": [
    {
      "type": "text",
      "text": "message text"
    }
  ],
  "raw_source_ref": "raw/codex/session.jsonl:12"
}
```

Allowed roles:

- `user`;
- `assistant`;
- `system`;
- `tool`;
- `unknown`.

Allowed part types:

- `text`;
- `tool_call`;
- `tool_result`;
- `image`;
- `file`;
- `reasoning`;
- `todo_state`;
- `token_usage`;
- `unknown`.

Unknown source parts are preserved as `type="unknown"` with a redacted or
schema-only summary in the normalized message and the full original event in raw
storage. Nothing unsupported should be silently dropped.

## Directional Mapping

### Codex to Bridge

Read from `threads` and the rollout JSONL.

Map:

- `threads.id` -> `source.session_id`;
- `threads.title` -> `session.title`;
- `threads.model_provider` -> `session.provider`;
- `threads.model` -> `session.model`;
- `threads.cwd` -> `work_context.primary_cwd`;
- `threads.git_branch`, `threads.git_sha`, `threads.git_origin_url` ->
  `work_context.current`;
- `session_meta.payload.git` and any future per-turn Git fields ->
  `work_context.snapshots[]`;
- `response_item.payload.type=user_message|message` with user role ->
  bridge user messages;
- `response_item.payload.type=agent_message|message` with assistant role ->
  bridge assistant messages;
- tool call/output payloads -> `tool_call` and `tool_result` parts;
- reasoning payloads -> `reasoning` parts;
- token count events -> `token_usage` parts or session extras.

Do not parse shell command output to infer branch changes in v1. It is too easy
to mistake ordinary message text for repository state. A later version may add
an opt-in heuristic preview, but it must be clearly marked as inferred.

### Bridge to Codex

Create a new Codex session by default.

Map:

- bridge `session.title` -> `threads.title`;
- bridge `session.provider` -> `threads.model_provider`;
- bridge `session.model` -> `threads.model`;
- bridge `work_context.primary_cwd` -> `threads.cwd`;
- bridge `work_context.current.git_branch` -> `threads.git_branch`;
- bridge `work_context.current.git_sha` -> `threads.git_sha`;
- bridge `work_context.current.git_origin_url` -> `threads.git_origin_url`;
- bridge messages -> a compatible rollout JSONL.

The full bridge metadata should be preserved in a sidecar under `.codex` or as
an ignored rollout metadata event that Codex can safely skip. The importer must
not modify pinned state, active provider config, auth files, or existing
sessions unless an explicit future overwrite mode is added.

### Droid to Bridge

Read from Droid session JSONL, companion settings, and index files.

Map:

- `session_start.id` -> `source.session_id`;
- `session_start.title` -> `session.title`;
- `message.id` -> bridge message id;
- `message.parentId` -> bridge parent id;
- `message.timestamp` -> bridge message timestamp;
- `message.message.role` -> bridge role;
- `message.message.content[].type=text` -> text parts;
- `tool_use` and `tool_result` -> tool parts;
- `todo_state` -> `todo_state` parts or session extras;
- `*.settings.json.providerLock` -> provider/model metadata when usable;
- `*.settings.json.tokenUsage` -> token usage extras, redacted if needed.

If Droid lacks Git context, set `work_context.current.confidence="unknown"` and
leave `timeline_complete=false`.

### Bridge to Droid

Create a new Droid session by default.

Map:

- bridge `session.title` -> `session_start.title`;
- bridge messages -> Droid `message` events;
- text parts -> Droid text content;
- tool calls/results -> Droid tool content where compatible;
- unsupported parts -> schema summaries plus raw bridge sidecar;
- provider/model -> companion settings if Droid accepts the field shape.

Because native Droid Git fields are not confirmed, write work context to a
bridge sidecar first. Do not add unverified custom keys to Droid-owned JSONL in
v1.

## Identity Policy

Default import behavior creates new destination session IDs. This avoids
collisions and prevents accidental overwrite of real user chats.

The bridge stores source IDs in metadata:

- `source.app`;
- `source.session_id`;
- `source.path`;
- optional `source.forked_from_id`.

Deterministic ID reuse is reserved for future mirror mode. It must require an
explicit flag and a mapping database.

## Preview and Safety

Every conversion command should have a preview path before an apply path.

Preview reports:

- source session count;
- sessions that can be converted;
- sessions skipped and why;
- message counts by role;
- unsupported event counts by source type;
- work context quality: current snapshot present/missing, timeline complete or
  incomplete, number of branch/SHA snapshots;
- files that would be written.

Apply behavior:

- create backups before writing destination-owned files;
- upsert only when the target command explicitly says so;
- never delete destination sessions in v1;
- never copy keys, auth files, PINs, or secret config;
- never run Git commands that mutate the project.

## Mirror Sync Later

Mirror sync should be a separate layer on top of the bridge contract.

It needs its own state file:

```json
{
  "version": 1,
  "pairs": [
    {
      "bridge_id": "stable-bridge-id",
      "codex_session_id": "codex-id",
      "droid_session_id": "droid-id",
      "last_codex_hash": "hash",
      "last_droid_hash": "hash",
      "last_synced_at": "2026-05-28T00:00:00Z"
    }
  ]
}
```

Mirror mode must start as preview-only. Conflict policy should be explicit:

- `local`;
- `remote`;
- `newer`.

Deletion should remain disabled by default. Branch changes should be treated as
metadata changes and shown in the preview. Mirror mode should warn if the
current working tree branch differs from the latest bridge snapshot, but it
should not checkout or reset anything automatically.

## Proposed CLI Surface

Read-only discovery:

- `--codex-sessions`
- `--droid-sessions`
- `--chat-bridge-preview ZIP_OR_SESSION`
- `--chat-bridge-from codex|droid`

One-shot transfer:

- `--export-chat-bridge ZIP`
- `--import-chat-bridge ZIP`
- `--codex-to-droid`
- `--droid-to-codex`
- `--chat-session ID1,ID2`
- `--chat-project PATH`
- `--chat-with-raw`
- `--chat-without-raw`

Future mirror layer:

- `--chat-mirror-preview`
- `--chat-mirror-apply`
- `--chat-mirror-state PATH`
- `--chat-conflict local|remote|newer`

The first implementation does not need every flag above. The minimum useful
slice is read-only listing, bridge preview, and one export direction.

## Testing

Use temp Codex and Factory homes only.

Cover:

- Codex session listing without printing message bodies;
- Droid session listing without printing message bodies;
- empty Droid sessions containing only `session_start`;
- Codex rollout with missing or unreadable JSONL safely skipped;
- text-only Codex to bridge conversion;
- text-only Droid to bridge conversion;
- tool call/tool result preservation as structured parts;
- unknown event preservation in raw storage;
- branch snapshot from Codex `threads.git_branch/git_sha`;
- branch snapshot from Codex `session_meta.payload.git` when present;
- incomplete timeline marked as `timeline_complete=false`;
- bridge import does not mutate auth, active provider, pinned state, or existing
  unrelated sessions;
- preview writes no files;
- redaction of keys, tokens, auth payloads, and PIN-like values.

## Open Implementation Notes

- Prefer a small new module such as `chat_bridge.py` instead of growing
  `codex_chat_transformer.py` further.
- Keep adapters separate: `CodexChatAdapter`, `DroidChatAdapter`, and a shared
  bridge schema validator.
- Use stdlib JSON and ZIP handling.
- Validate schema shape internally even without adding a third-party JSON Schema
  dependency.
- Keep raw event files optional on import, required for full-fidelity export.

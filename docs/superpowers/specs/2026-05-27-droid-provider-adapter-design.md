# Droid Provider Adapter Design

Date: 2026-05-27

## Goal

Add low-risk Factory Droid provider management to Codex Chat Transformer. The first version manages Droid models and endpoints only. It does not convert chats between Codex and Droid yet.

The adapter must respect the current Factory installation in `C:\Users\test\.factory`, where:

- `settings.json` is JSONC with comments and current CLI settings.
- `config.json` contains legacy `custom_models` and still works.
- sessions live under `sessions/<uuid>.jsonl` with companion `sessions/<uuid>.settings.json`.

## Non-Goals

- No Codex to Droid chat conversion in this phase.
- No mutation of Droid auth files: `auth.json`, `auth.v2.file`, `auth.v2.key`.
- No sync of Factory cache, logs, telemetry, certs, or binaries.
- No new external dependencies.
- No large GUI redesign.

## Configuration Strategy

Factory currently has two model configuration surfaces:

1. `settings.json` with `customModels`, `sessionDefaultSettings`, and `modelFavorites`.
2. `config.json` with legacy `custom_models`.

The adapter reads both. `settings.json` takes priority for the current model because it is the newer settings surface. `config.json` remains read-only compatibility input.

New managed Droid models are written to `settings.local.json`, not directly to `settings.json`. This preserves comments in `settings.json` and avoids overwriting a working legacy setup. The effective settings view is:

1. Load `settings.json` as JSONC.
2. Load `settings.local.json` as JSON/JSONC if it exists.
3. Merge local values over base values for the Droid fields managed by this tool.
4. Read `config.json` legacy models for diagnostics and optional migration.

Before every write, create a timestamped backup next to the changed file.

## CLI Surface

Add these flags:

- `--droid-models`: list effective Droid custom models, active model, favorites, and source file.
- `--droid-doctor`: validate Factory paths, parse settings, show legacy/current model counts, detect duplicate IDs, and warn about missing keys without printing secrets.
- `--droid-add-neurogate`: add the three NeuroGate models from the provided template.
- `--droid-import-provider NAME`: convert one saved Codex provider profile into a Droid custom model.
- `--droid-use MODEL_ID`: set Droid active model and reasoning effort in `settings.local.json`.
- `--droid-remove-model MODEL_ID`: remove a managed model from `settings.local.json` only.
- `--droid-settings PATH`: optional override for the Factory settings path, mostly for tests.
- `--droid-with-key`: allow writing a direct API key into Droid settings. Default behavior avoids direct key writes when possible.
- `--droid-api-key-env VAR`: set the environment variable reference used for Droid `apiKey`, defaulting to provider-specific names such as `NEUROGATE_API_KEY`.

These commands are independent from existing Codex provider commands.

## Data Mapping

Codex provider profile to Droid `customModels`:

- Codex profile name -> Droid `displayName`.
- Codex `provider_section.base_url` -> Droid `baseUrl`.
- Codex model -> Droid `model`.
- Codex provider section name -> stable Droid id, prefixed as `custom:<safe-name>`.
- Codex reasoning effort -> Droid `reasoningEffort`, default `medium`.
- Droid `provider` defaults to `openai` unless the Codex provider clearly maps to another supported Factory provider.
- API key is copied only when the user explicitly requests key writing.

NeuroGate bootstrap creates:

- `custom:NeuroGate-GPT-5.5-1`
- `custom:NeuroGate-GPT-5.4-2`
- `custom:NeuroGate-GPT-5.4-Mini-3`

The bootstrap sets base URL to `https://api.neurogate.space/v1` and provider to `openai`. If Droid has no active model yet, it initializes the active/default model to GPT-5.5 with medium reasoning. If Droid already has an active model in `settings.json` or `settings.local.json`, bootstrap preserves that selection and only adds the NeuroGate models/favorites.

`--droid-use` writes both top-level `model` and `sessionDefaultSettings.model` to the selected model ID. It also writes top-level `reasoningEffort` and `sessionDefaultSettings.reasoningEffort` when a reasoning value is available. This keeps the local file compatible with both the current local settings shape and the NeuroGate template provided by the user.

## Secret Handling

The tool must never print API keys, Factory auth tokens, PINs, or raw auth payloads.

Default behavior should not copy direct keys from Codex profiles into Droid settings. For NeuroGate, if no key is explicitly provided, the adapter writes an environment reference such as `${NEUROGATE_API_KEY}` rather than inventing a secret.

If `--droid-with-key` is used with the existing `--api-key` flag, the command may copy/write the key but must still redact it from terminal output and operation history.

## JSONC Handling

Implement a small stdlib-only JSONC reader that strips line and block comments while respecting quoted strings. It is used for `settings.json` and `settings.local.json`.

Writes use formatted JSON. Because writes go to `settings.local.json`, this does not destroy comments in the user's main `settings.json`.

## Operation History

Append redacted events to `.codex/operation_history.jsonl` for:

- `droid_model_added`
- `droid_model_removed`
- `droid_model_selected`
- `droid_provider_imported`
- `droid_doctor_checked`

History entries include model IDs, display names, source file paths, and counts. They do not include keys or session message bodies.

## Future Chat Transfer

The observed Droid session format is promising:

- JSONL starts with `session_start`.
- Messages use `type=message`, `message.role`, and `message.content[]`.
- Companion settings contain `providerLock`, timing, and token usage.

Chat conversion should be a separate phase after a fuller schema sample is collected. That phase should start read-only: list Droid sessions, summarize metadata, and compare a few Droid messages with Codex rollout events before writing any converter.

## Testing

Use temp Factory homes for tests. Cover:

- JSONC parsing with comments and comment-like text inside strings.
- Merge order: `settings.local.json` overrides `settings.json`.
- Read-only legacy `config.json` support.
- NeuroGate bootstrap idempotency.
- Codex provider to Droid model mapping.
- `--droid-use` active model update.
- `--droid-remove-model` only removes local managed entries.
- Secret redaction in output and history.
- No writes to Factory auth files or legacy `config.json`.

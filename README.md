# Codex Chat Transformer

[Русский](README.ru.md) | [中文](README.zh.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org/)
[![Zero external deps](https://img.shields.io/badge/deps-zero-green.svg)]()

A tool for managing [Codex Desktop](https://github.com/openai/codex) sessions — convert chats between providers, pin them to the sidebar, and create full backups.

---

## Quick Start

Install:
```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.sh | bash
```
```powershell
# PowerShell
irm https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.ps1 | iex
```

Basic usage:
```bash
# GUI launch
codex_manager.cmd
```
```bash
# Save current provider
python codex_chat_transformer.py --save-provider MyProvider
```
```bash
# Switch provider + convert chats
python codex_chat_transformer.py --use-provider MyProvider
```
```bash
# Full backup
python codex_chat_transformer.py --backup
```

---

## The Problem

Codex Desktop creates separate "virtual spaces" per connection method. When you switch between subscription and API key, chats "disappear" — they're still there, but the sidebar filters by `model_provider`. Trying to continue a chat from another provider gives 401 because it hits the wrong endpoint.

---

## Features

### Chat Conversion

Converts chats from one provider to another. Changes `model_provider` in DB and JSONL. Supports project filter and model mapping. Auto-creates backup. Verification report after conversion.

```bash
python codex_chat_transformer.py --from openai --to MyProvider
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --dry-run
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --project my_project
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --from-model gpt-4 --to-model gpt-5.5
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --thread <ID>
```
```bash
python codex_chat_transformer.py --from openai --to MyProvider --skip-pinned
```

### Provider Management

All providers live in a single `config.toml` — each as a `[model_providers.*]` section. Switching only changes `model_provider`, `model`, and `model_reasoning_effort` fields. Profiles are saved in `providers.json` with automatic migration from old format.

> **Note:** Provider `openai` is protected — URL and API key fields are read-only. To change OpenAI credentials, authenticate directly through Codex Desktop.

Save current provider as profile:
```bash
python codex_chat_transformer.py --save-provider MyProvider
```

Switch:
```bash
python codex_chat_transformer.py --use-provider MyProvider
```

Add from JSON file:
```bash
python codex_chat_transformer.py --add-provider provider.json
```
```bash
python codex_chat_transformer.py --add-provider provider.json --api-key sk-xxx
```

Edit:
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-model gpt-5.5
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-url https://new.url/v1
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-key sk-new
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-reasoning high
```
```bash
python codex_chat_transformer.py --edit-provider MyProvider --set-name NewName
```

Change model (no provider switch):
```bash
python codex_chat_transformer.py --set-model gpt-5.5
```

Remove:
```bash
python codex_chat_transformer.py --remove-provider MyProvider
```

List:
```bash
python codex_chat_transformer.py --providers
```

Auto-detect:
```bash
python codex_chat_transformer.py --detect-provider
```

### Pin Chats

Makes chats visible regardless of the active provider. Pinned chats always appear in the sidebar. Used for reactivating chats when transitioning between providers.

```bash
python codex_chat_transformer.py --pin-top 10
```
```bash
python codex_chat_transformer.py --pin-top 10 --project my_project
```
```bash
python codex_chat_transformer.py --pin-list
```
```bash
python codex_chat_transformer.py --unpin-all
```

### Full Backup

Packs the entire `.codex` folder into a ZIP: database, configs, auth, all sessions, `providers.json`.

```bash
python codex_chat_transformer.py --backup
```
```bash
python codex_chat_transformer.py --restore backup_20260518_120000
```
```bash
python codex_chat_transformer.py --restore-zip codex_backup_20260518.zip
```

### Codex Pack

Portable subset ZIP for moving providers and sessions without copying the full `.codex` folder.

```bash
python codex_chat_transformer.py --export-pack my.codex-pack.zip --scope all
```
```bash
python codex_chat_transformer.py --export-pack providers.zip --scope providers --providers OpenRouter --without-keys
```
```bash
python codex_chat_transformer.py --import-pack my.codex-pack.zip --scope sessions --sessions SESSION_ID
```

Pack import is upsert-only: it does not delete local data and does not switch the active provider.

### Search & History

```bash
python codex_chat_transformer.py --search "database migration" --project C:\Research\my_project
```
```bash
python codex_chat_transformer.py --history --history-limit 20
```

Search scans session metadata first and falls back to JSONL text. Operation history is stored as `.codex/operation_history.jsonl` with API keys, PINs, and auth payloads redacted.

### Doctor

Read-only health check: database, config, auth, provider profile health, pinned threads, and recent operations.

```bash
python codex_chat_transformer.py --doctor
```

### P2P Sync

Local bidirectional sync between machines via HTTP API + web Dashboard. Both machines run the same server. Browser acts as orchestrator — Push and Pull providers, sessions, and project files.

```bash
# Start sync server (auto-selects free port)
python codex_chat_transformer.py --sync-host

# Start on specific port
python codex_chat_transformer.py --sync-host --sync-port 8080

# Connect to remote and pull data
python codex_chat_transformer.py --sync-pull 192.168.1.60:8080 --sync-pin A7B3C2
```

Features:
- Web Dashboard (dark theme, 5 tabs: Connect, Providers, Sessions, Files, Settings)
- PIN-based auth with rate limiting
- **Trusted devices (pairing)**: enter PIN once → device remembered → auto-connect without PIN
- **LAN auto-discovery**: UDP beacon with server name, click to connect from Dashboard
- Bidirectional: Push + Pull per item
- Provider import modes: with key / without key / skip / keep both
- Session sync: JSONL download + DB insertion
- File sync: SHA-256 hash diff + ZIP packaging, preview mode, conflict policy (`local`, `remote`, `newer`)
- File scans report included/excluded counts and sample excluded paths
- Auto-link: session Pull/Push detects linked project and offers file sync
- Background auto-sync polling (30s–5 min, configurable)
- Auto port selection (tries 8080-8099)
- UDP broadcast for LAN discovery
- Git dirty state check before file sync
- **Worktree recreation**: native `git worktree add` on receiving machine preserves isolation
- **Project path mapping**: remembers local↔remote directory pairs for auto-fill
- **Git mismatch warning**: alerts when branches or commits differ between machines
- **Provider rename**: `--edit-provider NAME --set-name NEW` updates TOML + providers.json
- Auto-backup before every write operation

---

## GUI

GUI is a thin wrapper over CLI (`import codex_chat_transformer as ct`), no code duplication.

### GUI Features

- One-click provider switching
- Background thread conversion — GUI doesn't freeze
- Edit provider: button or right-click context menu
- Model and reasoning editable inline in info panel
- Reasoning dropdown: low / medium / high / xhigh / default
- Auto-detection of JSON configs next to app
- API key prompt on import if missing
- Provider `openai` is read-only (auth via Codex)
- Auto-migration of old `config.toml` format profiles
- RU / EN interface

### Launch

| Platform | Command |
|---|---|
| Windows | `codex_manager.cmd` (double-click) |
| PowerShell | `.\codex_manager.ps1` |
| Linux / macOS | `./codex_manager.sh` |

### Adding a provider

Place a JSON file next to the app — it's auto-detected. If no API key is present, the app will prompt for it.

```json
{
  "name": "NeuroGate API",
  "model": "gpt-5.5",
  "base_url": "https://api.example.com/v1",
  "wire_api": "responses",
  "model_reasoning_effort": "medium"
}
```

---

## Requirements

- Python 3.7+
- Tkinter (included with standard Python)
- No external dependencies

### Optional: System Tray

The tray widget provides server control from the system tray with a colored status indicator:
- Red — server stopped
- Yellow — server running, waiting for connections
- Green — active sync in progress

```bash
pip install pystray Pillow
python sync_tray.py
```

Features: Start/Stop server, Open Dashboard, Autorun on startup (Windows/macOS), single instance lock.
The tray is fully optional — the main tool and Dashboard work without it.

---

## Security

API keys are stored locally with base64 obfuscation (both CLI and GUI). This is **not** encryption. Keep `providers.json` and `auth.json` secure. The tool never sends keys anywhere except the configured API endpoint.

---

## FAQ

**Q: Chats disappeared after switching connection.**

A: Convert to current provider: `--list` to see names, then `--from openai --to YourProvider`. Codex must be closed.

**Q: Chat is visible but sending gives 401.**

A: Provider in JSONL didn't update. Re-run conversion — both DB and JSONL are updated.

**Q: Convert chats from one project only?**

A: `--from openai --to MyProvider --project my_project`. Filters by the `project` field in the database.

**Q: How to map models during conversion?**

A: `--from openai --to MyProvider --from-model gpt-4 --to-model gpt-5.5`. Replaces model name in JSONL files.

**Q: Can I undo?**

A: Three ways:
1. `--restore backup_YYYYMMDD_HHMMSS` — rollback DB
2. `--restore-zip file.zip` — full restore
3. Reverse conversion: `--from YourProvider --to openai`

**Q: Must I close Codex?**

A: **Yes.** Codex keeps the DB open and may overwrite changes.

**Q: What does `--doctor` do?**

A: Read-only diagnostics: checks DB, config, auth, providers, pinned threads. Changes nothing.

**Q: Change model without switching provider?**

A: GUI: click model in info panel and type new one. CLI: `--set-model gpt-5.5`.

**Q: How to change reasoning effort?**

A: GUI: dropdown in info panel. CLI: `--edit-provider NAME --set-reasoning high`.

**Q: How to sync providers between two computers?**

A: Run `--sync-host` on both. Open Dashboard in browser, enter remote IP + PIN, select providers and click Pull or Push.

**Q: Can I sync without the Dashboard?**

A: Yes: `--sync-pull IP:PORT --pin XXXXXX` opens an interactive CLI menu.

---

## Storage

| File | Content |
|---|---|
| `state_5.sqlite` → `threads` | Chat metadata: provider, title, project, tokens |
| `sessions/YYYY/MM/DD/rollout-*.jsonl` | Full chat history |
| `.codex-global-state.json` → `pinned-thread-ids` | Pinned chats |
| `config.toml` | All providers `[model_providers.*]` + settings |
| `auth.json` | Current auth (API key or OAuth) |
| `providers.json` | Provider profiles (`provider_section` + `model` + auth, b64 obfuscation) |
| `operation_history.jsonl` | Append-only operation log with secrets redacted |

---

## Files

```
codex_chat_transformer.py    — CLI: conversion, providers, pin, backup, doctor, edit, sync
codex_manager_gui.py         — GUI: switching, editing, model change, sync (CLI wrapper)
codex_sync.py                — P2P sync engine: server, client, Dashboard, file sync, auto-sync
sync_tray.py                 — System tray widget (optional, requires pystray + Pillow)
test_smoke.py                — Smoke tests (47 tests)
codex_manager.cmd / .ps1     — Windows launchers
codex_manager.sh             — Unix launcher
providers_template.json      — Provider template
providers_example.json       — Provider example
CHANGELOG.md                 — Changelog
install.sh / install.ps1     — One-line installers
```

## License

[MIT](LICENSE)

# Codex Chat Transformer

A tool for managing [Codex Desktop](https://github.com/openai/codex) sessions — convert chats between providers, pin them to the sidebar, and create full backups.

Инструмент для управления сессиями [Codex Desktop](https://github.com/openai/codex) — конвертация чатов между провайдерами, закрепление в сайдбаре и полное резервное копирование.

---

## Quick Start / Быстрый старт

Install / Установка:
```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.sh | bash
```
```powershell
# PowerShell
irm https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.ps1 | iex
```

Basic usage / Основные команды:
```bash
# GUI launch / Запуск GUI
codex_manager.cmd
```
```bash
# Save current provider / Сохранить текущего провайдера
python codex_chat_transformer.py --save-provider MyProvider
```
```bash
# Switch provider + convert chats / Переключить провайдер + конвертировать чаты
python codex_chat_transformer.py --use-provider MyProvider
```
```bash
# Full backup / Полный бекап
python codex_chat_transformer.py --backup
```

---

## The Problem / Проблема

**EN:** Codex Desktop creates separate "virtual spaces" per connection method. When you switch between subscription and API key, chats "disappear" — they're still there, but the sidebar filters by `model_provider`. Trying to continue a chat from another provider gives 401 because it hits the wrong endpoint.

**RU:** Codex Desktop создаёт отдельные «виртуальные пространства» для каждого способа подключения. При переключении между подпиской и API-ключом чаты «пропадают» — они на месте, но сайдбар фильтрует по текущему `model_provider`. Если попытаться продолжить чужой чат — получаешь 401, потому что он стучится не на тот endpoint.

---

## Features / Возможности

### Chat Conversion / Конвертация чатов

Converts chats from one provider to another. Changes `model_provider` in DB and JSONL. Supports project filter and model mapping. Auto-creates backup. Verification report after conversion.

Конвертирует чаты с одного провайдера на другой. Меняет `model_provider` в базе и JSONL-файлах. Поддерживает фильтрацию по проекту и маппинг моделей. Автоматически создаёт бекап. Отчёт о верификации после конвертации.

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

### Provider Management / Управление провайдерами

All providers live in a single `config.toml` — each as a `[model_providers.*]` section. Switching only changes `model_provider`, `model`, and `model_reasoning_effort` fields. Profiles are saved in `providers.json` with automatic migration from old format.

Все провайдеры хранятся в одном `config.toml` — каждый как отдельная секция `[model_providers.*]`. Переключение меняет только `model_provider`, `model` и `model_reasoning_effort`, не трогая остальные настройки. Профили сохраняются в `providers.json` с автоматической миграцией старого формата.

> **Note:** Provider `openai` is protected — URL and API key fields are read-only. To change OpenAI credentials, authenticate directly through Codex Desktop.

Save current provider as profile / Сохранить текущего провайдера как профиль:
```bash
python codex_chat_transformer.py --save-provider MyProvider
```

Switch / Переключиться:
```bash
python codex_chat_transformer.py --use-provider MyProvider
```

Add from JSON file / Добавить из JSON-файла:
```bash
python codex_chat_transformer.py --add-provider provider.json
```
```bash
python codex_chat_transformer.py --add-provider provider.json --api-key sk-xxx
```

Edit / Редактировать:
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

Change model (no provider switch) / Сменить модель (без переключения провайдера):
```bash
python codex_chat_transformer.py --set-model gpt-5.5
```

Remove / Удалить:
```bash
python codex_chat_transformer.py --remove-provider MyProvider
```

List / Список:
```bash
python codex_chat_transformer.py --providers
```

Auto-detect / Автообнаружение:
```bash
python codex_chat_transformer.py --detect-provider
```

### Pin Chats / Закрепление чатов

Makes chats visible regardless of the active provider. Pinned chats always appear in the sidebar. Used for reactivating chats when transitioning between providers.

Делает чаты видимыми при **любом** подключении. Pinned-чаты показываются всегда, независимо от провайдера. Используется для реактивации чатов при переходе между провайдерами.

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

### Full Backup / Полный бекап

Packs the entire `.codex` folder into a ZIP: database, configs, auth, all sessions, `providers.json`.

Упаковывает всю папку `.codex` в ZIP: база, конфиги, авторизация, все сессии, `providers.json`.

```bash
python codex_chat_transformer.py --backup
```
```bash
python codex_chat_transformer.py --restore backup_20260518_120000
```
```bash
python codex_chat_transformer.py --restore-zip codex_backup_20260518.zip
```

### Doctor / Диагностика

Read-only health check: database, config, auth, providers, pinned threads.

Read-only проверка состояния: база, конфиг, авторизация, провайдеры, закреплённые чаты.

```bash
python codex_chat_transformer.py --doctor
```

---

## GUI

GUI. Thin wrapper over CLI (`import codex_chat_transformer as ct`), no code duplication.

GUI — тонкая обёртка над CLI (`import codex_chat_transformer as ct`), дублирования кода нет.

### Features / Возможности GUI

- One-click provider switching / Переключение провайдеров одним кликом
- Background thread conversion — GUI doesn't freeze / Конвертация чатов в фоновом потоке — GUI не зависает
- Edit provider: button or right-click context menu / Редактирование провайдера: кнопка или правый клик
- Model and reasoning editable inline in info panel / Модель и reasoning меняются прямо в info-панели
- Reasoning dropdown: low / medium / high / xhigh / default / Выпадающий список reasoning
- Auto-detection of JSON configs next to app / Автообнаружение JSON-конфигов рядом с приложением
- API key prompt on import if missing / Запрос API-ключа при импорте если отсутствует
- Provider `openai` is read-only (auth via Codex) / Провайдер `openai` защищён от редактирования
- Auto-migration of old `config.toml` format profiles / Автоматическая миграция старых профилей
- RU / EN interface / RU / EN интерфейс

### Launch / Запуск

| Platform | Command |
|---|---|
| Windows | `codex_manager.cmd` (double-click) |
| PowerShell | `.\codex_manager.ps1` |
| Linux / macOS | `./codex_manager.sh` |

### Adding a provider / Добавление провайдера

Place a JSON file next to the app — it's auto-detected. If no API key is present, the app will prompt for it.

Положите JSON-файл рядом с приложением — он подхватится автоматически. Если ключа нет — программа спросит.

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

## Requirements / Требования

- Python 3.7+
- Tkinter (included with standard Python / входит в стандартную поставку Python)
- No external dependencies / Без внешних зависимостей

---

## Security / Безопасность

**EN:** API keys are stored locally with base64 obfuscation (both CLI and GUI). This is **not** encryption. Keep `providers.json` and `auth.json` secure. The tool never sends keys anywhere except the configured API endpoint.

**RU:** API-ключи хранятся локально с base64 обфусцированием (и в CLI, и в GUI). Это **не** шифрование. Не передавайте `providers.json` и `auth.json` третьим лицам. Инструмент не отправляет ключи никуда, кроме настроенного API endpoint.

---

## FAQ

**Q: Chats disappeared after switching connection. / Чаты пропали после смены способа подключения.**

A: Convert to current provider: `--list` to see names, then `--from openai --to YourProvider`. Codex must be closed. / Конвертируйте в текущий провайдер: `--list` чтобы узнать имя, затем `--from openai --to YourProvider`. Codex должен быть закрыт.

**Q: Chat is visible but sending gives 401. / Чат видно, но при отправке — 401.**

A: Provider in JSONL didn't update. Re-run conversion — both DB and JSONL are updated. / Провайдер в JSONL не обновился. Перезапустите конвертацию — обновляются и БД, и JSONL.

**Q: Convert chats from one project only? / Как конвертировать чаты только одного проекта?**

A: `--from openai --to MyProvider --project my_project`. Filters by the `project` field in the database. / Фильтрует по полю `project` в базе.

**Q: How to map models during conversion? / Как маппить модели при конвертации?**

A: `--from openai --to MyProvider --from-model gpt-4 --to-model gpt-5.5`. Replaces model name in JSONL files. / Заменяет имя модели в JSONL.

**Q: Can I undo? / Можно ли откатить?**

A: Three ways / Три способа:
1. `--restore backup_YYYYMMDD_HHMMSS` — rollback DB / откатить БД
2. `--restore-zip file.zip` — full restore / полное восстановление
3. Reverse / Обратная конвертация: `--from YourProvider --to openai`

**Q: Must I close Codex? / Нужно ли закрывать Codex?**

A: **Yes.** Codex keeps the DB open and may overwrite changes. / **Да.** Codex держит БД открытой и может перезаписать изменения.

**Q: What does `--doctor` do? / Что делает `--doctor`?**

A: Read-only diagnostics: checks DB, config, auth, providers, pinned threads. Changes nothing. / Read-only диагностика: проверяет базу, конфиг, авторизацию, провайдеры, pinned-чаты. Ничего не меняет.

**Q: Change model without switching provider? / Как сменить модель без переключения провайдера?**

A: GUI: click model in info panel and type new one. CLI: `--set-model gpt-5.5`. / В GUI — кликните на модель в info-панели и введите новую. В CLI — `--set-model gpt-5.5`.

**Q: How to change reasoning effort? / Как сменить reasoning effort?**

A: GUI: dropdown in info panel. CLI: `--edit-provider NAME --set-reasoning high`. / В GUI — выпадающий список в info-панели. В CLI — `--edit-provider NAME --set-reasoning high`.

---

## Storage / Где что хранится

| File / Файл | Content / Содержимое |
|---|---|
| `state_5.sqlite` → `threads` | Chat metadata: provider, title, project, tokens / Метаданные чатов |
| `sessions/YYYY/MM/DD/rollout-*.jsonl` | Full chat history / Полная история чата |
| `.codex-global-state.json` → `pinned-thread-ids` | Pinned chats / Закреплённые чаты |
| `config.toml` | All providers `[model_providers.*]` + settings / Все провайдеры + настройки |
| `auth.json` | Current auth (API key or OAuth) / Текущая авторизация |
| `providers.json` | Provider profiles (`provider_section` + `model` + auth, b64 obfuscation) / Профили провайдеров |

---

## Files / Файлы

```
codex_chat_transformer.py    — CLI: conversion, providers, pin, backup, doctor, edit / CLI: конвертация, провайдеры, закрепление, бекап, doctor, редактирование
codex_manager_gui.py         — GUI: switching, editing, model change (CLI wrapper) / GUI: переключение, редактирование, смена модели (обёртка над CLI)
test_smoke.py                — Smoke tests (14 tests) / Smoke-тесты (14 тестов)
codex_manager.cmd / .ps1     — Windows launchers / Windows запускаторы
codex_manager.sh             — Unix launcher / Unix запускатор
providers_template.json      — Provider template / Шаблон провайдера
providers_example.json       — Provider example / Пример провайдера
CHANGELOG.md                 — Changelog / История изменений
install.sh / install.ps1     — One-line installers / Установка одной строкой
```

## License

[MIT](LICENSE)

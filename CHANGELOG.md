# Changelog

## [1.0.0] — 2026-05-23

### Chat Conversion / Конвертация чатов
- Convert chats between providers: `model_provider` in DB + JSONL / Конвертация чатов между провайдерами: `model_provider` в БД + JSONL
- Project filter: `--project my_project` / Фильтрация по проекту: `--project my_project`
- Model mapping: `--from-model gpt-4 --to-model gpt-5.5` / Маппинг моделей: `--from-model gpt-4 --to-model gpt-5.5`
- Select specific chat: `--thread <ID>` / Выбор конкретного чата: `--thread <ID>`
- Skip pinned: `--skip-pinned` / Пропуск закреплённых: `--skip-pinned`
- Dry-run mode: `--dry-run` / Dry-run режим: `--dry-run`
- Verification report after conversion / Отчёт о верификации после конвертации
- Automatic DB backup before each conversion / Автоматический бекап БД перед каждой конвертацией

### Provider Management / Управление провайдерами
- Multi-provider TOML: all `[model_providers.*]` in one `config.toml` / Все провайдеры в одном `config.toml`
- Switching only changes `model_provider`, `model`, `model_reasoning_effort` / Переключение меняет только `model_provider`, `model`, `model_reasoning_effort`
- All other settings preserved (projects, MCP, plugins, features) / Все остальные настройки сохраняются
- Profiles in `providers.json` with new format (`provider_section` + `model`) / Профили в новом формате
- Auto-migration of old profiles on load / Автоматическая миграция старых профилей
- Save profile: `--save-provider NAME` / Сохранение профиля: `--save-provider NAME`
- Switch: `--use-provider NAME` (auto-saves current) / Переключение: `--use-provider NAME`
- Add from JSON: `--add-provider file.json --api-key sk-xxx` / Добавление из JSON: `--add-provider file.json`
- Edit: `--edit-provider NAME --set-model / --set-url / --set-key / --set-reasoning` / Редактирование провайдера
- Remove: `--remove-provider NAME` / Удаление: `--remove-provider NAME`
- Standalone model change: `--set-model gpt-5.5` / Смена модели отдельно: `--set-model gpt-5.5`
- Detect unsaved provider: `--detect-provider` / Обнаружение несохранённых провайдеров
- Base64 API key obfuscation (CLI + GUI) / Base64 обфускация API-ключей

### Pin Chats / Закрепление чатов
- Pin N recent chats: `--pin-top N` / Закрепление N свежих чатов: `--pin-top N`
- Project filter: `--project` / Фильтр по проекту: `--project`
- View pinned: `--pin-list` / Просмотр закреплённых: `--pin-list`
- Unpin all: `--unpin-all` / Снятие всех: `--unpin-all`

### Backup / Бекап
- Full ZIP backup of `.codex` (DB, configs, auth, sessions, `providers.json`) / Полный ZIP бекап `.codex`
- Restore DB: `--restore backup_YYYYMMDD_HHMMSS` / Восстановление БД: `--restore`
- Restore from ZIP: `--restore-zip file.zip` / Восстановление из ZIP: `--restore-zip`

### Doctor / Диагностика
- Read-only health check: `--doctor` / Read-only проверка: `--doctor`
- Checks: DB, config.toml, auth.json, providers, pinned chats, Codex process / Проверяет: БД, конфиг, авторизацию, провайдеры, pinned-чаты

### GUI
- Thin CLI wrapper — `import codex_chat_transformer as ct`, no code duplication / Тонкая обёртка над CLI, без дублирования
- RU / EN interface toggle / RU / EN интерфейс с переключением
- One-click provider switching / Переключение провайдеров одним кликом
- Background thread conversion (GUI stays responsive) / Конвертация чатов в фоновом потоке
- Inline model editing (click → type → Enter) / Инлайн редактирование модели
- Reasoning dropdown (low / medium / high / xhigh / default) / Выпадающий список reasoning
- Edit provider: button + right-click context menu / Редактирование: кнопка + правый клик
- Provider `openai` protected — URL and API key read-only / Провайдер `openai` защищён от редактирования
- Auto-detect JSON configs next to app / Автообнаружение JSON-конфигов рядом с приложением
- API key prompt on import if missing / Запрос API-ключа при импорте

### Tests / Тесты
- 14 smoke tests: syntax, merge config, b64, add/remove/edit provider, set model / 14 smoke-тестов
- `python test_smoke.py` — no external dependencies / без внешних зависимостей

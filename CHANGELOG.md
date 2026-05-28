# Changelog

## [1.4.0] - 2026-05-25

### Sync hardening
- CLI sync peer parsing now accepts `host`, `host:port`, `http://host:port`, and `https://host:port`, with explicit host/port validation before network I/O.
- File sync endpoints accept `preview` and `conflict` (`local`, `remote`, `newer`) fields; preview returns a plan without mutating files.
- `/api/repo-hashes` now returns compatible `files` plus per-file `meta` and excluded-file summary.
- Dashboard wires preview/conflict settings into file sync requests and shows included/excluded scan counts.

### Codex Pack, search, and history
- Added `--export-pack`, `--import-pack`, `--scope`, `--sessions`, and `--without-keys` for portable provider/session ZIP bundles.
- `--providers` still lists profiles when used alone, and filters pack import/export when passed a comma-separated value.
- Added `--search QUERY` with metadata-first session search and JSONL fallback.
- Added `.codex/operation_history.jsonl`, `--history`, and `--history-limit`; API keys, PINs, and auth payloads are redacted.
- `--doctor` now reports provider profile health and treats `openai` + `chatgpt` auth as valid without an API key.

### Factory Droid provider management
- Added `--droid-models`, `--droid-doctor`, `--droid-add-neurogate`, `--droid-import-provider`, `--droid-use`, and `--droid-remove-model`.
- Droid writes go to `settings.local.json`; existing `settings.json`, legacy `config.json`, and Factory auth files are left untouched.
- API keys default to environment variable references such as `${NEUROGATE_API_KEY}`; direct key writes require `--droid-with-key --api-key ...`.
- Droid doctor reports legacy `config.json` model count without failing healthy current `customModels` because legacy BYOK configs can still work.

### Chat Bridge
- Added first-slice Codex <-> Droid chat transfer helpers and CLI flags: `--droid-sessions`, `--codex-sessions`, `--droid-to-codex`, `--codex-to-droid`, `--chat-session`, `--chat-fresh-timestamps`, and `--chat-pin-old`.
- GUI now exposes a Chat Bridge panel for refreshing Droid/Codex session lists and launching Droid -> Codex or Codex -> Droid transfers with confirmation.
- Droid -> Codex imports create a verified `threads` row + rollout JSONL pair and create a full `.codex` backup before writing.
- Chat transfers preserve source timestamps by default, can import as fresh, and record session pairs in `chat_bridge_mappings.json` for future mirror sync.

### Tests
- 102 smoke tests (was 47), covering sync preview/conflicts, pack import/export, search, history redaction, provider health checks, Droid provider management, GUI wiring, and Chat Bridge transfer.

## [1.3.0] — 2026-05-25

### Multiplatform Sync & Git Safety / Мультиплатформенная синхронизация и безопасность Git
- Case-insensitive path validation via `os.path.normcase` — mixed slashes, drive letter case on Windows / Регистронезависимая валидация путей — смешанные слеши, регистр диска на Windows
- `check_git_dirty` uses `git rev-parse --is-inside-work-tree` instead of `.git` folder check — works in worktrees, submodules, monorepos / Проверка через git rev-parse вместо поиска .git — работает в worktrees, сабмодулях, монорепо
- `get_git_metadata()` helper — extracts branch, SHA, origin URL via git CLI / Хелпер извлечения ветки, SHA, origin URL
- SQLite sync fix: `INSERT OR IGNORE` + `UPDATE` in session upload handlers — prevents infinite auto-sync polling loop / Исправление SQLite: INSERT OR IGNORE + UPDATE — предотвращает бесконечный polling
- `sandbox_policy` column now synced with sessions / Колонка sandbox_policy теперь синхронизируется
- `conn.close()` wrapped in `finally` blocks in all DB operations / Закрытие conn обёрнуто в finally во всех DB-операциях
- **Dynamic schema detection**: `_get_sessions_list` reads columns via `PRAGMA table_info` — works with any Codex version / Динамическое чтение схемы БД — совместимость с любой версией Codex
- **`_upsert_session_record`**: `ON CONFLICT(id) DO UPDATE` with all current columns (`approval_mode`, `has_user_event`, `created_at`, `updated_at`, etc.) / INSERT с полным набором колонок текущей схемы
- **`--project` filter** now uses `cwd` column instead of non-existent `project` / Фильтр `--project` использует колонку `cwd` вместо несуществующей `project`

### File Sync Safety / Безопасность синхронизации файлов
- `EXCLUDE_PATTERNS` blocks `.env`, `.env.*`, `secrets/`, `.worktrees/`, `backup_*`, temp files from sync / Блокировка `.env`, `secrets`, `.worktrees`, `backup`, временных файлов
- `delete_files` operation with backup before removal — `deleted` status no longer ignored / Операция удаления файлов с бэкапом — статус `deleted` больше не игнорируется
- Dashboard local API calls now include `Authorization: Bearer` header via `localAuthHeaders()` / Локальные запросы Dashboard теперь с авторизацией
- CLI sync push reads providers directly from `providers.json` — no hardcoded `127.0.0.1:8080` / CLI push читает провайдеры напрямую, без хардкода порта

### Worktree Recreation & Project Path Mapping / Воссоздание Worktree и маппинг путей проектов
- `POST /api/recreate-worktree` — native `git worktree add` or `git checkout -f` on receiving machine / Нативное создание/выравнивание worktree на принимающей машине
- Scenario A: worktree doesn't exist → `git worktree add <path> <sha>` from base repo / Сценарий А: worktree нет → создание из базового репо
- Scenario B: worktree exists but stale → `git checkout -f <sha>` + file overlay / Сценарий Б: worktree устарел → переключение + накат файлов
- `POST /api/project-mappings` / `GET /api/project-mappings` — save and recall local↔remote directory pairs / Сохранение связок локальных и удалённых директорий
- Dashboard Files tab: separate Local and Remote project dir inputs with auto-fill from mappings / Раздельные поля локальной и удалённой директории с автозаполнением
- Git mismatch warning banner when branches or commits differ between local and remote / Предупреждение при несовпадении веток/коммитов

### Provider Edit Bugfixes / Исправления редактирования провайдеров
- Provider rename now removes old `[model_providers.OldName]` section from TOML (was leaving duplicate) / Переименование теперь удаляет старую секцию из TOML (раньше оставался дубликат)
- Provider rename auto-converts chats (`transform(old, new)`) in both CLI and GUI / При переименовании провайдера чаты автоматически конвертируются
- `edit_provider` CLI supports `--set-name` for renaming / CLI поддерживает переименование через --set-name
- Provider name sanitization: spaces and special chars (`/ \ : * ? " < > |`) replaced with `_` / Санитизация имени: пробелы и спецсимволы заменяются на `_`
- GUI updates config.toml correctly when active provider is renamed (checks both old and new name) / GUI корректно обновляет config.toml при переименовании активного провайдера
- Reasoning effort is added to config.toml even when not previously present (was silently dropped) / Reasoning добавляется в config.toml даже если его там не было
- `_remove_provider_section()` helper for clean TOML section removal / Хелпер для удаления секции из TOML

### Tests / Тесты
- 47 smoke tests (was 32) / 47 smoke-тестов (было 32)
- New: dynamic schema sessions, upload session with current schema, delete files, local auth, file excludes, `--project` cwd filter, CLI sync push, sanitize name, reasoning add-when-absent, provider rename / Новые: динамическая схема, upload сессий, удаление файлов, локальная авторизация, excludes, фильтр --project, CLI sync, санитизация имени

## [1.2.0] — 2026-05-24

### UDP Beacon + Trusted Devices (Pairing) / UDP Beacon + Доверенные устройства (Pairing)
- UDP beacon now broadcasts `server_id` (UUID) and `name` for stable device identification / UDP beacon теперь транслирует `server_id` (UUID) и `name` для стабильной идентификации
- Trusted device storage in `~/.codex/trusted_devices.json` — tokens stored as SHA-256 hashes / Хранилище доверенных устройств — токены хранятся как SHA-256 хэши
- One-time PIN pairing: `POST /api/pair` exchanges PIN for long-term crypto token / Одноразовый pairing: обмен PIN на долгосрочный токен
- Auto-connect: trusted devices connect without PIN, keyed by `server_id` (survives DHCP changes) / Авто-подключение: доверенные устройства подключаются без PIN, привязка по server_id
- `GET /api/local-info` — local-only endpoint returns PIN, server_id, trusted devices / Локальный endpoint возвращает PIN, server_id, доверенные устройства
- `POST /api/server-name` — change display name from Dashboard / Смена имени сервера из Dashboard
- `POST /api/unpair` — revoke trusted device / Отзыв доверенного устройства
- `GET /api/trusted` — list paired devices / Список связанных устройств
- `GET /api/scan-beacons` — server-side UDP listener for Dashboard auto-discovery / Серверный UDP listener для автообнаружения
- ThreadingHTTPServer replaces HTTPServer — beacon scanning no longer blocks requests / ThreadingHTTPServer — сканирование beacon больше не блокирует запросы
- Dashboard Connect tab: auto-scan LAN, discovered server list, click-to-connect with pairing / Вкладка Connect: автосканирование LAN, список серверов, подключение с pairing
- Dashboard Settings tab: trusted devices list with Unpair, server name editor / Вкладка Settings: список доверенных устройств, редактор имени сервера
- Deduplication in `listen_for_beacons()` — same IP:port appears once / Дедупликация в listen_for_beacons

### Session-Project Auto-Link / Связывание сессий с файлами проекта
- After session Pull/Push, Dashboard detects linked project directory and offers file sync / После Pull/Push сессии Dashboard определяет привязанный проект и предлагает синхронизацию файлов
- Uses session `cwd` (real working dir) instead of `project` field / Использует `cwd` (реальную рабочую директорию) вместо поля `project`
- Git branch and SHA from DB shown in Sessions table / Ветка и SHA из БД отображаются в таблице сессий
- Worktree detection: sessions in `~/.codex/worktrees/` flagged with yellow badge / Обнаружение worktrees: сессии в worktrees помечены жёлтым бейджем
- Warning when syncing worktree files (Codex internals) / Предупреждение при синхронизации файлов worktree
- Bulk: aggregates unique directories across multiple selected sessions / Массовая операция: объединяет уникальные директории

### Background Auto-Sync / Фоновая авторсинхронизация
- Dashboard Settings tab: auto-sync polling (30s / 60s / 2 min / 5 min) / Вкладка Settings: авторсинхронизация с интервалом
- Auto-pull modes: notify only / sessions / providers / all / Режимы: только уведомление / сессии / провайдеры / все
- `/api/manifest` now returns `hash` + `timestamp` fields for change detection / Манифест возвращает хэш и метку времени
- Status indicators: last sync time, polling status / Индикаторы: время последней синхронизации, статус опроса
- Sync mutex prevents overlapping auto-pulls / Мьютекс предотвращает пересекающиеся авторсинхронизации

### System Tray Widget / Виджет в системном трее
- New file: `sync_tray.py` — optional system tray app / Новый файл: опциональное приложение в трее
- Colored circle status indicator: Red (stopped), Yellow (idle), Green (syncing) / Цветной индикатор: красный/жёлтый/зелёный
- Menu: Start/Stop Server, Open Dashboard, Autorun on startup, Exit / Меню: старт/стоп, Dashboard, автозапуск, выход
- Dynamic icon via Pillow (no .ico files) / Динамическая иконка через Pillow
- Autorun: Windows registry / macOS LaunchAgent / Автозапуск: реестр Windows / LaunchAgent macOS
- Single instance via PID lockfile / Одна копия через PID lockfile
- Requires: `pip install pystray Pillow` (optional) / Требует: pystray + Pillow (опционально)

### Tests / Тесты
- 32 smoke tests (was 23) / 32 smoke-тестов (было 23)
- New: manifest hash, sessions cwd/git fields, sync_tray syntax, sync_tray import, trusted device storage, pairing endpoint, local-info, unpair / Новые: хэш манифеста, поля cwd/git, трей, pairing, local-info, unpair

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

## [1.1.0] — 2026-05-24

### P2P Sync / P2P Синхронизация
- Local P2P bidirectional sync between machines via HTTP API / Локальная P2P двунаправленная синхронизация между машинами
- Web Dashboard (embedded HTML, dark theme) — accessible from any browser on the network / Веб-панель (встроенный HTML, тёмная тема)
- PIN-based authentication (6-char hex) with rate limiting / PIN-авторизация (6-значный hex) с rate limiting
- CORS support for cross-origin browser requests / Поддержка CORS для кросс-доменных запросов
- Auto port selection (8080-8099) — tries next port if busy / Автоподбор порта — пробует следующий если занят
- UDP broadcast beacon for LAN auto-discovery / UDP broadcast beacon для автообнаружения в LAN
- Bidirectional: Push + Pull providers, sessions, files / Двунаправленная: Push + Pull провайдеров, сессий, файлов
- Provider import modes: with key / without key / skip / keep both / Режимы импорта: с ключом / без ключа / пропустить / оба
- Session sync: downloads JSONL + inserts into local DB / Синхронизация сессий: скачивает JSONL + вставляет в локальную БД
- File sync: SHA-256 hash diff + ZIP packaging / Синхронизация файлов: SHA-256 diff + ZIP упаковка
- Git dirty state check before file sync / Проверка незакоммиченных изменений Git перед синхронизацией
- ZIP size limit (500 MB) / Лимит размера ZIP (500 МБ)
- Auto-backup before every sync write operation / Автобекап перед каждой операцией записи
- Settings tab: language, auto-backup, conflict resolution / Вкладка настроек: язык, автобекап, разрешение конфликтов

### CLI / CLI
- `--sync-host` — start sync server + Dashboard / запуск сервера синхронизации + Dashboard
- `--sync-pull HOST[:PORT]` — connect and pull data / подключение и загрузка данных
- `--sync-push HOST[:PORT]` — connect and push data / подключение и отправка данных
- `--sync-pin PIN` — authentication PIN / PIN для авторизации
- `--sync-port PORT` — specify port (default: auto) / указать порт (по умолчанию: авто)

### GUI
- Sync panel: Start/Stop server, IP:PORT + PIN display / Панель синхронизации: запуск/остановка, IP:PORT + PIN
- "Open Dashboard" button — opens browser / Кнопка "Открыть Dashboard" — открывает браузер
- "Copy IP:PIN" button / Кнопка "Копировать IP:PIN"
- Auto-refresh GUI when data changes via Dashboard / Автообновление GUI при изменениях через Dashboard

### New File / Новый файл
- `codex_sync.py` — P2P sync engine (server, client, Dashboard, all 4 layers) / Движок P2P синхронизации

### Tests / Тесты
- 23 smoke tests (was 14) — added sync tests / 23 smoke-тестов (было 14) — добавлены тесты синхронизации
- Tests: PIN format, hashes, file diff, path traversal, server ping, CORS, auth / Тесты: формат PIN, хэши, file diff, path traversal, ping, CORS, авторизация

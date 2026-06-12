# Codex Chat Transformer

[English](README.md) | [中文](README.zh.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org/)
[![Zero external deps](https://img.shields.io/badge/deps-zero-green.svg)]()

Инструмент для управления сессиями [Codex Desktop](https://github.com/openai/codex) — конвертация чатов между провайдерами, закрепление в сайдбаре и полное резервное копирование.

---

## Быстрый старт

Установка:
```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.sh | bash
```
```powershell
# PowerShell
irm https://raw.githubusercontent.com/lightcomc/codex-chat-transformer/main/install.ps1 | iex
```

Основные команды:
```bash
# Запуск GUI
codex_manager.cmd
```
```bash
# Сохранить текущего провайдера
python codex_chat_transformer.py --save-provider MyProvider
```
```bash
# Переключить провайдер + конвертировать чаты
python codex_chat_transformer.py --use-provider MyProvider
```
```bash
# Полный бекап
python codex_chat_transformer.py --backup
```

---

## Проблема

Codex Desktop создаёт отдельные «виртуальные пространства» для каждого способа подключения. При переключении между подпиской и API-ключом чаты «пропадают» — они на месте, но сайдбар фильтрует по текущему `model_provider`. Если попытаться продолжить чужой чат — получаешь 401, потому что он стучится не на тот endpoint.

---

## Возможности

### Конвертация чатов

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

### Управление провайдерами

Все провайдеры хранятся в одном `config.toml` — каждый как отдельная секция `[model_providers.*]`. Переключение меняет только `model_provider`, `model` и `model_reasoning_effort`, не трогая остальные настройки. Профили сохраняются в `providers.json` с автоматической миграцией старого формата.

> **Примечание:** Провайдер `openai` защищён — URL и API-ключ доступны только для чтения. Для смены учётных данных OpenAI авторизуйтесь напрямую через Codex Desktop.

Сохранить текущего провайдера как профиль:
```bash
python codex_chat_transformer.py --save-provider MyProvider
```

Переключиться:
```bash
python codex_chat_transformer.py --use-provider MyProvider
```

Добавить из JSON-файла:
```bash
python codex_chat_transformer.py --add-provider provider.json
```
```bash
python codex_chat_transformer.py --add-provider provider.json --api-key sk-xxx
```

Редактировать:
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

Сменить модель (без переключения провайдера):
```bash
python codex_chat_transformer.py --set-model gpt-5.5
```

Удалить:
```bash
python codex_chat_transformer.py --remove-provider MyProvider
```

Список:
```bash
python codex_chat_transformer.py --providers
```

Автообнаружение:
```bash
python codex_chat_transformer.py --detect-provider
```

### Синхронизация авторизации

Автоматическая синхронизация OpenAI auth при запуске. Когда активный провайдер использует `chatgpt` auth mode, инструмент извлекает email из текущего JWT-токена и сравнивает с сохранёнными профилями:

- **Устаревший auth**: тот же email, но `last_refresh` отличается → предложение обновить
- **Новый email**: обнаружена другая почта → обновить существующий профиль или сохранить как новый (автогенерация имени, например `openai_username`)
- **Несохранённый провайдер**: активный провайдер отсутствует в профилях → предложение сохранить

Каждый профиль теперь содержит `bound_at` (дата первого сохранения) и `auth_email`. Поддерживается несколько OpenAI-профилей под разными почтами.

Работает и в CLI (интерактивный запрос при запуске), и в GUI (диалог при открытии). Никаких флагов — запускается автоматически.

### Модели Factory Droid

Инструмент умеет управлять custom models/endpoints Factory Droid без перезаписи комментированного `%USERPROFILE%\.factory\settings.json` и без изменения Factory auth-файлов.

```bash
python codex_chat_transformer.py --droid-models
python codex_chat_transformer.py --droid-doctor
python codex_chat_transformer.py --droid-add-neurogate
python codex_chat_transformer.py --droid-use custom:NeuroGate-GPT-5.5-1 --set-reasoning medium
python codex_chat_transformer.py --droid-import-provider OpenRouter --droid-api-key-env OPENROUTER_API_KEY
python codex_chat_transformer.py --droid-remove-model custom:OpenRouter
```

Все записи Droid идут в `%USERPROFILE%\.factory\settings.local.json`. Существующие `settings.json`, legacy `config.json` и Factory auth-файлы не трогаются. По умолчанию API-ключи пишутся как ссылки на переменные окружения, например `${NEUROGATE_API_KEY}`; прямую запись ключа нужно явно включить через `--droid-with-key --api-key ...`.

### Chat Bridge: сессии Codex <-> Droid [Экспериментальный]

Первый срез переноса чатов создаёт новые сессии в целевой системе и записывает пары в `chat_bridge_mappings.json` для будущей синхронизации. Auth-файлы и API-ключи не копируются.
Если у Codex-сессии есть проектный `cwd`, Codex -> Droid пишет JSONL/settings в соответствующую проектную папку внутри `%USERPROFILE%\.factory\sessions\`, записывает `cwd` в индексы Droid, а `--droid-sessions` сканирует такие вложенные проектные папки.

```bash
python codex_chat_transformer.py --droid-sessions
python codex_chat_transformer.py --codex-sessions --project C:\Research\my_project
python codex_chat_transformer.py --droid-to-codex --chat-session DROID_SESSION_ID --chat-pin-old
python codex_chat_transformer.py --codex-to-droid --chat-session CODEX_SESSION_ID
python codex_chat_transformer.py --codex-to-droid --chat-session CODEX_SESSION_ID --chat-skip-system
python codex_chat_transformer.py --droid-to-codex --chat-session DROID_SESSION_ID --chat-fresh-timestamps
python codex_chat_transformer.py --droid-to-codex --chat-session DROID_SESSION_ID --chat-backup
python codex_chat_transformer.py --chat-mapping-plan --project C:\Research\my_project
python codex_chat_transformer.py --codex-to-droid --chat-session CODEX_SESSION_ID --chat-compaction-mode inline
```

По умолчанию сохраняются даты создания и последнего сообщения, включая Droid index/file mtime при импорте Codex -> Droid. `--chat-fresh-timestamps` переносит чат как свежий. Droid -> Codex создаёт rollout JSONL и строку `threads` как проверенную пару; полный backup `.codex` создаётся только при явном `--chat-backup`.
`--chat-compaction-mode archived` теперь режим по умолчанию: переносится вся видимая история, включая tool calls и tool results, а compaction/source events остаются только архивными bridge-метаданными. `raw` - legacy alias для `archived`. `inline` и `native` стоит включать только когда нужно явно создать native compaction/continuation state в целевом чате. Codex `reasoning` и Droid `thinking` теперь сохраняются, включая OpenAI encrypted reasoning payloads, которые нужны для native continuation.
`--chat-mapping-plan` работает только на чтение: классифицирует пары как stale, metadata drift или requiring fresh re-export, печатает рекомендованные команды, но не меняет mapping и не создает сессии.

#### Режим идентификации Codex Desktop

При конвертации Droid -> Codex мост создаёт rollout, структурно идентичные реальным сессиям Codex Desktop (`codex_desktop_compat`). Этот режим включён по умолчанию для всех трансферов Droid -> Codex.

**Что конвертируется:**
- `session_meta` с корректными `originator`, `cli_version`, `source`, `model_provider`, `base_instructions`, `dynamic_tools`
- Полный жизненный цикл событий: `task_started` -> `user_message` / `agent_message` / `token_count` -> `task_complete`
- `turn_context` перед каждым ответом ассистента
- Developer-сообщение с контекстом окружения (CWD, дата, часовой пояс)
- Все вызовы инструментов обёрнуты в `exec_command` с JSON-аргументами
- Вывод инструментов обёрнут в `Chunk ID` / `Wall time` / `Process exited with code 0`
- Reasoning как `encrypted_content`-only с `summary: []`, `content: null`
- Сабагенты (Droid "Task") конвертируются в пространство имён `multi_agent_v1`: `tool_search_call` -> `spawn_agent` -> `wait_agent` -> `close_agent`

**Привязка провайдера/модели:**
- Droid -> Codex: использует активный провайдер/модель из `config.toml` как `model_provider` в rollout `session_meta` и строке БД `threads`
- Codex -> Droid: использует активный провайдер/модель из `config.toml` для `providerLock` и выбора модели Droid-сессии

**Известные ограничения:**
- `base_instructions` и `dynamic_tools` берутся из `codex_desktop_meta_template.json` (при наличии) или из минимального fallback-промпта
- `encrypted_content` в reasoning — синтетический (base64-заполнитель), не настоящий зашифрованный reasoning
- Результаты сабагентов приблизительны — prompt Droid Task становится `spawn_agent` message, результат Task становится `wait_agent` output

### Закрепление чатов

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

### Полный бекап

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

### Codex Pack / Search / History

Portable subset ZIP for providers and sessions:

```bash
python codex_chat_transformer.py --export-pack my.codex-pack.zip --scope all
```
```bash
python codex_chat_transformer.py --export-pack providers.zip --scope providers --providers OpenRouter --without-keys
```
```bash
python codex_chat_transformer.py --import-pack my.codex-pack.zip --scope sessions --sessions SESSION_ID
```

Search and operation history:

```bash
python codex_chat_transformer.py --search "database migration" --project C:\Research\my_project
```
```bash
python codex_chat_transformer.py --history --history-limit 20
```

Pack import is upsert-only and does not switch the active provider. History is stored in `.codex/operation_history.jsonl` with API keys, PINs, and auth payloads redacted.

### Диагностика

Read-only проверка состояния: база, конфиг, авторизация, провайдеры, закреплённые чаты.

```bash
python codex_chat_transformer.py --doctor
```

### P2P Синхронизация

Локальная двунаправленная синхронизация между машинами через HTTP API + веб-панель. Обе машины запускают один и тот же сервер. Браузер выступает оркестратором — Push и Pull провайдеров, сессий и файлов проекта.

```bash
# Запуск сервера синхронизации (автоподбор свободного порта)
python codex_chat_transformer.py --sync-host

# Запуск на конкретном порту
python codex_chat_transformer.py --sync-host --sync-port 8080

# Подключение к удалённому серверу и загрузка данных
python codex_chat_transformer.py --sync-pull 192.168.1.60:8080 --sync-pin A7B3C2
```

Возможности:
- Веб-панель (тёмная тема, 5 вкладок: Подключение, Провайдеры, Сессии, Файлы, Настройки)
- PIN-авторизация с rate limiting
- **Доверенные устройства (pairing)**: введите PIN один раз → устройство запоминается → авто-подключение без PIN
- **Автообнаружение в LAN**: UDP beacon с именем сервера, подключение одним кликом из Dashboard
- Двунаправленная: Push + Pull для каждого элемента
- Режимы импорта провайдеров: с ключом / без ключа / пропустить / оба
- Синхронизация сессий: скачивание JSONL + вставка в БД
- Синхронизация файлов: SHA-256 diff + ZIP упаковка
- Авто-связывание: Pull/Push сессии определяет привязанный проект и предлагает синхронизацию файлов
- Фоновая авторсинхронизация (30с–5 мин, настраиваемый интервал)
- Автоподбор порта (пробует 8080-8099)
- UDP broadcast для автообнаружения в LAN
- Проверка незакоммиченных изменений Git перед синхронизацией
- **Воссоздание worktree**: нативный `git worktree add` на принимающей машине сохраняет изоляцию
- **Маппинг путей проектов**: запоминает связки локальных и удалённых директорий
- **Предупреждение Git mismatch**: алерт при несовпадении веток/коммитов между машинами
- **Переименование провайдера**: `--edit-provider NAME --set-name NEW` обновляет TOML + providers.json
- Автобекап перед каждой операцией записи

---

## GUI

GUI — тонкая обёртка над CLI (`import codex_chat_transformer as ct`), дублирования кода нет.

### Возможности GUI

- Переключение провайдеров одним кликом
- Конвертация чатов в фоновом потоке — GUI не зависает
- Полоса прогресса конвертации с логированием в CMD-окно
- Секция P2P-синхронизации: запуск сервера, Dashboard и копирование IP:PIN
- Панель Chat Bridge для переноса сессий Droid -> Codex и Codex -> Droid
- Редактирование провайдера: кнопка или правый клик
- Кнопки «Вставить из буфера» во всех диалогах ввода
- Модель и reasoning меняются прямо в info-панели
- Выпадающий список reasoning: low / medium / high / xhigh / default
- Автообнаружение JSON-конфигов рядом с приложением
- Запрос API-ключа при импорте если отсутствует
- Провайдер `openai` защищён от редактирования
- Auth sync при запуске: автообновление устаревших токенов, создание профиля для новой почты
- Автосохранение auth текущего провайдера в `providers.json` при переключении
- Регистронезависимое сравнение email при auth sync
- Автоматическая миграция старых профилей
- RU / EN интерфейс

### Запуск

| Платформа | Команда |
|---|---|
| Windows | `codex_manager.cmd` (двойной клик) |
| PowerShell | `.\codex_manager.ps1` |
| Linux / macOS | `./codex_manager.sh` |

### Добавление провайдера

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

## Требования

- Python 3.7+
- Tkinter (входит в стандартную поставку Python)
- Без внешних зависимостей

### Опционально: Системный трей

Виджет в системном трее с цветным индикатором статуса:
- Красный — сервер остановлен
- Жёлтый — сервер запущен, ожидает подключений
- Зелёный — идёт синхронизация

```bash
pip install pystray Pillow
python sync_tray.py
```

Возможности: запуск/остановка сервера, открытие Dashboard, автозапуск (Windows/macOS), защита от повторного запуска.
Трей полностью опционален — основной инструмент и Dashboard работают без него.

---

## Безопасность

API-ключи хранятся локально с base64 обфусцированием (и в CLI, и в GUI). Это **не** шифрование. Не передавайте `providers.json` и `auth.json` третьим лицам. Инструмент не отправляет ключи никуда, кроме настроенного API endpoint.

---

## FAQ

**В: Чаты пропали после смены способа подключения.**

О: Конвертируйте в текущий провайдер: `--list` чтобы узнать имя, затем `--from openai --to YourProvider`. Codex должен быть закрыт.

**В: Чат видно, но при отправке — 401.**

О: Провайдер в JSONL не обновился. Перезапустите конвертацию — обновляются и БД, и JSONL.

**В: Как конвертировать чаты только одного проекта?**

О: `--from openai --to MyProvider --project my_project`. Фильтрует по полю `project` в базе.

**В: Как маппить модели при конвертации?**

О: `--from openai --to MyProvider --from-model gpt-4 --to-model gpt-5.5`. Заменяет имя модели в JSONL.

**В: Можно ли откатить?**

О: Три способа:
1. `--restore backup_YYYYMMDD_HHMMSS` — откатить БД
2. `--restore-zip file.zip` — полное восстановление
3. Обратная конвертация: `--from YourProvider --to openai`

**В: Нужно ли закрывать Codex?**

О: **Да.** Codex держит БД открытой и может перезаписать изменения.

**В: Что делает `--doctor`?**

О: Read-only диагностика: проверяет базу, конфиг, авторизацию, провайдеры, pinned-чаты. Ничего не меняет.

**В: Как сменить модель без переключения провайдера?**

О: В GUI — кликните на модель в info-панели и введите новую. В CLI — `--set-model gpt-5.5`.

**В: Как сменить reasoning effort?**

О: В GUI — выпадающий список в info-панели. В CLI — `--edit-provider NAME --set-reasoning high`.

**В: Как синхронизировать провайдеров между двумя компьютерами?**

О: Запустите `--sync-host` на обоих. Откройте Dashboard в браузере, введите удалённый IP + PIN, выберите провайдеров и нажмите Pull или Push.

**В: Можно ли синхронизировать без Dashboard?**

О: Да: `--sync-pull IP:PORT --pin XXXXXX` откроет интерактивное CLI-меню.

---

## Где что хранится

| Файл | Содержимое |
|---|---|
| `state_5.sqlite` → `threads` | Метаданные чатов: провайдер, заголовок, проект, токены |
| `sessions/YYYY/MM/DD/rollout-*.jsonl` | Полная история чата |
| `.codex-global-state.json` → `pinned-thread-ids` | Закреплённые чаты |
| `config.toml` | Все провайдеры `[model_providers.*]` + настройки |
| `auth.json` | Текущая авторизация (API-ключ или OAuth) |
| `providers.json` | Профили провайдеров (`provider_section` + `model` + авторизация + `auth_email` + `bound_at`, b64 обфускация) |

---

## Файлы

```
codex_chat_transformer.py    — CLI: конвертация, провайдеры, закрепление, бекап, doctor, редактирование, синхронизация
codex_manager_gui.py         — GUI: переключение, редактирование, смена модели, синхронизация (обёртка над CLI)
codex_sync.py                — Движок P2P синхронизации: сервер, клиент, Dashboard, файлы, авторсинхронизация
sync_tray.py                 — Виджет в системном трее (опционально, требует pystray + Pillow)
test_smoke.py                — Smoke-тесты (99 тестов)
codex_manager.cmd / .ps1     — Windows запускаторы
codex_manager.sh             — Unix запускатор
providers_template.json      — Шаблон провайдера
providers_example.json       — Пример провайдера
CHANGELOG.md                 — История изменений
install.sh / install.ps1     — Установка одной строкой
```

## Лицензия

[MIT](LICENSE)

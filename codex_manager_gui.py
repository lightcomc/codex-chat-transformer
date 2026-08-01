#!/usr/bin/env python3
"""
Codex Chat Transformer — GUI for managing Codex Desktop providers.
Pure Python + Tkinter, no external dependencies. RU/EN interface.
"""

import datetime
import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

import chat_bridge
import codex_chat_transformer as ct
import droid_provider_adapter as droid

# ── Paths ──────────────────────────────────────────────────────────────────

CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
STATE_DB = CODEX_DIR / "state_5.sqlite"
GLOBAL_STATE = CODEX_DIR / ".codex-global-state.json"
SCRIPT_DIR = Path(__file__).resolve().parent
PROVIDERS_FILE = CODEX_DIR / "providers.json"
SESSIONS_DIR = CODEX_DIR / "sessions"

# ── Theme ──────────────────────────────────────────────────────────────────

BG = "#1e1e2e"
BG2 = "#2a2a3d"
FG = "#cdd6f4"
FG2 = "#a6adc8"
ACCENT = "#89b4fa"
GREEN = "#a6e3a1"
RED = "#f38ba8"
YELLOW = "#f9e2af"

# ── Localization ───────────────────────────────────────────────────────────

LANG = "ru"

T = {
    "title": {"ru": "Codex Chat Transformer", "en": "Codex Chat Transformer"},
    "subtitle": {"ru": "Управление провайдерами, чатами и бекапами", "en": "Manage providers, chats and backups"},
    "total_chats": {"ru": "Всего чатов", "en": "Total chats"},
    "active_word": {"ru": "активных", "en": "active"},
    "archived_word": {"ru": "архивных", "en": "archived"},
    "active_provider": {"ru": "Активный провайдер", "en": "Active provider"},
    "model": {"ru": "Модель", "en": "Model"},
    "reasoning": {"ru": "Размышления", "en": "Reasoning"},
    "subagents": {"ru": "Сабагенты", "en": "Subagents"},
    "saved_providers": {"ru": "Сохранённые провайдеры:", "en": "Saved providers:"},
    "use_provider": {"ru": "Использовать", "en": "Use Provider"},
    "save_current": {"ru": "Сохранить текущий", "en": "Save Current"},
    "remove": {"ru": "Удалить", "en": "Remove"},
    "auto_backup": {"ru": "Автобекап БД перед конвертацией", "en": "Auto-backup DB before conversion"},
    "backup_created": {"ru": "Автобекап: {}", "en": "Auto-backup: {}"},
    "convert_chats": {"ru": "Конвертировать чаты при переключении", "en": "Convert chats when switching"},
    "pin_top": {"ru": "Закрепить 10 свежих чатов", "en": "Pin top 10 recent chats"},
    "add_json": {"ru": "Добавить из JSON...", "en": "Add from JSON..."},
    "create_new": {"ru": "Создать провайдер...", "en": "Create provider..."},
    "full_backup": {"ru": "Полный ZIP бекап", "en": "Full ZIP Backup"},
    "restore_zip": {"ru": "Восстановить из ZIP...", "en": "Restore from ZIP..."},
    "fix_dates": {"ru": "Восстановить даты", "en": "Fix file dates"},
    "ready": {"ru": "Готов", "en": "Ready"},
    "switch_confirm": {"ru": "Переключиться с '{}' на '{}'?\n\nИзменится config, auth и все чаты будут сконвертированы.", "en": "Switch from '{}' to '{}'?\n\nConfig, auth will change and all chats will be converted."},
    "already_using": {"ru": "Уже используется '{}'.", "en": "Already using '{}'."},
    "switch_done": {"ru": "Переключено на '{}'.", "en": "Switched to '{}'."},
    "switch_title": {"ru": "Переключить провайдер", "en": "Switch provider"},
    "save_title": {"ru": "Сохранить провайдер", "en": "Save Provider"},
    "save_prompt": {"ru": "Имя профиля:", "en": "Profile name:"},
    "save_done": {"ru": "Сохранён профиль '{}' ({}; {})", "en": "Saved profile '{}' ({}; {})"},
    "remove_confirm": {"ru": "Удалить провайдер '{}'?", "en": "Remove provider '{}'?"},
    "remove_done": {"ru": "Удалён '{}'", "en": "Removed '{}'"},
    "not_saved": {"ru": "Провайдер '{}' не сохранён. Нажмите «Сохранить текущий».", "en": "Provider '{}' not saved. Click 'Save Current'."},
    "account_unmatched": {"ru": "Текущий аккаунт не сопоставлен со saved-профилем. Нажмите «Сохранить текущий».", "en": "Current account is not matched to a saved profile. Click 'Save Current'."},
    "no_selection": {"ru": "Выберите провайдер из списка.", "en": "Select a provider from the list."},
    "not_found": {"ru": "Профиль '{}' не найден.", "en": "Profile '{}' not found."},
    "backup_saved": {"ru": "Бекап сохранён", "en": "Backup saved"},
    "restore_confirm": {"ru": "Текущие файлы будут перезаписаны. Продолжить?", "en": "Current files will be overwritten. Continue?"},
    "restore_title": {"ru": "Восстановить", "en": "Restore"},
    "restore_done": {"ru": "Восстановлено. Перезапустите Codex.", "en": "Restored. Restart Codex to apply."},
    "json_detect": {"ru": "Обнаружен провайдер: '{}'\n\nДобавить в сохранённые?", "en": "Detected provider: '{}'\n\nAdd to saved profiles?"},
    "json_detect_title": {"ru": "Добавить провайдер", "en": "Add Provider"},
    "json_added": {"ru": "Добавлен провайдер '{}' из JSON", "en": "Added provider '{}' from JSON"},
    "json_error": {"ru": "Не удалось прочитать JSON", "en": "Failed to read JSON"},
    "create_title": {"ru": "Создать провайдер", "en": "Create Provider"},
    "f_name": {"ru": "Имя провайдера:", "en": "Provider name:"},
    "f_model": {"ru": "Модель:", "en": "Model:"},
    "f_url": {"ru": "API Base URL:", "en": "API Base URL:"},
    "f_key": {"ru": "API ключ:", "en": "API Key:"},
    "f_wire": {"ru": "Wire API:", "en": "Wire API:"},
    "f_create": {"ru": "Создать", "en": "Create"},
    "f_enter_name": {"ru": "Введите имя провайдера.", "en": "Enter provider name."},
    "auto_detected": {"ru": "Обнаружен новый провайдер: '{}'. Добавить?", "en": "New provider detected: '{}'. Add it?"},
    "ask_key_title": {"ru": "Введите API ключ", "en": "Enter API Key"},
    "ask_key_msg": {"ru": "Провайдер «{}» не содержит API ключ.\nВведите ключ для подключения:", "en": "Provider '{}' has no API key.\nEnter key to connect:"},
    "ask_key_skip": {"ru": "Пропустить (без ключа)", "en": "Skip (no key)"},
    "paste_clip": {"ru": "Вставить", "en": "Paste"},
    "auto_detect_title": {"ru": "Автообнаружение", "en": "Auto-detection"},
    "converted": {"ru": "Сконвертировано {} чатов: {} -> {}", "en": "Converted {} chats: {} -> {}"},
    "switched_noconv": {"ru": "Переключено на {} (без конвертации)", "en": "Switched to {} (no conversion)"},
    "edit_provider": {"ru": "Редактировать...", "en": "Edit..."},
    "edit_title": {"ru": "Редактировать провайдер", "en": "Edit Provider"},
    "f_reasoning": {"ru": "Reasoning:", "en": "Reasoning:"},
    "f_reasoning_hint": {"ru": "low / medium / high / xhigh (пусто = по умолчанию)", "en": "low / medium / high / xhigh (empty = default)"},
    "f_save": {"ru": "Сохранить", "en": "Save"},
    "edit_done": {"ru": "Провайдер '{}' обновлён.", "en": "Provider '{}' updated."},
    "change_model": {"ru": "Сменить модель", "en": "Change Model"},
    "model_title": {"ru": "Сменить модель", "en": "Change Model"},
    "model_prompt": {"ru": "Новая модель:", "en": "New model:"},
    "model_done": {"ru": "Модель изменена на: {}", "en": "Model changed to: {}"},
    "converting": {"ru": "Конвертация чатов {} -> {}...", "en": "Converting chats {} -> {}..."},
    "converting_progress": {"ru": "Конвертация: обработано {} из {} чатов...", "en": "Converting: processed {} of {} chats..."},
    "ctx_edit": {"ru": "Редактировать", "en": "Edit"},
    "ctx_switch": {"ru": "Переключиться", "en": "Switch"},
    "ctx_remove": {"ru": "Удалить", "en": "Remove"},
    "openai_note": {"ru": "* авторизация через Codex", "en": "* auth via Codex"},
    "ok": {"ru": "OK", "en": "OK"},
    "cancel": {"ru": "Отмена", "en": "Cancel"},
    "yes": {"ru": "Да", "en": "Yes"},
    "no": {"ru": "Нет", "en": "No"},
    "warning": {"ru": "Предупреждение", "en": "Warning"},
    "error": {"ru": "Ошибка", "en": "Error"},
    "info": {"ru": "Информация", "en": "Info"},
    "codex_running": {"ru": "Codex Desktop запущен. Перезапустите Codex после переключения.", "en": "Codex Desktop is running. Restart Codex after switching."},
    "reasoning_set": {"ru": "Размышления: {}", "en": "Reasoning: {}"},
    "files_fixed": {"ru": "Исправлено: {} файлов", "en": "Fixed: {} files"},
    "pinned_count": {"ru": "Закреплено: {}", "en": "Pinned: {}"},
    "default_val": {"ru": "по умолчанию", "en": "default"},
    "sync_start": {"ru": "Запустить сервер", "en": "Start Server"},
    "sync_stop": {"ru": "Остановить", "en": "Stop"},
    "sync_running": {"ru": "Сервер: {ip}:{port} PIN: {pin}", "en": "Server: {ip}:{port} PIN: {pin}"},
    "sync_stopped": {"ru": "Сервер остановлен", "en": "Server stopped"},
    "sync_title": {"ru": "Синхронизатор", "en": "Sync"},
    "sync_open": {"ru": "Открыть Dashboard", "en": "Open Dashboard"},
    "sync_copy": {"ru": "Копировать IP:PIN", "en": "Copy IP:PIN"},
    "chat_bridge": {"ru": "Codex ↔ Droid", "en": "Codex ↔ Droid"},
    "chat_refresh": {"ru": "Обновить списки", "en": "Refresh lists"},
    "chat_droid_session": {"ru": "Droid-сессия", "en": "Droid session"},
    "chat_codex_session": {"ru": "Codex-сессия", "en": "Codex session"},
    "droid_to_codex": {"ru": "Droid → Codex", "en": "Droid → Codex"},
    "codex_to_droid": {"ru": "Codex → Droid", "en": "Codex → Droid"},
    "chat_fresh_timestamps": {"ru": "Импортировать как свежий чат", "en": "Import as fresh chat"},
    "chat_pin_old": {"ru": "Pin старые Droid-чаты", "en": "Pin old Droid chats"},
    "chat_skip_system": {"ru": "Skip Codex system context", "en": "Skip Codex system context"},
    "chat_compaction_mode": {"ru": "Compaction", "en": "Compaction"},
    "chat_mirror_plan": {"ru": "Mirror plan", "en": "Mirror plan"},
    "chat_mirror_running": {"ru": "Building mirror plan...", "en": "Building mirror plan..."},
    "chat_mirror_ready": {"ru": "Mirror plan: {pairs} pairs | {statuses}", "en": "Mirror plan: {pairs} pairs | {statuses}"},
    "chat_lists_ready": {"ru": "Droid: {droid}, Codex: {codex}", "en": "Droid: {droid}, Codex: {codex}"},
    "chat_no_droid": {"ru": "Выберите Droid-сессию.", "en": "Select a Droid session."},
    "chat_no_codex": {"ru": "Выберите Codex-сессию.", "en": "Select a Codex session."},
    "chat_confirm_droid_to_codex": {"ru": "Импортировать Droid-сессию в Codex?\n\nБудет создана новая Codex-сессия.", "en": "Import the Droid session into Codex?\n\nA new Codex session will be created."},
    "chat_confirm_codex_to_droid": {"ru": "Экспортировать Codex-сессию в Droid?\n\nБудет создана новая Droid-сессия.", "en": "Export the Codex session into Droid?\n\nA new Droid session will be created."},
    "chat_transfer_running": {"ru": "Перенос чата...", "en": "Transferring chat..."},
    "chat_imported_codex": {"ru": "Droid → Codex: {session}", "en": "Droid → Codex: {session}"},
    "chat_imported_droid": {"ru": "Codex → Droid: {session}", "en": "Codex → Droid: {session}"},
    "chat_refreshing": {"ru": "Обновление списков...", "en": "Refreshing lists..."},
    "consent_title": {"ru": "Codex Chat Transformer — Условия использования", "en": "Codex Chat Transformer — Terms of Use"},
    "consent_accept": {"ru": "Принимаю условия", "en": "I accept the terms"},
    "consent_decline": {"ru": "Отклонить и выйти", "en": "Decline and exit"},
    "consent_text": {
        "ru": (
            "Данное программное обеспечение предоставляется «КАК ЕСТЬ»,\n"
            "без каких-либо гарантий — явных или подразумеваемых,\n"
            "включая пригодность для конкретной цели.\n"
            "\n"
            "ВНИМАНИЕ: Данный инструмент работает с API-ключами\n"
            "и токенами авторизации. Данные хранятся локально\n"
            "с базовым обфусцированием (base64), что НЕ является\n"
            "надёжным шифрованием. Не передавайте файл providers.json\n"
            "третьим лицам.\n"
            "\n"
            "Автор не несёт ответственности за утечку учётных данных,\n"
            "потерю данных или любой другой ущерб.\n"
            "\n"
            "Поставьте галочку и нажмите «Принимаю условия»\n"
            "для продолжения."
        ),
        "en": (
            "This software is provided \"AS IS\", without warranty\n"
            "of any kind, express or implied, including fitness for\n"
            "a particular purpose.\n"
            "\n"
            "WARNING: This tool handles API keys and auth tokens.\n"
            "Data is stored locally with basic obfuscation (base64),\n"
            "which is NOT secure encryption. Do not share the\n"
            "providers.json file with third parties.\n"
            "\n"
            "The author is not liable for credential leaks,\n"
            "data loss, or any other damages.\n"
            "\n"
            "Check the box and click \"I accept the terms\"\n"
            "to continue."
        ),
    },
    "auth_sync_title": {"ru": "Синхронизация OpenAI Auth", "en": "OpenAI Auth Sync"},
    "auth_sync_stale": {
        "ru": "Активен аккаунт: {cur_email}\nДата авторизации обновилась: {cur_date}\nСохранённая в профиле '{name}' устарела: {std_date}\n\nОбновить авторизацию в профиле '{name}'?",
        "en": "Active account: {cur_email}\nAuth date updated: {cur_date}\nStored in profile '{name}' is stale: {std_date}\n\nUpdate auth in profile '{name}'?",
    },
    "auth_sync_new_email": {
        "ru": "Обнаружена новая почта OpenAI!\n\nТекущий: {cur_email} (refreshed: {cur_date})\nСохранённый 'openai': {std_email} (refreshed: {std_date})\n\nЧто сделать?",
        "en": "New OpenAI email detected!\n\nCurrent: {cur_email} (refreshed: {cur_date})\nStored 'openai': {std_email} (refreshed: {std_date})\n\nWhat to do?",
    },
    "auth_update_existing": {"ru": "Обновить существующий '{}'", "en": "Update existing '{}'"},
    "auth_save_new": {"ru": "Сохранить как '{}'", "en": "Save as '{}'"},
    "auth_skip": {"ru": "Пропустить", "en": "Skip"},
    "auth_updated": {"ru": "Авторизация '{}' обновлена.", "en": "Auth for '{}' updated."},
    "auth_created": {"ru": "Создан профиль '{}'.", "en": "Created profile '{}'."},
    "not_saved_prompt": {
        "ru": "Активный провайдер '{}' не сохранён в базе.\n\nДобавить?",
        "en": "Active provider '{}' is not saved.\n\nAdd it?",
    },
    "not_saved_title": {"ru": "Сохранить провайдер", "en": "Save Provider"},
}

def t(key, *args, **kwargs):
    s = T.get(key, {}).get(LANG, key)
    if kwargs:
        return s.format(**kwargs)
    return s.format(*args) if args else s


def _unique_chat_display(display, unique_hint, taken):
    """Keep combobox display labels unique even after truncation."""
    display = str(display or "-")
    if display not in taken:
        return display
    hint = " ".join(str(unique_hint or "").split())[:24] or str(len(taken) + 1)
    candidate = f"{display} [{hint}]"
    counter = 2
    while candidate in taken:
        candidate = f"{display} [{hint} #{counter}]"
        counter += 1
    return candidate


# ── Data helpers (delegate to CLI module) ────────────────────────────────────

def _db_conn():
    return ct.get_db_conn(exit_on_error=False)


def _get_chat_stats():
    stats, active, archived = ct.get_thread_stats()
    return stats, {0: active, 1: archived}


def _get_config_info():
    """Read model, reasoning effort, subagent config from config.toml."""
    info = {"provider": "?", "model": "?", "reasoning": "?", "subagent_model": None}
    cfg = CODEX_DIR / "config.toml"
    if not cfg.exists():
        return info
    with open(str(cfg), "r", encoding="utf-8") as f:
        in_multi_agent = False
        for line in f:
            s = line.strip()
            if s.startswith("model_provider") and "=" in s:
                info["provider"] = s.split("=", 1)[1].strip().strip('"').strip("'")
            elif s.startswith("model") and "=" in s and not s.startswith("model_"):
                info["model"] = s.split("=", 1)[1].strip().strip('"').strip("'")
            elif s.startswith("model_reasoning_effort"):
                info["reasoning"] = s.split("=", 1)[1].strip().strip('"').strip("'")
            elif s == "[multi_agent]":
                in_multi_agent = True
            elif in_multi_agent and s.startswith("model"):
                info["subagent_model"] = s.split("=", 1)[1].strip().strip('"').strip("'")
                in_multi_agent = False
    return info


def _get_active_provider():
    return ct.get_active_provider()


def _get_active_profile_name():
    return ct.get_active_profile_name()


def _load_providers():
    data = ct.load_providers()
    for prof in data.get("profiles", {}).values():
        prof["auth.json"] = ct.decode_secret(prof.get("auth.json"))
    return data


def _save_providers(data):
    ct.save_providers(data)


def _read_file_safe(path):
    return ct.read_file_safe(str(path))


def _detect_provider_in_config(path):
    return ct.detect_provider_in_config(str(path))


def _detect_auth_mode(path):
    return ct.detect_auth_mode(str(path))


def _extract_provider_config(config_text):
    return ct.extract_provider_config(config_text)


def _merge_config(current_text, target_provider, target_section, target_model=None, target_reasoning=None):
    return ct.merge_config(current_text, target_provider, target_section, target_model, target_reasoning)


def _run_convert(from_p, to_p, auto_backup=True, progress_cb=None):
    if auto_backup:
        ct.create_backup(from_p)
        print(f"[backup] created before conversion {from_p} -> {to_p}")
    print(f"[convert] starting: {from_p} -> {to_p}")
    conn = _db_conn()
    if not conn:
        print("[convert] no database connection")
        return 0, 0
    cur = conn.cursor()
    cur.execute("SELECT id, rollout_path FROM threads WHERE model_provider = ?", (from_p,))
    threads = cur.fetchall()
    total = len(threads)
    if total == 0:
        conn.close()
        print(f"[convert] no chats found for '{from_p}'")
        return 0, 0
    print(f"[convert] found {total} chats, updating DB...")
    cur.execute("UPDATE threads SET model_provider = ? WHERE model_provider = ?", (to_p, from_p))
    conn.commit()
    conn.close()
    jsonl_updated = 0
    for i, thread in enumerate(threads):
        rollout = thread["rollout_path"]
        if rollout and ct.transform_jsonl_file(rollout, from_p, to_p):
            jsonl_updated += 1
        msg = t("converting_progress", i + 1, total)
        print(f"[convert] {i + 1}/{total} {'OK' if rollout else 'skip'}: {rollout}")
        if progress_cb:
            progress_cb(msg)
    print(f"[convert] done: {jsonl_updated}/{total} jsonl updated")
    return total, jsonl_updated


def _detect_provider_in_text(text):
    return ct.detect_provider_from_text(text)


def _detect_auth_mode_text(text):
    try:
        return json.loads(text).get("auth_mode", "unknown")
    except Exception:
        return "unknown"


def _scan_for_provider_jsons():
    """Scan script directory for JSON files that might contain provider config."""
    found = []
    for f in SCRIPT_DIR.iterdir():
        if not f.is_file() or not f.suffix == ".json":
            continue
        if f.name in ("providers.json", "providers_template.json"):
            continue
        # Skip pure auth files — they're not provider profiles
        if f.name in ("auth.json", "-auth.json", "--auth.json"):
            continue
        try:
            with open(str(f), "r", encoding="utf-8") as fh:
                raw = json.load(fh)

            provider_name = None
            is_provider = False

            # Full profile format: has config.toml + auth.json keys
            if isinstance(raw, dict) and "config.toml" in raw and "auth.json" in raw:
                is_provider = True
                provider_name = raw.get("model_provider", f.stem)
            # Simple provider format: has name + base_url
            elif isinstance(raw, dict) and "base_url" in raw and "name" in raw:
                is_provider = True
                provider_name = raw.get("name", f.stem)
            # Providers export format
            elif isinstance(raw, dict) and "profiles" in raw:
                for pname in raw.get("profiles", {}):
                    provider_name = pname
                    is_provider = True
                    break

            if is_provider:
                found.append({"path": f, "name": provider_name or f.stem, "data": raw})
        except Exception:
            pass
    return found


# ── GUI ────────────────────────────────────────────────────────────────────

class CodexManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Codex Chat Transformer")
        self.root.geometry("620x860")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self._setup_styles()
        self._build_ui()
        self._refresh()
        self._refresh_chat_bridge_sessions(silent=True)
        self.root.after(500, self._check_auth_sync)
        self._auto_detect()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI", 16, "bold"))
        style.configure("Model.TLabel", background=BG2, foreground=YELLOW, font=("Segoe UI", 10))
        style.configure("Stats.TLabel", background=BG2, foreground=FG2, font=("Segoe UI", 10))
        style.configure("Active.TLabel", background=BG2, foreground=GREEN, font=("Segoe UI", 11, "bold"))
        style.configure("TButton", background="#313244", foreground=FG, font=("Segoe UI", 10), padding=5)
        style.map("TButton", background=[("active", "#45475a")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#1e1e2e", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#74c7ec")])
        style.configure("Danger.TButton", background=RED, foreground="#1e1e2e")
        style.map("Danger.TButton", background=[("active", "#eba0ac")])
        style.configure("Small.TButton", background="#313244", foreground=FG2, font=("Segoe UI", 9))
        style.map("Small.TButton", background=[("active", "#45475a")])
        style.configure("TCheckbutton", background=BG, foreground=FG, font=("Segoe UI", 10))

    def _build_ui(self):
        # Top bar: title + lang switch
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=16, pady=(12, 0))

        ttk.Label(top, text=t("title"), style="Title.TLabel").pack(side="left")
        self.btn_lang = ttk.Button(top, text="EN", style="Small.TButton", command=self._toggle_lang, width=3)
        self.btn_lang.pack(side="right")

        # Subtitle
        self.lbl_subtitle = ttk.Label(self.root, text=t("subtitle"))
        self.lbl_subtitle.pack(pady=(2, 8))

        # Stats frame
        self.stats_frame = tk.Frame(self.root, bg=BG2, padx=12, pady=8)
        self.stats_frame.pack(fill="x", padx=16, pady=(0, 6))
        self.stats_label = ttk.Label(self.stats_frame, text="...", style="Stats.TLabel")
        self.stats_label.pack(anchor="w")

        # Active provider + model info
        self.info_frame = tk.Frame(self.root, bg=BG2, padx=12, pady=8)
        self.info_frame.pack(fill="x", padx=16, pady=(0, 6))

        info_top = tk.Frame(self.info_frame, bg=BG2)
        info_top.pack(fill="x")
        self.active_label = ttk.Label(info_top, text="", style="Active.TLabel")
        self.active_label.pack(side="left")

        # Model row: label + editable entry
        info_model = tk.Frame(self.info_frame, bg=BG2)
        info_model.pack(fill="x", pady=(4, 0))

        self.lbl_model = ttk.Label(info_model, text=f"{t('model')}:", style="Model.TLabel")
        self.lbl_model.pack(side="left")
        self.model_var = tk.StringVar()
        self.model_entry = tk.Entry(info_model, textvariable=self.model_var, bg=BG2, fg=ACCENT,
                                    insertbackground=FG, font=("Segoe UI", 10, "bold"),
                                    relief="flat", width=28)
        self._bind_paste(self.model_entry)
        self.model_entry.pack(side="left", padx=(4, 0))
        self.model_entry.bind("<Return>", self._on_model_change)
        self.model_entry.bind("<FocusOut>", self._on_model_change)

        # Reasoning row: label + combobox
        info_reas = tk.Frame(self.info_frame, bg=BG2)
        info_reas.pack(fill="x", pady=(2, 0))

        self.lbl_reasoning = ttk.Label(info_reas, text=f"{t('reasoning')}:", style="Model.TLabel")
        self.lbl_reasoning.pack(side="left")
        self.reasoning_var = tk.StringVar()
        self.reasoning_cb = ttk.Combobox(info_reas, textvariable=self.reasoning_var,
                                         values=["", "low", "medium", "high", "xhigh"],
                                         width=10, state="readonly", font=("Segoe UI", 10))
        self.reasoning_cb.pack(side="left", padx=(4, 0))
        self.reasoning_cb.bind("<<ComboboxSelected>>", self._on_reasoning_change)

        # Conversion progress strip
        self.conv_frame = tk.Frame(self.root, bg=ACCENT, padx=12, pady=6)
        self.conv_label = tk.Label(self.conv_frame, text="", bg=ACCENT, fg="#1e1e2e",
                                   font=("Segoe UI", 10, "bold"))
        self.conv_label.pack(anchor="w")
        # Hidden by default; shown during conversion
        # (pack is called dynamically in _use_provider)

        # Provider list
        self.list_frame = tk.Frame(self.root, bg=BG2, padx=12, pady=8)
        self.list_frame.pack(fill="x", padx=16, pady=(0, 6))

        self.lbl_providers = ttk.Label(self.list_frame, text=t("saved_providers"))
        self.lbl_providers.pack(anchor="w")
        self.provider_listbox = tk.Listbox(
            self.list_frame, height=5, bg=BG2, fg=FG, selectbackground=ACCENT,
            selectforeground="#1e1e2e", font=("Segoe UI", 11), relief="flat",
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BG2,
            activestyle="none"
        )
        self.provider_listbox.pack(fill="x", pady=(4, 0))
        self.provider_listbox.bind("<Button-3>", self._on_right_click)

        # Context menu
        self.ctx_menu = tk.Menu(self.root, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT,
                                activeforeground="#1e1e2e", font=("Segoe UI", 10))
        self.ctx_menu.add_command(label=t("ctx_switch"), command=self._use_provider)
        self.ctx_menu.add_command(label=t("ctx_edit"), command=self._edit_provider)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label=t("ctx_remove"), command=self._remove_provider)

        # Buttons row 1
        btn1 = tk.Frame(self.root, bg=BG)
        btn1.pack(fill="x", padx=16, pady=(4, 2))

        self.btn_use = ttk.Button(btn1, text=t("use_provider"), style="Accent.TButton", command=self._use_provider)
        self.btn_use.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_edit = ttk.Button(btn1, text=t("edit_provider"), command=self._edit_provider)
        self.btn_edit.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_save = ttk.Button(btn1, text=t("save_current"), command=self._save_current)
        self.btn_save.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_remove = ttk.Button(btn1, text=t("remove"), style="Danger.TButton", command=self._remove_provider)
        self.btn_remove.pack(side="left", expand=True, fill="x")

        # Options
        self.convert_var = tk.BooleanVar(value=True)
        self.autobackup_var = tk.BooleanVar(value=True)
        self.pin_var = tk.BooleanVar(value=False)
        opt = tk.Frame(self.root, bg=BG)
        opt.pack(fill="x", padx=16, pady=(6, 2))

        self.chk_convert = ttk.Checkbutton(opt, text=t("convert_chats"), variable=self.convert_var)
        self.chk_convert.pack(anchor="w")
        self.chk_autobackup = ttk.Checkbutton(opt, text=t("auto_backup"), variable=self.autobackup_var)
        self.chk_autobackup.pack(anchor="w")
        self.chk_pin = ttk.Checkbutton(opt, text=t("pin_top"), variable=self.pin_var)
        self.chk_pin.pack(anchor="w")

        # Buttons row 2
        btn2 = tk.Frame(self.root, bg=BG)
        btn2.pack(fill="x", padx=16, pady=(6, 2))

        self.btn_json = ttk.Button(btn2, text=t("add_json"), command=self._add_from_json)
        self.btn_json.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_create = ttk.Button(btn2, text=t("create_new"), command=self._create_provider)
        self.btn_create.pack(side="left", expand=True, fill="x")

        # Buttons row 3
        btn3 = tk.Frame(self.root, bg=BG)
        btn3.pack(fill="x", padx=16, pady=(4, 2))

        self.btn_backup = ttk.Button(btn3, text=t("full_backup"), command=self._backup)
        self.btn_backup.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_restore = ttk.Button(btn3, text=t("restore_zip"), command=self._restore)
        self.btn_restore.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_fixdates = ttk.Button(btn3, text=t("fix_dates"), command=self._fix_dates)
        self.btn_fixdates.pack(side="left", expand=True, fill="x")

        # Sync section
        sync_frame = tk.Frame(self.root, bg=BG2, padx=12, pady=6)
        sync_frame.pack(fill="x", padx=16, pady=(6, 2))

        self._sync_server = None
        self._sync_pin = ""
        self._sync_port = 0

        self.lbl_sync_title = ttk.Label(sync_frame, text=t("sync_title"), style="Active.TLabel")
        self.lbl_sync_title.pack(side="left", padx=(0, 8))
        self.btn_sync = ttk.Button(sync_frame, text=t("sync_start"), command=self._toggle_sync)
        self.btn_sync.pack(side="left")
        self.sync_status = ttk.Label(sync_frame, text=t("sync_stopped"), style="Stats.TLabel")
        self.sync_status.pack(side="left", padx=(8, 0))
        self.btn_dash = ttk.Button(sync_frame, text=t("sync_open"), command=self._open_dashboard, style="Small.TButton")
        self.btn_dash.pack(side="right")
        self.btn_copy_sync = ttk.Button(sync_frame, text=t("sync_copy"), command=self._copy_sync_info, style="Small.TButton")
        self.btn_copy_sync.pack(side="right", padx=(0, 4))

        # Chat Bridge section
        chat_frame = tk.Frame(self.root, bg=BG2, padx=12, pady=8)
        chat_frame.pack(fill="x", padx=16, pady=(6, 2))

        self.chat_droid_sessions = []
        self.chat_codex_sessions = []
        self.chat_droid_map = {}
        self.chat_codex_map = {}
        self.chat_droid_var = tk.StringVar()
        self.chat_codex_var = tk.StringVar()
        self.chat_fresh_var = tk.BooleanVar(value=False)
        self.chat_pin_old_var = tk.BooleanVar(value=True)
        self.chat_skip_system_var = tk.BooleanVar(value=True)
        self.chat_compaction_mode_var = tk.StringVar(value="archived")

        chat_top = tk.Frame(chat_frame, bg=BG2)
        chat_top.pack(fill="x")
        self.lbl_chat_bridge = ttk.Label(chat_top, text=t("chat_bridge"), style="Active.TLabel")
        self.lbl_chat_bridge.pack(side="left")
        self.btn_chat_refresh = ttk.Button(chat_top, text=t("chat_refresh"), command=self._refresh_chat_bridge_sessions, style="Small.TButton")
        self.btn_chat_refresh.pack(side="right")

        chat_rows = tk.Frame(chat_frame, bg=BG2)
        chat_rows.pack(fill="x", pady=(6, 0))
        chat_rows.columnconfigure(1, weight=1)

        self.lbl_chat_droid = ttk.Label(chat_rows, text=t("chat_droid_session"), style="Stats.TLabel")
        self.lbl_chat_droid.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        self.chat_droid_combo = ttk.Combobox(chat_rows, textvariable=self.chat_droid_var, state="readonly", width=54)
        self.chat_droid_combo.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        self.lbl_chat_codex = ttk.Label(chat_rows, text=t("chat_codex_session"), style="Stats.TLabel")
        self.lbl_chat_codex.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        self.chat_codex_combo = ttk.Combobox(chat_rows, textvariable=self.chat_codex_var, state="readonly", width=54)
        self.chat_codex_combo.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        chat_opts = tk.Frame(chat_frame, bg=BG2)
        chat_opts.pack(fill="x", pady=(2, 0))
        self.chk_chat_fresh = ttk.Checkbutton(chat_opts, text=t("chat_fresh_timestamps"), variable=self.chat_fresh_var)
        self.chk_chat_fresh.pack(side="left")
        self.chk_chat_pin_old = ttk.Checkbutton(chat_opts, text=t("chat_pin_old"), variable=self.chat_pin_old_var)
        self.chk_chat_pin_old.pack(side="left", padx=(14, 0))
        self.chk_chat_skip_system = ttk.Checkbutton(chat_opts, text=t("chat_skip_system"), variable=self.chat_skip_system_var)
        self.chk_chat_skip_system.pack(side="left", padx=(14, 0))
        self.lbl_chat_compaction_mode = ttk.Label(chat_opts, text=t("chat_compaction_mode"), style="Stats.TLabel")
        self.lbl_chat_compaction_mode.pack(side="left", padx=(14, 4))
        self.chat_compaction_mode_combo = ttk.Combobox(
            chat_opts,
            textvariable=self.chat_compaction_mode_var,
            state="readonly",
            values=("archived", "inline", "native", "raw"),
            width=8,
        )
        self.chat_compaction_mode_combo.pack(side="left")

        chat_buttons = tk.Frame(chat_frame, bg=BG2)
        chat_buttons.pack(fill="x", pady=(6, 0))
        self.btn_droid_to_codex = ttk.Button(chat_buttons, text=t("droid_to_codex"), command=self._chat_droid_to_codex)
        self.btn_droid_to_codex.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_codex_to_droid = ttk.Button(chat_buttons, text=t("codex_to_droid"), command=self._chat_codex_to_droid)
        self.btn_codex_to_droid.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.btn_chat_mirror_plan = ttk.Button(chat_buttons, text=t("chat_mirror_plan"), command=self._chat_mirror_plan)
        self.btn_chat_mirror_plan.pack(side="left", expand=True, fill="x")

        self.chat_status = ttk.Label(chat_frame, text="", style="Stats.TLabel")
        self.chat_status.pack(anchor="w", pady=(6, 0))

        # Status bar
        tk.Frame(self.root, bg=BG2, height=1).pack(fill="x", padx=16, pady=(8, 2))
        self.status_var = tk.StringVar(value=t("ready"))
        self.status_label = ttk.Label(self.root, textvariable=self.status_var, style="Stats.TLabel")
        self.status_label.pack(padx=16, pady=(0, 8), anchor="w")

    # ── Dialog helper: ensure paste works in grabbed dialogs ────────────────

    @staticmethod
    def _paste_clipboard_into(entry, replace_all=False):
        if str(entry.cget("state")) != "normal":
            return False
        clip = entry.clipboard_get()
        if replace_all:
            entry.delete(0, tk.END)
            entry.insert(0, clip)
        else:
            try:
                entry.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            entry.insert("insert", clip)
        return True

    @staticmethod
    def _handle_entry_shortcut(event):
        try:
            entry = event.widget
            if not hasattr(entry, "insert"):
                return None
            key = str(getattr(event, "keysym", "")).lower()
            keycode = getattr(event, "keycode", None)

            if key in ("a", "cyrillic_ef") or keycode == 65:
                entry.select_range(0, tk.END)
                entry.icursor(tk.END)
                return "break"
            if key in ("c", "cyrillic_es") or keycode == 67:
                entry.event_generate("<<Copy>>")
                return "break"
            if key in ("x", "cyrillic_che") or keycode == 88:
                if str(entry.cget("state")) == "normal":
                    entry.event_generate("<<Cut>>")
                    return "break"
            if key in ("v", "cyrillic_em") or keycode == 86:
                if CodexManagerApp._paste_clipboard_into(entry):
                    return "break"
        except Exception:
            pass
        return None

    @staticmethod
    def _bind_paste(widget):
        """Bind normal edit shortcuts on dialog entries, including RU keyboard layout."""
        widget.bind("<Control-KeyPress>", CodexManagerApp._handle_entry_shortcut)
        for child in widget.winfo_children():
            CodexManagerApp._bind_paste(child)

    def _paste_to_entry(self, entry):
        """Paste clipboard content into an Entry widget."""
        try:
            self._paste_clipboard_into(entry, replace_all=True)
            entry.focus_set()
        except Exception:
            pass

    # ── Language toggle ────────────────────────────────────────────────────

    def _toggle_lang(self):
        global LANG
        LANG = "en" if LANG == "ru" else "ru"
        self.btn_lang.config(text="RU" if LANG == "en" else "EN")
        self._update_labels()
        self._refresh()

    def _update_labels(self):
        self.lbl_subtitle.config(text=t("subtitle"))
        self.lbl_providers.config(text=t("saved_providers"))
        self.btn_use.config(text=t("use_provider"))
        self.btn_save.config(text=t("save_current"))
        self.btn_remove.config(text=t("remove"))
        self.chk_convert.config(text=t("convert_chats"))
        self.chk_autobackup.config(text=t("auto_backup"))
        self.chk_pin.config(text=t("pin_top"))
        self.btn_json.config(text=t("add_json"))
        self.btn_create.config(text=t("create_new"))
        self.btn_backup.config(text=t("full_backup"))
        self.btn_restore.config(text=t("restore_zip"))
        self.lbl_sync_title.config(text=t("sync_title"))
        self.btn_sync.config(text=t("sync_stop") if self._sync_server else t("sync_start"))
        self.btn_dash.config(text=t("sync_open"))
        self.btn_copy_sync.config(text=t("sync_copy"))
        if not self._sync_server:
            self.sync_status.config(text=t("sync_stopped"))
        self.lbl_chat_bridge.config(text=t("chat_bridge"))
        self.btn_chat_refresh.config(text=t("chat_refresh"))
        self.lbl_chat_droid.config(text=t("chat_droid_session"))
        self.lbl_chat_codex.config(text=t("chat_codex_session"))
        self.chk_chat_fresh.config(text=t("chat_fresh_timestamps"))
        self.chk_chat_pin_old.config(text=t("chat_pin_old"))
        self.chk_chat_skip_system.config(text=t("chat_skip_system"))
        self.lbl_chat_compaction_mode.config(text=t("chat_compaction_mode"))
        self.btn_droid_to_codex.config(text=t("droid_to_codex"))
        self.btn_codex_to_droid.config(text=t("codex_to_droid"))
        self.btn_chat_mirror_plan.config(text=t("chat_mirror_plan"))
        self.btn_fixdates.config(text=t("fix_dates"))
        self.btn_edit.config(text=t("edit_provider"))
        self.lbl_model.config(text=f"{t('model')}:")
        self.lbl_reasoning.config(text=f"{t('reasoning')}:")
        self.ctx_menu.entryconfig(0, label=t("ctx_switch"))
        self.ctx_menu.entryconfig(1, label=t("ctx_edit"))
        self.ctx_menu.entryconfig(3, label=t("ctx_remove"))

    # ── Sync server control ─────────────────────────────────────────────────

    def _toggle_sync(self):
        if self._sync_server:
            from codex_sync import stop_server
            stop_server(self._sync_server)
            self._sync_server = None
            self.sync_status.config(text=t("sync_stopped"))
            self.btn_sync.config(text=t("sync_start"))
        else:
            from codex_sync import start_server, get_local_ip
            server, pin, port = start_server(port=None)
            self._sync_server = server
            self._sync_pin = pin
            self._sync_port = port
            ip = get_local_ip()
            self.sync_status.config(text=t("sync_running").format(ip=ip, port=port, pin=pin))
            self.btn_sync.config(text=t("sync_stop"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self._sync_poll()

    def _sync_poll(self):
        if not self._sync_server:
            return
        import codex_sync
        if codex_sync.data_changed:
            codex_sync.data_changed = False
            self._refresh()
        self.root.after(2000, self._sync_poll)

    def _open_dashboard(self):
        if not self._sync_port:
            messagebox.showinfo(t("info"), t("sync_start"))
            return
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{self._sync_port}/dashboard")

    def _copy_sync_info(self):
        if not self._sync_port:
            return
        from codex_sync import get_local_ip
        ip = get_local_ip()
        text = f"{ip}:{self._sync_port} PIN:{self._sync_pin}"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set(f"Copied: {text}")

    # ── Refresh data ───────────────────────────────────────────────────────

    def _refresh(self):
        try:
            stats, archived = _get_chat_stats()
        except Exception:
            stats, archived = {}, {}

        total = sum(stats.values())
        active_cnt = archived.get(0, 0)
        arch_cnt = archived.get(1, 0)

        lines = [f"{t('total_chats')}: {total} ({active_cnt} {t('active_word')}, {arch_cnt} {t('archived_word')})"]
        for prov, cnt in sorted(stats.items(), key=lambda x: -x[1]):
            lines.append(f"  {prov}: {cnt}")
        self.stats_label.config(text="\n".join(lines))

        active = _get_active_provider()
        active_profile = _get_active_profile_name()
        self.active_label.config(text=f"{t('active_provider')}: {active_profile or active}")

        cfg_info = _get_config_info()
        self.model_var.set(cfg_info["model"])
        self.reasoning_var.set(cfg_info.get("reasoning", ""))

        # Provider list
        data = _load_providers()
        profiles = data.get("profiles", {})
        self.provider_listbox.delete(0, tk.END)
        # Only mark a profile active when the live account is actually matched to it.
        # Falling back to the provider name ("openai") would falsely highlight whichever
        # profile happens to share that name after an email change.
        active_marker = active_profile
        for name in profiles:
            prefix = ">>> " if (active_marker and name == active_marker) else "    "
            auth = profiles[name].get("auth_mode", "?")
            saved = profiles[name].get("saved_at", "")[:10]
            email = profiles[name].get("auth_email", "")
            if not email and auth == "chatgpt":
                stored_email, _ = ct.get_stored_auth_email(profiles[name])
                email = stored_email or ""
            email_part = f"  {email}" if email else ""
            self.provider_listbox.insert(tk.END, f"{prefix}{name}  ({auth}, {saved}{email_part})")

        if not active_marker:
            # Active account is logged in but matched no saved profile (e.g. new/changed email).
            self.status_var.set(t("account_unmatched"))
        elif active_marker not in profiles:
            self.status_var.set(t("not_saved", active_marker))

    def _short_chat_text(self, value, limit=62):
        text = " ".join(str(value or "-").split())
        if len(text) > limit:
            return text[: max(0, limit - 3)] + "..."
        return text

    def _chat_time_text(self, value):
        if not value:
            return "-"
        try:
            raw = float(value)
            if raw > 100000000000:
                raw = raw / 1000
            return datetime.datetime.fromtimestamp(raw).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"

    def _droid_session_display(self, session):
        parts = [
            self._short_chat_text(session.get("id"), 28),
            self._short_chat_text(session.get("title"), 36),
            f"msg={session.get('message_count', 0)}",
            self._chat_time_text(session.get("mtime")),
        ]
        if session.get("cwd"):
            parts.append(self._short_chat_text(session.get("cwd"), 42))
        return " | ".join(parts)

    def _codex_session_display(self, row):
        updated = row.get("updated_at_ms") or ((row.get("updated_at") or 0) * 1000)
        return " | ".join([
            self._short_chat_text(row.get("id"), 28),
            self._short_chat_text(row.get("title"), 34),
            self._short_chat_text(row.get("model_provider") or "-", 16),
            self._chat_time_text(updated),
        ])

    def _refresh_chat_bridge_sessions(self, silent=False):
        if not silent:
            self.chat_status.config(text=t("chat_refreshing"))
        threading.Thread(target=self._refresh_chat_bridge_sessions_thread, args=(silent,), daemon=True).start()

    def _refresh_chat_bridge_sessions_thread(self, silent=False):
        try:
            factory_home = droid.factory_home_from_settings(None)
            droid_sessions = chat_bridge.list_droid_sessions(factory_home)
            codex_sessions = ct._fetch_session_rows()

            droid_map = {}
            droid_values = []
            for session in droid_sessions[:80]:
                display = self._droid_session_display(session)
                display = _unique_chat_display(display, session.get("id"), droid_map)
                droid_map[display] = session
                droid_values.append(display)

            codex_map = {}
            codex_values = []
            for row in codex_sessions[:80]:
                display = self._codex_session_display(row)
                display = _unique_chat_display(display, row.get("id"), codex_map)
                codex_map[display] = row
                codex_values.append(display)

            self.root.after(
                0,
                lambda: self._apply_chat_bridge_sessions(
                    droid_sessions, codex_sessions, droid_values, codex_values, droid_map, codex_map, silent
                ),
            )
        except Exception as e:
            error = str(e)
            self.root.after(0, lambda: self._chat_bridge_refresh_failed(error, silent))

    def _apply_chat_bridge_sessions(self, droid_sessions, codex_sessions, droid_values, codex_values, droid_map, codex_map, silent=False):
        self.chat_droid_sessions = droid_sessions
        self.chat_codex_sessions = codex_sessions
        self.chat_droid_map = droid_map
        self.chat_codex_map = codex_map
        self.chat_droid_combo.config(values=droid_values)
        self.chat_codex_combo.config(values=codex_values)
        if self.chat_droid_var.get() not in self.chat_droid_map:
            self.chat_droid_var.set(droid_values[0] if droid_values else "")
        if self.chat_codex_var.get() not in self.chat_codex_map:
            self.chat_codex_var.set(codex_values[0] if codex_values else "")

        status = t("chat_lists_ready").format(droid=len(droid_sessions), codex=len(codex_sessions))
        if not silent or not self.chat_status.cget("text"):
            self.chat_status.config(text=status)
        if not silent:
            self.status_var.set(status)

    def _chat_bridge_refresh_failed(self, error, silent=False):
        self.chat_status.config(text=error)
        if not silent:
            messagebox.showerror(t("error"), error)

    def _selected_droid_chat(self):
        session = self.chat_droid_map.get(self.chat_droid_var.get())
        if not session:
            messagebox.showwarning(t("warning"), t("chat_no_droid"))
            return None
        return session

    def _selected_codex_chat(self):
        row = self.chat_codex_map.get(self.chat_codex_var.get())
        if not row:
            messagebox.showwarning(t("warning"), t("chat_no_codex"))
            return None
        return row

    def _chat_droid_to_codex(self):
        session = self._selected_droid_chat()
        if not session:
            return
        if not messagebox.askyesno(t("chat_bridge"), t("chat_confirm_droid_to_codex")):
            return
        self._start_chat_transfer("droid_to_codex", session)

    def _chat_codex_to_droid(self):
        row = self._selected_codex_chat()
        if not row:
            return
        if not messagebox.askyesno(t("chat_bridge"), t("chat_confirm_codex_to_droid")):
            return
        self._start_chat_transfer("codex_to_droid", row)

    def _format_chat_mirror_plan_summary(self, plan):
        summary = plan.get("summary") or {}
        statuses = summary.get("statuses") or {}
        status_text = ", ".join(f"{name}={count}" for name, count in sorted(statuses.items())) or "none"
        return t("chat_mirror_ready").format(pairs=summary.get("total_pairs", 0), statuses=status_text)

    def _chat_mirror_plan(self):
        self.status_var.set(t("chat_mirror_running"))
        self.chat_status.config(text=t("chat_mirror_running"))
        self._set_buttons_state("disabled")
        threading.Thread(target=self._chat_mirror_plan_thread, daemon=True).start()

    def _chat_mirror_plan_thread(self):
        try:
            factory_home = droid.factory_home_from_settings(None)
            droid_sessions = chat_bridge.list_droid_sessions(factory_home)
            codex_sessions = ct._fetch_session_rows()
            plan = chat_bridge.build_mirror_plan(ct.CODEX_DIR, factory_home, codex_sessions, droid_sessions)
            selection = chat_bridge.select_mirror_actions(plan, direction="newer")
            message = self._format_chat_mirror_plan_summary(plan)
            lines = [
                message,
                f"Apply preview: selected={selection.get('summary', {}).get('selected', 0)} skipped={selection.get('summary', {}).get('skipped', 0)}",
            ]
            for item in (plan.get("items") or [])[:12]:
                lines.append(
                    f"{item.get('status')} | {item.get('action')} | "
                    f"codex={item.get('codex_session_id') or '-'} | droid={item.get('droid_session_id') or '-'}"
                )
            detail = "\n".join(lines)
            self.root.after(0, lambda: self._chat_mirror_plan_done(message, detail))
        except Exception as e:
            error = str(e)
            self.root.after(0, lambda: self._chat_transfer_failed(error))

    def _chat_mirror_plan_done(self, message, detail):
        self._set_buttons_state("normal")
        self.status_var.set(message)
        self.chat_status.config(text=message)
        messagebox.showinfo(t("info"), detail)

    def _start_chat_transfer(self, direction, item):
        self.status_var.set(t("chat_transfer_running"))
        self.chat_status.config(text=t("chat_transfer_running"))
        self._set_buttons_state("disabled")
        preserve_timestamps = not self.chat_fresh_var.get()
        pin_old = self.chat_pin_old_var.get()
        skip_system = self.chat_skip_system_var.get()
        compaction_mode = self.chat_compaction_mode_var.get() or "archived"
        threading.Thread(
            target=self._chat_transfer_thread,
            args=(direction, item, preserve_timestamps, pin_old, skip_system, compaction_mode),
            daemon=True,
        ).start()

    def _chat_transfer_thread(self, direction, item, preserve_timestamps=True, pin_old=False, skip_system=True, compaction_mode="archived"):
        try:
            print(f"[chat_bridge] {direction}: starting transfer...")
            if direction == "droid_to_codex":
                summary = self._run_droid_to_codex_transfer(item, preserve_timestamps, pin_old, compaction_mode)
                message = t("chat_imported_codex").format(session=summary["codex_session_id"])
            else:
                summary = self._run_codex_to_droid_transfer(item, preserve_timestamps, skip_system, compaction_mode)
                message = t("chat_imported_droid").format(session=summary["droid_session_id"])
            print(f"[chat_bridge] {direction}: done - {message}")
            warnings = summary.get("warnings") or []
            detail = message
            if warnings:
                detail += " | warnings: " + "; ".join(str(w) for w in warnings)
            self.root.after(0, lambda: self._chat_transfer_done(message, detail))
        except Exception as e:
            error = str(e)
            print(f"[chat_bridge] ERROR: {error}")
            self.root.after(0, lambda: self._chat_transfer_failed(error))

    def _run_droid_to_codex_transfer(self, session, preserve_timestamps=True, pin_old=False, compaction_mode="archived"):
        session_id = session.get("id") or ""
        jsonl_path = Path(session.get("jsonl_path") or (droid.factory_home_from_settings(None) / "sessions" / f"{session_id}.jsonl"))
        settings_path = Path(session.get("settings_path") or jsonl_path.with_suffix(".settings.json"))
        if not jsonl_path.exists():
            raise ValueError(f"Droid session JSONL not found: {jsonl_path}")

        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path if settings_path.exists() else None)
        target_config = ct._chat_import_target_config()
        old_before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=180)
        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=ct.CODEX_DIR,
            state_db=ct.STATE_DB,
            sessions_dir=getattr(ct, "SESSIONS_DIR", SESSIONS_DIR),
            global_state_path=ct.GLOBAL_STATE,
            preserve_timestamps=preserve_timestamps,
            pin_old=pin_old,
            old_before_ms=int(old_before.timestamp() * 1000),
            compaction_mode=compaction_mode,
            target_provider=target_config.get("provider"),
            target_model=target_config.get("model"),
            codex_desktop_compat=True,
        )
        ct.record_history(
            "chat_bridge_droid_to_codex",
            source="gui",
            details={
                "sessions": 1,
                "droid_session_id": session_id,
                "codex_session_id": summary.get("codex_session_id"),
                "preserve_timestamps": preserve_timestamps,
                "compaction_mode": compaction_mode,
            },
        )
        return summary

    def _run_codex_to_droid_transfer(self, row, preserve_timestamps=True, skip_system=True, compaction_mode="archived"):
        session_id = row.get("id") or ""
        rows = ct._fetch_session_rows(session_ids=[session_id])
        if not rows:
            raise ValueError(f"Codex session not found: {session_id}")
        row = rows[0]
        rollout_path = ct._normalize_rollout_path(row.get("rollout_path"))
        if not rollout_path or not os.path.exists(rollout_path):
            raise ValueError(f"Codex rollout not found: {rollout_path or session_id}")
        bridge = chat_bridge.codex_session_to_bridge(row, rollout_path, include_system=not skip_system)
        factory_home = droid.factory_home_from_settings(None)
        target_config = ct._chat_import_target_config()
        summary = chat_bridge.import_bridge_to_droid(
            bridge,
            factory_home=factory_home,
            preserve_timestamps=preserve_timestamps,
            compaction_mode=compaction_mode,
            target_provider=target_config.get("provider"),
            target_model=target_config.get("model"),
        )
        ct.record_history(
            "chat_bridge_codex_to_droid",
            source="gui",
            details={
                "sessions": 1,
                "codex_session_id": session_id,
                "droid_session_id": summary.get("droid_session_id"),
                "preserve_timestamps": preserve_timestamps,
                "include_system": not skip_system,
                "compaction_mode": compaction_mode,
                "factory_home": str(factory_home),
            },
        )
        return summary

    def _chat_transfer_done(self, message, detail):
        self._set_buttons_state("normal")
        self._refresh()
        self._refresh_chat_bridge_sessions(silent=True)
        self.status_var.set(message)
        self.chat_status.config(text=detail)
        messagebox.showinfo(t("ok"), detail)

    def _chat_transfer_failed(self, error):
        self._set_buttons_state("normal")
        self.status_var.set(error)
        self.chat_status.config(text=error)
        messagebox.showerror(t("error"), error)

    # ── Auth sync on startup ───────────────────────────────────────────────

    def _check_auth_sync(self):
        """Check OpenAI auth sync and unsaved active provider on startup."""
        self._check_openai_auth_sync_gui()
        self._check_active_provider_saved_gui()

    def _check_openai_auth_sync_gui(self):
        """GUI: on startup, silently save the live auth.json back into the active
        chatgpt profile when it is fresher than what's stored.

        Finds the ACTIVE account and refreshes its stored auth without any prompt.
        """
        print("[auth_sync] checking...")
        active_profile = ct.compute_active_auth_sync()
        if not active_profile:
            return
        print(f"[auth_sync] refreshing stored auth for active profile '{active_profile}'")
        ct.save_provider(active_profile)
        self._refresh()
        self.status_var.set(t("auth_updated", active_profile))

    def _check_active_provider_saved_gui(self):
        """GUI: prompt to save active provider if not in profiles."""
        active = _get_active_provider()
        if not active or active == "?":
            return
        # If the current account is already recognized as a saved profile, nothing to do.
        if _get_active_profile_name() is not None:
            return
        prov_data = _load_providers()
        profiles = prov_data.get("profiles", {})
        if active in profiles:
            return
        if messagebox.askyesno(
            t("not_saved_title"),
            t("not_saved_prompt", active),
        ):
            ct.save_provider(active)
            self._refresh()
            self.status_var.set(t("save_done", active, active, "unknown"))

    # ── Auto-detect ────────────────────────────────────────────────────────

    def _auto_detect(self):
        """Scan for provider JSON files next to the app."""
        found = _scan_for_provider_jsons()
        data = _load_providers()
        profiles = data.get("profiles", {})

        for item in found:
            name = ct.sanitize_name(item["name"])
            if name in profiles:
                continue
            if messagebox.askyesno(t("auto_detect_title"), t("auto_detected", name)):
                self._import_provider_data(item["data"], name)

    def _import_provider_data(self, raw, fallback_name=None):
        """Import provider from various JSON structures."""
        data = _load_providers()
        config_text = None
        auth_text = None
        provider_name = None

        if "config.toml" in raw and "auth.json" in raw:
            provider_name = raw.get("model_provider", fallback_name or "unknown")
            config_text = raw.get("config.toml", "")
            auth_text = raw.get("auth.json", "")
            if isinstance(auth_text, dict):
                auth_text = json.dumps(auth_text, indent=2)
        elif "profiles" in raw:
            profiles = raw.get("profiles", {})
            for pname, pdata in profiles.items():
                provider_name = pname
                config_text = pdata.get("config.toml", "")
                auth_text = pdata.get("auth.json", "")
                break
        elif "OPENAI_API_KEY" in raw:
            auth_text = json.dumps(raw, indent=2)
            provider_name = fallback_name or "NewProvider"
        elif "base_url" in raw:
            name = ct.sanitize_name(raw.get("name", fallback_name or "NewProvider"))
            model = raw.get("model", "gpt-5.5")
            wire = raw.get("wire_api", "responses")
            reasoning = raw.get("model_reasoning_effort", "")
            personality = raw.get("personality", "")
            api_key = raw.get("api_key", "")
            base_url = raw.get("base_url", "")
            lines = [
                f'model = "{model}"',
                f'model_provider = "{name}"',
            ]
            if reasoning:
                lines.append(f'model_reasoning_effort = "{reasoning}"')
            if personality:
                lines.append(f'personality = "{personality}"')
            lines.append(f'\n[model_providers.{name}]')
            lines.append(f'name = "{name}"')
            lines.append(f'base_url = "{base_url}"')
            lines.append(f'wire_api = "{wire}"')
            config_text = "\n".join(lines) + "\n"
            if api_key:
                auth_text = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": api_key}, indent=2)
            else:
                api_key = self._ask_api_key(name)
                if api_key:
                    auth_text = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": api_key}, indent=2)
            provider_name = name

        if not provider_name:
            provider_name = fallback_name or "Unknown"

        if not config_text and not auth_text:
            messagebox.showerror(t("error"), t("json_error"))
            return

        # Ask name if needed
        name_raw = self._ask_string(t("save_title"), t("save_prompt"), initialvalue=provider_name)
        if not name_raw:
            return
        name = ct.sanitize_name(name_raw)

        pn = ct.detect_provider_from_text(config_text) if config_text else name
        am = _detect_auth_mode_text(auth_text) if auth_text else "unknown"

        # Extract provider section from config text
        _, section, model_val = ct.extract_provider_config(config_text) if config_text else (None, None, None)

        data.setdefault("profiles", {})[name] = {
            "model_provider": pn,
            "model": model_val,
            "auth_mode": am,
            "provider_section": section or "",
            "auth.json": auth_text or "",
            "saved_at": datetime.datetime.now().isoformat(),
        }
        _save_providers(data)
        self._refresh()
        self.status_var.set(t("json_added", name))

    # ── Provider actions ───────────────────────────────────────────────────

    def _use_provider(self):
        if ct.is_codex_running():
            messagebox.showwarning(t("warning"), t("codex_running"))
        name = self._get_selected()
        if not name:
            return

        data = _load_providers()
        profiles = data.get("profiles", {})
        if name not in profiles:
            messagebox.showerror(t("error"), t("not_found", name))
            return

        prof = profiles[name]
        target = prof["model_provider"]
        active = _get_active_provider()
        active_profile = _get_active_profile_name()

        # Block only when the SAME account/profile is selected, not merely the same
        # provider — two different OpenAI logins share model_provider="openai".
        if active_profile and name == active_profile:
            messagebox.showinfo(t("info"), t("already_using", active_profile))
            return

        if not messagebox.askyesno(t("switch_title"), t("switch_confirm", active_profile or active, name)):
            return

        try:
            # Auto-save / update current provider auth
            cfg = _read_file_safe(CODEX_DIR / "config.toml")
            auth = _read_file_safe(CODEX_DIR / "auth.json")
            if cfg:
                _, section, model_val = ct.extract_provider_config(cfg)
                auth_mode = _detect_auth_mode(CODEX_DIR / "auth.json") or "unknown"
                auth_email = None
                if auth_mode == "chatgpt" and auth:
                    try:
                        auth_data = json.loads(auth)
                        auth_email = ct.extract_email_from_jwt(auth_data.get("tokens", {}).get("id_token"))
                    except Exception:
                        pass
                existing = profiles.get(active_profile or active, {})
                profiles[active_profile or active] = {
                    "model_provider": active,
                    "model": model_val,
                    "auth_mode": auth_mode,
                    "provider_section": section,
                    "auth.json": auth,
                    "auth_email": auth_email,
                    "bound_at": existing.get("bound_at") or datetime.datetime.now().isoformat(),
                    "saved_at": datetime.datetime.now().isoformat(),
                }
                print(f"[switch] updated current provider auth: {active_profile or active}")

            # Merge config — new format or backward compat
            target_section = prof.get("provider_section")
            target_model = prof.get("model")
            target_reasoning = prof.get("model_reasoning_effort")
            if not target_section:
                old_cfg = prof.get("config.toml")
                if old_cfg:
                    _, target_section, target_model = ct.extract_provider_config(old_cfg)

            current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
            print(f"[switch] merging config: {active} -> {target} (model={target_model}, reasoning={target_reasoning})")
            if current_cfg and target_section:
                merged = _merge_config(current_cfg, target, target_section, target_model, target_reasoning)
                with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
                    f.write(merged)
            elif current_cfg:
                merged = _merge_config(current_cfg, target, None, target_model, target_reasoning)
                with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
                    f.write(merged)
            print("[switch] config.toml written")

            # Write auth
            target_auth = prof.get("auth.json")
            if target_auth:
                with open(str(CODEX_DIR / "auth.json"), "w", encoding="utf-8") as f:
                    f.write(ct.decode_secret(target_auth))
                print("[switch] auth.json written")

            data["active"] = name
            _save_providers(data)
            print(f"[switch] providers.json updated (active={name})")

            # Convert in background thread
            if self.convert_var.get():
                self.status_var.set(t("converting", active, target))
                self.conv_label.config(text=t("converting", active, target))
                self.conv_frame.pack(fill="x", padx=16, pady=(6, 0), before=self.list_frame)
                self._set_buttons_state("disabled")
                print(f"[switch] starting chat conversion thread: {active} -> {target}")
                threading.Thread(target=self._convert_thread, args=(active, target), daemon=True).start()
            else:
                if self.pin_var.get():
                    self._do_pin(10)
                self.status_var.set(t("switched_noconv", target))
                self._refresh()
                print(f"[switch] switched to {target} (no conversion)")
                messagebox.showinfo(t("ok"), t("switch_done", target))

        except Exception as e:
            self._set_buttons_state("normal")
            print(f"[switch] ERROR: {e}")
            messagebox.showerror(t("error"), str(e))

    def _set_buttons_state(self, state):
        for btn in [self.btn_use, self.btn_edit, self.btn_save, self.btn_remove,
                    self.btn_json, self.btn_create, self.btn_backup, self.btn_restore,
                    self.btn_chat_refresh, self.btn_droid_to_codex, self.btn_codex_to_droid,
                    self.btn_chat_mirror_plan]:
            try:
                btn.config(state=state)
            except Exception:
                pass

    def _convert_thread(self, from_p, to_p):
        try:
            self.root.after(0, lambda: self.conv_label.config(text=t("converting", from_p, to_p)))
            total, conv = _run_convert(from_p, to_p, auto_backup=self.autobackup_var.get(),
                                       progress_cb=lambda msg: self.root.after(0, lambda m=msg: self.conv_label.config(text=m)))
            self.root.after(0, lambda: self._convert_done(total, conv, from_p, to_p))
        except Exception as e:
            self.root.after(0, lambda: self._convert_failed(str(e)))

    def _convert_done(self, total, conv, from_p, to_p):
        self.conv_frame.pack_forget()
        self._set_buttons_state("normal")
        if self.pin_var.get():
            self._do_pin(10)
        self.status_var.set(t("converted", conv, from_p, to_p))
        self._refresh()
        messagebox.showinfo(t("ok"), t("switch_done", to_p))

    def _convert_failed(self, error):
        self.conv_frame.pack_forget()
        self._set_buttons_state("normal")
        messagebox.showerror(t("error"), error)

    def _save_current(self):
        active = _get_active_provider()
        name = self._ask_string(t("save_title"), t("save_prompt"), initialvalue=active)
        if not name:
            return

        cfg = _read_file_safe(CODEX_DIR / "config.toml")
        auth = _read_file_safe(CODEX_DIR / "auth.json")
        am = _detect_auth_mode(CODEX_DIR / "auth.json") or "unknown"

        _, section, model_val = ct.extract_provider_config(cfg) if cfg else (None, None, None)

        auth_email = None
        if am == "chatgpt" and auth:
            try:
                auth_data = json.loads(auth)
                auth_email = ct.extract_email_from_jwt(auth_data.get("tokens", {}).get("id_token"))
            except Exception:
                pass

        data = _load_providers()
        existing = data.get("profiles", {}).get(name, {})
        data.setdefault("profiles", {})[name] = {
            "model_provider": active,
            "model": model_val,
            "auth_mode": am,
            "provider_section": section or "",
            "auth.json": auth,
            "auth_email": auth_email,
            "bound_at": existing.get("bound_at") or datetime.datetime.now().isoformat(),
            "saved_at": datetime.datetime.now().isoformat(),
        }
        data["active"] = name
        _save_providers(data)
        print(f"[save] profile '{name}' saved (provider={active}, model={model_val}, auth={am})")

        self._refresh()
        self.status_var.set(t("save_done", name, active, am))

    def _remove_provider(self):
        name = self._get_selected()
        if not name:
            return
        if not messagebox.askyesno(t("remove"), t("remove_confirm", name)):
            return
        data = _load_providers()
        data.get("profiles", {}).pop(name, None)
        _save_providers(data)
        print(f"[remove] profile '{name}' removed")
        self._refresh()
        self.status_var.set(t("remove_done", name))

    def _add_from_json(self):
        path = filedialog.askopenfilename(
            title=t("add_json"), filetypes=[("JSON", "*.json"), ("All", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._import_provider_data(raw, Path(path).stem)
        except Exception as e:
            messagebox.showerror(t("error"), f"{t('json_error')}: {e}")

    def _create_provider(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(t("create_title"))
        dialog.geometry("540x400")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        self._bind_paste(dialog)

        fields = {}
        row = 0
        for label_key, key, default in [
            ("f_name", "name", ""),
            ("f_model", "model", "gpt-5.5"),
            ("f_url", "base_url", "https://api.example.com/v1"),
            ("f_key", "api_key", ""),
            ("f_wire", "wire_api", "responses"),
        ]:
            ttk.Label(dialog, text=t(label_key), style="TLabel").grid(row=row, column=0, padx=12, pady=4, sticky="w")
            var = tk.StringVar(value=default)
            entry = tk.Entry(dialog, textvariable=var, bg=BG2, fg=FG, insertbackground=FG, font=("Segoe UI", 10), relief="flat", width=32)
            self._bind_paste(entry)
            entry.grid(row=row, column=1, padx=12, pady=4)
            ttk.Button(dialog, text=t("paste_clip"), style="Small.TButton",
                       command=lambda e=entry: self._paste_to_entry(e)).grid(row=row, column=2, padx=(0, 8), pady=4)
            fields[key] = var
            row += 1

        # Reasoning dropdown
        ttk.Label(dialog, text=t("f_reasoning"), style="TLabel").grid(row=row, column=0, padx=12, pady=4, sticky="w")
        reasoning_var = tk.StringVar(value="")
        reasoning_cb = ttk.Combobox(dialog, textvariable=reasoning_var, values=["", "low", "medium", "high", "xhigh"],
                                    width=29, state="readonly", font=("Segoe UI", 10))
        reasoning_cb.grid(row=row, column=1, padx=12, pady=4)
        row += 1

        def _create():
            name = fields["name"].get().strip()
            if not name:
                messagebox.showwarning(t("warning"), t("f_enter_name"), parent=dialog)
                return
            model = fields["model"].get().strip() or "gpt-5.5"
            base_url = fields["base_url"].get().strip()
            api_key = fields["api_key"].get().strip()
            wire_api = fields["wire_api"].get().strip() or "responses"
            reasoning = reasoning_var.get().strip()

            section = f'[model_providers.{name}]\nname = "{name}"\nbase_url = "{base_url}"\nwire_api = "{wire_api}"'
            auth = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": api_key}, indent=2)

            data = _load_providers()
            data.setdefault("profiles", {})[name] = {
                "model_provider": name,
                "model": model,
                "auth_mode": "apikey",
                "model_reasoning_effort": reasoning,
                "provider_section": section,
                "auth.json": auth,
                "saved_at": datetime.datetime.now().isoformat(),
            }
            _save_providers(data)
            dialog.destroy()
            self._refresh()
            self.status_var.set(t("save_done", name, name, "apikey"))

        ttk.Button(dialog, text=t("f_create"), style="Accent.TButton", command=_create).grid(row=row, column=0, columnspan=2, pady=16)

    def _on_right_click(self, event):
        sel = self.provider_listbox.curselection()
        if sel:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)

    def _edit_provider(self):
        name = self._get_selected()
        if not name:
            return

        data = _load_providers()
        profiles = data.get("profiles", {})
        if name not in profiles:
            messagebox.showerror(t("error"), t("not_found", name))
            return

        prof = profiles[name]

        # Parse current values from profile
        section = prof.get("provider_section", "")
        cur_url = ""
        cur_wire = ""
        for line in section.split("\n"):
            s = line.strip()
            if s.startswith("base_url") and "=" in s:
                cur_url = s.split("=", 1)[1].strip().strip('"')
            elif s.startswith("wire_api") and "=" in s:
                cur_wire = s.split("=", 1)[1].strip().strip('"')

        cur_model = prof.get("model", "")
        cur_reasoning = prof.get("model_reasoning_effort", "")

        # Fallback: old config.toml format in profile
        if not section:
            old_cfg = prof.get("config.toml", "")
            if old_cfg:
                _, section, _ = ct.extract_provider_config(old_cfg)
                for line in section.split("\n"):
                    s = line.strip()
                    if s.startswith("base_url") and "=" in s and not cur_url:
                        cur_url = s.split("=", 1)[1].strip().strip('"')
                    elif s.startswith("wire_api") and "=" in s and not cur_wire:
                        cur_wire = s.split("=", 1)[1].strip().strip('"')

        # Decode current API key
        cur_key = ""
        auth_raw = prof.get("auth.json", "")
        if auth_raw:
            try:
                auth_decoded = json.loads(ct.decode_secret(auth_raw))
                cur_key = auth_decoded.get("OPENAI_API_KEY", "")
            except Exception:
                pass

        is_openai = (prof.get("model_provider", name).lower() == "openai")
        openai_note = " *" if is_openai else ""

        dialog = tk.Toplevel(self.root)
        dialog.title(t("edit_title"))
        dialog.geometry("540x400")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        self._bind_paste(dialog)

        fields = {}
        row = 0
        for label_key, key, default, editable in [
            ("f_name", "name", name, True),
            ("f_model", "model", cur_model, True),
            ("f_url", "base_url", cur_url, not is_openai),
            ("f_key", "api_key", cur_key, not is_openai),
            ("f_wire", "wire_api", cur_wire or "responses", not is_openai),
        ]:
            label_text = t(label_key)
            if is_openai and key in ("base_url", "api_key", "wire_api"):
                label_text += " " + t("openai_note")
            ttk.Label(dialog, text=label_text, style="TLabel").grid(row=row, column=0, padx=12, pady=4, sticky="w")
            var = tk.StringVar(value=default)
            entry = tk.Entry(dialog, textvariable=var, bg=BG2, fg=FG if editable else FG2,
                             insertbackground=FG if editable else BG2,
                             font=("Segoe UI", 10), relief="flat", width=32,
                             readonlybackground=BG2)
            if editable:
                self._bind_paste(entry)
            entry.grid(row=row, column=1, padx=12, pady=4)
            if not editable:
                entry.config(state="readonly")
            if editable:
                ttk.Button(dialog, text=t("paste_clip"), style="Small.TButton",
                           command=lambda e=entry: self._paste_to_entry(e)).grid(row=row, column=2, padx=(0, 8), pady=4)
            fields[key] = (var, editable)
            row += 1

        # Reasoning dropdown
        ttk.Label(dialog, text=t("f_reasoning"), style="TLabel").grid(row=row, column=0, padx=12, pady=4, sticky="w")
        reasoning_var = tk.StringVar(value=cur_reasoning or "")
        reasoning_cb = ttk.Combobox(dialog, textvariable=reasoning_var, values=["", "low", "medium", "high", "xhigh"],
                                    width=29, state="readonly", font=("Segoe UI", 10))
        reasoning_cb.grid(row=row, column=1, padx=12, pady=4)
        row += 1

        orig_name = name

        def _save():
            new_name_raw = fields["name"][0].get().strip()
            if not new_name_raw:
                messagebox.showwarning(t("warning"), t("f_enter_name"), parent=dialog)
                return
            new_name = ct.sanitize_name(new_name_raw)
            model = fields["model"][0].get().strip()
            base_url = fields["base_url"][0].get().strip()
            api_key = fields["api_key"][0].get().strip()
            wire_api = fields["wire_api"][0].get().strip() or "responses"
            reasoning = reasoning_var.get().strip()

            # For openai: keep original url/key/wire
            if is_openai:
                base_url = cur_url
                api_key = cur_key
                wire_api = cur_wire or "responses"

            section = f'[model_providers.{new_name}]\nname = "{new_name}"\nbase_url = "{base_url}"\nwire_api = "{wire_api}"'

            auth = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": api_key}, indent=2) if api_key else prof.get("auth.json", "")

            # If name changed, rename profile key
            if new_name != orig_name:
                del profiles[orig_name]

            profiles[new_name] = {
                "model_provider": new_name,
                "model": model,
                "auth_mode": "apikey" if api_key else prof.get("auth_mode", "unknown"),
                "model_reasoning_effort": reasoning,
                "provider_section": section,
                "auth.json": auth,
                "saved_at": prof.get("saved_at", datetime.datetime.now().isoformat()),
            }
            data["profiles"] = profiles
            _save_providers(data)

            # Update config.toml if this is the active provider (by old or new name)
            active = _get_active_provider()
            if active in (orig_name, new_name):
                current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
                if current_cfg:
                    # Remove old section if renamed
                    if new_name != orig_name:
                        current_cfg = ct.remove_provider_section(current_cfg, orig_name)
                    merged = ct.merge_config(current_cfg, new_name, section, model, reasoning if reasoning else None)
                    with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
                        f.write(merged)

            # Convert chats when renaming active provider
            if new_name != orig_name and active in (orig_name, new_name):
                conn = ct.get_db_conn()
                if conn is not None:
                    try:
                        ct.transform(conn, orig_name, new_name)
                    finally:
                        conn.close()

            dialog.destroy()
            self._refresh()
            self.status_var.set(t("edit_done", new_name))

        ttk.Button(dialog, text=t("f_save"), style="Accent.TButton", command=_save).grid(row=row, column=0, columnspan=2, pady=16)

    def _on_model_change(self, event=None):
        new_model = self.model_var.get().strip()
        if not new_model:
            return
        info = _get_config_info()
        if new_model == info.get("model"):
            return
        ct.set_model(new_model)
        self._refresh()
        self.status_var.set(t("model_done", new_model))

    def _on_reasoning_change(self, event=None):
        new_reas = self.reasoning_var.get().strip()
        info = _get_config_info()
        if new_reas == info.get("reasoning"):
            return
        cfg = _read_file_safe(CODEX_DIR / "config.toml")
        if not cfg:
            return
        merged = ct.merge_config(cfg, _get_active_provider(), None, None, new_reas or None)
        with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
            f.write(merged)
        self._refresh()
        self.status_var.set(t("reasoning_set", new_reas or t("default_val")))

    def _backup(self):
        import zipfile
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            title=t("full_backup"), defaultextension=".zip",
            initialfile=f"codex_backup_{ts}.zip", filetypes=[("ZIP", "*.zip")]
        )
        if not path:
            return
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for fn in ["state_5.sqlite", ".codex-global-state.json", "config.toml", "auth.json"]:
                    fp = CODEX_DIR / fn
                    if fp.exists():
                        zf.write(str(fp), f"codex/{fn}")
                for d in ["sessions", "archived_sessions"]:
                    dp = CODEX_DIR / d
                    if dp.exists():
                        for fp in dp.rglob("*"):
                            if fp.is_file():
                                zf.write(str(fp), f"codex/{fp.relative_to(CODEX_DIR)}")
            self.status_var.set(f"{t('backup_saved')}: {path}")
            print(f"[backup] saved to {path}")
            messagebox.showinfo(t("ok"), f"{t('backup_saved')}:\n{path}")
        except Exception as e:
            print(f"[backup] ERROR: {e}")
            messagebox.showerror(t("error"), str(e))

    def _restore(self):
        path = filedialog.askopenfilename(title=t("restore_zip"), filetypes=[("ZIP", "*.zip")])
        if not path:
            return
        if not messagebox.askyesno(t("restore_title"), t("restore_confirm")):
            return
        try:
            import zipfile
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    rel = name.split("/", 1)[-1] if "/" in name else name
                    dest = CODEX_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    zf.extract(name, str(CODEX_DIR.parent))
            self._refresh()
            self.status_var.set(f"{t('restore_done')}")
            print(f"[restore] restored from {path}")
            messagebox.showinfo(t("ok"), t("restore_done"))
        except Exception as e:
            print(f"[restore] ERROR: {e}")
            messagebox.showerror(t("error"), str(e))

    def _fix_dates(self):
        """Set file mtimes to last event timestamp."""
        conn = _db_conn()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT rollout_path FROM threads WHERE rollout_path IS NOT NULL")
        fixed = 0
        for (rp,) in cur.fetchall():
            rp = rp or ""
            if rp.startswith("\\\\?"):
                rp = rp[4:]
            if not rp or not os.path.exists(rp):
                continue
            ts = self._get_last_event_ts(rp)
            if ts:
                os.utime(rp, (ts, ts))
                fixed += 1
        conn.close()
        self.status_var.set(t("files_fixed", fixed))

    def _get_last_event_ts(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                last_line = None
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
                if not last_line:
                    return None
                obj = json.loads(last_line)
                ts = obj.get("timestamp", "")
                if ts:
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    return dt.timestamp()
        except Exception:
            pass
        return None

    def _do_pin(self, n):
        conn = _db_conn()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("SELECT id FROM threads WHERE archived = 0 AND source IN ('cli','vscode','exec') ORDER BY updated_at_ms DESC LIMIT ?", (n,))
        ids = [row[0] for row in cur.fetchall()]
        conn.close()
        if not ids:
            return
        if GLOBAL_STATE.exists():
            with open(str(GLOBAL_STATE), "r", encoding="utf-8") as f:
                gs = json.load(f)
        else:
            gs = {}
        pinned = set(gs.get("pinned-thread-ids", []))
        added = sum(1 for tid in ids if tid not in pinned and not pinned.add(tid))
        gs["pinned-thread-ids"] = list(pinned)
        with open(str(GLOBAL_STATE), "w", encoding="utf-8") as f:
            json.dump(gs, f, indent=2, ensure_ascii=False)
        self.status_var.set(t("pinned_count", added))

    def _get_selected(self):
        sel = self.provider_listbox.curselection()
        if not sel:
            messagebox.showwarning(t("warning"), t("no_selection"))
            return None
        line = self.provider_listbox.get(sel[0])
        return line.strip().lstrip(">").strip().split("  ")[0].strip()

    def _ask_string(self, title, prompt, initialvalue=""):
        result = tk.StringVar(value=initialvalue)
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("360x120")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        self._bind_paste(dialog)
        ttk.Label(dialog, text=prompt, style="TLabel").pack(padx=12, pady=(12, 4))
        entry_frame = tk.Frame(dialog, bg=BG)
        entry_frame.pack(fill="x", padx=12)
        entry = tk.Entry(entry_frame, textvariable=result, bg=BG2, fg=FG, insertbackground=FG, font=("Segoe UI", 11), relief="flat")
        self._bind_paste(entry)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(entry_frame, text=t("paste_clip"), style="Small.TButton",
                   command=lambda: self._paste_to_entry(entry)).pack(side="right", padx=(4, 0))
        entry.select_range(0, tk.END)
        entry.focus()
        def _ok(e=None): dialog.destroy()
        entry.bind("<Return>", _ok)
        ttk.Button(dialog, text=t("ok"), command=_ok).pack(pady=8)
        dialog.wait_window()
        return result.get().strip()

    def _ask_api_key(self, provider_name):
        result = tk.StringVar()
        dialog = tk.Toplevel(self.root)
        dialog.title(t("ask_key_title"))
        dialog.geometry("420x160")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        self._bind_paste(dialog)
        ttk.Label(dialog, text=t("ask_key_msg", provider_name), style="TLabel", wraplength=380).pack(padx=12, pady=(12, 4))
        entry_frame = tk.Frame(dialog, bg=BG)
        entry_frame.pack(fill="x", padx=12)
        entry = tk.Entry(entry_frame, textvariable=result, bg=BG2, fg=FG, insertbackground=FG, font=("Segoe UI", 11), relief="flat", show="*")
        self._bind_paste(entry)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(entry_frame, text=t("paste_clip"), style="Small.TButton",
                   command=lambda: self._paste_to_entry(entry)).pack(side="right", padx=(4, 0))
        entry.focus()
        def _ok(e=None): dialog.destroy()
        def _skip(): result.set(""); dialog.destroy()
        entry.bind("<Return>", _ok)
        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text=t("ok"), command=_ok).pack(side="left", padx=4)
        ttk.Button(btn_frame, text=t("ask_key_skip"), command=_skip).pack(side="left", padx=4)
        dialog.wait_window()
        return result.get().strip() or None


# ── Consent check ───────────────────────────────────────────────────────────

def _check_consent():
    """Check if user accepted terms. Returns True if consent given, False to exit."""
    data = _load_providers()
    consent = data.get("consent", {})
    if consent.get("accepted"):
        return True

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title(t("consent_title"))
    dialog.geometry("520x400")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.protocol("WM_DELETE_WINDOW", lambda: (root.destroy(), sys.exit(0)))

    # Title
    tk.Label(
        dialog, text=t("consent_title"), bg=BG, fg=ACCENT,
        font=("Segoe UI", 12, "bold"), wraplength=480
    ).pack(padx=20, pady=(16, 8))

    # Disclaimer text
    tk.Label(
        dialog, text=t("consent_text"), bg=BG, fg=FG,
        font=("Consolas", 9), justify="left", anchor="nw"
    ).pack(padx=20, fill="both")

    # Checkbox
    accept_var = tk.BooleanVar(value=False)
    chk = ttk.Checkbutton(
        dialog, text=t("consent_accept"),
        variable=accept_var, style="TCheckbutton"
    )
    chk.pack(pady=(12, 4))

    # Buttons
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(4, 16))

    def _confirm():
        if not accept_var.get():
            return
        data["consent"] = {
            "accepted": True,
            "accepted_at": datetime.datetime.now().isoformat(),
        }
        _save_providers(data)
        dialog.destroy()
        root.destroy()

    def _decline():
        root.destroy()
        sys.exit(0)

    btn_accept = ttk.Button(
        btn_frame, text=t("consent_accept"), style="Accent.TButton",
        command=_confirm, state="disabled"
    )
    btn_accept.pack(side="left", padx=8)

    ttk.Button(
        btn_frame, text=t("consent_decline"), style="Danger.TButton",
        command=_decline
    ).pack(side="left", padx=8)

    def _toggle_btn(*_):
        btn_accept.config(state="normal" if accept_var.get() else "disabled")

    accept_var.trace_add("write", _toggle_btn)

    dialog.wait_window()
    return False


if __name__ == "__main__":
    _check_consent()
    root = tk.Tk()
    app = CodexManagerApp(root)
    root.mainloop()

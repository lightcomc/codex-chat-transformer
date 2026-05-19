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

import codex_chat_transformer as ct

# ── Paths ──────────────────────────────────────────────────────────────────

CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
STATE_DB = CODEX_DIR / "state_5.sqlite"
GLOBAL_STATE = CODEX_DIR / ".codex-global-state.json"
SCRIPT_DIR = Path(__file__).resolve().parent
PROVIDERS_FILE = CODEX_DIR / "providers.json"

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
}

def t(key, *args):
    s = T.get(key, {}).get(LANG, key)
    return s.format(*args) if args else s


# ── Data helpers (delegate to CLI module) ────────────────────────────────────

def _db_conn():
    return ct.get_db_conn(exit_on_error=False)


def _get_chat_stats():
    stats, active, archived = ct.get_thread_stats()
    return stats, {0: active, 1: archived}


def _get_config_info():
    """Read model, reasoning effort, subagent config from config.toml."""
    info = {"model": "?", "reasoning": "?", "subagent_model": None}
    cfg = CODEX_DIR / "config.toml"
    if not cfg.exists():
        return info
    with open(str(cfg), "r", encoding="utf-8") as f:
        in_multi_agent = False
        for line in f:
            s = line.strip()
            if s.startswith("model") and "=" in s and not s.startswith("model_"):
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
    return ct._get_active_provider()


def _load_providers():
    data = ct._load_providers()
    for prof in data.get("profiles", {}).values():
        prof["auth.json"] = ct._decode_secret(prof.get("auth.json"))
    return data


def _save_providers(data):
    ct._save_providers(data)


def _read_file_safe(path):
    return ct._read_file_safe(str(path))


def _detect_provider_in_config(path):
    return ct._detect_provider_in_config(str(path))


def _detect_auth_mode(path):
    return ct._detect_auth_mode(str(path))


def _extract_provider_config(config_text):
    return ct._extract_provider_config(config_text)


def _merge_config(current_text, target_provider, target_section, target_model=None, target_reasoning=None):
    return ct._merge_config(current_text, target_provider, target_section, target_model, target_reasoning)


def _run_convert(from_p, to_p):
    conn = _db_conn()
    if not conn:
        return 0, 0
    cur = conn.cursor()
    cur.execute("SELECT id, rollout_path FROM threads WHERE model_provider = ?", (from_p,))
    threads = cur.fetchall()
    total = len(threads)
    if total == 0:
        conn.close()
        return 0, 0
    cur.execute("UPDATE threads SET model_provider = ? WHERE model_provider = ?", (to_p, from_p))
    conn.commit()
    conn.close()
    jsonl_updated = 0
    for thread in threads:
        rollout = thread["rollout_path"]
        if rollout and ct.transform_jsonl_file(rollout, from_p, to_p):
            jsonl_updated += 1
    return total, jsonl_updated


def _detect_provider_in_text(text):
    return ct._detect_provider_from_text(text)


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
        self.root.geometry("540x700")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self._setup_styles()
        self._build_ui()
        self._refresh()
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

        ttk.Label(info_model, text=f"{t('model')}:", style="Model.TLabel").pack(side="left")
        self.model_var = tk.StringVar()
        self.model_entry = tk.Entry(info_model, textvariable=self.model_var, bg=BG2, fg=ACCENT,
                                    insertbackground=FG, font=("Segoe UI", 10, "bold"),
                                    relief="flat", width=28)
        self.model_entry.pack(side="left", padx=(4, 0))
        self.model_entry.bind("<Return>", self._on_model_change)
        self.model_entry.bind("<FocusOut>", self._on_model_change)

        # Reasoning row: label + combobox
        info_reas = tk.Frame(self.info_frame, bg=BG2)
        info_reas.pack(fill="x", pady=(2, 0))

        ttk.Label(info_reas, text=f"{t('reasoning')}:", style="Model.TLabel").pack(side="left")
        self.reasoning_var = tk.StringVar()
        self.reasoning_cb = ttk.Combobox(info_reas, textvariable=self.reasoning_var,
                                         values=["", "low", "medium", "high", "xhigh"],
                                         width=10, state="readonly", font=("Segoe UI", 10))
        self.reasoning_cb.pack(side="left", padx=(4, 0))
        self.reasoning_cb.bind("<<ComboboxSelected>>", self._on_reasoning_change)

        # Provider list
        list_frame = tk.Frame(self.root, bg=BG2, padx=12, pady=8)
        list_frame.pack(fill="x", padx=16, pady=(0, 6))

        self.lbl_providers = ttk.Label(list_frame, text=t("saved_providers"))
        self.lbl_providers.pack(anchor="w")
        self.provider_listbox = tk.Listbox(
            list_frame, height=5, bg=BG2, fg=FG, selectbackground=ACCENT,
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
        self.pin_var = tk.BooleanVar(value=False)
        opt = tk.Frame(self.root, bg=BG)
        opt.pack(fill="x", padx=16, pady=(6, 2))

        self.chk_convert = ttk.Checkbutton(opt, text=t("convert_chats"), variable=self.convert_var)
        self.chk_convert.pack(anchor="w")
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

        # Status bar
        tk.Frame(self.root, bg=BG2, height=1).pack(fill="x", padx=16, pady=(8, 2))
        self.status_var = tk.StringVar(value=t("ready"))
        self.status_label = ttk.Label(self.root, textvariable=self.status_var, style="Stats.TLabel")
        self.status_label.pack(padx=16, pady=(0, 8), anchor="w")

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
        self.chk_pin.config(text=t("pin_top"))
        self.btn_json.config(text=t("add_json"))
        self.btn_create.config(text=t("create_new"))
        self.btn_backup.config(text=t("full_backup"))
        self.btn_restore.config(text=t("restore_zip"))
        self.btn_fixdates.config(text=t("fix_dates"))
        self.btn_edit.config(text=t("edit_provider"))
        self.ctx_menu.entryconfig(0, label=t("ctx_switch"))
        self.ctx_menu.entryconfig(1, label=t("ctx_edit"))
        self.ctx_menu.entryconfig(3, label=t("ctx_remove"))

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
        self.active_label.config(text=f"{t('active_provider')}: {active}")

        cfg_info = _get_config_info()
        self.model_var.set(cfg_info["model"])
        self.reasoning_var.set(cfg_info.get("reasoning", ""))

        # Provider list
        data = _load_providers()
        profiles = data.get("profiles", {})
        self.provider_listbox.delete(0, tk.END)
        for name in profiles:
            prefix = ">>> " if name == active else "    "
            auth = profiles[name].get("auth_mode", "?")
            saved = profiles[name].get("saved_at", "")[:10]
            self.provider_listbox.insert(tk.END, f"{prefix}{name}  ({auth}, {saved})")

        if active not in profiles:
            self.status_var.set(t("not_saved", active))

    # ── Auto-detect ────────────────────────────────────────────────────────

    def _auto_detect(self):
        """Scan for provider JSON files next to the app."""
        found = _scan_for_provider_jsons()
        data = _load_providers()
        profiles = data.get("profiles", {})

        for item in found:
            name = item["name"]
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
            name = raw.get("name", fallback_name or "NewProvider")
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
        name = self._ask_string(t("save_title"), t("save_prompt"), initialvalue=provider_name)
        if not name:
            return

        pn = ct._detect_provider_from_text(config_text) if config_text else name
        am = _detect_auth_mode_text(auth_text) if auth_text else "unknown"

        # Extract provider section from config text
        _, section, model_val = ct._extract_provider_config(config_text) if config_text else (None, None, None)

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

        if target == active:
            messagebox.showinfo(t("info"), t("already_using", active))
            return

        if not messagebox.askyesno(t("switch_title"), t("switch_confirm", active, target)):
            return

        try:
            # Auto-save current
            if active not in profiles:
                cfg = _read_file_safe(CODEX_DIR / "config.toml")
                auth = _read_file_safe(CODEX_DIR / "auth.json")
                if cfg:
                    _, section, model_val = ct._extract_provider_config(cfg)
                    profiles[active] = {
                        "model_provider": active,
                        "model": model_val,
                        "auth_mode": _detect_auth_mode(CODEX_DIR / "auth.json") or "unknown",
                        "provider_section": section,
                        "auth.json": auth,
                        "saved_at": datetime.datetime.now().isoformat(),
                    }

            # Merge config — new format or backward compat
            target_section = prof.get("provider_section")
            target_model = prof.get("model")
            target_reasoning = prof.get("model_reasoning_effort")
            if not target_section:
                old_cfg = prof.get("config.toml")
                if old_cfg:
                    _, target_section, target_model = ct._extract_provider_config(old_cfg)

            current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
            if current_cfg and target_section:
                merged = _merge_config(current_cfg, target, target_section, target_model, target_reasoning)
                with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
                    f.write(merged)
            elif current_cfg:
                merged = _merge_config(current_cfg, target, None, target_model, target_reasoning)
                with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
                    f.write(merged)

            # Write auth
            target_auth = prof.get("auth.json")
            if target_auth:
                with open(str(CODEX_DIR / "auth.json"), "w", encoding="utf-8") as f:
                    f.write(ct._decode_secret(target_auth))

            data["active"] = target
            _save_providers(data)

            # Convert in background thread
            if self.convert_var.get():
                self.status_var.set(t("converting", active, target))
                self._set_buttons_state("disabled")
                threading.Thread(target=self._convert_thread, args=(active, target), daemon=True).start()
            else:
                if self.pin_var.get():
                    self._do_pin(10)
                self.status_var.set(t("switched_noconv", target))
                self._refresh()
                messagebox.showinfo(t("ok"), t("switch_done", target))

        except Exception as e:
            self._set_buttons_state("normal")
            messagebox.showerror(t("error"), str(e))

    def _set_buttons_state(self, state):
        for btn in [self.btn_use, self.btn_edit, self.btn_save, self.btn_remove,
                    self.btn_json, self.btn_create, self.btn_backup, self.btn_restore]:
            try:
                btn.config(state=state)
            except Exception:
                pass

    def _convert_thread(self, from_p, to_p):
        try:
            total, conv = _run_convert(from_p, to_p)
            self.root.after(0, lambda: self._convert_done(total, conv, from_p, to_p))
        except Exception as e:
            self.root.after(0, lambda: self._convert_failed(str(e)))

    def _convert_done(self, total, conv, from_p, to_p):
        self._set_buttons_state("normal")
        if self.pin_var.get():
            self._do_pin(10)
        self.status_var.set(t("converted", conv, from_p, to_p))
        self._refresh()
        messagebox.showinfo(t("ok"), t("switch_done", to_p))

    def _convert_failed(self, error):
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

        _, section, model_val = ct._extract_provider_config(cfg) if cfg else (None, None, None)

        data = _load_providers()
        data.setdefault("profiles", {})[name] = {
            "model_provider": active,
            "model": model_val,
            "auth_mode": am,
            "provider_section": section or "",
            "auth.json": auth,
            "saved_at": datetime.datetime.now().isoformat(),
        }
        data["active"] = active
        _save_providers(data)

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
        dialog.geometry("440x400")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()

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
            entry.grid(row=row, column=1, padx=12, pady=4)
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
                _, section, _ = ct._extract_provider_config(old_cfg)
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
                auth_decoded = json.loads(ct._decode_secret(auth_raw))
                cur_key = auth_decoded.get("OPENAI_API_KEY", "")
            except Exception:
                pass

        is_openai = (prof.get("model_provider", name).lower() == "openai")
        openai_note = " *" if is_openai else ""

        dialog = tk.Toplevel(self.root)
        dialog.title(t("edit_title"))
        dialog.geometry("440x400")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()

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
            entry.grid(row=row, column=1, padx=12, pady=4)
            if not editable:
                entry.config(state="readonly")
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
            new_name = fields["name"][0].get().strip()
            if not new_name:
                messagebox.showwarning(t("warning"), t("f_enter_name"), parent=dialog)
                return
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

            # Update config.toml if this is the active provider
            active = _get_active_provider()
            if active == new_name:
                current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
                if current_cfg:
                    merged = ct._merge_config(current_cfg, new_name, section, model, reasoning or None)
                    with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
                        f.write(merged)

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
        merged = ct._merge_config(cfg, _get_active_provider(), None, None, new_reas or None)
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
            messagebox.showinfo(t("ok"), f"{t('backup_saved')}:\n{path}")
        except Exception as e:
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
            messagebox.showinfo(t("ok"), t("restore_done"))
        except Exception as e:
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
        dialog.geometry("300x120")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text=prompt, style="TLabel").pack(padx=12, pady=(12, 4))
        entry = tk.Entry(dialog, textvariable=result, bg=BG2, fg=FG, insertbackground=FG, font=("Segoe UI", 11), relief="flat")
        entry.pack(fill="x", padx=12)
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
        dialog.geometry("380x160")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text=t("ask_key_msg", provider_name), style="TLabel", wraplength=340).pack(padx=12, pady=(12, 4))
        entry = tk.Entry(dialog, textvariable=result, bg=BG2, fg=FG, insertbackground=FG, font=("Segoe UI", 11), relief="flat", show="*")
        entry.pack(fill="x", padx=12)
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

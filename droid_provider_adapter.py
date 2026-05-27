#!/usr/bin/env python3
"""Factory Droid provider settings helpers."""

import copy
import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path

FACTORY_DIR = Path(os.environ.get("FACTORY_HOME") or (Path.home() / ".factory"))
SETTINGS_NAME = "settings.json"
LOCAL_SETTINGS_NAME = "settings.local.json"
LEGACY_CONFIG_NAME = "config.json"
MANAGED_BY = "codex-provider-manager"


def factory_home_from_settings(settings_path=None):
    if settings_path is not None:
        return Path(settings_path).expanduser().resolve().parent
    return FACTORY_DIR


def strip_jsonc_comments(text):
    text = text or ""
    chars = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            chars.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue

        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            if index + 1 < len(text):
                index += 2
            else:
                index = len(text)
            continue

        chars.append(char)
        index += 1

    return "".join(chars)


def loads_jsonc(text):
    stripped = strip_jsonc_comments(text)
    if not stripped.strip():
        return {}
    return json.loads(stripped)


def load_jsonc_file(path):
    path = Path(path)
    if not path.exists():
        return {}
    return loads_jsonc(path.read_text(encoding="utf-8"))


def backup_file(path):
    path = Path(path)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
    backup_dir = path.parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    suffix = 0
    while True:
        name = f"{path.name}.{timestamp}.bak" if suffix == 0 else f"{path.name}.{timestamp}.{suffix}.bak"
        backup_path = backup_dir / name
        if not backup_path.exists():
            break
        suffix += 1
    if path.exists():
        shutil.copy2(path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
    return backup_path


def merge_settings(base, local):
    base = base or {}
    local = local or {}
    merged = copy.deepcopy(base)
    for key, value in local.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_settings(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def write_local_settings(home, data):
    home = Path(home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    path = home / LOCAL_SETTINGS_NAME
    backup_path = backup_file(path)
    rendered = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f"{LOCAL_SETTINGS_NAME}.", suffix=".tmp", dir=str(home))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        Path(tmp_name).replace(path)
    finally:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()
    return {"path": path, "backup_path": backup_path}


def normalize_current_model(raw, source):
    if not isinstance(raw, dict):
        return None

    model_id = raw.get("id") or raw.get("model")
    model_name = raw.get("model")
    if not model_id or not model_name:
        return None

    normalized = {
        "id": str(model_id),
        "model": str(model_name),
        "displayName": raw.get("displayName") or raw.get("model_display_name") or str(model_id),
        "baseUrl": raw.get("baseUrl") or raw.get("base_url") or "",
        "provider": raw.get("provider") or "",
        "apiKey": raw.get("apiKey") or raw.get("api_key") or "",
        "reasoningEffort": raw.get("reasoningEffort") or "",
        "source": source,
        "managed": raw.get("managedBy") == MANAGED_BY,
        "raw": copy.deepcopy(raw),
    }
    return normalized


def normalize_legacy_model(raw):
    if not isinstance(raw, dict):
        return None

    model_name = raw.get("model")
    if not model_name:
        return None

    converted = {
        "id": raw.get("id") or f"custom:{model_name}",
        "model": model_name,
        "displayName": raw.get("model_display_name") or raw.get("displayName") or model_name,
        "baseUrl": raw.get("base_url") or raw.get("baseUrl") or "",
        "provider": raw.get("provider") or "",
        "apiKey": raw.get("api_key") or raw.get("apiKey") or "",
        "reasoningEffort": raw.get("reasoningEffort") or "",
        "managedBy": raw.get("managedBy"),
    }
    return normalize_current_model(converted, "config.json")


def _normalize_model_list(rows, source, normalizer):
    models = []
    if not isinstance(rows, list):
        return models
    for row in rows:
        model = normalizer(row) if normalizer is normalize_legacy_model else normalizer(row, source)
        if model is not None:
            models.append(model)
    return models


def _local_settings(home):
    home = Path(home).expanduser().resolve()
    path = home / LOCAL_SETTINGS_NAME
    return path, load_jsonc_file(path)


def _model_index(models, model_id):
    for index, model in enumerate(models or []):
        if isinstance(model, dict) and model.get("id") == model_id:
            return index
    return -1


def neurogate_models(api_key_env="NEUROGATE_API_KEY", api_key=None):
    api_key_value = api_key if api_key is not None else f"${{{api_key_env}}}"
    models = [
        ("custom:NeuroGate-GPT-5.5-1", "gpt-5.5", "NeuroGate GPT-5.5", 1),
        ("custom:NeuroGate-GPT-5.4-2", "gpt-5.4", "NeuroGate GPT-5.4", 2),
        ("custom:NeuroGate-GPT-5.4-Mini-3", "gpt-5.4-mini", "NeuroGate GPT-5.4 Mini", 3),
    ]
    return [
        {
            "id": model_id,
            "model": model_name,
            "displayName": display_name,
            "index": index,
            "baseUrl": "https://api.neurogate.space/v1",
            "provider": "openai",
            "apiKey": api_key_value,
            "maxOutputTokens": 128000,
            "reasoningEffort": "medium",
            "noImageSupport": False,
            "managedBy": MANAGED_BY,
        }
        for model_id, model_name, display_name, index in models
    ]


def load_factory_context(factory_home=None, settings_path=None):
    home = Path(factory_home).expanduser().resolve() if factory_home is not None else factory_home_from_settings(settings_path)
    settings_file = Path(settings_path).expanduser().resolve() if settings_path is not None else (home / SETTINGS_NAME)
    local_file = settings_file.with_name(LOCAL_SETTINGS_NAME)
    legacy_file = home / LEGACY_CONFIG_NAME

    base_settings = load_jsonc_file(settings_file)
    local_settings = load_jsonc_file(local_file)
    settings = merge_settings(base_settings, local_settings)
    legacy_settings = load_jsonc_file(legacy_file)

    custom_models_source = "settings.local.json" if "customModels" in (local_settings or {}) else "settings.json"
    models = _normalize_model_list(settings.get("customModels") or [], custom_models_source, normalize_current_model)
    legacy_models = _normalize_model_list(legacy_settings.get("custom_models") or [], "config.json", normalize_legacy_model)

    return {
        "home": home,
        "settings_path": settings_file,
        "local_settings_path": local_file,
        "legacy_config_path": legacy_file,
        "paths": {
            "settings": settings_file,
            "settings_local": local_file,
            "legacy_config": legacy_file,
        },
        "settings": settings,
        "base_settings": base_settings,
        "local_settings": local_settings,
        "legacy_settings": legacy_settings,
        "models": models,
        "legacy_models": legacy_models,
        "sources": {
            "settings": str(settings_file) if settings_file.exists() else "",
            "settings_local": str(local_file) if local_file.exists() else "",
            "legacy_config": str(legacy_file) if legacy_file.exists() else "",
        },
    }


def add_neurogate_models(factory_home=None, api_key_env="NEUROGATE_API_KEY", api_key=None):
    home = Path(factory_home).expanduser().resolve() if factory_home is not None else FACTORY_DIR
    ctx = load_factory_context(home)
    _, local_settings = _local_settings(home)
    local_settings = copy.deepcopy(local_settings or {})
    if "customModels" in local_settings:
        custom_models = copy.deepcopy(local_settings.get("customModels") or [])
    else:
        custom_models = copy.deepcopy(ctx["settings"].get("customModels") or [])
    if "modelFavorites" in local_settings:
        favorites = list(local_settings.get("modelFavorites") or [])
    else:
        favorites = list(ctx["settings"].get("modelFavorites") or [])
    managed_models = neurogate_models(api_key_env=api_key_env, api_key=api_key)
    added = 0
    updated = 0

    for model in managed_models:
        index = _model_index(custom_models, model["id"])
        if index == -1:
            custom_models.append(copy.deepcopy(model))
            added += 1
        elif custom_models[index] != model:
            custom_models[index] = copy.deepcopy(model)
            updated += 1

    model_ids = [model["id"] for model in managed_models]
    for model_id in model_ids:
        if model_id not in favorites:
            favorites.append(model_id)

    local_settings["customModels"] = custom_models
    local_settings["modelFavorites"] = favorites
    if "sessionDefaultSettings" in local_settings:
        session_defaults = copy.deepcopy(local_settings.get("sessionDefaultSettings") or {})
    else:
        session_defaults = copy.deepcopy(ctx["settings"].get("sessionDefaultSettings") or {})

    if not ctx["settings"].get("model"):
        local_settings["model"] = model_ids[0]
    if not ctx["settings"].get("reasoningEffort"):
        local_settings["reasoningEffort"] = "medium"
    if not session_defaults.get("model"):
        session_defaults["model"] = model_ids[0]
    if not session_defaults.get("reasoningEffort"):
        session_defaults["reasoningEffort"] = "medium"
    if session_defaults:
        local_settings["sessionDefaultSettings"] = session_defaults

    result = write_local_settings(home, local_settings)
    return {
        "added": added,
        "updated": updated,
        "models": model_ids,
        "path": result["path"],
        "backup_path": result["backup_path"],
    }


def use_model(factory_home, model_id, reasoning=None):
    home = Path(factory_home).expanduser().resolve()
    ctx = load_factory_context(home)
    available_ids = {model["id"] for model in ctx["models"] + ctx["legacy_models"]}
    if model_id not in available_ids:
        raise ValueError(f"Unknown Droid model: {model_id}")

    _, local_settings = _local_settings(home)
    local_settings = copy.deepcopy(local_settings or {})
    local_settings["model"] = model_id
    session_defaults = copy.deepcopy(local_settings.get("sessionDefaultSettings") or {})
    session_defaults["model"] = model_id
    if reasoning is not None:
        local_settings["reasoningEffort"] = reasoning
        session_defaults["reasoningEffort"] = reasoning
    local_settings["sessionDefaultSettings"] = session_defaults

    result = write_local_settings(home, local_settings)
    summary = {
        "model_id": model_id,
        "path": result["path"],
        "backup_path": result["backup_path"],
    }
    if reasoning is not None:
        summary["reasoning"] = reasoning
    return summary


def remove_model(factory_home, model_id):
    home = Path(factory_home).expanduser().resolve()
    ctx = load_factory_context(home)
    local_settings = copy.deepcopy(ctx["local_settings"] or {})
    custom_models = copy.deepcopy(local_settings.get("customModels") or [])
    index = _model_index(custom_models, model_id)

    if index == -1:
        raise ValueError(f"Model {model_id} is not present in settings.local.json")
    if custom_models[index].get("managedBy") != MANAGED_BY:
        raise ValueError(f"Model {model_id} is not managed by {MANAGED_BY}")

    del custom_models[index]
    local_settings["customModels"] = custom_models
    replacement_model_id = custom_models[0]["id"] if custom_models else ""

    favorites = [favorite for favorite in (local_settings.get("modelFavorites") or []) if favorite != model_id]
    if favorites or "modelFavorites" in local_settings:
        local_settings["modelFavorites"] = favorites

    if ctx["settings"].get("model") == model_id:
        local_settings["model"] = replacement_model_id

    session_defaults = copy.deepcopy(local_settings.get("sessionDefaultSettings") or {})
    effective_session_defaults = copy.deepcopy(ctx["settings"].get("sessionDefaultSettings") or {})
    if effective_session_defaults.get("model") == model_id:
        session_defaults["model"] = replacement_model_id
    if session_defaults or "sessionDefaultSettings" in local_settings or effective_session_defaults.get("model") == model_id:
        local_settings["sessionDefaultSettings"] = session_defaults

    result = write_local_settings(home, local_settings)
    return {
        "model_id": model_id,
        "path": result["path"],
        "backup_path": result["backup_path"],
    }

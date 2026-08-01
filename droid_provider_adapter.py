#!/usr/bin/env python3
"""Factory Droid provider settings helpers."""

import copy
import datetime
import json
import os
import re
import shutil
import tempfile
from base64 import b64decode
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
    stripped = strip_jsonc_comments(text.lstrip("\ufeff") if text else text)
    if not stripped.strip():
        return {}
    return json.loads(stripped)


def load_jsonc_file(path):
    path = Path(path)
    if not path.exists():
        return {}
    return loads_jsonc(path.read_text(encoding="utf-8-sig"))


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


def _safe_id(name):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("_")
    return safe or "Provider"


def _strip_toml_inline_comment(value):
    chars = []
    quote = ""
    escaped = False
    for char in value:
        if quote:
            chars.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in ('"', "'"):
            quote = char
            chars.append(char)
            continue
        if char == "#":
            break
        chars.append(char)
    return "".join(chars).strip()


def extract_toml_value(section, key):
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*(.+)$")
    for raw_line in (section or "").splitlines():
        line = raw_line.strip()
        match = pattern.match(line)
        if not match:
            continue
        value = _strip_toml_inline_comment(match.group(1).strip())
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]
        return value
    return ""


def extract_openai_key(profile):
    raw = (profile or {}).get("auth.json", "")
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        decoded = b64decode(raw[4:].encode("ascii")).decode("utf-8") if raw.startswith("b64:") else raw
        payload = json.loads(decoded)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    key = payload.get("OPENAI_API_KEY") or payload.get("api_key") or ""
    return key if isinstance(key, str) else ""


def codex_profile_to_model(name, profile, api_key_env=None, with_key=False):
    profile = profile or {}
    display_name = name or profile.get("model_provider") or profile.get("name") or "Provider"
    safe_name = _safe_id(display_name)
    base_url = extract_toml_value(profile.get("provider_section", ""), "base_url")
    if not base_url:
        raise ValueError(f"Codex provider '{display_name}' has no base_url")

    key_value = extract_openai_key(profile)
    env_name = api_key_env or f"{safe_name.upper().replace('-', '_').replace('.', '_')}_API_KEY"
    model = {
        "id": f"custom:{safe_name}",
        "model": profile.get("model") or "gpt-5",
        "displayName": display_name,
        "baseUrl": base_url,
        "reasoningEffort": profile.get("model_reasoning_effort") or "medium",
        "provider": "openai",
        "apiKey": f"${{{env_name}}}",
        "managedBy": MANAGED_BY,
    }
    if with_key and key_value:
        model["apiKey"] = key_value
    return model


def _same_managed_import_target(model, display_name):
    return (
        isinstance(model, dict)
        and model.get("managedBy") == MANAGED_BY
        and model.get("displayName") == display_name
    )


def _next_available_model_id(models, base_model_id, display_name):
    existing_ids = {
        model.get("id")
        for model in (models or [])
        if isinstance(model, dict) and model.get("id")
    }
    for model in models or []:
        if _same_managed_import_target(model, display_name):
            return model.get("id") or base_model_id
    if base_model_id not in existing_ids:
        return base_model_id

    suffix = 2
    while True:
        candidate = f"{base_model_id}-{suffix}"
        if candidate not in existing_ids:
            return candidate
        suffix += 1


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


def import_codex_provider(factory_home, name, profile, api_key_env=None, with_key=False):
    home = Path(factory_home).expanduser().resolve() if factory_home is not None else FACTORY_DIR
    ctx = load_factory_context(home)
    _, local_settings = _local_settings(home)
    local_settings = copy.deepcopy(local_settings or {})

    custom_models = []
    for source_model in copy.deepcopy(ctx["base_settings"].get("customModels") or []):
        if isinstance(source_model, dict):
            custom_models.append(source_model)
    for source_model in copy.deepcopy(local_settings.get("customModels") or []):
        if not isinstance(source_model, dict):
            continue
        index = _model_index(custom_models, source_model.get("id"))
        if index == -1:
            custom_models.append(source_model)
        else:
            custom_models[index] = source_model

    model = codex_profile_to_model(name, profile, api_key_env=api_key_env, with_key=with_key)
    model["id"] = _next_available_model_id(custom_models, model["id"], model["displayName"])
    index = _model_index(custom_models, model["id"])
    added = 0
    updated = 0
    if index == -1:
        custom_models.append(copy.deepcopy(model))
        added = 1
    elif custom_models[index] != model:
        custom_models[index] = copy.deepcopy(model)
        updated = 1

    local_settings["customModels"] = custom_models

    result = write_local_settings(home, local_settings)
    return {
        "added": added,
        "updated": updated,
        "model_id": model["id"],
        "displayName": model["displayName"],
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

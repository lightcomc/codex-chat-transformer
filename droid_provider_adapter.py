#!/usr/bin/env python3
"""Factory Droid provider settings helpers."""

import copy
import json
import os
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


def merge_settings(base, local):
    merged = copy.deepcopy(base or {})
    for key, value in (local or {}).items():
        merged[key] = copy.deepcopy(value)
    return merged


def normalize_current_model(raw, source):
    if not isinstance(raw, dict):
        return None

    model_id = raw.get("id") or raw.get("model")
    model_name = raw.get("model") or raw.get("id")
    if not model_id or not model_name:
        return None

    normalized = {
        "id": str(model_id),
        "model": str(model_name),
        "displayName": raw.get("displayName") or str(model_id),
        "baseUrl": raw.get("baseUrl") or "",
        "provider": raw.get("provider") or "",
        "apiKey": raw.get("apiKey") or "",
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
            "settings": str(settings_file),
            "settings_local": str(local_file),
            "legacy_config": str(legacy_file),
        },
    }

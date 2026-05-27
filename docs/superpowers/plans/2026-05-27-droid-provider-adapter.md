# Droid Provider Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stdlib-only Factory Droid provider/model management while preserving existing Factory settings and legacy BYOK config.

**Architecture:** Add a focused `droid_provider_adapter.py` module for Factory paths, JSONC parsing, model normalization, and safe writes to `settings.local.json`. Keep `codex_chat_transformer.py` as the CLI orchestrator and operation-history source. Extend `test_smoke.py` because the repo currently uses one smoke suite instead of a separate test package.

**Tech Stack:** Python stdlib (`argparse`, `json`, `pathlib`, `shutil`, `datetime`, `re`), existing provider/profile helpers, existing smoke runner.

---

## File Structure

- Create `droid_provider_adapter.py`
  - Owns Factory home/settings paths, JSONC load, safe backup/write, effective model read, model mutation helpers, NeuroGate templates, and Codex-profile mapping.
- Modify `codex_chat_transformer.py`
  - Adds Droid CLI flags and prints summaries.
  - Calls existing `record_history()` with redacted details.
  - Does not import Droid module until a Droid command is used.
- Modify `test_smoke.py`
  - Adds focused tests for JSONC parsing, merge behavior, legacy reads, idempotent NeuroGate bootstrap, Codex provider mapping, remove/use operations, and secret redaction.
  - Adds `py_compile` check for the new module.
- Modify `README.md`, `README.ru.md`, `README.zh.md`, `CHANGELOG.md`
  - Documents only the new Droid flags and safety behavior.

---

### Task 1: Core Droid Settings Reader

**Files:**
- Create: `droid_provider_adapter.py`
- Modify: `test_smoke.py`

- [ ] **Step 1: Write failing tests for JSONC and effective settings**

Add imports near the top of `test_smoke.py`:

```python
import droid_provider_adapter as droid
```

Add tests after the existing operation-history tests:

```python
def test_droid_jsonc_parser_respects_strings():
    text = '''
    // top comment
    {
      "url": "https://example.invalid//not-comment",
      "pattern": "/* not a block */",
      /* block comment */
      "customModels": [{"id": "custom:a", "model": "gpt-5"}]
    }
    '''
    data = droid.loads_jsonc(text)
    assert data["url"].endswith("//not-comment")
    assert data["pattern"] == "/* not a block */"
    assert data["customModels"][0]["id"] == "custom:a"


def test_droid_effective_settings_merges_local_over_base():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "settings.json").write_text(
            '{"model": "base", "customModels": [{"id": "custom:base", "model": "base"}]}',
            encoding="utf-8",
        )
        (home / "settings.local.json").write_text(
            '{"model": "local", "customModels": [{"id": "custom:local", "model": "local"}]}',
            encoding="utf-8",
        )
        ctx = droid.load_factory_context(home)
        assert ctx["settings"]["model"] == "local"
        ids = [m["id"] for m in ctx["models"]]
        assert ids == ["custom:local"], f"local customModels should override base: {ids}"
        assert ctx["sources"]["settings_local"].endswith("settings.local.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python test_smoke.py
```

Expected: failure because `droid_provider_adapter` does not exist.

- [ ] **Step 3: Implement JSONC parser and context loader**

Create `droid_provider_adapter.py` with:

```python
#!/usr/bin/env python3
"""Factory Droid provider/model settings helpers."""

import copy
import datetime
import json
import os
import re
import shutil
from pathlib import Path

FACTORY_DIR = Path(os.environ.get("FACTORY_HOME", Path.home() / ".factory"))
SETTINGS_NAME = "settings.json"
LOCAL_SETTINGS_NAME = "settings.local.json"
LEGACY_CONFIG_NAME = "config.json"
MANAGED_BY = "codex-provider-manager"


def factory_home_from_settings(settings_path=None):
    if settings_path:
        return Path(settings_path).expanduser().resolve().parent
    return FACTORY_DIR


def strip_jsonc_comments(text):
    out = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2 if i + 1 < len(text) else 0
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def loads_jsonc(text):
    stripped = strip_jsonc_comments(text or "")
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
    if not model_id:
        return None
    return {
        "id": str(model_id),
        "model": raw.get("model", ""),
        "displayName": raw.get("displayName") or raw.get("model_display_name") or str(model_id),
        "baseUrl": raw.get("baseUrl") or raw.get("base_url", ""),
        "provider": raw.get("provider", ""),
        "apiKey": raw.get("apiKey") or raw.get("api_key", ""),
        "reasoningEffort": raw.get("reasoningEffort", ""),
        "source": source,
        "managed": raw.get("managedBy") == MANAGED_BY,
        "raw": raw,
    }


def normalize_legacy_model(raw):
    if not isinstance(raw, dict):
        return None
    model = raw.get("model", "")
    if not model:
        return None
    item = dict(raw)
    item.setdefault("id", "custom:" + str(model))
    item.setdefault("displayName", raw.get("model_display_name", model))
    item.setdefault("baseUrl", raw.get("base_url", ""))
    item.setdefault("apiKey", raw.get("api_key", ""))
    return normalize_current_model(item, "config.json")


def load_factory_context(factory_home=None, settings_path=None):
    home = Path(factory_home) if factory_home else factory_home_from_settings(settings_path)
    settings_file = Path(settings_path) if settings_path else home / SETTINGS_NAME
    local_file = settings_file.with_name(LOCAL_SETTINGS_NAME)
    legacy_file = home / LEGACY_CONFIG_NAME
    base = load_jsonc_file(settings_file)
    local = load_jsonc_file(local_file)
    settings = merge_settings(base, local)
    current_models = []
    for raw in settings.get("customModels", []) or []:
        model = normalize_current_model(raw, "settings.local.json" if local_file.exists() else "settings.json")
        if model:
            current_models.append(model)
    legacy = load_jsonc_file(legacy_file)
    legacy_models = []
    for raw in legacy.get("custom_models", []) or []:
        model = normalize_legacy_model(raw)
        if model:
            legacy_models.append(model)
    return {
        "home": str(home),
        "settings_path": str(settings_file),
        "local_settings_path": str(local_file),
        "legacy_config_path": str(legacy_file),
        "settings": settings,
        "base_settings": base,
        "local_settings": local,
        "models": current_models,
        "legacy_models": legacy_models,
        "sources": {
            "settings": str(settings_file) if settings_file.exists() else "",
            "settings_local": str(local_file) if local_file.exists() else "",
            "legacy_config": str(legacy_file) if legacy_file.exists() else "",
        },
    }
```

- [ ] **Step 4: Run tests to verify Task 1 passes**

Run:

```powershell
python test_smoke.py
```

Expected: all previous tests pass plus the new Droid JSONC tests.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -f droid_provider_adapter.py test_smoke.py
git commit -m "feat: read Droid settings safely"
```

---

### Task 2: Droid Model Mutation Helpers

**Files:**
- Modify: `droid_provider_adapter.py`
- Modify: `test_smoke.py`

- [ ] **Step 1: Write failing tests for NeuroGate, use, remove, and backups**

Add:

```python
def test_droid_add_neurogate_is_idempotent_and_uses_env_key():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        summary1 = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        summary2 = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        ctx = droid.load_factory_context(home)
        ids = [m["id"] for m in ctx["models"]]
        assert ids.count("custom:NeuroGate-GPT-5.5-1") == 1
        assert summary1["added"] == 3
        assert summary2["added"] == 0
        assert ctx["settings"]["model"] == "custom:NeuroGate-GPT-5.5-1"
        raw = (home / "settings.local.json").read_text(encoding="utf-8")
        assert "${NEUROGATE_API_KEY}" in raw
        assert summary1["backup_path"].exists(), "write should create a backup"


def test_droid_use_model_updates_top_level_and_session_defaults():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        droid.add_neurogate_models(home)
        summary = droid.use_model(home, "custom:NeuroGate-GPT-5.4-2", reasoning="high")
        ctx = droid.load_factory_context(home)
        assert summary["model_id"] == "custom:NeuroGate-GPT-5.4-2"
        assert ctx["settings"]["model"] == "custom:NeuroGate-GPT-5.4-2"
        assert ctx["settings"]["reasoningEffort"] == "high"
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:NeuroGate-GPT-5.4-2"
        assert ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "high"


def test_droid_remove_model_only_removes_local_managed_model():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "settings.json").write_text(
            '{"customModels": [{"id": "custom:base", "model": "base"}]}',
            encoding="utf-8",
        )
        droid.add_neurogate_models(home)
        summary = droid.remove_model(home, "custom:NeuroGate-GPT-5.4-2")
        ctx = droid.load_factory_context(home)
        assert summary["removed"] == 1
        assert "custom:NeuroGate-GPT-5.4-2" not in [m["id"] for m in ctx["models"]]
        try:
            droid.remove_model(home, "custom:base")
        except ValueError as exc:
            assert "settings.local.json" in str(exc)
        else:
            raise AssertionError("base settings model should not be removed by local-only remover")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python test_smoke.py
```

Expected: failures for missing `add_neurogate_models`, `use_model`, and `remove_model`.

- [ ] **Step 3: Implement safe write and mutation helpers**

Add to `droid_provider_adapter.py`:

```python
def backup_file(path):
    path = Path(path)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(path.name + ".bak-" + timestamp)
    if path.exists():
        shutil.copy2(str(path), str(backup))
    else:
        backup.write_text("", encoding="utf-8")
    return backup


def write_local_settings(home, data):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    path = home / LOCAL_SETTINGS_NAME
    backup = backup_file(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(path), "backup_path": str(backup)}


def _local_settings(home):
    return load_jsonc_file(Path(home) / LOCAL_SETTINGS_NAME)


def _model_index(models, model_id):
    for idx, item in enumerate(models):
        if item.get("id") == model_id:
            return idx
    return None


def neurogate_models(api_key_env="NEUROGATE_API_KEY", api_key=None):
    key_value = api_key if api_key else "${" + api_key_env + "}"
    return [
        {
            "model": "gpt-5.5",
            "id": "custom:NeuroGate-GPT-5.5-1",
            "index": 1,
            "baseUrl": "https://api.neurogate.space/v1",
            "displayName": "NeuroGate GPT-5.5",
            "maxOutputTokens": 128000,
            "reasoningEffort": "medium",
            "noImageSupport": False,
            "provider": "openai",
            "apiKey": key_value,
            "managedBy": MANAGED_BY,
        },
        {
            "model": "gpt-5.4",
            "id": "custom:NeuroGate-GPT-5.4-2",
            "index": 2,
            "baseUrl": "https://api.neurogate.space/v1",
            "displayName": "NeuroGate GPT-5.4",
            "maxOutputTokens": 128000,
            "reasoningEffort": "medium",
            "noImageSupport": False,
            "provider": "openai",
            "apiKey": key_value,
            "managedBy": MANAGED_BY,
        },
        {
            "model": "gpt-5.4-mini",
            "id": "custom:NeuroGate-GPT-5.4-Mini-3",
            "index": 3,
            "baseUrl": "https://api.neurogate.space/v1",
            "displayName": "NeuroGate GPT-5.4 Mini",
            "maxOutputTokens": 128000,
            "reasoningEffort": "medium",
            "noImageSupport": False,
            "provider": "openai",
            "apiKey": key_value,
            "managedBy": MANAGED_BY,
        },
    ]


def add_neurogate_models(factory_home=None, api_key_env="NEUROGATE_API_KEY", api_key=None):
    home = Path(factory_home) if factory_home else FACTORY_DIR
    ctx = load_factory_context(home)
    local = _local_settings(home)
    models = []
    for item in (ctx["base_settings"].get("customModels", []) or []):
        models.append(copy.deepcopy(item))
    for item in (local.get("customModels", []) or []):
        idx = _model_index(models, item.get("id"))
        if idx is None:
            models.append(copy.deepcopy(item))
        else:
            models[idx] = copy.deepcopy(item)
    added = 0
    updated = 0
    for model in neurogate_models(api_key_env=api_key_env, api_key=api_key):
        idx = _model_index(models, model["id"])
        if idx is None:
            models.append(model)
            added += 1
        elif models[idx] != model:
            models[idx] = model
            updated += 1
    local["customModels"] = models
    existing_favorites = list(local.get("modelFavorites", []) or [])
    local["modelFavorites"] = []
    for fav in (ctx["base_settings"].get("modelFavorites", []) or []):
        if fav not in local["modelFavorites"]:
            local["modelFavorites"].append(fav)
    for fav in existing_favorites:
        if fav not in local["modelFavorites"]:
            local["modelFavorites"].append(fav)
    for fav in ("custom:NeuroGate-GPT-5.5-1", "custom:NeuroGate-GPT-5.4-2", "custom:NeuroGate-GPT-5.4-Mini-3"):
        if fav not in local["modelFavorites"]:
            local["modelFavorites"].append(fav)
    effective = ctx["settings"]
    if not effective.get("model"):
        local["model"] = "custom:NeuroGate-GPT-5.5-1"
    if not effective.get("reasoningEffort"):
        local["reasoningEffort"] = "medium"
    defaults = dict(effective.get("sessionDefaultSettings", {}) or {})
    defaults.setdefault("model", "custom:NeuroGate-GPT-5.5-1")
    defaults.setdefault("reasoningEffort", "medium")
    local["sessionDefaultSettings"] = defaults
    write = write_local_settings(home, local)
    return {"added": added, "updated": updated, "models": [m["id"] for m in neurogate_models()], **write}


def use_model(factory_home, model_id, reasoning=None):
    home = Path(factory_home) if factory_home else FACTORY_DIR
    ctx = load_factory_context(home)
    known_ids = {m["id"] for m in ctx["models"]} | {m["id"] for m in ctx["legacy_models"]}
    if model_id not in known_ids:
        raise ValueError(f"Droid model not found: {model_id}")
    local = _local_settings(home)
    local["model"] = model_id
    if reasoning:
        local["reasoningEffort"] = reasoning
    defaults = dict(local.get("sessionDefaultSettings", {}) or {})
    defaults["model"] = model_id
    if reasoning:
        defaults["reasoningEffort"] = reasoning
    local["sessionDefaultSettings"] = defaults
    write = write_local_settings(home, local)
    return {"model_id": model_id, "reasoning": reasoning or local.get("reasoningEffort", ""), **write}


def remove_model(factory_home, model_id):
    home = Path(factory_home) if factory_home else FACTORY_DIR
    local = _local_settings(home)
    models = list(local.get("customModels", []) or [])
    idx = _model_index(models, model_id)
    if idx is None:
        raise ValueError(f"Model is not managed in settings.local.json: {model_id}")
    removed = models.pop(idx)
    local["customModels"] = models
    favorites = [fav for fav in (local.get("modelFavorites", []) or []) if fav != model_id]
    local["modelFavorites"] = favorites
    if local.get("model") == model_id:
        local.pop("model", None)
    if (local.get("sessionDefaultSettings") or {}).get("model") == model_id:
        local["sessionDefaultSettings"].pop("model", None)
    write = write_local_settings(home, local)
    return {"removed": 1, "model_id": model_id, "displayName": removed.get("displayName", ""), **write}
```

- [ ] **Step 4: Run tests to verify Task 2 passes**

Run:

```powershell
python test_smoke.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -f droid_provider_adapter.py test_smoke.py
git commit -m "feat: manage Droid local models"
```

---

### Task 3: Codex Provider to Droid Mapping

**Files:**
- Modify: `droid_provider_adapter.py`
- Modify: `test_smoke.py`

- [ ] **Step 1: Write failing tests for provider import and direct-key gating**

Add:

```python
def test_droid_import_codex_provider_defaults_to_env_key():
    profile = {
        "model_provider": "My Provider",
        "model": "gpt-5.5",
        "model_reasoning_effort": "medium",
        "provider_section": '[model_providers.My_Provider]\nname = "My Provider"\nbase_url = "https://api.example.invalid/v1"\nwire_api = "responses"',
        "auth.json": ct._encode_secret(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-hidden"})),
    }
    with tempfile.TemporaryDirectory() as td:
        summary = droid.import_codex_provider(Path(td), "My Provider", profile, api_key_env="MY_PROVIDER_API_KEY")
        raw = (Path(td) / "settings.local.json").read_text(encoding="utf-8")
        ctx = droid.load_factory_context(Path(td))
        model = ctx["models"][0]
        assert summary["model_id"] == "custom:My_Provider"
        assert model["baseUrl"] == "https://api.example.invalid/v1"
        assert model["model"] == "gpt-5.5"
        assert "${MY_PROVIDER_API_KEY}" in raw
        assert "sk-hidden" not in raw


def test_droid_import_codex_provider_can_write_key_when_allowed():
    profile = {
        "model_provider": "KeyProv",
        "model": "gpt-5",
        "provider_section": '[model_providers.KeyProv]\nname = "KeyProv"\nbase_url = "https://key.invalid/v1"',
        "auth.json": ct._encode_secret(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-real"})),
    }
    with tempfile.TemporaryDirectory() as td:
        droid.import_codex_provider(Path(td), "KeyProv", profile, with_key=True)
        raw = (Path(td) / "settings.local.json").read_text(encoding="utf-8")
        assert "sk-real" in raw
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python test_smoke.py
```

Expected: failure because `import_codex_provider` is missing.

- [ ] **Step 3: Implement mapping helpers**

Add to `droid_provider_adapter.py`:

```python
def _safe_id(name):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("_")
    return safe or "Provider"


def extract_toml_value(section, key):
    prefix = key + " ="
    for line in (section or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                return value[1:-1]
            return value
    return ""


def extract_openai_key(profile):
    raw = profile.get("auth.json", "")
    if not raw:
        return ""
    if raw.startswith("b64:"):
        try:
            raw = json.loads(json.dumps(raw))
        except Exception:
            pass
    try:
        if raw.startswith("b64:"):
            import base64
            decoded = base64.b64decode(raw[4:].encode("ascii")).decode("utf-8")
        else:
            decoded = raw
        data = json.loads(decoded)
    except Exception:
        return ""
    return data.get("OPENAI_API_KEY", "") or data.get("api_key", "")


def codex_profile_to_model(name, profile, api_key_env=None, with_key=False):
    section = profile.get("provider_section", "")
    safe = _safe_id(name or profile.get("model_provider") or profile.get("name"))
    model_id = "custom:" + safe
    base_url = extract_toml_value(section, "base_url")
    if not base_url:
        raise ValueError(f"Codex provider '{name}' has no base_url")
    api_key = extract_openai_key(profile) if with_key else ""
    env_name = api_key_env or (safe.upper().replace("-", "_").replace(".", "_") + "_API_KEY")
    return {
        "model": profile.get("model", "gpt-5"),
        "id": model_id,
        "baseUrl": base_url,
        "displayName": name,
        "reasoningEffort": profile.get("model_reasoning_effort") or "medium",
        "provider": "openai",
        "apiKey": api_key if with_key and api_key else "${" + env_name + "}",
        "managedBy": MANAGED_BY,
    }


def import_codex_provider(factory_home, name, profile, api_key_env=None, with_key=False):
    home = Path(factory_home) if factory_home else FACTORY_DIR
    model = codex_profile_to_model(name, profile, api_key_env=api_key_env, with_key=with_key)
    local = _local_settings(home)
    models = list(local.get("customModels", []) or [])
    idx = _model_index(models, model["id"])
    added = 0
    updated = 0
    if idx is None:
        models.append(model)
        added = 1
    else:
        models[idx] = model
        updated = 1
    local["customModels"] = models
    write = write_local_settings(home, local)
    return {"added": added, "updated": updated, "model_id": model["id"], "displayName": model["displayName"], **write}
```

- [ ] **Step 4: Run tests to verify Task 3 passes**

Run:

```powershell
python test_smoke.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -f droid_provider_adapter.py test_smoke.py
git commit -m "feat: import Codex providers into Droid"
```

---

### Task 4: CLI Integration and History

**Files:**
- Modify: `codex_chat_transformer.py`
- Modify: `test_smoke.py`

- [ ] **Step 1: Write failing CLI/history tests**

Add:

```python
def test_droid_cli_flags_registered():
    text = Path("codex_chat_transformer.py").read_text(encoding="utf-8")
    for flag in (
        "--droid-models",
        "--droid-doctor",
        "--droid-add-neurogate",
        "--droid-import-provider",
        "--droid-use",
        "--droid-remove-model",
        "--droid-settings",
        "--droid-with-key",
        "--droid-api-key-env",
    ):
        assert flag in text, f"missing CLI flag {flag}"


def test_droid_history_redacts_key():
    original, tmp_dir = setup_temp_codex_home()
    try:
        ct.record_history("droid_model_added", api_key="sk-droid-secret", model_id="custom:x")
        raw = (tmp_dir / "operation_history.jsonl").read_text(encoding="utf-8")
        assert "sk-droid-secret" not in raw
        assert "custom:x" in raw
    finally:
        restore_temp_codex_home(original, tmp_dir)
```

- [ ] **Step 2: Run tests to verify CLI flag test fails**

Run:

```powershell
python test_smoke.py
```

Expected: missing Droid CLI flags.

- [ ] **Step 3: Add parser flags and command handlers**

In `main()` parser setup, add:

```python
    parser.add_argument("--droid-models", action="store_true", help="List Factory Droid custom models and active model")
    parser.add_argument("--droid-doctor", action="store_true", help="Validate Factory Droid provider/model settings")
    parser.add_argument("--droid-add-neurogate", action="store_true", help="Add NeuroGate models to Droid settings.local.json")
    parser.add_argument("--droid-import-provider", metavar="NAME", help="Import a saved Codex provider profile into Droid")
    parser.add_argument("--droid-use", metavar="MODEL_ID", help="Set the active Droid model")
    parser.add_argument("--droid-remove-model", metavar="MODEL_ID", help="Remove a managed Droid model from settings.local.json")
    parser.add_argument("--droid-settings", metavar="PATH", help="Override Factory Droid settings.json path")
    parser.add_argument("--droid-with-key", action="store_true", help="Allow writing a direct API key into Droid settings")
    parser.add_argument("--droid-api-key-env", metavar="VAR", help="Environment variable name to reference for Droid apiKey")
```

After pack/search/history handling and before Codex provider commands, add:

```python
    if any([args.droid_models, args.droid_doctor, args.droid_add_neurogate,
            args.droid_import_provider, args.droid_use, args.droid_remove_model]):
        handle_droid_command(args)
        return
```

Add helper functions before `main()`:

```python
def _droid_home_from_args(args):
    import droid_provider_adapter as droid
    return droid.factory_home_from_settings(args.droid_settings)


def _print_droid_models(ctx):
    print("\n=== Droid Models ===\n")
    print(f"Factory home: {ctx['home']}")
    print(f"Active model: {ctx['settings'].get('model', '(not set)')}")
    print(f"Favorites: {', '.join(ctx['settings'].get('modelFavorites', []) or []) or '(none)'}")
    print("\nCurrent customModels:")
    if not ctx["models"]:
        print("  (none)")
    for model in ctx["models"]:
        key_state = "yes" if model.get("apiKey") else "no"
        print(f"  {model['id']} | {model['displayName']} | {model['model']} | {model['baseUrl']} | key={key_state} | source={model['source']}")
    if ctx["legacy_models"]:
        print("\nLegacy config.json custom_models:")
        for model in ctx["legacy_models"]:
            key_state = "yes" if model.get("apiKey") else "no"
            print(f"  {model['id']} | {model['displayName']} | {model['model']} | {model['baseUrl']} | key={key_state}")


def _droid_doctor_report(ctx):
    issues = []
    ids = {}
    for model in ctx["models"]:
        ids.setdefault(model["id"], 0)
        ids[model["id"]] += 1
        if not model.get("baseUrl"):
            issues.append(f"{model['id']}: missing baseUrl")
        if not model.get("apiKey"):
            issues.append(f"{model['id']}: missing apiKey")
    duplicates = sorted(k for k, count in ids.items() if count > 1)
    for model_id in duplicates:
        issues.append(f"{model_id}: duplicate custom model id")
    return {"ok": not issues, "issues": issues, "model_count": len(ctx["models"]), "legacy_count": len(ctx["legacy_models"])}


def _print_droid_doctor(report):
    print("\n=== Droid Doctor ===\n")
    print(f"Current models: {report['model_count']}")
    print(f"Legacy models: {report['legacy_count']}")
    if report["ok"]:
        print("OK: Droid provider settings look usable.")
    else:
        print("Issues:")
        for issue in report["issues"]:
            print(f"  - {issue}")


def handle_droid_command(args):
    import droid_provider_adapter as droid
    home = _droid_home_from_args(args)
    if args.droid_models:
        ctx = droid.load_factory_context(home)
        _print_droid_models(ctx)
        return
    if args.droid_doctor:
        ctx = droid.load_factory_context(home)
        report = _droid_doctor_report(ctx)
        _print_droid_doctor(report)
        record_history("droid_doctor_checked", details={"ok": report["ok"], "model_count": report["model_count"], "legacy_count": report["legacy_count"]})
        return
    if args.droid_add_neurogate:
        summary = droid.add_neurogate_models(home, api_key_env=args.droid_api_key_env or "NEUROGATE_API_KEY", api_key=args.api_key if args.droid_with_key else None)
        print(f"Added/updated NeuroGate Droid models: added={summary['added']}, updated={summary['updated']}")
        print(f"Wrote: {summary['path']}")
        record_history("droid_model_added", details={"models": summary["models"], "path": summary["path"]})
        return
    if args.droid_import_provider:
        data = _load_providers()
        profile = data.get("profiles", {}).get(args.droid_import_provider)
        if not profile:
            print(f"ERROR: Provider not found: {args.droid_import_provider}")
            return
        summary = droid.import_codex_provider(home, args.droid_import_provider, profile, api_key_env=args.droid_api_key_env, with_key=args.droid_with_key)
        print(f"Imported Codex provider into Droid: {summary['model_id']}")
        print(f"Wrote: {summary['path']}")
        record_history("droid_provider_imported", provider=args.droid_import_provider, details={"model_id": summary["model_id"], "path": summary["path"]})
        return
    if args.droid_use:
        summary = droid.use_model(home, args.droid_use, reasoning=args.set_reasoning)
        print(f"Droid active model: {summary['model_id']}")
        record_history("droid_model_selected", details={"model_id": summary["model_id"], "reasoning": summary.get("reasoning", "")})
        return
    if args.droid_remove_model:
        summary = droid.remove_model(home, args.droid_remove_model)
        print(f"Removed Droid model: {summary['model_id']}")
        record_history("droid_model_removed", details={"model_id": summary["model_id"]})
        return
```

- [ ] **Step 4: Run tests to verify Task 4 passes**

Run:

```powershell
python test_smoke.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

```powershell
git add codex_chat_transformer.py test_smoke.py
git commit -m "feat: expose Droid provider CLI"
```

---

### Task 5: Docs and End-to-End Verification

**Files:**
- Modify: `README.md`
- Modify: `README.ru.md`
- Modify: `README.zh.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document the Droid commands**

Add a short section near provider management docs:

```markdown
### Factory Droid Models

The tool can also manage Factory Droid custom models without touching Factory auth files or rewriting the commented `~/.factory/settings.json`.

```bash
python codex_chat_transformer.py --droid-models
python codex_chat_transformer.py --droid-doctor
python codex_chat_transformer.py --droid-add-neurogate
python codex_chat_transformer.py --droid-use custom:NeuroGate-GPT-5.5-1 --set-reasoning medium
python codex_chat_transformer.py --droid-import-provider OpenRouter --droid-api-key-env OPENROUTER_API_KEY
python codex_chat_transformer.py --droid-remove-model custom:OpenRouter
```

New Droid writes go to `~/.factory/settings.local.json`. Existing `~/.factory/settings.json`, legacy `~/.factory/config.json`, and Factory auth files remain untouched. By default API keys are written as environment variable references such as `${NEUROGATE_API_KEY}`; direct key writes require `--droid-with-key --api-key ...`.
```

Add equivalent short sections to `README.ru.md` and `README.zh.md`. Add one bullet to `CHANGELOG.md` under the latest unreleased/current section.

- [ ] **Step 2: Compile and smoke test**

Run:

```powershell
python -m py_compile codex_chat_transformer.py codex_sync.py droid_provider_adapter.py test_smoke.py
python test_smoke.py
git diff --check
```

Expected:

- `py_compile` exits 0.
- smoke suite exits 0.
- `git diff --check` exits 0.

- [ ] **Step 3: Local Droid dry run in a temp Factory home**

Run:

```powershell
$tmp = Join-Path $env:TEMP ("factory-droid-test-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force $tmp | Out-Null
'{"model":"base","customModels":[]}' | Set-Content -Encoding UTF8 (Join-Path $tmp "settings.json")
python codex_chat_transformer.py --droid-add-neurogate --droid-settings (Join-Path $tmp "settings.json")
python codex_chat_transformer.py --droid-models --droid-settings (Join-Path $tmp "settings.json")
python codex_chat_transformer.py --droid-use custom:NeuroGate-GPT-5.4-2 --set-reasoning high --droid-settings (Join-Path $tmp "settings.json")
python codex_chat_transformer.py --droid-doctor --droid-settings (Join-Path $tmp "settings.json")
Remove-Item -Recurse -Force $tmp
```

Expected:

- Commands write only `settings.local.json` in the temp Factory home.
- Listed models include the three NeuroGate IDs.
- Active model changes to `custom:NeuroGate-GPT-5.4-2`.
- No API key value is printed.

- [ ] **Step 4: Commit docs and verification-ready state**

```powershell
git add README.md README.ru.md README.zh.md CHANGELOG.md
git commit -m "docs: document Droid provider management"
```

---

## Self-Review Checklist

- The plan covers JSONC parsing, local overrides, legacy `config.json` read support, NeuroGate bootstrap, Codex provider import, active model selection, local-only removal, history, docs, and verification.
- No step mutates `C:\Users\test\.factory`; tests and dry runs use temp Factory homes.
- No step writes Factory auth files or legacy `config.json`.
- Direct API key writes are gated by `--droid-with-key`.
- The smoke suite remains the source of truth for regression testing.

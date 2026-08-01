#!/usr/bin/env python3
"""Smoke tests for Codex Chat Transformer."""

import argparse
import ast
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import codex_chat_transformer as ct
import droid_provider_adapter as droid
import py_compile

PASSED = 0
FAILED = 0


def test(name, fn):
    global PASSED, FAILED
    try:
        fn()
        print(f"  PASS  {name}")
        PASSED += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        FAILED += 1


test.__test__ = False


def setup_temp_providers():
    """Create a temporary providers.json, return (original_path, temp_path)."""
    orig = ct.PROVIDERS_FILE
    tmp = Path(tempfile.mktemp(suffix=".json"))
    ct.PROVIDERS_FILE = tmp
    return orig, tmp


def restore_providers(orig, tmp):
    ct.PROVIDERS_FILE = orig
    if tmp.exists():
        tmp.unlink()


def setup_temp_codex_home():
    import codex_sync

    tmp_dir = Path(tempfile.mkdtemp())
    (tmp_dir / ".codex-global-state.json").write_text(
        json.dumps({"pinned-thread-ids": []}),
        encoding="utf-8",
    )
    original = {
        "ct": {
            "CODEX_DIR": ct.CODEX_DIR,
            "STATE_DB": ct.STATE_DB,
            "GLOBAL_STATE": ct.GLOBAL_STATE,
            "PROVIDERS_FILE": ct.PROVIDERS_FILE,
            "SESSIONS_DIR": ct.SESSIONS_DIR,
            "ARCHIVED_DIR": ct.ARCHIVED_DIR,
        },
        "sync": {
            "CODEX_DIR": codex_sync.CODEX_DIR,
            "STATE_DB": codex_sync.STATE_DB,
            "PROVIDERS_FILE": codex_sync.PROVIDERS_FILE,
            "SESSIONS_DIR": codex_sync.SESSIONS_DIR,
        },
    }

    ct.CODEX_DIR = tmp_dir
    ct.STATE_DB = tmp_dir / "state_5.sqlite"
    ct.GLOBAL_STATE = tmp_dir / ".codex-global-state.json"
    ct.PROVIDERS_FILE = tmp_dir / "providers.json"
    ct.SESSIONS_DIR = tmp_dir / "sessions"
    ct.ARCHIVED_DIR = tmp_dir / "archived_sessions"

    codex_sync.CODEX_DIR = tmp_dir
    codex_sync.STATE_DB = ct.STATE_DB
    codex_sync.PROVIDERS_FILE = ct.PROVIDERS_FILE
    codex_sync.SESSIONS_DIR = ct.SESSIONS_DIR
    return original, tmp_dir


def restore_temp_codex_home(original, tmp_dir):
    import codex_sync
    import gc
    import shutil
    import time

    ct.CODEX_DIR = original["ct"]["CODEX_DIR"]
    ct.STATE_DB = original["ct"]["STATE_DB"]
    ct.GLOBAL_STATE = original["ct"]["GLOBAL_STATE"]
    ct.PROVIDERS_FILE = original["ct"]["PROVIDERS_FILE"]
    ct.SESSIONS_DIR = original["ct"]["SESSIONS_DIR"]
    ct.ARCHIVED_DIR = original["ct"]["ARCHIVED_DIR"]

    codex_sync.CODEX_DIR = original["sync"]["CODEX_DIR"]
    codex_sync.STATE_DB = original["sync"]["STATE_DB"]
    codex_sync.PROVIDERS_FILE = original["sync"]["PROVIDERS_FILE"]
    codex_sync.SESSIONS_DIR = original["sync"]["SESSIONS_DIR"]
    for attempt in range(5):
        try:
            shutil.rmtree(tmp_dir)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.1 * (attempt + 1))
    shutil.rmtree(tmp_dir)


def create_temp_threads_db():
    import sqlite3

    conn = sqlite3.connect(str(ct.STATE_DB))
    _create_current_threads_schema(conn)
    conn.commit()
    conn.close()


def store_temp_session(session_id, title, cwd, jsonl_text="", **extra):
    import base64
    import codex_sync

    meta = {
        "id": session_id,
        "model_provider": extra.pop("model_provider", "openai"),
        "model": extra.pop("model", "gpt-5"),
        "title": title,
        "created_at_ms": extra.pop("created_at_ms", 1700000000000),
        "updated_at_ms": extra.pop("updated_at_ms", 1700000001000),
        "archived": extra.pop("archived", False),
        "source": extra.pop("source", "cli"),
        "cwd": cwd,
        "git_branch": extra.pop("git_branch", "main"),
        "git_sha": extra.pop("git_sha", "a" * 40),
        "git_origin_url": extra.pop("git_origin_url", "https://example.invalid/repo.git"),
        "sandbox_policy": extra.pop("sandbox_policy", "{}"),
        "approval_mode": extra.pop("approval_mode", "never"),
        "has_user_event": extra.pop("has_user_event", 1),
        "first_user_message": extra.pop("first_user_message", ""),
        "preview": extra.pop("preview", ""),
        "reasoning_effort": extra.pop("reasoning_effort", None),
    }
    meta.update(extra)
    jsonl_b64 = base64.b64encode(jsonl_text.encode("utf-8")).decode("ascii") if jsonl_text else ""
    return codex_sync._store_session(meta, jsonl_b64)


# --- Tests ---

def test_gui_syntax():
    py_compile.compile(
        str(Path(__file__).parent / "codex_manager_gui.py"), doraise=True
    )


def test_gui_chat_bridge_controls_are_wired():
    text = (Path(__file__).parent / "codex_manager_gui.py").read_text(encoding="utf-8")
    required = [
        "import chat_bridge",
        "import droid_provider_adapter as droid",
        '"chat_bridge"',
        '"chat_refresh"',
        '"droid_to_codex"',
        '"codex_to_droid"',
        '"chat_fresh_timestamps"',
        '"chat_skip_system"',
        '"chat_compaction_mode"',
        '"chat_mirror_plan"',
        '"chat_pin_old"',
        "self.chat_droid_combo",
        "self.chat_codex_combo",
        "self.chat_skip_system_var",
        "self.chk_chat_skip_system",
        "self.chat_compaction_mode_var",
        "self.chat_compaction_mode_combo",
        "self.btn_chat_mirror_plan",
        "include_system=not skip_system",
        "compaction_mode=compaction_mode",
        "build_mirror_plan",
        "select_mirror_actions",
        "def _refresh_chat_bridge_sessions",
        "def _refresh_chat_bridge_sessions_thread",
        "def _apply_chat_bridge_sessions",
        "def _chat_droid_to_codex",
        "def _chat_codex_to_droid",
        "def _chat_mirror_plan",
        "def _chat_transfer_thread",
    ]
    for needle in required:
        assert needle in text, f"GUI Chat Bridge wiring missing: {needle}"


def test_gui_chat_bridge_display_keys_remain_unique():
    import codex_manager_gui as gui

    taken = set()
    first = gui._unique_chat_display("same label", "session-a", taken)
    taken.add(first)
    second = gui._unique_chat_display("same label", "session-b", taken)
    assert first != second, "duplicate rendered labels must not overwrite combobox mappings"
    assert second.endswith("[session-b]"), "duplicate labels should include a stable session hint"


def test_gui_chat_bridge_buttons_bind_expected_callbacks():
    path = Path(__file__).parent / "codex_manager_gui.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    commands = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            value = keyword.value
            if (
                keyword.arg == "command"
                and isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            ):
                commands.add(value.attr)
    for callback in ["_refresh_chat_bridge_sessions", "_chat_droid_to_codex", "_chat_codex_to_droid"]:
        assert callback in commands, f"GUI Chat Bridge button callback not bound: {callback}"


def test_gui_dialog_entries_bind_paste_directly():
    text = (Path(__file__).parent / "codex_manager_gui.py").read_text(encoding="utf-8")
    assert "def _paste_clipboard_into" in text, "GUI paste helper missing"
    assert "def _handle_entry_shortcut" in text, "GUI entry shortcut handler missing"
    assert "keycode == 65" in text, "Ctrl+A should select all"
    assert "cyrillic_em" in text, "Ctrl+V should work on RU keyboard layout"
    assert text.count("self._bind_paste(entry)") >= 4, "dialog Entry widgets should bind paste directly"


def test_merge_preserves_all_sections():
    cfg = (
        'model_provider = "A"\n'
        'model = "gpt-5"\n'
        "\n"
        "[model_providers.A]\n"
        'name = "A"\n'
        'base_url = "https://a.com"\n'
        "\n"
        "[model_providers.B]\n"
        'name = "B"\n'
        'base_url = "https://b.com"\n'
    )
    section = '[model_providers.B]\nname = "B"\nbase_url = "https://b.com"'
    result = ct._merge_config(cfg, "B", section, "gpt-5.5")
    assert 'model_provider = "B"' in result, "model_provider not switched"
    assert 'model = "gpt-5.5"' in result, "model not updated"
    assert "[model_providers.A]" in result, "ProviderA section lost"
    assert "[model_providers.B]" in result, "ProviderB section lost"
    # Regression: each provider section must appear EXACTLY once.
    # A substring `in` check passes even when a section is duplicated.
    assert result.count("[model_providers.A]") == 1, "ProviderA duplicated"
    assert result.count("[model_providers.B]") == 1, "ProviderB duplicated"


def test_merge_no_duplicate_from_contaminated_blob():
    """If a profile stored a contaminated provider_section that is the
    concatenation of several [model_providers.*] blocks (legacy bug),
    merging must NOT duplicate the other providers already in config.toml."""
    cfg = (
        'model_provider = "A"\n'
        'model = "gpt-5"\n'
        "\n"
        "[model_providers.A]\n"
        'name = "A"\n'
        'base_url = "https://a.com"\n'
        "\n"
        "[model_providers.B]\n"
        'name = "B"\n'
        'base_url = "https://b.com"\n'
    )
    # Contaminated blob: B's section followed by a stray copy of A's section.
    blob = (
        "[model_providers.B]\n"
        'name = "B"\n'
        'base_url = "https://b.com"\n'
        "[model_providers.A]\n"
        'name = "A"\n'
        'base_url = "https://a.com"\n'
    )
    result = ct._merge_config(cfg, "B", blob, "gpt-5.5")
    assert result.count("[model_providers.A]") == 1, "ProviderA duplicated from blob"
    assert result.count("[model_providers.B]") == 1, "ProviderB duplicated from blob"


def test_merge_append_new_section():
    cfg = 'model_provider = "A"\nmodel = "gpt-5"\n'
    section = '[model_providers.C]\nname = "C"\nbase_url = "https://c.com"'
    result = ct._merge_config(cfg, "C", section, "gpt-6")
    assert 'model_provider = "C"' in result
    assert "[model_providers.C]" in result


def test_b64_roundtrip():
    plain = '{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test123"}'
    encoded = ct._encode_secret(plain)
    assert encoded.startswith("b64:"), "encoded should start with b64:"
    assert ct._decode_secret(encoded) == plain, "roundtrip mismatch"


def test_b64_passthrough():
    assert ct._decode_secret("not-b64") == "not-b64"
    assert ct._decode_secret("") == ""
    assert ct._decode_secret(None) is None


def test_add_provider_format():
    orig, tmp = setup_temp_providers()
    try:
        jf = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump(
            {
                "name": "TestProv",
                "model": "gpt-5",
                "base_url": "https://api.test.com/v1",
                "wire_api": "responses",
            },
            jf,
        )
        jf.close()

        ct.add_provider(jf.name, "sk-testkey")
        data = ct._load_providers()
        p = data["profiles"]["TestProv"]

        assert "provider_section" in p, "missing provider_section"
        assert "config.toml" not in p, "old config.toml field should not exist"
        assert p["model"] == "gpt-5", f"model mismatch: {p['model']}"
        assert "[model_providers.TestProv]" in p["provider_section"]
        assert p["auth.json"].startswith("b64:"), "auth not b64-encoded"

        decoded = json.loads(ct._decode_secret(p["auth.json"]))
        assert decoded["OPENAI_API_KEY"] == "sk-testkey"

        os.unlink(jf.name)
    finally:
        restore_providers(orig, tmp)


def test_remove_provider():
    orig, tmp = setup_temp_providers()
    try:
        jf = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump(
            {
                "name": "ToRemove",
                "model": "gpt-5",
                "base_url": "https://r.com/v1",
            },
            jf,
        )
        jf.close()
        ct.add_provider(jf.name, "sk-rem")
        ct.remove_provider("ToRemove")
        data = ct._load_providers()
        assert "ToRemove" not in data.get("profiles", {}), "profile not removed"
        os.unlink(jf.name)
    finally:
        restore_providers(orig, tmp)


def test_extract_provider_config():
    cfg = (
        'model = "gpt-5.5"\n'
        'model_provider = "Active"\n'
        "\n"
        "[model_providers.Active]\n"
        'name = "Active"\n'
        'base_url = "https://active.com/v1"\n'
        'wire_api = "responses"\n'
        "\n"
        "[model_providers.Other]\n"
        'name = "Other"\n'
        'base_url = "https://other.com/v1"\n'
    )
    name, section, model = ct._extract_provider_config(cfg)
    assert name == "Active"
    assert model == "gpt-5.5"
    assert "[model_providers.Active]" in section
    # Regression: must return ONLY the active provider's section. An earlier
    # line-collector grabbed every consecutive [model_providers.*] block.
    assert "[model_providers.Other]" not in section, "extractor leaked other provider section"


def test_transform_signature():
    import inspect

    sig = inspect.signature(ct.transform)
    params = list(sig.parameters.keys())
    assert "project" in params, "project param missing"
    assert "from_model" in params, "from_model param missing"
    assert "to_model" in params, "to_model param missing"


def test_project_filter_uses_cwd_column():
    text = Path("codex_chat_transformer.py").read_text(encoding="utf-8")
    assert "AND cwd LIKE ?" in text, "project filtering should use current threads.cwd column"
    assert "AND project LIKE ?" not in text, "current Codex schema has no project column"


def test_cli_sync_push_not_hardcoded_to_8080():
    text = Path("codex_chat_transformer.py").read_text(encoding="utf-8")
    assert "127.0.0.1:8080/api/providers" not in text, "CLI provider push must not depend on local port 8080"
    assert "_providers_summary" in text and "_provider_full" in text, "CLI provider push should read local providers directly"


def test_parse_sync_peer_accepts_supported_forms():
    cases = [
        ("example.com", {"scheme": "http", "host": "example.com", "port": 8080}),
        ("example.com:9090", {"scheme": "http", "host": "example.com", "port": 9090}),
        ("http://example.com:7000", {"scheme": "http", "host": "example.com", "port": 7000}),
        ("https://example.com:7443", {"scheme": "https", "host": "example.com", "port": 7443}),
    ]
    for raw, expected in cases:
        parsed = ct.parse_sync_peer(raw)
        assert parsed == expected, f"{raw}: expected {expected}, got {parsed}"


def test_parse_sync_peer_rejects_invalid_inputs():
    for raw in ("", ":8080", "example.com:nope", "http://:8080", "example.com:0", "example.com:65536"):
        try:
            ct.parse_sync_peer(raw)
        except ValueError:
            continue
        raise AssertionError(f"{raw!r} should raise ValueError")


def test_is_codex_running():
    result = ct.is_codex_running()
    assert isinstance(result, bool)


def test_merge_reasoning():
    cfg = (
        'model_provider = "A"\n'
        'model = "gpt-5"\n'
        'model_reasoning_effort = "low"\n'
        "\n"
        "[model_providers.A]\n"
        'name = "A"\n'
        'base_url = "https://a.com"\n'
    )
    section = '[model_providers.B]\nname = "B"\nbase_url = "https://b.com"'
    result = ct._merge_config(cfg, "B", section, "gpt-5.5", "high")
    assert 'model_reasoning_effort = "high"' in result, "reasoning not set"
    assert "low" not in result, "old reasoning not removed"


def test_merge_add_reasoning_when_absent():
    """Reasoning line is added even when not present in original config."""
    cfg = (
        'model_provider = "A"\n'
        'model = "gpt-5"\n'
        "\n"
        "[model_providers.A]\n"
        'name = "A"\n'
        'base_url = "https://a.com"\n'
    )
    result = ct._merge_config(cfg, "A", None, None, "high")
    assert 'model_reasoning_effort = "high"' in result, "reasoning not added when absent"


def test_merge_remove_reasoning():
    cfg = (
        'model_provider = "A"\n'
        'model = "gpt-5"\n'
        'model_reasoning_effort = "high"\n'
    )
    result = ct._merge_config(cfg, "B", None, "gpt-5.5", None)
    assert "model_reasoning_effort" not in result, "reasoning should be removed when target_reasoning=None"


def test_edit_provider():
    orig, tmp = setup_temp_providers()
    try:
        # Create a provider first
        jf = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump(
            {
                "name": "EditMe",
                "model": "gpt-5",
                "base_url": "https://old.com/v1",
                "wire_api": "responses",
            },
            jf,
        )
        jf.close()
        ct.add_provider(jf.name, "sk-old")

        # Edit it
        ct.edit_provider("EditMe", model="gpt-5.5", base_url="https://new.com/v1",
                         reasoning="high")
        data = ct._load_providers()
        p = data["profiles"]["EditMe"]
        assert p["model"] == "gpt-5.5", f"model not updated: {p['model']}"
        assert "new.com" in p["provider_section"], "base_url not updated"
        assert "model_reasoning_effort" not in p["provider_section"], "reasoning should NOT be in section"
        assert p["model_reasoning_effort"] == "high", "reasoning not saved"
        os.unlink(jf.name)
    finally:
        restore_providers(orig, tmp)


def test_rename_provider():
    orig, tmp = setup_temp_providers()
    try:
        jf = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        json.dump(
            {
                "name": "OldName",
                "model": "gpt-5",
                "base_url": "https://old.com/v1",
                "wire_api": "responses",
            },
            jf,
        )
        jf.close()
        ct.add_provider(jf.name, "sk-test")

        # Rename + change url
        ct.edit_provider("OldName", base_url="https://new.com/v1",
                         reasoning="medium", new_name="NewName")
        data = ct._load_providers()
        assert "OldName" not in data["profiles"], "old key should be removed"
        assert "NewName" in data["profiles"], "new key should exist"
        p = data["profiles"]["NewName"]
        assert p["model_provider"] == "NewName", "model_provider not updated"
        assert "new.com" in p["provider_section"], "base_url not updated"
        assert "[model_providers.NewName]" in p["provider_section"], "section header not renamed"
        assert p["model_reasoning_effort"] == "medium", "reasoning not preserved"
        os.unlink(jf.name)
    finally:
        restore_providers(orig, tmp)


def test_sanitize_name():
    assert ct._sanitize_name("My Provider") == "My_Provider"
    assert ct._sanitize_name("Hello World") == "Hello_World"
    assert ct._sanitize_name("NoSpaces") == "NoSpaces"
    assert ct._sanitize_name("a/b:c*d?e") == "a_b_c_d_e"
    assert ct._sanitize_name("  trim  ") == "trim"
    assert ct._sanitize_name("") == ""


def test_set_model():
    # Create a temp dir with config.toml
    tmp_dir = tempfile.mkdtemp()
    cfg_path = Path(tmp_dir) / "config.toml"
    cfg_path.write_text('model = "gpt-4"\nmodel_provider = "test"\n', encoding="utf-8")

    orig_dir = ct.CODEX_DIR
    ct.CODEX_DIR = Path(tmp_dir)
    ct.STATE_DB = ct.CODEX_DIR / "state_5.sqlite"

    ct.set_model("gpt-5.5")
    content = cfg_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in content
    assert "gpt-4" not in content

    import shutil
    shutil.rmtree(tmp_dir)
    ct.CODEX_DIR = orig_dir
    ct.STATE_DB = ct.CODEX_DIR / "state_5.sqlite"


def test_cli_syntax():
    py_compile.compile(
        str(Path(__file__).parent / "codex_chat_transformer.py"), doraise=True
    )


def test_export_pack_without_keys_strips_provider_auth():
    original, tmp_dir = setup_temp_codex_home()
    try:
        ct._save_providers({
            "profiles": {
                "PackProv": {
                    "model_provider": "PackProv",
                    "model": "gpt-5",
                    "auth_mode": "apikey",
                    "provider_section": '[model_providers.PackProv]\nname = "PackProv"\nbase_url = "https://pack.invalid/v1"\nwire_api = "responses"',
                    "auth.json": json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-pack"}),
                    "saved_at": "2026-01-01T00:00:00",
                }
            },
            "active": "PackProv",
        })
        zip_path = tmp_dir / "providers-pack.zip"
        summary = ct.export_pack(zip_path, scope="providers", provider_names=["PackProv"], without_keys=True)

        import zipfile
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            provider = json.loads(zf.read("codex-pack/providers/PackProv.json").decode("utf-8"))

        assert summary["providers_exported"] == ["PackProv"], f"unexpected summary: {summary}"
        assert provider["auth.json"] == "", "without-keys export should strip auth payload"
        assert provider["auth_mode"] == "apikey", "auth mode should remain visible"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_import_pack_upserts_provider_and_stores_auth_obfuscated():
    original, tmp_dir = setup_temp_codex_home()
    try:
        zip_path = tmp_dir / "import-provider-pack.zip"
        import zipfile
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("codex-pack/manifest.json", json.dumps({"version": 1, "scope": "providers"}))
            zf.writestr("codex-pack/providers/ImportProv.json", json.dumps({
                "name": "ImportProv",
                "model_provider": "ImportProv",
                "model": "gpt-5.5",
                "auth_mode": "apikey",
                "provider_section": '[model_providers.ImportProv]\nname = "ImportProv"\nbase_url = "https://import.invalid/v1"\nwire_api = "responses"',
                "auth.json": json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-import"}),
                "saved_at": "2026-01-01T00:00:00",
            }))

        backup_calls = []
        original_full_backup = ct.full_backup
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")
        try:
            summary = ct.import_pack(zip_path, scope="providers")
        finally:
            ct.full_backup = original_full_backup

        raw = json.loads(ct.PROVIDERS_FILE.read_text(encoding="utf-8"))
        stored = raw["profiles"]["ImportProv"]["auth.json"]
        assert summary["providers_imported"] == ["ImportProv"], f"unexpected summary: {summary}"
        assert backup_calls == ["called"], f"import should create one backup, got {backup_calls}"
        assert stored.startswith("b64:"), "imported provider auth should be stored obfuscated"
        decoded = json.loads(ct._decode_secret(stored))
        assert decoded["OPENAI_API_KEY"] == "sk-import", "decoded auth should preserve the key"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_pack_sessions_export_import_round_trip():
    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = '\n'.join([
            json.dumps({"type": "session_meta", "payload": {"model_provider": "openai", "model": "gpt-5"}}),
            json.dumps({"type": "user_message", "text": "hello pack"}),
        ]) + "\n"
        store_temp_session(
            "sess-pack",
            "Pack Session",
            r"C:\Projects\Pack",
            jsonl_text=jsonl_text,
            first_user_message="hello pack",
            preview="pack preview",
        )

        zip_path = tmp_dir / "sessions-pack.zip"
        export_summary = ct.export_pack(zip_path, scope="sessions")

        import shutil
        shutil.rmtree(ct.SESSIONS_DIR)
        ct.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        import sqlite3
        conn = sqlite3.connect(str(ct.STATE_DB))
        conn.execute("DELETE FROM threads")
        conn.commit()
        conn.close()

        backup_calls = []
        original_full_backup = ct.full_backup
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")
        try:
            import_summary = ct.import_pack(zip_path, scope="sessions")
        finally:
            ct.full_backup = original_full_backup

        conn = sqlite3.connect(str(ct.STATE_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, title, cwd, first_user_message, preview FROM threads WHERE id = ?", ("sess-pack",)).fetchone()
        conn.close()

        rollout_files = list(ct.SESSIONS_DIR.rglob("rollout-sess-pack.jsonl"))
        assert export_summary["sessions_exported"] == ["sess-pack"], f"unexpected export summary: {export_summary}"
        assert import_summary["sessions_imported"] == ["sess-pack"], f"unexpected import summary: {import_summary}"
        assert backup_calls == ["called"], f"import should create one backup, got {backup_calls}"
        assert row is not None, "import should upsert the session row"
        assert row["title"] == "Pack Session", "session title should round-trip"
        assert row["first_user_message"] == "hello pack", "first user message should round-trip"
        assert row["preview"] == "pack preview", "preview should round-trip"
        assert rollout_files, "session import should restore a rollout file"
        assert "hello pack" in rollout_files[0].read_text(encoding="utf-8"), "rollout file should round-trip"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_pack_filters_limit_exported_items():
    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        ct._save_providers({
            "profiles": {
                "KeepProv": {
                    "model_provider": "KeepProv",
                    "model": "gpt-5",
                    "auth_mode": "apikey",
                    "provider_section": '[model_providers.KeepProv]\nname = "KeepProv"\nbase_url = "https://keep.invalid/v1"',
                    "auth.json": json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-keep"}),
                    "saved_at": "2026-01-01T00:00:00",
                },
                "DropProv": {
                    "model_provider": "DropProv",
                    "model": "gpt-5",
                    "auth_mode": "apikey",
                    "provider_section": '[model_providers.DropProv]\nname = "DropProv"\nbase_url = "https://drop.invalid/v1"',
                    "auth.json": json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-drop"}),
                    "saved_at": "2026-01-01T00:00:00",
                },
            },
            "active": "KeepProv",
        })
        store_temp_session("keep-session", "Keep Session", r"C:\Projects\Keep", jsonl_text='{"type":"user_message","text":"keep"}\n')
        store_temp_session("drop-session", "Drop Session", r"C:\Projects\Drop", jsonl_text='{"type":"user_message","text":"drop"}\n')

        zip_path = tmp_dir / "filtered-pack.zip"
        summary = ct.export_pack(
            zip_path,
            scope="all",
            provider_names=["KeepProv"],
            session_ids=["keep-session"],
        )

        import zipfile
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = set(zf.namelist())

        assert summary["providers_exported"] == ["KeepProv"], f"unexpected provider summary: {summary}"
        assert summary["sessions_exported"] == ["keep-session"], f"unexpected session summary: {summary}"
        assert "codex-pack/providers/KeepProv.json" in names, "selected provider should be exported"
        assert "codex-pack/providers/DropProv.json" not in names, "unselected provider should be omitted"
        assert "codex-pack/sessions/keep-session.json" in names, "selected session metadata should be exported"
        assert "codex-pack/sessions/drop-session.json" not in names, "unselected session should be omitted"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_export_pack_skips_missing_rollout_with_warning():
    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session("good-session", "Good Session", r"C:\Projects\Good", jsonl_text='{"type":"user_message","text":"good"}\n')
        store_temp_session("missing-session", "Missing Session", r"C:\Projects\Missing", jsonl_text="")

        zip_path = tmp_dir / "missing-rollout-pack.zip"
        summary = ct.export_pack(zip_path, scope="sessions")

        import zipfile
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = set(zf.namelist())

        assert summary["sessions_exported"] == ["good-session"], f"unexpected exported sessions: {summary}"
        assert summary["sessions_skipped"] == 1, f"missing rollout should be counted as skipped: {summary}"
        assert summary["warnings"], "missing rollout should emit at least one warning"
        assert "codex-pack/sessions/good-session.jsonl" in names, "readable rollout should be exported"
        assert "codex-pack/sessions/missing-session.jsonl" not in names, "missing rollout should be skipped"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_search_sessions_metadata_hit():
    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session(
            "meta-hit",
            "Needle Title",
            r"C:\Projects\Meta",
            jsonl_text="",
            preview="compact preview",
            first_user_message="first prompt",
        )
        results = ct.search_sessions("needle")
        assert [r["id"] for r in results] == ["meta-hit"], f"metadata search should match by title: {results}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_search_sessions_jsonl_fallback_hit():
    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = '\n'.join([
            json.dumps({"type": "session_meta", "payload": {"model_provider": "openai"}}),
            json.dumps({"type": "assistant_message", "text": "plain fallback needle"}),
        ]) + "\n"
        store_temp_session(
            "jsonl-hit",
            "Unrelated Title",
            r"C:\Projects\Jsonl",
            jsonl_text=jsonl_text,
            preview="no match here",
            first_user_message="still no match",
        )
        results = ct.search_sessions("needle")
        assert [r["id"] for r in results] == ["jsonl-hit"], f"search should fall back to JSONL scan: {results}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_search_sessions_project_filter():
    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session("proj-a", "Needle A", r"C:\Projects\Alpha", jsonl_text="")
        store_temp_session("proj-b", "Needle B", r"C:\Projects\Beta", jsonl_text="")
        results = ct.search_sessions("needle", project="Alpha")
        assert [r["id"] for r in results] == ["proj-a"], f"project filter should limit search results: {results}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def write_temp_droid_session(home, session_id="droid-old", title="Droid Old Chat"):
    sessions_dir = Path(home) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = sessions_dir / f"{session_id}.jsonl"
    settings_path = sessions_dir / f"{session_id}.settings.json"
    events = [
        {"type": "session_start", "id": session_id, "title": title, "owner": "user"},
        {
            "type": "message",
            "id": "msg-user-1",
            "timestamp": "2025-01-02T03:04:05.000Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "hello from droid"}]},
        },
        {
            "type": "message",
            "id": "msg-assistant-1",
            "timestamp": "2025-01-02T03:04:07.000Z",
            "parentId": "msg-user-1",
            "message": {
                "id": "assistant-inner-1",
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "droid reply"},
                    {"type": "tool_use", "id": "tool-1", "name": "shell", "input": {"cmd": "echo ok"}},
                ],
            },
        },
        {
            "type": "message",
            "id": "msg-tool-1",
            "timestamp": "2025-01-02T03:04:08.000Z",
            "parentId": "msg-assistant-1",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tool-1", "is_error": False, "content": "ok"}],
            },
        },
        {"type": "todo_state", "id": "todo-1", "timestamp": "2025-01-02T03:04:09.000Z", "todos": []},
    ]
    jsonl_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    settings_path.write_text(
        json.dumps({
            "model": "custom:Stub-GPT-5.5-1",
            "reasoningEffort": "medium",
            "providerLock": "openai",
            "providerLockTimestamp": "2025-01-02T03:04:05.000Z",
            "tokenUsage": {"total": 123},
        }),
        encoding="utf-8",
    )
    return jsonl_path, settings_path


def test_chat_bridge_droid_session_to_bridge_preserves_messages_and_tools():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        jsonl_path, settings_path = write_temp_droid_session(tmp)
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

    assert bridge["format"] == "codex-droid-chat-bridge", f"unexpected bridge format: {bridge}"
    assert bridge["source"]["app"] == "droid", f"unexpected source app: {bridge['source']}"
    assert bridge["source"]["session_id"] == "droid-old", f"source id should come from session_start: {bridge['source']}"
    assert bridge["session"]["title"] == "Droid Old Chat", "title should come from session_start"
    assert bridge["session"]["provider"] == "openai", "providerLock should become bridge provider"
    assert bridge["session"]["model"] == "custom:Stub-GPT-5.5-1", "Droid model should become bridge model"
    assert bridge["work_context"]["current"]["confidence"] == "unknown", "Droid git context should be unknown in v1"
    assert bridge["work_context"]["timeline_complete"] is False, "Droid timeline should be explicitly incomplete"
    assert [m["role"] for m in bridge["messages"][:3]] == ["user", "assistant", "tool"], f"unexpected roles: {bridge['messages']}"
    part_types = [p["type"] for m in bridge["messages"] for p in m["parts"]]
    assert "text" in part_types, f"text parts should be preserved: {part_types}"
    assert "tool_call" in part_types, f"tool_use should become tool_call: {part_types}"
    assert "tool_result" in part_types, f"tool_result should be preserved: {part_types}"
    tool_result = next(p for m in bridge["messages"] for p in m["parts"] if p.get("type") == "tool_result")
    assert tool_result["is_error"] is False, f"Droid tool_result error state should be preserved: {tool_result}"
    assert "todo_state" in part_types, f"todo_state should be preserved as metadata: {part_types}"


def test_chat_bridge_droid_to_bridge_preserves_compaction_state_and_parent():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        sessions_dir = Path(tmp) / "sessions" / "-C-Research-nothing"
        sessions_dir.mkdir(parents=True)
        jsonl_path = sessions_dir / "droid-child.jsonl"
        settings_path = sessions_dir / "droid-child.settings.json"
        events = [
            {
                "type": "session_start",
                "id": "droid-child",
                "title": "New Session",
                "sessionTitle": "New Session",
                "owner": "test",
                "parent": "droid-parent",
                "version": 2,
                "cwd": r"C:\Research\nothing",
                "hostId": "host-1",
            },
            {
                "type": "compaction_state",
                "id": "compact-1",
                "timestamp": "2026-05-28T13:01:08.623Z",
                "summaryText": "Earlier Droid summary",
                "summaryTokens": 623,
                "summaryKind": "llm_summary",
                "removedCount": 9,
                "systemInfo": {
                    "osName": "win32 10.0.26100",
                    "directoryInfo": [{"cmd": "pwd", "out": r"C:\Research\nothing"}],
                    "gitInfo": [{"cmd": "git status -b --porcelain | head -n1", "out": "not a git repository"}],
                    "guidelinesInfo": [],
                    "designGuidelinesInfo": [],
                },
            },
        ]
        jsonl_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        settings_path.write_text(json.dumps({"model": "custom:model", "providerLock": "openai"}), encoding="utf-8")

        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

    compactions = bridge.get("compactions") or []
    assert len(compactions) == 1, f"Droid compaction_state should become bridge compaction: {bridge}"
    compaction = compactions[0]
    assert compaction["source"] == "droid", f"source should be Droid: {compaction}"
    assert compaction["id"] == "compact-1", f"compaction id should be preserved: {compaction}"
    assert compaction["summary_text"] == "Earlier Droid summary", f"summary text should be preserved: {compaction}"
    assert compaction["summary_tokens"] == 623, f"summary token count should be preserved: {compaction}"
    assert compaction["removed_count"] == 9, f"removedCount should be preserved: {compaction}"
    assert compaction["parent_session_id"] == "droid-parent", f"manual /compress parent should be preserved: {compaction}"
    assert compaction["system_info"]["directoryInfo"][0]["out"] == r"C:\Research\nothing", f"systemInfo should be preserved: {compaction}"
    assert compaction["anchor_message_index"] == -1, f"manual Droid /compress summary should be anchorless: {compaction}"
    source_types = [event["payload_type"] for event in bridge["source_events"]]
    assert "compaction_state" in source_types, f"raw compaction_state should still be lossless source event: {source_types}"


def test_chat_bridge_droid_session_lookup_finds_project_nested_files():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "sessions" / "-C-Research-nothing"
        project_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = project_dir / "droid-project.jsonl"
        settings_path = project_dir / "droid-project.settings.json"
        jsonl_path.write_text(
            json.dumps({
                "type": "session_start",
                "id": "droid-project",
                "title": "Project Droid",
                "cwd": r"C:\Research\nothing",
            }) + "\n",
            encoding="utf-8",
        )
        settings_path.write_text("{}", encoding="utf-8")

        found_jsonl, found_settings = chat_bridge.find_droid_session_paths(tmp, "droid-project")

        assert found_jsonl == jsonl_path, f"project Droid session should be found recursively: {found_jsonl}"
        assert found_settings == settings_path, f"project Droid settings should follow JSONL path: {found_settings}"


def test_chat_bridge_droid_to_bridge_preserves_project_cwd_and_session_title():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        jsonl_path, settings_path = write_temp_droid_session(tmp, title="seed title")
        lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
        lines[0]["sessionTitle"] = "Review Provided Repository for Analysis"
        lines[0]["cwd"] = r"C:\Research\nothing"
        lines[0]["hostId"] = "host-project-1"
        jsonl_path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

    assert bridge["session"]["title"] == "Review Provided Repository for Analysis", f"Droid sessionTitle should become Codex title: {bridge['session']}"
    assert bridge["work_context"]["primary_cwd"] == r"C:\Research\nothing", f"Droid cwd should become bridge primary cwd: {bridge['work_context']}"
    assert bridge["work_context"]["current"]["cwd"] == r"C:\Research\nothing", f"Droid cwd should become current cwd: {bridge['work_context']}"


def test_chat_bridge_droid_to_codex_import_creates_consistent_rollout_and_pins_old():
    import chat_bridge
    import sqlite3

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        jsonl_path, settings_path = write_temp_droid_session(factory_home)
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=ct.CODEX_DIR,
            state_db=ct.STATE_DB,
            sessions_dir=ct.SESSIONS_DIR,
            global_state_path=ct.GLOBAL_STATE,
            preserve_timestamps=True,
            pin_old=True,
            old_before_ms=1767225600000,
            target_provider="Stub_API",
            target_model="gpt-5.5",
        )

        conn = sqlite3.connect(str(ct.STATE_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (summary["codex_session_id"],)).fetchone()
        conn.close()

        assert row is not None, "Droid import should insert a Codex threads row"
        codex_id_re = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
        assert codex_id_re.match(summary["codex_session_id"]), f"Codex import should use sidebar-compatible UUIDv7-like ids: {summary['codex_session_id']}"
        rollout_path = Path(row["rollout_path"])
        assert rollout_path.exists(), "threads.rollout_path should point at a real rollout file"
        lines = [json.loads(line) for line in rollout_path.read_text(encoding="utf-8").splitlines()]
        meta = lines[0]
        assert meta["type"] == "session_meta", "rollout should start with session_meta"
        assert meta["payload"]["id"] == row["id"], "rollout session id should match DB id"
        assert meta["payload"]["model_provider"] == row["model_provider"], "provider should match DB"
        assert meta["payload"]["model"] == row["model"], "model should match DB"
        assert row["model_provider"] == "Stub_API", f"Codex import should use target provider for sidebar visibility: {dict(row)}"
        assert row["model"] == "gpt-5.5", f"Codex import should use target model: {dict(row)}"
        assert row["created_at_ms"] == 1735787045000, f"created timestamp should be preserved, got {row['created_at_ms']}"
        assert row["updated_at_ms"] == 1735787049000, f"updated timestamp should be preserved, got {row['updated_at_ms']}"

        session_index_path = ct.CODEX_DIR / "session_index.jsonl"
        index_entries = [json.loads(line) for line in session_index_path.read_text(encoding="utf-8").splitlines()]
        index_entry = next((entry for entry in index_entries if entry.get("id") == summary["codex_session_id"]), None)
        assert index_entry is not None, "Droid import should append session_index.jsonl so Codex sidebar can discover it"
        assert index_entry["thread_name"] == "Droid Old Chat", f"session index should use imported title: {index_entry}"
        assert index_entry["updated_at"].startswith("2025-01-02T03:04:09"), f"session index should use imported updated time: {index_entry}"

        pinned = json.loads(ct.GLOBAL_STATE.read_text(encoding="utf-8"))["pinned-thread-ids"]
        assert summary["codex_session_id"] in pinned, "old imported Droid session should be pinned when requested"
        mapping = json.loads((ct.CODEX_DIR / "chat_bridge_mappings.json").read_text(encoding="utf-8"))
        assert mapping["pairs"][0]["droid_session_id"] == "droid-old", f"mapping should remember Droid id: {mapping}"
        assert mapping["pairs"][0]["codex_session_id"] == summary["codex_session_id"], f"mapping should remember Codex id: {mapping}"

        reread_bridge = chat_bridge.codex_session_to_bridge(dict(row), row["rollout_path"])
        reread_part_types = [p["type"] for m in reread_bridge["messages"] for p in m["parts"]]
        assert "tool_call" in reread_part_types, f"Codex reread should preserve Droid tool calls: {reread_part_types}"
        assert "tool_result" in reread_part_types, f"Codex reread should preserve Droid tool results: {reread_part_types}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_to_codex_import_can_use_fresh_timestamps():
    import chat_bridge
    import sqlite3

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        jsonl_path, settings_path = write_temp_droid_session(factory_home, session_id="droid-fresh")
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=ct.CODEX_DIR,
            state_db=ct.STATE_DB,
            sessions_dir=ct.SESSIONS_DIR,
            global_state_path=ct.GLOBAL_STATE,
            preserve_timestamps=False,
        )

        conn = sqlite3.connect(str(ct.STATE_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT rollout_path, created_at_ms, updated_at_ms FROM threads WHERE id = ?", (summary["codex_session_id"],)).fetchone()
        conn.close()

        assert row["created_at_ms"] > 1767225600000, f"fresh import should use current-ish created time: {dict(row)}"
        assert row["updated_at_ms"] >= row["created_at_ms"], f"fresh updated time should not go backwards: {dict(row)}"
        rollout_events = [json.loads(line) for line in Path(row["rollout_path"]).read_text(encoding="utf-8").splitlines()]
        event_times = [chat_bridge._ms(event["timestamp"]) for event in rollout_events]
        assert min(event_times) >= row["created_at_ms"], f"fresh rollout timestamps should not keep old source dates: {event_times}"
        assert max(event_times) <= row["updated_at_ms"], f"fresh rollout timestamps should fit DB updated_at_ms: {event_times}, {dict(row)}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_to_codex_mapping_failure_reports_warning_after_commit():
    import chat_bridge
    import sqlite3

    original, tmp_dir = setup_temp_codex_home()
    original_upsert = chat_bridge._upsert_mapping
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        jsonl_path, settings_path = write_temp_droid_session(factory_home, session_id="droid-map-fail")
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)
        chat_bridge._upsert_mapping = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("mapping denied"))

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=ct.CODEX_DIR,
            state_db=ct.STATE_DB,
            sessions_dir=ct.SESSIONS_DIR,
            global_state_path=ct.GLOBAL_STATE,
        )

        conn = sqlite3.connect(str(ct.STATE_DB))
        count = conn.execute("SELECT COUNT(*) FROM threads WHERE id = ?", (summary["codex_session_id"],)).fetchone()[0]
        conn.close()
        assert count == 1, "committed Codex import should remain visible after mapping warning"
        assert summary["warnings"], f"mapping failure should be reported as warning: {summary}"
        assert "mapping" in summary["warnings"][0], f"warning should identify mapping issue: {summary}"
    finally:
        chat_bridge._upsert_mapping = original_upsert
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_mapping_keeps_duplicate_import_pairs():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        jsonl_path, settings_path = write_temp_droid_session(factory_home, session_id="droid-repeat")
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)
        first = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=ct.CODEX_DIR,
            state_db=ct.STATE_DB,
            sessions_dir=ct.SESSIONS_DIR,
            global_state_path=ct.GLOBAL_STATE,
        )
        second = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=ct.CODEX_DIR,
            state_db=ct.STATE_DB,
            sessions_dir=ct.SESSIONS_DIR,
            global_state_path=ct.GLOBAL_STATE,
        )
        mapping = json.loads((ct.CODEX_DIR / "chat_bridge_mappings.json").read_text(encoding="utf-8"))
        codex_ids = [pair["codex_session_id"] for pair in mapping["pairs"]]
        assert first["codex_session_id"] in codex_ids, f"first import pair should remain in mapping: {mapping}"
        assert second["codex_session_id"] in codex_ids, f"second import pair should be appended to mapping: {mapping}"
        assert len(mapping["pairs"]) == 2, f"duplicate imports should be recorded as separate pairs: {mapping}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_mirror_plan_merges_roots_and_classifies_states():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        codex_root = root / "codex"
        factory_home = root / "factory"
        codex_root.mkdir()
        factory_home.mkdir()

        (codex_root / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [
                {"import_id": "shared", "codex_session_id": "codex-newer", "droid_session_id": "droid-newer"},
                {"codex_session_id": "codex-older", "droid_session_id": "droid-older"},
                {"codex_session_id": "codex-only", "droid_session_id": "missing-droid"},
            ],
        }), encoding="utf-8")
        (factory_home / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [
                {"import_id": "shared", "codex_session_id": "codex-newer", "droid_session_id": "droid-newer"},
                {"codex_session_id": "codex-older", "droid_session_id": "droid-older"},
                {"codex_session_id": "codex-sync", "droid_session_id": "droid-sync"},
                {"codex_session_id": "missing-codex", "droid_session_id": "droid-only"},
                {"codex_session_id": "missing-both", "droid_session_id": "missing-both"},
            ],
        }), encoding="utf-8")

        codex_rows = [
            {"id": "codex-newer", "title": "Codex Newer", "updated_at_ms": 5000},
            {"id": "codex-older", "title": "Codex Older", "updated_at_ms": 1000},
            {"id": "codex-sync", "title": "Codex Sync", "updated_at_ms": 3000},
            {"id": "codex-only", "title": "Codex Only", "updated_at_ms": 2000},
        ]
        droid_sessions = [
            {"id": "droid-newer", "title": "Droid Newer", "mtime": 2},
            {"id": "droid-older", "title": "Droid Older", "mtime": 5},
            {"id": "droid-sync", "title": "Droid Sync", "mtime": 3.4},
            {"id": "droid-only", "title": "Droid Only", "mtime": 4},
        ]

        plan = chat_bridge.build_mirror_plan(codex_root, factory_home, codex_rows, droid_sessions, timestamp_tolerance_ms=1000)

    items = {(item["codex_session_id"], item["droid_session_id"]): item for item in plan["items"]}
    assert plan["read_only"] is True, f"mirror plan must be explicitly read-only: {plan}"
    assert plan["summary"]["total_pairs"] == 6, f"duplicate mapping pairs should be merged: {plan}"
    assert items[("codex-newer", "droid-newer")]["status"] == "codex_newer", f"expected Codex-newer status: {items}"
    assert items[("codex-older", "droid-older")]["status"] == "droid_newer", f"expected Droid-newer status: {items}"
    assert items[("codex-sync", "droid-sync")]["status"] == "in_sync", f"close timestamps should be in sync: {items}"
    assert items[("codex-only", "missing-droid")]["status"] == "missing_droid", f"missing Droid should be detected: {items}"
    assert items[("missing-codex", "droid-only")]["status"] == "missing_codex", f"missing Codex should be detected: {items}"
    assert items[("missing-both", "missing-both")]["status"] == "stale_pair", f"stale pair should be detected: {items}"
    assert plan["summary"]["statuses"]["codex_newer"] == 1, f"summary should count statuses: {plan}"


def test_chat_bridge_mirror_plan_surfaces_import_id_conflicts():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        codex_root = root / "codex"
        factory_home = root / "factory"
        codex_root.mkdir()
        factory_home.mkdir()

        (codex_root / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"import_id": "conflict-id", "codex_session_id": "codex-a", "droid_session_id": "droid-a"}],
        }), encoding="utf-8")
        (factory_home / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"import_id": "conflict-id", "codex_session_id": "codex-b", "droid_session_id": "droid-b"}],
        }), encoding="utf-8")

        plan = chat_bridge.build_mirror_plan(
            codex_root,
            factory_home,
            [{"id": "codex-a", "title": "A", "updated_at_ms": 1000}, {"id": "codex-b", "title": "B", "updated_at_ms": 1000}],
            [{"id": "droid-a", "title": "A", "mtime": 1}, {"id": "droid-b", "title": "B", "mtime": 1}],
        )

    conflict_items = [item for item in plan["items"] if item["status"] == "mapping_conflict"]
    assert len(conflict_items) == 2, f"same import_id with different pairs must not be silently collapsed: {plan}"
    assert {item["codex_session_id"] for item in conflict_items} == {"codex-a", "codex-b"}, f"both conflicting rows should be visible: {plan}"
    assert plan["summary"]["statuses"]["mapping_conflict"] == 2, f"summary should surface mapping conflicts: {plan}"


def test_chat_bridge_mirror_plan_project_filter_does_not_create_false_missing_codex():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        codex_root = root / "codex"
        factory_home = root / "factory"
        codex_root.mkdir()
        factory_home.mkdir()

        (codex_root / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [
                {"codex_session_id": "codex-in", "droid_session_id": "droid-in"},
                {"codex_session_id": "codex-out", "droid_session_id": "droid-out"},
                {"codex_session_id": "missing-codex", "droid_session_id": "droid-unknown-project"},
            ],
        }), encoding="utf-8")

        plan = chat_bridge.build_mirror_plan(
            codex_root,
            factory_home,
            [
                {"id": "codex-in", "title": "In", "cwd": r"C:\Research\nothing", "updated_at_ms": 1000},
                {"id": "codex-out", "title": "Out", "cwd": r"C:\Research\other", "updated_at_ms": 1000},
            ],
            [
                {"id": "droid-in", "title": "In", "mtime": 1},
                {"id": "droid-out", "title": "Out", "mtime": 1},
                {"id": "droid-unknown-project", "title": "Unknown", "mtime": 1},
            ],
            project="nothing",
        )

    assert [item["codex_session_id"] for item in plan["items"]] == ["codex-in"], f"project filter should keep only matching Codex rows: {plan}"
    assert "missing_codex" not in plan["summary"]["statuses"], f"unknown-project pairs should not become false missing_codex: {plan}"


def test_chat_bridge_mirror_actions_select_newer_and_skip_unsafe_states():
    import chat_bridge

    plan = {
        "items": [
            {"status": "codex_newer", "action": "would_export_to_droid", "codex_session_id": "codex-newer", "droid_session_id": "droid-old"},
            {"status": "missing_droid", "action": "would_create_droid", "codex_session_id": "codex-only", "droid_session_id": "missing-droid"},
            {"status": "droid_newer", "action": "would_import_to_codex", "codex_session_id": "codex-old", "droid_session_id": "droid-newer"},
            {"status": "missing_codex", "action": "would_create_codex", "codex_session_id": "missing-codex", "droid_session_id": "droid-only"},
            {"status": "in_sync", "action": "none", "codex_session_id": "codex-sync", "droid_session_id": "droid-sync"},
            {"status": "mapping_conflict", "action": "none", "codex_session_id": "codex-conflict", "droid_session_id": "droid-conflict"},
            {"status": "stale_pair", "action": "none", "codex_session_id": "codex-stale", "droid_session_id": "droid-stale"},
        ],
    }

    selected = chat_bridge.select_mirror_actions(plan, direction="newer")

    assert [item["codex_session_id"] for item in selected["items"]] == [
        "codex-newer",
        "codex-only",
        "codex-old",
        "missing-codex",
    ], f"newer direction should select only actionable newer/missing target states: {selected}"
    directions = {item["codex_session_id"]: item["apply_direction"] for item in selected["items"]}
    assert directions["codex-newer"] == "codex_to_droid", f"Codex-newer should export to Droid: {selected}"
    assert directions["codex-old"] == "droid_to_codex", f"Droid-newer should import to Codex: {selected}"
    skipped_statuses = {item["status"] for item in selected["skipped"]}
    assert {"in_sync", "mapping_conflict", "stale_pair"}.issubset(skipped_statuses), f"unsafe/no-op statuses should be skipped: {selected}"


def test_chat_bridge_mirror_actions_can_force_one_direction():
    import chat_bridge

    plan = {
        "items": [
            {"status": "codex_newer", "action": "would_export_to_droid", "codex_session_id": "codex-newer", "droid_session_id": "droid-old"},
            {"status": "missing_droid", "action": "would_create_droid", "codex_session_id": "codex-only", "droid_session_id": "missing-droid"},
            {"status": "droid_newer", "action": "would_import_to_codex", "codex_session_id": "codex-old", "droid_session_id": "droid-newer"},
        ],
    }

    selected = chat_bridge.select_mirror_actions(plan, direction="codex-to-droid")

    assert [item["codex_session_id"] for item in selected["items"]] == ["codex-newer", "codex-only"], f"forced direction should only export Codex rows: {selected}"
    assert all(item["apply_direction"] == "codex_to_droid" for item in selected["items"]), f"forced direction should be reflected per item: {selected}"


def test_chat_bridge_mirror_actions_skip_ambiguous_one_to_many_pairs():
    import chat_bridge

    plan = {
        "items": [
            {"status": "codex_newer", "codex_session_id": "codex-a", "droid_session_id": "droid-a"},
            {"status": "codex_newer", "codex_session_id": "codex-a", "droid_session_id": "droid-b"},
            {"status": "droid_newer", "codex_session_id": "codex-b", "droid_session_id": "droid-c"},
            {"status": "droid_newer", "codex_session_id": "codex-c", "droid_session_id": "droid-c"},
        ],
    }

    selected = chat_bridge.select_mirror_actions(plan, direction="newer")

    assert selected["items"] == [], f"one-to-many mappings should not be auto-applied: {selected}"
    assert {item["skip_reason"] for item in selected["skipped"]} == {"ambiguous_mapping"}, f"ambiguity should be explicit: {selected}"


def test_chat_bridge_mirror_actions_support_session_status_and_limit_filters():
    import chat_bridge

    plan = {
        "items": [
            {"status": "codex_newer", "codex_session_id": "codex-a", "droid_session_id": "droid-a"},
            {"status": "missing_droid", "codex_session_id": "codex-b", "droid_session_id": "droid-b"},
            {"status": "droid_newer", "codex_session_id": "codex-c", "droid_session_id": "droid-c"},
        ],
    }

    selected = chat_bridge.select_mirror_actions(
        plan,
        direction="newer",
        session_ids=["codex-a", "codex-b", "droid-c"],
        statuses=["codex_newer", "droid_newer"],
        limit=1,
    )

    assert [item["codex_session_id"] for item in selected["items"]] == ["codex-a"], f"limit should apply after session/status filters: {selected}"
    skipped_reasons = {(item["codex_session_id"], item["skip_reason"]) for item in selected["skipped"]}
    assert ("codex-b", "status_filter") in skipped_reasons, f"status filter should skip codex-b: {selected}"
    assert ("codex-c", "limit") in skipped_reasons, f"limit should skip extra matching item: {selected}"


def test_chat_bridge_mirror_actions_mark_previous_copy_as_already_applied():
    import chat_bridge

    plan = {
        "items": [
            {
                "status": "missing_droid",
                "codex_session_id": "codex-source",
                "droid_session_id": "missing-target",
                "bridge_id": "codex-codex-source",
                "source_app": "",
            },
            {
                "status": "in_sync",
                "codex_session_id": "codex-source",
                "droid_session_id": "bridge-droid-copy",
                "bridge_id": "codex-codex-source",
                "source_app": "codex",
            },
        ],
    }

    selected = chat_bridge.select_mirror_actions(plan, direction="newer")

    assert selected["items"] == [], f"previously applied logical source should not fan out again: {selected}"
    already = [item for item in selected["skipped"] if item.get("skip_reason") == "already_applied"]
    assert already and already[0]["codex_session_id"] == "codex-source", f"duplicate guard should be explicit: {selected}"


def test_chat_bridge_doctor_detects_structural_differences():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "main", "git_sha": "a" * 40}},
        "messages": [
            {"role": "user", "parts": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "parts": [{"type": "tool_call", "id": "tool-1", "name": "shell", "input": {"cmd": "echo ok"}}]},
            {"role": "tool", "parts": [{"type": "tool_result", "tool_call_id": "tool-1", "content": "ok"}]},
        ],
        "compactions": [{"summary_text": "summary"}],
        "source_events": [{"payload_type": "message"}],
    }
    droid_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {}},
        "messages": [
            {"role": "user", "parts": [{"type": "text", "text": "hello"}]},
            {"role": "tool", "parts": [{"type": "tool_result", "tool_call_id": "tool-1", "content": "ok"}]},
            {"role": "assistant", "parts": [{"type": "tool_call", "id": "tool-1", "name": "shell", "input": {"cmd": "echo ok"}}]},
        ],
        "compactions": [],
        "source_events": [],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    codes = {issue["code"] for issue in report["issues"]}
    assert report["read_only"] is True, f"doctor report should be read-only: {report}"
    severities = {issue["code"]: issue["severity"] for issue in report["issues"]}
    assert report["status"] == "error", f"structural differences should be errors: {report}"
    assert {"role_sequence", "part_type_sequence", "compaction_count", "source_event_count"}.issubset(codes), f"doctor should flag structural differences: {report}"
    assert severities["role_sequence"] == "error", f"role sequence mismatch should be a real error: {report}"
    assert severities["part_type_sequence"] == "error", f"part type sequence mismatch should be a real error: {report}"
    assert severities["compaction_count"] == "expected", f"compaction count drift should be expected: {report}"
    assert severities["source_event_count"] == "expected", f"source event count drift should be expected: {report}"


def test_chat_bridge_doctor_detects_one_sided_metadata_loss():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "main", "git_sha": "a" * 40}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }
    droid_bridge = {
        "session": {"provider": "", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "main", "git_sha": "a" * 40}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    codes = {issue["code"] for issue in report["issues"]}
    assert report["status"] == "warn", f"one-sided provider loss should warn: {report}"
    assert "provider" in codes, f"doctor should flag one-sided provider loss: {report}"


def test_chat_bridge_doctor_normalizes_extended_windows_cwd():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"\\?\C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }
    droid_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    codes = {issue["code"] for issue in report["issues"]}
    assert "primary_cwd" not in codes, f"extended Windows cwd prefix should not create doctor noise: {report}"
    assert report["status"] == "ok", f"normalized cwd pair should otherwise be clean: {report}"


def test_chat_bridge_doctor_reports_malformed_mapped_droid_jsonl():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-bad-droid",
            "Codex Bad Droid",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-bad-droid"),
        )
        factory_home = tmp_dir / "factory"
        sessions_dir = factory_home / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "droid-bad-jsonl.jsonl").write_text("{not json}\n", encoding="utf-8")
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-bad-droid", "droid_session_id": "droid-bad-jsonl"}],
        }), encoding="utf-8")

        report = ct._build_chat_bridge_doctor_report(chat_bridge, factory_home)

        assert report["summary"]["error"] == 1, f"malformed Droid JSONL should be reported as pair error: {report}"
        item = report["items"][0]
        codes = {issue["code"] for issue in item["issues"]}
        assert item["status"] == "error", f"malformed Droid JSONL should not abort or downgrade: {report}"
        assert "droid_source_unreadable" in codes, f"doctor should flag unreadable Droid source: {report}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_doctor_reports_malformed_droid_settings():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-bad-settings",
            "Codex Bad Settings",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-bad-settings"),
        )
        factory_home = tmp_dir / "factory"
        _jsonl_path, settings_path = write_temp_droid_session(factory_home, session_id="droid-bad-settings", title="Droid Bad Settings")
        settings_path.write_text("{not json}\n", encoding="utf-8")
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-bad-settings", "droid_session_id": "droid-bad-settings"}],
        }), encoding="utf-8")

        report = ct._build_chat_bridge_doctor_report(chat_bridge, factory_home)

        assert report["summary"]["error"] == 1, f"malformed Droid settings should be reported as pair error: {report}"
        item = report["items"][0]
        codes = {issue["code"] for issue in item["issues"]}
        assert item["status"] == "error", f"malformed Droid settings should not become normal metadata noise: {report}"
        assert "droid_settings_unreadable" in codes, f"doctor should flag unreadable Droid settings: {report}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_to_codex_import_rolls_back_invalid_rollout():
    import chat_bridge
    import sqlite3

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        bridge = {
            "format": "codex-droid-chat-bridge",
            "version": 1,
            "source": {"app": "droid", "session_id": "bad-droid", "path": ""},
            "session": {"bridge_id": "bad", "title": "Bad", "created_at": "2025-01-02T03:04:05Z", "updated_at": "2025-01-02T03:04:06Z", "provider": "droid", "model": "bad"},
            "work_context": {"primary_cwd": "", "current": {"confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
            "messages": [{"id": "bad-message", "role": "user", "created_at": "2025-01-02T03:04:05Z", "parts": []}],
        }
        try:
            chat_bridge.import_bridge_to_codex(
                bridge,
                codex_dir=ct.CODEX_DIR,
                state_db=ct.STATE_DB,
                sessions_dir=ct.SESSIONS_DIR,
                global_state_path=ct.GLOBAL_STATE,
            )
            raise AssertionError("invalid bridge should fail import")
        except ValueError:
            pass

        conn = sqlite3.connect(str(ct.STATE_DB))
        count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        conn.close()
        rollout_files = list(ct.SESSIONS_DIR.rglob("rollout-*.jsonl")) if ct.SESSIONS_DIR.exists() else []
        assert count == 0, "failed import should not leave a DB row"
        assert not rollout_files, f"failed import should not leave rollout files: {rollout_files}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_import_writes_session_and_mapping():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "codex-small",
                    "timestamp": "2026-05-28T10:00:00Z",
                    "cwd": r"C:\Projects\Bridge",
                    "model_provider": "openai",
                    "model": "gpt-5",
                    "git": {"branch": "feature/bridge", "commit_hash": "b" * 40, "repository_url": "https://example.invalid/bridge.git"},
                },
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello from codex"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "codex reply"}]},
            }),
        ]) + "\n"
        store_temp_session(
            "codex-small",
            "Codex Small",
            r"C:\Projects\Bridge",
            jsonl_text=jsonl_text,
            model_provider="openai",
            model="gpt-5",
            git_branch="feature/bridge",
            git_sha="b" * 40,
        )
        row = ct._fetch_session_rows(session_ids=["codex-small"])[0]
        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        factory_home = tmp_dir / "factory"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=factory_home)

        jsonl_path = Path(summary["droid_jsonl_path"])
        settings_path = Path(summary["droid_settings_path"])
        assert jsonl_path.exists(), "Droid JSONL should be created"
        assert settings_path.exists(), "Droid session settings should be created"
        events = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
        assert events[0]["type"] == "session_start", f"first Droid event should be session_start: {events[0]}"
        assert "hello from codex" in jsonl_path.read_text(encoding="utf-8"), "Droid JSONL should include Codex text"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert settings["model"] == "gpt-5", f"settings should preserve selected model: {settings}"
        assert settings["providerLock"] == "openai", f"settings should preserve provider lock: {settings}"
        mapping = json.loads((factory_home / "chat_bridge_mappings.json").read_text(encoding="utf-8"))
        assert mapping["pairs"][0]["codex_session_id"] == "codex-small", f"mapping should remember Codex id: {mapping}"
        assert mapping["pairs"][0]["droid_session_id"] == summary["droid_session_id"], f"mapping should remember Droid id: {mapping}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_preserves_project_context():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        factory_home.mkdir(parents=True, exist_ok=True)
        (factory_home / "host.json").write_text(
            json.dumps({"schemaVersion": 1, "hostId": "host-project-1"}),
            encoding="utf-8",
        )
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "codex-project",
                    "timestamp": "2026-05-28T10:00:00Z",
                    "cwd": r"C:\Research\nothing",
                    "model_provider": "openai",
                    "model": "gpt-5",
                },
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "project prompt"}]},
            }),
        ]) + "\n"
        store_temp_session("codex-project", "Project Chat", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-project"])[0]
        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=factory_home)
        jsonl_path = Path(summary["droid_jsonl_path"])
        list_jsonl_path = Path(summary["droid_list_jsonl_path"])
        project_dir = factory_home / "sessions" / "-C-Research-nothing"
        assert jsonl_path.parent == project_dir, f"Codex-imported Droid sessions should live in their project directory: {jsonl_path}"
        assert list_jsonl_path == jsonl_path, f"list path should point at the canonical imported session file: {summary}"
        assert list((factory_home / "sessions").rglob(f"{summary['droid_session_id']}.jsonl")) == [jsonl_path], f"import should create one canonical Droid session file: {summary}"
        first_event = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
        assert first_event["cwd"] == r"C:\Research\nothing", f"session_start should preserve cwd: {first_event}"
        assert first_event["hostId"] == "host-project-1", f"session_start should preserve hostId: {first_event}"
        assert first_event["isSessionTitleManuallySet"] is True, f"imported title should be marked manual so Droid does not regenerate it: {first_event}"
        assert "sessionTitleAutoStage" not in first_event, f"manual imported title should not schedule auto title generation: {first_event}"

        session_index = json.loads((factory_home / "sessions-index.json").read_text(encoding="utf-8"))
        entry = next(e for e in session_index["entries"] if e["sessionId"] == summary["droid_session_id"])
        assert entry["cwd"] == r"C:\Research\nothing", f"sessions-index should preserve cwd: {entry}"
        assert entry["hostId"] == "host-project-1", f"sessions-index should preserve hostId: {entry}"

        discovery = json.loads((factory_home / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        discovered = discovery["entries"][summary["droid_session_id"]]
        assert discovered["cwd"] == r"C:\Research\nothing", f"discovery index should preserve cwd: {discovered}"
        assert discovered["directoryPath"] == str(project_dir), f"discovery index should point at the project sessions dir: {discovered}"
        assert str(project_dir) in discovery["projectDirectories"], f"discovery index should track the imported project directory: {discovery}"
        assert jsonl_path.name in discovery["directories"][str(project_dir)]["sessionFiles"], f"project directory snapshot should include the import: {discovery}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_round_trip_preserves_manual_title_and_settings_metadata():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        jsonl_path, settings_path = write_temp_droid_session(tmp, session_id="droid-manual", title="Pinned Review Task")
        events = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
        events[0].update({
            "sessionTitle": "Pinned Review Task",
            "owner": "manual-owner",
            "version": 2,
            "cwd": r"C:\Research\nothing",
            "hostId": "host-manual-1",
            "isSessionTitleManuallySet": True,
            "sessionTitleAutoStage": "first_file_edit",
        })
        jsonl_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["assistantActiveTimeMs"] = 4321
        settings["tokenUsage"] = {"total": 123, "output": 7}
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True, mirror_to_root=False)
        round_trip_events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        round_trip_settings = json.loads(Path(summary["droid_settings_path"]).read_text(encoding="utf-8"))

    first_event = round_trip_events[0]
    assert bridge["session"]["is_title_manually_set"] is True, f"Droid bridge should retain manual title marker: {bridge['session']}"
    assert first_event["title"] == "Pinned Review Task", f"round-trip should preserve imported title text: {first_event}"
    assert first_event["isSessionTitleManuallySet"] is True, f"round-trip should keep manual title flag: {first_event}"
    assert "sessionTitleAutoStage" not in first_event, f"manual title should not be scheduled for regeneration: {first_event}"
    assert first_event["hostId"] == "host-manual-1", f"round-trip should keep original Droid hostId when present: {first_event}"
    assert first_event["owner"] == "manual-owner", f"round-trip should keep original owner: {first_event}"
    assert round_trip_settings["assistantActiveTimeMs"] == 4321, f"assistant active time should survive round-trip: {round_trip_settings}"
    assert round_trip_settings["tokenUsage"] == {"total": 123, "output": 7}, f"token usage should survive round-trip: {round_trip_settings}"


def test_chat_bridge_codex_to_droid_normalizes_extended_windows_cwd():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-extended", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-extended",
            "title": "Extended Path",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:01Z",
            "provider": "openai",
            "model": "gpt-5",
        },
        "work_context": {
            "primary_cwd": r"\\?\C:\Research\nothing",
            "current": {"cwd": r"\\?\C:\Research\nothing", "confidence": "observed"},
            "timeline_complete": False,
            "snapshots": [],
        },
        "messages": [
            {"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "hello"}]},
        ],
        "extras": {},
        "raw_event_refs": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        jsonl_path = Path(summary["droid_jsonl_path"])
        first_event = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
        discovery = json.loads((Path(tmp) / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        discovered = discovery["entries"][summary["droid_session_id"]]

    assert jsonl_path.parent.name == "-C-Research-nothing", f"extended cwd should map to the canonical project directory: {jsonl_path}"
    assert first_event["cwd"] == r"C:\Research\nothing", f"Droid cwd should not keep Windows extended prefix: {first_event}"
    assert discovered["cwd"] == r"C:\Research\nothing", f"discovery cwd should not keep Windows extended prefix: {discovered}"


def test_chat_bridge_codex_to_droid_uses_fresh_discovery_time():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-time", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-time",
            "title": "Timed Chat",
            "created_at": "2025-01-02T03:04:05Z",
            "updated_at": "2025-01-02T03:04:07Z",
            "provider": "openai",
            "model": "gpt-5",
        },
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m1", "role": "user", "created_at": "2025-01-02T03:04:05Z", "parts": [{"type": "text", "text": "hello"}]},
            {"id": "m2", "role": "assistant", "created_at": "2025-01-02T03:04:07Z", "parts": [{"type": "text", "text": "reply"}]},
        ],
        "extras": {},
        "raw_event_refs": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        before_import_ms = int(time.time() * 1000)
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        after_import_ms = int(time.time() * 1000)
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        session_index = json.loads((Path(tmp) / "sessions-index.json").read_text(encoding="utf-8"))
        entry = next(e for e in session_index["entries"] if e["sessionId"] == summary["droid_session_id"])
        discovery = json.loads((Path(tmp) / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        discovered = discovery["entries"][summary["droid_session_id"]]

    expected_created_ms = 1735787045000
    assert before_import_ms - 1000 <= entry["mtime"] <= after_import_ms + 1000, f"Droid mtime should reflect the fresh import: {entry}"
    assert discovered["modifiedTimeMs"] == entry["mtime"], f"discovery modified time should match the fresh import: {discovered}"
    assert discovered["createdTimeMs"] == expected_created_ms, f"discovery created time should preserve source created_at: {discovered}"
    assert [event["timestamp"] for event in events if event.get("type") == "message"] == [
        "2025-01-02T03:04:05Z",
        "2025-01-02T03:04:07Z",
    ], f"fresh discovery time must not rewrite message timestamps: {events}"


def test_chat_bridge_codex_to_droid_writes_droid_valid_tool_inputs_and_parent_chain():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-tools", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-tools",
            "title": "Tool Chat",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:03Z",
            "provider": "openai",
            "model": "gpt-5",
        },
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m-user", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "run command"}]},
            {
                "id": "m-assistant",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:02Z",
                "parts": [
                    {"type": "text", "text": "running"},
                    {"type": "tool_call", "id": "call-1", "name": "shell", "input": "{\"cmd\":\"echo ok\"}"},
                ],
            },
            {"id": "m-tool", "role": "tool", "created_at": "2026-05-28T10:00:03Z", "parts": [{"type": "tool_result", "tool_call_id": "call-1", "content": "ok"}]},
        ],
        "extras": {},
        "raw_event_refs": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        events = [json.loads(line) for line in Path(summary["droid_jsonl_path"]).read_text(encoding="utf-8").splitlines()]

    messages = [event for event in events if event.get("type") == "message"]
    tool_use = messages[1]["message"]["content"][1]
    assert tool_use["input"] == {"cmd": "echo ok"}, f"Droid tool_use input must be an object, not a JSON string: {tool_use}"
    assert "parentId" not in messages[0], f"first Droid message should start the chain: {messages[0]}"
    assert messages[1]["parentId"] == messages[0]["id"], f"second message should point at previous message: {messages}"
    assert messages[2]["parentId"] == messages[1]["id"], f"tool result should point at assistant tool call message: {messages}"


def test_chat_bridge_codex_to_droid_normalizes_native_content_contract():
    import chat_bridge

    png_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+XwP7WQAAAABJRU5ErkJggg=="
    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-content", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-content",
            "title": "Native Content",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:03Z",
            "provider": "openai",
            "model": "gpt-5",
        },
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {
                "id": "assistant-tools",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:01Z",
                "parts": [
                    {"type": "reasoning", "text": "inspect screenshot"},
                    {"type": "tool_call", "id": "call-image", "name": "view_image", "input": {}},
                ],
            },
            {
                "id": "tool-results",
                "role": "tool",
                "created_at": "2026-05-28T10:00:02Z",
                "parts": [
                    {
                        "type": "tool_result",
                        "tool_call_id": "call-image",
                        "content": [
                            {"type": "input_image", "image_url": f"data:image/png;base64,{png_data}"},
                            {"type": "text", "text": "caption"},
                            {"type": "unsupported", "value": 3},
                        ],
                    },
                    {"type": "tool_result", "tool_call_id": "call-object", "content": {"answer": 42}},
                    {"type": "tool_result", "tool_call_id": "call-number", "content": 7},
                    {"type": "tool_result", "tool_call_id": "call-null", "content": None},
                ],
            },
        ],
        "source_events": [],
        "extras": {},
        "raw_event_refs": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])

    chat_bridge._validate_droid_events(events)
    thinking = events[1]["message"]["content"][0]
    results = events[2]["message"]["content"]
    assert thinking["signature"] == "", f"Droid thinking signature must always be a string: {thinking}"
    assert results[0]["content"][0] == {
        "type": "image",
        "source": {"type": "base64", "data": png_data, "media_type": "image/png"},
    }, f"Codex input_image should become a native persisted Droid image: {results[0]}"
    assert results[0]["content"][1] == {"type": "text", "text": "caption"}, f"text tool output should stay native text: {results[0]}"
    assert results[0]["content"][2]["type"] == "text" and '"type":"unsupported"' in results[0]["content"][2]["text"], f"unsupported array blocks should become diagnostic text: {results[0]}"
    assert results[1]["content"] == '{"answer":42}', f"object tool output should become deterministic text: {results[1]}"
    assert results[2]["content"] == "7", f"numeric tool output should become text: {results[2]}"
    assert results[3]["content"] == "null", f"null tool output should become text: {results[3]}"

    invalid_events = json.loads(json.dumps(events))
    invalid_events[2]["message"]["content"][0]["content"] = [{"type": "input_image", "image_url": "data:image/png;base64,AAAA"}]
    try:
        chat_bridge._validate_droid_events(invalid_events)
    except ValueError as exc:
        assert "unsupported tool result content type" in str(exc), f"validator should identify unsupported content: {exc}"
    else:
        raise AssertionError("validator should reject non-native tool result blocks")


def test_chat_bridge_codex_to_droid_rejects_invalid_raw_replay_before_commit():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-invalid", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-invalid",
            "title": "Invalid Replay",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:01Z",
            "provider": "openai",
            "model": "gpt-5",
        },
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [],
        "source_events": [
            {
                "index": 0,
                "timestamp": "2026-05-28T10:00:00Z",
                "source_app": "droid",
                "outer_type": "session_start",
                "payload_type": "session_start",
                "represented_by": "",
                "raw": {"type": "session_start", "id": "droid-invalid", "title": "Invalid Replay", "owner": "test"},
            },
            {
                "index": 1,
                "timestamp": "2026-05-28T10:00:01Z",
                "source_app": "droid",
                "outer_type": "message",
                "payload_type": "message",
                "represented_by": "bad-message",
                "raw": {
                    "type": "message",
                    "id": "bad-message",
                    "timestamp": "2026-05-28T10:00:01Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "call-invalid",
                                "content": [{"type": "input_image", "image_url": "data:image/png;base64,AAAA"}],
                            },
                        ],
                    },
                },
            },
        ],
        "extras": {},
        "raw_event_refs": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        try:
            chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True, compaction_mode="raw")
        except ValueError as exc:
            assert "unsupported tool result content type" in str(exc), f"validator should report the foreign block: {exc}"
        else:
            raise AssertionError("invalid raw replay should fail before commit")
        assert not list((Path(tmp) / "sessions").rglob("*.jsonl")), "invalid replay should not leave a Droid session file"
        assert not (Path(tmp) / "sessions-index.json").exists(), "invalid replay should not update the Droid index"
        assert not (Path(tmp) / "cache" / "session-discovery-index.json").exists(), "invalid replay should not update discovery"


def test_chat_bridge_codex_to_droid_uses_unique_event_ids_for_tool_pairs():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "inspect"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "call-same", "name": "shell", "arguments": "{\"cmd\":\"dir\"}"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-same", "output": "ok"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:03Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "final summary"}]},
            }),
        ]) + "\n"
        store_temp_session("codex-tool-pair", "Tool Pair", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-tool-pair"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        summary = chat_bridge.import_bridge_to_droid(
            bridge,
            factory_home=tmp_dir / "factory",
            preserve_timestamps=True,
            compaction_mode="inline",
        )
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        messages = [event for event in events if event.get("type") == "message"]
        ids = [message["id"] for message in messages]

        assert len(ids) == len(set(ids)), f"Droid event ids must be unique so the UI can render the full chain: {ids}"
        assert messages[-1]["message"]["content"][0]["text"] == "final summary", f"final assistant message should stay at chain tail: {messages[-1]}"
        assert messages[-1]["parentId"] == messages[-2]["id"], f"final assistant message should parent to unique tool result event: {messages[-2:]}"
        tool_use = next(part for event in messages for part in event["message"]["content"] if part.get("type") == "tool_use")
        tool_result = next(part for event in messages for part in event["message"]["content"] if part.get("type") == "tool_result")
        assert tool_use["id"] == "call-same", f"tool_use id should still preserve Codex call_id: {tool_use}"
        assert tool_result["tool_use_id"] == "call-same", f"tool_result should still link to tool_use id: {tool_result}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_groups_parallel_tool_calls_like_droid():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "inspect"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I will inspect files."}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "call-ls", "name": "exec_command", "arguments": "{\"cmd\":\"dir\"}"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "call-read", "name": "exec_command", "arguments": "{\"cmd\":\"type README.md\"}"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:03Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-ls", "output": "index.html\nREADME.md"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:03Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-read", "output": "# Project"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:04Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done"}]},
            }),
        ]) + "\n"
        store_temp_session("codex-tool-group", "Tool Group", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-tool-group"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        bridge_part_groups = [[part["type"] for part in message["parts"]] for message in bridge["messages"]]
        assert bridge_part_groups == [
            ["text"],
            ["text", "tool_call", "tool_call"],
            ["tool_result", "tool_result"],
            ["text"],
        ], f"Codex bridge should group Droid-native parallel tools: {bridge['messages']}"

        summary = chat_bridge.import_bridge_to_droid(
            bridge,
            factory_home=tmp_dir / "factory",
            preserve_timestamps=True,
            compaction_mode="inline",
        )
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        messages = [event for event in events if event.get("type") == "message"]
        droid_part_groups = [[part["type"] for part in event["message"]["content"]] for event in messages]

        assert droid_part_groups == [
            ["text"],
            ["text", "tool_use", "tool_use"],
            ["tool_result", "tool_result"],
            ["text"],
        ], f"Droid session should receive native grouped tool transcript: {messages}"
        assert messages[1]["message"]["content"][1]["id"] == "call-ls", f"first tool id should be preserved: {messages[1]}"
        assert messages[2]["message"]["content"][1]["tool_use_id"] == "call-read", f"second result should link to the second tool: {messages[2]}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_renders_grouped_tool_message_to_codex_in_part_order():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-tools", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-tools",
            "title": "Droid Tool Order",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:04Z",
            "provider": "openai",
            "model": "custom:model",
        },
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {
                "id": "assistant-tools",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:01Z",
                "parts": [
                    {"type": "text", "text": "I will inspect files."},
                    {"type": "tool_call", "id": "call-ls", "name": "LS", "input": {"directory_path": r"C:\Research\nothing"}},
                    {"type": "tool_call", "id": "call-read", "name": "Read", "input": {"file_path": r"C:\Research\nothing\README.md"}},
                ],
            },
            {
                "id": "tool-results",
                "role": "tool",
                "created_at": "2026-05-28T10:00:02Z",
                "parts": [
                    {"type": "tool_result", "tool_call_id": "call-ls", "content": "index.html\nREADME.md"},
                    {"type": "tool_result", "tool_call_id": "call-read", "content": "# Project"},
                ],
            },
        ],
        "extras": {},
        "raw_event_refs": [],
    }

    rendered = chat_bridge._render_codex_rollout(
        bridge,
        "codex-tool-order",
        chat_bridge._ms("2026-05-28T10:00:00Z"),
        chat_bridge._ms("2026-05-28T10:00:04Z"),
    )
    events = [json.loads(line) for line in rendered.splitlines()]
    payload_types = [event.get("payload", {}).get("type") for event in events if event.get("type") == "response_item"]

    assert payload_types == ["message", "function_call", "function_call", "function_call_output", "function_call_output"], f"Codex rollout should preserve grouped Droid part order: {events}"
    assert events[1]["payload"]["content"][0]["text"] == "I will inspect files.", f"assistant text should stay before tool calls: {events}"


def test_chat_bridge_desktop_compat_renders_task_tool_without_payload_loss():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-task", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-task",
            "title": "Droid Task",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:03Z",
            "provider": "openai",
            "model": "custom:model",
        },
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {
                "id": "assistant-task",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:01Z",
                "parts": [
                    {"type": "tool_call", "id": "task-call", "name": "Task", "input": {"description": "inspect bridge behavior"}},
                    {"type": "tool_result", "tool_call_id": "task-call", "content": "subagent result"},
                ],
            },
        ],
        "extras": {},
        "raw_event_refs": [],
    }

    rendered = chat_bridge._render_codex_rollout(
        bridge,
        "codex-task",
        chat_bridge._ms("2026-05-28T10:00:00Z"),
        chat_bridge._ms("2026-05-28T10:00:03Z"),
        codex_desktop_compat=True,
    )
    events = [json.loads(line) for line in rendered.splitlines()]
    response_payloads = [event["payload"] for event in events if event.get("type") == "response_item"]
    call_names = [payload.get("name") for payload in response_payloads if payload.get("type") == "function_call"]

    assert "spawn_agent" in call_names, f"Task should become spawn_agent: {response_payloads}"
    assert "wait_agent" in call_names, f"Task result should become wait_agent: {response_payloads}"
    assert "close_agent" in call_names, f"Task result should close the spawned agent: {response_payloads}"
    assert any(payload.get("type") == "function_call_output" and "subagent result" in str(payload.get("output")) for payload in response_payloads), f"Task output should be preserved: {response_payloads}"


def test_chat_bridge_desktop_compat_session_meta_keeps_target_model():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-model", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-model",
            "title": "Model Transfer",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:01Z",
            "provider": "openai",
            "model": "custom:Wrong-Model",
        },
        "work_context": {"primary_cwd": r"C:\Research\svoi-intake-service", "current": {"cwd": r"C:\Research\svoi-intake-service"}},
        "messages": [{"role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }

    rendered = chat_bridge._render_codex_rollout(
        bridge,
        "codex-model",
        chat_bridge._ms("2026-05-28T10:00:00Z"),
        chat_bridge._ms("2026-05-28T10:00:01Z"),
        target_provider="Stub_API",
        target_model="gpt-5.5",
        codex_desktop_compat=True,
    )
    events = [json.loads(line) for line in rendered.splitlines()]
    session_meta = events[0]["payload"]
    turn_context = next(event["payload"] for event in events if event.get("type") == "turn_context")

    assert session_meta["model_provider"] == "Stub_API", f"session_meta provider should match active Codex config: {session_meta}"
    assert session_meta["model"] == "gpt-5.5", f"session_meta model should match active Codex config so Codex Desktop does not null it: {session_meta}"
    assert turn_context["model"] == "gpt-5.5", f"turn_context model should match session_meta model: {turn_context}"


def test_chat_bridge_desktop_compat_renders_apply_patch_without_payload_loss():
    import chat_bridge

    patch_text = "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch\n"
    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-patch", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-patch",
            "title": "Droid Patch",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:03Z",
            "provider": "openai",
            "model": "custom:model",
        },
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {
                "id": "assistant-patch",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:01Z",
                "parts": [
                    {"type": "tool_call", "id": "patch-call", "name": "apply_patch", "input": {"raw": patch_text}},
                    {"type": "tool_result", "tool_call_id": "patch-call", "content": "Done!"},
                ],
            },
        ],
        "extras": {},
        "raw_event_refs": [],
    }

    rendered = chat_bridge._render_codex_rollout(
        bridge,
        "codex-patch",
        chat_bridge._ms("2026-05-28T10:00:00Z"),
        chat_bridge._ms("2026-05-28T10:00:03Z"),
        codex_desktop_compat=True,
    )
    events = [json.loads(line) for line in rendered.splitlines()]
    response_payloads = [event["payload"] for event in events if event.get("type") == "response_item"]
    event_payloads = [event["payload"] for event in events if event.get("type") == "event_msg"]

    assert any(payload.get("type") == "custom_tool_call" and payload.get("name") == "apply_patch" for payload in response_payloads), f"apply_patch call should render as custom tool: {response_payloads}"
    assert any(payload.get("type") == "custom_tool_call_output" and payload.get("output") == "Done!" for payload in response_payloads), f"apply_patch output should be preserved: {response_payloads}"
    patch_events = [payload for payload in event_payloads if payload.get("type") == "patch_apply_end"]
    assert patch_events, f"apply_patch should emit patch_apply_end: {event_payloads}"
    assert patch_events[0]["success"] is True, f"successful patch result should stay successful: {patch_events[0]}"
    assert "README.md" in patch_events[0]["changes"], f"patch changed file should be preserved: {patch_events[0]}"


def test_chat_bridge_desktop_compat_renders_uppercase_apply_patch_as_custom_tool():
    import chat_bridge

    patch_text = "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch\n"
    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-patch", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-patch",
            "title": "Droid Patch",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:03Z",
            "provider": "openai",
            "model": "custom:model",
        },
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {
                "id": "assistant-patch",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:01Z",
                "parts": [
                    {"type": "tool_call", "id": "patch-call", "name": "ApplyPatch", "input": {"raw": patch_text}},
                    {"type": "tool_result", "tool_call_id": "patch-call", "content": "Done!"},
                ],
            },
        ],
        "extras": {},
        "raw_event_refs": [],
    }

    rendered = chat_bridge._render_codex_rollout(
        bridge,
        "codex-patch",
        chat_bridge._ms("2026-05-28T10:00:00Z"),
        chat_bridge._ms("2026-05-28T10:00:03Z"),
        codex_desktop_compat=True,
    )
    events = [json.loads(line) for line in rendered.splitlines()]
    response_payloads = [event["payload"] for event in events if event.get("type") == "response_item"]

    assert any(payload.get("type") == "custom_tool_call" and payload.get("name") == "apply_patch" for payload in response_payloads), f"ApplyPatch should render as custom tool: {response_payloads}"
    assert any(payload.get("type") == "custom_tool_call_output" and payload.get("output") == "Done!" for payload in response_payloads), f"ApplyPatch output should be preserved: {response_payloads}"
    assert not any(payload.get("type") == "function_call" and payload.get("name") == "exec_command" and "ApplyPatch" in str(payload.get("arguments")) for payload in response_payloads), f"ApplyPatch must not fall back to exec_command: {response_payloads}"


def test_chat_bridge_desktop_compat_apply_patch_results_do_not_repeat_previous_function_output():
    import chat_bridge

    patch_text = "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch\n"
    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "droid", "session_id": "droid-patch-repeat", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "droid-droid-patch-repeat",
            "title": "Droid Patch Repeat",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:04Z",
            "provider": "openai",
            "model": "custom:model",
        },
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {
                "id": "assistant-patch-repeat",
                "role": "assistant",
                "created_at": "2026-05-28T10:00:01Z",
                "parts": [
                    {"type": "tool_call", "id": "exec-call", "name": "exec_command", "input": {"cmd": "echo before", "workdir": r"C:\Research\nothing"}},
                    {"type": "tool_result", "tool_call_id": "exec-call", "content": "before"},
                    {"type": "tool_call", "id": "patch-call-1", "name": "apply_patch", "input": {"raw": patch_text}},
                    {"type": "tool_result", "tool_call_id": "patch-call-1", "content": "Done 1"},
                    {"type": "tool_call", "id": "patch-call-2", "name": "apply_patch", "input": {"raw": patch_text}},
                    {"type": "tool_result", "tool_call_id": "patch-call-2", "content": "Done 2"},
                ],
            },
        ],
        "extras": {},
        "raw_event_refs": [],
    }

    rendered = chat_bridge._render_codex_rollout(
        bridge,
        "codex-patch-repeat",
        chat_bridge._ms("2026-05-28T10:00:00Z"),
        chat_bridge._ms("2026-05-28T10:00:04Z"),
        codex_desktop_compat=True,
    )
    events = [json.loads(line) for line in rendered.splitlines()]
    response_payloads = [event["payload"] for event in events if event.get("type") == "response_item"]
    function_outputs = [payload for payload in response_payloads if payload.get("type") == "function_call_output"]
    custom_outputs = [payload for payload in response_payloads if payload.get("type") == "custom_tool_call_output"]

    assert len(function_outputs) == 1, f"apply_patch results must not repeat prior function output: {response_payloads}"
    assert "before" in str(function_outputs[0].get("output")), f"the original exec output should be preserved: {function_outputs}"
    assert [payload.get("output") for payload in custom_outputs] == ["Done 1", "Done 2"], f"patch outputs should stay custom and ordered: {custom_outputs}"


def test_chat_bridge_codex_to_droid_preserves_lossless_source_events():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        raw_events = [
            {
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "codex-lossless",
                    "timestamp": "2026-05-28T10:00:00Z",
                    "cwd": r"C:\Research\nothing",
                    "git": {"branch": "main", "commit_hash": "c" * 40},
                },
            },
            {
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "model": "gpt-5", "cwd": r"C:\Research\nothing"},
            },
            {
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "inspect repo"}]},
            },
            {
                "timestamp": "2026-05-28T10:00:03Z",
                "type": "response_item",
                "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Need inspect files first."}]},
            },
            {
                "timestamp": "2026-05-28T10:00:04Z",
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "call-1", "name": "shell", "arguments": "{\"cmd\":\"dir\"}"},
            },
            {
                "timestamp": "2026-05-28T10:00:05Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-1", "output": "tool output body"},
            },
            {
                "timestamp": "2026-05-28T10:00:06Z",
                "type": "response_item",
                "payload": {"type": "token_count", "input_tokens": 123, "output_tokens": 45},
            },
            {
                "timestamp": "2026-05-28T10:00:07Z",
                "type": "event_msg",
                "payload": {"type": "mcp_tool_call_end", "call_id": "call-1", "duration_ms": 17},
            },
            {
                "timestamp": "2026-05-28T10:00:08Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "last_agent_message": "done"},
            },
            {
                "timestamp": "2026-05-28T10:00:09Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "final summary"}]},
            },
        ]
        jsonl_text = "".join(json.dumps(event) + "\n" for event in raw_events)
        store_temp_session("codex-lossless", "Lossless Events", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-lossless"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        source_events = bridge.get("source_events") or []
        assert len(source_events) == len(raw_events), f"bridge should preserve every raw Codex event: {source_events}"
        for index, source_event in enumerate(source_events):
            assert source_event["index"] == index, f"source event should keep original index: {source_event}"
            assert source_event["raw"] == raw_events[index], f"source event should keep raw payload: {source_event}"
            assert "outer_type" in source_event and "payload_type" in source_event, f"source event should describe source types: {source_event}"

        payload_types = {event["payload_type"] for event in source_events}
        assert {"task_started", "reasoning", "token_count", "mcp_tool_call_end", "task_complete"} <= payload_types, f"non-message events should survive: {payload_types}"
        represented = {event["payload_type"]: event.get("represented_by") or "" for event in source_events}
        assert represented["message"], f"normalized message source event should point at bridge message: {source_events}"
        assert represented["function_call"], f"tool call should point at a bridge assistant message: {source_events}"
        assert represented["function_call_output"].startswith("codex-tool-result-"), f"tool output should point at synthetic message id: {source_events}"
        assert represented["reasoning"], f"reasoning source event should point at bridge reasoning message: {source_events}"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True)
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        archive_path = Path(summary["droid_source_archive_path"])
        archived_events = chat_bridge._read_droid_source_archive(summary["droid_jsonl_path"])
        assert archive_path.exists(), f"lossless source metadata should be written outside native Droid JSONL: {summary}"
        assert not [event for event in events if event.get("type") == "bridge_source_event"], f"native Droid JSONL should contain no archival event types: {events}"
        assert len(archived_events) == len(source_events), f"source archive should keep every bridge source event: {archived_events}"
        assert archived_events[3]["payload_type"] == "reasoning", f"reasoning should be present in the source archive: {archived_events[3]}"
        assert archived_events[5]["raw"]["payload"]["output"] == "tool output body", f"tool output body should survive losslessly: {archived_events[5]}"
        droid_bridge = chat_bridge.droid_session_to_bridge(summary["droid_jsonl_path"], summary["droid_settings_path"])
        assert droid_bridge["source_events"] == archived_events, f"Droid bridge should restore the external source archive: {droid_bridge['source_events']}"

        discovery = json.loads((tmp_dir / "factory" / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        discovered = discovery["entries"][summary["droid_session_id"]]
        assert discovered["messageCount"] == len(bridge["messages"]), f"lossless metadata should not inflate Droid message count: {discovered}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_raw_replay_from_droid_archive_preserves_native_events():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        raw_events = [
            {
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "codex-raw-replay",
                    "timestamp": "2026-05-28T10:00:00Z",
                    "cwd": r"C:\Research\nothing",
                    "model_provider": "openai",
                    "model": "gpt-5",
                },
            },
            {
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run raw replay"}]},
            },
            {
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "call-raw", "name": "exec_command", "arguments": "{\"cmd\":\"echo raw\"}"},
            },
            {
                "timestamp": "2026-05-28T10:00:03Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-raw", "output": "raw output"},
            },
            {
                "timestamp": "2026-05-28T10:00:04Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "duration_ms": 1000},
            },
        ]
        store_temp_session("codex-raw-replay", "Raw Replay", r"C:\Research\nothing", jsonl_text="".join(json.dumps(event) + "\n" for event in raw_events))
        row = ct._fetch_session_rows(session_ids=["codex-raw-replay"])[0]
        codex_bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])

        droid_summary = chat_bridge.import_bridge_to_droid(codex_bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True)
        droid_bridge = chat_bridge.droid_session_to_bridge(droid_summary["droid_jsonl_path"], droid_summary["droid_settings_path"])
        codex_replay = chat_bridge.import_bridge_to_codex(
            droid_bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
            compaction_mode="raw",
        )
        replay_events = chat_bridge._read_jsonl(codex_replay["rollout_path"])

        assert [event.get("type") for event in replay_events] == [event.get("type") for event in raw_events], f"raw Codex replay should keep native event order: {replay_events}"
        assert replay_events[0]["payload"]["id"] == codex_replay["codex_session_id"], f"replayed session_meta should target the new Codex id: {replay_events[0]}"
        assert replay_events[2]["payload"]["call_id"] == "call-raw", f"tool call id should replay from archived Codex event: {replay_events[2]}"
        assert replay_events[3]["payload"]["output"] == "raw output", f"tool output should replay from archived Codex event: {replay_events[3]}"
        assert not [event for event in replay_events if event.get("payload", {}).get("type") == "bridge_source_events"], f"raw replay should not wrap replayed events again: {replay_events}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_raw_replay_from_codex_archive_preserves_native_events():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        sessions_dir = factory_home / "sessions"
        sessions_dir.mkdir(parents=True)
        droid_jsonl = sessions_dir / "droid-raw-replay.jsonl"
        droid_settings = sessions_dir / "droid-raw-replay.settings.json"
        raw_events = [
            {"type": "session_start", "id": "droid-raw-replay", "title": "Droid Raw Replay", "owner": "test", "version": 2, "cwd": r"C:\Research\nothing"},
            {
                "type": "message",
                "id": "msg-droid",
                "timestamp": "2026-05-28T10:00:01Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "hello droid"}]},
            },
            {
                "type": "compaction_state",
                "id": "compact-droid",
                "timestamp": "2026-05-28T10:00:02Z",
                "summaryText": "native summary",
                "summaryTokens": 7,
                "summaryKind": "llm_summary",
                "removedCount": 1,
            },
        ]
        droid_jsonl.write_text("".join(json.dumps(event) + "\n" for event in raw_events), encoding="utf-8")
        droid_settings.write_text(json.dumps({"model": "custom:Stub-GPT-5.5-1", "providerLock": "openai"}), encoding="utf-8")
        droid_bridge = chat_bridge.droid_session_to_bridge(droid_jsonl, droid_settings)

        codex_summary = chat_bridge.import_bridge_to_codex(
            droid_bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
            compaction_mode="archived",
        )
        row = ct._fetch_session_rows(session_ids=[codex_summary["codex_session_id"]])[0]
        archived_bridge = chat_bridge.codex_session_to_bridge(row, codex_summary["rollout_path"])
        replay_summary = chat_bridge.import_bridge_to_droid(archived_bridge, factory_home=tmp_dir / "factory-replay", preserve_timestamps=True, compaction_mode="raw")
        replay_events = chat_bridge._read_jsonl(replay_summary["droid_jsonl_path"])

        assert [event.get("type") for event in replay_events] == [event.get("type") for event in raw_events], f"raw Droid replay should keep native event order: {replay_events}"
        assert replay_events[0]["id"] == replay_summary["droid_session_id"], f"replayed session_start should target the new Droid id: {replay_events[0]}"
        assert replay_events[1]["message"]["content"][0]["text"] == "hello droid", f"Droid message should replay from archive: {replay_events[1]}"
        assert replay_events[2]["summaryText"] == "native summary", f"Droid compaction should replay from archive: {replay_events[2]}"
        assert not [event for event in replay_events if event.get("type") == "bridge_source_event"], f"raw replay should not wrap replayed events again: {replay_events}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_reasoning_preserves_encrypted_content_for_droid():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        raw_events = [
            {
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": [],
                    "content": None,
                    "encrypted_content": "gAAAAAB-not-transferable",
                },
            },
            {
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "visible"}],
                },
            },
        ]
        store_temp_session("codex-encrypted-source", "Encrypted Source", r"C:\Research\nothing", jsonl_text="".join(json.dumps(event) + "\n" for event in raw_events))
        row = ct._fetch_session_rows(session_ids=["codex-encrypted-source"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        source_events = bridge.get("source_events") or []
        assert len(source_events) == 2, f"source event metadata should remain for diagnostics: {source_events}"
        assert "gAAAAAB-not-transferable" in json.dumps(source_events, ensure_ascii=False), f"encrypted Codex reasoning should stay available for native continuation: {source_events}"
        assert source_events[0]["raw"]["payload"]["type"] == "reasoning", f"sanitized reasoning metadata should remain: {source_events[0]}"
        reasoning_parts = [part for message in bridge["messages"] for part in message.get("parts", []) if part.get("type") == "reasoning"]
        assert reasoning_parts and reasoning_parts[0]["encrypted_content"] == "gAAAAAB-not-transferable", f"Codex reasoning should normalize into a bridge part: {bridge['messages']}"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True, compaction_mode="archived")
        droid_events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        thinking_parts = [
            part
            for event in droid_events
            if event.get("type") == "message"
            for part in event.get("message", {}).get("content", [])
            if part.get("type") == "thinking"
        ]
        assert thinking_parts and thinking_parts[0]["openaiEncryptedContent"] == "gAAAAAB-not-transferable", f"Droid thinking should keep encrypted reasoning: {droid_events}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_thinking_preserves_encrypted_reasoning_for_codex():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        sessions_dir = factory_home / "sessions"
        sessions_dir.mkdir(parents=True)
        jsonl_path = sessions_dir / "droid-thinking.jsonl"
        settings_path = sessions_dir / "droid-thinking.settings.json"
        signature_payload = {
            "id": "rs_droid_1",
            "type": "reasoning",
            "encrypted_content": "gAAAAAB-droid-native",
            "summary": [{"type": "summary_text", "text": "inspected repo"}],
        }
        events = [
            {"type": "session_start", "id": "droid-thinking", "title": "Thinking", "owner": "test", "version": 2, "cwd": r"C:\Research\nothing"},
            {
                "type": "message",
                "id": "assistant-thinking",
                "timestamp": "2026-05-28T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "planning text",
                            "signature": json.dumps(signature_payload),
                            "signatureProvider": "openai",
                            "durationMs": 1234,
                            "openaiEncryptedContent": "gAAAAAB-droid-native",
                            "openaiReasoningId": "rs_droid_1",
                            "openaiReasoningSummary": "inspected repo",
                        },
                        {"type": "text", "text": "final answer"},
                    ],
                },
            },
        ]
        jsonl_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        settings_path.write_text(json.dumps({"model": "custom:Stub-GPT-5.5-1", "providerLock": "openai", "reasoningEffort": "high"}), encoding="utf-8")

        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)
        reasoning_parts = [part for message in bridge["messages"] for part in message.get("parts", []) if part.get("type") == "reasoning"]
        assert reasoning_parts, f"Droid thinking should normalize into bridge reasoning: {bridge['messages']}"
        reasoning = reasoning_parts[0]
        assert reasoning["encrypted_content"] == "gAAAAAB-droid-native", f"encrypted reasoning should be preserved: {reasoning}"
        assert reasoning["reasoning_id"] == "rs_droid_1", f"reasoning id should be preserved: {reasoning}"
        assert reasoning["summary_text"] == "inspected repo", f"reasoning summary should be preserved: {reasoning}"
        assert reasoning["text"] == "planning text", f"plain thinking text should be preserved: {reasoning}"

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
        )
        rollout_events = chat_bridge._read_jsonl(summary["rollout_path"])
        reasoning_events = [event for event in rollout_events if event.get("payload", {}).get("type") == "reasoning"]
        assert reasoning_events, f"Codex rollout should contain native reasoning event: {rollout_events}"
        payload = reasoning_events[0]["payload"]
        assert payload["encrypted_content"] == "gAAAAAB-droid-native", f"Codex reasoning encrypted payload should survive: {payload}"
        assert payload["id"] == "rs_droid_1", f"Codex reasoning id should survive: {payload}"
        assert payload["summary"] == [{"type": "summary_text", "text": "inspected repo"}], f"Codex reasoning summary should survive: {payload}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_round_trip_preserves_unknown_role_and_source_events():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-round-trip-lossless", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-round-trip-lossless",
            "title": "Round Trip Lossless",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:03Z",
            "provider": "Stub_API",
            "model": "gpt-5.5",
        },
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing", "confidence": "observed"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m-unknown", "role": "unknown", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "internal"}]},
            {"id": "m-user", "role": "user", "created_at": "2026-05-28T10:00:02Z", "parts": [{"type": "text", "text": "hello"}]},
        ],
        "source_events": [
            {"index": 0, "timestamp": "2026-05-28T10:00:00Z", "outer_type": "session_meta", "payload_type": "session_meta", "represented_by": "", "raw": {"type": "session_meta"}},
            {"index": 1, "timestamp": "2026-05-28T10:00:01Z", "outer_type": "response_item", "payload_type": "message", "represented_by": "m-unknown", "raw": {"type": "response_item"}},
        ],
        "compactions": [],
        "extras": {},
        "raw_event_refs": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        round_trip = chat_bridge.droid_session_to_bridge(summary["droid_jsonl_path"], summary["droid_settings_path"])

    roles = [message.get("role") for message in round_trip.get("messages") or []]
    assert roles == ["unknown", "user"], f"bridge-only roles should survive Droid round-trip for doctor comparisons: {roles}"
    assert len(round_trip.get("source_events") or []) == len(bridge["source_events"]), f"round-trip source event archive should not be double-counted: {round_trip.get('source_events')}"


def test_chat_bridge_codex_droid_codex_loss_smoke_reports_recovery():
    import chat_bridge
    from collections import Counter

    def canonical_json(value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return value
            return parsed
        return value

    def canonical_tool_input(value):
        parsed = canonical_json(value)
        if isinstance(parsed, dict) and set(parsed.keys()) == {"raw"}:
            return parsed["raw"]
        return parsed

    def part_fingerprints(bridge):
        fingerprints = []
        for message in bridge.get("messages") or []:
            role = message.get("role") or ""
            for part in message.get("parts") or []:
                part_type = part.get("type") or ""
                if part_type == "text":
                    payload = part.get("text") or ""
                elif part_type == "reasoning":
                    payload = {
                        "summary_text": part.get("summary_text") or "",
                        "encrypted_content": part.get("encrypted_content") or "",
                        "reasoning_id": part.get("reasoning_id") or "",
                    }
                elif part_type == "tool_call":
                    payload = {
                        "id": part.get("id") or "",
                        "name": part.get("name") or "",
                        "input": canonical_tool_input(part.get("input")),
                    }
                elif part_type == "tool_result":
                    payload = {
                        "tool_call_id": part.get("tool_call_id") or "",
                        "content": canonical_json(part.get("content")),
                        "is_error": bool(part.get("is_error")),
                    }
                else:
                    payload = canonical_json(part)
                fingerprints.append(json.dumps({"role": role, "type": part_type, "payload": payload}, sort_keys=True, ensure_ascii=False))
        return fingerprints

    def normalized_raw_event(event):
        normalized = json.loads(json.dumps(event))
        payload = normalized.get("payload")
        if isinstance(payload, dict) and payload.get("type") == "session_meta":
            payload["id"] = "<session-id>"
        return normalized

    def percent(numerator, denominator):
        return round((float(numerator) / float(denominator or 1)) * 100.0, 1)

    replacement_history = [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Проверь перенос Codex ↔ Droid"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Нашёл мост и тесты."}]},
    ]
    raw_events = [
        {
            "timestamp": "2026-05-28T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "type": "session_meta",
                "id": "codex-loss-smoke",
                "timestamp": "2026-05-28T10:00:00Z",
                "cwd": r"C:\Users\test\codex-provider-manager",
                "model_provider": "openai",
                "model": "gpt-5",
                "git": {"branch": "codex/tier0-s-tier-sync-pack-search", "commit_hash": "d" * 40},
            },
        },
        {
            "timestamp": "2026-05-28T10:00:01Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "model": "gpt-5", "cwd": r"C:\Users\test\codex-provider-manager"},
        },
        {
            "timestamp": "2026-05-28T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": "<system-reminder>real chats carry hidden environment envelopes</system-reminder>"}],
            },
        },
        {
            "timestamp": "2026-05-28T10:00:03Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Проверь перенос Codex ↔ Droid и процент потерь."}]},
        },
        {
            "timestamp": "2026-05-28T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "id": "rs-smoke-1",
                "summary": [{"type": "summary_text", "text": "Нужно сравнить видимый контент и сырой архив."}],
                "encrypted_content": "gAAAAAB-smoke-not-human-readable",
            },
        },
        {
            "timestamp": "2026-05-28T10:00:05Z",
            "type": "response_item",
            "payload": {"type": "function_call", "call_id": "call-list", "name": "exec_command", "arguments": "{\"cmd\":\"Get-ChildItem\"}"},
        },
        {
            "timestamp": "2026-05-28T10:00:06Z",
            "type": "response_item",
            "payload": {"type": "function_call", "call_id": "call-search", "name": "exec_command", "arguments": "{\"cmd\":\"Select-String -Pattern diagnose_bridge_pair\"}"},
        },
        {
            "timestamp": "2026-05-28T10:00:07Z",
            "type": "response_item",
            "payload": {"type": "function_call", "call_id": "call-missing", "name": "exec_command", "arguments": "{\"cmd\":\"Select-String -Pattern impossible\"}"},
        },
        {
            "timestamp": "2026-05-28T10:00:08Z",
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": "call-list", "output": "chat_bridge.py\ntest_smoke.py"},
        },
        {
            "timestamp": "2026-05-28T10:00:09Z",
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": "call-search", "output": "diagnose_bridge_pair"},
        },
        {
            "timestamp": "2026-05-28T10:00:10Z",
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": "call-missing", "output": "No matches", "is_error": True},
        },
        {
            "timestamp": "2026-05-28T10:00:11Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Нашёл bridge и существующие проверки."}]},
        },
        {
            "timestamp": "2026-05-28T10:00:12Z",
            "type": "response_item",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": 12345, "output_tokens": 678, "total_tokens": 13023}},
                "rate_limits": {"limit_id": "codex", "plan_type": "team"},
            },
        },
        {
            "timestamp": "2026-05-28T10:00:13Z",
            "type": "compacted",
            "payload": {"message": "Compacted after bridge exploration.", "replacement_history": replacement_history},
        },
        {
            "timestamp": "2026-05-28T10:00:14Z",
            "type": "event_msg",
            "payload": {"type": "context_compacted"},
        },
        {
            "timestamp": "2026-05-28T10:00:15Z",
            "type": "event_msg",
            "payload": {"type": "mcp_tool_call_end", "call_id": "call-search", "duration_ms": 42},
        },
        {
            "timestamp": "2026-05-28T10:00:16Z",
            "type": "response_item",
            "payload": {"type": "function_call", "call_id": "call-patch", "name": "apply_patch", "arguments": "*** Begin Patch\n*** End Patch"},
        },
        {
            "timestamp": "2026-05-28T10:00:17Z",
            "type": "response_item",
            "payload": {"type": "function_call_output", "call_id": "call-patch", "output": "Done"},
        },
        {
            "timestamp": "2026-05-28T10:00:18Z",
            "type": "event_msg",
            "payload": {"type": "task_complete", "last_agent_message": "Smoke test complete"},
        },
        {
            "timestamp": "2026-05-28T10:00:19Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Итог: считаем восстановление по архиву и видимому контенту."}]},
        },
    ]
    gap_flags = {
        "real_metadata_context": any((event.get("payload") or {}).get("git") for event in raw_events),
        "hidden_internal_envelope": "<system-reminder>" in json.dumps(raw_events, ensure_ascii=False),
        "non_message_events": any(event.get("type") == "event_msg" for event in raw_events),
        "parallel_tool_calls": [
            (event.get("payload") or {}).get("type")
            for event in raw_events
        ][5:8] == ["function_call", "function_call", "function_call"],
        "tool_error_output": any((event.get("payload") or {}).get("is_error") for event in raw_events),
        "encrypted_reasoning": "encrypted_content" in json.dumps(raw_events),
        "token_and_rate_limit_metadata": "rate_limits" in json.dumps(raw_events),
        "compaction_state": any(event.get("type") == "compacted" or (event.get("payload") or {}).get("type") == "context_compacted" for event in raw_events),
        "mcp_or_external_tool_events": any((event.get("payload") or {}).get("type") == "mcp_tool_call_end" for event in raw_events),
    }

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-loss-smoke",
            "Round Trip Loss Smoke",
            r"C:\Users\test\codex-provider-manager",
            jsonl_text="".join(json.dumps(event, ensure_ascii=False) + "\n" for event in raw_events),
        )
        row = ct._fetch_session_rows(session_ids=["codex-loss-smoke"])[0]
        codex_bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        droid_summary = chat_bridge.import_bridge_to_droid(codex_bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True)
        droid_bridge = chat_bridge.droid_session_to_bridge(droid_summary["droid_jsonl_path"], droid_summary["droid_settings_path"])
        codex_replay = chat_bridge.import_bridge_to_codex(
            droid_bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
            compaction_mode="raw",
        )
        replay_events = chat_bridge._read_jsonl(codex_replay["rollout_path"])
        doctor_report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-loss-smoke", droid_summary["droid_session_id"])

        original_parts = Counter(part_fingerprints(codex_bridge))
        round_trip_parts = Counter(part_fingerprints(droid_bridge))
        visible_total = sum(original_parts.values())
        visible_matched = sum((original_parts & round_trip_parts).values())
        raw_matched = sum(
            1
            for expected, actual in zip(raw_events, replay_events)
            if normalized_raw_event(expected) == normalized_raw_event(actual)
        )
        source_archive_count = len(droid_bridge.get("source_events") or [])
        recovery_chance = min(
            percent(raw_matched, len(raw_events)),
            percent(visible_matched, visible_total),
            percent(source_archive_count, len(raw_events)),
        )
        smoke_report = {
            "raw_event_recovery_percent": percent(raw_matched, len(raw_events)),
            "normalized_content_retention_percent": percent(visible_matched, visible_total),
            "source_archive_retention_percent": percent(source_archive_count, len(raw_events)),
            "recovery_chance_percent": recovery_chance,
            "loss_percent": round(100.0 - recovery_chance, 1),
            "synthetic_real_gap_coverage_percent": percent(sum(1 for present in gap_flags.values() if present), len(gap_flags)),
            "doctor_status": doctor_report["status"],
            "doctor_error_count": sum(1 for issue in doctor_report["issues"] if issue.get("severity") == "error"),
        }
        print(
            "  INFO  chat bridge round-trip loss smoke: "
            f"recovery={smoke_report['recovery_chance_percent']}%, "
            f"loss={smoke_report['loss_percent']}%, "
            f"raw={smoke_report['raw_event_recovery_percent']}%, "
            f"visible={smoke_report['normalized_content_retention_percent']}%, "
            f"archive={smoke_report['source_archive_retention_percent']}%, "
            f"synthetic_gap_coverage={smoke_report['synthetic_real_gap_coverage_percent']}%, "
            f"doctor={smoke_report['doctor_status']}"
        )

        missing_flags = [name for name, present in gap_flags.items() if not present]
        assert not missing_flags, f"smoke fixture lost real-chat risk coverage: {missing_flags}"
        assert smoke_report["raw_event_recovery_percent"] == 100.0, f"raw Codex event replay should restore the original event picture: {smoke_report}"
        assert smoke_report["normalized_content_retention_percent"] == 100.0, f"visible content should survive Codex→Droid: {smoke_report}"
        assert smoke_report["source_archive_retention_percent"] == 100.0, f"Droid archive should carry every original source event: {smoke_report}"
        assert smoke_report["loss_percent"] == 0.0, f"round-trip smoke should have zero measured loss: {smoke_report}"
        assert smoke_report["doctor_error_count"] == 0, f"doctor should report only expected/warn format drift: {doctor_report}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_doctor_treats_canonical_droid_provider_as_equivalent():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "Stub_API", "model": "gpt-5.5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }
    droid_bridge = {
        "session": {"provider": "openai", "model": "gpt-5.5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    codes = {issue["code"] for issue in report["issues"]}
    assert "provider" not in codes, f"canonical Droid provider should not warn when model is preserved: {report}"
    assert report["status"] == "ok", f"canonical provider equivalent pair should be clean: {report}"


def test_chat_bridge_doctor_categorizes_expected_format_differences():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "Stub_API", "model": "gpt-5.5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "feature", "git_sha": "a" * 40}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }
    droid_bridge = {
        "session": {"provider": "openai", "model": "custom:Stub-GPT-5.5-1"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "main", "git_sha": "a" * 40}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [{"summary_text": "archived"}],
        "source_events": [{"payload_type": "bridge_source_events"}],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    issues = {issue["code"]: issue for issue in report["issues"]}
    assert report["status"] == "warn", f"expected format differences should warn, not error: {report}"
    assert issues["compaction_count"]["severity"] == "expected", f"archived compaction differences should be expected: {report}"
    assert issues["source_event_count"]["severity"] == "expected", f"archived source event differences should be expected: {report}"
    assert issues["git_branch"]["severity"] == "expected", f"branch drift should be expected: {report}"
    assert "model" not in issues, f"canonical custom model names should compare equal: {report}"
    assert "provider" not in issues, f"canonical Droid provider should compare equal with normalized model: {report}"


def test_chat_bridge_doctor_treats_codex_expansion_counts_as_warn():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [
            {"role": "user", "parts": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "parts": [{"type": "text", "text": "summary"}]},
        ],
        "compactions": [],
        "source_events": [],
    }
    droid_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}],
        "compactions": [],
        "source_events": [],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    issues = {issue["code"]: issue for issue in report["issues"]}
    assert report["status"] == "warn", f"Codex-only expansion should warn: {report}"
    assert issues["message_count"]["severity"] == "warn", f"Codex >= Droid message count should warn: {report}"
    assert "role_sequence" not in issues, f"Codex-only suffix should not be structural loss: {report}"
    assert "part_type_sequence" not in issues, f"Codex-only suffix should not be structural loss: {report}"


def test_chat_bridge_doctor_treats_message_splitting_as_warn_when_tools_are_preserved():
    import chat_bridge

    codex_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [
            {"role": "assistant", "parts": [
                {"type": "tool_call", "id": "one", "name": "exec_command", "input": {"cmd": "one"}},
                {"type": "tool_call", "id": "two", "name": "exec_command", "input": {"cmd": "two"}},
            ]},
            {"role": "tool", "parts": [
                {"type": "tool_result", "tool_call_id": "one", "content": "one"},
                {"type": "tool_result", "tool_call_id": "two", "content": "two"},
            ]},
        ],
        "compactions": [],
        "source_events": [],
    }
    droid_bridge = {
        "session": {"provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"git_branch": "", "git_sha": ""}},
        "messages": [
            {"role": "assistant", "parts": [{"type": "tool_call", "id": "one", "name": "Execute", "input": {"command": "one"}}]},
            {"role": "tool", "parts": [{"type": "tool_result", "tool_call_id": "one", "content": "one"}]},
            {"role": "assistant", "parts": [{"type": "tool_call", "id": "two", "name": "Execute", "input": {"command": "two"}}]},
            {"role": "tool", "parts": [{"type": "tool_result", "tool_call_id": "two", "content": "two"}]},
        ],
        "compactions": [],
        "source_events": [],
    }

    report = chat_bridge.diagnose_bridge_pair(codex_bridge, droid_bridge, "codex-a", "droid-a")

    issues = {issue["code"]: issue for issue in report["issues"]}
    assert report["status"] == "warn", f"message splitting with preserved tools should warn, not error: {report}"
    assert issues["message_count"]["severity"] == "warn", f"message count split should be warn: {report}"
    assert issues["role_sequence"]["severity"] == "warn", f"role sequence split should be warn: {report}"
    assert issues["part_type_sequence"]["severity"] == "warn", f"part sequence split should be warn: {report}"


def test_chat_bridge_codex_to_bridge_extracts_compaction_metadata():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        replacement_history = [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "chack this repo"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Checked repository."}]},
        ]
        raw_events = [
            {
                "timestamp": "2026-05-28T08:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "chack this repo"}]},
            },
            {
                "timestamp": "2026-05-28T08:03:32Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Checked repository."}]},
            },
            {
                "timestamp": "2026-05-28T12:20:51Z",
                "type": "compacted",
                "payload": {
                    "message": "Another language model started to solve this problem and produced a summary.",
                    "replacement_history": replacement_history,
                },
            },
            {
                "timestamp": "2026-05-28T12:20:52Z",
                "type": "event_msg",
                "payload": {"type": "context_compacted"},
            },
        ]
        store_temp_session("codex-compact", "Codex Compact", r"C:\Research\nothing", jsonl_text="".join(json.dumps(event) + "\n" for event in raw_events))
        row = ct._fetch_session_rows(session_ids=["codex-compact"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])

        compactions = bridge.get("compactions") or []
        assert len(compactions) == 1, f"Codex compacted event should become bridge compaction: {bridge}"
        compaction = compactions[0]
        assert compaction["source"] == "codex", f"source should be Codex: {compaction}"
        assert compaction["summary_text"].startswith("Another language model"), f"summary text should come from payload.message: {compaction}"
        assert compaction["replacement_history"] == replacement_history, f"replacement_history should be preserved: {compaction}"
        assert compaction["source_event_index"] == 2, f"source index should point at compacted event: {compaction}"
        assert compaction["context_compacted_event_index"] == 3, f"context_compacted marker should be linked: {compaction}"
        assert compaction["anchor_message_id"] == bridge["messages"][1]["id"], f"anchor should be last visible message before compaction: {compaction}"
        assert compaction["anchor_message_index"] == 1, f"anchor index should match normalized messages: {compaction}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_writes_compaction_state_event():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        raw_events = [
            {
                "timestamp": "2026-05-28T08:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "chack this repo"}]},
            },
            {
                "timestamp": "2026-05-28T08:03:32Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Checked repository."}]},
            },
            {
                "timestamp": "2026-05-28T12:20:51Z",
                "type": "compacted",
                "payload": {
                    "message": "Codex compacted summary",
                    "replacement_history": [{"role": "user", "content": "chack this repo"}],
                },
            },
            {
                "timestamp": "2026-05-28T12:20:52Z",
                "type": "event_msg",
                "payload": {"type": "context_compacted"},
            },
        ]
        store_temp_session("codex-compact-droid", "Codex Compact Droid", r"C:\Research\nothing", jsonl_text="".join(json.dumps(event) + "\n" for event in raw_events))
        row = ct._fetch_session_rows(session_ids=["codex-compact-droid"])[0]
        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])

        summary = chat_bridge.import_bridge_to_droid(
            bridge,
            factory_home=tmp_dir / "factory",
            preserve_timestamps=True,
            compaction_mode="inline",
        )
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])

        compaction_events = [event for event in events if event.get("type") == "compaction_state"]
        assert len(compaction_events) == 1, f"Droid JSONL should contain one native compaction_state: {events}"
        compaction = compaction_events[0]
        assert compaction["summaryText"] == "Codex compacted summary", f"summaryText should come from Codex payload.message: {compaction}"
        assert compaction["summaryKind"] == "llm_summary", f"Codex compaction should import as Droid LLM summary: {compaction}"
        assert compaction["removedCount"] == 1, f"removedCount should use replacement_history length: {compaction}"
        assert compaction["anchorMessage"]["id"] == bridge["messages"][1]["id"], f"anchor id should target last pre-compaction message: {compaction}"
        assert compaction["anchorMessage"]["index"] == 1, f"anchor index should target last pre-compaction message: {compaction}"
        message_count = len([event for event in events if event.get("type") == "message"])
        discovery = json.loads((tmp_dir / "factory" / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        assert discovery["entries"][summary["droid_session_id"]]["messageCount"] == message_count, f"compaction_state should not inflate message count: {discovery}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_compaction_import_to_codex_writes_compacted_events():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        sessions_dir = factory_home / "sessions"
        sessions_dir.mkdir(parents=True)
        jsonl_path = sessions_dir / "droid-compact.jsonl"
        settings_path = sessions_dir / "droid-compact.settings.json"
        events = [
            {"type": "session_start", "id": "droid-compact", "title": "Compressed", "owner": "test", "parent": "droid-parent"},
            {
                "type": "compaction_state",
                "id": "compact-1",
                "timestamp": "2026-05-28T13:01:08Z",
                "summaryText": "Droid compacted summary",
                "summaryTokens": 7,
                "summaryKind": "llm_summary",
                "removedCount": 3,
            },
            {
                "type": "message",
                "id": "msg-after",
                "timestamp": "2026-05-28T13:01:09Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "continue"}]},
            },
        ]
        jsonl_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        settings_path.write_text(json.dumps({"model": "custom:model", "providerLock": "openai"}), encoding="utf-8")
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
            compaction_mode="inline",
        )
        rollout_events = chat_bridge._read_jsonl(summary["rollout_path"])

        compacted = [event for event in rollout_events if event.get("type") == "compacted"]
        assert len(compacted) == 1, f"Codex rollout should contain compacted event for Droid summary: {rollout_events}"
        assert compacted[0]["payload"]["message"] == "Droid compacted summary", f"summary should be preserved: {compacted[0]}"
        assert compacted[0]["payload"]["removed_count"] == 3, f"removedCount should be preserved: {compacted[0]}"
        assert any(event.get("payload", {}).get("type") == "context_compacted" for event in rollout_events), f"context_compacted marker should be written: {rollout_events}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_compaction_survives_codex_round_trip():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        sessions_dir = factory_home / "sessions"
        sessions_dir.mkdir(parents=True)
        jsonl_path = sessions_dir / "droid-round-trip.jsonl"
        settings_path = sessions_dir / "droid-round-trip.settings.json"
        system_info = {
            "osName": "win32 10.0.26100",
            "directoryInfo": [{"cmd": "pwd", "out": r"C:\Research\nothing"}],
            "gitInfo": [{"cmd": "git status -b --porcelain | head -n1", "out": "not a git repository"}],
            "guidelinesInfo": [],
            "designGuidelinesInfo": [],
        }
        events = [
            {
                "type": "session_start",
                "id": "droid-round-trip",
                "title": "Compressed",
                "owner": "test",
                "parent": "droid-parent",
                "version": 2,
                "cwd": r"C:\Research\nothing",
            },
            {
                "type": "message",
                "id": "msg-anchor",
                "timestamp": "2026-05-28T13:01:07Z",
                "message": {"role": "user", "content": [{"type": "text", "text": "anchor"}]},
            },
            {
                "type": "compaction_state",
                "id": "compact-rt",
                "timestamp": "2026-05-28T13:01:08Z",
                "summaryText": "Droid summary survives",
                "summaryTokens": 17,
                "summaryKind": "llm_summary",
                "removedCount": 4,
                "anchorMessage": {"id": "msg-anchor", "index": 0},
                "systemInfo": system_info,
                "uiRenderCutoffMessageId": "msg-anchor",
            },
        ]
        jsonl_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        settings_path.write_text(json.dumps({"model": "custom:model", "providerLock": "openai"}), encoding="utf-8")
        bridge = chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
            compaction_mode="inline",
        )
        round_tripped = chat_bridge.codex_session_to_bridge(
            {
                "id": summary["codex_session_id"],
                "title": "Round Trip",
                "cwd": r"C:\Research\nothing",
                "created_at_ms": 1779973267000,
                "updated_at_ms": 1779973268000,
            },
            summary["rollout_path"],
        )

        compaction = (round_tripped.get("compactions") or [])[0]
        assert compaction["summary_text"] == "Droid summary survives", f"summary should survive Codex round-trip: {compaction}"
        assert compaction["summary_tokens"] == 17, f"summary tokens should survive Codex round-trip: {compaction}"
        assert compaction["removed_count"] == 4, f"removed count should survive Codex round-trip: {compaction}"
        assert compaction["parent_session_id"] == "droid-parent", f"Droid parent should survive Codex round-trip: {compaction}"
        assert compaction["anchor_message_id"] == "msg-anchor", f"anchor id should survive Codex round-trip: {compaction}"
        assert compaction["anchor_message_index"] == 0, f"anchor index should survive Codex round-trip: {compaction}"
        assert compaction["system_info"] == system_info, f"systemInfo should survive Codex round-trip: {compaction}"
        assert compaction["ui_render_cutoff_message_id"] == "msg-anchor", f"ui cutoff should survive Codex round-trip: {compaction}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_raw_compaction_mode_skips_native_state():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-raw", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {"bridge_id": "codex-codex-raw", "title": "Raw Mode", "created_at": "2026-05-28T10:00:00Z", "updated_at": "2026-05-28T10:00:03Z", "provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "before"}]},
            {"id": "m2", "role": "assistant", "created_at": "2026-05-28T10:00:02Z", "parts": [{"type": "text", "text": "after"}]},
        ],
        "compactions": [{"source": "codex", "id": "compact-1", "timestamp": "2026-05-28T10:00:02Z", "summary_text": "summary", "removed_count": 1, "anchor_message_id": "m1", "anchor_message_index": 0}],
        "source_events": [
            {"index": 0, "timestamp": "2026-05-28T10:00:01Z", "outer_type": "event_msg", "payload_type": "task_started", "represented_by": "", "raw": {"type": "event_msg", "payload": {"type": "task_started"}}},
            {"index": 1, "timestamp": "2026-05-28T10:00:02Z", "outer_type": "compacted", "payload_type": "compacted", "represented_by": "", "raw": {"type": "compacted", "payload": {"message": "summary"}}},
        ],
        "raw_event_refs": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True, compaction_mode="raw")
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        source_events = chat_bridge._read_droid_source_archive(summary["droid_jsonl_path"])
        discovery = json.loads((Path(tmp) / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))

    assert not [event for event in events if event.get("type") == "compaction_state"], f"raw mode should not write native Droid compaction_state: {events}"
    assert not [event for event in events if event.get("type") == "bridge_source_event"], f"raw mode should keep native Droid JSONL free of archive events: {events}"
    assert len(source_events) == 2, f"raw mode should keep mixed lossless source events in the sidecar: {source_events}"
    assert [event["payload_type"] for event in source_events] == ["task_started", "compacted"], f"raw mode source event order should be preserved: {source_events}"
    assert len([event for event in events if event.get("type") == "message"]) == 2, f"raw mode should keep visible messages: {events}"
    assert discovery["entries"][summary["droid_session_id"]]["messageCount"] == 2, f"source events should not inflate message count: {discovery}"


def test_chat_bridge_codex_to_droid_default_archived_compaction_mode_skips_native_state():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-archived", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {"bridge_id": "codex-codex-archived", "title": "Archived Mode", "created_at": "2026-05-28T10:00:00Z", "updated_at": "2026-05-28T10:00:03Z", "provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "before"}]},
            {"id": "m2", "role": "assistant", "created_at": "2026-05-28T10:00:02Z", "parts": [{"type": "text", "text": "after"}]},
        ],
        "compactions": [{"source": "codex", "id": "compact-archived", "timestamp": "2026-05-28T10:00:02Z", "summary_text": "summary", "removed_count": 1, "anchor_message_id": "m1", "anchor_message_index": 0}],
        "source_events": [
            {"index": 0, "timestamp": "2026-05-28T10:00:02Z", "outer_type": "compacted", "payload_type": "compacted", "represented_by": "", "raw": {"type": "compacted", "payload": {"message": "summary"}}},
        ],
        "raw_event_refs": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        source_events = chat_bridge._read_droid_source_archive(summary["droid_jsonl_path"])

    assert not [event for event in events if event.get("type") == "compaction_state"], f"default archived mode should not activate Droid compaction: {events}"
    assert not [event for event in events if event.get("type") == "bridge_source_event"], f"default archived mode should keep native JSONL free of archive events: {events}"
    assert [event["payload_type"] for event in source_events] == ["compacted"], f"default archived mode should keep compaction only in the source sidecar: {source_events}"
    assert len([event for event in events if event.get("type") == "message"]) == 2, f"default archived mode should keep full visible history: {events}"


def test_chat_bridge_codex_to_droid_native_compaction_mode_writes_continuation_suffix():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-native", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {"bridge_id": "codex-codex-native", "title": "Native Mode", "created_at": "2026-05-28T10:00:00Z", "updated_at": "2026-05-28T10:00:04Z", "provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": r"C:\Research\nothing", "current": {"cwd": r"C:\Research\nothing", "confidence": "observed"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "before-user", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "before user"}]},
            {"id": "before-assistant", "role": "assistant", "created_at": "2026-05-28T10:00:02Z", "parts": [{"type": "text", "text": "before assistant"}]},
            {"id": "after-user", "role": "user", "created_at": "2026-05-28T10:00:03Z", "parts": [{"type": "text", "text": "after compaction"}]},
        ],
        "compactions": [{"source": "codex", "id": "compact-native", "timestamp": "2026-05-28T10:00:02Z", "summary_text": "native summary", "summary_tokens": 5, "removed_count": 2, "anchor_message_id": "before-assistant", "anchor_message_index": 1, "parent_session_id": "droid-parent"}],
        "source_events": [],
        "raw_event_refs": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True, compaction_mode="native")
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])
        discovery = json.loads((Path(tmp) / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))

    session_start = events[0]
    compaction = next(event for event in events if event.get("type") == "compaction_state")
    messages = [event for event in events if event.get("type") == "message"]
    assert session_start["parent"] == "droid-parent", f"native mode should preserve Droid parent when known: {session_start}"
    assert "anchorMessage" not in compaction, f"native Droid continuation should use anchorless summary: {compaction}"
    assert compaction["summaryText"] == "native summary", f"native mode should preserve summary: {compaction}"
    assert [message["id"] for message in messages] == ["after-user"], f"native mode should keep only suffix messages: {messages}"
    assert discovery["entries"][summary["droid_session_id"]]["messageCount"] == 1, f"native mode messageCount should count only suffix messages: {discovery}"


def test_chat_bridge_codex_to_droid_native_compaction_mode_skips_tool_result_suffix_start():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-native-tool", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {"bridge_id": "codex-codex-native-tool", "title": "Native Tool", "created_at": "2026-05-28T10:00:00Z", "updated_at": "2026-05-28T10:00:04Z", "provider": "openai", "model": "gpt-5"},
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "tool-call", "role": "assistant", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "tool_call", "id": "call-1", "name": "shell", "input": {"cmd": "dir"}}]},
            {"id": "tool-result", "role": "tool", "created_at": "2026-05-28T10:00:02Z", "parts": [{"type": "tool_result", "tool_call_id": "call-1", "content": "ok"}]},
            {"id": "after-user", "role": "user", "created_at": "2026-05-28T10:00:03Z", "parts": [{"type": "text", "text": "continue"}]},
        ],
        "compactions": [{"source": "codex", "id": "compact-native-tool", "timestamp": "2026-05-28T10:00:01Z", "summary_text": "summary", "removed_count": 1, "anchor_message_id": "tool-call", "anchor_message_index": 0}],
        "source_events": [],
        "raw_event_refs": [],
    }

    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True, compaction_mode="native")
        events = chat_bridge._read_jsonl(summary["droid_jsonl_path"])

    messages = [event for event in events if event.get("type") == "message"]
    assert [message["id"] for message in messages] == ["after-user"], f"native suffix must not start with tool_result: {messages}"
    assert not any(part.get("type") == "tool_result" for message in messages for part in message["message"]["content"]), f"orphaned tool_result should be skipped: {messages}"


def test_chat_bridge_droid_to_codex_raw_compaction_mode_skips_compacted_events():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        bridge = {
            "format": "codex-droid-chat-bridge",
            "version": 1,
            "source": {"app": "droid", "session_id": "droid-raw", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
            "session": {"bridge_id": "droid-droid-raw", "title": "Droid Raw", "created_at": "2026-05-28T10:00:00Z", "updated_at": "2026-05-28T10:00:02Z", "provider": "openai", "model": "custom:model"},
            "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
            "messages": [{"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "continue"}]}],
            "compactions": [{"source": "droid", "id": "compact-raw", "timestamp": "2026-05-28T10:00:00Z", "summary_text": "summary", "removed_count": 3}],
            "source_events": [],
            "raw_event_refs": [],
        }

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
            compaction_mode="raw",
        )
        events = chat_bridge._read_jsonl(summary["rollout_path"])

        assert not [event for event in events if event.get("type") == "compacted"], f"raw mode should skip Codex compacted events: {events}"
        assert not [event for event in events if event.get("payload", {}).get("type") == "context_compacted"], f"raw mode should skip context_compacted: {events}"
        assert any(event.get("payload", {}).get("type") == "message" for event in events), f"raw mode should still write visible messages: {events}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_to_codex_default_archived_compaction_mode_skips_compacted_events():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        bridge = {
            "format": "codex-droid-chat-bridge",
            "version": 1,
            "source": {"app": "droid", "session_id": "droid-archived", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
            "session": {"bridge_id": "droid-droid-archived", "title": "Droid Archived", "created_at": "2026-05-28T10:00:00Z", "updated_at": "2026-05-28T10:00:02Z", "provider": "openai", "model": "custom:model"},
            "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
            "messages": [{"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "continue"}]}],
            "compactions": [{"source": "droid", "id": "compact-archived", "timestamp": "2026-05-28T10:00:00Z", "summary_text": "summary", "removed_count": 3}],
            "source_events": [],
            "raw_event_refs": [],
        }

        summary = chat_bridge.import_bridge_to_codex(
            bridge,
            codex_dir=tmp_dir,
            state_db=tmp_dir / "state_5.sqlite",
            sessions_dir=tmp_dir / "sessions",
            global_state_path=tmp_dir / "global_state.json",
            preserve_timestamps=True,
        )
        events = chat_bridge._read_jsonl(summary["rollout_path"])

        assert not [event for event in events if event.get("type") == "compacted"], f"default archived mode should skip Codex compacted events: {events}"
        assert not [event for event in events if event.get("payload", {}).get("type") == "context_compacted"], f"default archived mode should skip context_compacted: {events}"
        assert any(event.get("payload", {}).get("type") == "message" for event in events), f"default archived mode should still write visible messages: {events}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_droid_archived_source_events_preserve_encrypted_content():
    import chat_bridge

    with tempfile.TemporaryDirectory() as tmp:
        session_path = Path(tmp) / "droid-archive.jsonl"
        settings_path = Path(tmp) / "droid-archive.settings.json"
        events = [
            {"type": "session_start", "id": "droid-archive", "title": "Archive", "owner": "test"},
            {
                "type": "bridge_source_event",
                "id": "bridge-source-event-000001",
                "timestamp": "2026-05-28T10:00:00Z",
                "sourceIndex": 1,
                "outerType": "response_item",
                "payloadType": "reasoning",
                "representedBy": "",
                "raw": {
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "summary": [{"text": "keep this"}],
                        "encrypted_content": "opaque",
                        "nested": {"encrypted_content": "opaque-nested", "visible": "kept"},
                    },
                },
            },
        ]
        session_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        settings_path.write_text("{}", encoding="utf-8")

        bridge = chat_bridge.droid_session_to_bridge(session_path, settings_path)

    source_events = bridge.get("source_events") or []
    assert len(source_events) == 1, f"archived Droid source event should round-trip: {source_events}"
    assert "opaque" in json.dumps(source_events, ensure_ascii=False), f"encrypted archived source data should remain available for native continuation: {source_events}"
    assert source_events[0]["raw"]["payload"]["nested"]["visible"] == "kept", f"non-encrypted metadata should remain: {source_events[0]}"


def test_chat_bridge_codex_to_droid_can_skip_system_messages():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "repeated codex system prompt"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "real user prompt"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "real assistant reply"}]},
            }),
        ]) + "\n"
        store_temp_session("codex-system", "Codex System", r"C:\Projects\Bridge", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-system"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"], include_system=False)
        assert [m["role"] for m in bridge["messages"]] == ["user", "assistant"], "system messages should be skipped"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp_dir / "factory")
        text = Path(summary["droid_jsonl_path"]).read_text(encoding="utf-8")
        assert "repeated codex system prompt" not in text, "skipped system prompt should not be written to Droid"
        assert "real user prompt" in text, "user content should still be transferred"
        assert "real assistant reply" in text, "assistant content should still be transferred"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_skip_system_filters_internal_envelopes():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<permissions instructions>\nsecret runtime policy"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "content": [{"type": "input_text", "text": "<app-context>\nprivate app context"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>\nC:\\Research\\nothing"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:03Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "chack this repo"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:04Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I will inspect the repository."}]},
            }),
        ]) + "\n"
        store_temp_session("codex-internal", "Codex Internal", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-internal"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"], include_system=False)
        bridge_texts = [part["text"] for message in bridge["messages"] for part in message["parts"] if part.get("type") == "text"]
        assert bridge_texts == ["chack this repo", "I will inspect the repository."], f"internal Codex context should be stripped: {bridge_texts}"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True)
        events = [json.loads(line) for line in Path(summary["droid_jsonl_path"]).read_text(encoding="utf-8").splitlines()]
        messages = [event for event in events if event.get("type") == "message"]
        assert messages[0]["message"]["content"][0]["text"] == "chack this repo", f"Droid first message should be the real user prompt: {messages}"
        raw = Path(summary["droid_jsonl_path"]).read_text(encoding="utf-8")
        assert "<permissions instructions>" not in raw
        assert "<app-context>" not in raw
        assert "<environment_context>" not in raw
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_default_filters_internal_envelopes_from_messages():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "content": [{"type": "input_text", "text": "<permissions instructions>\nruntime policy"}, {"type": "input_text", "text": "<skills_instructions>\nskills"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>\nC:\\Research\\nothing"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "chack this repo"}]},
            }),
        ]) + "\n"
        store_temp_session("codex-internal-default", "Codex Internal Default", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-internal-default"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"], include_system=True)
        bridge_texts = [part["text"] for message in bridge["messages"] for part in message["parts"] if part.get("type") == "text"]
        assert bridge_texts == ["chack this repo"], f"runtime envelopes should not be visible bridge messages by default: {bridge_texts}"
        assert len(bridge.get("source_events") or []) == 3, f"raw source events should remain available for diagnostics: {bridge.get('source_events')}"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True)
        droid_bridge = chat_bridge.droid_session_to_bridge(summary["droid_jsonl_path"], summary["droid_settings_path"])
        droid_texts = [part["text"] for message in droid_bridge["messages"] for part in message["parts"] if part.get("type") == "text"]
        assert droid_texts == ["chack this repo"], f"Droid visible messages should exclude runtime envelopes: {droid_texts}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_preserves_tool_result_errors():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        jsonl_text = "\n".join([
            json.dumps({
                "timestamp": "2026-05-28T10:00:00Z",
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run failing command"}]},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:01Z",
                "type": "response_item",
                "payload": {"type": "function_call", "call_id": "call-fail", "name": "shell", "arguments": "{\"cmd\":\"exit 1\"}"},
            }),
            json.dumps({
                "timestamp": "2026-05-28T10:00:02Z",
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "call-fail", "output": "exit code 1", "is_error": True},
            }),
        ]) + "\n"
        store_temp_session("codex-tool-error", "Tool Error", r"C:\Research\nothing", jsonl_text=jsonl_text)
        row = ct._fetch_session_rows(session_ids=["codex-tool-error"])[0]

        bridge = chat_bridge.codex_session_to_bridge(row, row["rollout_path"])
        tool_result = next(part for message in bridge["messages"] for part in message["parts"] if part.get("type") == "tool_result")
        assert tool_result["is_error"] is True, f"bridge tool_result should preserve Codex error state: {tool_result}"

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp_dir / "factory", preserve_timestamps=True)
        events = [json.loads(line) for line in Path(summary["droid_jsonl_path"]).read_text(encoding="utf-8").splitlines()]
        droid_result = next(part for event in events if event.get("type") == "message" for part in event["message"]["content"] if part.get("type") == "tool_result")
        assert droid_result["is_error"] is True, f"Droid tool_result should preserve error state: {droid_result}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_codex_to_droid_maps_custom_model_settings():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-custom-model", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-custom-model",
            "title": "Custom Model",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:01Z",
            "provider": "openai",
            "model": "gpt-5.5",
        },
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "hello"}]},
        ],
        "extras": {},
        "raw_event_refs": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        factory_home = Path(tmp)
        (factory_home / "settings.json").write_text(json.dumps({
            "customModels": [
                {
                    "id": "custom:Stub-GPT-5.5-1",
                    "model": "gpt-5.5",
                    "displayName": "Stub GPT-5.5",
                    "provider": "openai",
                    "reasoningEffort": "medium",
                }
            ],
            "sessionDefaultSettings": {"model": "custom:Stub-GPT-5.5-1", "reasoningEffort": "medium"},
        }), encoding="utf-8")

        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=factory_home, preserve_timestamps=True)
        settings = json.loads(Path(summary["droid_settings_path"]).read_text(encoding="utf-8"))

    assert settings["model"] == "custom:Stub-GPT-5.5-1", f"Droid session should use matching custom model id: {settings}"
    assert settings["providerLock"] == "openai", f"Droid provider lock should use the custom model provider: {settings}"
    assert settings["reasoningEffort"] == "medium", f"Droid reasoning effort should follow the custom model/default: {settings}"


def test_chat_bridge_codex_to_droid_maps_profile_provider_to_droid_backend():
    import chat_bridge

    bridge = {
        "format": "codex-droid-chat-bridge",
        "version": 1,
        "source": {"app": "codex", "session_id": "codex-profile-provider", "path": "", "exported_at": "2026-05-28T10:00:00Z"},
        "session": {
            "bridge_id": "codex-codex-profile-provider",
            "title": "Profile Provider",
            "created_at": "2026-05-28T10:00:00Z",
            "updated_at": "2026-05-28T10:00:01Z",
            "provider": "Stub_API",
            "model": "gpt-5.5",
            "reasoning_effort": "xhigh",
        },
        "work_context": {"primary_cwd": "", "current": {"cwd": "", "confidence": "unknown"}, "timeline_complete": False, "snapshots": []},
        "messages": [
            {"id": "m1", "role": "user", "created_at": "2026-05-28T10:00:01Z", "parts": [{"type": "text", "text": "hello"}]},
        ],
        "extras": {},
        "raw_event_refs": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        settings = json.loads(Path(summary["droid_settings_path"]).read_text(encoding="utf-8"))

    assert settings["model"] == "gpt-5.5", f"fallback should keep source model when no Droid custom model matches: {settings}"
    assert settings["providerLock"] == "openai", f"GPT-like Codex profile names should map to Droid openai backend: {settings}"
    assert settings["reasoningEffort"] == "xhigh", f"Codex reasoning effort should be preserved when present: {settings}"


def test_operation_history_redacts_and_loads_newest():
    original, tmp_dir = setup_temp_codex_home()
    try:
        ct.record_history("first", api_key="sk-secret", details={"remote_pin": "ABC123", "safe": "shown"})
        ct.record_history("second", provider="HistProv")
        records = ct.load_history(2)
        raw = (tmp_dir / "operation_history.jsonl").read_text(encoding="utf-8")
        assert [r["action"] for r in records] == ["second", "first"], f"history should load newest-first: {records}"
        assert "sk-secret" not in raw, "history should not contain raw API keys"
        assert "ABC123" not in raw, "history should not contain raw PINs"
        assert records[1]["details"]["safe"] == "shown", "safe details should be preserved"
        assert records[1]["api_key"] == "***", "API key field should be redacted"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_provider_action_emits_history_without_secret():
    original, tmp_dir = setup_temp_codex_home()
    try:
        provider_json = tmp_dir / "provider.json"
        provider_json.write_text(json.dumps({
            "name": "HistoryProv",
            "model": "gpt-5",
            "base_url": "https://history.invalid/v1",
            "wire_api": "responses",
        }), encoding="utf-8")
        ct.add_provider(str(provider_json), "sk-history")
        records = ct.load_history(1)
        raw = (tmp_dir / "operation_history.jsonl").read_text(encoding="utf-8")
        assert records[0]["action"] == "add_provider", f"expected add_provider history, got {records}"
        assert records[0]["provider"] == "HistoryProv", f"provider name should be recorded: {records}"
        assert "sk-history" not in raw, "history must not record provider API keys"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_droid_cli_flags_registered():
    parser = ct.build_parser()
    args = parser.parse_args([
        "--droid-models",
        "--droid-doctor",
        "--droid-import-provider", "SavedProv",
        "--droid-use", "custom:model-one",
        "--droid-remove-model", "custom:model-two",
        "--droid-settings", "C:\\Temp\\factory\\settings.json",
        "--droid-with-key",
        "--droid-api-key-env", "DROID_KEY_ENV",
    ])
    assert args.droid_models is True
    assert args.droid_doctor is True
    assert args.droid_import_provider == "SavedProv"
    assert args.droid_use == "custom:model-one"
    assert args.droid_remove_model == "custom:model-two"
    assert args.droid_settings == "C:\\Temp\\factory\\settings.json"
    assert args.droid_with_key is True
    assert args.droid_api_key_env == "DROID_KEY_ENV"


def test_chat_bridge_cli_flags_registered():
    parser = ct.build_parser()
    args = parser.parse_args([
        "--droid-to-codex",
        "--codex-to-droid",
        "--droid-sessions",
        "--codex-sessions",
        "--chat-bridge-doctor",
        "--chat-mapping-plan",
        "--chat-mirror-plan",
        "--chat-mirror-apply",
        "--chat-mirror-confirm",
        "--chat-mirror-direction", "droid-to-codex",
        "--chat-mirror-session", "codex-a,droid-b",
        "--chat-mirror-status", "codex_newer,droid_newer",
        "--chat-mirror-limit", "2",
        "--chat-session", "one,two",
        "--chat-preserve-timestamps",
        "--chat-fresh-timestamps",
        "--chat-pin-old",
        "--chat-backup",
        "--chat-skip-system",
        "--chat-compaction-mode", "native",
    ])
    assert args.droid_to_codex is True
    assert args.codex_to_droid is True
    assert args.droid_sessions is True
    assert args.codex_sessions is True
    assert args.chat_bridge_doctor is True
    assert args.chat_mapping_plan is True
    assert args.chat_mirror_plan is True
    assert args.chat_mirror_apply is True
    assert args.chat_mirror_confirm is True
    assert args.chat_mirror_direction == "droid-to-codex"
    assert args.chat_mirror_session == "codex-a,droid-b"
    assert args.chat_mirror_status == "codex_newer,droid_newer"
    assert args.chat_mirror_limit == 2
    assert args.chat_session == "one,two"
    assert args.chat_preserve_timestamps is True
    assert args.chat_fresh_timestamps is True
    assert args.chat_pin_old is True
    assert args.chat_backup is True
    assert args.chat_skip_system is True
    assert args.chat_compaction_mode == "native"

    default_args = parser.parse_args([])
    assert default_args.chat_compaction_mode == "archived", "chat bridge should default to full visible history with compactions archived"
    assert default_args.chat_backup is False, "chat imports should not create full .codex backups unless requested"
    archived_args = parser.parse_args(["--chat-compaction-mode", "archived"])
    assert archived_args.chat_compaction_mode == "archived", "archived compaction mode should be accepted by CLI"


def test_chat_bridge_cli_missing_droid_session_does_not_backup():
    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        factory_home.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=True,
            codex_to_droid=False,
            chat_session="missing-session",
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_compaction_mode="raw",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        handled = ct.handle_chat_bridge_command(args)

        assert handled is True, "chat bridge CLI command should be handled"
        assert backup_calls == [], f"missing source sessions should not trigger Codex backup: {backup_calls}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_droid_to_codex_import_does_not_backup_by_default():
    import contextlib
    import io
    import sqlite3

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        write_temp_droid_session(factory_home, session_id="droid-import", title="Droid Import")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=True,
            codex_to_droid=False,
            chat_session="droid-import",
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_compaction_mode="raw",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        conn = sqlite3.connect(str(ct.STATE_DB))
        count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        conn.close()
        assert handled is True, "Droid-to-Codex import should be handled"
        assert backup_calls == [], f"default Droid-to-Codex import must not create full .codex backup: {backup_calls}"
        assert count == 1, f"import should still create one Codex session copy, got {count}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_droid_to_codex_import_backs_up_when_requested():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        factory_home = tmp_dir / "factory"
        write_temp_droid_session(factory_home, session_id="droid-import-backup", title="Droid Import Backup")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=True,
            codex_to_droid=False,
            chat_session="droid-import-backup",
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=True,
            chat_old_days=180,
            chat_compaction_mode="raw",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        assert handled is True, "Droid-to-Codex import should be handled"
        assert backup_calls == ["called"], f"--chat-backup should create one full .codex backup: {backup_calls}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_mirror_plan_is_read_only_and_does_not_require_session():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session("codex-plan", "Codex Plan", r"C:\Research\nothing", updated_at_ms=5000)
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-plan", title="Droid Plan")
        os.utime(jsonl_path, (2, 2))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-plan", "droid_session_id": "droid-plan"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=True,
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_old_days=180,
            chat_compaction_mode="raw",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        text = out.getvalue()
        assert handled is True, "chat mirror plan CLI command should be handled"
        assert backup_calls == [], f"read-only mirror plan should not create backups: {backup_calls}"
        assert "Mirror Plan" in text, f"mirror plan output should be visible: {text}"
        assert "codex_newer" in text, f"mirror plan should classify mapped pair: {text}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_doctor_is_read_only_and_reports_pair_differences():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-doctor",
            "Codex Doctor",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-doctor"),
            updated_at_ms=5000,
        )
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-doctor", title="Droid Doctor")
        os.utime(jsonl_path, (5, 5))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-doctor", "droid_session_id": "droid-doctor"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_bridge_doctor=True,
            chat_mirror_plan=False,
            chat_mirror_apply=False,
            chat_mirror_confirm=False,
            chat_mirror_direction="newer",
            chat_mirror_session=None,
            chat_mirror_status=None,
            chat_mirror_limit=None,
            chat_session="codex-doctor",
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        text = out.getvalue()
        assert handled is True, "chat bridge doctor CLI should be handled"
        assert backup_calls == [], f"doctor must not create backups: {backup_calls}"
        assert "Chat Bridge Doctor" in text, f"doctor output should be visible: {text}"
        assert "message_count" in text or "tool_result_count" in text, f"doctor should report structural differences: {text}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_mapping_plan_classifies_stale_and_reexport_read_only():
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-map-plan",
            "Codex Map Plan",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-map-plan"),
            updated_at_ms=5000,
        )
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-map-partial", title="Droid Partial")
        os.utime(jsonl_path, (5, 5))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [
                {
                    "codex_session_id": "codex-map-plan",
                    "droid_session_id": "droid-map-missing",
                    "source_app": "codex",
                    "bridge_id": "codex-codex-map-plan",
                },
                {
                    "codex_session_id": "codex-map-plan",
                    "droid_session_id": "droid-map-partial",
                    "source_app": "codex",
                    "bridge_id": "codex-codex-map-plan",
                },
            ],
        }), encoding="utf-8")

        plan = ct._build_chat_mapping_plan(chat_bridge, factory_home)

        assert plan["read_only"] is True, f"mapping plan must be read-only: {plan}"
        statuses = plan["summary"]["statuses"]
        assert statuses["stale_mapping"] == 1, f"missing target should be classified as stale mapping: {plan}"
        assert statuses["needs_reexport"] == 1, f"structural drift should recommend re-export: {plan}"
        stale = [item for item in plan["items"] if item["status"] == "stale_mapping"][0]
        reexport = [item for item in plan["items"] if item["status"] == "needs_reexport"][0]
        assert stale["recommended_action"] == "review_stale_mapping", f"stale mapping should not auto-clean: {plan}"
        assert reexport["recommended_action"] == "create_fresh_droid_copy", f"Codex source drift should suggest fresh Droid copy: {plan}"
        assert "--codex-to-droid" in reexport["recommended_command"], f"plan should show explicit re-export command: {plan}"
        assert "--chat-session codex-map-plan" in reexport["recommended_command"], f"plan command should identify source session: {plan}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_mapping_plan_reexport_requires_error_severity():
    warn_issues = [
        {"code": "message_count", "severity": "warn"},
        {"code": "compaction_count", "severity": "expected"},
    ]
    error_issues = warn_issues + [{"code": "role_sequence", "severity": "error"}]

    assert ct._chat_mapping_has_error_structural_issue(warn_issues) is False
    assert ct._chat_mapping_has_error_structural_issue(error_issues) is True


def test_chat_bridge_cli_mapping_plan_is_read_only():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-map-cli",
            "Codex Map CLI",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-map-cli"),
        )
        factory_home = tmp_dir / "factory"
        factory_home.mkdir(parents=True, exist_ok=True)
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-map-cli", "droid_session_id": "droid-map-cli-missing", "source_app": "codex", "bridge_id": "codex-codex-map-cli"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_bridge_doctor=False,
            chat_mapping_plan=True,
            chat_mirror_plan=False,
            chat_mirror_apply=False,
            chat_mirror_confirm=False,
            chat_mirror_direction="newer",
            chat_mirror_session=None,
            chat_mirror_status=None,
            chat_mirror_limit=None,
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        text = out.getvalue()
        assert handled is True, "chat mapping plan CLI should be handled"
        assert backup_calls == [], f"mapping plan must not create backups: {backup_calls}"
        assert "Chat Mapping Plan" in text, f"mapping plan output should be visible: {text}"
        assert "stale_mapping" in text, f"mapping plan should classify stale pairs: {text}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def _codex_mirror_apply_jsonl(session_id="codex-copy"):
    return "\n".join([
        json.dumps({
            "timestamp": "2026-05-28T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-05-28T10:00:00Z",
                "cwd": r"C:\Research\nothing",
                "model_provider": "openai",
                "model": "gpt-5",
            },
        }),
        json.dumps({
            "timestamp": "2026-05-28T10:00:01Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "mirror me"}]},
        }),
        json.dumps({
            "timestamp": "2026-05-28T10:00:02Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "mirrored"}]},
        }),
    ]) + "\n"


def test_chat_bridge_cli_mirror_apply_preview_does_not_write_or_backup():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-preview",
            "Codex Preview",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-preview"),
            updated_at_ms=5000,
        )
        factory_home = tmp_dir / "factory"
        factory_home.mkdir(parents=True, exist_ok=True)
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-preview", "droid_session_id": "missing-droid"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=False,
            chat_mirror_apply=True,
            chat_mirror_confirm=False,
            chat_mirror_direction="newer",
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        text = out.getvalue()
        assert handled is True, "mirror apply preview should be handled"
        assert backup_calls == [], f"preview must not create Codex backups: {backup_calls}"
        assert not list(factory_home.rglob("*.jsonl")), f"preview must not create Droid sessions: {list(factory_home.rglob('*.jsonl'))}"
        assert "Preview only" in text, f"preview output should make write safety explicit: {text}"
        assert "would_create_droid" in text, f"preview should list selected action: {text}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_mirror_apply_preview_honors_session_status_and_limit_filters():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-keep",
            "Codex Keep",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-keep"),
            updated_at_ms=5000,
        )
        store_temp_session(
            "codex-drop",
            "Codex Drop",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-drop"),
            updated_at_ms=6000,
        )
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-newer", title="Droid Newer")
        os.utime(jsonl_path, (7, 7))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [
                {"codex_session_id": "codex-keep", "droid_session_id": "missing-keep"},
                {"codex_session_id": "codex-drop", "droid_session_id": "missing-drop"},
                {"codex_session_id": "missing-codex", "droid_session_id": "droid-newer"},
            ],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=False,
            chat_mirror_apply=True,
            chat_mirror_confirm=False,
            chat_mirror_direction="newer",
            chat_mirror_session="codex-keep,missing-codex",
            chat_mirror_status="missing_droid,missing_codex",
            chat_mirror_limit=1,
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        text = out.getvalue()
        assert handled is True, "filtered mirror preview should be handled"
        assert "Selected: 1" in text, f"limit should reduce selected actions: {text}"
        assert "codex=codex-keep" in text, f"session filter should include codex-keep: {text}"
        assert "codex=codex-drop" in text and "session_filter" in text, f"session filter skip should be visible: {text}"
        assert "limit" in text, f"limit skip should be visible: {text}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_mirror_apply_confirm_exports_codex_copy_to_droid():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-export",
            "Codex Export",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-export"),
            updated_at_ms=5000,
        )
        factory_home = tmp_dir / "factory"
        factory_home.mkdir(parents=True, exist_ok=True)
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-export", "droid_session_id": "missing-droid"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=False,
            chat_mirror_apply=True,
            chat_mirror_confirm=True,
            chat_mirror_direction="newer",
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_skip_system=True,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        text = out.getvalue()
        droid_rollouts = list((factory_home / "sessions").rglob("*.jsonl"))
        assert handled is True, "confirmed mirror apply should be handled"
        assert backup_calls == [], f"Codex-to-Droid mirror copy should not back up Codex DB: {backup_calls}"
        assert len(droid_rollouts) == 1, f"confirmed export should create one canonical Droid session file: {droid_rollouts}"
        assert "codex-export ->" in text, f"output should report exported session pair: {text}"
        assert "mirror me" in droid_rollouts[0].read_text(encoding="utf-8"), "Droid copy should contain transferred messages"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_mirror_apply_confirm_imports_droid_copy_to_codex_without_backup_by_default():
    import contextlib
    import io
    import sqlite3

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-old",
            "Codex Old",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-old"),
            updated_at_ms=1000,
        )
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-new", title="Droid New")
        os.utime(jsonl_path, (5, 5))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-old", "droid_session_id": "droid-new"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=False,
            chat_mirror_apply=True,
            chat_mirror_confirm=True,
            chat_mirror_direction="newer",
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        conn = sqlite3.connect(str(ct.STATE_DB))
        count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        conn.close()
        text = out.getvalue()
        assert handled is True, "confirmed Droid-to-Codex mirror apply should be handled"
        assert backup_calls == [], f"default Droid-to-Codex mirror apply must not create full .codex backup: {backup_calls}"
        assert count == 2, f"confirmed import should create one additional Codex session copy, got {count}"
        assert "droid-new ->" in text, f"output should report imported Droid session: {text}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_mirror_apply_confirm_imports_droid_copy_to_codex_with_backup_when_requested():
    import contextlib
    import io

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    backup_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-old-backup",
            "Codex Old Backup",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-old-backup"),
            updated_at_ms=1000,
        )
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-new-backup", title="Droid New Backup")
        os.utime(jsonl_path, (5, 5))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-old-backup", "droid_session_id": "droid-new-backup"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=False,
            chat_mirror_apply=True,
            chat_mirror_confirm=True,
            chat_mirror_direction="newer",
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=True,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        assert handled is True, "confirmed Droid-to-Codex mirror apply should be handled"
        assert backup_calls == ["called"], f"--chat-backup should create one full .codex backup for mirror import: {backup_calls}"
    finally:
        ct.full_backup = original_full_backup
        restore_temp_codex_home(original, tmp_dir)


def test_chat_bridge_cli_mirror_apply_stale_droid_source_does_not_backup_and_records_error():
    import contextlib
    import io
    import sqlite3
    import chat_bridge

    original, tmp_dir = setup_temp_codex_home()
    original_full_backup = ct.full_backup
    original_record_history = ct.record_history
    original_find_droid_session_paths = chat_bridge.find_droid_session_paths
    backup_calls = []
    history_calls = []
    try:
        create_temp_threads_db()
        store_temp_session(
            "codex-stale",
            "Codex Stale",
            r"C:\Research\nothing",
            jsonl_text=_codex_mirror_apply_jsonl("codex-stale"),
            updated_at_ms=1000,
        )
        factory_home = tmp_dir / "factory"
        jsonl_path, _settings_path = write_temp_droid_session(factory_home, session_id="droid-stale", title="Droid Stale")
        os.utime(jsonl_path, (5, 5))
        (ct.CODEX_DIR / "chat_bridge_mappings.json").write_text(json.dumps({
            "version": 1,
            "pairs": [{"codex_session_id": "codex-stale", "droid_session_id": "droid-stale"}],
        }), encoding="utf-8")
        args = argparse.Namespace(
            droid_sessions=False,
            codex_sessions=False,
            droid_to_codex=False,
            codex_to_droid=False,
            chat_mirror_plan=False,
            chat_mirror_apply=True,
            chat_mirror_confirm=True,
            chat_mirror_direction="newer",
            chat_session=None,
            chat_fresh_timestamps=False,
            chat_pin_old=False,
            chat_backup=False,
            chat_old_days=180,
            chat_skip_system=False,
            chat_compaction_mode="inline",
            droid_settings=str(factory_home / "settings.json"),
            project=None,
        )
        ct.full_backup = lambda: backup_calls.append("called") or (tmp_dir / "backup.zip")
        ct.record_history = lambda action, **fields: history_calls.append({"action": action, **fields})
        chat_bridge.find_droid_session_paths = lambda *args, **kwargs: (None, None)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            handled = ct.handle_chat_bridge_command(args)

        conn = sqlite3.connect(str(ct.STATE_DB))
        count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        conn.close()
        text = out.getvalue()
        assert handled is True, "stale confirmed apply should still be handled"
        assert backup_calls == [], f"stale source should not create a backup before any Codex write: {backup_calls}"
        assert count == 1, f"stale source should not create a Codex copy, got {count}"
        assert "ERROR" in text and "Droid session JSONL not found" in text, f"stale source error should be visible: {text}"
        assert history_calls and history_calls[-1].get("status") == "error", f"all-error apply should be recorded as error: {history_calls}"
    finally:
        ct.full_backup = original_full_backup
        ct.record_history = original_record_history
        chat_bridge.find_droid_session_paths = original_find_droid_session_paths
        restore_temp_codex_home(original, tmp_dir)


def test_droid_history_redacts_key():
    original, tmp_dir = setup_temp_codex_home()
    try:
        # Seed a saved Codex provider so --droid-import-provider has something to copy.
        (ct.CODEX_DIR / "config.toml").write_text(
            'model_provider = "RedactProv"\nmodel = "gpt-5.5"\n\n[model_providers.RedactProv]\nname = "RedactProv"\nbase_url = "https://redact.invalid/v1"\nwire_api = "responses"\n',
            encoding="utf-8",
        )
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-droid-secret"}),
            encoding="utf-8",
        )
        ct.save_provider("RedactProv")

        with tempfile.TemporaryDirectory() as td:
            factory_home = Path(td)
            args = argparse.Namespace(
                droid_models=False,
                droid_doctor=False,
                droid_import_provider="RedactProv",
                droid_use=None,
                droid_remove_model=None,
                droid_settings=str(factory_home / "settings.json"),
                droid_with_key=True,
                droid_api_key_env="ALT_NEURO_KEY",
                api_key="sk-droid-secret",
                set_reasoning=None,
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                handled = ct.handle_droid_command(args)

            history_path = tmp_dir / "operation_history.jsonl"
            settings_raw = (factory_home / "settings.local.json").read_text(encoding="utf-8")
            history_raw = history_path.read_text(encoding="utf-8")

            assert handled is True, "Droid command should short-circuit main flow"
            assert "sk-droid-secret" not in stdout.getvalue(), "CLI output should not print raw keys"
            assert "sk-droid-secret" not in history_raw, "history must not record Droid secrets"
            assert "droid_provider_imported" in history_raw, "expected Droid history action"
            assert "sk-droid-secret" in settings_raw, "with-key path should write the requested key to temp settings"
    finally:
        restore_temp_codex_home(original, tmp_dir)


def test_droid_doctor_ignores_legacy_model_issues():
    ctx = {
        "home": Path(tempfile.gettempdir()),
        "settings": {"model": "custom:good"},
        "models": [
            {
                "id": "custom:good",
                "baseUrl": "https://good.invalid/v1",
                "apiKey": "${GOOD_KEY}",
            }
        ],
        "legacy_models": [
            {
                "id": "custom:legacy-broken",
                "baseUrl": "",
                "apiKey": "",
            }
        ],
    }
    report = ct._droid_doctor_report(ctx)
    assert report["ok"] is True, f"legacy-only issues should not fail Droid doctor: {report}"
    assert report["issues"] == []
    assert report["model_count"] == 1
    assert report["legacy_count"] == 1


def test_droid_jsonc_parser_respects_strings():
    text = """
    // top comment
    {
      "url": "https://example.invalid//not-comment",
      "pattern": "/* not a block */",
      "escaped": "\\"//still-string\\"",
      /* block comment */
      "customModels": [{"id": "custom:a", "model": "gpt-5"}]
    }
    """
    data = droid.loads_jsonc(text)
    assert data["url"].endswith("//not-comment")
    assert data["pattern"] == "/* not a block */"
    assert data["escaped"] == '"//still-string"'
    assert data["customModels"][0]["id"] == "custom:a"


def test_droid_strip_jsonc_comments_discards_unterminated_block_comment():
    stripped = droid.strip_jsonc_comments('{"a": 1} /* unterminated comment')
    assert stripped == '{"a": 1} ', f"unterminated block comment should be discarded to EOF: {stripped!r}"


def test_droid_loads_jsonc_empty_returns_empty_dict():
    assert droid.loads_jsonc("") == {}
    assert droid.loads_jsonc("   \n\t") == {}


def test_droid_loads_jsonc_accepts_utf8_bom():
    assert droid.loads_jsonc('\ufeff{"model": "custom:with-bom"}')["model"] == "custom:with-bom"


def test_droid_load_jsonc_file_missing_returns_empty_dict():
    with tempfile.TemporaryDirectory() as td:
        missing = Path(td) / "missing.json"
        assert droid.load_jsonc_file(missing) == {}


def test_droid_merge_settings_recursively_merges_nested_dicts_and_deep_copies():
    base = {
        "model": "base",
        "nested": {
            "keep": 1,
            "replace": {"base_only": True},
            "list_value": [1, 2],
        },
    }
    local = {
        "nested": {
            "replace": {"local_only": True},
            "list_value": ["local"],
            "added": 2,
        }
    }
    merged = droid.merge_settings(base, local)
    assert merged == {
        "model": "base",
        "nested": {
            "keep": 1,
            "replace": {"base_only": True, "local_only": True},
            "list_value": ["local"],
            "added": 2,
        },
    }
    merged["nested"]["replace"]["local_only"] = False
    merged["nested"]["list_value"].append("x")
    assert local["nested"]["replace"]["local_only"] is True, "merged settings must deep-copy local nested dicts"
    assert local["nested"]["list_value"] == ["local"], "merged settings must deep-copy local lists"
    assert base["nested"]["replace"] == {"base_only": True}, "merged settings must not mutate base nested dicts"


def test_droid_normalize_current_model_supports_alias_fields_and_invalid_rows():
    model = droid.normalize_current_model(
        {
            "id": "custom:alias",
            "model": "gpt-5",
            "model_display_name": "Alias Name",
            "base_url": "https://example.invalid/v1",
            "api_key": "${ALIAS_KEY}",
        },
        "settings.json",
    )
    assert model["displayName"] == "Alias Name"
    assert model["baseUrl"] == "https://example.invalid/v1"
    assert model["apiKey"] == "${ALIAS_KEY}"
    assert droid.normalize_current_model(None, "settings.json") is None
    assert droid.normalize_current_model([], "settings.json") is None
    assert droid.normalize_current_model({}, "settings.json") is None
    assert droid.normalize_current_model({"id": "custom:missing-model"}, "settings.json") is None
    assert droid.normalize_current_model({"model": "gpt-5"}, "settings.json") is not None


def test_droid_effective_settings_merges_local_over_base():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "settings.json").write_text(
            json.dumps(
                {
                    "model": "base",
                    "nested": {"keep": 1, "replace": {"base_only": True}},
                    "customModels": [{"id": "custom:base", "model": "base"}],
                }
            ),
            encoding="utf-8",
        )
        (home / "settings.local.json").write_text(
            json.dumps(
                {
                    "model": "local",
                    "nested": {"replace": {"local_only": True}},
                    "customModels": [{"id": "custom:local", "model": "local"}],
                }
            ),
            encoding="utf-8",
        )
        ctx = droid.load_factory_context(home)
        assert ctx["settings"]["model"] == "local"
        assert ctx["settings"]["nested"] == {"keep": 1, "replace": {"base_only": True, "local_only": True}}
        ids = [model["id"] for model in ctx["models"]]
        assert ids == ["custom:local"], f"local customModels should override base: {ids}"
        assert ctx["sources"]["settings_local"].endswith("settings.local.json")


def test_droid_load_factory_context_reports_missing_optional_sources_and_reads_legacy_config():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        ctx_empty = droid.load_factory_context(home)
        assert ctx_empty["sources"]["settings"] == ""
        assert ctx_empty["settings"] == {}

        (home / "settings.json").write_text(
            json.dumps({"model": "base"}),
            encoding="utf-8",
        )
        ctx_without_optional = droid.load_factory_context(home)
        assert ctx_without_optional["sources"]["settings"].endswith("settings.json")
        assert ctx_without_optional["sources"]["settings_local"] == ""
        assert ctx_without_optional["sources"]["legacy_config"] == ""
        assert ctx_without_optional["local_settings"] == {}
        assert ctx_without_optional["legacy_models"] == []

        (home / "config.json").write_text(
            json.dumps(
                {
                    "custom_models": [
                        {
                            "model": "legacy-model",
                            "model_display_name": "Legacy Display",
                            "base_url": "https://legacy.invalid/v1",
                            "api_key": "${LEGACY_KEY}",
                        },
                        {"id": "broken-only"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        ctx_with_legacy = droid.load_factory_context(home)
        assert len(ctx_with_legacy["legacy_models"]) == 1
        legacy = ctx_with_legacy["legacy_models"][0]
        assert legacy["id"] == "custom:legacy-model"
        assert legacy["displayName"] == "Legacy Display"
        assert legacy["baseUrl"] == "https://legacy.invalid/v1"
        assert legacy["apiKey"] == "${LEGACY_KEY}"
        assert legacy["source"] == "config.json"
        assert ctx_with_legacy["sources"]["legacy_config"].endswith("config.json")


def test_droid_use_model_updates_top_level_and_session_defaults():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        droid.write_local_settings(
            home,
            {
                "customModels": [
                    {
                        "id": "custom:local-model",
                        "model": "local-model",
                        "displayName": "Local Model",
                        "baseUrl": "https://local.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${LOCAL_KEY}",
                    }
                ],
                "sessionDefaultSettings": {"model": "custom:stale", "reasoningEffort": "low"},
            },
        )
        (home / "config.json").write_text(
            json.dumps(
                {
                    "custom_models": [
                        {
                            "model": "legacy-model",
                            "model_display_name": "Legacy Model",
                            "base_url": "https://legacy.invalid/v1",
                            "api_key": "${LEGACY_KEY}",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        local_summary = droid.use_model(home, "custom:local-model", reasoning="high")
        local_ctx = droid.load_factory_context(home)
        assert local_summary["model_id"] == "custom:local-model"
        assert local_summary["reasoning"] == "high"
        assert local_ctx["settings"]["model"] == "custom:local-model"
        assert local_ctx["settings"]["reasoningEffort"] == "high"
        assert local_ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:local-model"
        assert local_ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "high"

        legacy_summary = droid.use_model(home, "custom:legacy-model")
        legacy_ctx = droid.load_factory_context(home)
        assert legacy_summary["model_id"] == "custom:legacy-model"
        assert "reasoning" not in legacy_summary
        assert legacy_ctx["settings"]["model"] == "custom:legacy-model"
        assert legacy_ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:legacy-model"
        assert legacy_ctx["settings"]["reasoningEffort"] == "high", "reasoning should stay unchanged when omitted"
        assert legacy_ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "high"


def test_droid_remove_model_only_removes_local_managed_model():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        droid.write_local_settings(
            home,
            {
                "model": "custom:managed-one",
                "customModels": [
                    {
                        "id": "custom:managed-one",
                        "model": "managed-one",
                        "displayName": "Managed One",
                        "baseUrl": "https://managed-one.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${ONE_KEY}",
                        "managedBy": droid.MANAGED_BY,
                    },
                    {
                        "id": "custom:managed-two",
                        "model": "managed-two",
                        "displayName": "Managed Two",
                        "baseUrl": "https://managed-two.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${TWO_KEY}",
                        "managedBy": droid.MANAGED_BY,
                    },
                    {
                        "id": "custom:foreign",
                        "model": "foreign-model",
                        "displayName": "Foreign Model",
                        "baseUrl": "https://foreign.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${FOREIGN_KEY}",
                    },
                ],
                "modelFavorites": [
                    "custom:managed-one",
                    "custom:managed-two",
                    "custom:foreign",
                    "custom:base-only",
                ],
                "sessionDefaultSettings": {
                    "model": "custom:managed-one",
                    "reasoningEffort": "medium",
                },
                "reasoningEffort": "medium",
            },
        )
        (home / "settings.json").write_text(
            json.dumps(
                {
                    "model": "custom:base-only",
                    "customModels": [
                        {
                            "id": "custom:base-only",
                            "model": "base-only",
                            "displayName": "Base Only",
                            "baseUrl": "https://base.invalid/v1",
                            "provider": "openai",
                            "apiKey": "${BASE_KEY}",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        summary = droid.remove_model(home, "custom:managed-one")
        ctx = droid.load_factory_context(home)
        ids = [model["id"] for model in ctx["models"]]

        assert summary["model_id"] == "custom:managed-one"
        assert ids == ["custom:managed-two", "custom:foreign"], f"only the targeted local model should be removed: {ids}"
        assert ctx["local_settings"]["model"] == "custom:managed-two", "selected local model should repoint to a remaining local model"
        assert ctx["local_settings"]["sessionDefaultSettings"]["model"] == "custom:managed-two", "session default should repoint to a remaining local model"
        assert ctx["settings"]["model"] == "custom:managed-two"
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:managed-two"
        assert ctx["settings"]["modelFavorites"] == ["custom:managed-two", "custom:foreign", "custom:base-only"]
        assert summary["backup_path"].exists(), f"removal should create a backup: {summary}"

        try:
            droid.remove_model(home, "custom:base-only")
        except ValueError as exc:
            assert "settings.local.json" in str(exc) or "managed" in str(exc)
        else:
            raise AssertionError("expected ValueError when removing a base-only model")

        try:
            droid.remove_model(home, "custom:foreign")
        except ValueError as exc:
            assert "managed" in str(exc)
        else:
            raise AssertionError("expected ValueError when removing an unmanaged local model")


def test_droid_remove_model_repoints_effective_base_selection():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "settings.json").write_text(
            json.dumps(
                {
                    "model": "custom:managed-one",
                    "sessionDefaultSettings": {"model": "custom:managed-one"},
                }
            ),
            encoding="utf-8",
        )
        droid.write_local_settings(
            home,
            {
                "customModels": [
                    {
                        "id": "custom:managed-one",
                        "model": "managed-one",
                        "displayName": "Managed One",
                        "baseUrl": "https://managed-one.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${ONE_KEY}",
                        "managedBy": droid.MANAGED_BY,
                    },
                    {
                        "id": "custom:managed-two",
                        "model": "managed-two",
                        "displayName": "Managed Two",
                        "baseUrl": "https://managed-two.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${TWO_KEY}",
                        "managedBy": droid.MANAGED_BY,
                    },
                ]
            },
        )

        droid.remove_model(home, "custom:managed-one")
        ctx = droid.load_factory_context(home)

        assert ctx["settings"]["model"] == "custom:managed-two"
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:managed-two"
        assert ctx["local_settings"]["model"] == "custom:managed-two"
        assert ctx["local_settings"]["sessionDefaultSettings"]["model"] == "custom:managed-two"


def test_droid_import_codex_provider_defaults_to_env_key():
    profile = {
        "model_provider": "My Provider",
        "model": "gpt-5.5",
        "model_reasoning_effort": "medium",
        "provider_section": '[model_providers.My_Provider]\nname = "My Provider"\nbase_url = "https://api.example.invalid/v1"\nwire_api = "responses"',
        "auth.json": ct._encode_secret(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-hidden"})),
    }
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        summary = droid.import_codex_provider(home, "My Provider", profile, api_key_env="MY_PROVIDER_API_KEY")
        raw = (home / "settings.local.json").read_text(encoding="utf-8")
        ctx = droid.load_factory_context(home)
        model = ctx["models"][0]

        assert summary["model_id"] == "custom:My_Provider"
        assert summary["added"] == 1
        assert summary["updated"] == 0
        assert model["displayName"] == "My Provider"
        assert model["baseUrl"] == "https://api.example.invalid/v1"
        assert model["model"] == "gpt-5.5"
        assert model["reasoningEffort"] == "medium"
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
        home = Path(td)
        summary = droid.import_codex_provider(home, "KeyProv", profile, with_key=True)
        raw = (home / "settings.local.json").read_text(encoding="utf-8")
        ctx = droid.load_factory_context(home)

        assert summary["model_id"] == "custom:KeyProv"
        assert summary["added"] == 1
        assert summary["updated"] == 0
        assert ctx["models"][0]["apiKey"] == "sk-real"
        assert "sk-real" in raw


def test_droid_codex_profile_to_model_requires_base_url():
    profile = {
        "model_provider": "Broken",
        "model": "gpt-5",
        "provider_section": '[model_providers.Broken]\nname = "Broken"',
    }
    try:
        droid.codex_profile_to_model("Broken", profile)
    except ValueError as exc:
        assert "base_url" in str(exc)
    else:
        raise AssertionError("expected ValueError for provider without base_url")


def test_droid_extract_toml_value_ignores_inline_comments_outside_quotes():
    section = '\n'.join([
        '[model_providers.Commented]',
        'base_url = "https://api.example.invalid/v1#inside" # trailing comment',
        'wire_api = responses # another comment',
    ])
    assert droid.extract_toml_value(section, "base_url") == "https://api.example.invalid/v1#inside"
    assert droid.extract_toml_value(section, "wire_api") == "responses"


def test_droid_extract_openai_key_returns_empty_for_malformed_auth_payloads():
    assert droid.extract_openai_key({"auth.json": "b64:not-valid-base64"}) == ""
    assert droid.extract_openai_key({"auth.json": "b64:bm90LWpzb24="}) == ""


def test_droid_import_codex_provider_avoids_sanitized_id_collisions():
    first_profile = {
        "model_provider": "A/B",
        "model": "gpt-5",
        "provider_section": '[model_providers.A_B]\nname = "A/B"\nbase_url = "https://first.invalid/v1"',
    }
    second_profile = {
        "model_provider": "A B",
        "model": "gpt-5.5",
        "provider_section": '[model_providers.A_B]\nname = "A B"\nbase_url = "https://second.invalid/v1"',
    }
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        first = droid.import_codex_provider(home, "A/B", first_profile)
        second = droid.import_codex_provider(home, "A B", second_profile)
        ctx = droid.load_factory_context(home)
        ids = [model["id"] for model in ctx["models"]]
        names = [model["displayName"] for model in ctx["models"]]

        assert first["model_id"] == "custom:A_B"
        assert second["model_id"] == "custom:A_B-2"
        assert ids == ["custom:A_B", "custom:A_B-2"], ids
        assert names == ["A/B", "A B"], names
        assert ctx["models"][0]["baseUrl"] == "https://first.invalid/v1"
        assert ctx["models"][1]["baseUrl"] == "https://second.invalid/v1"


def test_doctor_report_accepts_chatgpt_auth_without_api_key():
    original, tmp_dir = setup_temp_codex_home()
    old_running = ct.is_codex_running
    ct.is_codex_running = lambda: False
    try:
        (tmp_dir / "config.toml").write_text('model_provider = "openai"\nmodel = "gpt-5"\n', encoding="utf-8")
        (tmp_dir / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
        report = ct.build_doctor_report()
        assert report["auth_ok"], f"chatgpt auth should not require API key: {report}"
        assert not report["provider_health"]["issues"], f"chatgpt auth should not create provider issues: {report}"
    finally:
        ct.is_codex_running = old_running
        restore_temp_codex_home(original, tmp_dir)


def test_doctor_report_flags_provider_health_issues():
    original, tmp_dir = setup_temp_codex_home()
    old_running = ct.is_codex_running
    ct.is_codex_running = lambda: False
    try:
        (tmp_dir / "config.toml").write_text('model_provider = "BadProv"\nmodel = "gpt-5"\n', encoding="utf-8")
        (tmp_dir / "auth.json").write_text(json.dumps({"auth_mode": "apikey"}), encoding="utf-8")
        ct._save_providers({
            "profiles": {
                "BadProv": {
                    "model_provider": "BadProv",
                    "model": "gpt-5",
                    "auth_mode": "apikey",
                    "provider_section": "[model_providers.BadProv]\nname = \"BadProv\"",
                    "auth.json": "",
                    "saved_at": "2026-01-01T00:00:00",
                }
            },
            "active": "BadProv",
        })
        report = ct.build_doctor_report()
        issues = "\n".join(report["provider_health"]["issues"])
        assert "active auth incomplete" in issues, f"missing active API key should be reported: {issues}"
        assert "missing base_url" in issues, f"missing base_url should be reported: {issues}"
        assert "missing API key" in issues, f"missing saved provider key should be reported: {issues}"
    finally:
        ct.is_codex_running = old_running
        restore_temp_codex_home(original, tmp_dir)


# --- Sync tests ---

def _create_current_threads_schema(conn):
    """Create a threads table shaped like current Codex Desktop state_5.sqlite."""
    conn.execute("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            model_provider TEXT NOT NULL,
            cwd TEXT NOT NULL,
            title TEXT NOT NULL,
            sandbox_policy TEXT NOT NULL,
            approval_mode TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            has_user_event INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            archived_at INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT NOT NULL DEFAULT '',
            first_user_message TEXT NOT NULL DEFAULT '',
            agent_nickname TEXT,
            agent_role TEXT,
            memory_mode TEXT NOT NULL DEFAULT 'enabled',
            model TEXT,
            reasoning_effort TEXT,
            agent_path TEXT,
            created_at_ms INTEGER,
            updated_at_ms INTEGER,
            thread_source TEXT,
            preview TEXT NOT NULL DEFAULT ''
        )
    """)


def test_sync_syntax():
    py_compile.compile(
        str(Path(__file__).parent / "codex_sync.py"), doraise=True
    )


def test_sync_imports():
    import codex_sync
    assert hasattr(codex_sync, "generate_pin")
    assert hasattr(codex_sync, "get_local_ip")
    assert hasattr(codex_sync, "find_free_port")
    assert hasattr(codex_sync, "compute_local_hashes")
    assert hasattr(codex_sync, "compute_file_diff")
    assert hasattr(codex_sync, "start_server")
    assert hasattr(codex_sync, "stop_server")


def test_pin_format():
    import codex_sync
    for _ in range(10):
        pin = codex_sync.generate_pin()
        assert len(pin) == 6, f"PIN should be 6 chars, got {len(pin)}"
        assert pin == pin.upper(), f"PIN should be uppercase: {pin}"
        int(pin, 16)  # must be valid hex


def test_compute_hashes():
    import codex_sync, shutil
    tmp = tempfile.mkdtemp()
    try:
        (Path(tmp) / "test.txt").write_text("hello", encoding="utf-8")
        (Path(tmp) / "sub").mkdir()
        (Path(tmp) / "sub" / "inner.py").write_text("print(1)", encoding="utf-8")
        (Path(tmp) / ".git").mkdir()
        (Path(tmp) / ".git" / "config").write_text("git", encoding="utf-8")
        (Path(tmp) / "__pycache__").mkdir()
        (Path(tmp) / "__pycache__" / "cache.pyc").write_text("cache", encoding="utf-8")
        hashes = codex_sync.compute_local_hashes(tmp)
        assert "test.txt" in hashes, "test.txt should be hashed"
        assert "sub/inner.py" in hashes, "sub/inner.py should be hashed"
        assert not any(".git" in h for h in hashes), ".git files should be excluded"
        assert not any("__pycache__" in h for h in hashes), "__pycache__ should be excluded"
    finally:
        shutil.rmtree(tmp)


def test_compute_hashes_excludes_sensitive_and_temp_paths():
    import codex_sync, shutil
    tmp = tempfile.mkdtemp()
    try:
        (Path(tmp) / "src").mkdir()
        (Path(tmp) / "src" / "app.py").write_text("print(1)", encoding="utf-8")
        (Path(tmp) / ".env").write_text("SECRET=1", encoding="utf-8")
        (Path(tmp) / ".env.local").write_text("SECRET=2", encoding="utf-8")
        (Path(tmp) / "secrets").mkdir()
        (Path(tmp) / "secrets" / "prod.key").write_text("key", encoding="utf-8")
        (Path(tmp) / ".worktrees").mkdir()
        (Path(tmp) / ".worktrees" / "wt.txt").write_text("wt", encoding="utf-8")
        (Path(tmp) / "codex_tmp_probe").mkdir()
        (Path(tmp) / "codex_tmp_probe" / "out.txt").write_text("tmp", encoding="utf-8")
        (Path(tmp) / ".codex_tmp_probe").mkdir()
        (Path(tmp) / ".codex_tmp_probe" / "out.txt").write_text("tmp", encoding="utf-8")
        (Path(tmp) / "__pytest_tmp_probe").mkdir()
        (Path(tmp) / "__pytest_tmp_probe" / "out.txt").write_text("tmp", encoding="utf-8")

        hashes = codex_sync.compute_local_hashes(tmp)
        assert "src/app.py" in hashes, "normal project file should be hashed"
        assert ".env" not in hashes, ".env should be excluded"
        assert ".env.local" not in hashes, ".env.local should be excluded"
        assert not any(p.startswith("secrets/") for p in hashes), "secrets dir should be excluded"
        assert not any(p.startswith(".worktrees/") for p in hashes), ".worktrees should be excluded"
        assert not any(p.startswith("codex_tmp_probe/") for p in hashes), "codex temp dirs should be excluded"
        assert not any(p.startswith(".codex_tmp_probe/") for p in hashes), "dot codex temp dirs should be excluded"
        assert not any(p.startswith("__pytest_tmp_probe/") for p in hashes), "dunder pytest temp dirs should be excluded"
    finally:
        shutil.rmtree(tmp)


def test_repo_hashes_include_meta_and_excluded_summary():
    import codex_sync, threading, json, shutil, http.client
    from urllib.parse import quote
    tmp = tempfile.mkdtemp()
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        (Path(tmp) / "src").mkdir()
        include = Path(tmp) / "src" / "app.py"
        include.write_text("print(1)\n", encoding="utf-8")
        (Path(tmp) / "secrets").mkdir()
        (Path(tmp) / "secrets" / "token.txt").write_text("secret", encoding="utf-8")
        (Path(tmp) / ".env").write_text("SECRET=1\n", encoding="utf-8")

        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request(
            "GET",
            "/api/repo-hashes?dir=" + quote(tmp, safe=""),
            headers={"Authorization": "Bearer " + pin},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        assert data["files"]["src/app.py"], "hash entry should be present"
        assert data["meta"]["src/app.py"]["size"] == include.stat().st_size, "size should be reported"
        assert data["meta"]["src/app.py"]["mtime_ms"] > 0, "mtime_ms should be reported"
        assert data["excluded"]["count"] >= 2, "excluded files should be counted"
        sample = data["excluded"]["sample_paths"]
        assert ".env" in sample or "secrets/token.txt" in sample, "excluded sample should include blocked paths"
    finally:
        codex_sync.stop_server(server)
        shutil.rmtree(tmp)


def _sync_request(port, pin, path, payload):
    import http.client
    import json
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(
        "POST",
        path,
        body=json.dumps(payload),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + pin},
    )
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, data


def _start_sync_server_thread(codex_sync, pin):
    import threading
    server, _, _ = codex_sync.start_server(port=0, pin=pin)
    actual_port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, actual_port


def test_push_files_preview_does_not_mutate_remote():
    import codex_sync, shutil
    pin = "ABC123"
    local_dir = tempfile.mkdtemp()
    remote_dir = tempfile.mkdtemp()
    local_server, local_port = _start_sync_server_thread(codex_sync, pin)
    remote_server, remote_port = _start_sync_server_thread(codex_sync, pin)
    try:
        (Path(local_dir) / "replace.txt").write_text("local-new", encoding="utf-8")
        (Path(local_dir) / "add.txt").write_text("brand-new", encoding="utf-8")
        (Path(remote_dir) / "replace.txt").write_text("remote-old", encoding="utf-8")
        (Path(remote_dir) / "remove.txt").write_text("delete-me", encoding="utf-8")

        status, data = _sync_request(local_port, pin, "/api/push/files", {
            "remote_host": "127.0.0.1",
            "remote_port": remote_port,
            "remote_pin": pin,
            "files": ["replace.txt", "add.txt"],
            "delete_files": ["remove.txt"],
            "base_dir": local_dir,
            "remote_dir": remote_dir,
            "preview": True,
            "conflict": "remote",
        })

        assert status == 200, f"Expected 200, got {status}"
        assert data["preview"] is True, "response should indicate preview mode"
        assert data["counts"]["transfer"] == 2, f"expected 2 planned transfers, got {data['counts']}"
        assert data["counts"]["delete"] == 1, f"expected 1 planned delete, got {data['counts']}"
        assert (Path(remote_dir) / "replace.txt").read_text(encoding="utf-8") == "remote-old", "preview must not overwrite remote files"
        assert not (Path(remote_dir) / "add.txt").exists(), "preview must not create remote files"
        assert (Path(remote_dir) / "remove.txt").exists(), "preview must not delete remote files"
        assert not list(Path(remote_dir).glob(".sync_backup_*")), "preview must not create backups"
    finally:
        codex_sync.stop_server(local_server)
        codex_sync.stop_server(remote_server)
        shutil.rmtree(local_dir)
        shutil.rmtree(remote_dir)


def test_pull_files_conflict_policies():
    import codex_sync, shutil
    pin = "ABC123"

    def set_mtime(path, seconds):
        os.utime(path, (seconds, seconds))

    def run_policy(policy):
        base_ts = 1700000000
        local_dir = tempfile.mkdtemp()
        remote_dir = tempfile.mkdtemp()
        local_server, local_port = _start_sync_server_thread(codex_sync, pin)
        remote_server, remote_port = _start_sync_server_thread(codex_sync, pin)
        try:
            remote_older = Path(remote_dir) / "older.txt"
            remote_newer = Path(remote_dir) / "newer.txt"
            remote_added = Path(remote_dir) / "added.txt"
            remote_older.write_text("remote-older", encoding="utf-8")
            remote_newer.write_text("remote-newer", encoding="utf-8")
            remote_added.write_text("remote-added", encoding="utf-8")
            set_mtime(remote_older, base_ts + 1000)
            set_mtime(remote_newer, base_ts + 4000)
            set_mtime(remote_added, base_ts + 5000)

            local_older = Path(local_dir) / "older.txt"
            local_newer = Path(local_dir) / "newer.txt"
            local_remove = Path(local_dir) / "remove.txt"
            local_older.write_text("local-newest", encoding="utf-8")
            local_newer.write_text("local-old", encoding="utf-8")
            local_remove.write_text("keep-or-delete", encoding="utf-8")
            set_mtime(local_older, base_ts + 3000)
            set_mtime(local_newer, base_ts + 2000)
            set_mtime(local_remove, base_ts + 3500)

            status, data = _sync_request(local_port, pin, "/api/pull/files", {
                "remote_host": "127.0.0.1",
                "remote_port": remote_port,
                "remote_pin": pin,
                "files": ["older.txt", "newer.txt", "added.txt"],
                "delete_files": ["remove.txt"],
                "base_dir": local_dir,
                "remote_dir": remote_dir,
                "preview": False,
                "conflict": policy,
            })
            assert status == 200, f"{policy}: expected 200, got {status}"
            return {
                "data": data,
                "older": local_older.read_text(encoding="utf-8"),
                "newer": local_newer.read_text(encoding="utf-8"),
                "added": (Path(local_dir) / "added.txt").read_text(encoding="utf-8"),
                "remove_exists": local_remove.exists(),
            }
        finally:
            codex_sync.stop_server(local_server)
            codex_sync.stop_server(remote_server)
            shutil.rmtree(local_dir)
            shutil.rmtree(remote_dir)

    remote_result = run_policy("remote")
    assert remote_result["older"] == "remote-older", "remote policy should overwrite destination conflicts"
    assert remote_result["newer"] == "remote-newer", "remote policy should apply remote updates"
    assert remote_result["added"] == "remote-added", "remote policy should add missing files"
    assert not remote_result["remove_exists"], "remote policy should delete destination-only files"

    local_result = run_policy("local")
    assert local_result["older"] == "local-newest", "local policy should keep conflicting destination files"
    assert local_result["newer"] == "local-old", "local policy should skip overwriting conflicting files"
    assert local_result["added"] == "remote-added", "local policy should still add missing files"
    assert local_result["remove_exists"], "local policy should skip deletes"

    newer_result = run_policy("newer")
    assert newer_result["older"] == "local-newest", "newer policy should skip when source is older"
    assert newer_result["newer"] == "remote-newer", "newer policy should apply when source mtime is newer"
    assert newer_result["added"] == "remote-added", "newer policy should add missing files"
    assert newer_result["remove_exists"], "newer policy should skip deletes conservatively"


def test_file_diff():
    import codex_sync
    local = {"a.txt": "aaa", "b.txt": "bbb", "c.txt": "ccc"}
    remote = {"a.txt": "aaa", "b.txt": "BBB", "d.txt": "ddd"}
    diff = codex_sync.compute_file_diff(local, remote)
    assert set(diff["unchanged"]) == {"a.txt"}, f"unchanged: {diff['unchanged']}"
    assert set(diff["modified"]) == {"b.txt"}, f"modified: {diff['modified']}"
    assert set(diff["new"]) == {"d.txt"}, f"new: {diff['new']}"
    assert set(diff["deleted"]) == {"c.txt"}, f"deleted: {diff['deleted']}"


def test_path_traversal():
    import codex_sync
    assert codex_sync._validate_path("safe/file.txt", "/project")
    assert not codex_sync._validate_path("../../../etc/passwd", "/project")
    assert not codex_sync._validate_path("/absolute/path", "/project")


def test_chunked_pack_extract():
    """_create_pack writes to temp file, extract_pack reads from file path."""
    import codex_sync, tempfile, os
    with tempfile.TemporaryDirectory() as src_dir:
        with open(os.path.join(src_dir, "test.txt"), "w") as f:
            f.write("hello chunked world")
        zip_path = codex_sync._create_pack(["test.txt"], src_dir)
        assert os.path.exists(zip_path), "zip temp file should exist"
        assert os.path.getsize(zip_path) > 0, "zip should not be empty"
        with tempfile.TemporaryDirectory() as dst_dir:
            result = codex_sync.extract_pack(zip_path, dst_dir, backup=False)
            assert result["errors"] == [], "no errors: {}".format(result["errors"])
            extracted = os.path.join(dst_dir, "test.txt")
            assert os.path.exists(extracted), "extracted file should exist"
            with open(extracted, "r") as f:
                assert f.read() == "hello chunked world"
        os.unlink(zip_path)


def test_delete_files_backs_up_and_removes_targets():
    import codex_sync, tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        keep = Path(tmp) / "keep.txt"
        victim = Path(tmp) / "victim.txt"
        nested = Path(tmp) / "nested" / "gone.txt"
        keep.write_text("keep", encoding="utf-8")
        victim.write_text("delete", encoding="utf-8")
        nested.parent.mkdir()
        nested.write_text("delete nested", encoding="utf-8")

        result = codex_sync.delete_files(["victim.txt", "nested/gone.txt", "../blocked"], tmp, backup=True)
        assert result["deleted"] == 2, "two files should be deleted"
        assert result["errors"], "path traversal should be reported"
        assert keep.exists(), "unselected file should remain"
        assert not victim.exists(), "victim should be deleted"
        assert not nested.exists(), "nested victim should be deleted"
        backups = list(Path(tmp).glob(".sync_backup_*"))
        assert backups, "deleted files should be backed up"
        assert (backups[0] / "victim.txt").exists(), "backup should contain deleted file"


def test_server_ping():
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/ping")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        assert data["status"] == "ok"
        assert data["version"] == "1.0"
    finally:
        codex_sync.stop_server(server)


def test_server_auth_required():
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/manifest")
        resp = conn.getresponse()
        conn.close()
        assert resp.status == 401, f"Expected 401, got {resp.status}"

        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/manifest", headers={"Authorization": f"Bearer {pin}"})
        resp = conn.getresponse()
        conn.close()
        assert resp.status == 200, f"Expected 200 with PIN, got {resp.status}"
    finally:
        codex_sync.stop_server(server)


def test_server_cors():
    import codex_sync, threading
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("OPTIONS", "/api/providers")
        resp = conn.getresponse()
        resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        assert resp.status == 200, f"OPTIONS should return 200, got {resp.status}"
        assert "access-control-allow-origin" in headers, "Missing CORS header"
        assert headers["access-control-allow-origin"] == "*", "CORS should be *"
    finally:
        codex_sync.stop_server(server)


import http.client


def test_manifest_includes_hash():
    """Manifest endpoint returns hash field for auto-sync change detection."""
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/manifest", headers={"Authorization": "Bearer " + pin})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert "hash" in data, "manifest should include hash"
        assert len(data["hash"]) == 16, "hash should be 16 chars, got {}".format(len(data["hash"]))
        assert all(c in "0123456789abcdef" for c in data["hash"]), "hash should be hex"
        assert "timestamp" in data, "manifest should include timestamp"
    finally:
        codex_sync.stop_server(server)


def test_sessions_include_cwd_and_git():
    """Sessions API returns cwd, git_branch, git_sha, is_worktree fields."""
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/sessions", headers={"Authorization": "Bearer " + pin})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert "sessions" in data, "should return sessions key"
        for s in data["sessions"]:
            assert "cwd" in s, "session should include cwd field"
            assert "git_branch" in s, "session should include git_branch"
            assert "git_sha" in s, "session should include git_sha"
            assert "is_worktree" in s, "session should include is_worktree"
    finally:
        codex_sync.stop_server(server)


def test_current_schema_sessions_list_handles_worktree_rows():
    import codex_sync, sqlite3, shutil, json
    orig_db = codex_sync.STATE_DB
    orig_codex_dir = codex_sync.CODEX_DIR
    tmp_dir = tempfile.mkdtemp()
    try:
        db = Path(tmp_dir) / "state_5.sqlite"
        base_repo = Path(tmp_dir) / "repo"
        wt_dir = Path(tmp_dir) / ".codex" / "worktrees" / "abcd" / "repo"
        rollout = Path(tmp_dir) / "rollout-thread-1.jsonl"
        base_repo.mkdir()
        wt_dir.mkdir(parents=True)
        rollout.write_text("{}", encoding="utf-8")

        conn = sqlite3.connect(str(db))
        _create_current_threads_schema(conn)
        conn.execute("""
            INSERT INTO threads
            (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
             sandbox_policy, approval_mode, created_at_ms, updated_at_ms, git_branch, git_sha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "thread-1",
            str(rollout),
            1700000000,
            1700000001,
            "vscode",
            "openai",
            str(wt_dir),
            "Worktree thread",
            json.dumps({"writable_roots": [str(wt_dir), str(base_repo), str(base_repo / ".git")]}),
            "never",
            1700000000000,
            1700000001000,
            "main",
            "a" * 40,
        ))
        conn.commit()
        conn.close()

        codex_sync.STATE_DB = db
        codex_sync.CODEX_DIR = Path(tmp_dir) / ".codex"
        sessions = codex_sync._get_sessions_list()
        assert len(sessions) == 1, "worktree rows should not make session listing empty"
        assert sessions[0]["is_worktree"], "session should be marked as worktree"
        assert sessions[0]["real_cwd"] == str(base_repo), "real_cwd should resolve from sandbox policy"
        assert sessions[0]["has_rollout"], "rollout file should be detected"
    finally:
        codex_sync.STATE_DB = orig_db
        codex_sync.CODEX_DIR = orig_codex_dir
        shutil.rmtree(tmp_dir)


def test_upload_session_inserts_new_row_with_current_schema():
    import codex_sync, sqlite3, shutil
    orig_db = codex_sync.STATE_DB
    orig_sessions_dir = codex_sync.SESSIONS_DIR
    tmp_dir = tempfile.mkdtemp()
    try:
        db = Path(tmp_dir) / "state_5.sqlite"
        conn = sqlite3.connect(str(db))
        _create_current_threads_schema(conn)
        conn.commit()
        conn.close()

        codex_sync.STATE_DB = db
        codex_sync.SESSIONS_DIR = Path(tmp_dir) / "sessions"
        meta = {
            "id": "thread-current",
            "model_provider": "openai",
            "model": "gpt-5",
            "title": "Imported thread",
            "created_at_ms": 1700000000000,
            "updated_at_ms": 1700000001000,
            "archived": False,
            "source": "vscode",
            "cwd": r"C:\Project",
            "git_branch": "main",
            "git_sha": "b" * 40,
            "git_origin_url": "https://example.invalid/repo.git",
            "sandbox_policy": "{}",
            "approval_mode": "on-request",
            "has_user_event": 1,
        }

        codex_sync.SyncHandler._do_upload_session(None, meta, "")

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM threads WHERE id = ?", ("thread-current",)).fetchone()
        conn.close()
        assert row is not None, "new session should be inserted into current Codex schema"
        assert row["created_at"] == 1700000000, "created_at seconds should be populated"
        assert row["updated_at"] == 1700000001, "updated_at seconds should be populated"
        assert row["approval_mode"] == "on-request", "approval_mode should be preserved"
        assert row["has_user_event"] == 1, "has_user_event should be preserved"
        assert row["model"] == "gpt-5", "model should be preserved when column exists"
    finally:
        codex_sync.STATE_DB = orig_db
        codex_sync.SESSIONS_DIR = orig_sessions_dir
        shutil.rmtree(tmp_dir)


def test_dashboard_uses_local_pin_for_protected_local_api():
    text = Path("codex_sync.py").read_text(encoding="utf-8")
    assert "localAuthHeaders()" in text, "dashboard should define local auth headers"
    assert "fetch('/api/providers',{headers:localAuthHeaders()})" in text, "local providers fetch should include auth"
    assert "fetch('/api/sessions',{headers:localAuthHeaders()})" in text, "local sessions fetch should include auth"
    assert "fetch('/api/repo-hashes?dir='+encodeURIComponent(dir),{headers:localAuthHeaders()})" in text, "local repo scan should include auth"


def test_dashboard_file_sync_wires_preview_conflict_and_scan_summary():
    text = Path("codex_sync.py").read_text(encoding="utf-8")
    assert "preview" in text, "dashboard should wire preview flag for file sync"
    assert "conflict" in text, "dashboard should wire conflict mode for file sync"
    assert "excluded" in text, "dashboard should show excluded scan summary"
    assert "remoteFields()" in text and "remote_scheme:remoteScheme" in text, "dashboard should pass remote scheme through local handlers"


def test_sync_tray_syntax():
    """sync_tray.py compiles without syntax errors."""
    path = os.path.join(os.path.dirname(__file__), "sync_tray.py")
    if not os.path.exists(path):
        return
    py_compile.compile(path, doraise=True)


def test_sync_tray_imports_optional():
    """sync_tray.py has graceful import error for missing pystray."""
    path = os.path.join(os.path.dirname(__file__), "sync_tray.py")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "try:" in content and "pystray" in content, "Should have graceful import"
    assert "pip install pystray Pillow" in content, "Should show install instructions"
    assert "_create_icon_image" in content, "Should have icon generation function"
    assert "SyncTrayApp" in content, "Should have SyncTrayApp class"


# --- Pairing tests ---

def test_trusted_device_storage():
    """Trusted device helpers: add, check, remove."""
    import codex_sync, tempfile, json, shutil
    tmp = tempfile.mkdtemp()
    orig = codex_sync.TRUSTED_FILE
    codex_sync.TRUSTED_FILE = codex_sync.Path(tmp) / "trusted_devices.json"
    try:
        data = codex_sync._load_trusted()
        assert "server_id" in data, "should auto-create server_id"
        assert len(data["server_id"]) == 32, "server_id should be 32 hex chars"
        assert "devices" in data, "should have devices dict"
        assert len(data["devices"]) == 0, "should start empty"

        token = "a" * 32
        codex_sync._add_trusted_token(token, "Test Laptop")
        assert codex_sync._is_trusted_token(token), "should recognize trusted token"
        assert not codex_sync._is_trusted_token("wrong"), "should reject unknown token"

        data2 = codex_sync._load_trusted()
        assert len(data2["devices"]) == 1, "should have 1 device"

        codex_sync._remove_trusted_token(codex_sync._hash_token(token))
        assert not codex_sync._is_trusted_token(token), "should remove trust"

        data3 = codex_sync._load_trusted()
        assert len(data3["devices"]) == 0, "should be empty after remove"
    finally:
        codex_sync.TRUSTED_FILE = orig
        shutil.rmtree(tmp)


def test_server_pairing_endpoint():
    """POST /api/pair with correct PIN returns paired, wrong PIN returns 401."""
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # Wrong PIN
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        body = json.dumps({"pin": "WRONG", "client_token": "a" * 32, "device_name": "Bad"})
        conn.request("POST", "/api/pair", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 401, f"Wrong PIN should give 401, got {resp.status}"

        # Correct PIN
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        client_token = "b" * 32
        body = json.dumps({"pin": pin, "client_token": client_token,
                           "device_name": "Test Laptop"})
        conn.request("POST", "/api/pair", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200, f"Correct PIN should give 200, got {resp.status}"
        assert data["status"] == "paired", f"Expected paired, got {data}"
        assert "server_name" in data, "should return server_name"

        # Trusted token should now work for auth
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/manifest",
                     headers={"Authorization": "Bearer " + client_token})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 200, f"Trusted token should work, got {resp.status}"
    finally:
        codex_sync.stop_server(server)


def test_server_local_info():
    """GET /api/local-info returns pin, server_id, server_name without auth."""
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/local-info")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        assert data["pin"] == pin, "should return actual PIN"
        assert len(data["server_id"]) == 32, "server_id should be 32 hex"
        assert "server_name" in data, "should have server_name"
        assert isinstance(data["trusted"], list), "should have trusted list"
    finally:
        codex_sync.stop_server(server)


def test_server_unpair_endpoint():
    """POST /api/unpair removes trusted device."""
    import codex_sync, threading, json
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        # Pair first
        client_token = "c" * 32
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        body = json.dumps({"pin": pin, "client_token": client_token,
                           "device_name": "ToUnpair"})
        conn.request("POST", "/api/pair", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 200

        # Unpair
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        body = json.dumps({"device_name": "ToUnpair"})
        conn.request("POST", "/api/unpair", body=body,
                     headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + pin})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        assert resp.status == 200
        assert data["status"] == "unpaired"

        # Token should no longer work
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("GET", "/api/manifest",
                     headers={"Authorization": "Bearer " + client_token})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 401, "Token should be revoked after unpair"
    finally:
        codex_sync.stop_server(server)


def test_upload_provider_stores_auth_obfuscated():
    import codex_sync, threading, json, shutil
    tmp_dir = tempfile.mkdtemp()
    orig_providers = codex_sync.PROVIDERS_FILE
    codex_sync.PROVIDERS_FILE = Path(tmp_dir) / "providers.json"
    server, pin, port = codex_sync.start_server(port=0)
    actual_port = server.server_address[1]
    codex_sync.SyncHandler.pin = pin
    codex_sync.SyncHandler.server_port = actual_port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        payload = {
            "name": "SecretProvider",
            "model_provider": "SecretProvider",
            "model": "gpt-5",
            "auth_mode": "apikey",
            "provider_section": "[model_providers.SecretProvider]",
            "auth.json": '{"OPENAI_API_KEY":"sk-secret"}',
        }
        conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
        conn.request("POST", "/api/upload/provider", body=json.dumps(payload),
                     headers={"Content-Type": "application/json",
                              "Authorization": "Bearer " + pin})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 200, f"upload should return 200, got {resp.status}"
        data = json.loads(codex_sync.PROVIDERS_FILE.read_text(encoding="utf-8"))
        auth_value = data["profiles"]["SecretProvider"]["auth.json"]
        assert auth_value.startswith("b64:"), "provider auth should be stored obfuscated"
        assert "sk-secret" not in codex_sync.PROVIDERS_FILE.read_text(encoding="utf-8"), "raw key should not be written"
    finally:
        codex_sync.stop_server(server)
        codex_sync.PROVIDERS_FILE = orig_providers
        shutil.rmtree(tmp_dir)


def test_case_insensitive_path_validation():
    import codex_sync
    assert codex_sync._validate_path("file.txt", "C:\\Project")
    assert codex_sync._validate_path("Sub/file.txt", "C:\\Project")
    assert codex_sync._validate_path("file.txt", "c:\\project")
    assert not codex_sync._validate_path("../passwd", "C:\\Project")


def test_get_git_metadata():
    import codex_sync, subprocess, shutil
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init"], cwd=tmp, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp)
        subprocess.run(["git", "config", "remote.origin.url", "https://github.com/test/repo.git"], cwd=tmp)
        with open(os.path.join(tmp, "a.txt"), "w") as f:
            f.write("test")
        subprocess.run(["git", "add", "a.txt"], cwd=tmp)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp)
        
        branch, sha, origin_url = codex_sync.get_git_metadata(tmp)
        assert branch in ("master", "main"), f"expected main/master branch, got {branch}"
        assert len(sha) == 40, f"expected 40-char SHA, got {sha}"
        assert origin_url == "https://github.com/test/repo.git", f"expected origin URL, got {origin_url}"
        
        is_git, is_dirty, dirty_files = codex_sync.check_git_dirty(tmp)
        assert is_git, "should be git repo"
        assert not is_dirty, "should be clean repo"
        
        with open(os.path.join(tmp, "a.txt"), "a") as f:
            f.write("dirty")
        is_git, is_dirty, dirty_files = codex_sync.check_git_dirty(tmp)
        assert is_dirty, "should be dirty repo"
        assert "a.txt" in dirty_files[0], "a.txt should be listed in dirty files"
    finally:
        def on_rm_error(func, path, exc_info):
            import stat
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass
        shutil.rmtree(tmp, onerror=on_rm_error)


def test_project_path_mappings_and_worktree():
    import codex_sync, threading, json, shutil
    orig_db = codex_sync.STATE_DB
    orig_trusted = codex_sync.TRUSTED_FILE
    
    tmp_dir = tempfile.mkdtemp()
    codex_sync.STATE_DB = Path(tmp_dir) / "state_5.sqlite"
    codex_sync.TRUSTED_FILE = Path(tmp_dir) / "trusted_devices.json"
    
    try:
        server, pin, port = codex_sync.start_server(port=0)
        actual_port = server.server_address[1]
        codex_sync.SyncHandler.pin = pin
        codex_sync.SyncHandler.server_port = actual_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        
        try:
            conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
            body = json.dumps({"local_path": "C:\\Local", "remote_path": "D:\\Remote"})
            conn.request("POST", "/api/project-mappings", body=body,
                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + pin})
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
            conn.close()
            assert resp.status == 200
            assert data["status"] == "ok"
            
            conn = http.client.HTTPConnection("127.0.0.1", actual_port, timeout=5)
            conn.request("GET", "/api/project-mappings",
                         headers={"Authorization": "Bearer " + pin})
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
            conn.close()
            assert resp.status == 200
            assert "C:\\Local" in data["project_mappings"]
            assert data["project_mappings"]["C:\\Local"] == "D:\\Remote"
        finally:
            codex_sync.stop_server(server)
    finally:
        codex_sync.STATE_DB = orig_db
        codex_sync.TRUSTED_FILE = orig_trusted
        shutil.rmtree(tmp_dir)


def test_sqlite_sync_updates_existing():
    import codex_sync, shutil, sqlite3
    orig_db = codex_sync.STATE_DB
    tmp_dir = tempfile.mkdtemp()
    codex_sync.STATE_DB = Path(tmp_dir) / "state_5.sqlite"
    
    try:
        conn = sqlite3.connect(str(codex_sync.STATE_DB))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT,
                model_provider TEXT,
                title TEXT,
                created_at_ms INTEGER,
                updated_at_ms INTEGER,
                archived INTEGER,
                source TEXT,
                cwd TEXT,
                git_branch TEXT,
                git_sha TEXT,
                git_origin_url TEXT,
                sandbox_policy TEXT
            )
        """)
        conn.commit()
        conn.close()
        
        meta = {
            "id": "thread-123",
            "model_provider": "openai",
            "title": "Initial Title",
            "created_at_ms": 1000,
            "updated_at_ms": 1000,
            "archived": False,
            "source": "api",
            "cwd": "C:\\Project",
            "git_branch": "main",
            "git_sha": "a" * 40,
            "git_origin_url": "https://github.com/test",
            "sandbox_policy": "{}"
        }
        
        orig_sessions_dir = codex_sync.SESSIONS_DIR
        codex_sync.SESSIONS_DIR = Path(tmp_dir) / "sessions"
        
        try:
            codex_sync.SyncHandler._do_upload_session(None, meta, "")
            
            conn = sqlite3.connect(str(codex_sync.STATE_DB))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM threads WHERE id = ?", ("thread-123",))
            row = cur.fetchone()
            assert row is not None
            assert row["title"] == "Initial Title"
            assert row["updated_at_ms"] == 1000
            assert row["sandbox_policy"] == "{}"
            conn.close()
            
            meta_updated = meta.copy()
            meta_updated["title"] = "Updated Title"
            meta_updated["updated_at_ms"] = 2000
            meta_updated["sandbox_policy"] = '{"allowed": true}'
            
            codex_sync.SyncHandler._do_upload_session(None, meta_updated, "")
            
            conn = sqlite3.connect(str(codex_sync.STATE_DB))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM threads WHERE id = ?", ("thread-123",))
            row = cur.fetchone()
            assert row is not None
            assert row["title"] == "Updated Title"
            assert row["updated_at_ms"] == 2000
            assert row["sandbox_policy"] == '{"allowed": true}'
            conn.close()
            
        finally:
            codex_sync.SESSIONS_DIR = orig_sessions_dir
            
    finally:
        codex_sync.STATE_DB = orig_db
        shutil.rmtree(tmp_dir)


def _make_jwt(email):
    """Build a minimal unsigned JWT id_token whose payload carries `email`."""
    import base64

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    header = b64({"alg": "none", "typ": "JWT"})
    payload = b64({"email": email})
    return f"{header}.{payload}."


def test_get_active_profile_name_distinguishes_openai_logins():
    """Two openai profiles (same model_provider, different emails) must be told apart."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        jwt_a = _make_jwt("alice@example.com")
        jwt_b = _make_jwt("bob@example.com")
        data = {
            "profiles": {
                "openai_alice": {
                    "model_provider": "openai",
                    "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_a}})),
                },
                "openai_bob": {
                    "model_provider": "openai",
                    "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_b}})),
                },
            },
            "active": "openai_bob",
        }
        ct._save_providers(data)
        # config.toml selects the openai provider
        (ct.CODEX_DIR / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        # Current live auth.json is Bob's account
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_b}}),
            encoding="utf-8",
        )

        assert ct._get_active_provider() == "openai", "provider must be openai"
        active = ct._get_active_profile_name()
        assert active == "openai_bob", f"expected openai_bob, got {active}"

        # Switch the live auth to Alice -> active profile should change to Alice
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_a}}),
            encoding="utf-8",
        )
        active = ct._get_active_profile_name()
        assert active == "openai_alice", f"expected openai_alice, got {active}"
    finally:
        restore_temp_codex_home(orig, tmp_dir)


def test_switch_between_two_openai_profiles_not_blocked():
    """use_provider must switch auth.json even when both profiles share provider 'openai'."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        jwt_a = _make_jwt("alice@example.com")
        jwt_b = _make_jwt("bob@example.com")

        # config.toml with an openai provider section
        (ct.CODEX_DIR / "config.toml").write_text(
            'model_provider = "openai"\n\n[model_providers.openai]\nname = "OpenAI"\nbase_url = "https://api.openai.com/v1"\nwire_api = "responses"\n',
            encoding="utf-8",
        )
        # Live auth = Alice
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_a}}),
            encoding="utf-8",
        )

        ct._save_providers({
            "profiles": {
                "openai_alice": {
                    "model_provider": "openai",
                    "auth_mode": "chatgpt",
                    "model": "gpt-5",
                    "provider_section": '[model_providers.openai]\nname = "OpenAI"\nbase_url = "https://api.openai.com/v1"\nwire_api = "responses"\n',
                    "auth.json": ct._encode_secret(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_a}})),
                },
                "openai_bob": {
                    "model_provider": "openai",
                    "auth_mode": "chatgpt",
                    "model": "gpt-5",
                    "provider_section": '[model_providers.openai]\nname = "OpenAI"\nbase_url = "https://api.openai.com/v1"\nwire_api = "responses"\n',
                    "auth.json": ct._encode_secret(json.dumps({"auth_mode": "chatgpt", "tokens": {"id_token": jwt_b}})),
                },
            },
            "active": "openai_alice",
        })

        # Sanity: live auth is currently Alice's
        assert ct._get_active_profile_name() == "openai_alice"

        # Switch to Bob (same provider 'openai') — must NOT be a no-op.
        ct.use_provider("openai_bob", skip_convert=True)

        live = json.loads((ct.CODEX_DIR / "auth.json").read_text(encoding="utf-8"))
        live_jwt = live.get("tokens", {}).get("id_token", "")
        assert ct._extract_email_from_jwt(live_jwt) == "bob@example.com", "auth.json should now be Bob's"
        assert ct._get_active_profile_name() == "openai_bob", "active profile should now be Bob"

        data = ct._load_providers()
        assert data["active"] == "openai_bob", f"active field should be openai_bob, got {data.get('active')}"
        # Alice's auth must be preserved (auto-saved back), not overwritten by Bob's.
        alice_auth = json.loads(ct._decode_secret(data["profiles"]["openai_alice"]["auth.json"]))
        assert ct._extract_email_from_jwt(alice_auth.get("tokens", {}).get("id_token", "")) == "alice@example.com", "Alice's profile must not be clobbered"
    finally:
        restore_temp_codex_home(orig, tmp_dir)


def test_startup_auth_sync_updates_active_profile():
    """On startup, if the live auth.json is fresher than the ACTIVE profile's stored
    auth, _compute_active_auth_sync() returns that profile name (and save refreshes it)."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        jwt_a = _make_jwt("alice@example.com")
        # config + live auth: Alice, freshly refreshed (today)
        (ct.CODEX_DIR / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        live_last_refresh = "2026-07-31T00:00:00.000Z"
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "last_refresh": live_last_refresh,
                        "tokens": {"id_token": jwt_a}}),
            encoding="utf-8",
        )
        # Two profiles share email alice; the ACTIVE one has a STALE stored auth.
        ct._save_providers({
            "profiles": {
                "openai_alice": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "last_refresh": "2026-07-25T00:00:00.000Z",  # stale
                        "tokens": {"id_token": jwt_a}})),
                },
                "openai_alice_dup": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "last_refresh": "2026-07-20T00:00:00.000Z",  # even staler
                        "tokens": {"id_token": jwt_a}})),
                },
            },
            "active": "openai_alice",
        })

        # Active profile detected from live auth -> openai_alice
        assert ct._get_active_profile_name() == "openai_alice", "active profile should be alice"

        # Decision function must pick the ACTIVE profile to update.
        assert ct._compute_active_auth_sync() == "openai_alice"

        # Applying the refresh via save_provider must update only the active profile.
        ct.save_provider("openai_alice")
        data = ct._load_providers()
        _, stored_refresh = ct._get_stored_auth_email(data["profiles"]["openai_alice"])
        assert stored_refresh == live_last_refresh, f"active profile auth not refreshed, still {stored_refresh!r}"
        # The duplicate must be left untouched.
        _, dup_refresh = ct._get_stored_auth_email(data["profiles"]["openai_alice_dup"])
        assert dup_refresh == "2026-07-20T00:00:00.000Z", "duplicate profile should not be touched"
    finally:
        restore_temp_codex_home(orig, tmp_dir)


def test_startup_auth_sync_no_update_when_fresh():
    """No update when the active profile auth is already up to date."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        jwt_a = _make_jwt("alice@example.com")
        live_last_refresh = "2026-07-31T00:00:00.000Z"
        (ct.CODEX_DIR / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "last_refresh": live_last_refresh,
                        "tokens": {"id_token": jwt_a}}),
            encoding="utf-8",
        )
        ct._save_providers({
            "profiles": {
                "openai_alice": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "last_refresh": live_last_refresh,  # SAME -> fresh
                        "tokens": {"id_token": jwt_a}})),
                },
            },
            "active": "openai_alice",
        })

        # Fresh -> nothing to do.
        assert ct._compute_active_auth_sync() is None
    finally:
        restore_temp_codex_home(orig, tmp_dir)


def test_active_profile_matched_by_account_id_after_email_change():
    """When the live account changed its email, the profile must still be recognized
    by the stable account_id (email-only matching would return None)."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        account_id = "d05b5d1d-57b8-41c0-a974-44bb738c684a"
        old_email_jwt = _make_jwt("terrylee0236@gmail.com")
        new_email_jwt = _make_jwt("new.email@example.com")
        # Saved profile stores OLD email + account_id.
        ct._save_providers({
            "profiles": {
                "openai_terrylee": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "tokens": {"id_token": old_email_jwt, "account_id": account_id}})),
                },
                "openai_other": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "tokens": {"id_token": _make_jwt("boards.drawls1d@icloud.com"),
                                   "account_id": "012b6a36-334f-448f-b04b-e44bcd38fb66"}})),
                },
            },
            "active": "openai_terrylee",
        })
        (ct.CODEX_DIR / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        # Live auth: SAME account_id but NEW (changed) email.
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt",
                        "tokens": {"id_token": new_email_jwt, "account_id": account_id}}),
            encoding="utf-8",
        )

        active = ct._get_active_profile_name()
        assert active == "openai_terrylee", f"should match by account_id after email change, got {active!r}"
    finally:
        restore_temp_codex_home(orig, tmp_dir)


def test_auth_sync_updates_email_after_account_id_match():
    """Startup auth sync must refresh the matched profile's stored email when the
    account changed its email (recognized via account_id), keeping auth fresh."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        account_id = "d05b5d1d-57b8-41c0-a974-44bb738c684a"
        old_jwt = _make_jwt("terrylee0236@gmail.com")
        new_jwt = _make_jwt("renamed@example.com")
        live_refresh = "2026-07-31T00:00:00.000Z"
        ct._save_providers({
            "profiles": {
                "openai_terrylee": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "last_refresh": "2026-07-25T00:00:00.000Z",
                        "tokens": {"id_token": old_jwt, "account_id": account_id}})),
                },
            },
            "active": "openai_terrylee",
        })
        (ct.CODEX_DIR / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "last_refresh": live_refresh,
                        "tokens": {"id_token": new_jwt, "account_id": account_id}}),
            encoding="utf-8",
        )

        # Matched by account_id despite the email change.
        assert ct._compute_active_auth_sync() == "openai_terrylee"
        ct.save_provider("openai_terrylee")

        data = ct._load_providers()
        prof = data["profiles"]["openai_terrylee"]
        # Stored email now reflects the NEW one.
        assert prof.get("auth_email") == "renamed@example.com", f"email not updated, got {prof.get('auth_email')!r}"
        stored_raw = ct._decode_secret(prof["auth.json"])
        stored = json.loads(stored_raw)
        assert stored.get("last_refresh") == live_refresh, "stored auth not refreshed"
    finally:
        restore_temp_codex_home(orig, tmp_dir)


def test_unmatched_active_account_returns_none():
    """An account whose account_id/email matches no saved profile returns None
    (so the GUI does not falsely highlight a profile as active)."""
    orig, tmp_dir = setup_temp_codex_home()
    try:
        ct._save_providers({
            "profiles": {
                "openai_old": {
                    "model_provider": "openai", "auth_mode": "chatgpt",
                    "auth.json": ct._encode_secret(json.dumps({
                        "auth_mode": "chatgpt",
                        "tokens": {"id_token": _make_jwt("old@example.com"),
                                   "account_id": "11111111-1111-1111-1111-111111111111"}})),
                },
            },
            "active": "openai_old",
        })
        (ct.CODEX_DIR / "config.toml").write_text('model_provider = "openai"\n', encoding="utf-8")
        # Live auth is a completely different account.
        (ct.CODEX_DIR / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt",
                        "tokens": {"id_token": _make_jwt("stranger@example.com"),
                                   "account_id": "22222222-2222-2222-2222-222222222222"}}),
            encoding="utf-8",
        )

        assert ct._get_active_profile_name() is None, "unmatched account should return None"
    finally:
        restore_temp_codex_home(orig, tmp_dir)


# --- Run ---

if __name__ == "__main__":
    print("Codex Chat Transformer — smoke tests\n")

    test("CLI syntax valid", test_cli_syntax)
    test("GUI syntax valid", test_gui_syntax)
    test("GUI Chat Bridge controls are wired", test_gui_chat_bridge_controls_are_wired)
    test("GUI Chat Bridge display keys remain unique", test_gui_chat_bridge_display_keys_remain_unique)
    test("GUI Chat Bridge buttons bind expected callbacks", test_gui_chat_bridge_buttons_bind_expected_callbacks)
    test("GUI dialog entries bind paste directly", test_gui_dialog_entries_bind_paste_directly)
    test("_merge_config preserves all provider sections", test_merge_preserves_all_sections)
    test("_merge_config appends new section", test_merge_append_new_section)
    test("b64 encode/decode roundtrip", test_b64_roundtrip)
    test("b64 passthrough for non-encoded", test_b64_passthrough)
    test("_get_active_profile_name distinguishes two openai logins", test_get_active_profile_name_distinguishes_openai_logins)
    test("switch between two openai profiles is not blocked", test_switch_between_two_openai_profiles_not_blocked)
    test("startup auth sync updates the active profile (with prompt)", test_startup_auth_sync_updates_active_profile)
    test("startup auth sync does not update when fresh", test_startup_auth_sync_no_update_when_fresh)
    test("active profile matched by account_id after email change", test_active_profile_matched_by_account_id_after_email_change)
    test("auth sync updates stored email after account_id match", test_auth_sync_updates_email_after_account_id_match)
    test("unmatched active account returns None", test_unmatched_active_account_returns_none)
    test("add_provider uses new format + b64 auth", test_add_provider_format)
    test("remove_provider deletes profile", test_remove_provider)
    test("_extract_provider_config", test_extract_provider_config)
    test("transform() has project/from_model/to_model params", test_transform_signature)
    test("project filter uses cwd column", test_project_filter_uses_cwd_column)
    test("CLI sync push does not hardcode localhost:8080", test_cli_sync_push_not_hardcoded_to_8080)
    test("sync peer parser accepts supported forms", test_parse_sync_peer_accepts_supported_forms)
    test("sync peer parser rejects invalid inputs", test_parse_sync_peer_rejects_invalid_inputs)
    test("is_codex_running returns bool", test_is_codex_running)
    test("_merge_config handles reasoning effort", test_merge_reasoning)
    test("_merge_config adds reasoning when absent", test_merge_add_reasoning_when_absent)
    test("edit_provider updates profile", test_edit_provider)
    test("edit_provider rename + update", test_rename_provider)
    test("provider name sanitization", test_sanitize_name)
    test("set_model changes config", test_set_model)
    test("pack export strips provider auth with --without-keys", test_export_pack_without_keys_strips_provider_auth)
    test("pack import upserts provider with obfuscated auth", test_import_pack_upserts_provider_and_stores_auth_obfuscated)
    test("pack sessions export/import round-trip", test_pack_sessions_export_import_round_trip)
    test("pack filters limit exported items", test_pack_filters_limit_exported_items)
    test("pack export skips missing rollout with warning", test_export_pack_skips_missing_rollout_with_warning)
    test("session search metadata hit", test_search_sessions_metadata_hit)
    test("session search JSONL fallback hit", test_search_sessions_jsonl_fallback_hit)
    test("session search project filter", test_search_sessions_project_filter)
    test("chat bridge Droid session normalizes messages and tools", test_chat_bridge_droid_session_to_bridge_preserves_messages_and_tools)
    test("chat bridge Droid to bridge preserves compaction state and parent", test_chat_bridge_droid_to_bridge_preserves_compaction_state_and_parent)
    test("chat bridge Droid session lookup finds project nested files", test_chat_bridge_droid_session_lookup_finds_project_nested_files)
    test("chat bridge Droid to bridge preserves project cwd and session title", test_chat_bridge_droid_to_bridge_preserves_project_cwd_and_session_title)
    test("chat bridge Droid to Codex import creates consistent rollout and pins old", test_chat_bridge_droid_to_codex_import_creates_consistent_rollout_and_pins_old)
    test("chat bridge Droid to Codex import can use fresh timestamps", test_chat_bridge_droid_to_codex_import_can_use_fresh_timestamps)
    test("chat bridge Droid to Codex mapping failure reports warning after commit", test_chat_bridge_droid_to_codex_mapping_failure_reports_warning_after_commit)
    test("chat bridge mapping keeps duplicate import pairs", test_chat_bridge_mapping_keeps_duplicate_import_pairs)
    test("chat bridge mirror plan merges roots and classifies states", test_chat_bridge_mirror_plan_merges_roots_and_classifies_states)
    test("chat bridge mirror plan surfaces import_id conflicts", test_chat_bridge_mirror_plan_surfaces_import_id_conflicts)
    test("chat bridge mirror plan project filter avoids false missing_codex", test_chat_bridge_mirror_plan_project_filter_does_not_create_false_missing_codex)
    test("chat bridge mirror actions select newer and skip unsafe states", test_chat_bridge_mirror_actions_select_newer_and_skip_unsafe_states)
    test("chat bridge mirror actions can force one direction", test_chat_bridge_mirror_actions_can_force_one_direction)
    test("chat bridge mirror actions skip ambiguous one-to-many pairs", test_chat_bridge_mirror_actions_skip_ambiguous_one_to_many_pairs)
    test("chat bridge mirror actions support session status and limit filters", test_chat_bridge_mirror_actions_support_session_status_and_limit_filters)
    test("chat bridge mirror actions mark previous copy as already applied", test_chat_bridge_mirror_actions_mark_previous_copy_as_already_applied)
    test("chat bridge doctor detects structural differences", test_chat_bridge_doctor_detects_structural_differences)
    test("chat bridge doctor detects one-sided metadata loss", test_chat_bridge_doctor_detects_one_sided_metadata_loss)
    test("chat bridge doctor normalizes extended Windows cwd", test_chat_bridge_doctor_normalizes_extended_windows_cwd)
    test("chat bridge doctor reports malformed mapped Droid JSONL", test_chat_bridge_doctor_reports_malformed_mapped_droid_jsonl)
    test("chat bridge doctor reports malformed Droid settings", test_chat_bridge_doctor_reports_malformed_droid_settings)
    test("chat bridge Droid to Codex import rolls back invalid rollout", test_chat_bridge_droid_to_codex_import_rolls_back_invalid_rollout)
    test("chat bridge Codex to Droid import writes session and mapping", test_chat_bridge_codex_to_droid_import_writes_session_and_mapping)
    test("chat bridge Codex to Droid preserves project context", test_chat_bridge_codex_to_droid_preserves_project_context)
    test("chat bridge Droid round-trip preserves manual title and settings metadata", test_chat_bridge_droid_round_trip_preserves_manual_title_and_settings_metadata)
    test("chat bridge Codex to Droid normalizes extended Windows cwd", test_chat_bridge_codex_to_droid_normalizes_extended_windows_cwd)
    test("chat bridge Codex to Droid uses fresh discovery time", test_chat_bridge_codex_to_droid_uses_fresh_discovery_time)
    test("chat bridge Codex to Droid writes valid tool inputs and parent chain", test_chat_bridge_codex_to_droid_writes_droid_valid_tool_inputs_and_parent_chain)
    test("chat bridge Codex to Droid normalizes native content contract", test_chat_bridge_codex_to_droid_normalizes_native_content_contract)
    test("chat bridge Codex to Droid rejects invalid raw replay before commit", test_chat_bridge_codex_to_droid_rejects_invalid_raw_replay_before_commit)
    test("chat bridge Codex to Droid uses unique event ids for tool pairs", test_chat_bridge_codex_to_droid_uses_unique_event_ids_for_tool_pairs)
    test("chat bridge Codex to Droid groups parallel tools like Droid", test_chat_bridge_codex_to_droid_groups_parallel_tool_calls_like_droid)
    test("chat bridge renders grouped tools to Codex in part order", test_chat_bridge_renders_grouped_tool_message_to_codex_in_part_order)
    test("chat bridge desktop compat renders Task tool without payload loss", test_chat_bridge_desktop_compat_renders_task_tool_without_payload_loss)
    test("chat bridge desktop compat session_meta keeps target model", test_chat_bridge_desktop_compat_session_meta_keeps_target_model)
    test("chat bridge desktop compat renders apply_patch without payload loss", test_chat_bridge_desktop_compat_renders_apply_patch_without_payload_loss)
    test("chat bridge desktop compat renders uppercase ApplyPatch as custom tool", test_chat_bridge_desktop_compat_renders_uppercase_apply_patch_as_custom_tool)
    test("chat bridge desktop compat apply_patch results do not repeat previous function output", test_chat_bridge_desktop_compat_apply_patch_results_do_not_repeat_previous_function_output)
    test("chat bridge Codex to Droid preserves lossless source events", test_chat_bridge_codex_to_droid_preserves_lossless_source_events)
    test("chat bridge Codex raw replay from Droid archive preserves native events", test_chat_bridge_codex_raw_replay_from_droid_archive_preserves_native_events)
    test("chat bridge Droid raw replay from Codex archive preserves native events", test_chat_bridge_droid_raw_replay_from_codex_archive_preserves_native_events)
    test("chat bridge Codex reasoning preserves encrypted content for Droid", test_chat_bridge_codex_reasoning_preserves_encrypted_content_for_droid)
    test("chat bridge Droid thinking preserves encrypted reasoning for Codex", test_chat_bridge_droid_thinking_preserves_encrypted_reasoning_for_codex)
    test("chat bridge Codex to Droid round-trip preserves unknown role and source events", test_chat_bridge_codex_to_droid_round_trip_preserves_unknown_role_and_source_events)
    test("chat bridge doctor treats canonical Droid provider as equivalent", test_chat_bridge_doctor_treats_canonical_droid_provider_as_equivalent)
    test("chat bridge doctor categorizes expected format differences", test_chat_bridge_doctor_categorizes_expected_format_differences)
    test("chat bridge doctor treats Codex expansion counts as warn", test_chat_bridge_doctor_treats_codex_expansion_counts_as_warn)
    test("chat bridge doctor treats message splitting as warn when tools are preserved", test_chat_bridge_doctor_treats_message_splitting_as_warn_when_tools_are_preserved)
    test("chat bridge Codex to bridge extracts compaction metadata", test_chat_bridge_codex_to_bridge_extracts_compaction_metadata)
    test("chat bridge Codex to Droid writes compaction state event", test_chat_bridge_codex_to_droid_writes_compaction_state_event)
    test("chat bridge Droid compaction import to Codex writes compacted events", test_chat_bridge_droid_compaction_import_to_codex_writes_compacted_events)
    test("chat bridge Droid compaction survives Codex round-trip", test_chat_bridge_droid_compaction_survives_codex_round_trip)
    test("chat bridge Codex to Droid raw compaction mode skips native state", test_chat_bridge_codex_to_droid_raw_compaction_mode_skips_native_state)
    test("chat bridge Codex to Droid default archived compaction mode skips native state", test_chat_bridge_codex_to_droid_default_archived_compaction_mode_skips_native_state)
    test("chat bridge Codex to Droid native compaction mode writes continuation suffix", test_chat_bridge_codex_to_droid_native_compaction_mode_writes_continuation_suffix)
    test("chat bridge Codex to Droid native compaction mode skips tool result suffix start", test_chat_bridge_codex_to_droid_native_compaction_mode_skips_tool_result_suffix_start)
    test("chat bridge Droid to Codex raw compaction mode skips compacted events", test_chat_bridge_droid_to_codex_raw_compaction_mode_skips_compacted_events)
    test("chat bridge Droid to Codex default archived compaction mode skips compacted events", test_chat_bridge_droid_to_codex_default_archived_compaction_mode_skips_compacted_events)
    test("chat bridge Codex Droid Codex loss smoke reports recovery", test_chat_bridge_codex_droid_codex_loss_smoke_reports_recovery)
    test("chat bridge Droid archived source events preserve encrypted content", test_chat_bridge_droid_archived_source_events_preserve_encrypted_content)
    test("chat bridge Codex to Droid can skip system messages", test_chat_bridge_codex_to_droid_can_skip_system_messages)
    test("chat bridge Codex to Droid skip-system filters internal envelopes", test_chat_bridge_codex_to_droid_skip_system_filters_internal_envelopes)
    test("chat bridge Codex to Droid default filters internal envelopes from messages", test_chat_bridge_codex_to_droid_default_filters_internal_envelopes_from_messages)
    test("chat bridge Codex to Droid preserves tool result errors", test_chat_bridge_codex_to_droid_preserves_tool_result_errors)
    test("chat bridge Codex to Droid maps custom model settings", test_chat_bridge_codex_to_droid_maps_custom_model_settings)
    test("chat bridge Codex to Droid maps profile provider to Droid backend", test_chat_bridge_codex_to_droid_maps_profile_provider_to_droid_backend)
    test("operation history redacts and loads newest first", test_operation_history_redacts_and_loads_newest)
    test("provider action emits history without secret", test_provider_action_emits_history_without_secret)
    test("droid CLI flags are registered", test_droid_cli_flags_registered)
    test("chat bridge CLI flags are registered", test_chat_bridge_cli_flags_registered)
    test("chat bridge CLI missing Droid session does not backup", test_chat_bridge_cli_missing_droid_session_does_not_backup)
    test("chat bridge CLI Droid to Codex import does not backup by default", test_chat_bridge_cli_droid_to_codex_import_does_not_backup_by_default)
    test("chat bridge CLI Droid to Codex import backs up when requested", test_chat_bridge_cli_droid_to_codex_import_backs_up_when_requested)
    test("chat bridge CLI mirror plan is read-only and does not require session", test_chat_bridge_cli_mirror_plan_is_read_only_and_does_not_require_session)
    test("chat bridge CLI doctor is read-only and reports pair differences", test_chat_bridge_cli_doctor_is_read_only_and_reports_pair_differences)
    test("chat bridge mapping plan classifies stale and reexport read-only", test_chat_bridge_mapping_plan_classifies_stale_and_reexport_read_only)
    test("chat mapping plan reexport requires error severity", test_chat_mapping_plan_reexport_requires_error_severity)
    test("chat bridge CLI mapping plan is read-only", test_chat_bridge_cli_mapping_plan_is_read_only)
    test("chat bridge CLI mirror apply preview does not write or backup", test_chat_bridge_cli_mirror_apply_preview_does_not_write_or_backup)
    test("chat bridge CLI mirror apply preview honors session status and limit filters", test_chat_bridge_cli_mirror_apply_preview_honors_session_status_and_limit_filters)
    test("chat bridge CLI mirror apply confirm exports Codex copy to Droid", test_chat_bridge_cli_mirror_apply_confirm_exports_codex_copy_to_droid)
    test("chat bridge CLI mirror apply confirm imports Droid copy to Codex without backup by default", test_chat_bridge_cli_mirror_apply_confirm_imports_droid_copy_to_codex_without_backup_by_default)
    test("chat bridge CLI mirror apply confirm imports Droid copy to Codex with backup when requested", test_chat_bridge_cli_mirror_apply_confirm_imports_droid_copy_to_codex_with_backup_when_requested)
    test("chat bridge CLI mirror apply stale Droid source does not backup and records error", test_chat_bridge_cli_mirror_apply_stale_droid_source_does_not_backup_and_records_error)
    test("droid history redacts keys", test_droid_history_redacts_key)
    test("droid doctor ignores legacy model issues", test_droid_doctor_ignores_legacy_model_issues)
    test("droid JSONC parser respects strings", test_droid_jsonc_parser_respects_strings)
    test("droid JSONC parser discards unterminated block comments", test_droid_strip_jsonc_comments_discards_unterminated_block_comment)
    test("droid loads_jsonc empty returns empty dict", test_droid_loads_jsonc_empty_returns_empty_dict)
    test("droid loads_jsonc accepts UTF-8 BOM", test_droid_loads_jsonc_accepts_utf8_bom)
    test("droid load_jsonc_file missing returns empty dict", test_droid_load_jsonc_file_missing_returns_empty_dict)
    test("droid merge_settings recursively merges and deep-copies", test_droid_merge_settings_recursively_merges_nested_dicts_and_deep_copies)
    test("droid normalize_current_model supports aliases and rejects invalid rows", test_droid_normalize_current_model_supports_alias_fields_and_invalid_rows)
    test("droid effective settings merges local over base", test_droid_effective_settings_merges_local_over_base)
    test("droid load_factory_context reports missing optional sources and reads legacy config", test_droid_load_factory_context_reports_missing_optional_sources_and_reads_legacy_config)
    test("droid use_model updates top-level and session defaults", test_droid_use_model_updates_top_level_and_session_defaults)
    test("droid remove_model only removes local managed model", test_droid_remove_model_only_removes_local_managed_model)
    test("droid remove_model repoints effective base selection", test_droid_remove_model_repoints_effective_base_selection)
    test("droid import Codex provider defaults to env key", test_droid_import_codex_provider_defaults_to_env_key)
    test("droid import Codex provider can write key when allowed", test_droid_import_codex_provider_can_write_key_when_allowed)
    test("droid Codex profile mapping requires base_url", test_droid_codex_profile_to_model_requires_base_url)
    test("droid extract_toml_value ignores inline comments outside quotes", test_droid_extract_toml_value_ignores_inline_comments_outside_quotes)
    test("droid extract_openai_key returns empty for malformed auth payloads", test_droid_extract_openai_key_returns_empty_for_malformed_auth_payloads)
    test("droid import Codex provider avoids sanitized id collisions", test_droid_import_codex_provider_avoids_sanitized_id_collisions)
    test("doctor accepts chatgpt auth without API key", test_doctor_report_accepts_chatgpt_auth_without_api_key)
    test("doctor flags provider health issues", test_doctor_report_flags_provider_health_issues)

    # Sync tests
    test("codex_sync.py syntax valid", test_sync_syntax)
    test("codex_sync imports", test_sync_imports)
    test("PIN format: 6 uppercase hex chars", test_pin_format)
    test("compute_local_hashes", test_compute_hashes)
    test("compute_local_hashes excludes sensitive/temp paths", test_compute_hashes_excludes_sensitive_and_temp_paths)
    test("repo hashes include meta and excluded summary", test_repo_hashes_include_meta_and_excluded_summary)
    test("compute_file_diff", test_file_diff)
    test("path traversal protection", test_path_traversal)
    test("chunked pack + extract (temp file based)", test_chunked_pack_extract)
    test("delete_files backs up and removes targets", test_delete_files_backs_up_and_removes_targets)
    test("push files preview does not mutate remote", test_push_files_preview_does_not_mutate_remote)
    test("pull files honor conflict policies", test_pull_files_conflict_policies)
    test("server ping", test_server_ping)
    test("server auth required (401 without PIN, 200 with PIN)", test_server_auth_required)
    test("server CORS headers", test_server_cors)
    test("manifest includes hash", test_manifest_includes_hash)
    test("sessions include cwd and git fields", test_sessions_include_cwd_and_git)
    test("current schema sessions list handles worktree rows", test_current_schema_sessions_list_handles_worktree_rows)
    test("upload session inserts new row with current schema", test_upload_session_inserts_new_row_with_current_schema)
    test("dashboard local API uses local auth", test_dashboard_uses_local_pin_for_protected_local_api)
    test("dashboard file sync wires preview/conflict/scan summary", test_dashboard_file_sync_wires_preview_conflict_and_scan_summary)
    test("sync_tray.py syntax valid", test_sync_tray_syntax)
    test("sync_tray imports optional (graceful)", test_sync_tray_imports_optional)
    test("trusted device storage (add/check/remove)", test_trusted_device_storage)
    test("server pairing endpoint (PIN exchange)", test_server_pairing_endpoint)
    test("server local-info (no auth)", test_server_local_info)
    test("server unpair endpoint (revoke token)", test_server_unpair_endpoint)
    test("upload provider stores auth obfuscated", test_upload_provider_stores_auth_obfuscated)
    test("case-insensitive path validation", test_case_insensitive_path_validation)
    test("get Git metadata and check dirty", test_get_git_metadata)
    test("project path mappings and worktrees", test_project_path_mappings_and_worktree)
    test("SQLite sync updates existing session", test_sqlite_sync_updates_existing)

    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)

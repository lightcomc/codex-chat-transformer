#!/usr/bin/env python3
"""Smoke tests for Codex Chat Transformer."""

import argparse
import ast
import contextlib
import io
import json
import os
import sys
import tempfile
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
        '"chat_pin_old"',
        "self.chat_droid_combo",
        "self.chat_codex_combo",
        "def _refresh_chat_bridge_sessions",
        "def _refresh_chat_bridge_sessions_thread",
        "def _apply_chat_bridge_sessions",
        "def _chat_droid_to_codex",
        "def _chat_codex_to_droid",
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
        'model_provider = "MyProv"\n'
        "\n"
        "[model_providers.MyProv]\n"
        'name = "MyProv"\n'
        'base_url = "https://my.com/v1"\n'
        'wire_api = "responses"\n'
    )
    name, section, model = ct._extract_provider_config(cfg)
    assert name == "MyProv"
    assert model == "gpt-5.5"
    assert "[model_providers.MyProv]" in section


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
                "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "ok"}],
            },
        },
        {"type": "todo_state", "id": "todo-1", "timestamp": "2025-01-02T03:04:09.000Z", "todos": []},
    ]
    jsonl_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    settings_path.write_text(
        json.dumps({
            "providerLock": "custom:NeuroGate-GPT-5.5-1",
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
    assert bridge["session"]["model"] == "custom:NeuroGate-GPT-5.5-1", "providerLock should become bridge model"
    assert bridge["work_context"]["current"]["confidence"] == "unknown", "Droid git context should be unknown in v1"
    assert bridge["work_context"]["timeline_complete"] is False, "Droid timeline should be explicitly incomplete"
    assert [m["role"] for m in bridge["messages"][:3]] == ["user", "assistant", "tool"], f"unexpected roles: {bridge['messages']}"
    part_types = [p["type"] for m in bridge["messages"] for p in m["parts"]]
    assert "text" in part_types, f"text parts should be preserved: {part_types}"
    assert "tool_call" in part_types, f"tool_use should become tool_call: {part_types}"
    assert "tool_result" in part_types, f"tool_result should be preserved: {part_types}"
    assert "todo_state" in part_types, f"todo_state should be preserved as metadata: {part_types}"


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
        )

        conn = sqlite3.connect(str(ct.STATE_DB))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM threads WHERE id = ?", (summary["codex_session_id"],)).fetchone()
        conn.close()

        assert row is not None, "Droid import should insert a Codex threads row"
        rollout_path = Path(row["rollout_path"])
        assert rollout_path.exists(), "threads.rollout_path should point at a real rollout file"
        lines = [json.loads(line) for line in rollout_path.read_text(encoding="utf-8").splitlines()]
        meta = lines[0]
        assert meta["type"] == "session_meta", "rollout should start with session_meta"
        assert meta["payload"]["id"] == row["id"], "rollout session id should match DB id"
        assert meta["payload"]["model_provider"] == row["model_provider"], "provider should match DB"
        assert meta["payload"]["model"] == row["model"], "model should match DB"
        assert row["created_at_ms"] == 1735787045000, f"created timestamp should be preserved, got {row['created_at_ms']}"
        assert row["updated_at_ms"] == 1735787049000, f"updated timestamp should be preserved, got {row['updated_at_ms']}"

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
        assert settings["providerLock"] == "gpt-5", f"settings should preserve model lock: {settings}"
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
        assert jsonl_path.parent.name == "-C-Research-nothing", f"Droid project sessions should be nested by cwd: {jsonl_path}"
        first_event = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
        assert first_event["cwd"] == r"C:\Research\nothing", f"session_start should preserve cwd: {first_event}"
        assert first_event["hostId"] == "host-project-1", f"session_start should preserve hostId: {first_event}"

        session_index = json.loads((factory_home / "sessions-index.json").read_text(encoding="utf-8"))
        entry = next(e for e in session_index["entries"] if e["sessionId"] == summary["droid_session_id"])
        assert entry["cwd"] == r"C:\Research\nothing", f"sessions-index should preserve cwd: {entry}"
        assert entry["hostId"] == "host-project-1", f"sessions-index should preserve hostId: {entry}"

        discovery = json.loads((factory_home / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        discovered = discovery["entries"][summary["droid_session_id"]]
        assert discovered["cwd"] == r"C:\Research\nothing", f"discovery index should preserve cwd: {discovered}"
        assert discovered["directoryPath"].endswith(r"sessions\-C-Research-nothing"), f"discovery directory should point at project folder: {discovered}"
    finally:
        restore_temp_codex_home(original, tmp_dir)


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

    assert jsonl_path.parent.name == "-C-Research-nothing", f"extended cwd should use Droid's normal project folder slug: {jsonl_path}"
    assert first_event["cwd"] == r"C:\Research\nothing", f"Droid cwd should not keep Windows extended prefix: {first_event}"
    assert discovered["cwd"] == r"C:\Research\nothing", f"discovery cwd should not keep Windows extended prefix: {discovered}"


def test_chat_bridge_codex_to_droid_preserves_droid_index_timestamps():
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
        summary = chat_bridge.import_bridge_to_droid(bridge, factory_home=tmp, preserve_timestamps=True)
        session_index = json.loads((Path(tmp) / "sessions-index.json").read_text(encoding="utf-8"))
        entry = next(e for e in session_index["entries"] if e["sessionId"] == summary["droid_session_id"])
        discovery = json.loads((Path(tmp) / "cache" / "session-discovery-index.json").read_text(encoding="utf-8"))
        discovered = discovery["entries"][summary["droid_session_id"]]

    expected_updated_ms = 1735787047000
    expected_created_ms = 1735787045000
    assert abs(entry["mtime"] - expected_updated_ms) < 1500, f"Droid mtime should preserve source updated_at: {entry}"
    assert abs(discovered["modifiedTimeMs"] - expected_updated_ms) < 1500, f"discovery modified time should preserve source updated_at: {discovered}"
    assert discovered["createdTimeMs"] == expected_created_ms, f"discovery created time should preserve source created_at: {discovered}"


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
        "--droid-add-neurogate",
        "--droid-import-provider", "SavedProv",
        "--droid-use", "custom:model-one",
        "--droid-remove-model", "custom:model-two",
        "--droid-settings", "C:\\Temp\\factory\\settings.json",
        "--droid-with-key",
        "--droid-api-key-env", "DROID_KEY_ENV",
    ])
    assert args.droid_models is True
    assert args.droid_doctor is True
    assert args.droid_add_neurogate is True
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
        "--chat-session", "one,two",
        "--chat-preserve-timestamps",
        "--chat-fresh-timestamps",
        "--chat-pin-old",
        "--chat-skip-system",
    ])
    assert args.droid_to_codex is True
    assert args.codex_to_droid is True
    assert args.droid_sessions is True
    assert args.codex_sessions is True
    assert args.chat_session == "one,two"
    assert args.chat_preserve_timestamps is True
    assert args.chat_fresh_timestamps is True
    assert args.chat_pin_old is True
    assert args.chat_skip_system is True


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
            chat_old_days=180,
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


def test_droid_history_redacts_key():
    original, tmp_dir = setup_temp_codex_home()
    try:
        with tempfile.TemporaryDirectory() as td:
            factory_home = Path(td)
            args = argparse.Namespace(
                droid_models=False,
                droid_doctor=False,
                droid_add_neurogate=True,
                droid_import_provider=None,
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
            assert "droid_model_added" in history_raw, "expected Droid history action"
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


def test_droid_add_neurogate_is_idempotent_and_uses_env_key():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        summary1 = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        summary2 = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        ctx = droid.load_factory_context(home)
        models = ctx["models"]
        ids = [model["id"] for model in models]

        assert summary1["added"] == 3, f"first add should create three models: {summary1}"
        assert summary1["updated"] == 0, f"first add should not count updates for new file: {summary1}"
        assert summary2["added"] == 0, f"second add should be idempotent: {summary2}"
        assert summary2["updated"] == 0, f"second add should not rewrite identical models: {summary2}"
        assert ids == [
            "custom:NeuroGate-GPT-5.5-1",
            "custom:NeuroGate-GPT-5.4-2",
            "custom:NeuroGate-GPT-5.4-Mini-3",
        ], f"expected the managed NeuroGate models in order: {ids}"
        expected_payloads = [
            ("gpt-5.5", "NeuroGate GPT-5.5", 1),
            ("gpt-5.4", "NeuroGate GPT-5.4", 2),
            ("gpt-5.4-mini", "NeuroGate GPT-5.4 Mini", 3),
        ]
        for model, expected in zip(models, expected_payloads):
            model_name, display_name, index = expected
            assert model["model"] == model_name
            assert model["displayName"] == display_name
            assert model["baseUrl"] == "https://api.neurogate.space/v1"
            assert model["provider"] == "openai"
            assert model["apiKey"] == "${NEUROGATE_API_KEY}"
            assert model["reasoningEffort"] == "medium"
            assert model["managed"]
            assert model["raw"]["index"] == index
            assert model["raw"]["maxOutputTokens"] == 128000
            assert model["raw"]["noImageSupport"] is False
            assert model["raw"]["managedBy"] == droid.MANAGED_BY
        assert ctx["settings"]["model"] == "custom:NeuroGate-GPT-5.5-1"
        assert ctx["settings"]["reasoningEffort"] == "medium"
        assert ctx["settings"]["modelFavorites"] == ids
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:NeuroGate-GPT-5.5-1"
        assert ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "medium"

        raw = (home / "settings.local.json").read_text(encoding="utf-8")
        assert "${NEUROGATE_API_KEY}" in raw, "expected env var reference in local settings"
        assert summary1["backup_path"].exists(), f"backup should be created on first write: {summary1}"
        assert summary2["backup_path"].exists(), f"backup should be created on repeated write: {summary2}"
        assert summary1["backup_path"] != summary2["backup_path"], "rapid writes should get unique backups"


def test_droid_add_neurogate_preserves_existing_selection_defaults():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        droid.write_local_settings(
            home,
            {
                "model": "custom:keep-me",
                "reasoningEffort": "low",
                "sessionDefaultSettings": {
                    "model": "custom:keep-me",
                    "reasoningEffort": "low",
                },
                "customModels": [
                    {
                        "id": "custom:keep-me",
                        "model": "keep-me",
                        "displayName": "Keep Me",
                        "baseUrl": "https://keep.invalid/v1",
                        "provider": "openai",
                        "apiKey": "${KEEP_KEY}",
                    }
                ],
            },
        )

        summary = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        ctx = droid.load_factory_context(home)

        assert summary["added"] == 3
        assert ctx["settings"]["model"] == "custom:keep-me"
        assert ctx["settings"]["reasoningEffort"] == "low"
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:keep-me"
        assert ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "low"
        assert "custom:NeuroGate-GPT-5.5-1" in ctx["settings"]["modelFavorites"]


def test_droid_add_neurogate_preserves_base_selection_defaults():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "settings.json").write_text(
            json.dumps(
                {
                    "model": "custom:base-existing",
                    "reasoningEffort": "low",
                    "sessionDefaultSettings": {
                        "model": "custom:base-existing",
                        "reasoningEffort": "low",
                    },
                    "customModels": [
                        {
                            "id": "custom:base-existing",
                            "model": "base-existing",
                            "displayName": "Base Existing",
                            "baseUrl": "https://base.invalid/v1",
                            "provider": "openai",
                            "apiKey": "${BASE_KEY}",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        summary = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        ctx = droid.load_factory_context(home)
        ids = [model["id"] for model in ctx["models"]]

        assert summary["added"] == 3
        assert ctx["settings"]["model"] == "custom:base-existing"
        assert ctx["settings"]["reasoningEffort"] == "low"
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:base-existing"
        assert ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "low"
        assert "custom:base-existing" in ids, "base custom model should remain effective after local add"
        assert "custom:NeuroGate-GPT-5.5-1" in ids
        assert "custom:NeuroGate-GPT-5.5-1" in ctx["settings"]["modelFavorites"]


def test_droid_add_neurogate_preserves_base_model_when_local_models_empty():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "settings.json").write_text(
            json.dumps(
                {
                    "model": "custom:base-existing",
                    "reasoningEffort": "low",
                    "modelFavorites": ["custom:base-existing"],
                    "sessionDefaultSettings": {
                        "model": "custom:base-existing",
                        "reasoningEffort": "low",
                    },
                    "customModels": [
                        {
                            "id": "custom:base-existing",
                            "model": "base-existing",
                            "displayName": "Base Existing",
                            "baseUrl": "https://base.invalid/v1",
                            "provider": "openai",
                            "apiKey": "${BASE_KEY}",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (home / "settings.local.json").write_text(
            json.dumps({"customModels": [], "modelFavorites": []}),
            encoding="utf-8",
        )

        summary = droid.add_neurogate_models(home, api_key_env="NEUROGATE_API_KEY")
        ctx = droid.load_factory_context(home)
        ids = [model["id"] for model in ctx["models"]]

        assert summary["added"] == 3
        assert ctx["settings"]["model"] == "custom:base-existing"
        assert ctx["settings"]["reasoningEffort"] == "low"
        assert ctx["settings"]["sessionDefaultSettings"]["model"] == "custom:base-existing"
        assert ctx["settings"]["sessionDefaultSettings"]["reasoningEffort"] == "low"
        assert "custom:base-existing" in ids, "base model should be copied into local before adding NeuroGate"
        assert "custom:NeuroGate-GPT-5.5-1" in ids
        assert "custom:base-existing" in ctx["settings"]["modelFavorites"]
        assert "custom:NeuroGate-GPT-5.5-1" in ctx["settings"]["modelFavorites"]


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


# --- Run ---

if __name__ == "__main__":
    print("Codex Chat Transformer — smoke tests\n")

    test("CLI syntax valid", test_cli_syntax)
    test("GUI syntax valid", test_gui_syntax)
    test("GUI Chat Bridge controls are wired", test_gui_chat_bridge_controls_are_wired)
    test("GUI Chat Bridge display keys remain unique", test_gui_chat_bridge_display_keys_remain_unique)
    test("GUI Chat Bridge buttons bind expected callbacks", test_gui_chat_bridge_buttons_bind_expected_callbacks)
    test("_merge_config preserves all provider sections", test_merge_preserves_all_sections)
    test("_merge_config appends new section", test_merge_append_new_section)
    test("b64 encode/decode roundtrip", test_b64_roundtrip)
    test("b64 passthrough for non-encoded", test_b64_passthrough)
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
    test("chat bridge Droid session lookup finds project nested files", test_chat_bridge_droid_session_lookup_finds_project_nested_files)
    test("chat bridge Droid to Codex import creates consistent rollout and pins old", test_chat_bridge_droid_to_codex_import_creates_consistent_rollout_and_pins_old)
    test("chat bridge Droid to Codex import can use fresh timestamps", test_chat_bridge_droid_to_codex_import_can_use_fresh_timestamps)
    test("chat bridge Droid to Codex mapping failure reports warning after commit", test_chat_bridge_droid_to_codex_mapping_failure_reports_warning_after_commit)
    test("chat bridge mapping keeps duplicate import pairs", test_chat_bridge_mapping_keeps_duplicate_import_pairs)
    test("chat bridge Droid to Codex import rolls back invalid rollout", test_chat_bridge_droid_to_codex_import_rolls_back_invalid_rollout)
    test("chat bridge Codex to Droid import writes session and mapping", test_chat_bridge_codex_to_droid_import_writes_session_and_mapping)
    test("chat bridge Codex to Droid preserves project context", test_chat_bridge_codex_to_droid_preserves_project_context)
    test("chat bridge Codex to Droid normalizes extended Windows cwd", test_chat_bridge_codex_to_droid_normalizes_extended_windows_cwd)
    test("chat bridge Codex to Droid preserves Droid index timestamps", test_chat_bridge_codex_to_droid_preserves_droid_index_timestamps)
    test("chat bridge Codex to Droid can skip system messages", test_chat_bridge_codex_to_droid_can_skip_system_messages)
    test("operation history redacts and loads newest first", test_operation_history_redacts_and_loads_newest)
    test("provider action emits history without secret", test_provider_action_emits_history_without_secret)
    test("droid CLI flags are registered", test_droid_cli_flags_registered)
    test("chat bridge CLI flags are registered", test_chat_bridge_cli_flags_registered)
    test("chat bridge CLI missing Droid session does not backup", test_chat_bridge_cli_missing_droid_session_does_not_backup)
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
    test("droid add_neurogate is idempotent and uses env key", test_droid_add_neurogate_is_idempotent_and_uses_env_key)
    test("droid add_neurogate preserves existing selection defaults", test_droid_add_neurogate_preserves_existing_selection_defaults)
    test("droid add_neurogate preserves base selection defaults", test_droid_add_neurogate_preserves_base_selection_defaults)
    test("droid add_neurogate preserves base model when local models empty", test_droid_add_neurogate_preserves_base_model_when_local_models_empty)
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

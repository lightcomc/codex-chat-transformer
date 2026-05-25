#!/usr/bin/env python3
"""Smoke tests for Codex Chat Transformer."""

import json
import os
import sys
import tempfile
from pathlib import Path

import codex_chat_transformer as ct
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


# --- Tests ---

def test_gui_syntax():
    py_compile.compile(
        str(Path(__file__).parent / "codex_manager_gui.py"), doraise=True
    )


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
    test("is_codex_running returns bool", test_is_codex_running)
    test("_merge_config handles reasoning effort", test_merge_reasoning)
    test("_merge_config adds reasoning when absent", test_merge_add_reasoning_when_absent)
    test("edit_provider updates profile", test_edit_provider)
    test("edit_provider rename + update", test_rename_provider)
    test("provider name sanitization", test_sanitize_name)
    test("set_model changes config", test_set_model)

    # Sync tests
    test("codex_sync.py syntax valid", test_sync_syntax)
    test("codex_sync imports", test_sync_imports)
    test("PIN format: 6 uppercase hex chars", test_pin_format)
    test("compute_local_hashes", test_compute_hashes)
    test("compute_local_hashes excludes sensitive/temp paths", test_compute_hashes_excludes_sensitive_and_temp_paths)
    test("compute_file_diff", test_file_diff)
    test("path traversal protection", test_path_traversal)
    test("chunked pack + extract (temp file based)", test_chunked_pack_extract)
    test("delete_files backs up and removes targets", test_delete_files_backs_up_and_removes_targets)
    test("server ping", test_server_ping)
    test("server auth required (401 without PIN, 200 with PIN)", test_server_auth_required)
    test("server CORS headers", test_server_cors)
    test("manifest includes hash", test_manifest_includes_hash)
    test("sessions include cwd and git fields", test_sessions_include_cwd_and_git)
    test("current schema sessions list handles worktree rows", test_current_schema_sessions_list_handles_worktree_rows)
    test("upload session inserts new row with current schema", test_upload_session_inserts_new_row_with_current_schema)
    test("dashboard local API uses local auth", test_dashboard_uses_local_pin_for_protected_local_api)
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

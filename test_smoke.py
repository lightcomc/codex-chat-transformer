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
    test("is_codex_running returns bool", test_is_codex_running)
    test("_merge_config handles reasoning effort", test_merge_reasoning)
    test("edit_provider updates profile", test_edit_provider)
    test("set_model changes config", test_set_model)

    # Sync tests
    test("codex_sync.py syntax valid", test_sync_syntax)
    test("codex_sync imports", test_sync_imports)
    test("PIN format: 6 uppercase hex chars", test_pin_format)
    test("compute_local_hashes", test_compute_hashes)
    test("compute_file_diff", test_file_diff)
    test("path traversal protection", test_path_traversal)
    test("server ping", test_server_ping)
    test("server auth required (401 without PIN, 200 with PIN)", test_server_auth_required)
    test("server CORS headers", test_server_cors)

    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)

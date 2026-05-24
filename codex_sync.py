#!/usr/bin/env python3
"""
Codex Sync — Local P2P bidirectional sync via HTTP API + web Dashboard.
Zero external dependencies. Python 3.7+ stdlib only.

Usage:
  python codex_chat_transformer.py --sync-host [--port PORT]
  python codex_chat_transformer.py --sync-pull HOST[:PORT] --pin XXXXXX
  python codex_chat_transformer.py --sync-push HOST[:PORT] --pin XXXXXX
"""

import hashlib
import http.client
import io
import json
import os
import secrets
import shutil
import socket
import sqlite3
import threading
import time
import zipfile
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── Paths (same resolution as codex_chat_transformer.py) ──────────────────

CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
STATE_DB = CODEX_DIR / "state_5.sqlite"
PROVIDERS_FILE = CODEX_DIR / "providers.json"
SESSIONS_DIR = CODEX_DIR / "sessions"

SYNC_VERSION = "1.0"

MAX_ZIP_SIZE = 500 * 1024 * 1024  # 500 MB

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".idea", ".tox", ".mypy_cache", ".pytest_cache", ".eggs",
    ".claude", "backup_*", "*.egg-info", ".env",
}

# Module-level flag: set to True when sync writes local data
data_changed = False

# ── Rate limiter ──────────────────────────────────────────────────────────

MAX_AUTH_FAILURES = 5
AUTH_BLOCK_SECONDS = 30

_failed_auth = {"count": 0, "blocked_until": 0.0}
_auth_lock = threading.Lock()

# ── Utilities ─────────────────────────────────────────────────────────────


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_pin():
    return secrets.token_hex(3).upper()


def find_free_port(start=8080, max_tries=20):
    for port in range(start, start + max_tries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.bind(("", port))
            s.close()
            return port
        except OSError:
            continue
    return None


def _validate_path(rel_path, base_dir):
    base = os.path.realpath(base_dir)
    resolved = os.path.realpath(os.path.join(base, rel_path))
    return (resolved.startswith(base + os.sep) or resolved == base) and ".." not in Path(rel_path).parts


def _check_rate_limit():
    with _auth_lock:
        if _failed_auth["blocked_until"] > time.time():
            return False
    return True


def _record_failed_auth():
    with _auth_lock:
        _failed_auth["count"] += 1
        if _failed_auth["count"] >= MAX_AUTH_FAILURES:
            _failed_auth["blocked_until"] = time.time() + AUTH_BLOCK_SECONDS
            _failed_auth["count"] = 0


def _reset_rate_limit():
    with _auth_lock:
        _failed_auth["count"] = 0


def check_git_dirty(project_dir):
    """Check if git working tree has uncommitted changes. Returns (is_git, is_dirty, files)."""
    git_dir = os.path.join(os.path.realpath(project_dir), ".git")
    if not os.path.exists(git_dir):
        return False, False, []
    try:
        import subprocess
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=os.path.realpath(project_dir),
            capture_output=True, text=True, timeout=10
        )
        files = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        return True, len(files) > 0, files
    except Exception:
        return True, False, []


def is_port_free(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.bind(("", port))
        s.close()
        return True
    except OSError:
        return False


# ── Providers helpers ────────────────────────────────────────────────────


def _load_providers_raw():
    if not PROVIDERS_FILE.exists():
        return {"profiles": {}, "active": None}
    try:
        with open(str(PROVIDERS_FILE), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"profiles": {}, "active": None}


def _save_providers_raw(data):
    with open(str(PROVIDERS_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _providers_summary():
    data = _load_providers_raw()
    profiles = data.get("profiles", {})
    result = []
    for name, prof in profiles.items():
        has_key = bool(prof.get("auth.json"))
        result.append({
            "name": name,
            "model_provider": prof.get("model_provider", "?"),
            "model": prof.get("model", "?"),
            "auth_mode": prof.get("auth_mode", "?"),
            "has_key": has_key,
            "saved_at": prof.get("saved_at", ""),
        })
    return result, data.get("active")


def _provider_full(name):
    data = _load_providers_raw()
    prof = data.get("profiles", {}).get(name)
    if not prof:
        return None
    auth_raw = prof.get("auth.json", "")
    if auth_raw and auth_raw.startswith("b64:"):
        import base64
        try:
            auth_raw = base64.b64decode(auth_raw[4:]).decode("utf-8")
        except Exception:
            pass
    return {
        "name": name,
        "model_provider": prof.get("model_provider", ""),
        "model": prof.get("model", ""),
        "auth_mode": prof.get("auth_mode", ""),
        "provider_section": prof.get("provider_section", ""),
        "auth.json": auth_raw,
        "saved_at": prof.get("saved_at", ""),
    }


# ── Sessions helpers ─────────────────────────────────────────────────────


def _get_manifest_hash():
    """Hash representing current state of sessions + providers. Used for auto-sync change detection."""
    sessions = _get_sessions_list()
    providers, _ = _providers_summary()
    sess_str = "|".join("{}:{}".format(s["id"], s["updated_at_ms"]) for s in sessions)
    prov_str = "|".join(p["name"] for p in providers)
    return hashlib.sha256((sess_str + "||" + prov_str).encode()).hexdigest()[:16]


def _get_sessions_list():
    if not STATE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(STATE_DB), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, rollout_path, model_provider, title,
                   created_at_ms, updated_at_ms, archived, source, cwd,
                   git_branch, git_sha, git_origin_url
            FROM threads
            ORDER BY updated_at_ms DESC
        """)
        rows = cur.fetchall()
        conn.close()
        result = []
        for r in rows:
            has_rollout = bool(r["rollout_path"]) and os.path.exists(
                r["rollout_path"].replace("\\\\?\\", "")
            )
            cwd_val = (r["cwd"] or "").replace("\\\\?\\", "")
            is_worktree = "worktrees" in cwd_val and ".codex" in cwd_val
            result.append({
                "id": r["id"],
                "title": (r["title"] or "")[:80],
                "cwd": cwd_val,
                "model_provider": r["model_provider"] or "",
                "created_at_ms": r["created_at_ms"],
                "updated_at_ms": r["updated_at_ms"],
                "archived": bool(r["archived"]),
                "source": r["source"] or "",
                "has_rollout": has_rollout,
                "git_branch": r["git_branch"] or "",
                "git_sha": r["git_sha"] or "",
                "git_origin_url": r["git_origin_url"] or "",
                "is_worktree": is_worktree,
            })
        return result
    except Exception:
        return []


def _get_session_jsonl(session_id):
    if not STATE_DB.exists():
        return None
    try:
        conn = sqlite3.connect(str(STATE_DB), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT rollout_path FROM threads WHERE id = ?", (session_id,))
        row = cur.fetchone()
        conn.close()
        if not row or not row["rollout_path"]:
            return None
        path = row["rollout_path"].replace("\\\\?\\", "")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


# ── File sync helpers ────────────────────────────────────────────────────


def compute_local_hashes(project_dir):
    result = {}
    base = os.path.realpath(project_dir)
    if not os.path.isdir(base):
        return result
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, base).replace("\\", "/")
            try:
                h = hashlib.sha256()
                with open(full, "rb") as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        h.update(chunk)
                result[rel] = h.hexdigest()
            except Exception:
                pass
    return result


def compute_file_diff(local_hashes, remote_hashes):
    local_set = set(local_hashes.keys())
    remote_set = set(remote_hashes.keys())
    new_files = sorted(remote_set - local_set)
    deleted_files = sorted(local_set - remote_set)
    common = local_set & remote_set
    modified = sorted(p for p in common if local_hashes[p] != remote_hashes[p])
    unchanged = sorted(p for p in common if local_hashes[p] == remote_hashes[p])
    return {
        "new": new_files,
        "modified": modified,
        "deleted": deleted_files,
        "unchanged": unchanged,
    }


def _create_pack(file_list, base_dir):
    buf = io.BytesIO()
    base = os.path.realpath(base_dir)
    total_size = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in file_list:
            if not _validate_path(rel, base):
                continue
            full = os.path.join(base, rel)
            if os.path.exists(full):
                total_size += os.path.getsize(full)
                if total_size > MAX_ZIP_SIZE:
                    raise RuntimeError(f"ZIP size exceeds {MAX_ZIP_SIZE // 1024 // 1024} MB limit")
                zf.write(full, rel)
    return buf.getvalue()


def extract_pack(zip_bytes, target_dir, backup=True):
    global data_changed
    target = os.path.realpath(target_dir)
    os.makedirs(target, exist_ok=True)

    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_dir = os.path.join(target, f".sync_backup_{ts}")
        os.makedirs(bak_dir, exist_ok=True)

    buf = io.BytesIO(zip_bytes)
    replaced = []
    errors = []
    with zipfile.ZipFile(buf, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename
            if not _validate_path(rel, target):
                errors.append(f"Blocked (path traversal): {rel}")
                continue
            dest = os.path.join(target, rel)
            if os.path.exists(dest) and backup:
                bak_path = os.path.join(bak_dir, rel)
                os.makedirs(os.path.dirname(bak_path), exist_ok=True)
                shutil.copy2(dest, bak_path)
                replaced.append(rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as dst:
                dst.write(src.read())

    data_changed = True
    return {"extracted": len(replaced) + len(errors) == 0 and len(zf.infolist()) or 0,
            "replaced": len(replaced), "errors": errors}


# ── Backup helper ────────────────────────────────────────────────────────


def _create_sync_backup():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_dir = CODEX_DIR / f"backup_sync_{ts}"
    bak_dir.mkdir(parents=True, exist_ok=True)
    if STATE_DB.exists():
        shutil.copy2(str(STATE_DB), str(bak_dir / "state_5.sqlite"))
        for ext in ("-shm", "-wal"):
            src = str(STATE_DB) + ext
            if os.path.exists(src):
                shutil.copy2(src, str(bak_dir / "state_5.sqlite") + ext)
    if PROVIDERS_FILE.exists():
        shutil.copy2(str(PROVIDERS_FILE), str(bak_dir / "providers.json"))
    return str(bak_dir)


# ── HTTP Request Handler ─────────────────────────────────────────────────


class SyncHandler(BaseHTTPRequestHandler):
    pin = ""
    server_port = 0

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_binary(self, data, content_type="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self):
        if not _check_rate_limit():
            self._send_json({"error": "rate_limited"}, status=429)
            return False
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {self.pin}":
            _record_failed_auth()
            self._send_json({"error": "unauthorized"}, status=401)
            return False
        _reset_rate_limit()
        return True

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            return self.rfile.read(length)
        return b""

    # ── GET routing ───────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/dashboard":
            self._send_html(_DASHBOARD_HTML)
            return

        if path == "/api/ping":
            self._send_json({"status": "ok", "version": SYNC_VERSION,
                             "ip": get_local_ip(), "port": self.server_port})
            return

        if not self._check_auth():
            return

        if path == "/api/manifest":
            self._handle_manifest()
        elif path == "/api/providers":
            self._handle_providers(params)
        elif path == "/api/providers/full":
            self._handle_provider_full(params)
        elif path == "/api/sessions":
            self._handle_sessions()
        elif path == "/api/session":
            self._handle_session(params)
        elif path == "/api/repo-hashes":
            self._handle_repo_hashes(params)
        else:
            self._send_json({"error": "not_found"}, status=404)

    # ── POST routing ──────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/dashboard", "/api/ping"):
            self._send_json({"error": "method_not_allowed"}, status=405)
            return

        if not self._check_auth():
            return

        if path == "/api/download-pack":
            self._handle_download_pack()
        elif path == "/api/upload/provider":
            self._handle_upload_provider()
        elif path == "/api/upload/session":
            self._handle_upload_session()
        elif path == "/api/upload/pack":
            self._handle_upload_pack()
        elif path == "/api/pull/providers":
            self._handle_pull_providers()
        elif path == "/api/pull/sessions":
            self._handle_pull_sessions()
        elif path == "/api/pull/files":
            self._handle_pull_files()
        elif path == "/api/push/providers":
            self._handle_push_providers()
        elif path == "/api/push/sessions":
            self._handle_push_sessions()
        elif path == "/api/push/files":
            self._handle_push_files()
        else:
            self._send_json({"error": "not_found"}, status=404)

    # ── Read endpoint handlers ────────────────────────────────────────

    def _handle_manifest(self):
        providers, active = _providers_summary()
        sessions = _get_sessions_list()
        self._send_json({
            "version": SYNC_VERSION,
            "provider_count": len(providers),
            "session_count": len(sessions),
            "active_provider": active,
            "ip": get_local_ip(),
            "port": self.server_port,
            "hash": _get_manifest_hash(),
            "timestamp": int(time.time()),
        })

    def _handle_providers(self, params):
        providers, active = _providers_summary()
        self._send_json({"providers": providers, "active": active})

    def _handle_provider_full(self, params):
        name = params.get("name", [None])[0]
        if not name:
            self._send_json({"error": "name required"}, status=400)
            return
        prof = _provider_full(name)
        if not prof:
            self._send_json({"error": "not_found"}, status=404)
            return
        self._send_json(prof)

    def _handle_sessions(self):
        sessions = _get_sessions_list()
        self._send_json({"sessions": sessions})

    def _handle_session(self, params):
        sid = params.get("id", [None])[0]
        if not sid:
            self._send_json({"error": "id required"}, status=400)
            return
        data = _get_session_jsonl(sid)
        if data is None:
            self._send_json({"error": "not_found"}, status=404)
            return
        self._send_binary(data, "application/octet-stream")

    def _handle_repo_hashes(self, params):
        dir_path = params.get("dir", ["."])[0]
        if not os.path.isdir(dir_path):
            self._send_json({"error": "dir not found", "dir": dir_path}, status=404)
            return
        is_git, is_dirty, dirty_files = check_git_dirty(dir_path)
        hashes = compute_local_hashes(dir_path)
        result = {"files": hashes, "base_dir": os.path.realpath(dir_path),
                  "count": len(hashes)}
        if is_git:
            result["git"] = True
            result["git_dirty"] = is_dirty
            result["git_dirty_count"] = len(dirty_files)
        self._send_json(result)

    # ── Write endpoint handlers ───────────────────────────────────────

    def _handle_download_pack(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        files = req.get("files", [])
        base_dir = req.get("base_dir", ".")
        if not os.path.isdir(base_dir):
            self._send_json({"error": "base_dir not found"}, status=404)
            return
        try:
            zip_data = _create_pack(files, base_dir)
        except RuntimeError as e:
            self._send_json({"error": str(e)}, status=413)
            return
        self._send_binary(zip_data, "application/zip")

    def _handle_upload_provider(self):
        global data_changed
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        name = req.get("name")
        if not name:
            self._send_json({"error": "name required"}, status=400)
            return
        bak = _create_sync_backup()
        data = _load_providers_raw()
        profiles = data.setdefault("profiles", {})
        profiles[name] = {
            "model_provider": req.get("model_provider", ""),
            "model": req.get("model", ""),
            "auth_mode": req.get("auth_mode", ""),
            "provider_section": req.get("provider_section", ""),
            "auth.json": req.get("auth.json", ""),
            "saved_at": datetime.now().isoformat(),
        }
        _save_providers_raw(data)
        data_changed = True
        self._send_json({"status": "ok", "name": name, "backup": bak})

    def _handle_upload_session(self):
        global data_changed
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        meta = req.get("meta", {})
        jsonl_b64 = req.get("jsonl", "")
        if not meta.get("id"):
            self._send_json({"error": "session id required"}, status=400)
            return

        import base64
        try:
            jsonl_data = base64.b64decode(jsonl_b64) if jsonl_b64 else b""
        except Exception:
            self._send_json({"error": "invalid jsonl base64"}, status=400)
            return

        bak = _create_sync_backup()
        created_ms = meta.get("created_at_ms", int(time.time() * 1000))
        dt = datetime.fromtimestamp(created_ms / 1000)
        date_dir = SESSIONS_DIR / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
        date_dir.mkdir(parents=True, exist_ok=True)
        rollout_path = str(date_dir / f"rollout-{meta['id']}.jsonl")

        if jsonl_data:
            with open(rollout_path, "wb") as f:
                f.write(jsonl_data)

        try:
            conn = sqlite3.connect(str(STATE_DB), timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                INSERT OR IGNORE INTO threads
                (id, rollout_path, model_provider, title,
                 created_at_ms, updated_at_ms, archived, source, cwd, project)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meta["id"],
                rollout_path,
                meta.get("model_provider", ""),
                meta.get("title", ""),
                meta.get("created_at_ms", 0),
                meta.get("updated_at_ms", 0),
                int(meta.get("archived", False)),
                meta.get("source", ""),
                meta.get("cwd", ""),
                meta.get("project", ""),
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)
            return

        data_changed = True
        self._send_json({"status": "ok", "id": meta["id"], "backup": bak})

    def _handle_upload_pack(self):
        raw = self._read_body()
        target_dir = self.headers.get("X-Target-Dir", ".")
        result = extract_pack(raw, target_dir, backup=True)
        self._send_json(result)

    # ── Proxy (server-to-server) handlers ─────────────────────────────

    def _handle_pull_providers(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        remote = req.get("remote_host", "")
        port = int(req.get("remote_port", 8080))
        rpin = req.get("remote_pin", "")
        names = req.get("names", [])
        mode = req.get("mode", "with_key")

        bak = _create_sync_backup()
        results = []
        local_data = _load_providers_raw()

        for name in names:
            try:
                if mode == "with_key":
                    prof = _client_get_provider_full(remote, port, rpin, name)
                else:
                    prof = _client_get_provider_no_key(remote, port, rpin, name)
                if prof:
                    local_data.setdefault("profiles", {})[name] = prof
                    results.append({"name": name, "status": "imported"})
                else:
                    results.append({"name": name, "status": "not_found"})
            except Exception as e:
                results.append({"name": name, "status": "error", "error": str(e)})

        _save_providers_raw(local_data)
        global data_changed
        data_changed = True
        self._send_json({"results": results, "backup": bak})

    def _handle_pull_sessions(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        remote = req.get("remote_host", "")
        port = int(req.get("remote_port", 8080))
        rpin = req.get("remote_pin", "")
        ids = req.get("session_ids", [])

        bak = _create_sync_backup()
        results = []

        remote_sessions = _client_get_json(f"http://{remote}:{port}/api/sessions",
                                            rpin).get("sessions", [])
        remote_map = {s["id"]: s for s in remote_sessions}

        for sid in ids:
            try:
                meta = remote_map.get(sid)
                if not meta:
                    results.append({"id": sid, "status": "not_found"})
                    continue
                jsonl_bytes = _client_get_bytes(f"http://{remote}:{port}/api/session?id={sid}", rpin)
                if jsonl_bytes is None:
                    results.append({"id": sid, "status": "no_jsonl"})
                    continue
                import base64
                self._do_upload_session(meta, base64.b64encode(jsonl_bytes).decode("ascii"))
                results.append({"id": sid, "status": "imported"})
            except Exception as e:
                results.append({"id": sid, "status": "error", "error": str(e)})

        global data_changed
        data_changed = True
        self._send_json({"results": results, "backup": bak})

    def _handle_pull_files(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        remote = req.get("remote_host", "")
        port = int(req.get("remote_port", 8080))
        rpin = req.get("remote_pin", "")
        files = req.get("files", [])
        base_dir = req.get("base_dir", ".")

        try:
            zip_data = _client_post_zip(
                f"http://{remote}:{port}/api/download-pack",
                rpin, {"files": files, "base_dir": base_dir})
            result = extract_pack(zip_data, base_dir, backup=True)
            self._send_json(result)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def _handle_push_providers(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        remote = req.get("remote_host", "")
        port = int(req.get("remote_port", 8080))
        rpin = req.get("remote_pin", "")
        names = req.get("names", [])
        mode = req.get("mode", "with_key")

        results = []
        for name in names:
            try:
                if mode == "with_key":
                    prof = _provider_full(name)
                else:
                    prof = _provider_full(name)
                    if prof:
                        prof["auth.json"] = ""
                        prof["auth_mode"] = "unknown"
                if not prof:
                    results.append({"name": name, "status": "not_found"})
                    continue
                _client_post_json(f"http://{remote}:{port}/api/upload/provider", rpin, prof)
                results.append({"name": name, "status": "pushed"})
            except Exception as e:
                results.append({"name": name, "status": "error", "error": str(e)})
        self._send_json({"results": results})

    def _handle_push_sessions(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        remote = req.get("remote_host", "")
        port = int(req.get("remote_port", 8080))
        rpin = req.get("remote_pin", "")
        ids = req.get("session_ids", [])

        results = []
        local_sessions = _get_sessions_list()
        local_map = {s["id"]: s for s in local_sessions}

        import base64
        for sid in ids:
            try:
                meta = local_map.get(sid)
                if not meta:
                    results.append({"id": sid, "status": "not_found"})
                    continue
                jsonl_data = _get_session_jsonl(sid)
                if jsonl_data is None:
                    results.append({"id": sid, "status": "no_jsonl"})
                    continue
                payload = {"meta": meta, "jsonl": base64.b64encode(jsonl_data).decode("ascii")}
                _client_post_json(f"http://{remote}:{port}/api/upload/session", rpin, payload)
                results.append({"id": sid, "status": "pushed"})
            except Exception as e:
                results.append({"id": sid, "status": "error", "error": str(e)})
        self._send_json({"results": results})

    def _handle_push_files(self):
        raw = self._read_body()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json({"error": "invalid json"}, status=400)
            return
        remote = req.get("remote_host", "")
        port = int(req.get("remote_port", 8080))
        rpin = req.get("remote_pin", "")
        files = req.get("files", [])
        base_dir = req.get("base_dir", ".")

        try:
            zip_data = _create_pack(files, base_dir)
            _client_post_zip_raw(
                f"http://{remote}:{port}/api/upload/pack", rpin, zip_data, base_dir)
            self._send_json({"status": "ok", "pushed": len(files)})
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def _do_upload_session(self, meta, jsonl_b64):
        import base64
        created_ms = meta.get("created_at_ms", int(time.time() * 1000))
        dt = datetime.fromtimestamp(created_ms / 1000)
        date_dir = SESSIONS_DIR / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{dt.day:02d}"
        date_dir.mkdir(parents=True, exist_ok=True)
        rollout_path = str(date_dir / f"rollout-{meta['id']}.jsonl")

        jsonl_data = base64.b64decode(jsonl_b64) if jsonl_b64 else b""
        if jsonl_data:
            with open(rollout_path, "wb") as f:
                f.write(jsonl_data)

        conn = sqlite3.connect(str(STATE_DB), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            INSERT OR IGNORE INTO threads
            (id, rollout_path, model_provider, title,
             created_at_ms, updated_at_ms, archived, source, cwd, project)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            meta["id"], rollout_path, meta.get("model_provider", ""),
            meta.get("title", ""), meta.get("created_at_ms", 0),
            meta.get("updated_at_ms", 0), int(meta.get("archived", False)),
            meta.get("source", ""), meta.get("cwd", ""), meta.get("project", ""),
        ))
        conn.commit()
        conn.close()


# ── Client-side HTTP helpers ─────────────────────────────────────────────


def _http_request(url, method="GET", pin=None, body=None, timeout=30):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    headers = {}
    if pin:
        headers["Authorization"] = f"Bearer {pin}"
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else body
        headers["Content-Type"] = "application/json"
    else:
        body_bytes = None
    conn.request(method, path, body=body_bytes, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def _client_get_json(url, pin):
    status, data = _http_request(url, "GET", pin)
    if status != 200:
        raise Exception(f"HTTP {status}: {data.decode('utf-8', errors='replace')}")
    return json.loads(data.decode("utf-8"))


def _client_get_bytes(url, pin):
    status, data = _http_request(url, "GET", pin)
    if status == 404:
        return None
    if status != 200:
        raise Exception(f"HTTP {status}")
    return data


def _client_get_provider_full(host, port, pin, name):
    return _client_get_json(f"http://{host}:{port}/api/providers/full?name={name}", pin)


def _client_get_provider_no_key(host, port, pin, name):
    data = _client_get_json(f"http://{host}:{port}/api/providers", pin)
    for p in data.get("providers", []):
        if p["name"] == name:
            return {
                "model_provider": p.get("model_provider", ""),
                "model": p.get("model", ""),
                "auth_mode": "unknown",
                "provider_section": "",
                "auth.json": "",
                "saved_at": p.get("saved_at", ""),
            }
    return None


def _client_post_json(url, pin, payload):
    status, data = _http_request(url, "POST", pin, payload)
    if status not in (200, 201):
        raise Exception(f"HTTP {status}: {data.decode('utf-8', errors='replace')}")
    return json.loads(data.decode("utf-8"))


def _client_post_zip(url, pin, payload):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 80
    conn = http.client.HTTPConnection(host, port, timeout=120)
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {pin}",
        "Content-Type": "application/json",
    }
    conn.request("POST", parsed.path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    if resp.status != 200:
        raise Exception(f"HTTP {resp.status}")
    return data


def _client_post_zip_raw(url, pin, zip_data, base_dir):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 80
    conn = http.client.HTTPConnection(host, port, timeout=120)
    headers = {
        "Authorization": f"Bearer {pin}",
        "Content-Type": "application/zip",
        "X-Target-Dir": base_dir,
    }
    conn.request("POST", parsed.path, body=zip_data, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    if resp.status != 200:
        raise Exception(f"HTTP {resp.status}: {data.decode('utf-8', errors='replace')}")


# ── Server lifecycle ─────────────────────────────────────────────────────


def start_server(host="0.0.0.0", port=None, pin=None):
    if pin is None:
        pin = generate_pin()
    if port is None:
        port = find_free_port()
    elif not is_port_free(port):
        # Requested port busy — auto-find next free port
        port = find_free_port(port + 1)
    if port is None:
        raise RuntimeError("No free port found (tried 8080-8099)")
    SyncHandler.pin = pin
    SyncHandler.server_port = port
    server = HTTPServer((host, port), SyncHandler)
    return server, pin, port


def stop_server(server):
    server.shutdown()
    server.server_close()


# ── UDP broadcast beacon for LAN auto-discovery ──────────────────────────

def start_beacon(sync_port, pin, interval=3):
    """Broadcast UDP beacon on port 19876 for LAN auto-discovery."""
    def _beacon():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        msg = json.dumps({"type": "codex-sync", "port": sync_port,
                          "pin_hint": pin[:3] + "..."}).encode("utf-8")
        while True:
            try:
                sock.sendto(msg, ("<broadcast>", 19876))
            except Exception:
                pass
            time.sleep(interval)
    t = threading.Thread(target=_beacon, daemon=True)
    t.start()
    return t


def listen_for_beacons(timeout=5):
    """Listen for UDP beacons. Returns list of {ip, port, pin_hint}."""
    results = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("", 19876))
    except OSError:
        return results
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(1024)
            info = json.loads(data.decode("utf-8"))
            if info.get("type") == "codex-sync":
                results.append({"ip": addr[0], "port": info["port"],
                                "pin_hint": info.get("pin_hint", "")})
        except socket.timeout:
            break
        except Exception:
            break
    sock.close()
    return results


# ── Dashboard HTML ───────────────────────────────────────────────────────

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Codex Sync Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1e1e2e;color:#cdd6f4;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
.header{background:#2a2a3d;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #45475a}
.header h1{color:#89b4fa;font-size:18px;font-weight:600}
.header .server-info{color:#a6adc8;font-size:13px}
.tabs{display:flex;background:#2a2a3d;border-bottom:1px solid #45475a;padding:0 8px}
.tab{padding:10px 18px;color:#a6adc8;cursor:pointer;border-bottom:2px solid transparent;font-size:13px}
.tab:hover{color:#cdd6f4}
.tab.active{color:#89b4fa;border-bottom-color:#89b4fa}
.content{padding:20px;max-width:1100px;margin:0 auto}
.panel{display:none}
.panel.active{display:block}
h2{color:#89b4fa;font-size:16px;margin-bottom:12px;font-weight:600}
.info-box{background:#2a2a3d;border-radius:8px;padding:16px;margin-bottom:12px}
.info-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.info-row label{color:#a6adc8;font-size:13px;min-width:100px}
.info-row input,.info-row select{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:6px 10px;font-size:13px;flex:1}
.info-row input:focus{outline:none;border-color:#89b4fa}
.pin-display{font-family:monospace;font-size:18px;color:#a6e3a1;font-weight:700;letter-spacing:2px}
.btn{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:13px}
.btn:hover{background:#45475a}
.btn.primary{background:#89b4fa;color:#1e1e2e;border-color:#89b4fa;font-weight:600}
.btn.primary:hover{background:#74c7ec}
.btn.danger{background:#f38ba8;color:#1e1e2e;border-color:#f38ba8}
.btn.success{background:#a6e3a1;color:#1e1e2e;border-color:#a6e3a1}
.btn.small{padding:4px 10px;font-size:12px}
.btn:disabled{opacity:.4;cursor:not-allowed}
table{width:100%;border-collapse:collapse;background:#2a2a3d;border-radius:8px;overflow:hidden}
th{background:#313244;color:#a6adc8;font-size:12px;text-transform:uppercase;padding:10px 12px;text-align:left}
td{padding:8px 12px;border-top:1px solid #45475a;font-size:13px}
tr:hover td{background:#313244}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge.green{background:#a6e3a122;color:#a6e3a1}
.badge.red{background:#f38ba822;color:#f38ba8}
.badge.yellow{background:#f9e2af22;color:#f9e2af}
.badge.blue{background:#89b4fa22;color:#89b4fa}
.actions{display:flex;gap:4px}
.status-bar{position:fixed;bottom:0;left:0;right:0;background:#2a2a3d;border-top:1px solid #45475a;padding:8px 20px;display:flex;justify-content:space-between;font-size:12px;color:#a6adc8}
.progress{width:100%;height:4px;background:#313244;border-radius:2px;margin:8px 0}
.progress-bar{height:100%;background:#89b4fa;border-radius:2px;transition:width .3s}
.toast{position:fixed;top:20px;right:20px;background:#313244;border:1px solid #45475a;border-radius:8px;padding:12px 20px;z-index:999;display:none;font-size:13px}
.toast.show{display:block}
.toast.success{border-color:#a6e3a1;color:#a6e3a1}
.toast.error{border-color:#f38ba8;color:#f38ba8}
.checkbox{width:16px;height:16px;accent-color:#89b4fa}
select{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:4px 8px;font-size:12px}
</style>
</head>
<body>

<div class="header">
  <h1>Codex Sync Dashboard</h1>
  <div class="server-info" id="serverInfo">Loading...</div>
</div>

<div class="tabs">
  <div class="tab active" data-tab="connect" onclick="switchTab('connect')">Connect</div>
  <div class="tab" data-tab="providers" onclick="switchTab('providers')">Providers</div>
  <div class="tab" data-tab="sessions" onclick="switchTab('sessions')">Sessions</div>
  <div class="tab" data-tab="files" onclick="switchTab('files')">Files</div>
  <div class="tab" data-tab="settings" onclick="switchTab('settings')">Settings</div>
</div>

<div class="content">
  <!-- Connect tab -->
  <div class="panel active" id="panel-connect">
    <h2>Your Server</h2>
    <div class="info-box">
      <div class="info-row">
        <label>Address:</label>
        <span id="localAddr" style="color:#89b4fa;font-weight:600">...</span>
        <button class="btn small" onclick="copyText(document.getElementById('localAddr').textContent)">Copy</button>
      </div>
      <div class="info-row">
        <label>PIN:</label>
        <span class="pin-display" id="localPin">...</span>
        <button class="btn small" onclick="copyText(document.getElementById('localPin').textContent)">Copy</button>
      </div>
    </div>

    <h2>Connect to Remote</h2>
    <div class="info-box">
      <div class="info-row">
        <label>IP:Port:</label>
        <input id="remoteAddr" placeholder="192.168.1.60:8080">
      </div>
      <div class="info-row">
        <label>PIN:</label>
        <input id="remotePin" placeholder="XXXXXX" maxlength="6" style="max-width:120px;text-transform:uppercase">
      </div>
      <div class="info-row">
        <button class="btn primary" onclick="connectRemote()">Connect</button>
        <button class="btn danger" onclick="disconnectRemote()">Disconnect</button>
        <span id="connStatus" style="margin-left:12px;font-size:13px">Disconnected</span>
      </div>
    </div>
  </div>

  <!-- Providers tab -->
  <div class="panel" id="panel-providers">
    <div id="provNotConnected" style="color:#a6adc8">Connect to a remote server first.</div>
    <div id="provContent" style="display:none">
      <h2>Providers <span id="provCounts" style="font-size:12px;color:#a6adc8"></span></h2>
      <div style="margin-bottom:8px">
        <button class="btn small" onclick="selectAll('prov')">Select All</button>
        <button class="btn small" onclick="deselectAll('prov')">Deselect All</button>
        <button class="btn primary small" onclick="pullSelectedProviders()">Pull Selected</button>
        <button class="btn success small" onclick="pushSelectedProviders()">Push Selected</button>
      </div>
      <table>
        <thead><tr><th><input type="checkbox" class="checkbox" onchange="toggleAll(this,'prov')"></th><th>Name</th><th>Local</th><th>Remote</th><th>Key</th><th>Mode</th><th>Actions</th></tr></thead>
        <tbody id="provBody"></tbody>
      </table>
    </div>
  </div>

  <!-- Sessions tab -->
  <div class="panel" id="panel-sessions">
    <div id="sessNotConnected" style="color:#a6adc8">Connect to a remote server first.</div>
    <div id="sessContent" style="display:none">
      <h2>Sessions <span id="sessCounts" style="font-size:12px;color:#a6adc8"></span></h2>
      <div style="margin-bottom:8px">
        <button class="btn small" onclick="selectAll('sess')">Select All</button>
        <button class="btn small" onclick="deselectAll('sess')">Deselect All</button>
        <button class="btn primary small" onclick="pullSelectedSessions()">Pull Selected</button>
        <button class="btn success small" onclick="pushSelectedSessions()">Push Selected</button>
      </div>
      <table>
        <thead><tr><th><input type="checkbox" class="checkbox" onchange="toggleAll(this,'sess')"></th><th>Title</th><th>Project</th><th>Provider</th><th>Updated</th><th>Actions</th></tr></thead>
        <tbody id="sessBody"></tbody>
      </table>
      <div class="progress" id="sessProgress" style="display:none"><div class="progress-bar" id="sessProgressBar"></div></div>
    </div>
  </div>

  <!-- Files tab -->
  <div class="panel" id="panel-files">
    <div id="filesNotConnected" style="color:#a6adc8">Connect to a remote server first.</div>
    <div id="filesContent" style="display:none">
      <div class="info-box">
        <div class="info-row">
          <label>Project Dir:</label>
          <input id="projectDir" placeholder="/path/to/project">
          <button class="btn primary" onclick="scanFiles()">Scan</button>
        </div>
      </div>
      <h2>File Diff <span id="fileCounts" style="font-size:12px;color:#a6adc8"></span></h2>
      <div style="margin-bottom:8px">
        <button class="btn small" onclick="selectChanged()">Select Changed</button>
        <button class="btn small" onclick="deselectAll('file')">Deselect All</button>
        <button class="btn primary small" onclick="pullSelectedFiles()">Pull Selected</button>
        <button class="btn success small" onclick="pushSelectedFiles()">Push Selected</button>
      </div>
      <table>
        <thead><tr><th><input type="checkbox" class="checkbox" onchange="toggleAll(this,'file')"></th><th>Path</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody id="fileBody"></tbody>
      </table>
    </div>
  </div>

  <!-- Settings tab -->
  <div class="panel" id="panel-settings">
    <h2>Settings</h2>
    <div class="info-box">
      <div class="info-row">
        <label>Language:</label>
        <select id="settingLang" onchange="setLang(this.value)">
          <option value="en">English</option>
          <option value="ru">Русский</option>
        </select>
      </div>
      <div class="info-row">
        <label>Auto-backup:</label>
        <select id="settingBackup" onchange="setSetting('backup',this.value)">
          <option value="true">Enabled</option>
          <option value="false">Disabled</option>
        </select>
      </div>
      <div class="info-row">
        <label>Conflict resolution:</label>
        <select id="settingConflict" onchange="setSetting('conflict',this.value)">
          <option value="skip">Skip (don't overwrite)</option>
          <option value="overwrite">Overwrite</option>
          <option value="newer">Newer wins</option>
        </select>
      </div>
    </div>
    <h2>UDP Discovery</h2>
    <div class="info-box">
      <div class="info-row">
        <button class="btn" onclick="scanBeacons()">Scan for servers</button>
        <span id="beaconResults" style="margin-left:12px;color:#a6adc8;font-size:13px"></span>
      </div>
      <table id="beaconTable" style="display:none">
        <thead><tr><th>IP</th><th>Port</th><th>PIN hint</th><th>Action</th></tr></thead>
        <tbody id="beaconBody"></tbody>
      </table>
    </div>
    <h2>Auto-Sync</h2>
    <div class="info-box">
      <div class="info-row">
        <label>Auto-sync:</label>
        <select id="settingAutoSync" onchange="startAutoSync()">
          <option value="0">Off</option>
          <option value="30">Every 30s</option>
          <option value="60">Every 60s</option>
          <option value="120">Every 2 min</option>
          <option value="300">Every 5 min</option>
        </select>
      </div>
      <div class="info-row">
        <label>Auto-pull:</label>
        <select id="settingAutoPull" onchange="setSetting('autoPull',this.value)">
          <option value="none">Notify only</option>
          <option value="sessions">Auto-pull sessions</option>
          <option value="providers">Auto-pull providers</option>
          <option value="all">Auto-pull everything</option>
        </select>
      </div>
      <div class="info-row">
        <label>Last sync:</label>
        <span id="lastSyncTime" style="color:#a6adc8">Never</span>
      </div>
      <div class="info-row">
        <label>Status:</label>
        <span id="autoSyncStatus" style="color:#a6adc8">Idle</span>
      </div>
    </div>
  </div>
</div>

<div class="status-bar">
  <span id="statusLeft">Ready</span>
  <span id="statusRight"></span>
</div>

<div class="toast" id="toast"></div>

<div id="confirmModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;align-items:center;justify-content:center">
  <div style="background:#2a2a3d;border:1px solid #45475a;border-radius:12px;padding:24px;max-width:480px;width:90%">
    <p id="confirmMsg" style="color:#cdd6f4;font-size:14px;margin-bottom:16px;white-space:pre-wrap"></p>
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button class="btn" onclick="modalResolve(false)">No</button>
      <button class="btn primary" onclick="modalResolve(true)">Yes</button>
    </div>
  </div>
</div>

<script>
let localPin='', remoteHost='', remotePort=8080, remotePinVal='';
let localProviders=[], remoteProviders=[], localSessions=[], remoteSessions=[];
let fileDiff=null;

async function init(){
  try{
    const r=await fetch('/api/ping');
    const d=await r.json();
    document.getElementById('serverInfo').textContent='Server: '+d.ip+':'+d.port;
    localPin=d.ip+':'+d.port; // store for reference
  }catch(e){
    document.getElementById('serverInfo').textContent='Server error';
  }
}

function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelector('[data-tab="'+name+'"]').classList.add('active');
  document.getElementById('panel-'+name).classList.add('active');
  if(name==='providers'&&remoteHost) loadProviders();
  if(name==='sessions'&&remoteHost) loadSessions();
}

function copyText(text){navigator.clipboard.writeText(text).catch(()=>{})}

function showToast(msg,type){
  const t=document.getElementById('toast');
  t.textContent=msg;t.className='toast show '+(type||'');
  setTimeout(()=>t.className='toast',3000);
}

let _modalResolveFunc=null;
function showModal(msg){
  return new Promise(function(resolve){
    _modalResolveFunc=resolve;
    document.getElementById('confirmMsg').textContent=msg;
    document.getElementById('confirmModal').style.display='flex';
  });
}
function modalResolve(val){
  document.getElementById('confirmModal').style.display='none';
  if(_modalResolveFunc){_modalResolveFunc(val);_modalResolveFunc=null;}
}

async function connectRemote(){
  const addr=document.getElementById('remoteAddr').value.trim();
  remotePinVal=document.getElementById('remotePin').value.trim().toUpperCase();
  if(!addr||!remotePinVal){showToast('Enter address and PIN','error');return}
  const parts=addr.split(':');
  remoteHost=parts[0];remotePort=parts[1]?parseInt(parts[1]):8080;
  try{
    const status=await fetch('http://'+remoteHost+':'+remotePort+'/api/manifest',{
      headers:{'Authorization':'Bearer '+remotePinVal}});
    if(!status.ok) throw new Error('HTTP '+status.status);
    const d=await status.json();
    document.getElementById('connStatus').innerHTML='<span class="badge green">Connected</span> '+remoteHost+':'+remotePort+' ('+d.session_count+' sessions, '+d.provider_count+' providers)';
    document.getElementById('provNotConnected').style.display='none';
    document.getElementById('provContent').style.display='block';
    document.getElementById('sessNotConnected').style.display='none';
    document.getElementById('sessContent').style.display='block';
    document.getElementById('filesNotConnected').style.display='none';
    document.getElementById('filesContent').style.display='block';
    showToast('Connected!','success');
    startAutoSync();
  }catch(e){
    document.getElementById('connStatus').innerHTML='<span class="badge red">Error</span> '+e.message;
    showToast('Connection failed: '+e.message,'error');
  }
}

function disconnectRemote(){
  remoteHost='';remotePort=8080;remotePinVal='';
  if(_pollTimer){clearInterval(_pollTimer);_pollTimer=null;}
  document.getElementById('connStatus').innerHTML='<span class="badge">Disconnected</span>';
  document.getElementById('provNotConnected').style.display='';
  document.getElementById('provContent').style.display='none';
  document.getElementById('sessNotConnected').style.display='';
  document.getElementById('sessContent').style.display='none';
  document.getElementById('filesNotConnected').style.display='';
  document.getElementById('filesContent').style.display='none';
}

async function loadProviders(){
  const [lr,rr]=await Promise.all([
    fetch('/api/providers').then(r=>r.json()),
    fetch('http://'+remoteHost+':'+remotePort+'/api/providers',{headers:{'Authorization':'Bearer '+remotePinVal}}).then(r=>r.json())
  ]);
  localProviders=lr.providers||[];remoteProviders=rr.providers||[];
  const tbody=document.getElementById('provBody');tbody.innerHTML='';
  const allNames=new Set([...localProviders.map(p=>p.name),...remoteProviders.map(p=>p.name)]);
  for(const name of allNames){
    const loc=localProviders.find(p=>p.name===name);
    const rem=remoteProviders.find(p=>p.name===name);
    const status=loc&&rem?'<span class="badge yellow">Both</span>':loc?'<span class="badge blue">Local only</span>':'<span class="badge green">Remote only</span>';
    const keySt=(rem&&rem.has_key)?'<span class="badge green">Has key</span>':'<span class="badge red">No key</span>';
    const tr=document.createElement('tr');
    tr.innerHTML='<td><input type="checkbox" class="checkbox" data-name="'+name+'" data-scope="prov"></td>'+
      '<td>'+name+'</td><td>'+(loc?loc.model+'<br><small>'+loc.auth_mode+'</small>':'—')+'</td>'+
      '<td>'+(rem?rem.model+'<br><small>'+rem.auth_mode+'</small>':'—')+'</td>'+
      '<td>'+keySt+'</td>'+
      '<td><select id="mode_'+name+'" style="background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:4px;padding:2px 6px;font-size:11px">'+
      '<option value="with_key">With key</option><option value="no_key">Without key</option>'+
      (loc&&rem?'<option value="skip">Skip</option><option value="rename">Keep both</option>':'')+
      '</select></td>'+
      '<td class="actions"><button class="btn small primary" onclick="pullProvider(\''+name+'\')">Pull</button>'+
      '<button class="btn small success" onclick="pushProvider(\''+name+'\')">Push</button></td>';
    tbody.appendChild(tr);
  }
  document.getElementById('provCounts').textContent='('+localProviders.length+' local, '+remoteProviders.length+' remote)';
}

function selectAll(scope){document.querySelectorAll('[data-scope="'+scope+'"]').forEach(c=>c.checked=true)}
function deselectAll(scope){document.querySelectorAll('[data-scope="'+scope+'"]').forEach(c=>c.checked=false)}
function toggleAll(master,scope){document.querySelectorAll('[data-scope="'+scope+'"]').forEach(c=>c.checked=master.checked)}
function selectChanged(){document.querySelectorAll('[data-scope="file"]').forEach(c=>{
  const row=c.closest('tr');if(row&&row.dataset.status!=='unchanged')c.checked=true;
})}

async function pullProvider(name){
  const modeEl=document.getElementById('mode_'+name);
  const mode=modeEl?modeEl.value:'with_key';
  if(mode==='skip'){showToast('Skipped '+name,'error');return}
  try{const r=await fetch('/api/pull/providers',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,names:[name],mode:mode})});
    showResult(r);loadProviders();}catch(e){showToast(e.message,'error')}
}

async function pushProvider(name){
  try{const r=await fetch('/api/push/providers',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,names:[name],mode:'with_key'})});
    showResult(r);loadProviders();}catch(e){showToast(e.message,'error')}
}

async function pullSelectedProviders(){
  const names=getSelected('prov');if(!names.length){showToast('Nothing selected','error');return}
  for(const name of names){
    const modeEl=document.getElementById('mode_'+name);
    const mode=modeEl?modeEl.value:'with_key';
    if(mode==='skip') continue;
    try{await fetch('/api/pull/providers',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,names:[name],mode:mode})});
    }catch(e){showToast(e.message,'error')}
  }
  loadProviders();showToast('Pull done','success');
}

async function pushSelectedProviders(){
  const names=getSelected('prov');if(!names.length){showToast('Nothing selected','error');return}
  try{const r=await fetch('/api/push/providers',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,names:names,mode:'with_key'})});
    showResult(r);loadProviders();}catch(e){showToast(e.message,'error')}
}

async function loadSessions(){
  const [lr,rr]=await Promise.all([
    fetch('/api/sessions').then(r=>r.json()),
    fetch('http://'+remoteHost+':'+remotePort+'/api/sessions',{headers:{'Authorization':'Bearer '+remotePinVal}}).then(r=>r.json())
  ]);
  localSessions=lr.sessions||[];remoteSessions=rr.sessions||[];
  const tbody=document.getElementById('sessBody');tbody.innerHTML='';
  const localIds=new Set(localSessions.map(s=>s.id));
  for(const s of remoteSessions){
    const exists=localIds.has(s.id);
    const loc=exists?localSessions.find(l=>l.id===s.id):null;
    let status='<span class="badge green">New</span>';
    if(loc){
      const newer=s.updated_at_ms>loc.updated_at_ms;
      status=newer?'<span class="badge yellow">Remote newer</span>':'<span class="badge blue">Local newer</span>';
    }
    const updated=new Date(s.updated_at_ms).toLocaleString();
    const cwdShort=s.cwd?s.cwd.split(/[\\/]/).slice(-2).join('/'):'—';
    const wtBadge=s.is_worktree?'<br><span class="badge yellow">worktree</span>':'';
    const branchBadge=s.git_branch?'<br><span class="badge blue">'+s.git_branch+'</span>':'';
    const tr=document.createElement('tr');
    tr.innerHTML='<td><input type="checkbox" class="checkbox" data-name="'+s.id+'" data-scope="sess"></td>'+
      '<td>'+(s.title||'Untitled')+'</td><td>'+cwdShort+wtBadge+branchBadge+'</td>'+
      '<td>'+s.model_provider+'</td><td>'+updated+'</td>'+
      '<td class="actions"><button class="btn small primary" onclick="pullSession(\''+s.id+'\')">Pull</button>'+
      (loc?'<button class="btn small success" onclick="pushSession(\''+s.id+'\')">Push</button>':'')+'</td>';
    tbody.appendChild(tr);
  }
  document.getElementById('sessCounts').textContent='('+localSessions.length+' local, '+remoteSessions.length+' remote)';
}

async function pullSession(id){
  try{const r=await fetch('/api/pull/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,session_ids:[id]})});
    await showResult(r);loadSessions();
    await offerProjectFileSync(id,'pull');
  }catch(e){showToast(e.message,'error')}
}

async function pushSession(id){
  try{const r=await fetch('/api/push/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,session_ids:[id]})});
    await showResult(r);loadSessions();
    await offerProjectFileSync(id,'push');
  }catch(e){showToast(e.message,'error')}
}

async function pullSelectedSessions(){
  const ids=getSelected('sess');if(!ids.length){showToast('Nothing selected','error');return}
  try{const r=await fetch('/api/pull/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,session_ids:ids})});
    await showResult(r);loadSessions();
    await offerBulkProjectFileSync(ids,'pull');
  }catch(e){showToast(e.message,'error')}
}

async function pushSelectedSessions(){
  const ids=getSelected('sess');if(!ids.length){showToast('Nothing selected','error');return}
  try{const r=await fetch('/api/push/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,session_ids:ids})});
    await showResult(r);loadSessions();
    await offerBulkProjectFileSync(ids,'push');
  }catch(e){showToast(e.message,'error')}
}

async function scanFiles(){
  const dir=document.getElementById('projectDir').value.trim();
  if(!dir){showToast('Enter project directory','error');return}
  try{
    const [lr,rr]=await Promise.all([
      fetch('/api/repo-hashes?dir='+encodeURIComponent(dir)).then(r=>r.json()),
      fetch('http://'+remoteHost+':'+remotePort+'/api/repo-hashes?dir='+encodeURIComponent(dir),
        {headers:{'Authorization':'Bearer '+remotePinVal}}).then(r=>r.json())
    ]);
    const local=lr.files||{};const remote=rr.files||{};
    fileDiff=computeFileDiff(local,remote);
    renderFileDiff();
  }catch(e){showToast(e.message,'error')}
}

function computeFileDiff(local,remote){
  const ls=new Set(Object.keys(local)),rs=new Set(Object.keys(remote));
  const common=[...ls].filter(k=>rs.has(k));
  return{
    new:[...rs].filter(k=>!ls.has(k)).sort(),
    modified:common.filter(k=>local[k]!==remote[k]).sort(),
    deleted:[...ls].filter(k=>!rs.has(k)).sort(),
    unchanged:common.filter(k=>local[k]===remote[k]).sort()
  };
}

function renderFileDiff(){
  if(!fileDiff)return;
  const tbody=document.getElementById('fileBody');tbody.innerHTML='';
  const addRows=(list,status,badge)=>{
    for(const p of list){
      const tr=document.createElement('tr');tr.dataset.status=status;
      tr.innerHTML='<td><input type="checkbox" class="checkbox" data-name="'+p+'" data-scope="file"></td>'+
        '<td>'+p+'</td><td><span class="badge '+badge+'">'+status+'</span></td>'+
        '<td class="actions"><button class="btn small primary" onclick="pullFile(\''+p+'\')">Pull</button>'+
        '<button class="btn small success" onclick="pushFile(\''+p+'\')">Push</button></td>';
      tbody.appendChild(tr);
    }
  };
  addRows(fileDiff.new,'new','green');
  addRows(fileDiff.modified,'modified','yellow');
  addRows(fileDiff.deleted,'deleted','red');
  addRows(fileDiff.unchanged,'unchanged','blue');
  const total=fileDiff.new.length+fileDiff.modified.length+fileDiff.deleted.length+fileDiff.unchanged.length;
  document.getElementById('fileCounts').textContent='('+total+' files: '+fileDiff.new.length+' new, '+fileDiff.modified.length+' modified, '+fileDiff.deleted.length+' deleted)';
}

async function pullFile(path){
  const dir=document.getElementById('projectDir').value.trim();
  try{const r=await fetch('/api/pull/files',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,files:[path],base_dir:dir})});
    showResult(r);scanFiles();}catch(e){showToast(e.message,'error')}
}

async function pushFile(path){
  const dir=document.getElementById('projectDir').value.trim();
  try{const r=await fetch('/api/push/files',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,files:[path],base_dir:dir})});
    showResult(r);scanFiles();}catch(e){showToast(e.message,'error')}
}

async function pullSelectedFiles(){
  const paths=getSelected('file');if(!paths.length){showToast('Nothing selected','error');return}
  const dir=document.getElementById('projectDir').value.trim();
  try{const r=await fetch('/api/pull/files',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,files:paths,base_dir:dir})});
    showResult(r);scanFiles();}catch(e){showToast(e.message,'error')}
}

async function pushSelectedFiles(){
  const paths=getSelected('file');if(!paths.length){showToast('Nothing selected','error');return}
  const dir=document.getElementById('projectDir').value.trim();
  try{const r=await fetch('/api/push/files',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,files:paths,base_dir:dir})});
    showResult(r);scanFiles();}catch(e){showToast(e.message,'error')}
}

function getSelected(scope){
  return [...document.querySelectorAll('[data-scope="'+scope+'"]:checked')].map(c=>c.dataset.name);
}

async function showResult(response){
  try{
    const d=await response.json();
    if(d.results){
      const ok=d.results.filter(r=>r.status==='imported'||r.status==='pushed').length;
      showToast(ok+'/'+d.results.length+' done'+(d.backup?' (backup: '+d.backup+')':''),'success');
    }else if(d.error){
      showToast(d.error,'error');
    }else{
      showToast(JSON.stringify(d),'success');
    }
  }catch(e){showToast('Done','success')}
}

// ── Session-Project Linking ──────────────────────────────────────────────

async function offerProjectFileSync(sessionId,direction){
  var session=localSessions.find(function(s){return s.id===sessionId});
  if(!session) session=remoteSessions.find(function(s){return s.id===sessionId});
  if(!session||!session.cwd) return;
  var projectPath=session.cwd;
  if(session.is_worktree){
    var yes=await showModal('This session uses an isolated worktree:\n'+projectPath+
      '\n\nWorktree is stored inside .codex — syncing these files may conflict with Codex internals.\n\nContinue?');
    if(!yes) return;
  }else{
    var yes=await showModal('This session is linked to project:\n'+projectPath+
      (session.git_branch?'\nBranch: '+session.git_branch:'')+
      '\n\nSync project files?');
    if(!yes) return;
  }
  switchTab('files');
  document.getElementById('projectDir').value=projectPath;
  await scanFiles();
}

async function offerBulkProjectFileSync(ids,direction){
  var paths={};
  for(var i=0;i<ids.length;i++){
    var sid=ids[i];
    var session=localSessions.find(function(s){return s.id===sid});
    if(!session) session=remoteSessions.find(function(s){return s.id===sid});
    if(session&&session.cwd) paths[session.cwd]=session;
  }
  var pathList=Object.keys(paths);
  if(!pathList.length) return;
  var hasWorktree=pathList.some(function(p){return paths[p].is_worktree});
  var msg='These sessions are linked to '+(pathList.length>1?pathList.length+' directories':'directory')+':\n\n';
  for(var j=0;j<pathList.length&&j<5;j++){
    var s=paths[pathList[j]];
    msg+=pathList[j]+(s.git_branch?' ['+s.git_branch+']':'')+(s.is_worktree?' (worktree)':'')+'\n';
  }
  if(pathList.length>5) msg+='...and '+(pathList.length-5)+' more\n';
  if(hasWorktree) msg+='\nWarning: some sessions use isolated worktrees inside .codex.';
  msg+='\n\nSync project files?';
  var yes=await showModal(msg);
  if(yes){
    switchTab('files');
    document.getElementById('projectDir').value=pathList[0];
    await scanFiles();
  }
}

// ── Auto-Sync Polling ───────────────────────────────────────────────────

let _pollTimer=null,_lastRemoteHash=null,_syncBusy=false;

function startAutoSync(){
  if(_pollTimer){clearInterval(_pollTimer);_pollTimer=null}
  var interval=parseInt(document.getElementById('settingAutoSync').value)||0;
  if(!interval||!remoteHost){
    document.getElementById('autoSyncStatus').textContent='Idle';
    document.getElementById('statusLeft').textContent='Ready';
    return;
  }
  _lastRemoteHash=null;
  document.getElementById('statusLeft').textContent='Auto-sync: every '+interval+'s';
  _pollTimer=setInterval(function(){pollRemote()},interval*1000);
}

async function pollRemote(){
  if(_syncBusy||!remoteHost) return;
  try{
    document.getElementById('autoSyncStatus').textContent='Polling...';
    document.getElementById('autoSyncStatus').style.color='#f9e2af';
    var remote=await fetch('http://'+remoteHost+':'+remotePort+'/api/manifest',{
      headers:{'Authorization':'Bearer '+remotePinVal}}).then(function(r){return r.json()});
    var local=await fetch('/api/manifest').then(function(r){return r.json()});
    if(_lastRemoteHash!==null&&remote.hash!==_lastRemoteHash){
      _syncBusy=true;
      document.getElementById('autoSyncStatus').textContent='Syncing...';
      document.getElementById('autoSyncStatus').style.color='#89b4fa';
      var mode=document.getElementById('settingAutoPull').value;
      if(mode==='sessions'||mode==='all') await autoPullSessions();
      if(mode==='providers'||mode==='all') await autoPullProviders();
      if(mode==='none') showToast('Remote has changes!','info');
      _syncBusy=false;
    }
    _lastRemoteHash=remote.hash;
    document.getElementById('lastSyncTime').textContent=new Date().toLocaleTimeString();
    document.getElementById('autoSyncStatus').textContent='Idle';
    document.getElementById('autoSyncStatus').style.color='#a6adc8';
  }catch(e){
    document.getElementById('autoSyncStatus').textContent='Error';
    document.getElementById('autoSyncStatus').style.color='#f38ba8';
  }
}

async function autoPullSessions(){
  var lr=await fetch('/api/sessions').then(function(r){return r.json()});
  var rr=await fetch('http://'+remoteHost+':'+remotePort+'/api/sessions',{
    headers:{'Authorization':'Bearer '+remotePinVal}}).then(function(r){return r.json()});
  var localIds={};
  (lr.sessions||[]).forEach(function(s){localIds[s.id]=s.updated_at_ms});
  var toPull=(rr.sessions||[]).filter(function(s){
    return !localIds[s.id]||s.updated_at_ms>(localIds[s.id]||0);
  });
  if(!toPull.length) return;
  var ids=toPull.map(function(s){return s.id});
  await fetch('/api/pull/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,session_ids:ids})});
  showToast('Auto-pulled '+ids.length+' session(s)','success');
  if(document.querySelector('[data-tab="sessions"]').classList.contains('active')) loadSessions();
}

async function autoPullProviders(){
  var lr=await fetch('/api/providers').then(function(r){return r.json()});
  var rr=await fetch('http://'+remoteHost+':'+remotePort+'/api/providers',{
    headers:{'Authorization':'Bearer '+remotePinVal}}).then(function(r){return r.json()});
  var localNames=new Set((lr.providers||[]).map(function(p){return p.name}));
  var toPull=(rr.providers||[]).filter(function(p){return !localNames.has(p.name)});
  if(!toPull.length) return;
  var names=toPull.map(function(p){return p.name});
  await fetch('/api/pull/providers',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote_host:remoteHost,remote_port:remotePort,remote_pin:remotePinVal,names:names,mode:'with_key'})});
  showToast('Auto-pulled '+names.length+' provider(s)','success');
}

// ── Settings ─────────────────────────────────────────────────────────────

const SETTINGS_KEY='codex_sync_settings';
function loadSettings(){
  try{const s=localStorage.getItem(SETTINGS_KEY);return s?JSON.parse(s):{lang:'en',backup:'true',conflict:'skip'}}catch(e){return{lang:'en',backup:'true',conflict:'skip'}}
}
function saveSettings(s){try{localStorage.setItem(SETTINGS_KEY,JSON.stringify(s))}catch(e){}}
function setLang(lang){const s=loadSettings();s.lang=lang;saveSettings(s)}
function setSetting(key,val){const s=loadSettings();s[key]=val;saveSettings(s)}

// ── UDP Beacon scan ──────────────────────────────────────────────────────

async function scanBeacons(){
  document.getElementById('beaconResults').textContent='Scanning...';
  try{
    const r=await fetch('/api/ping');
    const d=await r.json();
    document.getElementById('beaconResults').textContent='UDP scan is server-side. Use manual IP entry for now.';
  }catch(e){document.getElementById('beaconResults').textContent='Error: '+e.message}
}

// ── Init settings UI ────────────────────────────────────────────────────
(function(){
  var s=loadSettings();
  document.getElementById('settingLang').value=s.lang||'en';
  document.getElementById('settingBackup').value=s.backup||'true';
  document.getElementById('settingConflict').value=s.conflict||'skip';
  document.getElementById('settingAutoSync').value=s.autoSync||'0';
  document.getElementById('settingAutoPull').value=s.autoPull||'none';
})();

init();
</script>
</body>
</html>"""

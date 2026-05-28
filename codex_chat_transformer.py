#!/usr/bin/env python3
"""
Codex Chat Transformer — migrates sessions between model_provider types.

When you switch Codex from subscription (openai) to API key (custom provider),
old sessions become invisible because the UI filters by model_provider.

This tool:
  1. Creates a full backup (DB + JSONL files)
  2. Updates model_provider in state_5.sqlite (threads table)
  3. Updates model_provider in JSONL rollout files (session_meta events)

Usage:
  python codex_chat_transformer.py --from openai --to MyProvider [--dry-run] [--thread ID]
  python codex_chat_transformer.py --from MyProvider --to openai [--dry-run]
  python codex_chat_transformer.py --list                          # show current breakdown
  python codex_chat_transformer.py --restore BACKUP_DIR            # restore from backup
  python codex_chat_transformer.py --pin-top 10 [--project DIR]   # pin N most recent threads
  python codex_chat_transformer.py --unpin-all                     # clear all pins
  python codex_chat_transformer.py --pin-list                      # show currently pinned threads
  python codex_chat_transformer.py --backup                        # full ZIP backup of .codex
  python codex_chat_transformer.py --restore-zip FILE              # restore from ZIP backup
"""

import argparse
import base64
import datetime
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
STATE_DB = CODEX_DIR / "state_5.sqlite"
GLOBAL_STATE = CODEX_DIR / ".codex-global-state.json"
PROVIDERS_FILE = CODEX_DIR / "providers.json"
SESSIONS_DIR = CODEX_DIR / "sessions"
ARCHIVED_DIR = CODEX_DIR / "archived_sessions"
PACK_ROOT = "codex-pack"
PROVIDERS_LIST_SENTINEL = "__LIST__"
HISTORY_MAX_BYTES = 2 * 1024 * 1024
HISTORY_ROTATIONS = 3


def parse_sync_peer(raw_target):
    """Parse CLI sync peer input and validate host/port before any network I/O."""
    target = (raw_target or "").strip()
    if not target:
        raise ValueError("sync target is required")

    scheme = "http"
    host = ""
    port = 8080

    if "://" in target:
        parsed = urlparse(target)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            raise ValueError("sync target scheme must be http or https")
        host = parsed.hostname or ""
        if not host:
            raise ValueError("sync target host is required")
        try:
            port = parsed.port if parsed.port is not None else 8080
        except ValueError:
            raise ValueError("sync target port must be numeric")
    else:
        if target.startswith(":"):
            raise ValueError("sync target host is required")
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            host = host.strip()
            if not host:
                raise ValueError("sync target host is required")
            if not port_str.isdigit():
                raise ValueError("sync target port must be numeric")
            port = int(port_str)
        else:
            host = target

    if not host:
        raise ValueError("sync target host is required")
    if not 1 <= int(port) <= 65535:
        raise ValueError("sync target port must be between 1 and 65535")
    return {"scheme": scheme, "host": host, "port": int(port)}


def get_db_conn(exit_on_error=True):
    if not STATE_DB.exists():
        if exit_on_error:
            print(f"ERROR: Database not found: {STATE_DB}")
            sys.exit(1)
        return None
    conn = sqlite3.connect(str(STATE_DB))
    conn.row_factory = sqlite3.Row
    return conn


def list_threads(conn):
    """Show breakdown of threads by model_provider."""
    cur = conn.cursor()
    cur.execute("""
        SELECT model_provider, COUNT(*) as cnt,
               MIN(created_at_ms) as earliest,
               MAX(created_at_ms) as latest
        FROM threads
        GROUP BY model_provider
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()

    print("\n=== Thread breakdown by model_provider ===\n")
    print(f"{'Provider':<20} {'Count':>6}  {'Earliest':<22}  {'Latest':<22}")
    print("-" * 75)
    for row in rows:
        earliest = datetime.datetime.fromtimestamp(row["earliest"] / 1000).strftime("%Y-%m-%d %H:%M") if row["earliest"] else "N/A"
        latest = datetime.datetime.fromtimestamp(row["latest"] / 1000).strftime("%Y-%m-%d %H:%M") if row["latest"] else "N/A"
        print(f"{row['model_provider']:<20} {row['cnt']:>6}  {earliest:<22}  {latest:<22}")

    # Also show non-archived vs archived
    cur.execute("SELECT archived, COUNT(*) FROM threads GROUP BY archived")
    arch_rows = cur.fetchall()
    print()
    for ar in arch_rows:
        status = "archived" if ar[0] else "active"
        print(f"  {status}: {ar[1]} threads")

    # Show source breakdown
    cur.execute("""
        SELECT
            CASE
                WHEN source IN ('cli', 'exec', 'vscode') THEN source
                WHEN source LIKE '%subagent%' THEN 'subagent'
                ELSE 'other'
            END as src_group,
            model_provider, COUNT(*) as cnt
        FROM threads
        GROUP BY src_group, model_provider
        ORDER BY src_group, model_provider
    """)
    src_rows = cur.fetchall()
    print(f"\n{'Source':<15} {'Provider':<20} {'Count':>6}")
    print("-" * 45)
    for row in src_rows:
        print(f"{row[0]:<15} {row[1]:<20} {row[2]:>6}")


def get_thread_stats():
    """Return thread statistics for GUI consumption."""
    conn = get_db_conn(exit_on_error=False)
    if not conn:
        return {}, 0, 0
    cur = conn.cursor()
    cur.execute("SELECT model_provider, COUNT(*) as cnt FROM threads GROUP BY model_provider")
    stats = {row["model_provider"]: row["cnt"] for row in cur.fetchall()}
    cur.execute("SELECT archived, COUNT(*) FROM threads GROUP BY archived")
    active = 0
    archived = 0
    for row in cur.fetchall():
        if row[0]:
            archived = row[1]
        else:
            active = row[1]
    conn.close()
    return stats, active, archived


def create_backup(from_provider):
    """Create timestamped backup of DB and affected JSONL files."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = CODEX_DIR / f"backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Backup DB
    db_backup = backup_dir / "state_5.sqlite"
    shutil.copy2(str(STATE_DB), str(db_backup))
    # Also copy WAL and SHM if they exist
    for ext in ("-shm", "-wal"):
        src = str(STATE_DB) + ext
        if os.path.exists(src):
            shutil.copy2(src, str(db_backup) + ext)

    # Backup providers.json
    if PROVIDERS_FILE.exists():
        shutil.copy2(str(PROVIDERS_FILE), str(backup_dir / "providers.json"))

    print(f"Backup created: {backup_dir}")
    record_history("backup_created", provider=from_provider, backup_path=str(backup_dir))
    return backup_dir


def _get_timestamp_from_filename(filepath):
    """Extract creation timestamp from rollout filename."""
    fname = os.path.basename(filepath)
    try:
        ts_part = fname.replace("rollout-", "").split("-019")[0]
        dt = datetime.datetime.strptime(ts_part, "%Y-%m-%dT%H-%M-%S")
        return dt.timestamp()
    except (ValueError, IndexError):
        return None


def _get_last_event_ts(filepath):
    """Get timestamp of last event in a JSONL rollout file."""
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


def transform_jsonl_file(filepath, from_provider, to_provider, dry_run=False, from_model=None, to_model=None):
    """Update model_provider in a JSONL rollout file."""
    if not filepath or not os.path.exists(filepath):
        return False

    # Normalize path (handle \\?\ prefix on Windows)
    filepath = filepath.replace("\\\\?\\", "")
    if not os.path.exists(filepath):
        return False

    # Save original timestamps before modification
    orig_atime = os.path.getatime(filepath)
    orig_mtime = os.path.getmtime(filepath)

    changed = False
    lines_out = []

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                lines_out.append(line)
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                lines_out.append(line)
                continue

            # Only update session_meta events with matching provider
            if (obj.get("type") == "session_meta"
                    and obj.get("payload", {}).get("model_provider") == from_provider):
                obj["payload"]["model_provider"] = to_provider
                if from_model and obj.get("payload", {}).get("model") == from_model:
                    obj["payload"]["model"] = to_model
                changed = True
                lines_out.append(json.dumps(obj, ensure_ascii=False))
            else:
                lines_out.append(line)

    if changed and not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            for line in lines_out:
                f.write(line + "\n")
        # Restore original file timestamps
        os.utime(filepath, (orig_atime, orig_mtime))

    return changed


def transform(conn, from_provider, to_provider, dry_run=False, thread_id=None, skip_pinned=False, from_model=None, to_model=None, project=None):
    """Main transformation: update DB and JSONL files."""
    if is_codex_running():
        print("WARNING: Codex Desktop is running. Restart Codex after conversion.")
    cur = conn.cursor()

    pinned_ids = set()
    if skip_pinned:
        state = load_global_state()
        pinned_ids = set(state.get("pinned-thread-ids", []))

    # Find threads to transform
    if thread_id:
        cur.execute(
            "SELECT id, rollout_path, title, model_provider FROM threads WHERE id = ? AND model_provider = ?",
            (thread_id, from_provider),
        )
    elif project:
        cur.execute(
            "SELECT id, rollout_path, title, model_provider FROM threads WHERE model_provider = ? AND cwd LIKE ?",
            (from_provider, f"%{project}%"),
        )
    else:
        cur.execute(
            "SELECT id, rollout_path, title, model_provider FROM threads WHERE model_provider = ?",
            (from_provider,),
        )

    threads = cur.fetchall()
    if not threads:
        print(f"No threads found with model_provider='{from_provider}'"
              + (f" and id='{thread_id}'" if thread_id else ""))
        return

    print(f"\nFound {len(threads)} threads with model_provider='{from_provider}'")
    if dry_run:
        print("[DRY RUN] No changes will be made.\n")

    # Create backup (unless dry run)
    backup_dir = None
    if not dry_run:
        backup_dir = create_backup(from_provider)

    jsonl_updated = 0
    jsonl_not_found = 0
    jsonl_no_change = 0

    for i, thread in enumerate(threads):
        tid = thread["id"]
        rollout = thread["rollout_path"]
        title = (thread["title"] or "")[:60]

        if tid in pinned_ids:
            continue

        if not dry_run:
            # Update DB
            cur.execute(
                "UPDATE threads SET model_provider = ? WHERE id = ?",
                (to_provider, tid),
            )

        # Update JSONL rollout file
        if rollout:
            changed = transform_jsonl_file(rollout, from_provider, to_provider, dry_run, from_model, to_model)
            if changed:
                jsonl_updated += 1
            elif os.path.exists(rollout.replace("\\\\?\\", "")):
                jsonl_no_change += 1
            else:
                jsonl_not_found += 1

        # Also check archived_sessions
        archived_pattern = f"rollout-*{tid}.jsonl"
        if os.path.isdir(str(ARCHIVED_DIR)):
            for fname in os.listdir(str(ARCHIVED_DIR)):
                if tid in fname:
                    fpath = os.path.join(str(ARCHIVED_DIR), fname)
                    transform_jsonl_file(fpath, from_provider, to_provider, dry_run)

        if (i + 1) % 50 == 0 or i == len(threads) - 1:
            print(f"  Processed {i + 1}/{len(threads)} threads...")

    skipped_pinned = sum(1 for t in threads if t["id"] in pinned_ids)
    converted = [t for t in threads if t["id"] not in pinned_ids]

    if not dry_run:
        conn.commit()
        print(f"\nDatabase updated: {len(converted)} threads changed from '{from_provider}' to '{to_provider}'"
              + (f" ({skipped_pinned} pinned skipped)" if skipped_pinned else ""))
        print(f"Backup saved to: {backup_dir}")
    else:
        print(f"\n[DRY RUN] Would change {len(converted)} threads from '{from_provider}' to '{to_provider}'"
              + (f" ({skipped_pinned} pinned would be skipped)" if skipped_pinned else ""))

    print(f"\nJSONL files: {jsonl_updated} updated, {jsonl_no_change} no change needed, {jsonl_not_found} not found")

    # Verification: spot-check a few converted threads
    if not dry_run and converted:
        cur.execute(
            "SELECT COUNT(*) as cnt FROM threads WHERE model_provider = ?",
            (to_provider,),
        )
        total_to = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT COUNT(*) as cnt FROM threads WHERE model_provider = ?",
            (from_provider,),
        )
        remaining_from = cur.fetchone()["cnt"]
        print(f"\nVerification: {total_to} threads now with '{to_provider}', {remaining_from} remaining with '{from_provider}'")

    # Swap config and auth files to match target provider
    if not dry_run:
        swap_configs(to_provider)


def is_codex_running():
    """Check if Codex Desktop process is running."""
    import platform
    try:
        if platform.system() == "Windows":
            result = os.popen('tasklist /FI "IMAGENAME eq Codex.exe" /NH 2>NUL').read()
            return "Codex.exe" in result
        else:
            result = os.popen("pgrep -f 'codex' 2>/dev/null").read()
            return len(result.strip()) > 0
    except Exception:
        return False


def _read_config_info():
    """Read current config.toml provider/model info."""
    cfg_path = CODEX_DIR / "config.toml"
    info = {"provider": "?", "model": "?"}
    if cfg_path.exists():
        with open(str(cfg_path), "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("model_provider"):
                    info["provider"] = s.split("=", 1)[1].strip().strip('"')
                elif s.startswith("model") and "=" in s and not s.startswith("model_"):
                    info["model"] = s.split("=", 1)[1].strip().strip('"')
    return info


def _read_auth_info():
    """Read current auth.json info."""
    auth_path = CODEX_DIR / "auth.json"
    if not auth_path.exists():
        return {"mode": "none", "has_key": False}
    try:
        with open(str(auth_path), "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "mode": data.get("auth_mode", "unknown"),
            "has_key": bool(data.get("OPENAI_API_KEY")),
        }
    except Exception:
        return {"mode": "error", "has_key": False}


def _history_path():
    return CODEX_DIR / "operation_history.jsonl"


def _history_logging_enabled():
    try:
        return PROVIDERS_FILE.parent.resolve() == CODEX_DIR.resolve()
    except Exception:
        return True


def _redact_history_value(key, value):
    key_l = str(key or "").lower()
    sensitive = (
        key_l in ("key", "api_key", "openai_api_key", "pin", "remote_pin", "sync_pin", "token", "client_token")
        or key_l.endswith("_key")
        or key_l.endswith("_token")
        or key_l in ("auth.json", "auth")
    )
    if sensitive:
        return "***"
    if isinstance(value, dict):
        return {k: _redact_history_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_history_value(key, item) for item in value]
    if isinstance(value, str) and ("OPENAI_API_KEY" in value or "sk-" in value):
        return "***"
    return value


def _rotate_history_if_needed(path):
    if not path.exists() or path.stat().st_size <= HISTORY_MAX_BYTES:
        return
    for idx in range(HISTORY_ROTATIONS - 1, 0, -1):
        src = path.with_name(f"{path.name}.{idx}")
        dst = path.with_name(f"{path.name}.{idx + 1}")
        if src.exists():
            if idx + 1 > HISTORY_ROTATIONS:
                src.unlink()
            else:
                src.replace(dst)
    path.replace(path.with_name(f"{path.name}.1"))


def record_history(action, status="ok", source="cli", **fields):
    """Append a small operation-history record without secrets."""
    if not _history_logging_enabled():
        return
    try:
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_history_if_needed(path)
        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": source,
            "action": action,
            "status": status,
        }
        for key, value in fields.items():
            record[key] = _redact_history_value(key, value)
        with open(str(path), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


def load_history(limit=20):
    """Load operation history newest-first."""
    try:
        limit = int(limit)
    except Exception:
        limit = 20
    limit = max(1, limit)
    path = _history_path()
    if not path.exists():
        return []
    records = []
    try:
        with open(str(path), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return list(reversed(records))[:limit]


def print_history(limit=20):
    records = load_history(limit)
    if not records:
        print("No operation history.")
        return
    print(f"\n=== Operation history ({len(records)}) ===\n")
    print(f"{'Time':<22} {'Source':<8} {'Action':<24} {'Status':<8} Summary")
    print("-" * 88)
    for rec in records:
        summary_parts = []
        for key in ("provider", "from_provider", "to_provider", "zip_path", "backup_path"):
            if rec.get(key):
                summary_parts.append(f"{key}={rec[key]}")
        details = rec.get("details")
        if isinstance(details, dict):
            for key in ("providers", "sessions", "path"):
                if key in details:
                    summary_parts.append(f"{key}={details[key]}")
        print(f"{rec.get('ts', '')[:22]:<22} {rec.get('source', ''):<8} {rec.get('action', ''):<24} {rec.get('status', ''):<8} {'; '.join(summary_parts)}")


def _profile_auth_has_key(prof):
    auth_raw = _decode_secret(prof.get("auth.json", ""))
    if not auth_raw:
        return False
    try:
        return bool(json.loads(auth_raw).get("OPENAI_API_KEY"))
    except Exception:
        return "OPENAI_API_KEY" in auth_raw


def _section_has_provider_header(section, provider):
    return f"[model_providers.{provider}]" in (section or "")


def _section_has_base_url(section):
    for line in (section or "").splitlines():
        if line.strip().startswith("base_url") and "=" in line:
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return bool(value)
    return False


def _active_auth_ok(provider, auth):
    if provider == "openai" and auth.get("mode") == "chatgpt":
        return True
    if auth.get("mode") == "apikey" and auth.get("has_key"):
        return True
    return False


def build_doctor_report():
    """Build read-only doctor data for CLI and tests."""
    running = is_codex_running()
    cfg = _read_config_info()
    auth = _read_auth_info()
    prov_data = _load_providers()
    profiles = prov_data.get("profiles", {})
    active = cfg.get("provider")
    issues = []
    warnings = []

    if not _active_auth_ok(active, auth):
        issues.append(f"active auth incomplete for provider '{active}'")

    if active and active not in ("?", "openai") and active not in profiles:
        warnings.append(f"active provider '{active}' is not saved")
    elif active == "openai" and profiles and active not in profiles:
        warnings.append("active provider 'openai' is not saved")

    for name, prof in profiles.items():
        model_provider = prof.get("model_provider") or name
        section = prof.get("provider_section", "")
        if model_provider != name:
            warnings.append(f"profile '{name}' stores model_provider '{model_provider}'")
        if not section:
            issues.append(f"profile '{name}' missing provider_section")
        elif not _section_has_provider_header(section, model_provider):
            issues.append(f"profile '{name}' section header does not match '{model_provider}'")
        if model_provider != "openai" and not _section_has_base_url(section):
            issues.append(f"profile '{name}' missing base_url")
        if model_provider != "openai" and prof.get("auth_mode") == "apikey" and not _profile_auth_has_key(prof):
            issues.append(f"profile '{name}' missing API key")

    return {
        "running": running,
        "config": cfg,
        "auth": auth,
        "profiles": profiles,
        "active_saved": prov_data.get("active", "none"),
        "provider_health": {"issues": issues, "warnings": warnings},
        "recent_history": load_history(5),
        "auth_ok": _active_auth_ok(active, auth),
    }


def doctor():
    """Read-only health check of Codex state."""
    print("Codex Chat Transformer - Doctor")
    print("-" * 50)

    report = build_doctor_report()
    running = report["running"]
    cfg = report["config"]
    auth = report["auth"]

    print(f"  Codex running:     {'YES (restart recommended)' if running else 'no'}")
    print(f"  Active provider:   {cfg['provider']}")
    print(f"  Active model:      {cfg['model']}")
    print(f"  Auth mode:         {auth['mode']}")
    api_key_status = "not required" if cfg["provider"] == "openai" and auth["mode"] == "chatgpt" else ("present" if auth["has_key"] else "MISSING")
    print(f"  API key:           {api_key_status}")
    print(f"  DB:                {'OK' if STATE_DB.exists() else 'NOT FOUND'}")

    # Provider profiles
    profiles = report["profiles"]
    active_saved = report["active_saved"]
    print(f"  Saved profiles:    {len(profiles)}")
    print(f"  Last active slot:  {active_saved}")
    print()
    print("  Provider health:")
    health = report["provider_health"]
    if not health["issues"] and not health["warnings"]:
        print("    OK")
    for issue in health["issues"]:
        print(f"    ISSUE: {issue}")
    for warning in health["warnings"]:
        print(f"    WARN:  {warning}")

    # Thread stats
    if STATE_DB.exists():
        conn = get_db_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute("SELECT model_provider, COUNT(*) as cnt FROM threads GROUP BY model_provider ORDER BY cnt DESC")
        rows = cur.fetchall()
        total_threads = sum(r[1] for r in rows)

        print()
        print(f"  Threads by provider ({total_threads} total):")
        for row in rows:
            marker = " <<<" if row[0] == cfg["provider"] else ""
            print(f"    {row[0]:<25} {row[1]:>6}{marker}")

        # DB ↔ JSONL consistency
        cur.execute("SELECT id, rollout_path, model_provider FROM threads")
        threads = cur.fetchall()
        missing = 0
        mismatch = 0
        for t in threads:
            rollout = t[1]
            if not rollout:
                missing += 1
                continue
            path = rollout.replace("\\\\?\\", "")
            if not os.path.exists(path):
                missing += 1
                continue
            # Check provider match in first session_meta
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        if obj.get("type") == "session_meta":
                            jsonl_provider = obj.get("payload", {}).get("model_provider", "")
                            if jsonl_provider and jsonl_provider != t[2]:
                                mismatch += 1
                            break
            except Exception:
                pass

        # Pinned threads
        state = load_global_state()
        pinned = len(state.get("pinned-thread-ids", []))

        print()
        print(f"  DB <-> JSONL consistency:")
        print(f"    Missing rollout:   {missing}")
        print(f"    Provider mismatch: {mismatch}")
        print(f"  Pinned threads:      {pinned}")
        conn.close()
    else:
        print("\n  [!] Database not found - cannot check threads.")

    recent = report["recent_history"]
    if recent:
        print()
        print("  Recent operations:")
        for rec in recent[:5]:
            print(f"    {rec.get('ts', '')[:19]}  {rec.get('action', '')}  {rec.get('status', '')}")

    print("-" * 50)
    status = "OK" if not running and report["auth_ok"] and not health["issues"] else "ISSUES DETECTED"
    print(f"  Status: {status}")


def _detect_provider_in_config(filepath):
    """Read a config.toml and return the model_provider value (or 'openai' for default)."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("model_provider"):
                    return stripped.split("=", 1)[1].strip().strip('"').strip("'")
        return "openai"
    except Exception:
        return None


def _detect_auth_mode(filepath):
    """Read an auth.json and return the auth_mode value."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f).get("auth_mode", "unknown")
    except Exception:
        return None


def _find_prefixed_variants(basename):
    """Find all prefixed variants of a file (e.g., -config.toml, --config.toml)."""
    variants = []
    for prefix in ("-", "--"):
        fpath = CODEX_DIR / f"{prefix}{basename}"
        if fpath.exists():
            variants.append(fpath)
    return variants


def swap_configs(target_provider):
    """Swap config.toml and auth.json with their prefixed backups to match target provider."""
    swaps_done = []

    for basename, detect_fn in [
        ("config.toml", _detect_provider_in_config),
        ("auth.json", _detect_auth_mode),
    ]:
        active = CODEX_DIR / basename
        if not active.exists():
            continue

        active_value = detect_fn(str(active))

        # Check if active already matches target
        if basename == "config.toml" and active_value == target_provider:
            continue
        if basename == "auth.json":
            target_mode = "chatgpt" if target_provider == "openai" else "apikey"
            if active_value == target_mode:
                continue

        # Find prefixed variants
        variants = _find_prefixed_variants(basename)
        if not variants:
            continue

        # Pick variant matching target
        target_variant = None
        for v in variants:
            v_value = detect_fn(str(v))
            if basename == "config.toml" and v_value == target_provider:
                target_variant = v
                break
            elif basename == "auth.json":
                target_mode = "chatgpt" if target_provider == "openai" else "apikey"
                if v_value == target_mode:
                    target_variant = v
                    break

        if not target_variant:
            target_variant = variants[0]

        # Swap: active -> tmp, variant -> active, tmp -> variant position
        tmp_path = CODEX_DIR / f"{basename}.swapping"
        os.rename(str(active), str(tmp_path))
        os.rename(str(target_variant), str(active))
        os.rename(str(tmp_path), str(target_variant))
        swaps_done.append(basename)

    if swaps_done:
        print(f"Config files swapped: {', '.join(swaps_done)}")


def restore_backup(backup_dir):
    """Restore state_5.sqlite from a backup directory."""
    backup_dir = Path(backup_dir)
    db_backup = backup_dir / "state_5.sqlite"
    if not db_backup.exists():
        print(f"ERROR: No state_5.sqlite found in {backup_dir}")
        sys.exit(1)

    # Copy back
    shutil.copy2(str(db_backup), str(STATE_DB))
    for ext in ("-shm", "-wal"):
        src = str(db_backup) + ext
        dst = str(STATE_DB) + ext
        if os.path.exists(src):
            shutil.copy2(src, dst)
        elif os.path.exists(dst):
            os.remove(dst)

    print(f"Restored state_5.sqlite from {backup_dir}")
    print("NOTE: JSONL files were NOT restored (they may have been modified in-place).")
    print("      If you need full rollback, restore the entire .codex/sessions/ directory manually.")
    record_history("restore_backup", backup_path=str(backup_dir))


def load_global_state():
    """Load .codex-global-state.json."""
    if not GLOBAL_STATE.exists():
        print(f"ERROR: Global state not found: {GLOBAL_STATE}")
        sys.exit(1)
    with open(str(GLOBAL_STATE), "r", encoding="utf-8") as f:
        return json.load(f)


def save_global_state(state):
    """Save .codex-global-state.json."""
    with open(str(GLOBAL_STATE), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def pin_top_threads(conn, n, project=None):
    """Pin top N most recent active threads (optionally filtered by project cwd)."""
    cur = conn.cursor()
    query = """
        SELECT id, title, model_provider, updated_at_ms
        FROM threads
        WHERE archived = 0 AND source IN ('cli', 'vscode', 'exec')
    """
    params = []
    if project:
        query += " AND cwd LIKE ?"
        params.append(f"%{project}%")
    query += " ORDER BY updated_at_ms DESC LIMIT ?"
    params.append(n)

    cur.execute(query, params)
    threads = cur.fetchall()

    if not threads:
        print("No matching threads found.")
        return

    state = load_global_state()
    pinned = set(state.get("pinned-thread-ids", []))
    added = []

    print(f"\nPinning top {len(threads)} most recent threads:\n")
    for t in threads:
        ts = datetime.datetime.fromtimestamp(t["updated_at_ms"] / 1000).strftime("%Y-%m-%d %H:%M") if t["updated_at_ms"] else "N/A"
        marker = "  (already pinned)" if t["id"] in pinned else ""
        print(f"  {ts}  [{t['model_provider']}]  {(t['title'] or '')[:55]}{marker}")
        if t["id"] not in pinned:
            pinned.add(t["id"])
            added.append(t["id"])

    if added:
        state["pinned-thread-ids"] = list(pinned)
        save_global_state(state)
        print(f"\nPinned {len(added)} new threads (total pinned: {len(pinned)})")
    else:
        print("\nAll already pinned.")


def unpin_all():
    """Clear all pinned threads."""
    state = load_global_state()
    old_count = len(state.get("pinned-thread-ids", []))
    state["pinned-thread-ids"] = []
    save_global_state(state)
    print(f"Cleared {old_count} pinned threads.")


def list_pinned(conn):
    """Show currently pinned threads with details."""
    state = load_global_state()
    pinned_ids = state.get("pinned-thread-ids", [])
    if not pinned_ids:
        print("No pinned threads.")
        return

    cur = conn.cursor()
    placeholders = ",".join("?" for _ in pinned_ids)
    cur.execute(f"SELECT id, title, model_provider, updated_at_ms, cwd FROM threads WHERE id IN ({placeholders})", tuple(pinned_ids))
    rows = {row["id"]: row for row in cur.fetchall()}

    print(f"\n=== Pinned threads ({len(pinned_ids)}) ===\n")
    for tid in pinned_ids:
        row = rows.get(tid)
        if row:
            ts = datetime.datetime.fromtimestamp(row["updated_at_ms"] / 1000).strftime("%Y-%m-%d %H:%M") if row["updated_at_ms"] else "N/A"
            print(f"  {ts}  [{row['model_provider']}]  {(row['title'] or '')[:55]}")
        else:
            print(f"  {tid[:20]}...  (not found in DB)")


def full_backup():
    """Create a full ZIP backup of critical .codex files."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = CODEX_DIR / f"codex_backup_{timestamp}.zip"

    # Essential files to back up (relative to CODEX_DIR)
    essential_files = [
        "state_5.sqlite",
        "state_5.sqlite-shm",
        "state_5.sqlite-wal",
        ".codex-global-state.json",
        ".codex-global-state.json.bak",
        "config.toml",
        "--config.toml",
        "-config.toml",
        "auth.json",
        "--auth.json",
        "-auth.json",
        "session_index.jsonl",
        "models_cache.json",
        "installation_id",
        "version.json",
        "AGENTS.md",
        "providers.json",
    ]

    # Directories to include
    dirs_to_include = [
        "sessions",
        "archived_sessions",
        "sqlite",
    ]

    file_count = 0
    total_bytes = 0

    print(f"Creating full backup: {zip_path}")
    print()

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # Add essential files
        for fname in essential_files:
            fpath = CODEX_DIR / fname
            if fpath.exists():
                arcname = f"codex/{fname}"
                zf.write(str(fpath), arcname)
                size = fpath.stat().st_size
                total_bytes += size
                file_count += 1
                print(f"  + {fname} ({_fmt_size(size)})")

        # Add directories
        for dirname in dirs_to_include:
            dirpath = CODEX_DIR / dirname
            if not dirpath.exists():
                continue
            for fpath in dirpath.rglob("*"):
                if fpath.is_file():
                    arcname = f"codex/{fpath.relative_to(CODEX_DIR)}"
                    zf.write(str(fpath), arcname)
                    size = fpath.stat().st_size
                    total_bytes += size
                    file_count += 1
            dir_size = sum(f.stat().st_size for f in dirpath.rglob("*") if f.is_file())
            dir_files = sum(1 for f in dirpath.rglob("*") if f.is_file())
            print(f"  + {dirname}/ ({dir_files} files, {_fmt_size(dir_size)})")

    zip_size = zip_path.stat().st_size
    print(f"\nDone: {file_count} files, {_fmt_size(total_bytes)} -> {_fmt_size(zip_size)} compressed")
    print(f"Saved to: {zip_path}")
    record_history("full_backup", backup_path=str(zip_path), details={"files": file_count, "bytes": total_bytes})
    return zip_path


def restore_from_zip(zip_path):
    """Restore .codex from a ZIP backup."""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        print(f"ERROR: ZIP not found: {zip_path}")
        sys.exit(1)

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        names = zf.namelist()
        # Find the codex/ prefix
        prefix = ""
        for n in names:
            if n.endswith("state_5.sqlite"):
                prefix = n.rsplit("state_5.sqlite", 1)[0]
                break

        print(f"Restoring from: {zip_path}")
        print(f"Files in archive: {len(names)}")
        print()

        restored = 0
        for name in names:
            if name.endswith("/"):
                continue
            # Strip prefix to get relative path
            rel = name[len(prefix):] if prefix else name
            dest = CODEX_DIR / rel

            # Create parent dirs
            dest.parent.mkdir(parents=True, exist_ok=True)
            zf.extract(name, str(CODEX_DIR.parent))
            restored += 1

        print(f"Restored {restored} files.")
        print("WARNING: Codex must be restarted to pick up changes.")
        record_history("restore_zip", zip_path=str(zip_path), details={"files": restored})


def _fmt_size(n):
    """Format bytes as human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fix_dates():
    """Set file mtime to last event timestamp for all rollout files."""
    conn = get_db_conn()
    if conn is None:
        return
    cur = conn.cursor()
    cur.execute("SELECT rollout_path FROM threads WHERE rollout_path IS NOT NULL")

    fixed = 0
    failed = 0

    for (rp,) in cur.fetchall():
        rp = rp or ""
        if rp.startswith("\\\\?"):
            rp = rp[4:]
        if not rp or not os.path.exists(rp):
            continue
        ts = _get_last_event_ts(rp)
        if ts:
            os.utime(rp, (ts, ts))
            fixed += 1
        else:
            failed += 1

    # Also fix archived sessions
    if os.path.isdir(str(ARCHIVED_DIR)):
        for fname in os.listdir(str(ARCHIVED_DIR)):
            fpath = os.path.join(str(ARCHIVED_DIR), fname)
            if os.path.isfile(fpath) and fname.endswith(".jsonl"):
                ts = _get_last_event_ts(fpath)
                if ts:
                    os.utime(fpath, (ts, ts))
                    fixed += 1
                else:
                    failed += 1

    conn.close()
    print(f"Fixed: {fixed} files (mtime = last message timestamp)")
    print(f"Failed: {failed}")


def _parse_csv_list(raw):
    if raw is None:
        return None
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    return values


def _load_providers_readonly():
    if not PROVIDERS_FILE.exists():
        return {"profiles": {}, "active": None}
    with open(str(PROVIDERS_FILE), "r", encoding="utf-8") as f:
        return json.load(f)


def _pack_scope_enabled(scope, part):
    return scope == "all" or scope == part


def _pack_leaf_name(raw_name, kind):
    name = str(raw_name or "").strip()
    if not name or any(sep in name for sep in ("/", "\\")) or name in (".", ".."):
        raise ValueError(f"invalid {kind} name for pack: {raw_name!r}")
    return name


def _session_order_column(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
    if "updated_at_ms" in columns:
        return "updated_at_ms"
    if "updated_at" in columns:
        return "updated_at"
    return "id"


def _fetch_session_rows(session_ids=None, project=None):
    conn = get_db_conn(exit_on_error=False)
    if conn is None:
        return []
    try:
        order_col = _session_order_column(conn)
        clauses = []
        params = []
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            clauses.append(f"id IN ({placeholders})")
            params.extend(session_ids)
        if project:
            clauses.append("cwd LIKE ?")
            params.append(f"%{project}%")
        sql = "SELECT * FROM threads"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {order_col} DESC"
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _normalize_rollout_path(rollout_path):
    return (rollout_path or "").replace("\\\\?\\", "")


def _read_rollout_bytes(rollout_path):
    path = _normalize_rollout_path(rollout_path)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _serialize_session_meta(row):
    meta = dict(row)
    meta.pop("rollout_path", None)
    if "archived" in meta:
        meta["archived"] = bool(meta["archived"])
    return meta


def export_pack(zip_file, scope="all", provider_names=None, session_ids=None, without_keys=False):
    provider_names = provider_names or []
    session_ids = session_ids or []
    warnings = []
    provider_entries = []
    session_entries = []

    if _pack_scope_enabled(scope, "providers"):
        data = _load_providers_readonly()
        profiles = data.get("profiles", {})
        selected_names = provider_names or sorted(profiles.keys())
        for name in selected_names:
            prof = profiles.get(name)
            if not prof:
                warnings.append(f"provider not found: {name}")
                continue
            pack_name = _pack_leaf_name(name, "provider")
            payload = json.loads(json.dumps(prof))
            payload["name"] = name
            if without_keys:
                payload["auth.json"] = ""
            provider_entries.append((pack_name, payload))

    if _pack_scope_enabled(scope, "sessions"):
        selected_rows = _fetch_session_rows(session_ids=session_ids or None)
        row_map = {row.get("id"): row for row in selected_rows}
        ordered_ids = session_ids or [row.get("id") for row in selected_rows]
        for sid in ordered_ids:
            row = row_map.get(sid)
            if not row:
                warnings.append(f"session not found: {sid}")
                continue
            pack_id = _pack_leaf_name(row.get("id"), "session")
            rollout_bytes = _read_rollout_bytes(row.get("rollout_path"))
            if rollout_bytes is None:
                warnings.append(f"session skipped (missing rollout): {row.get('id')}")
                continue
            session_entries.append((pack_id, _serialize_session_meta(row), rollout_bytes))

    if scope == "providers" and not provider_entries:
        raise ValueError("no providers matched requested scope")
    if scope == "sessions" and not session_entries:
        raise ValueError("no sessions matched requested scope")
    if scope == "all" and not provider_entries and not session_entries:
        raise ValueError("no providers or sessions matched requested scope")

    zip_path = Path(zip_file)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": "codex-pack",
        "version": 1,
        "scope": scope,
        "without_keys": bool(without_keys),
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "provider_count": len(provider_entries),
        "session_count": len(session_entries),
    }

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{PACK_ROOT}/manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False),
        )
        for name, payload in provider_entries:
            zf.writestr(
                f"{PACK_ROOT}/providers/{name}.json",
                json.dumps(payload, indent=2, ensure_ascii=False),
            )
        for sid, meta, rollout_bytes in session_entries:
            zf.writestr(
                f"{PACK_ROOT}/sessions/{sid}.json",
                json.dumps(meta, indent=2, ensure_ascii=False),
            )
            zf.writestr(f"{PACK_ROOT}/sessions/{sid}.jsonl", rollout_bytes)

    summary = {
        "zip_path": str(zip_path),
        "providers_exported": [name for name, _ in provider_entries],
        "sessions_exported": [sid for sid, _, _ in session_entries],
        "sessions_skipped": sum(1 for msg in warnings if "missing rollout" in msg),
        "warnings": warnings,
    }
    record_history(
        "export_pack",
        zip_path=str(zip_path),
        details={"providers": len(provider_entries), "sessions": len(session_entries), "without_keys": bool(without_keys)},
    )
    return summary


def _validate_pack_member(name):
    parts = PurePosixPath(name).parts
    if not parts:
        raise ValueError("empty path in pack")
    if PurePosixPath(name).is_absolute() or ".." in parts:
        raise ValueError(f"unsafe path in pack: {name}")
    return parts


def _read_pack(zip_file):
    zip_path = Path(zip_file)
    if not zip_path.exists():
        raise ValueError(f"ZIP not found: {zip_file}")

    providers = {}
    session_meta = {}
    session_rollouts = {}
    manifest = None

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = _validate_pack_member(info.filename)
                if parts[0] != PACK_ROOT:
                    raise ValueError(f"unexpected path in pack: {info.filename}")
                if len(parts) == 2 and parts[1] == "manifest.json":
                    manifest = json.loads(zf.read(info).decode("utf-8"))
                    continue
                if len(parts) != 3:
                    raise ValueError(f"unexpected path in pack: {info.filename}")
                bucket = parts[1]
                leaf = parts[2]
                if bucket == "providers" and leaf.endswith(".json"):
                    name = _pack_leaf_name(leaf[:-5], "provider")
                    providers[name] = json.loads(zf.read(info).decode("utf-8"))
                elif bucket == "sessions" and leaf.endswith(".jsonl"):
                    sid = _pack_leaf_name(leaf[:-6], "session")
                    session_rollouts[sid] = zf.read(info)
                elif bucket == "sessions" and leaf.endswith(".json"):
                    sid = _pack_leaf_name(leaf[:-5], "session")
                    session_meta[sid] = json.loads(zf.read(info).decode("utf-8"))
                else:
                    raise ValueError(f"unexpected path in pack: {info.filename}")
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in pack: {e}") from e

    if not isinstance(manifest, dict):
        raise ValueError("manifest.json missing or malformed")
    if manifest.get("format") not in (None, "codex-pack"):
        raise ValueError("unsupported pack format")

    missing_pairs = sorted(set(session_meta) ^ set(session_rollouts))
    if missing_pairs:
        raise ValueError(f"session metadata/rollout mismatch for: {', '.join(missing_pairs)}")
    return manifest, providers, session_meta, session_rollouts


def _align_codex_sync_paths(codex_sync):
    codex_sync.CODEX_DIR = CODEX_DIR
    codex_sync.STATE_DB = STATE_DB
    codex_sync.PROVIDERS_FILE = PROVIDERS_FILE
    codex_sync.SESSIONS_DIR = SESSIONS_DIR


def import_pack(zip_file, scope="all", provider_names=None, session_ids=None):
    provider_names = provider_names or []
    session_ids = session_ids or []
    manifest, providers, session_meta, session_rollouts = _read_pack(zip_file)
    warnings = []

    selected_provider_names = []
    selected_session_ids = []
    if _pack_scope_enabled(scope, "providers"):
        for name in (provider_names or sorted(providers.keys())):
            if name not in providers:
                warnings.append(f"provider not found in pack: {name}")
                continue
            selected_provider_names.append(name)
    if _pack_scope_enabled(scope, "sessions"):
        for sid in (session_ids or sorted(session_meta.keys())):
            if sid not in session_meta:
                warnings.append(f"session not found in pack: {sid}")
                continue
            selected_session_ids.append(sid)

    if scope == "providers" and not selected_provider_names:
        raise ValueError("no providers matched requested scope")
    if scope == "sessions" and not selected_session_ids:
        raise ValueError("no sessions matched requested scope")
    if scope == "all" and not selected_provider_names and not selected_session_ids:
        raise ValueError("no providers or sessions matched requested scope")

    backup_path = full_backup()

    if selected_provider_names:
        data = _load_providers_readonly()
        profiles = data.setdefault("profiles", {})
        for name in selected_provider_names:
            record = json.loads(json.dumps(providers[name]))
            record.pop("name", None)
            record.setdefault("model_provider", name)
            record.setdefault("model", "")
            record.setdefault("auth_mode", "")
            record.setdefault("provider_section", "")
            record.setdefault("auth.json", "")
            record.setdefault("saved_at", datetime.datetime.now().isoformat())
            profiles[name] = record
        data["profiles"] = profiles
        _save_providers(data)

    if selected_session_ids:
        import base64
        import codex_sync

        _align_codex_sync_paths(codex_sync)
        for sid in selected_session_ids:
            meta = json.loads(json.dumps(session_meta[sid]))
            meta["id"] = sid
            codex_sync._store_session(
                meta,
                base64.b64encode(session_rollouts[sid]).decode("ascii"),
            )

    summary = {
        "backup_path": str(backup_path),
        "manifest": manifest,
        "providers_imported": selected_provider_names,
        "sessions_imported": selected_session_ids,
        "warnings": warnings,
    }
    record_history(
        "import_pack",
        zip_path=str(zip_file),
        backup_path=str(backup_path),
        details={"providers": len(selected_provider_names), "sessions": len(selected_session_ids)},
    )
    return summary


def _session_metadata_match(row, query):
    for field in ("title", "preview", "first_user_message", "cwd", "model_provider", "id"):
        value = row.get(field, "")
        if query in str(value or "").casefold():
            return True
    return False


def search_sessions(query, project=None):
    needle = (query or "").strip()
    if not needle:
        raise ValueError("search query is required")
    rows = _fetch_session_rows(project=project)
    needle_cf = needle.casefold()
    results = []
    for row in rows:
        reason = None
        if _session_metadata_match(row, needle_cf):
            reason = "metadata"
        else:
            rollout_bytes = _read_rollout_bytes(row.get("rollout_path"))
            if rollout_bytes is not None:
                rollout_text = rollout_bytes.decode("utf-8", errors="replace")
                if needle_cf in rollout_text.casefold():
                    reason = "jsonl"
        if not reason:
            continue
        results.append({
            "id": row.get("id", ""),
            "title": row.get("title", "") or "",
            "model_provider": row.get("model_provider", "") or "",
            "cwd": row.get("cwd", "") or "",
            "updated_at_ms": row.get("updated_at_ms") or (row.get("updated_at") or 0) * 1000,
            "reason": reason,
        })
    return results


def print_search_results(results):
    if not results:
        print("No sessions matched.")
        return
    for item in results:
        title = " ".join(str(item.get("title", "")).split())[:60]
        cwd = " ".join(str(item.get("cwd", "")).split())[:60]
        print(f"{item['id']} | {item['model_provider']} | {title} | {cwd}")


def print_pack_summary(action, summary):
    print(f"{action} pack: {summary.get('zip_path') or summary.get('backup_path', '')}")
    if "providers_exported" in summary:
        print(f"  Providers: {len(summary['providers_exported'])}")
        print(f"  Sessions:  {len(summary['sessions_exported'])}")
        if summary.get("sessions_skipped"):
            print(f"  Skipped sessions: {summary['sessions_skipped']}")
    else:
        print(f"  Providers: {len(summary['providers_imported'])}")
        print(f"  Sessions:  {len(summary['sessions_imported'])}")
        print(f"  Backup:    {summary['backup_path']}")
    for warning in summary.get("warnings", []):
        print(f"WARNING: {warning}")


# ── Provider profiles management ──────────────────────────────────────────

def _detect_provider_from_text(text):
    """Get model_provider from TOML text."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("model_provider"):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return "openai"


def _sanitize_name(name):
    """Replace spaces and invalid chars in provider name with underscores."""
    import re
    return re.sub(r'[\s/\\:*?"<>|]+', '_', name.strip())


def _extract_provider_config(config_text):
    """Extract provider-specific parts from config.toml.
    Returns (provider_name, provider_section_text, model_value)."""
    provider_name = None
    provider_section = []
    model_value = None
    in_section = False

    for line in config_text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("model_provider"):
            provider_name = stripped.split("=", 1)[1].strip().strip('"').strip("'")

        if stripped.startswith("model") and "=" in stripped and not stripped.startswith("model_"):
            model_value = stripped.split("=", 1)[1].strip().strip('"').strip("'")

        if stripped.startswith("[model_providers."):
            in_section = True
            provider_section.append(line)
            continue

        if in_section:
            if stripped.startswith("[") and not stripped.startswith("[model_providers."):
                in_section = False
            else:
                provider_section.append(line)

    return provider_name, "\n".join(provider_section), model_value


def _extract_named_section(config_text, provider_name):
    """Extract a specific [model_providers.XXX] section by name.
    Returns section text or empty string."""
    sections = {}
    current_name = None
    current_lines = []
    in_section = False

    for line in config_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("[model_providers."):
            # Save previous section
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines)
            current_name = stripped[len("[model_providers."):-1].strip('"').strip("'")
            current_lines = [line]
            in_section = True
            continue
        if in_section:
            if stripped.startswith("[") and not stripped.startswith("[model_providers."):
                in_section = False
                if current_name is not None:
                    sections[current_name] = "\n".join(current_lines)
                current_name = None
            else:
                current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines)

    return sections.get(provider_name, "")


def _remove_provider_section(text, provider_name):
    """Remove a [model_providers.X] section from TOML text."""
    lines = text.split("\n")
    out = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[model_providers."):
            sec_name = stripped[len("[model_providers."):-1].strip('"').strip("'")
            if sec_name == provider_name:
                skip = True
                continue
            else:
                skip = False
                out.append(line)
                continue
        if skip:
            if stripped.startswith("["):
                skip = False
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def _merge_config(current_text, target_provider_name, target_provider_section, target_model=None, target_reasoning=None):
    """Merge provider settings into current config, preserving all preferences.
    Changes only: model_provider, model, model_reasoning_effort fields.
    Updates [model_providers.<target>] section if provided.
    Preserves ALL other [model_providers.*] sections."""
    lines = current_text.split("\n")
    out = []
    target_section_written = False
    in_provider_section = None
    model_provider_written = False

    for line in lines:
        stripped = line.strip()

        # Replace model_provider line
        if stripped.startswith("model_provider") and "=" in stripped:
            out.append(f'model_provider = "{target_provider_name}"')
            model_provider_written = True
            continue

        # Replace model line (top-level only)
        if stripped.startswith("model") and "=" in stripped and not stripped.startswith("model_"):
            if target_model:
                out.append(f'model = "{target_model}"')
            else:
                out.append(line)
            continue

        # Replace or remove model_reasoning_effort line
        if stripped.startswith("model_reasoning_effort") and "=" in stripped:
            if target_reasoning:
                out.append(f'model_reasoning_effort = "{target_reasoning}"')
            # else: drop the line (no reasoning for target)
            continue

        # Detect [model_providers.XXX] section headers
        if stripped.startswith("[model_providers."):
            section_name = stripped[len("[model_providers."):-1].strip('"').strip("'")
            if section_name == target_provider_name:
                if target_provider_section:
                    # Replace target provider section with new one
                    in_provider_section = "target"
                    if not target_section_written:
                        out.append("")
                        out.append(target_provider_section)
                        out.append("")
                        target_section_written = True
                    continue
                else:
                    # No section provided — keep existing as-is
                    in_provider_section = None
                    out.append(line)
                    continue
            else:
                # Keep other provider sections as-is
                in_provider_section = "other"
                out.append(line)
                continue

        if in_provider_section == "target":
            # Skip old target section lines (we replaced it)
            if stripped.startswith("[") and not stripped.startswith("[model_providers."):
                in_provider_section = None
                out.append(line)
            continue

        if in_provider_section == "other":
            # Keep other provider section lines
            if stripped.startswith("[") and not stripped.startswith("[model_providers."):
                in_provider_section = None
            out.append(line)
            continue

        out.append(line)

    # If model_provider wasn't in file, add it
    if not model_provider_written:
        out.insert(0, f'model_provider = "{target_provider_name}"')

    # If target section wasn't in file, append it
    if not target_section_written and target_provider_section:
        out.append("")
        out.append(target_provider_section)

    # If reasoning was requested but line wasn't in file, add it after model
    if target_reasoning and not any(
        l.strip().startswith("model_reasoning_effort") for l in out
    ):
        for i, l in enumerate(out):
            if l.strip().startswith("model ") and "=" in l.strip() and not l.strip().startswith("model_"):
                out.insert(i + 1, f'model_reasoning_effort = "{target_reasoning}"')
                break

    return "\n".join(out)

def _load_providers():
    """Load providers.json. Migrate old format profiles to new format."""
    if not PROVIDERS_FILE.exists():
        return {"profiles": {}, "active": None}
    with open(str(PROVIDERS_FILE), "r", encoding="utf-8") as f:
        data = json.load(f)

    # Auto-migrate old format profiles
    profiles = data.get("profiles", {})
    changed = False
    for name, prof in profiles.items():
        if "config.toml" in prof and "provider_section" not in prof:
            old_cfg = prof["config.toml"]
            if old_cfg:
                _, section, model_val = _extract_provider_config(old_cfg)
                prof["provider_section"] = section or ""
                prof["model"] = model_val or ""
                changed = True
            # Remove old field
            del prof["config.toml"]

    if changed:
        _save_providers(data)

    return data


def _encode_secret(text):
    if not text:
        return text
    return "b64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


def _decode_secret(text):
    if not text or not text.startswith("b64:"):
        return text
    try:
        return base64.b64decode(text[4:]).decode("utf-8")
    except Exception:
        return text


def _save_providers(data):
    """Save providers.json with b64 obfuscation for auth.json fields."""
    out = json.loads(json.dumps(data))
    for prof in out.get("profiles", {}).values():
        auth = prof.get("auth.json")
        if auth and not auth.startswith("b64:"):
            prof["auth.json"] = _encode_secret(auth)
    with open(str(PROVIDERS_FILE), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def _get_active_provider():
    """Detect current active provider from config.toml."""
    cfg_path = CODEX_DIR / "config.toml"
    return _detect_provider_in_config(str(cfg_path)) or "openai"


def _read_file_safe(filepath):
    """Read file content, return None if not found."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def providers_list():
    """Show all saved provider profiles."""
    data = _load_providers()
    active = _get_active_provider()
    profiles = data.get("profiles", {})

    if not profiles:
        print("No provider profiles saved yet.")
        print("Use --save-provider NAME to save current settings as a profile.")
        return

    print(f"\n=== Provider profiles ({len(profiles)}) ===\n")
    print(f"  {'Active':<8}  {'Name':<20}  {'Auth mode':<12}  {'Saved':<20}")
    print(f"  {'-'*8}  {'-'*20}  {'-'*12}  {'-'*20}")
    for name, prof in profiles.items():
        is_active = ">>>" if name == active else ""
        auth_mode = prof.get("auth_mode", "?")
        saved = prof.get("saved_at", "?")[:16]
        print(f"  {is_active:<8}  {name:<20}  {auth_mode:<12}  {saved}")

    print(f"\n  Current active: {active}")
    if active not in profiles:
        print(f"  [!] Active provider '{active}' is not saved. Use --save-provider {active}")


def save_provider(name):
    """Save current provider section + auth as a profile."""
    name = _sanitize_name(name)
    data = _load_providers()
    profiles = data.get("profiles", {})

    cfg_content = _read_file_safe(CODEX_DIR / "config.toml")
    auth_content = _read_file_safe(CODEX_DIR / "auth.json")

    if not cfg_content:
        print("ERROR: config.toml not found.")
        sys.exit(1)

    provider_name, provider_section, model_value = _extract_provider_config(cfg_content)
    if not provider_name:
        provider_name = "openai"
    auth_mode = "unknown"
    if auth_content:
        try:
            auth_mode = json.loads(auth_content).get("auth_mode", "unknown")
        except Exception:
            pass

    profiles[name] = {
        "model_provider": provider_name,
        "model": model_value,
        "auth_mode": auth_mode,
        "provider_section": provider_section,
        "auth.json": auth_content,
        "saved_at": datetime.datetime.now().isoformat(),
    }
    data["profiles"] = profiles
    data["active"] = provider_name
    _save_providers(data)

    print(f"Saved profile '{name}' (provider: {provider_name}, model: {model_value}, auth: {auth_mode})")
    record_history("save_provider", provider=name, details={"model_provider": provider_name, "model": model_value, "auth_mode": auth_mode})


def use_provider(name, skip_convert=False):
    """Switch to a provider profile: swap config/auth + convert threads."""
    if is_codex_running():
        print("WARNING: Codex Desktop is running. Restart Codex after switching.")
    data = _load_providers()
    profiles = data.get("profiles", {})
    active = _get_active_provider()

    if name not in profiles:
        print(f"ERROR: Profile '{name}' not found.")
        print(f"Available: {', '.join(profiles.keys()) or 'none'}")
        sys.exit(1)

    prof = profiles[name]
    target_provider = prof["model_provider"]

    if target_provider == active:
        print(f"Already using '{target_provider}'. No changes needed.")
        record_history("use_provider", status="noop", provider=name, from_provider=active, to_provider=target_provider)
        return

    # 1. Save current active provider back to its profile
    if active not in profiles:
        print(f"Auto-saving current provider '{active}' before switching...")
        current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
        current_auth = _read_file_safe(CODEX_DIR / "auth.json")
        if current_cfg:
            _, section, model_val = _extract_provider_config(current_cfg)
            profiles[active] = {
                "model_provider": active,
                "model": model_val,
                "auth_mode": _detect_auth_mode(str(CODEX_DIR / "auth.json")) or "unknown",
                "provider_section": section,
                "auth.json": current_auth,
                "saved_at": datetime.datetime.now().isoformat(),
            }
    else:
        # Update existing profile with current files
        current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
        current_auth = _read_file_safe(CODEX_DIR / "auth.json")
        if current_cfg:
            _, section, model_val = _extract_provider_config(current_cfg)
            profiles[active]["provider_section"] = section
            profiles[active]["model"] = model_val
        if current_auth:
            profiles[active]["auth.json"] = current_auth

    # 2. Write target profile — merge into config.toml
    print(f"\nSwitching: {active} -> {target_provider}")

    target_section = prof.get("provider_section")
    target_model = prof.get("model")
    target_auth_content = prof.get("auth.json")

    # Backward compat: if profile has old config.toml format, extract section from it
    if not target_section:
        old_cfg = prof.get("config.toml")
        if old_cfg:
            _, target_section, target_model = _extract_provider_config(old_cfg)

    current_cfg = _read_file_safe(CODEX_DIR / "config.toml")
    if current_cfg and target_section:
        merged = _merge_config(current_cfg, target_provider, target_section, target_model)
        with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
            f.write(merged)
        print(f"  config.toml: merged (provider: {target_provider}, all sections preserved)")
    elif current_cfg:
        # No section, just update fields
        merged = _merge_config(current_cfg, target_provider, None, target_model)
        with open(str(CODEX_DIR / "config.toml"), "w", encoding="utf-8") as f:
            f.write(merged)
        print(f"  config.toml: updated (provider: {target_provider})")

    if target_auth_content:
        with open(str(CODEX_DIR / "auth.json"), "w", encoding="utf-8") as f:
            f.write(_decode_secret(target_auth_content))
        auth_mode = prof.get("auth_mode", "?")
        print(f"  auth.json: written (auth_mode: {auth_mode})")

    data["active"] = target_provider
    _save_providers(data)

    # 3. Convert threads
    if not skip_convert:
        conn = get_db_conn()
        if conn is not None:
            try:
                print()
                transform(conn, active, target_provider, thread_id=None, skip_pinned=False)
            finally:
                conn.close()
    record_history("use_provider", provider=name, from_provider=active, to_provider=target_provider, details={"skip_convert": bool(skip_convert)})


def detect_provider():
    """Scan for unsaved provider configs in prefixed files."""
    data = _load_providers()
    profiles = data.get("profiles", {})
    active = _get_active_provider()
    found = []

    for prefix in ("-", "--"):
        for basename in ["config.toml", "auth.json"]:
            fpath = CODEX_DIR / f"{prefix}{basename}"
            if fpath.exists():
                if prefix == "-" and basename == "config.toml":
                    provider = _detect_provider_in_config(str(fpath))
                    if provider and provider != active and provider not in profiles:
                        found.append({"provider": provider, "file": f"{prefix}{basename}"})
                elif prefix == "-" and basename == "auth.json":
                    auth_mode = _detect_auth_mode(str(fpath))
                    if auth_mode and auth_mode == "apikey" and active == "openai":
                        pass  # expected

    # Also check if current active is not saved
    if active not in profiles:
        found.append({"provider": active, "file": "config.toml (active, unsaved)"})

    if not found:
        print("No new providers detected.")
        if profiles:
            print(f"\nSaved profiles: {', '.join(profiles.keys())}")
        print(f"Active: {active}")
        return

    print(f"\n=== Detected providers ===\n")
    for item in found:
        print(f"  Provider: {item['provider']}")
        print(f"  Source:   {item['file']}")
        print()

    if active not in profiles:
        print(f"Current provider '{active}' is not saved.")
        print(f"Run: python codex_chat_transformer.py --save-provider {active}")


def add_provider(json_path, api_key=None):
    """Add a provider from a simple JSON file + optional API key."""
    if json_path == "-":
        raw = json.load(sys.stdin)
    else:
        p = Path(json_path)
        if not p.exists():
            print(f"ERROR: File not found: {json_path}")
            sys.exit(1)
        with open(str(p), "r", encoding="utf-8") as f:
            raw = json.load(f)

    if not isinstance(raw, dict) or "name" not in raw or "base_url" not in raw:
        print("ERROR: JSON must have 'name' and 'base_url' fields.")
        print('Example: {"name": "MyProvider", "model": "gpt-5.5", "base_url": "https://...", "wire_api": "responses"}')
        sys.exit(1)

    name = _sanitize_name(raw["name"])
    model = raw.get("model", "gpt-5.5")
    base_url = raw["base_url"]
    wire_api = raw.get("wire_api", "responses")
    reasoning = raw.get("model_reasoning_effort", "")
    personality = raw.get("personality", "")

    key = api_key or raw.get("api_key", "")
    if not key:
        key = input(f"Enter API key for '{name}': ").strip()
        if not key:
            print("No API key provided. Profile saved without key.")

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
    lines.append(f'wire_api = "{wire_api}"')
    config_text = "\n".join(lines) + "\n"

    auth_text = ""
    auth_mode = "unknown"
    if key:
        auth_text = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": key}, indent=2)
        auth_mode = "apikey"

    provider_section = f'[model_providers.{name}]\nname = "{name}"\nbase_url = "{base_url}"\nwire_api = "{wire_api}"'

    data = _load_providers()
    data.setdefault("profiles", {})[name] = {
        "model_provider": name,
        "model": model,
        "auth_mode": auth_mode,
        "provider_section": provider_section,
        "auth.json": auth_text,
        "saved_at": datetime.datetime.now().isoformat(),
    }
    _save_providers(data)
    print(f"Added provider '{name}' (model: {model}, url: {base_url}, auth: {auth_mode})")
    record_history("add_provider", provider=name, details={"model": model, "base_url": base_url, "auth_mode": auth_mode})


def remove_provider(name):
    """Remove a saved provider profile."""
    data = _load_providers()
    profiles = data.get("profiles", {})
    if name not in profiles:
        print(f"Profile '{name}' not found.")
        return
    del profiles[name]
    data["profiles"] = profiles
    _save_providers(data)
    print(f"Removed profile '{name}'.")
    record_history("remove_provider", provider=name)


def edit_provider(name, model=None, base_url=None, api_key=None, wire_api=None, reasoning=None, new_name=None):
    """Edit a saved provider profile. Only updates fields that are provided."""
    data = _load_providers()
    profiles = data.get("profiles", {})
    if name not in profiles:
        print(f"Profile '{name}' not found.")
        return

    prof = profiles[name]
    old_provider_name = prof.get("model_provider", name)
    final_name = _sanitize_name(new_name) if new_name else name

    # Parse current provider_section
    section_text = prof.get("provider_section", "")
    if not section_text:
        old_cfg = prof.get("config.toml", "")
        if old_cfg:
            _, section_text, _ = _extract_provider_config(old_cfg)

    # Rebuild section with new name and values
    section_lines = section_text.split("\n") if section_text else []
    new_section_lines = []
    for sl in section_lines:
        s = sl.strip()
        if s.startswith("[model_providers."):
            new_section_lines.append(f"[model_providers.{final_name}]")
        elif s.startswith("name") and "=" in s:
            new_section_lines.append(f'name = "{final_name}"')
        elif s.startswith("base_url") and "=" in s:
            new_section_lines.append(f'base_url = "{base_url}"' if base_url else sl)
        elif s.startswith("wire_api") and "=" in s:
            new_section_lines.append(f'wire_api = "{wire_api}"' if wire_api else sl)
        else:
            new_section_lines.append(sl)

    # If base_url/wire_api weren't in section, add them
    if base_url and not any(l.strip().startswith("base_url") for l in new_section_lines):
        new_section_lines.append(f'base_url = "{base_url}"')
    if wire_api and not any(l.strip().startswith("wire_api") for l in new_section_lines):
        new_section_lines.append(f'wire_api = "{wire_api}"')

    new_section = "\n".join(new_section_lines)
    prof["provider_section"] = new_section
    prof["model_provider"] = final_name

    if model:
        prof["model"] = model
    if reasoning is not None:
        prof["model_reasoning_effort"] = reasoning

    if api_key:
        auth_text = json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": api_key}, indent=2)
        prof["auth.json"] = auth_text
        prof["auth_mode"] = "apikey"

    # Handle rename: remove old key, add new
    if new_name and new_name != name:
        del profiles[name]
    profiles[final_name] = prof
    data["profiles"] = profiles
    _save_providers(data)

    changes = []
    if new_name and new_name != name: changes.append(f"name={new_name}")
    if model: changes.append(f"model={model}")
    if base_url: changes.append(f"url={base_url}")
    if api_key: changes.append("key=***")
    if wire_api: changes.append(f"wire_api={wire_api}")
    if reasoning is not None: changes.append(f"reasoning={reasoning or 'default'}")
    print(f"Updated provider '{final_name}': {', '.join(changes)}")
    record_history("edit_provider", provider=final_name, details={"old_name": name, "changes": changes})

    # If this is the active provider (by old or new name), update config.toml
    active = _get_active_provider()
    if active in (old_provider_name, final_name):
        cfg_path = CODEX_DIR / "config.toml"
        cfg_text = _read_file_safe(str(cfg_path))
        if cfg_text:
            # Remove old section if renamed
            if new_name and new_name != name and old_provider_name != final_name:
                cfg_text = _remove_provider_section(cfg_text, old_provider_name)
            merged = _merge_config(cfg_text, final_name, prof["provider_section"],
                                   prof.get("model"), prof.get("model_reasoning_effort"))
            with open(str(cfg_path), "w", encoding="utf-8") as f:
                f.write(merged)
            print(f"  config.toml updated (active provider)")

        # Convert chats when renaming active provider
        if new_name and new_name != name and old_provider_name != final_name:
            conn = get_db_conn()
            if conn is not None:
                try:
                    print()
                    transform(conn, old_provider_name, final_name)
                finally:
                    conn.close()


def set_model(model_name):
    """Change only the model in config.toml. No provider switch."""
    cfg_path = CODEX_DIR / "config.toml"
    cfg_text = _read_file_safe(str(cfg_path))
    if not cfg_text:
        print("ERROR: config.toml not found.")
        return
    lines = cfg_text.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if s.startswith("model") and "=" in s and not s.startswith("model_"):
            out.append(f'model = "{model_name}"')
        else:
            out.append(line)
    with open(str(cfg_path), "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Model changed to: {model_name}")


def _build_droid_model_line(model, source_label):
    return (
        f"  - {model.get('id', '?')} | model={model.get('model', '?')} | "
        f"name={model.get('displayName', '?')} | baseUrl={model.get('baseUrl') or '-'} | "
        f"key={'yes' if model.get('apiKey') else 'no'} | source={source_label}"
    )


def _args_have_droid_command(args):
    return any([
        getattr(args, "droid_models", False),
        getattr(args, "droid_doctor", False),
        getattr(args, "droid_add_neurogate", False),
        bool(getattr(args, "droid_import_provider", None)),
        bool(getattr(args, "droid_use", None)),
        bool(getattr(args, "droid_remove_model", None)),
    ])


def _droid_home_from_args(args):
    import droid_provider_adapter as droid

    return droid.factory_home_from_settings(getattr(args, "droid_settings", None))


def _load_droid_context(args):
    import droid_provider_adapter as droid

    home = _droid_home_from_args(args)
    return droid.load_factory_context(factory_home=home, settings_path=getattr(args, "droid_settings", None))


def _print_droid_models(ctx):
    favorites = ctx["settings"].get("modelFavorites") or []
    print("\n=== Droid Models ===")
    print(f"Factory home: {ctx['home']}")
    print(f"Active model: {ctx['settings'].get('model') or '-'}")
    print(f"Favorites: {', '.join(favorites) if favorites else '-'}")
    print(f"Current customModels: {len(ctx['models'])}")
    for model in ctx["models"]:
        print(_build_droid_model_line(model, model.get("source") or "settings"))
    print(f"Legacy config models: {len(ctx['legacy_models'])}")
    for model in ctx["legacy_models"]:
        print(_build_droid_model_line(model, model.get("source") or "config.json"))


def _droid_doctor_report(ctx):
    issues = []
    seen_ids = {}
    current_models = ctx.get("models") or []

    for model in current_models:
        model_id = model.get("id") or "?"
        seen_ids[model_id] = seen_ids.get(model_id, 0) + 1
        if not model.get("baseUrl"):
            issues.append(f"{model_id}: missing baseUrl")
        if not model.get("apiKey"):
            issues.append(f"{model_id}: missing apiKey")

    for model_id, count in sorted(seen_ids.items()):
        if count > 1:
            issues.append(f"{model_id}: duplicate id ({count})")

    return {
        "ok": not issues,
        "issues": issues,
        "model_count": len(current_models),
        "legacy_count": len(ctx.get("legacy_models") or []),
        "home": str(ctx.get("home") or ""),
        "active_model": ctx.get("settings", {}).get("model") or "",
    }


def _print_droid_doctor(report):
    print("\n=== Droid Doctor ===")
    print(f"Factory home: {report.get('home') or '-'}")
    print(f"Active model: {report.get('active_model') or '-'}")
    print(f"Current models: {report['model_count']}")
    print(f"Legacy models: {report['legacy_count']}")
    print(f"Status: {'OK' if report['ok'] else 'ISSUES'}")
    if report["issues"]:
        print("Issues:")
        for issue in report["issues"]:
            print(f"  - {issue}")
    else:
        print("Issues: none")


def handle_droid_command(args):
    if not _args_have_droid_command(args):
        return False

    try:
        import droid_provider_adapter as droid

        home = _droid_home_from_args(args)

        if args.droid_models:
            _print_droid_models(_load_droid_context(args))
            return True

        if args.droid_doctor:
            report = _droid_doctor_report(_load_droid_context(args))
            _print_droid_doctor(report)
            record_history(
                "droid_doctor_checked",
                details={
                    "ok": report["ok"],
                    "model_count": report["model_count"],
                    "legacy_count": report["legacy_count"],
                },
            )
            return True

        if args.droid_add_neurogate:
            summary = droid.add_neurogate_models(
                home,
                api_key_env=args.droid_api_key_env or "NEUROGATE_API_KEY",
                api_key=args.api_key if args.droid_with_key else None,
            )
            print("Droid NeuroGate models updated.")
            print(f"  Added: {summary['added']}")
            print(f"  Updated: {summary['updated']}")
            print(f"  Path: {summary['path']}")
            record_history(
                "droid_model_added",
                details={
                    "kind": "neurogate",
                    "added": summary["added"],
                    "updated": summary["updated"],
                    "models": summary["models"],
                    "path": str(summary["path"]),
                },
            )
            return True

        if args.droid_import_provider:
            data = _load_providers()
            profiles = data.get("profiles", {})
            profile = profiles.get(args.droid_import_provider)
            if not profile:
                raise ValueError(f"Saved provider '{args.droid_import_provider}' not found")
            summary = droid.import_codex_provider(
                home,
                args.droid_import_provider,
                profile,
                api_key_env=args.droid_api_key_env,
                with_key=args.droid_with_key,
            )
            print(f"Droid provider imported: {args.droid_import_provider}")
            print(f"  Model ID: {summary['model_id']}")
            print(f"  Path: {summary['path']}")
            record_history(
                "droid_provider_imported",
                provider=args.droid_import_provider,
                details={
                    "model_id": summary["model_id"],
                    "added": summary["added"],
                    "updated": summary["updated"],
                    "path": str(summary["path"]),
                },
            )
            return True

        if args.droid_use:
            summary = droid.use_model(home, args.droid_use, reasoning=args.set_reasoning)
            print(f"Droid active model set to: {summary['model_id']}")
            print(f"  Path: {summary['path']}")
            record_history(
                "droid_model_selected",
                details={
                    "model_id": summary["model_id"],
                    "reasoning": summary.get("reasoning", ""),
                    "path": str(summary["path"]),
                },
            )
            return True

        if args.droid_remove_model:
            summary = droid.remove_model(home, args.droid_remove_model)
            print(f"Droid model removed: {summary['model_id']}")
            print(f"  Path: {summary['path']}")
            record_history(
                "droid_model_removed",
                details={
                    "model_id": summary["model_id"],
                    "path": str(summary["path"]),
                },
            )
            return True
    except ValueError as e:
        print(f"ERROR: {e}")
        return True

    return False


def _args_have_chat_bridge_command(args):
    return any([
        getattr(args, "droid_sessions", False),
        getattr(args, "codex_sessions", False),
        getattr(args, "droid_to_codex", False),
        getattr(args, "codex_to_droid", False),
    ])


def _chat_session_ids(args):
    ids = _parse_csv_list(getattr(args, "chat_session", None))
    return ids


def _display_session_text(value, limit=80):
    text = " ".join(str(value or "-").split())
    if len(text) > limit:
        return text[: max(0, limit - 3)] + "..."
    return text


def _print_codex_chat_sessions(rows):
    print("\n=== Codex Sessions ===")
    if not rows:
        print("No sessions found.")
        return
    limit = 30
    for row in rows[:limit]:
        updated = row.get("updated_at_ms") or (row.get("updated_at") or 0) * 1000
        updated_text = "-"
        if updated:
            updated_text = datetime.datetime.fromtimestamp(updated / 1000).strftime("%Y-%m-%d %H:%M")
        print(f"  {row.get('id', '')} | {_display_session_text(row.get('title'))} | {row.get('model_provider') or '-'} | {updated_text}")
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more (use --project to filter)")


def _print_droid_chat_sessions(sessions, factory_home):
    print("\n=== Droid Sessions ===")
    print(f"Factory home: {factory_home}")
    if not sessions:
        print("No sessions found.")
        return
    for session in sessions:
        updated = session.get("mtime")
        updated_text = "-"
        if updated:
            if updated > 100000000000:
                updated = updated / 1000
            updated_text = datetime.datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M")
        print(f"  {session.get('id', '')} | {_display_session_text(session.get('title'))} | messages={session.get('message_count', 0)} | {updated_text}")


def handle_chat_bridge_command(args):
    if not _args_have_chat_bridge_command(args):
        return False

    try:
        import chat_bridge

        factory_home = _droid_home_from_args(args)

        if args.droid_sessions:
            _print_droid_chat_sessions(chat_bridge.list_droid_sessions(factory_home), factory_home)
            return True

        if args.codex_sessions:
            _print_codex_chat_sessions(_fetch_session_rows(project=args.project))
            return True

        ids = _chat_session_ids(args)
        if not ids:
            print("ERROR: --chat-session is required for chat transfer commands.")
            return True
        preserve_timestamps = not bool(args.chat_fresh_timestamps)

        if args.droid_to_codex:
            pending = []
            old_before_ms = None
            if args.chat_pin_old:
                old_before = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.chat_old_days)
                old_before_ms = int(old_before.timestamp() * 1000)
            for session_id in ids:
                jsonl_path = factory_home / "sessions" / f"{session_id}.jsonl"
                settings_path = factory_home / "sessions" / f"{session_id}.settings.json"
                if not jsonl_path.exists():
                    print(f"  {session_id}: Droid session JSONL not found")
                    continue
                pending.append((session_id, chat_bridge.droid_session_to_bridge(jsonl_path, settings_path)))
            if not pending:
                print("No valid Droid sessions to import.")
                return True
            backup_path = full_backup()
            imported = []
            for session_id, bridge in pending:
                summary = chat_bridge.import_bridge_to_codex(
                    bridge,
                    codex_dir=CODEX_DIR,
                    state_db=STATE_DB,
                    sessions_dir=SESSIONS_DIR,
                    global_state_path=GLOBAL_STATE,
                    preserve_timestamps=preserve_timestamps,
                    pin_old=args.chat_pin_old,
                    old_before_ms=old_before_ms,
                )
                imported.append(summary)
                print(f"  {session_id} -> {summary['codex_session_id']} | pinned={summary['pinned']}")
            record_history(
                "chat_bridge_droid_to_codex",
                backup_path=str(backup_path),
                details={"sessions": len(imported), "preserve_timestamps": preserve_timestamps},
            )
            return True

        if args.codex_to_droid:
            rows = _fetch_session_rows(session_ids=ids)
            row_map = {row.get("id"): row for row in rows}
            imported = []
            for session_id in ids:
                row = row_map.get(session_id)
                if not row:
                    print(f"  {session_id}: Codex session not found")
                    continue
                rollout_path = _normalize_rollout_path(row.get("rollout_path"))
                if not rollout_path or not os.path.exists(rollout_path):
                    print(f"  {session_id}: rollout not found")
                    continue
                bridge = chat_bridge.codex_session_to_bridge(row, rollout_path)
                summary = chat_bridge.import_bridge_to_droid(
                    bridge,
                    factory_home=factory_home,
                    preserve_timestamps=preserve_timestamps,
                )
                imported.append(summary)
                print(f"  {session_id} -> {summary['droid_session_id']}")
            record_history(
                "chat_bridge_codex_to_droid",
                details={"sessions": len(imported), "preserve_timestamps": preserve_timestamps, "factory_home": str(factory_home)},
            )
            return True
    except ValueError as e:
        print(f"ERROR: {e}")
        return True

    return False


def build_parser():
    parser = argparse.ArgumentParser(
        description="Transform Codex chats between model_provider types"
    )
    parser.add_argument("--list", action="store_true", help="List thread breakdown by provider")
    parser.add_argument("--from", dest="from_provider", help="Source model_provider (e.g., openai, MyProvider)")
    parser.add_argument("--to", dest="to_provider", help="Target model_provider")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying anything")
    parser.add_argument("--skip-pinned", action="store_true", help="Skip pinned threads during transformation")
    parser.add_argument("--thread", help="Transform only a specific thread ID")
    parser.add_argument("--restore", metavar="BACKUP_DIR", help="Restore DB from a backup directory")
    parser.add_argument("--pin-top", type=int, metavar="N", help="Pin top N most recent threads")
    parser.add_argument("--project", help="Filter by project directory (used with --pin-top and --from/--to)")
    parser.add_argument("--unpin-all", action="store_true", help="Clear all pinned threads")
    parser.add_argument("--pin-list", action="store_true", help="Show currently pinned threads")
    parser.add_argument("--backup", action="store_true", help="Create full ZIP backup of .codex")
    parser.add_argument("--restore-zip", metavar="ZIP_FILE", help="Restore from ZIP backup")
    parser.add_argument("--fix-dates", action="store_true", help="Set file mtimes to last message timestamp")
    parser.add_argument("--providers", nargs="?", const=PROVIDERS_LIST_SENTINEL, metavar="NAME1,NAME2",
                        help="List saved provider profiles, or filter pack commands by provider name")
    parser.add_argument("--sessions", metavar="ID1,ID2", help="Filter pack commands by session ID")
    parser.add_argument("--scope", choices=["providers", "sessions", "all"], default="all",
                        help="Scope for pack import/export")
    parser.add_argument("--without-keys", action="store_true", help="Strip provider auth when exporting a pack")
    parser.add_argument("--export-pack", metavar="ZIP_FILE", help="Export providers/sessions into a Codex Pack ZIP")
    parser.add_argument("--import-pack", metavar="ZIP_FILE", help="Import providers/sessions from a Codex Pack ZIP")
    parser.add_argument("--search", metavar="QUERY", help="Search sessions by metadata, with JSONL fallback")
    parser.add_argument("--history", action="store_true", help="Show recent operation history")
    parser.add_argument("--history-limit", type=int, default=20, metavar="N", help="Number of history entries to show")
    parser.add_argument("--save-provider", metavar="NAME", help="Save current config/auth as a provider profile")
    parser.add_argument("--use-provider", metavar="NAME", help="Switch to a saved provider profile")
    parser.add_argument("--detect-provider", action="store_true", help="Scan for unsaved provider configs")
    parser.add_argument("--remove-provider", metavar="NAME", help="Remove a saved provider profile")
    parser.add_argument("--add-provider", metavar="FILE", help="Add provider from JSON file (use - for stdin)")
    parser.add_argument("--api-key", metavar="KEY", help="API key for --add-provider (prompts if omitted)")
    parser.add_argument("--doctor", action="store_true", help="Read-only health check of Codex state")
    parser.add_argument("--from-model", metavar="MODEL", help="Source model name for model mapping")
    parser.add_argument("--to-model", metavar="MODEL", help="Target model name for model mapping")
    parser.add_argument("--edit-provider", metavar="NAME", help="Edit a saved provider profile")
    parser.add_argument("--set-model", metavar="MODEL", help="Set model (with --edit-provider or standalone)")
    parser.add_argument("--set-url", metavar="URL", help="Set base_url for --edit-provider")
    parser.add_argument("--set-key", metavar="KEY", help="Set API key for --edit-provider")
    parser.add_argument("--set-wire-api", metavar="API", help="Set wire_api for --edit-provider")
    parser.add_argument("--set-reasoning", metavar="LEVEL", help="Set reasoning effort (low/medium/high/xhigh) for --edit-provider")
    parser.add_argument("--set-name", metavar="NAME", help="Rename provider (with --edit-provider)")
    parser.add_argument("--droid-models", action="store_true", help="List Droid Factory models without printing secrets")
    parser.add_argument("--droid-doctor", action="store_true", help="Read-only health check of Droid Factory models")
    parser.add_argument("--droid-add-neurogate", action="store_true", help="Add or update managed NeuroGate models in Droid Factory")
    parser.add_argument("--droid-import-provider", metavar="NAME", help="Import a saved Codex provider into Droid Factory")
    parser.add_argument("--droid-use", metavar="MODEL_ID", help="Set the active Droid Factory model")
    parser.add_argument("--droid-remove-model", metavar="MODEL_ID", help="Remove a managed model from Droid Factory local settings")
    parser.add_argument("--droid-settings", metavar="PATH", help="Path to Droid Factory settings.json")
    parser.add_argument("--droid-with-key", action="store_true", help="Copy the resolved key into Droid Factory settings when supported")
    parser.add_argument("--droid-api-key-env", metavar="VAR", help="Environment variable name to reference for Droid API keys")
    parser.add_argument("--droid-sessions", action="store_true", help="List Droid Factory chat sessions without printing bodies")
    parser.add_argument("--codex-sessions", action="store_true", help="List Codex chat sessions without printing bodies")
    parser.add_argument("--droid-to-codex", action="store_true", help="Import selected Droid chat session(s) into Codex")
    parser.add_argument("--codex-to-droid", action="store_true", help="Import selected Codex chat session(s) into Droid Factory")
    parser.add_argument("--chat-session", metavar="ID1,ID2", help="Chat session ID(s) for bridge transfer")
    parser.add_argument("--chat-preserve-timestamps", action="store_true", help="Preserve source created/updated timestamps during chat transfer")
    parser.add_argument("--chat-fresh-timestamps", action="store_true", help="Use fresh timestamps during chat transfer")
    parser.add_argument("--chat-pin-old", action="store_true", help="Pin old Droid chats when importing them into Codex")
    parser.add_argument("--chat-old-days", type=int, default=180, metavar="N", help="Age threshold for --chat-pin-old")

    # Sync arguments
    parser.add_argument("--sync-host", action="store_true", help="Start P2P sync server + Dashboard")
    parser.add_argument("--sync-port", type=int, default=None, metavar="PORT", help="Port for sync server (default: auto)")
    parser.add_argument("--sync-pull", metavar="HOST[:PORT]", help="Connect to sync host and pull data")
    parser.add_argument("--sync-push", metavar="HOST[:PORT]", help="Connect to sync host and push data")
    parser.add_argument("--sync-pin", metavar="PIN", help="PIN for sync authentication (prompts if omitted)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if handle_droid_command(args):
        return
    if handle_chat_bridge_command(args):
        return
    provider_filter = None
    session_filter = None
    if args.providers not in (None, PROVIDERS_LIST_SENTINEL):
        provider_filter = _parse_csv_list(args.providers)
        if not provider_filter:
            print("ERROR: --providers requires at least one provider name.")
            return
    if args.sessions is not None:
        session_filter = _parse_csv_list(args.sessions)
        if not session_filter:
            print("ERROR: --sessions requires at least one session ID.")
            return
    if args.without_keys and not args.export_pack:
        print("ERROR: --without-keys is only valid with --export-pack.")
        return
    if args.providers == PROVIDERS_LIST_SENTINEL and (args.export_pack or args.import_pack):
        print("ERROR: --providers requires a comma-separated value with pack commands.")
        return
    if provider_filter and not (args.export_pack or args.import_pack):
        print("ERROR: --providers NAME1,NAME2 is only valid with --export-pack or --import-pack.")
        return
    if session_filter and not (args.export_pack or args.import_pack):
        print("ERROR: --sessions is only valid with --export-pack or --import-pack.")
        return

    if args.restore:
        restore_backup(args.restore)
        return

    if args.restore_zip:
        restore_from_zip(args.restore_zip)
        return

    if args.backup:
        full_backup()
        return

    if args.fix_dates:
        fix_dates()
        return

    if args.export_pack:
        try:
            summary = export_pack(
                args.export_pack,
                scope=args.scope,
                provider_names=provider_filter,
                session_ids=session_filter,
                without_keys=args.without_keys,
            )
        except ValueError as e:
            print(f"ERROR: {e}")
            return
        print_pack_summary("Exported", summary)
        return

    if args.import_pack:
        try:
            summary = import_pack(
                args.import_pack,
                scope=args.scope,
                provider_names=provider_filter,
                session_ids=session_filter,
            )
        except ValueError as e:
            print(f"ERROR: {e}")
            return
        print_pack_summary("Imported", summary)
        return

    if args.search:
        try:
            results = search_sessions(args.search, project=args.project)
        except ValueError as e:
            print(f"ERROR: {e}")
            return
        print_search_results(results)
        return

    if args.history:
        print_history(args.history_limit)
        return

    if args.providers == PROVIDERS_LIST_SENTINEL:
        providers_list()
        return

    if args.save_provider:
        save_provider(args.save_provider)
        return

    if args.use_provider:
        use_provider(args.use_provider)
        return

    if args.detect_provider:
        detect_provider()
        return

    if args.remove_provider:
        remove_provider(args.remove_provider)
        return

    if args.add_provider:
        add_provider(args.add_provider, args.api_key)
        return

    if args.edit_provider:
        edit_provider(args.edit_provider, args.set_model, args.set_url,
                      args.set_key, args.set_wire_api, args.set_reasoning,
                      args.set_name)
        return

    if args.set_model and not args.edit_provider:
        set_model(args.set_model)
        return

    if args.doctor:
        doctor()
        return

    if args.sync_host:
        from codex_sync import start_server, get_local_ip, stop_server
        server, pin, port = start_server(port=args.sync_port)
        ip = get_local_ip()
        print(f"\n=== Codex Sync Server ===")
        print(f"  Address: http://{ip}:{port}")
        print(f"  Dashboard: http://{ip}:{port}/dashboard")
        print(f"  PIN: {pin}")
        print(f"\nPress Ctrl+C to stop.\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping sync server...")
            stop_server(server)
        return

    if args.sync_pull or args.sync_push:
        from codex_sync import (
            _client_get_json, _client_post_json, _providers_summary, _provider_full,
            _get_sessions_list, _get_session_jsonl,
        )
        import base64
        try:
            peer = parse_sync_peer(args.sync_pull or args.sync_push)
        except ValueError as e:
            print(f"ERROR: {e}")
            return
        host = peer["host"]
        port = peer["port"]
        scheme = peer["scheme"]
        pin = args.sync_pin or input("Enter PIN: ").strip().upper()
        mode = "pull" if args.sync_pull else "push"
        base_url = f"{scheme}://{host}:{port}"
        print(f"\n=== Codex Sync ({mode}) ===")
        print(f"  Target: {scheme}://{host}:{port}")
        try:
            manifest = _client_get_json(f"{base_url}/api/manifest", pin)
            print(f"  Connected! {manifest['session_count']} sessions, {manifest['provider_count']} providers\n")
        except Exception as e:
            print(f"  Connection failed: {e}")
            return
        print("  [1] Pull providers")
        print("  [2] Pull sessions")
        print("  [3] Push providers")
        print("  [4] Push sessions")
        print("  [0] Exit")
        choice = input("\n  Choose: ").strip()
        if choice == "1":
            data = _client_get_json(f"{base_url}/api/providers", pin)
            for p in data.get("providers", []):
                print(f"  {p['name']}: {p['model']} ({p['auth_mode']}, key={'yes' if p['has_key'] else 'no'})")
        elif choice == "2":
            data = _client_get_json(f"{base_url}/api/sessions", pin)
            for s in data.get("sessions", [])[:20]:
                updated = datetime.datetime.fromtimestamp(s["updated_at_ms"] / 1000).strftime("%Y-%m-%d %H:%M") if s.get("updated_at_ms") else "?"
                print(f"  {s['id'][:12]}... | {s['title'][:40]} | {s['model_provider']} | {updated}")
        elif choice == "3":
            providers, _ = _providers_summary()
            names = [p["name"] for p in providers]
            if not names:
                print("  No local providers to push.")
            else:
                for n in names:
                    print(f"  {n}")
                sel = input("  Push which (comma-separated)? ").strip()
                if sel:
                    for name in [n.strip() for n in sel.split(",") if n.strip()]:
                        prof = _provider_full(name)
                        if not prof:
                            print(f"  {name}: not found")
                            continue
                        result = _client_post_json(f"{base_url}/api/upload/provider", pin, prof)
                        print(f"  {name}: {result}")
        elif choice == "4":
            sessions = _get_sessions_list()
            if not sessions:
                print("  No local sessions to push.")
            else:
                for s in sessions[:20]:
                    updated = datetime.datetime.fromtimestamp(s["updated_at_ms"] / 1000).strftime("%Y-%m-%d %H:%M") if s.get("updated_at_ms") else "?"
                    print(f"  {s['id'][:12]}... | {s['title'][:40]} | {s['model_provider']} | {updated}")
                sel = input("  Push which IDs (comma-separated)? ").strip()
                if sel:
                    session_map = {s["id"]: s for s in sessions}
                    for sid in [s.strip() for s in sel.split(",") if s.strip()]:
                        meta = session_map.get(sid)
                        if not meta:
                            print(f"  {sid}: not found")
                            continue
                        jsonl_data = _get_session_jsonl(sid)
                        if jsonl_data is None:
                            print(f"  {sid}: rollout not found")
                            continue
                        payload = {"meta": meta, "jsonl": base64.b64encode(jsonl_data).decode("ascii")}
                        result = _client_post_json(f"{base_url}/api/upload/session", pin, payload)
                        print(f"  {sid}: {result}")
        return

    conn = get_db_conn()
    if conn is not None:
        try:
            if args.list:
                list_threads(conn)
                return

            if args.pin_list:
                list_pinned(conn)
                return

            if args.unpin_all:
                unpin_all()
                return

            if args.pin_top:
                pin_top_threads(conn, args.pin_top, args.project)
                return

            if not args.from_provider or not args.to_provider:
                print("ERROR: --from and --to are required for transformation.")
                print("Use --list to see available providers.")
                print("\nExample:")
                print("  python codex_chat_transformer.py --list")
                print("  python codex_chat_transformer.py --from openai --to MyProvider --dry-run")
                print("  python codex_chat_transformer.py --from openai --to MyProvider")
                print("  python codex_chat_transformer.py --restore backup_YYYYMMDD_HHMMSS")
                sys.exit(1)

            if args.from_provider == args.to_provider:
                print("ERROR: --from and --to must be different.")
                sys.exit(1)

            print(f"Transforming: {args.from_provider} -> {args.to_provider}"
                  + (f" (project: {args.project})" if args.project else ""))
            transform(conn, args.from_provider, args.to_provider, args.dry_run, args.thread, args.skip_pinned,
                      args.from_model, args.to_model, args.project)
        finally:
            conn.close()


if __name__ == "__main__":
    main()

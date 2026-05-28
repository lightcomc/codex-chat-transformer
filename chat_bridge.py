#!/usr/bin/env python3
"""Chat Bridge helpers for Codex <-> Factory Droid sessions."""

import datetime
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path

BRIDGE_FORMAT = "codex-droid-chat-bridge"
BRIDGE_VERSION = 1
MAPPING_FILE = "chat_bridge_mappings.json"


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt):
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    return _iso(_utc_now())


def _parse_datetime(value):
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 100000000000:
            raw = raw / 1000.0
        return datetime.datetime.fromtimestamp(raw, tz=datetime.timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.astimezone(datetime.timezone.utc)
        except ValueError:
            pass
    return None


def _ms(value, default=None):
    dt = _parse_datetime(value)
    if dt is None:
        if default is None:
            return int(_utc_now().timestamp() * 1000)
        return int(default)
    return int(dt.timestamp() * 1000)


def _dt_from_ms(value):
    return datetime.datetime.fromtimestamp(int(value) / 1000, tz=datetime.timezone.utc)


def _safe_id_piece(value):
    text = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in str(value or "").strip())
    text = "-".join(part for part in text.split("-") if part)
    return text[:80] or "session"


def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4()}"


def _read_jsonl(path):
    events = []
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        for index, raw_line in enumerate(handle):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{index + 1}: {exc}") from exc
            if isinstance(event, dict):
                events.append(event)
    return events


def _read_json_file(path):
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _bridge_id(app, session_id):
    return f"{app}-{_safe_id_piece(session_id)}"


def _unknown_work_context():
    return {
        "primary_cwd": "",
        "current": {
            "cwd": "",
            "git_branch": "",
            "git_sha": "",
            "git_origin_url": "",
            "dirty_state": "unknown",
            "source": "",
            "confidence": "unknown",
        },
        "timeline_complete": False,
        "snapshots": [],
    }


def _first_text(parts):
    for part in parts or []:
        if part.get("type") == "text" and part.get("text"):
            return part.get("text", "")
    return ""


def _message_has_tool_result(parts):
    return parts and all(part.get("type") == "tool_result" for part in parts)


def _droid_part_to_bridge(part):
    if not isinstance(part, dict):
        return {"type": "unknown", "summary": type(part).__name__}
    part_type = part.get("type")
    if part_type == "text":
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "tool_use":
        return {
            "type": "tool_call",
            "id": str(part.get("id") or ""),
            "name": str(part.get("name") or ""),
            "input": part.get("input"),
        }
    if part_type == "tool_result":
        return {
            "type": "tool_result",
            "tool_call_id": str(part.get("tool_use_id") or part.get("id") or ""),
            "content": part.get("content"),
        }
    return {"type": "unknown", "source_type": str(part_type or ""), "keys": sorted(part.keys())}


def droid_session_to_bridge(jsonl_path, settings_path=None):
    jsonl_path = Path(jsonl_path)
    settings = _read_json_file(settings_path)
    events = _read_jsonl(jsonl_path)
    session_start = next((e for e in events if e.get("type") == "session_start"), {})
    session_id = str(session_start.get("id") or jsonl_path.stem)
    title = str(session_start.get("title") or session_id)
    messages = []
    timestamps = []
    raw_event_refs = []

    for event_index, event in enumerate(events):
        event_type = event.get("type")
        raw_event_refs.append(f"{jsonl_path}:{event_index + 1}")
        event_ts = event.get("timestamp")
        if event_ts:
            timestamps.append(_ms(event_ts))

        if event_type == "message":
            msg = event.get("message") if isinstance(event.get("message"), dict) else {}
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            parts = [_droid_part_to_bridge(part) for part in content]
            if not parts:
                parts = [{"type": "unknown", "summary": "empty Droid message content"}]
            role = str(msg.get("role") or "unknown")
            if _message_has_tool_result(parts):
                role = "tool"
            messages.append({
                "id": str(event.get("id") or msg.get("id") or f"droid-message-{event_index}"),
                "parent_id": str(event.get("parentId") or ""),
                "role": role if role in ("user", "assistant", "system", "tool") else "unknown",
                "created_at": _iso(_parse_datetime(event_ts) or _utc_now()),
                "parts": parts,
                "raw_source_ref": f"{jsonl_path}:{event_index + 1}",
            })
        elif event_type == "todo_state":
            messages.append({
                "id": str(event.get("id") or f"droid-todo-{event_index}"),
                "parent_id": "",
                "role": "unknown",
                "created_at": _iso(_parse_datetime(event_ts) or _utc_now()),
                "parts": [{"type": "todo_state", "summary": {"count": len(event.get("todos") or [])}}],
                "raw_source_ref": f"{jsonl_path}:{event_index + 1}",
            })

    created_ms = min(timestamps) if timestamps else int(_utc_now().timestamp() * 1000)
    updated_ms = max(timestamps) if timestamps else created_ms
    model = str(settings.get("providerLock") or "")
    bridge = {
        "format": BRIDGE_FORMAT,
        "version": BRIDGE_VERSION,
        "source": {
            "app": "droid",
            "session_id": session_id,
            "path": str(jsonl_path),
            "exported_at": _iso(_utc_now()),
        },
        "session": {
            "bridge_id": _bridge_id("droid", session_id),
            "title": title,
            "created_at": _iso(_dt_from_ms(created_ms)),
            "updated_at": _iso(_dt_from_ms(updated_ms)),
            "provider": "droid",
            "model": model,
        },
        "work_context": _unknown_work_context(),
        "messages": messages,
        "extras": {
            "droid_settings": {
                "providerLock": model,
                "providerLockTimestamp": settings.get("providerLockTimestamp") or "",
                "tokenUsage": settings.get("tokenUsage") if isinstance(settings.get("tokenUsage"), dict) else {},
            }
        },
        "raw_event_refs": raw_event_refs,
    }
    validate_bridge(bridge)
    return bridge


def _codex_content_part_to_bridge(part):
    if not isinstance(part, dict):
        return {"type": "unknown", "summary": type(part).__name__}
    part_type = part.get("type")
    if part_type in ("input_text", "output_text", "text"):
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "tool_call":
        return {
            "type": "tool_call",
            "id": str(part.get("id") or ""),
            "name": str(part.get("name") or ""),
            "input": part.get("input"),
        }
    if part_type == "tool_result":
        return {
            "type": "tool_result",
            "tool_call_id": str(part.get("tool_call_id") or part.get("tool_use_id") or ""),
            "content": part.get("content"),
        }
    if part_type in ("input_image", "image"):
        return {"type": "image", "summary": "image content"}
    return {"type": "unknown", "source_type": str(part_type or ""), "keys": sorted(part.keys())}


def _git_from_payload(payload):
    git = payload.get("git") if isinstance(payload, dict) else {}
    if not isinstance(git, dict):
        return {}
    return {
        "git_branch": git.get("branch") or git.get("git_branch") or "",
        "git_sha": git.get("sha") or git.get("commit_hash") or git.get("git_sha") or "",
        "git_origin_url": git.get("origin_url") or git.get("repository_url") or git.get("git_origin_url") or "",
    }


def codex_session_to_bridge(row, rollout_path, include_system=True):
    row = dict(row or {})
    rollout_path = Path(str(rollout_path or row.get("rollout_path") or ""))
    events = _read_jsonl(rollout_path)
    session_id = str(row.get("id") or rollout_path.stem.replace("rollout-", ""))
    created_ms = int(row.get("created_at_ms") or (int(row.get("created_at") or 0) * 1000) or int(_utc_now().timestamp() * 1000))
    updated_ms = int(row.get("updated_at_ms") or (int(row.get("updated_at") or 0) * 1000) or created_ms)
    messages = []
    snapshots = []
    raw_event_refs = []

    for event_index, event in enumerate(events):
        raw_event_refs.append(f"{rollout_path}:{event_index + 1}")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        payload_type = payload.get("type") or event.get("type")
        timestamp = event.get("timestamp") or payload.get("timestamp") or _iso(_dt_from_ms(created_ms))

        if event.get("type") == "session_meta":
            git_data = _git_from_payload(payload)
            if any(git_data.values()):
                snapshots.append({
                    "id": f"work-snapshot-{len(snapshots) + 1}",
                    "observed_at": _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                    "event_index": event_index,
                    "message_id": "",
                    "cwd": payload.get("cwd") or row.get("cwd") or "",
                    "git_branch": git_data.get("git_branch", ""),
                    "git_sha": git_data.get("git_sha", ""),
                    "git_origin_url": git_data.get("git_origin_url", ""),
                    "dirty_state": "unknown",
                    "source": "codex_session_meta",
                    "confidence": "observed",
                })
            continue

        if payload_type in ("message", "user_message", "agent_message"):
            role = payload.get("role")
            if not role:
                role = "user" if payload_type == "user_message" else "assistant" if payload_type == "agent_message" else "unknown"
            if role == "system" and not include_system:
                continue
            content = payload.get("content")
            parts = []
            if isinstance(content, list):
                parts = [_codex_content_part_to_bridge(part) for part in content]
            elif payload.get("text"):
                parts = [{"type": "text", "text": str(payload.get("text") or "")}]
            if parts:
                messages.append({
                    "id": str(payload.get("id") or event.get("id") or f"codex-message-{event_index}"),
                    "parent_id": "",
                    "role": role if role in ("user", "assistant", "system", "tool") else "unknown",
                    "created_at": _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                    "work_snapshot_id": snapshots[-1]["id"] if snapshots else "",
                    "parts": parts,
                    "raw_source_ref": f"{rollout_path}:{event_index + 1}",
                })
        elif payload_type in ("function_call", "custom_tool_call"):
            messages.append({
                "id": str(payload.get("call_id") or payload.get("id") or f"codex-tool-{event_index}"),
                "parent_id": "",
                "role": "assistant",
                "created_at": _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                "parts": [{"type": "tool_call", "id": str(payload.get("call_id") or payload.get("id") or ""), "name": str(payload.get("name") or ""), "input": payload.get("arguments") or payload.get("input")}],
                "raw_source_ref": f"{rollout_path}:{event_index + 1}",
            })
        elif payload_type in ("function_call_output", "custom_tool_call_output"):
            messages.append({
                "id": str(payload.get("call_id") or payload.get("id") or f"codex-tool-result-{event_index}"),
                "parent_id": "",
                "role": "tool",
                "created_at": _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                "parts": [{"type": "tool_result", "tool_call_id": str(payload.get("call_id") or payload.get("id") or ""), "content": payload.get("output")}],
                "raw_source_ref": f"{rollout_path}:{event_index + 1}",
            })

    work_context = {
        "primary_cwd": row.get("cwd") or "",
        "current": {
            "cwd": row.get("cwd") or "",
            "git_branch": row.get("git_branch") or "",
            "git_sha": row.get("git_sha") or "",
            "git_origin_url": row.get("git_origin_url") or "",
            "dirty_state": "unknown",
            "source": "codex_threads",
            "confidence": "observed" if (row.get("git_branch") or row.get("git_sha")) else "unknown",
        },
        "timeline_complete": False,
        "snapshots": snapshots,
    }
    bridge = {
        "format": BRIDGE_FORMAT,
        "version": BRIDGE_VERSION,
        "source": {
            "app": "codex",
            "session_id": session_id,
            "path": str(rollout_path),
            "exported_at": _iso(_utc_now()),
        },
        "session": {
            "bridge_id": _bridge_id("codex", session_id),
            "title": row.get("title") or session_id,
            "created_at": _iso(_dt_from_ms(created_ms)),
            "updated_at": _iso(_dt_from_ms(updated_ms)),
            "provider": row.get("model_provider") or "",
            "model": row.get("model") or "",
        },
        "work_context": work_context,
        "messages": messages,
        "extras": {},
        "raw_event_refs": raw_event_refs,
    }
    validate_bridge(bridge)
    return bridge


def validate_bridge(bridge):
    if not isinstance(bridge, dict):
        raise ValueError("bridge must be an object")
    if bridge.get("format") != BRIDGE_FORMAT:
        raise ValueError("unsupported bridge format")
    if int(bridge.get("version") or 0) != BRIDGE_VERSION:
        raise ValueError("unsupported bridge version")
    if not isinstance(bridge.get("source"), dict):
        raise ValueError("bridge source is required")
    if not isinstance(bridge.get("session"), dict):
        raise ValueError("bridge session is required")
    if not bridge["session"].get("bridge_id"):
        raise ValueError("bridge session bridge_id is required")
    messages = bridge.get("messages")
    if not isinstance(messages, list):
        raise ValueError("bridge messages must be a list")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"bridge message {index} must be an object")
        parts = message.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"bridge message {index} must have at least one part")
        for part in parts:
            if not isinstance(part, dict) or not part.get("type"):
                raise ValueError(f"bridge message {index} has invalid part")
    return True


def _rollout_message_part(part):
    part_type = part.get("type")
    if part_type == "text":
        return {"type": "output_text", "text": str(part.get("text") or "")}
    return {"type": "metadata", "text": json.dumps({"part_type": part_type}, ensure_ascii=True)}


def _render_codex_rollout(bridge, codex_id, created_ms, updated_ms, preserve_message_timestamps=True):
    session = bridge["session"]
    work = bridge.get("work_context") if isinstance(bridge.get("work_context"), dict) else {}
    current = work.get("current") if isinstance(work.get("current"), dict) else {}
    created_iso = _iso(_dt_from_ms(created_ms))
    events = [{
        "timestamp": created_iso,
        "type": "session_meta",
        "payload": {
            "id": codex_id,
            "timestamp": created_iso,
            "cwd": work.get("primary_cwd") or current.get("cwd") or "",
            "originator": "chat_bridge",
            "source": "chat_bridge",
            "model_provider": session.get("provider") or "",
            "model": session.get("model") or "",
            "git": {
                "branch": current.get("git_branch") or "",
                "commit_hash": current.get("git_sha") or "",
                "repository_url": current.get("git_origin_url") or "",
            },
        },
    }]
    messages = bridge.get("messages", [])
    for message_index, message in enumerate(messages):
        role = message.get("role") if message.get("role") in ("user", "assistant", "system", "tool") else "unknown"
        if preserve_message_timestamps:
            timestamp = message.get("created_at") or created_iso
        else:
            timestamp_ms = min(updated_ms, created_ms + message_index + 1)
            timestamp = _iso(_dt_from_ms(timestamp_ms))
        message_content = []
        for part in message.get("parts", []):
            part_type = part.get("type")
            if part_type == "tool_call":
                events.append({
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "call_id": part.get("id") or "",
                        "name": part.get("name") or "",
                        "arguments": part.get("input"),
                    },
                })
            elif part_type == "tool_result":
                events.append({
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": part.get("tool_call_id") or "",
                        "output": part.get("content"),
                    },
                })
            else:
                message_content.append(_rollout_message_part(part))
        if message_content:
            events.append({
                "timestamp": timestamp,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": role,
                    "content": message_content,
                },
            })
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _validate_codex_rollout(path, expected_id, expected_messages):
    events = _read_jsonl(path)
    if not events:
        raise ValueError("generated rollout is empty")
    first = events[0]
    if first.get("type") != "session_meta":
        raise ValueError("generated rollout does not start with session_meta")
    payload = first.get("payload") if isinstance(first.get("payload"), dict) else {}
    if payload.get("id") != expected_id:
        raise ValueError("generated rollout session id mismatch")
    message_count = sum(1 for event in events if event.get("type") == "response_item")
    if message_count < expected_messages:
        raise ValueError("generated rollout message count mismatch")
    return first


def _table_columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _insert_thread_row(conn, row):
    columns = _table_columns(conn, "threads")
    insert = {key: value for key, value in row.items() if key in columns}
    names = list(insert.keys())
    placeholders = ", ".join("?" for _ in names)
    sql = f"INSERT INTO threads ({', '.join(names)}) VALUES ({placeholders})"
    conn.execute(sql, [insert[name] for name in names])


def _first_user_text(messages):
    for message in messages or []:
        if message.get("role") == "user":
            text = _first_text(message.get("parts"))
            if text:
                return text
    return ""


def _preview_text(messages):
    for message in reversed(messages or []):
        text = _first_text(message.get("parts"))
        if text:
            return text[:500]
    return ""


def _load_mapping(root):
    path = Path(root) / MAPPING_FILE
    if not path.exists():
        return {"version": 1, "pairs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "pairs": []}
    if not isinstance(data, dict):
        return {"version": 1, "pairs": []}
    data.setdefault("version", 1)
    if not isinstance(data.get("pairs"), list):
        data["pairs"] = []
    return data


def _save_mapping(root, data):
    path = Path(root) / MAPPING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{MAPPING_FILE}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        Path(tmp_name).replace(path)
    finally:
        tmp_path = Path(tmp_name)
        if tmp_path.exists():
            tmp_path.unlink()
    return path


def list_droid_sessions(factory_home):
    factory_home = Path(factory_home)
    sessions_dir = factory_home / "sessions"
    index_path = factory_home / "sessions-index.json"
    indexed = {}
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            for entry in data.get("entries") or []:
                if isinstance(entry, dict) and entry.get("sessionId"):
                    indexed[str(entry["sessionId"])] = entry
        except Exception:
            indexed = {}
    sessions = []
    if not sessions_dir.exists():
        return sessions
    for jsonl_path in sorted(sessions_dir.glob("*.jsonl")):
        session_id = jsonl_path.stem
        title = session_id
        message_count = 0
        try:
            with jsonl_path.open("r", encoding="utf-8") as handle:
                for line_index, raw_line in enumerate(handle):
                    if not raw_line.strip():
                        continue
                    event = json.loads(raw_line)
                    if line_index == 0 and event.get("type") == "session_start":
                        title = event.get("title") or title
                        session_id = event.get("id") or session_id
                    if event.get("type") == "message":
                        message_count += 1
        except Exception:
            pass
        idx = indexed.get(session_id, {})
        sessions.append({
            "id": session_id,
            "title": idx.get("title") or title,
            "message_count": idx.get("messagesCount") if idx.get("messagesCount") is not None else message_count,
            "mtime": idx.get("mtime") or jsonl_path.stat().st_mtime,
            "jsonl_path": str(jsonl_path),
            "settings_path": str(sessions_dir / f"{session_id}.settings.json"),
        })
    sessions.sort(key=lambda item: item.get("mtime") or 0, reverse=True)
    return sessions


def _upsert_mapping(root, pair):
    data = _load_mapping(root)
    pairs = list(data.get("pairs", []))
    pair = dict(pair)
    pair.setdefault("import_id", str(uuid.uuid4()))
    pairs.append(pair)
    data["pairs"] = pairs
    return _save_mapping(root, data)


def _pin_session(global_state_path, session_id):
    path = Path(global_state_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    pinned = data.get("pinned-thread-ids")
    if not isinstance(pinned, list):
        pinned = []
    if session_id not in pinned:
        pinned.append(session_id)
    data["pinned-thread-ids"] = pinned
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def import_bridge_to_codex(
    bridge,
    codex_dir,
    state_db,
    sessions_dir,
    global_state_path,
    preserve_timestamps=True,
    pin_old=False,
    old_before_ms=None,
):
    validate_bridge(bridge)
    codex_dir = Path(codex_dir)
    state_db = Path(state_db)
    sessions_dir = Path(sessions_dir)
    source = bridge["source"]
    session = bridge["session"]
    work = bridge.get("work_context") if isinstance(bridge.get("work_context"), dict) else {}
    current = work.get("current") if isinstance(work.get("current"), dict) else {}
    now_ms = int(_utc_now().timestamp() * 1000)
    source_created_ms = _ms(session.get("created_at"), default=now_ms)
    source_updated_ms = _ms(session.get("updated_at"), default=source_created_ms)
    if preserve_timestamps:
        created_ms = source_created_ms
        updated_ms = source_updated_ms
    else:
        created_ms = now_ms
        updated_ms = created_ms + max(len(bridge.get("messages", [])), 0)

    codex_id = _new_id("bridge-codex")
    date_dir = sessions_dir / f"{_dt_from_ms(created_ms).year:04d}" / f"{_dt_from_ms(created_ms).month:02d}" / f"{_dt_from_ms(created_ms).day:02d}"
    date_dir.mkdir(parents=True, exist_ok=True)
    final_path = date_dir / f"rollout-{codex_id}.jsonl"
    fd, tmp_name = tempfile.mkstemp(prefix=f"rollout-{codex_id}.", suffix=".tmp", dir=str(date_dir))
    tmp_path = Path(tmp_name)
    conn = None
    committed = False
    try:
        rollout_text = _render_codex_rollout(
            bridge,
            codex_id,
            created_ms,
            updated_ms,
            preserve_message_timestamps=preserve_timestamps,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rollout_text)
        fd = None
        _validate_codex_rollout(tmp_path, codex_id, len(bridge.get("messages", [])))
        tmp_path.replace(final_path)
        row = {
            "id": codex_id,
            "rollout_path": str(final_path),
            "created_at": created_ms // 1000,
            "updated_at": updated_ms // 1000,
            "source": "chat_bridge",
            "model_provider": session.get("provider") or "",
            "cwd": work.get("primary_cwd") or current.get("cwd") or "",
            "title": session.get("title") or codex_id,
            "sandbox_policy": "{}",
            "approval_mode": "never",
            "tokens_used": 0,
            "has_user_event": 1 if any(m.get("role") == "user" for m in bridge.get("messages", [])) else 0,
            "archived": 0,
            "archived_at": None,
            "git_sha": current.get("git_sha") or "",
            "git_branch": current.get("git_branch") or "",
            "git_origin_url": current.get("git_origin_url") or "",
            "cli_version": "",
            "first_user_message": _first_user_text(bridge.get("messages")),
            "agent_nickname": None,
            "agent_role": None,
            "memory_mode": "enabled",
            "model": session.get("model") or "",
            "reasoning_effort": None,
            "agent_path": None,
            "created_at_ms": created_ms,
            "updated_at_ms": updated_ms,
            "thread_source": "chat_bridge",
            "preview": _preview_text(bridge.get("messages")),
        }
        conn = sqlite3.connect(str(state_db), timeout=30.0)
        conn.execute("BEGIN")
        _insert_thread_row(conn, row)
        db_row = conn.execute("SELECT id, rollout_path, model_provider, model, created_at_ms, updated_at_ms FROM threads WHERE id = ?", (codex_id,)).fetchone()
        if not db_row:
            raise ValueError("Codex import sanity check failed: missing DB row")
        conn.commit()
        committed = True
        conn.close()
        conn = None

        verify_conn = sqlite3.connect(str(state_db), timeout=30.0)
        verify_conn.row_factory = sqlite3.Row
        try:
            verified = verify_conn.execute("SELECT * FROM threads WHERE id = ?", (codex_id,)).fetchone()
        finally:
            verify_conn.close()
        if verified is None:
            raise ValueError("Codex import verification failed: missing DB row after commit")
        if str(verified["rollout_path"]) != str(final_path):
            raise ValueError("Codex import verification failed: rollout path mismatch")
        meta = _validate_codex_rollout(final_path, codex_id, len(bridge.get("messages", [])))
        payload = meta.get("payload") or {}
        if payload.get("model_provider") != verified["model_provider"] or payload.get("model") != verified["model"]:
            raise ValueError("Codex import verification failed: provider/model mismatch")

        warnings = []
        should_pin = bool(pin_old) and (old_before_ms is None or source_updated_ms < int(old_before_ms))
        if should_pin:
            try:
                _pin_session(global_state_path, codex_id)
            except Exception as exc:
                should_pin = False
                warnings.append(f"pin: {exc}")
        try:
            mapping_path = _upsert_mapping(codex_dir, {
                "bridge_id": session.get("bridge_id"),
                "source_app": source.get("app") or "",
                "codex_session_id": codex_id,
                "droid_session_id": source.get("session_id") if source.get("app") == "droid" else "",
                "created_at": _iso(_utc_now()),
            })
        except Exception as exc:
            mapping_path = ""
            warnings.append(f"mapping: {exc}")
        return {
            "codex_session_id": codex_id,
            "rollout_path": str(final_path),
            "mapping_path": str(mapping_path),
            "pinned": should_pin,
            "warnings": warnings,
        }
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if conn is not None:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        cleanup_paths = (tmp_path,) if committed else (tmp_path, final_path)
        for path in cleanup_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        raise


def _droid_content_part(part):
    part_type = part.get("type")
    if part_type == "text":
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "tool_call":
        return {"type": "tool_use", "id": part.get("id") or "", "name": part.get("name") or "", "input": part.get("input")}
    if part_type == "tool_result":
        return {"type": "tool_result", "tool_use_id": part.get("tool_call_id") or "", "content": part.get("content")}
    return {"type": "text", "text": f"[unsupported bridge part: {part_type}]"}


def _update_droid_index(factory_home, session_id, title, jsonl_path, settings_path, message_count):
    index_path = Path(factory_home) / "sessions-index.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except Exception:
        data = {}
    data["version"] = int(data.get("version") or 1)
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    entries = [entry for entry in entries if entry.get("sessionId") != session_id]
    entries.append({
        "sessionId": session_id,
        "mtime": jsonl_path.stat().st_mtime,
        "settingsMtime": settings_path.stat().st_mtime,
        "title": title,
        "messagesCount": message_count,
    })
    data["entries"] = entries
    if index_path.exists():
        backup_path = index_path.with_name(f"{index_path.name}.{int(_utc_now().timestamp())}.bak")
        try:
            shutil.copy2(index_path, backup_path)
        except OSError:
            pass
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def import_bridge_to_droid(bridge, factory_home, preserve_timestamps=True):
    validate_bridge(bridge)
    factory_home = Path(factory_home)
    sessions_dir = factory_home / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    source = bridge["source"]
    session = bridge["session"]
    droid_id = _new_id("bridge-droid")
    jsonl_path = sessions_dir / f"{droid_id}.jsonl"
    settings_path = sessions_dir / f"{droid_id}.settings.json"
    jsonl_tmp = None
    settings_tmp = None
    now = _utc_now()
    try:
        events = [{"type": "session_start", "id": droid_id, "title": session.get("title") or droid_id, "owner": "codex-provider-manager"}]

        for index, message in enumerate(bridge.get("messages", [])):
            role = message.get("role") if message.get("role") in ("user", "assistant") else "user"
            if preserve_timestamps:
                timestamp = message.get("created_at") or session.get("created_at") or _iso(now)
            else:
                timestamp = _iso(now + datetime.timedelta(milliseconds=index))
            events.append({
                "type": "message",
                "id": message.get("id") or f"message-{index}",
                "timestamp": timestamp,
                "message": {
                    "role": role,
                    "content": [_droid_content_part(part) for part in message.get("parts", [])],
                },
            })

        jsonl_fd, jsonl_tmp_name = tempfile.mkstemp(prefix=f"{droid_id}.", suffix=".jsonl.tmp", dir=str(sessions_dir))
        jsonl_tmp = Path(jsonl_tmp_name)
        with os.fdopen(jsonl_fd, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
        settings = {
            "assistantActiveTimeMs": 0,
            "providerLock": session.get("model") or "",
            "providerLockTimestamp": session.get("updated_at") or _iso(now),
            "tokenUsage": {},
        }
        settings_fd, settings_tmp_name = tempfile.mkstemp(prefix=f"{droid_id}.", suffix=".settings.json.tmp", dir=str(sessions_dir))
        settings_tmp = Path(settings_tmp_name)
        with os.fdopen(settings_fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(settings, indent=2, ensure_ascii=True) + "\n")
        jsonl_tmp.replace(jsonl_path)
        settings_tmp.replace(settings_path)
        _update_droid_index(factory_home, droid_id, session.get("title") or droid_id, jsonl_path, settings_path, len(bridge.get("messages", [])))
        warnings = []
        try:
            mapping_path = _upsert_mapping(factory_home, {
                "bridge_id": session.get("bridge_id"),
                "source_app": source.get("app") or "",
                "codex_session_id": source.get("session_id") if source.get("app") == "codex" else "",
                "droid_session_id": droid_id,
                "created_at": _iso(_utc_now()),
            })
        except Exception as exc:
            mapping_path = ""
            warnings.append(f"mapping: {exc}")
        return {
            "droid_session_id": droid_id,
            "droid_jsonl_path": str(jsonl_path),
            "droid_settings_path": str(settings_path),
            "mapping_path": str(mapping_path),
            "warnings": warnings,
        }
    except Exception:
        for path in (jsonl_tmp, settings_tmp, jsonl_path, settings_path):
            try:
                if path is not None and Path(path).exists():
                    Path(path).unlink()
            except OSError:
                pass
        raise

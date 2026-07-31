#!/usr/bin/env python3
"""Chat Bridge helpers for Codex <-> Factory Droid sessions."""

import datetime
import base64
import binascii
import gzip
import json
import os
import random
import re
import shutil
import sqlite3
import string
import tempfile
import uuid
from pathlib import Path

BRIDGE_FORMAT = "codex-droid-chat-bridge"
BRIDGE_VERSION = 1
MAPPING_FILE = "chat_bridge_mappings.json"
CHAT_COMPACTION_MODES = ("inline", "native", "archived", "raw")
DROID_SOURCE_ARCHIVE_FORMAT = "codex-droid-source-events"
DROID_SOURCE_ARCHIVE_VERSION = 1
DROID_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
DROID_NATIVE_EVENT_TYPES = frozenset({"session_start", "message", "compaction_state", "todo_state", "session_end"})

# Codex Desktop identity constants for Droid -> Codex conversion
CODEX_DESKTOP_CLI_VERSION = "0.133.0-alpha.1"
CODEX_DESKTOP_ORIGINATOR = "Codex Desktop"
CODEX_DESKTOP_SOURCE = "vscode"
CODEX_DESKTOP_THREAD_SOURCE = "user"
CODEX_DESKTOP_TIMEZONE = "Europe/Moscow"
CODEX_DESKTOP_PERSONALITY = "pragmatic"
CODEX_DESKTOP_MODEL_CONTEXT_WINDOW = 200000

CODEX_DESKTOP_META_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex_desktop_meta_template.json")

CODEX_DESKTOP_PERMISSIONS_BLOCK = (
    "<permissions instructions>\n"
    "Filesystem sandboxing is disabled. All filesystem commands are allowed.\n"
    "Approval policy: never.\n"
    "</permissions instructions>"
)

CODEX_DESKTOP_APP_CONTEXT_BLOCK = (
    "<app-context>\n"
    "# Codex desktop context\n"
    "Source: vscode\n"
    f"CLI version: {CODEX_DESKTOP_CLI_VERSION}\n"
    "</app-context>"
)

CODEX_DESKTOP_COLLABORATION_BLOCK = (
    "<collaboration_mode>\n"
    "# Collaboration Mode: Default\n"
    "You are collaborating with the user in default mode.\n"
    "</collaboration_mode>"
)

CODEX_DESKTOP_SKILLS_BLOCK = (
    "<skills_instructions>\n"
    "No custom skills configured.\n"
    "</skills_instructions>"
)

CODEX_DESKTOP_PLUGINS_BLOCK = (
    "<plugins_instructions>\n"
    "No plugins configured.\n"
    "</plugins_instructions>"
)

_EXEC_COMMAND_TOOL_NAMES = frozenset({
    "LS", "Glob", "Grep", "Read", "Write", "Edit", "Execute",
    "TodoWrite", "TodoRead", "Task", "WebSearch", "WebFetch",
    "EnterWorktree", "ExitWorktree", "NotebookEdit",
})


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


def _new_codex_thread_id():
    value = uuid.uuid4().int
    timestamp_ms = int(_utc_now().timestamp() * 1000) & ((1 << 48) - 1)
    rand_a = (value >> 64) & 0x0FFF
    rand_b = value & ((1 << 62) - 1)
    generated = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0x2 << 62)
        | rand_b
    )
    return str(uuid.UUID(int=generated))


def _desktop_call_id():
    chars = string.ascii_letters + string.digits
    suffix = "".join(random.choices(chars, k=22))
    return f"call_{suffix}"


def _desktop_chunk_id():
    return "".join(random.choices("0123456789abcdef", k=6))


def _desktop_env_context_text(cwd, date_iso):
    return (
        "<environment_context>\n"
        f"  <cwd>{cwd}</cwd>\n"
        "  <shell>powershell</shell>\n"
        f"  <current_date>{date_iso[:10]}</current_date>\n"
        f"  <timezone>{CODEX_DESKTOP_TIMEZONE}</timezone>\n"
        "</environment_context>"
    )


def _desktop_load_meta_template():
    path = CODEX_DESKTOP_META_TEMPLATE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "base_instructions": {"text": "You are Codex, a coding agent. Be concise and helpful."},
        "dynamic_tools": [],
    }


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


def _droid_source_archive_path(jsonl_path):
    jsonl_path = Path(jsonl_path)
    return jsonl_path.with_name(f"{jsonl_path.stem}.bridge-source-events.json.gz")


def _read_droid_source_archive(jsonl_path):
    archive_path = _droid_source_archive_path(jsonl_path)
    if not archive_path.exists():
        return []
    try:
        with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise ValueError(f"invalid Droid source archive at {archive_path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != DROID_SOURCE_ARCHIVE_FORMAT:
        raise ValueError(f"invalid Droid source archive format at {archive_path}")
    if _int_or_default(payload.get("version"), 0) != DROID_SOURCE_ARCHIVE_VERSION:
        raise ValueError(f"unsupported Droid source archive version at {archive_path}")
    expected_session_id = Path(jsonl_path).stem
    archive_session_id = str(payload.get("droid_session_id") or "")
    if archive_session_id and archive_session_id != expected_session_id:
        raise ValueError(f"Droid source archive session mismatch at {archive_path}")
    events = payload.get("events")
    if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
        raise ValueError(f"invalid Droid source archive events at {archive_path}")
    source_app = str(payload.get("source_app") or "")
    restored = json.loads(json.dumps(events))
    if source_app:
        for event in restored:
            if not _bridge_source_app(event):
                event["source_app"] = source_app
    return restored


def _bridge_id(app, session_id):
    return f"{app}-{_safe_id_piece(session_id)}"


def _bridge_extras(bridge):
    extras = bridge.get("extras") if isinstance(bridge, dict) and isinstance(bridge.get("extras"), dict) else {}
    return extras


def _bridge_droid_session_start(bridge):
    extras = _bridge_extras(bridge)
    data = extras.get("droid_session_start")
    return data if isinstance(data, dict) else {}


def _bridge_droid_settings(bridge):
    extras = _bridge_extras(bridge)
    data = extras.get("droid_settings")
    return data if isinstance(data, dict) else {}


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


_CODEX_INTERNAL_TEXT_PREFIXES = (
    "<permissions instructions>",
    "<app-context>",
    "<skills_instructions>",
    "<plugins_instructions>",
    "<collaboration_mode>",
    "<environment_context>",
    "<system-reminder>",
)


def _is_codex_internal_text(text):
    stripped = str(text or "").lstrip().lower()
    return any(stripped.startswith(prefix) for prefix in _CODEX_INTERNAL_TEXT_PREFIXES)


def _is_codex_internal_part(part):
    return isinstance(part, dict) and part.get("type") == "text" and _is_codex_internal_text(part.get("text"))


def _filter_codex_message_parts(role, parts, include_system):
    visible_parts = [part for part in parts or [] if not _is_codex_internal_part(part)]
    if include_system:
        return visible_parts
    if role in ("system", "developer"):
        return []
    if role not in ("user", "assistant", "tool"):
        return []
    return visible_parts


def _strip_encrypted_content(value):
    if isinstance(value, dict):
        return {
            key: _strip_encrypted_content(item)
            for key, item in value.items()
            if key != "encrypted_content"
        }
    if isinstance(value, list):
        return [_strip_encrypted_content(item) for item in value]
    return value


def _json_object_from_string(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _reasoning_summary_text(summary):
    if isinstance(summary, str):
        return summary
    if not isinstance(summary, list):
        return ""
    texts = []
    for item in summary:
        if isinstance(item, dict) and item.get("text"):
            texts.append(str(item.get("text") or ""))
        elif isinstance(item, str):
            texts.append(item)
    return "\n".join(text for text in texts if text)


def _reasoning_summary_list(part):
    summary = part.get("summary") if isinstance(part, dict) else None
    if isinstance(summary, list):
        return summary
    summary_text = str((part or {}).get("summary_text") or "")
    return [{"type": "summary_text", "text": summary_text}] if summary_text else []


def _droid_thinking_to_bridge(part):
    part = part if isinstance(part, dict) else {}
    signature = part.get("signature") if isinstance(part.get("signature"), str) else ""
    signature_payload = _json_object_from_string(signature)
    summary = signature_payload.get("summary") if isinstance(signature_payload.get("summary"), list) else []
    summary_text = str(part.get("openaiReasoningSummary") or _reasoning_summary_text(summary) or "")
    result = {
        "type": "reasoning",
        "text": str(part.get("thinking") or ""),
    }
    encrypted_content = part.get("openaiEncryptedContent") or signature_payload.get("encrypted_content") or part.get("encrypted_content")
    reasoning_id = part.get("openaiReasoningId") or signature_payload.get("id") or part.get("id")
    if encrypted_content:
        result["encrypted_content"] = str(encrypted_content)
    if reasoning_id:
        result["reasoning_id"] = str(reasoning_id)
    if summary:
        result["summary"] = summary
    if summary_text:
        result["summary_text"] = summary_text
    if signature:
        result["signature"] = signature
    if part.get("signatureProvider"):
        result["signature_provider"] = str(part.get("signatureProvider"))
    if part.get("durationMs") is not None:
        result["duration_ms"] = _int_or_default(part.get("durationMs"), 0)
    return result


def _codex_reasoning_to_bridge(payload):
    payload = payload if isinstance(payload, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), list) else []
    summary_text = _reasoning_summary_text(summary)
    result = {
        "type": "reasoning",
        "text": str(payload.get("content") or payload.get("text") or ""),
    }
    encrypted_content = payload.get("encrypted_content") or payload.get("openaiEncryptedContent")
    reasoning_id = payload.get("id") or payload.get("reasoning_id") or payload.get("openaiReasoningId")
    if encrypted_content:
        result["encrypted_content"] = str(encrypted_content)
    if reasoning_id:
        result["reasoning_id"] = str(reasoning_id)
    if summary:
        result["summary"] = summary
    if summary_text:
        result["summary_text"] = summary_text
    return result


def _bridge_source_event(event, event_index, timestamp_default, represented_by=""):
    event = event if isinstance(event, dict) else {}
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    timestamp = event.get("timestamp") or payload.get("timestamp") or timestamp_default
    return {
        "index": int(event_index),
        "timestamp": _iso(_parse_datetime(timestamp) or _parse_datetime(timestamp_default) or _utc_now()),
        "outer_type": str(event.get("type") or ""),
        "payload_type": str(payload.get("type") or event.get("type") or ""),
        "represented_by": str(represented_by or ""),
        "raw": event,
    }


def _bridge_source_app(source_event, fallback=""):
    source_event = source_event if isinstance(source_event, dict) else {}
    return str(source_event.get("source_app") or source_event.get("source") or fallback or "")


def _source_events_for_replay(bridge, target_app):
    bridge = bridge if isinstance(bridge, dict) else {}
    source = bridge.get("source") if isinstance(bridge.get("source"), dict) else {}
    bridge_source_app = str(source.get("app") or "")
    target_app = str(target_app or "")
    replay = []
    for order, source_event in enumerate(bridge.get("source_events") or []):
        if not isinstance(source_event, dict) or not isinstance(source_event.get("raw"), dict):
            continue
        event_source_app = _bridge_source_app(source_event, bridge_source_app if bridge_source_app == target_app else "")
        if event_source_app != target_app:
            continue
        replay.append((order, source_event))
    return [source_event for _, source_event in sorted(replay, key=lambda item: (_int_or_default(item[1].get("index"), item[0]), item[0]))]


def _copy_raw_events_for_replay(bridge, target_app, first_type):
    raw_events = []
    for source_event in _source_events_for_replay(bridge, target_app):
        raw = source_event.get("raw")
        if not isinstance(raw, dict):
            continue
        raw_events.append(json.loads(json.dumps(raw)))
    if not raw_events or raw_events[0].get("type") != first_type:
        return []
    return raw_events


def _int_or_default(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_compaction_mode(mode):
    text = str(mode or "archived").strip().lower()
    if text not in CHAT_COMPACTION_MODES:
        raise ValueError(f"unsupported chat compaction mode: {mode}")
    return text


def _is_archived_compaction_mode(mode):
    return str(mode or "").strip().lower() in ("archived", "raw")


def _codex_token_count_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    result = {}
    info = payload.get("info")
    if isinstance(info, dict):
        result["info"] = info
    if "rate_limits" in payload:
        result["rate_limits"] = payload.get("rate_limits")
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens", "model_context_window"):
        if key in payload:
            result[key] = payload.get(key)
    return result


def _filter_replacement_history(history, include_system=True):
    if not isinstance(history, list):
        return []
    if include_system:
        return list(history)
    filtered = []
    for item in history:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        role = str(item.get("role") or "").lower()
        if role in ("system", "developer"):
            continue
        content = item.get("content")
        if isinstance(content, list) and any(_is_codex_internal_part(part) for part in content):
            continue
        if isinstance(content, str) and _is_codex_internal_text(content):
            continue
        filtered.append(item)
    return filtered


def _codex_compaction_from_event(event, event_index, timestamp, messages, include_system, last_token_count):
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    payload_anchor = payload.get("anchor_message") if isinstance(payload.get("anchor_message"), dict) else {}
    payload_anchor_index = _int_or_default(payload_anchor.get("index"), -1)
    fallback_anchor_index = len(messages) - 1
    anchor_index = payload_anchor_index if payload_anchor_index >= 0 else fallback_anchor_index
    fallback_anchor = messages[fallback_anchor_index] if fallback_anchor_index >= 0 else {}
    replacement_history = _filter_replacement_history(payload.get("replacement_history"), include_system=include_system)
    compaction = {
        "source": "codex",
        "id": str(payload.get("id") or event.get("id") or f"codex-compaction-{event_index}"),
        "timestamp": _iso(_parse_datetime(timestamp) or _utc_now()),
        "summary_text": str(payload.get("message") or payload.get("summary") or ""),
        "summary_tokens": _int_or_default(payload.get("summary_tokens"), 0),
        "summary_kind": str(payload.get("summary_kind") or "llm_summary"),
        "removed_count": _int_or_default(payload.get("removed_count"), len(replacement_history)),
        "source_event_index": int(event_index),
        "context_compacted_event_index": -1,
        "anchor_message_id": str(payload_anchor.get("id") or fallback_anchor.get("id") or ""),
        "anchor_message_index": int(anchor_index),
        "parent_session_id": str(payload.get("parent_session_id") or ""),
        "replacement_history": replacement_history,
    }
    if last_token_count:
        compaction["token_count_before"] = last_token_count
    if isinstance(payload.get("token_count_before"), dict):
        compaction["token_count_before"] = payload.get("token_count_before")
    if isinstance(payload.get("token_count_after"), dict):
        compaction["token_count_after"] = payload.get("token_count_after")
    if isinstance(payload.get("system_info"), dict):
        compaction["system_info"] = payload.get("system_info")
    if payload.get("ui_render_cutoff_message_id"):
        compaction["ui_render_cutoff_message_id"] = str(payload.get("ui_render_cutoff_message_id"))
    return compaction


def _droid_compaction_from_event(event, event_index, session_start):
    event = event if isinstance(event, dict) else {}
    anchor = event.get("anchorMessage") if isinstance(event.get("anchorMessage"), dict) else {}
    compaction = {
        "source": "droid",
        "id": str(event.get("id") or f"droid-compaction-{event_index}"),
        "timestamp": _iso(_parse_datetime(event.get("timestamp")) or _utc_now()),
        "summary_text": str(event.get("summaryText") or ""),
        "summary_tokens": _int_or_default(event.get("summaryTokens"), 0),
        "summary_kind": str(event.get("summaryKind") or "llm_summary"),
        "removed_count": _int_or_default(event.get("removedCount"), 0),
        "source_event_index": int(event_index),
        "context_compacted_event_index": -1,
        "anchor_message_id": str(anchor.get("id") or ""),
        "anchor_message_index": _int_or_default(anchor.get("index"), -1),
        "parent_session_id": str(session_start.get("parent") or ""),
        "replacement_history": [],
    }
    if isinstance(event.get("systemInfo"), dict):
        compaction["system_info"] = event.get("systemInfo")
    if event.get("uiRenderCutoffMessageId"):
        compaction["ui_render_cutoff_message_id"] = str(event.get("uiRenderCutoffMessageId"))
    return compaction


def _message_has_tool_result(parts):
    return parts and all(part.get("type") == "tool_result" for part in parts)


def _droid_part_to_bridge(part):
    if not isinstance(part, dict):
        return {"type": "unknown", "summary": type(part).__name__}
    part_type = part.get("type")
    if part_type == "text":
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "thinking":
        return _droid_thinking_to_bridge(part)
    if part_type == "tool_use":
        return {
            "type": "tool_call",
            "id": str(part.get("id") or ""),
            "name": str(part.get("name") or ""),
            "input": part.get("input"),
        }
    if part_type == "tool_result":
        result = {
            "type": "tool_result",
            "tool_call_id": str(part.get("tool_use_id") or part.get("id") or ""),
            "content": part.get("content"),
        }
        if "is_error" in part:
            result["is_error"] = bool(part.get("is_error"))
        return result
    return {"type": "unknown", "source_type": str(part_type or ""), "keys": sorted(part.keys())}


def droid_session_to_bridge(jsonl_path, settings_path=None):
    jsonl_path = Path(jsonl_path)
    settings = _read_json_file(settings_path)
    events = _read_jsonl(jsonl_path)
    session_start = next((e for e in events if e.get("type") == "session_start"), {})
    session_id = str(session_start.get("id") or jsonl_path.stem)
    title = str(session_start.get("sessionTitle") or session_start.get("title") or session_id)
    cwd = _normalize_droid_cwd(session_start.get("cwd") or "")
    settings_model = str(settings.get("model") or settings.get("providerLock") or "")
    settings_provider = str(settings.get("providerLock") or "")
    bridge_provider = settings_provider if settings.get("model") and settings_provider else "droid"
    messages = []
    timestamps = []
    raw_event_refs = []
    native_source_events = []
    archived_source_events = []
    compactions = []

    for event_index, event in enumerate(events):
        event_type = event.get("type")
        raw_event_refs.append(f"{jsonl_path}:{event_index + 1}")
        event_ts = event.get("timestamp")
        if event_ts:
            timestamps.append(_ms(event_ts))
        if event_type == "bridge_source_event":
            raw = event.get("raw") if isinstance(event.get("raw"), dict) else event
            archived_source_events.append({
                "index": _int_or_default(event.get("sourceIndex"), event_index),
                "timestamp": _iso(_parse_datetime(event_ts) or _utc_now()),
                "source_app": str(event.get("source") or ""),
                "outer_type": str(event.get("outerType") or ""),
                "payload_type": str(event.get("payloadType") or ""),
                "represented_by": str(event.get("representedBy") or ""),
                "raw": raw,
            })
            continue
        source_event = _bridge_source_event(event, event_index, event_ts or _iso(_utc_now()))
        native_source_events.append(source_event)

        if event_type == "message":
            msg = event.get("message") if isinstance(event.get("message"), dict) else {}
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            parts = [_droid_part_to_bridge(part) for part in content]
            if not parts:
                parts = [{"type": "unknown", "summary": "empty Droid message content"}]
            role = str(event.get("bridgeRole") or msg.get("role") or "unknown")
            if _message_has_tool_result(parts):
                role = "tool"
            messages.append({
                "id": str(event.get("id") or msg.get("id") or f"droid-message-{event_index}"),
                "parent_id": str(event.get("parentId") or ""),
                "role": role if role in ("user", "assistant", "system", "tool", "unknown") else "unknown",
                "created_at": _iso(_parse_datetime(event_ts) or _utc_now()),
                "parts": parts,
                "raw_source_ref": f"{jsonl_path}:{event_index + 1}",
            })
            source_event["represented_by"] = messages[-1]["id"]
        elif event_type == "todo_state":
            messages.append({
                "id": str(event.get("id") or f"droid-todo-{event_index}"),
                "parent_id": "",
                "role": "unknown",
                "created_at": _iso(_parse_datetime(event_ts) or _utc_now()),
                "parts": [{"type": "todo_state", "summary": {"count": len(event.get("todos") or [])}}],
                "raw_source_ref": f"{jsonl_path}:{event_index + 1}",
            })
            source_event["represented_by"] = messages[-1]["id"]
        elif event_type == "compaction_state":
            compactions.append(_droid_compaction_from_event(event, event_index, session_start))

    sidecar_source_events = _read_droid_source_archive(jsonl_path)
    if sidecar_source_events:
        archived_source_events = sidecar_source_events

    created_ms = min(timestamps) if timestamps else int(_utc_now().timestamp() * 1000)
    updated_ms = max(timestamps) if timestamps else created_ms
    work_context = _unknown_work_context()
    if cwd:
        work_context["primary_cwd"] = cwd
        work_context["current"]["cwd"] = cwd
        work_context["current"]["source"] = "droid_session_start"
        work_context["current"]["confidence"] = "observed"
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
            "provider": bridge_provider,
            "model": settings_model,
            "reasoning_effort": settings.get("reasoningEffort") or "",
            "is_title_manually_set": bool(session_start.get("isSessionTitleManuallySet")) if "isSessionTitleManuallySet" in session_start else False,
            "title_auto_stage": str(session_start.get("sessionTitleAutoStage") or ""),
        },
        "work_context": work_context,
        "messages": messages,
        "extras": {
            "droid_session_start": {
                "title": session_start.get("title") or "",
                "sessionTitle": session_start.get("sessionTitle") or "",
                "cwd": cwd,
                "hostId": session_start.get("hostId") or "",
                "owner": session_start.get("owner") or "",
                "parent": session_start.get("parent") or "",
                "version": session_start.get("version"),
                "isSessionTitleManuallySet": bool(session_start.get("isSessionTitleManuallySet")) if "isSessionTitleManuallySet" in session_start else None,
                "sessionTitleAutoStage": session_start.get("sessionTitleAutoStage") or "",
            },
            "droid_settings": {
                "model": settings_model,
                "reasoningEffort": settings.get("reasoningEffort") or "",
                "providerLock": settings_provider,
                "providerLockTimestamp": settings.get("providerLockTimestamp") or "",
                "tokenUsage": settings.get("tokenUsage") if isinstance(settings.get("tokenUsage"), dict) else {},
                "assistantActiveTimeMs": _int_or_default(settings.get("assistantActiveTimeMs"), 0) if "assistantActiveTimeMs" in settings else None,
            }
        },
        "raw_event_refs": raw_event_refs,
        "source_events": archived_source_events if archived_source_events else native_source_events,
        "compactions": compactions,
    }
    validate_bridge(bridge)
    return bridge


def _codex_content_part_to_bridge(part):
    if not isinstance(part, dict):
        return {"type": "unknown", "summary": type(part).__name__}
    part_type = part.get("type")
    if part_type in ("input_text", "output_text", "text"):
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "reasoning":
        return _codex_reasoning_to_bridge(part)
    if part_type == "tool_call":
        return {
            "type": "tool_call",
            "id": str(part.get("id") or ""),
            "name": str(part.get("name") or ""),
            "input": part.get("input"),
        }
    if part_type == "tool_result":
        result = {
            "type": "tool_result",
            "tool_call_id": str(part.get("tool_call_id") or part.get("tool_use_id") or ""),
            "content": part.get("content"),
        }
        if "is_error" in part:
            result["is_error"] = bool(part.get("is_error"))
        return result
    if part_type in ("input_image", "image"):
        return {"type": "image", "summary": "image content"}
    return {"type": "unknown", "source_type": str(part_type or ""), "keys": sorted(part.keys())}


def _bridge_message_part_types(message):
    return [part.get("type") for part in (message.get("parts") or []) if isinstance(part, dict)]


def _append_codex_reasoning(messages, part, message_id, timestamp, event_index, rollout_path, snapshots):
    if messages and messages[-1].get("role") == "assistant":
        part_types = _bridge_message_part_types(messages[-1])
        if part_types and all(part_type in ("text", "tool_call", "reasoning") for part_type in part_types):
            messages[-1]["parts"].append(part)
            return messages[-1]
    messages.append({
        "id": str(message_id or f"codex-reasoning-{event_index}"),
        "parent_id": "",
        "role": "assistant",
        "created_at": timestamp,
        "work_snapshot_id": snapshots[-1]["id"] if snapshots else "",
        "parts": [part],
        "raw_source_ref": f"{rollout_path}:{event_index + 1}",
    })
    return messages[-1]


def _append_codex_tool_call(messages, part, message_id, timestamp, event_index, rollout_path, snapshots):
    if messages and messages[-1].get("role") == "assistant":
        part_types = _bridge_message_part_types(messages[-1])
        if part_types and all(part_type in ("text", "tool_call", "reasoning") for part_type in part_types):
            messages[-1]["parts"].append(part)
            return messages[-1]
    messages.append({
        "id": str(message_id or f"codex-tool-{event_index}"),
        "parent_id": "",
        "role": "assistant",
        "created_at": timestamp,
        "work_snapshot_id": snapshots[-1]["id"] if snapshots else "",
        "parts": [part],
        "raw_source_ref": f"{rollout_path}:{event_index + 1}",
    })
    return messages[-1]


def _append_codex_tool_result(messages, part, message_id, timestamp, event_index, rollout_path):
    if messages and messages[-1].get("role") == "tool":
        part_types = _bridge_message_part_types(messages[-1])
        if part_types and all(part_type == "tool_result" for part_type in part_types):
            messages[-1]["parts"].append(part)
            return messages[-1]
    messages.append({
        "id": str(message_id or f"codex-tool-result-{event_index}"),
        "parent_id": "",
        "role": "tool",
        "created_at": timestamp,
        "parts": [part],
        "raw_source_ref": f"{rollout_path}:{event_index + 1}",
    })
    return messages[-1]


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
    source_events = []
    archived_source_events = []
    compactions = []
    last_token_count = None
    pending_compaction_index = None

    for event_index, event in enumerate(events):
        raw_event_refs.append(f"{rollout_path}:{event_index + 1}")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        payload_type = payload.get("type") or event.get("type")
        timestamp = event.get("timestamp") or payload.get("timestamp") or _iso(_dt_from_ms(created_ms))
        source_event = _bridge_source_event(event, event_index, timestamp)

        if payload_type == "bridge_source_events":
            archive_source_app = str(payload.get("source_app") or payload.get("source") or "")
            archived = payload.get("events") if isinstance(payload.get("events"), list) else []
            for archived_event in archived:
                if not isinstance(archived_event, dict):
                    continue
                restored = json.loads(json.dumps(archived_event))
                if archive_source_app and not _bridge_source_app(restored):
                    restored["source_app"] = archive_source_app
                archived_source_events.append(restored)
            continue

        if payload_type == "token_count":
            token_count = _codex_token_count_payload(payload)
            if pending_compaction_index is not None and "token_count_after" not in compactions[pending_compaction_index]:
                compactions[pending_compaction_index]["token_count_after"] = token_count
            last_token_count = token_count
            source_events.append(source_event)
            continue

        if event.get("type") == "compacted":
            compactions.append(_codex_compaction_from_event(event, event_index, timestamp, messages, include_system, last_token_count))
            pending_compaction_index = len(compactions) - 1
            source_events.append(source_event)
            continue

        if payload_type == "context_compacted":
            if pending_compaction_index is not None:
                compactions[pending_compaction_index]["context_compacted_event_index"] = int(event_index)
                compactions[pending_compaction_index]["context_compacted_at"] = _iso(_parse_datetime(timestamp) or _utc_now())
            source_events.append(source_event)
            continue

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
            source_events.append(source_event)
            continue

        if payload_type == "reasoning":
            part = _codex_reasoning_to_bridge(payload)
            message = _append_codex_reasoning(
                messages,
                part,
                payload.get("id") or event.get("id") or f"codex-reasoning-{event_index}",
                _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                event_index,
                rollout_path,
                snapshots,
            )
            source_event["represented_by"] = message["id"]
            source_events.append(source_event)
            continue

        if payload_type in ("message", "user_message", "agent_message"):
            role = payload.get("role")
            if not role:
                role = "user" if payload_type == "user_message" else "assistant" if payload_type == "agent_message" else "unknown"
            content = payload.get("content")
            parts = []
            if isinstance(content, list):
                parts = [_codex_content_part_to_bridge(part) for part in content]
            elif payload.get("text"):
                parts = [{"type": "text", "text": str(payload.get("text") or "")}]
            parts = _filter_codex_message_parts(role, parts, include_system)
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
                source_event["represented_by"] = messages[-1]["id"]
                source_events.append(source_event)
            elif include_system:
                source_events.append(source_event)
        elif payload_type in ("function_call", "custom_tool_call"):
            part = {
                "type": "tool_call",
                "id": str(payload.get("call_id") or payload.get("id") or ""),
                "name": str(payload.get("name") or ""),
                "input": payload.get("arguments") or payload.get("input"),
            }
            message = _append_codex_tool_call(
                messages,
                part,
                payload.get("id"),
                _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                event_index,
                rollout_path,
                snapshots,
            )
            source_event["represented_by"] = message["id"]
            source_events.append(source_event)
        elif payload_type in ("function_call_output", "custom_tool_call_output"):
            part = {"type": "tool_result", "tool_call_id": str(payload.get("call_id") or payload.get("id") or ""), "content": payload.get("output")}
            if "is_error" in payload:
                part["is_error"] = bool(payload.get("is_error"))
            message = _append_codex_tool_result(
                messages,
                part,
                payload.get("id"),
                _iso(_parse_datetime(timestamp) or _dt_from_ms(created_ms)),
                event_index,
                rollout_path,
            )
            source_event["represented_by"] = message["id"]
            source_events.append(source_event)
        else:
            source_events.append(source_event)

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
            "reasoning_effort": row.get("reasoning_effort") or "",
        },
        "work_context": work_context,
        "messages": messages,
        "extras": {},
        "raw_event_refs": raw_event_refs,
        "source_events": archived_source_events if archived_source_events else source_events,
        "compactions": compactions,
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
    source_events = bridge.get("source_events", [])
    if source_events is None:
        source_events = []
    if not isinstance(source_events, list):
        raise ValueError("bridge source_events must be a list")
    for index, source_event in enumerate(source_events):
        if not isinstance(source_event, dict):
            raise ValueError(f"bridge source_event {index} must be an object")
        if "raw" not in source_event or not isinstance(source_event.get("raw"), dict):
            raise ValueError(f"bridge source_event {index} must include raw object")
    compactions = bridge.get("compactions", [])
    if compactions is None:
        compactions = []
    if not isinstance(compactions, list):
        raise ValueError("bridge compactions must be a list")
    for index, compaction in enumerate(compactions):
        if not isinstance(compaction, dict):
            raise ValueError(f"bridge compaction {index} must be an object")
        if "summary_text" not in compaction:
            raise ValueError(f"bridge compaction {index} must include summary_text")
        if "timestamp" in compaction and _parse_datetime(compaction.get("timestamp")) is None:
            raise ValueError(f"bridge compaction {index} has invalid timestamp")
    return True


def _rollout_message_part(part, role=None, codex_desktop_compat=False):
    part_type = part.get("type")
    if part_type == "text":
        if codex_desktop_compat and role in ("user", "system", "developer"):
            return {"type": "input_text", "text": str(part.get("text") or "")}
        return {"type": "output_text", "text": str(part.get("text") or "")}
    if codex_desktop_compat:
        return None
    return {"type": "metadata", "text": json.dumps({"part_type": part_type}, ensure_ascii=True)}


def _codex_reasoning_payload(part, codex_desktop_compat=False):
    part = part if isinstance(part, dict) else {}
    payload = {"type": "reasoning"}
    if part.get("reasoning_id"):
        payload["id"] = str(part.get("reasoning_id"))
    if part.get("encrypted_content"):
        payload["encrypted_content"] = str(part.get("encrypted_content"))
    if codex_desktop_compat:
        payload["summary"] = []
        payload["content"] = None
    else:
        summary = _reasoning_summary_list(part)
        if summary or "summary" in part or part.get("summary_text"):
            payload["summary"] = summary
        if part.get("text"):
            payload["content"] = str(part.get("text"))
    return payload


def _compaction_anchor_index(compaction, messages):
    anchor_id = str(compaction.get("anchor_message_id") or "")
    if anchor_id:
        for index, message in enumerate(messages or []):
            if str(message.get("id") or "") == anchor_id:
                return index
    index = _int_or_default(compaction.get("anchor_message_index"), -1)
    if 0 <= index < len(messages or []):
        return index
    return -1


def _codex_compaction_events(compaction, default_timestamp):
    compaction = compaction if isinstance(compaction, dict) else {}
    timestamp = _iso(_parse_datetime(compaction.get("timestamp")) or _parse_datetime(default_timestamp) or _utc_now())
    replacement_history = compaction.get("replacement_history") if isinstance(compaction.get("replacement_history"), list) else []
    payload = {
        "message": str(compaction.get("summary_text") or ""),
        "replacement_history": replacement_history,
        "source": str(compaction.get("source") or "chat_bridge"),
        "summary_tokens": _int_or_default(compaction.get("summary_tokens"), 0),
        "summary_kind": str(compaction.get("summary_kind") or "llm_summary"),
        "removed_count": _int_or_default(compaction.get("removed_count"), len(replacement_history)),
    }
    if compaction.get("parent_session_id"):
        payload["parent_session_id"] = str(compaction.get("parent_session_id"))
    anchor_index = _int_or_default(compaction.get("anchor_message_index"), -1)
    anchor_id = str(compaction.get("anchor_message_id") or "")
    if anchor_id or anchor_index >= 0:
        payload["anchor_message"] = {"id": anchor_id, "index": anchor_index}
    if isinstance(compaction.get("system_info"), dict):
        payload["system_info"] = compaction.get("system_info")
    if compaction.get("ui_render_cutoff_message_id"):
        payload["ui_render_cutoff_message_id"] = str(compaction.get("ui_render_cutoff_message_id"))
    if isinstance(compaction.get("token_count_before"), dict):
        payload["token_count_before"] = compaction.get("token_count_before")
    if isinstance(compaction.get("token_count_after"), dict):
        payload["token_count_after"] = compaction.get("token_count_after")
    context_timestamp = _iso(_parse_datetime(compaction.get("context_compacted_at")) or _parse_datetime(timestamp) or _utc_now())
    return [
        {"timestamp": timestamp, "type": "compacted", "payload": payload},
        {"timestamp": context_timestamp, "type": "event_msg", "payload": {"type": "context_compacted"}},
    ]


def _codex_bridge_source_events_event(source_events, timestamp, source_app):
    archived = [event for event in (source_events or []) if isinstance(event, dict)]
    if not archived:
        return None
    return {
        "timestamp": _iso(_parse_datetime(timestamp) or _utc_now()),
        "type": "event_msg",
        "payload": {
            "type": "bridge_source_events",
            "source": str(source_app or ""),
            "events": archived,
        },
    }


def _render_codex_raw_replay(bridge, codex_id, created_ms, target_provider=None, target_model=None):
    events = _copy_raw_events_for_replay(bridge, "codex", "session_meta")
    if not events:
        return ""
    created_iso = _iso(_dt_from_ms(created_ms))
    first = events[0]
    payload = first.get("payload") if isinstance(first.get("payload"), dict) else {}
    first["payload"] = payload
    payload["id"] = codex_id
    payload.setdefault("timestamp", created_iso)
    first.setdefault("timestamp", payload.get("timestamp") or created_iso)
    payload["model_provider"] = str(target_provider or payload.get("model_provider") or "")
    payload["model"] = str(target_model or payload.get("model") or "")
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _emit_desktop_token_count(events, timestamp, model):
    events.append({
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": random.randint(10000, 80000),
                    "cached_input_tokens": random.randint(2000, 10000),
                    "output_tokens": random.randint(100, 2000),
                    "reasoning_output_tokens": random.randint(0, 500),
                    "total_tokens": random.randint(12000, 85000),
                },
                "last_token_usage": {
                    "input_tokens": random.randint(5000, 30000),
                    "cached_input_tokens": random.randint(1000, 5000),
                    "output_tokens": random.randint(50, 1000),
                    "reasoning_output_tokens": random.randint(0, 200),
                    "total_tokens": random.randint(6000, 35000),
                },
                "model_context_window": CODEX_DESKTOP_MODEL_CONTEXT_WINDOW,
            },
            "rate_limits": {
                "limit_id": "codex",
                "limit_name": None,
                "primary": None,
                "secondary": None,
                "credits": None,
                "plan_type": None,
                "rate_limit_reached_type": None,
            },
        },
    })


def _render_codex_rollout(
    bridge,
    codex_id,
    created_ms,
    updated_ms,
    preserve_message_timestamps=True,
    compaction_mode="archived",
    target_provider=None,
    target_model=None,
    codex_desktop_compat=False,
):
    compaction_mode = _normalize_compaction_mode(compaction_mode)
    source = bridge.get("source") if isinstance(bridge.get("source"), dict) else {}
    session = bridge["session"]
    work = bridge.get("work_context") if isinstance(bridge.get("work_context"), dict) else {}
    current = work.get("current") if isinstance(work.get("current"), dict) else {}
    model_provider = target_provider or session.get("provider") or ""
    model = target_model or session.get("model") or ""
    created_iso = _iso(_dt_from_ms(created_ms))
    cwd = work.get("primary_cwd") or current.get("cwd") or ""

    # --- session_meta ---
    if codex_desktop_compat:
        meta_template = _desktop_load_meta_template()
        events = [{
            "timestamp": created_iso,
            "type": "session_meta",
            "payload": {
                "id": codex_id,
                "timestamp": created_iso,
                "cwd": cwd,
                "originator": CODEX_DESKTOP_ORIGINATOR,
                "cli_version": CODEX_DESKTOP_CLI_VERSION,
                "source": CODEX_DESKTOP_SOURCE,
                "thread_source": CODEX_DESKTOP_THREAD_SOURCE,
                "model_provider": model_provider,
                "model": model or "gpt-5.5",
                "base_instructions": meta_template.get("base_instructions", {"text": "You are Codex."}),
                "dynamic_tools": meta_template.get("dynamic_tools", []),
            },
        }]
        turn_id = str(uuid.uuid4())
        started_at = int(_dt_from_ms(created_ms).timestamp())
        events.append({
            "timestamp": created_iso,
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": turn_id,
                "started_at": started_at,
                "model_context_window": CODEX_DESKTOP_MODEL_CONTEXT_WINDOW,
                "collaboration_mode_kind": "default",
            },
        })
        events.append({
            "timestamp": created_iso,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": CODEX_DESKTOP_PERMISSIONS_BLOCK},
                    {"type": "input_text", "text": CODEX_DESKTOP_APP_CONTEXT_BLOCK},
                    {"type": "input_text", "text": CODEX_DESKTOP_COLLABORATION_BLOCK},
                    {"type": "input_text", "text": CODEX_DESKTOP_SKILLS_BLOCK},
                    {"type": "input_text", "text": CODEX_DESKTOP_PLUGINS_BLOCK},
                ],
            },
        })
        events.append({
            "timestamp": created_iso,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": _desktop_env_context_text(cwd, created_iso)}],
            },
        })
        events.append({
            "timestamp": created_iso,
            "type": "turn_context",
            "payload": {
                "turn_id": turn_id,
                "cwd": cwd,
                "current_date": created_iso[:10],
                "timezone": CODEX_DESKTOP_TIMEZONE,
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
                "permission_profile": {"type": "disabled"},
                "model": model or "gpt-5.5",
                "personality": CODEX_DESKTOP_PERSONALITY,
                "collaboration_mode": {"mode": "default", "settings": {}},
                "realtime_active": False,
                "effort": "low",
                "summary": "auto",
            },
        })
    else:
        events = [{
            "timestamp": created_iso,
            "type": "session_meta",
            "payload": {
                "id": codex_id,
                "timestamp": created_iso,
                "cwd": cwd,
                "originator": "chat_bridge",
                "source": "chat_bridge",
                "model_provider": model_provider,
                "model": model,
                "git": {
                    "branch": current.get("git_branch") or "",
                    "commit_hash": current.get("git_sha") or "",
                    "repository_url": current.get("git_origin_url") or "",
                },
            },
        }]

    messages = bridge.get("messages", [])
    compactions = [] if _is_archived_compaction_mode(compaction_mode) else (bridge.get("compactions") or [])
    compactions_before_messages = []
    compactions_after_message = {}
    for compaction in compactions:
        anchor_index = _compaction_anchor_index(compaction, messages)
        if anchor_index >= 0:
            compactions_after_message.setdefault(anchor_index, []).append(compaction)
        else:
            compactions_before_messages.append(compaction)
    for compaction in compactions_before_messages:
        events.extend(_codex_compaction_events(compaction, created_iso))

    # Desktop compat state
    desktop_turn_context_added = not codex_desktop_compat
    desktop_call_id_map = {}
    desktop_pending_token_count = False
    desktop_tool_search_emitted = False
    desktop_task_agents = {}  # original_call_id -> {agent_id, nickname, call_id}
    desktop_apply_patch_calls = {}  # mapped_call_id -> patch_input (str)

    for message_index, message in enumerate(messages):
        role = message.get("role") if message.get("role") in ("user", "assistant", "system", "tool") else "unknown"
        if codex_desktop_compat and role not in ("user", "assistant", "system", "tool"):
            continue  # skip todo_state and other unknown parts
        if preserve_message_timestamps:
            timestamp = message.get("created_at") or created_iso
        else:
            timestamp_ms = min(updated_ms, created_ms + message_index + 1)
            timestamp = _iso(_dt_from_ms(timestamp_ms))

        # Emit pending token_count from previous tool group
        if codex_desktop_compat and desktop_pending_token_count:
            desktop_pending_token_count = False
            _emit_desktop_token_count(events, timestamp, model)

        # Desktop: emit user_message event_msg before user messages
        if codex_desktop_compat and role == "user":
            user_text = _first_text(message.get("parts")) or ""
            if not _is_codex_internal_text(user_text):
                events.append({
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": user_text + "\n",
                        "images": [],
                        "local_images": [],
                        "text_elements": [],
                    },
                })

        message_content = []
        assistant_text_for_commentary = []

        def flush_message_content():
            if not message_content:
                return
            msg_payload = {
                "type": "message",
                "role": role,
                "content": list(message_content),
            }
            if codex_desktop_compat and role == "assistant" and assistant_text_for_commentary:
                msg_payload["phase"] = "commentary"
            events.append({
                "timestamp": timestamp,
                "type": "response_item",
                "payload": msg_payload,
            })
            # Desktop: emit agent_message event_msg after assistant text
            if codex_desktop_compat and role == "assistant" and assistant_text_for_commentary:
                events.append({
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "agent_message",
                        "message": " ".join(assistant_text_for_commentary),
                        "phase": "commentary",
                        "memory_citation": None,
                    },
                })
            message_content.clear()
            assistant_text_for_commentary.clear()

        for part in message.get("parts", []):
            part_type = part.get("type")
            if part_type == "reasoning":
                flush_message_content()
                events.append({
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": _codex_reasoning_payload(part, codex_desktop_compat=codex_desktop_compat),
                })
            elif part_type == "tool_call":
                flush_message_content()
                if codex_desktop_compat:
                    original_id = part.get("id") or _desktop_call_id()
                    fake_id = _desktop_call_id()
                    desktop_call_id_map[original_id] = fake_id
                    tool_name = str(part.get("name") or "")
                    tool_input = part.get("input")
                    if isinstance(tool_input, dict):
                        # Build exec_command args
                        if tool_name == "Execute":
                            cmd = tool_input.get("command") or tool_input.get("cmd") or str(tool_input)
                            summary_text = str(tool_input.get("summary") or "").strip()
                            if summary_text:
                                events.append({
                                    "timestamp": timestamp,
                                    "type": "event_msg",
                                    "payload": {
                                        "type": "agent_message",
                                        "message": summary_text,
                                        "phase": "commentary",
                                        "memory_citation": None,
                                    },
                                })
                                events.append({
                                    "timestamp": timestamp,
                                    "type": "response_item",
                                    "payload": {
                                        "type": "message",
                                        "role": "assistant",
                                        "content": [{"type": "output_text", "text": summary_text}],
                                        "phase": "commentary",
                                    },
                                })
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "Read":
                            cmd = f"Get-Content {tool_input.get('file_path', '')}"
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "Glob":
                            pattern = tool_input.get("pattern", "")
                            glob_path = tool_input.get("path", "")
                            cmd = f"Get-ChildItem -Recurse -Filter {pattern}"
                            if glob_path:
                                cmd += f" {glob_path}"
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "Grep":
                            pattern = tool_input.get("pattern", "")
                            grep_path = tool_input.get("path", "")
                            cmd = f"rg -n \"{pattern}\""
                            if grep_path:
                                cmd += f" {grep_path}"
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "LS":
                            cmd = "Get-ChildItem -Force"
                            args = {"cmd": cmd, "workdir": tool_input.get("path", cwd)}
                        elif tool_name == "Write":
                            cmd = f"Set-Content {tool_input.get('file_path', '')}"
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "Edit":
                            cmd = f"Edit {tool_input.get('file_path', '')}"
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "Task":
                            desc = tool_input.get("description") or tool_input.get("prompt") or ""
                            agent_nickname = random.choice(["Averroes", "Maimonides", "Avicenna", "Alhazen", "Rhazes"])
                            agent_id = str(uuid.uuid4())
                            # Emit tool_search_call + tool_search_output once
                            if not desktop_tool_search_emitted:
                                desktop_tool_search_emitted = True
                                search_call_id = _desktop_call_id()
                                events.append({
                                    "timestamp": timestamp,
                                    "type": "response_item",
                                    "payload": {
                                        "type": "tool_search_call",
                                        "call_id": search_call_id,
                                        "status": "completed",
                                        "execution": "client",
                                        "arguments": {
                                            "query": "subagent spawn manage agents parallel",
                                            "limit": 5,
                                        },
                                    },
                                })
                                events.append({
                                    "timestamp": timestamp,
                                    "type": "response_item",
                                    "payload": {
                                        "type": "tool_search_output",
                                        "call_id": search_call_id,
                                        "status": "completed",
                                        "execution": "client",
                                        "tools": [{
                                            "type": "namespace",
                                            "name": "multi_agent_v1",
                                            "description": "Tools for spawning and managing sub-agents.",
                                            "tools": [
                                                {"type": "function", "name": "spawn_agent", "description": "Spawn a sub-agent."},
                                                {"type": "function", "name": "wait_agent", "description": "Wait for sub-agent completion."},
                                                {"type": "function", "name": "close_agent", "description": "Close a sub-agent."},
                                            ],
                                        }],
                                    },
                                })
                                _emit_desktop_token_count(events, timestamp, model)
                            # Emit commentary
                            commentary_text = f"Запускаю сабагента `{agent_nickname}` для: {desc[:120]}"
                            events.append({
                                "timestamp": timestamp,
                                "type": "event_msg",
                                "payload": {
                                    "type": "agent_message",
                                    "message": commentary_text,
                                    "phase": "commentary",
                                    "memory_citation": None,
                                },
                            })
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [{"type": "output_text", "text": commentary_text}],
                                    "phase": "commentary",
                                },
                            })
                            # spawn_agent call
                            spawn_call_id = _desktop_call_id()
                            desktop_call_id_map[original_id] = spawn_call_id
                            spawn_args = {
                                "agent_type": "explorer",
                                "fork_context": False,
                                "message": desc,
                            }
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "function_call",
                                    "call_id": spawn_call_id,
                                    "name": "spawn_agent",
                                    "namespace": "multi_agent_v1",
                                    "arguments": json.dumps(spawn_args, ensure_ascii=False),
                                },
                            })
                            # spawn_agent output with agent_id
                            spawn_output = json.dumps({"agent_id": agent_id, "nickname": agent_nickname})
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "function_call_output",
                                    "call_id": spawn_call_id,
                                    "output": spawn_output,
                                },
                            })
                            _emit_desktop_token_count(events, timestamp, model)
                            desktop_task_agents[original_id] = {
                                "agent_id": agent_id,
                                "nickname": agent_nickname,
                                "call_id": spawn_call_id,
                            }
                            continue
                        elif tool_name == "TodoWrite":
                            cmd = "# TodoWrite"
                            args = {"cmd": cmd, "workdir": cwd}
                        elif tool_name == "exec_command":
                            # Pass through original exec_command args without re-wrapping
                            args = tool_input
                        elif tool_name in ("spawn_agent", "wait_agent", "close_agent"):
                            # Re-emit multi_agent_v1 namespace calls
                            multi_call_id = _desktop_call_id()
                            desktop_call_id_map[original_id] = multi_call_id
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "function_call",
                                    "call_id": multi_call_id,
                                    "name": tool_name,
                                    "namespace": "multi_agent_v1",
                                    "arguments": json.dumps(tool_input, ensure_ascii=False),
                                },
                            })
                            continue
                        elif tool_name in ("apply_patch", "ApplyPatch"):
                            # Emit as custom_tool_call for proper Codex UI rendering
                            patch_call_id = _desktop_call_id()
                            desktop_call_id_map[original_id] = patch_call_id
                            patch_input = tool_input.get("raw", tool_input.get("input", ""))
                            if isinstance(patch_input, dict):
                                patch_input = json.dumps(patch_input, ensure_ascii=False)
                            desktop_apply_patch_calls[patch_call_id] = str(patch_input)
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "custom_tool_call",
                                    "status": "completed",
                                    "call_id": patch_call_id,
                                    "name": "apply_patch",
                                    "input": str(patch_input),
                                },
                            })
                            continue
                        elif tool_name in ("write_stdin", "update_plan", "request_user_input", "read_thread_terminal"):
                            # Pass through as native function_call (not exec_command)
                            native_call_id = _desktop_call_id()
                            desktop_call_id_map[original_id] = native_call_id
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "function_call",
                                    "call_id": native_call_id,
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_input, ensure_ascii=False),
                                },
                            })
                            continue
                        else:
                            cmd = f"{tool_name} {json.dumps(tool_input, ensure_ascii=False)[:200]}"
                            args = {"cmd": cmd, "workdir": cwd}
                    elif isinstance(tool_input, str):
                        args = {"cmd": tool_input, "workdir": cwd}
                    else:
                        args = {"cmd": str(tool_name), "workdir": cwd}
                    events.append({
                        "timestamp": timestamp,
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "call_id": fake_id,
                            "name": "exec_command",
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    })
                else:
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
                flush_message_content()
                original_call_id = part.get("tool_call_id") or ""
                payload = None
                if codex_desktop_compat:
                    task_agent = desktop_task_agents.pop(original_call_id, None)
                    if task_agent:
                        # Task tool result -> wait_agent + close_agent sequence
                        raw_output = part.get("content")
                        output_str = str(raw_output or "") if not isinstance(raw_output, str) else raw_output
                        # Commentary about agent result
                        nick = task_agent["nickname"]
                        result_commentary = f"Сабагент `{nick}` завершил работу."
                        events.append({
                            "timestamp": timestamp,
                            "type": "event_msg",
                            "payload": {
                                "type": "agent_message",
                                "message": result_commentary,
                                "phase": "commentary",
                                "memory_citation": None,
                            },
                        })
                        events.append({
                            "timestamp": timestamp,
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": result_commentary}],
                                "phase": "commentary",
                            },
                        })
                        # wait_agent call
                        wait_call_id = _desktop_call_id()
                        wait_args = {"targets": [task_agent["agent_id"]], "timeout_ms": 120000}
                        events.append({
                            "timestamp": timestamp,
                            "type": "response_item",
                            "payload": {
                                "type": "function_call",
                                "call_id": wait_call_id,
                                "name": "wait_agent",
                                "namespace": "multi_agent_v1",
                                "arguments": json.dumps(wait_args, ensure_ascii=False),
                            },
                        })
                        # wait_agent output
                        wait_output = json.dumps({"status": {task_agent["agent_id"]: {"completed": output_str}}})
                        events.append({
                            "timestamp": timestamp,
                            "type": "response_item",
                            "payload": {
                                "type": "function_call_output",
                                "call_id": wait_call_id,
                                "output": wait_output,
                            },
                        })
                        _emit_desktop_token_count(events, timestamp, model)
                        # close_agent call
                        close_call_id = _desktop_call_id()
                        close_args = {"target": task_agent["agent_id"]}
                        events.append({
                            "timestamp": timestamp,
                            "type": "response_item",
                            "payload": {
                                "type": "function_call",
                                "call_id": close_call_id,
                                "name": "close_agent",
                                "namespace": "multi_agent_v1",
                                "arguments": json.dumps(close_args, ensure_ascii=False),
                            },
                        })
                        # close_agent output
                        close_output = json.dumps({"previous_status": {"completed": output_str[:200]}})
                        events.append({
                            "timestamp": timestamp,
                            "type": "response_item",
                            "payload": {
                                "type": "function_call_output",
                                "call_id": close_call_id,
                                "output": close_output,
                            },
                        })
                        _emit_desktop_token_count(events, timestamp, model)
                    else:
                        mapped_call_id = desktop_call_id_map.get(original_call_id, original_call_id)
                        # Check if this is an apply_patch result
                        patch_content = desktop_apply_patch_calls.pop(mapped_call_id, None)
                        if patch_content is not None:
                            raw_output = part.get("content")
                            output_str = str(raw_output or "") if not isinstance(raw_output, str) else raw_output
                            is_error = bool(part.get("is_error"))
                            success = not is_error
                            # custom_tool_call_output
                            events.append({
                                "timestamp": timestamp,
                                "type": "response_item",
                                "payload": {
                                    "type": "custom_tool_call_output",
                                    "call_id": mapped_call_id,
                                    "output": output_str,
                                },
                            })
                            # Parse file paths from patch for patch_apply_end
                            patch_changes = {}
                            for line in patch_content.split("\n"):
                                if line.startswith("*** Update File: ") or line.startswith("*** Add File: "):
                                    fpath = line.split(": ", 1)[-1].strip()
                                    change_type = "update" if "Update" in line else "add"
                                    patch_changes[fpath] = {"type": change_type, "unified_diff": "", "move_path": None}
                            if not patch_changes:
                                for line in patch_content.split("\n"):
                                    if line.startswith("*** "):
                                        parts = line.split(" ")
                                        if len(parts) >= 3:
                                            fpath = " ".join(parts[2:]).strip()
                                            patch_changes[fpath] = {"type": "update", "unified_diff": "", "move_path": None}
                            stdout_msg = output_str if success else ""
                            events.append({
                                "timestamp": timestamp,
                                "type": "event_msg",
                                "payload": {
                                    "type": "patch_apply_end",
                                    "call_id": mapped_call_id,
                                    "turn_id": turn_id,
                                    "stdout": stdout_msg,
                                    "stderr": "" if success else output_str,
                                    "success": success,
                                    "changes": patch_changes,
                                    "status": "completed" if success else "failed",
                                },
                            })
                        else:
                            mapped_call_id = desktop_call_id_map.get(original_call_id, original_call_id)
                            raw_output = part.get("content")
                            output_str = str(raw_output or "") if not isinstance(raw_output, str) else raw_output
                            token_est = max(1, len(output_str) // 4)
                            wall_time = round(random.uniform(0.1, 2.0), 2)
                            wrapped = (
                                f"Chunk ID: {_desktop_chunk_id()}\n"
                                f"Wall time: {wall_time} seconds\n"
                                f"Process exited with code 0\n"
                                f"Original token count: {token_est}\n"
                                f"Output:\n{output_str}"
                            )
                            payload = {
                                "type": "function_call_output",
                                "call_id": mapped_call_id,
                                "output": wrapped,
                            }
                            desktop_pending_token_count = True
                else:
                    payload = {
                        "type": "function_call_output",
                        "call_id": original_call_id,
                        "output": part.get("content"),
                    }
                if payload is not None:
                    if "is_error" in part:
                        payload["is_error"] = bool(part.get("is_error"))
                    events.append({
                        "timestamp": timestamp,
                        "type": "response_item",
                        "payload": payload,
                    })
            elif part_type == "todo_state":
                # Skip todo_state in desktop compat; pass through as metadata otherwise
                if not codex_desktop_compat:
                    converted = _rollout_message_part(part)
                    if converted:
                        message_content.append(converted)
            else:
                converted = _rollout_message_part(part, role=role, codex_desktop_compat=codex_desktop_compat)
                if converted is not None:
                    message_content.append(converted)
                    if codex_desktop_compat and role == "assistant" and converted.get("type") == "output_text":
                        assistant_text_for_commentary.append(converted.get("text", ""))
        flush_message_content()

        # Emit pending token_count after tool group at end of message
        if codex_desktop_compat and desktop_pending_token_count:
            desktop_pending_token_count = False
            _emit_desktop_token_count(events, timestamp, model)

        for compaction in compactions_after_message.get(message_index, []):
            events.extend(_codex_compaction_events(compaction, timestamp))

    archive_event = _codex_bridge_source_events_event(bridge.get("source_events") or [], events[-1]["timestamp"] if events else created_iso, source.get("app") or "")
    if archive_event:
        events.append(archive_event)

    # Desktop: emit task_complete at end
    if codex_desktop_compat:
        last_ts = events[-1]["timestamp"] if events else created_iso
        completed_at = int(_parse_datetime(last_ts).timestamp()) if _parse_datetime(last_ts) else started_at
        duration_ms = max(1000, (completed_at - started_at) * 1000)
        # Emit agent_message final_answer if last message was assistant text
        if messages:
            last_msg = messages[-1]
            if last_msg.get("role") == "assistant":
                last_text = _first_text(last_msg.get("parts")) or ""
                if last_text:
                    events.append({
                        "timestamp": last_ts,
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "message": last_text[:500],
                            "phase": "final_answer",
                            "memory_citation": None,
                        },
                    })
        events.append({
            "timestamp": last_ts,
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": turn_id,
                "completed_at": completed_at,
                "duration_ms": duration_ms,
            },
        })

    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _validate_codex_rollout(path, expected_id, expected_messages, codex_desktop_compat=False):
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
    expected = expected_messages
    if codex_desktop_compat:
        expected += 2  # developer message + environment context message
    if message_count < expected:
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


def _upsert_codex_session_index(codex_dir, session_id, title, updated_ms):
    path = Path(codex_dir) / "session_index.jsonl"
    entry = {
        "id": session_id,
        "thread_name": title or session_id,
        "updated_at": _iso(_dt_from_ms(updated_ms)),
    }
    entries = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except Exception:
                entries.append(None)
                continue
            if existing.get("id") != session_id:
                entries.append(existing)
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in entries:
            if item is not None:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")


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
    for jsonl_path in sorted(sessions_dir.rglob("*.jsonl")):
        session_id = jsonl_path.stem
        title = session_id
        message_count = 0
        cwd = ""
        try:
            with jsonl_path.open("r", encoding="utf-8") as handle:
                for line_index, raw_line in enumerate(handle):
                    if not raw_line.strip():
                        continue
                    event = json.loads(raw_line)
                    if line_index == 0 and event.get("type") == "session_start":
                        title = event.get("title") or title
                        title = event.get("sessionTitle") or title
                        session_id = event.get("id") or session_id
                        cwd = event.get("cwd") or ""
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
            "settings_path": str(jsonl_path.with_suffix(".settings.json")),
            "cwd": idx.get("cwd") or cwd,
        })
    sessions.sort(key=lambda item: item.get("mtime") or 0, reverse=True)
    return sessions


def find_droid_session_paths(factory_home, session_id):
    factory_home = Path(factory_home)
    sessions_dir = factory_home / "sessions"
    session_id = str(session_id or "")
    if not session_id or not sessions_dir.exists():
        return None, None

    direct_path = sessions_dir / f"{session_id}.jsonl"
    if direct_path.exists():
        return direct_path, direct_path.with_suffix(".settings.json")

    for jsonl_path in sessions_dir.rglob(f"{session_id}.jsonl"):
        return jsonl_path, jsonl_path.with_suffix(".settings.json")

    for jsonl_path in sessions_dir.rglob("*.jsonl"):
        try:
            with jsonl_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    if not raw_line.strip():
                        continue
                    event = json.loads(raw_line)
                    if event.get("type") == "session_start" and str(event.get("id") or "") == session_id:
                        return jsonl_path, jsonl_path.with_suffix(".settings.json")
                    break
        except Exception:
            continue
    return None, None


def _upsert_mapping(root, pair):
    data = _load_mapping(root)
    pairs = list(data.get("pairs", []))
    pair = dict(pair)
    pair.setdefault("import_id", str(uuid.uuid4()))
    pairs.append(pair)
    data["pairs"] = pairs
    return _save_mapping(root, data)


def _mapping_roots_key(root):
    try:
        return str(Path(root))
    except Exception:
        return str(root or "")


def _merge_mapping_pairs(*roots):
    merged = []
    by_import_id = {}
    by_pair = {}

    def mark_conflict(index, import_id):
        pair = merged[index]
        pair["mapping_conflict"] = True
        pair["mapping_conflict_reason"] = "same import_id has different session IDs"
        ids = pair.setdefault("mapping_conflict_import_ids", [])
        if import_id and import_id not in ids:
            ids.append(import_id)

    for root in roots:
        root_text = _mapping_roots_key(root)
        for raw_pair in _load_mapping(root).get("pairs", []):
            if not isinstance(raw_pair, dict):
                continue
            codex_id = str(raw_pair.get("codex_session_id") or "")
            droid_id = str(raw_pair.get("droid_session_id") or "")
            if not codex_id and not droid_id:
                continue
            import_id = str(raw_pair.get("import_id") or "")
            pair_key = (codex_id, droid_id)
            import_indexes = by_import_id.get(import_id, []) if import_id else []
            index = None
            for candidate in import_indexes:
                candidate_pair = merged[candidate]
                candidate_key = (candidate_pair.get("codex_session_id") or "", candidate_pair.get("droid_session_id") or "")
                if candidate_key == pair_key:
                    index = candidate
                    break
            conflict_indexes = []
            if index is None and import_indexes:
                conflict_indexes = list(import_indexes)
            if index is None:
                index = by_pair.get(pair_key)
            if index is None:
                pair = dict(raw_pair)
                pair["codex_session_id"] = codex_id
                pair["droid_session_id"] = droid_id
                pair["mapping_roots"] = [root_text]
                index = len(merged)
                if conflict_indexes:
                    pair["mapping_conflict"] = True
                    pair["mapping_conflict_reason"] = "same import_id has different session IDs"
                    pair["mapping_conflict_import_ids"] = [import_id]
                    for conflict_index in conflict_indexes:
                        mark_conflict(conflict_index, import_id)
                merged.append(pair)
            else:
                pair = merged[index]
                if import_id and not pair.get("import_id"):
                    pair["import_id"] = import_id
                if raw_pair.get("bridge_id") and not pair.get("bridge_id"):
                    pair["bridge_id"] = raw_pair.get("bridge_id")
                if raw_pair.get("source_app") and not pair.get("source_app"):
                    pair["source_app"] = raw_pair.get("source_app")
                roots_seen = pair.setdefault("mapping_roots", [])
                if root_text not in roots_seen:
                    roots_seen.append(root_text)

            if import_id:
                indexes = by_import_id.setdefault(import_id, [])
                if index not in indexes:
                    indexes.append(index)
            by_pair[pair_key] = index

    return merged


def _raw_int(value, default=0):
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return int(default)
    if raw <= 0:
        return int(default)
    return int(raw)


def _seconds_or_ms(value, default=0):
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return int(default)
    if raw <= 0:
        return int(default)
    if raw > 100000000000:
        return int(raw)
    return int(raw * 1000)


def _codex_row_updated_ms(row):
    if not isinstance(row, dict):
        return 0
    if row.get("updated_at_ms") is not None:
        return _raw_int(row.get("updated_at_ms"), 0)
    return _seconds_or_ms(row.get("updated_at"), 0)


def _droid_session_updated_ms(session):
    if not isinstance(session, dict):
        return 0
    if session.get("updated_at_ms") is not None:
        return _raw_int(session.get("updated_at_ms"), 0)
    return _seconds_or_ms(session.get("mtime"), 0)


def _mirror_action(status):
    return {
        "mapping_conflict": "none",
        "codex_newer": "would_export_to_droid",
        "droid_newer": "would_import_to_codex",
        "missing_droid": "would_create_droid",
        "missing_codex": "would_create_codex",
        "in_sync": "none",
        "stale_pair": "none",
    }.get(status, "none")


def _row_matches_project(row, project):
    if not project:
        return True
    if not isinstance(row, dict):
        return False
    needle = str(project or "").lower()
    haystack = " ".join(str(row.get(key) or "") for key in ("cwd", "project", "rollout_path")).lower()
    return needle in haystack


def build_mirror_plan(codex_root, factory_home, codex_rows, droid_sessions, timestamp_tolerance_ms=1000, project=None):
    codex_index = {str(row.get("id") or ""): row for row in (codex_rows or []) if isinstance(row, dict) and row.get("id")}
    droid_index = {str(session.get("id") or ""): session for session in (droid_sessions or []) if isinstance(session, dict) and session.get("id")}
    items = []
    statuses = {}

    for pair in _merge_mapping_pairs(codex_root, factory_home):
        codex_id = str(pair.get("codex_session_id") or "")
        droid_id = str(pair.get("droid_session_id") or "")
        codex_row = codex_index.get(codex_id)
        droid_session = droid_index.get(droid_id)
        codex_updated_ms = _codex_row_updated_ms(codex_row)
        droid_updated_ms = _droid_session_updated_ms(droid_session)

        if project and not _row_matches_project(codex_row, project):
            continue

        if pair.get("mapping_conflict"):
            status = "mapping_conflict"
        elif not codex_row and not droid_session:
            status = "stale_pair"
        elif not codex_row:
            status = "missing_codex"
        elif not droid_session:
            status = "missing_droid"
        else:
            delta_ms = codex_updated_ms - droid_updated_ms
            if abs(delta_ms) <= int(timestamp_tolerance_ms):
                status = "in_sync"
            elif delta_ms > 0:
                status = "codex_newer"
            else:
                status = "droid_newer"

        delta_ms = codex_updated_ms - droid_updated_ms if codex_updated_ms and droid_updated_ms else None
        statuses[status] = statuses.get(status, 0) + 1
        items.append({
            "import_id": pair.get("import_id") or "",
            "bridge_id": pair.get("bridge_id") or "",
            "source_app": pair.get("source_app") or "",
            "codex_session_id": codex_id,
            "droid_session_id": droid_id,
            "status": status,
            "action": _mirror_action(status),
            "read_only": True,
            "codex_present": bool(codex_row),
            "droid_present": bool(droid_session),
            "codex_updated_at_ms": codex_updated_ms,
            "droid_updated_at_ms": droid_updated_ms,
            "delta_ms": delta_ms,
            "codex_title": (codex_row or {}).get("title") or "",
            "droid_title": (droid_session or {}).get("title") or "",
            "codex_cwd": (codex_row or {}).get("cwd") or "",
            "codex_rollout_path": (codex_row or {}).get("rollout_path") or "",
            "droid_jsonl_path": (droid_session or {}).get("jsonl_path") or "",
            "mapping_roots": list(pair.get("mapping_roots") or []),
            "mapping_conflict": bool(pair.get("mapping_conflict")),
            "mapping_conflict_reason": pair.get("mapping_conflict_reason") or "",
            "mapping_conflict_import_ids": list(pair.get("mapping_conflict_import_ids") or []),
        })

    return {
        "version": 1,
        "kind": "chat_bridge_mirror_plan",
        "read_only": True,
        "generated_at": _iso(_utc_now()),
        "summary": {
            "total_pairs": len(items),
            "statuses": statuses,
            "codex_root": str(Path(codex_root)),
            "factory_home": str(Path(factory_home)),
            "project": str(project or ""),
        },
        "items": items,
    }


def _mirror_direction_for_status(status, direction):
    normalized = str(direction or "newer").replace("_", "-").lower()
    status = str(status or "")
    if normalized == "newer":
        if status in ("codex_newer", "missing_droid"):
            return "codex_to_droid"
        if status in ("droid_newer", "missing_codex"):
            return "droid_to_codex"
        return ""
    if normalized == "codex-to-droid":
        return "codex_to_droid" if status in ("codex_newer", "missing_droid") else ""
    if normalized == "droid-to-codex":
        return "droid_to_codex" if status in ("droid_newer", "missing_codex") else ""
    raise ValueError(f"unsupported mirror direction: {direction}")


def _normal_set(values):
    if not values:
        return set()
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",")]
    return {str(value).strip() for value in values if str(value).strip()}


def _ambiguous_mirror_ids(items):
    codex_counts = {}
    droid_counts = {}
    for item in items:
        codex_id = str(item.get("codex_session_id") or "")
        droid_id = str(item.get("droid_session_id") or "")
        if codex_id:
            codex_counts[codex_id] = codex_counts.get(codex_id, 0) + 1
        if droid_id:
            droid_counts[droid_id] = droid_counts.get(droid_id, 0) + 1
    return {
        "codex": {session_id for session_id, count in codex_counts.items() if count > 1},
        "droid": {session_id for session_id, count in droid_counts.items() if count > 1},
    }


def _already_applied_mirror_items(items):
    applied_codex_ids = set()
    applied_droid_ids = set()
    for item in items:
        source_app = str(item.get("source_app") or "")
        bridge_id = str(item.get("bridge_id") or "")
        codex_id = str(item.get("codex_session_id") or "")
        droid_id = str(item.get("droid_session_id") or "")
        if source_app == "codex" and codex_id and bridge_id == _bridge_id("codex", codex_id):
            applied_codex_ids.add(codex_id)
        if source_app == "droid" and droid_id and bridge_id == _bridge_id("droid", droid_id):
            applied_droid_ids.add(droid_id)
    return {"codex": applied_codex_ids, "droid": applied_droid_ids}


def select_mirror_actions(plan, direction="newer", session_ids=None, statuses=None, limit=None):
    items = [item for item in (plan.get("items") if isinstance(plan, dict) else []) or [] if isinstance(item, dict)]
    ambiguous = _ambiguous_mirror_ids(items)
    already_applied = _already_applied_mirror_items(items)
    session_filter = _normal_set(session_ids)
    status_filter = _normal_set(statuses)
    limit = int(limit) if limit not in (None, "") else None
    selected = []
    skipped = []
    for item in items:
        action = _mirror_direction_for_status(item.get("status"), direction)
        codex_id = str(item.get("codex_session_id") or "")
        droid_id = str(item.get("droid_session_id") or "")
        if session_filter and codex_id not in session_filter and droid_id not in session_filter:
            skipped_item = dict(item)
            skipped_item["skip_reason"] = "session_filter"
            skipped.append(skipped_item)
            continue
        if status_filter and str(item.get("status") or "") not in status_filter:
            skipped_item = dict(item)
            skipped_item["skip_reason"] = "status_filter"
            skipped.append(skipped_item)
            continue
        if (action == "codex_to_droid" and codex_id in already_applied["codex"]) or (action == "droid_to_codex" and droid_id in already_applied["droid"]):
            skipped_item = dict(item)
            skipped_item["skip_reason"] = "already_applied"
            skipped.append(skipped_item)
            continue
        if codex_id in ambiguous["codex"] or droid_id in ambiguous["droid"]:
            skipped_item = dict(item)
            skipped_item["skip_reason"] = "ambiguous_mapping"
            skipped.append(skipped_item)
            continue
        if not action:
            skipped_item = dict(item)
            skipped_item["skip_reason"] = "not_actionable"
            skipped.append(skipped_item)
            continue
        if limit is not None and len(selected) >= limit:
            skipped_item = dict(item)
            skipped_item["skip_reason"] = "limit"
            skipped.append(skipped_item)
            continue
        selected_item = dict(item)
        selected_item["apply_direction"] = action
        selected.append(selected_item)
    return {
        "version": 1,
        "kind": "chat_bridge_mirror_actions",
        "read_only": True,
        "direction": str(direction or "newer"),
        "summary": {
            "selected": len(selected),
            "skipped": len(skipped),
        },
        "items": selected,
        "skipped": skipped,
    }


def _bridge_current_context(bridge):
    work = bridge.get("work_context") if isinstance(bridge.get("work_context"), dict) else {}
    current = work.get("current") if isinstance(work.get("current"), dict) else {}
    return work, current


def _bridge_message_signature(messages):
    signature = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        parts = message.get("parts") if isinstance(message.get("parts"), list) else []
        parts = [
            part for part in parts
            if isinstance(part, dict)
            and part.get("type") != "todo_state"
            and not _is_codex_internal_part(part)
        ]
        if not parts:
            continue
        signature.append({
            "role": str(message.get("role") or ""),
            "parts": [str(part.get("type") or "") for part in parts],
        })
    return signature


def _bridge_metric_counts(bridge):
    bridge = bridge if isinstance(bridge, dict) else {}
    messages = bridge.get("messages") if isinstance(bridge.get("messages"), list) else []
    compactions = bridge.get("compactions") if isinstance(bridge.get("compactions"), list) else []
    source_events = bridge.get("source_events") if isinstance(bridge.get("source_events"), list) else []
    work, current = _bridge_current_context(bridge)
    session = bridge.get("session") if isinstance(bridge.get("session"), dict) else {}
    part_counts = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "")
            part_counts[part_type] = part_counts.get(part_type, 0) + 1
    signature = _bridge_message_signature(messages)
    return {
        "message_count": len(signature),
        "role_sequence": [item["role"] for item in signature],
        "part_type_sequence": [item["parts"] for item in signature],
        "part_counts": part_counts,
        "tool_call_count": part_counts.get("tool_call", 0),
        "tool_result_count": part_counts.get("tool_result", 0),
        "compaction_count": len(compactions),
        "source_event_count": len(source_events),
        "primary_cwd": _normalize_droid_cwd(work.get("primary_cwd") or current.get("cwd") or ""),
        "git_branch": str(current.get("git_branch") or ""),
        "git_sha": str(current.get("git_sha") or ""),
        "provider": str(session.get("provider") or ""),
        "model": str(session.get("model") or ""),
    }


def _doctor_issue(code, message, codex_value, droid_value, severity="warn"):
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "codex": codex_value,
        "droid": droid_value,
    }


def _sequence_has_prefix(longer, shorter):
    longer = longer if isinstance(longer, list) else []
    shorter = shorter if isinstance(shorter, list) else []
    return len(longer) >= len(shorter) and longer[:len(shorter)] == shorter


def _doctor_tools_preserved(codex_metrics, droid_metrics):
    return (
        int(codex_metrics.get("tool_call_count") or 0) >= int(droid_metrics.get("tool_call_count") or 0)
        and int(codex_metrics.get("tool_result_count") or 0) >= int(droid_metrics.get("tool_result_count") or 0)
    )


def diagnose_bridge_pair(codex_bridge, droid_bridge, codex_session_id="", droid_session_id=""):
    codex_metrics = _bridge_metric_counts(codex_bridge)
    droid_metrics = _bridge_metric_counts(droid_bridge)
    issues = []
    tools_preserved = _doctor_tools_preserved(codex_metrics, droid_metrics)

    for key, message in (
        ("message_count", "Message count differs"),
        ("tool_call_count", "Tool call count differs"),
        ("tool_result_count", "Tool result count differs"),
    ):
        codex_value = codex_metrics.get(key)
        droid_value = droid_metrics.get(key)
        if codex_value != droid_value:
            is_loss = int(codex_value or 0) < int(droid_value or 0)
            if key == "message_count" and is_loss and tools_preserved:
                is_loss = False
            severity = "error" if is_loss else "warn"
            issues.append(_doctor_issue(key, message, codex_value, droid_value, severity=severity))

    for key, message in (
        ("role_sequence", "Message role sequence differs"),
        ("part_type_sequence", "Message part type sequence differs"),
    ):
        codex_value = codex_metrics.get(key)
        droid_value = droid_metrics.get(key)
        if codex_value != droid_value and not _sequence_has_prefix(codex_value, droid_value):
            has_codex_expansion = any(
                int(codex_metrics.get(count_key) or 0) > int(droid_metrics.get(count_key) or 0)
                for count_key in ("message_count", "tool_call_count", "tool_result_count")
            )
            has_message_split = codex_metrics.get("message_count") != droid_metrics.get("message_count") and tools_preserved
            severity = "warn" if has_codex_expansion or has_message_split else "error"
            issues.append(_doctor_issue(key, message, codex_value, droid_value, severity=severity))

    for key, message in (
        ("compaction_count", "Compaction count differs"),
        ("source_event_count", "Source event count differs"),
    ):
        if codex_metrics.get(key) != droid_metrics.get(key):
            issues.append(_doctor_issue(key, message, codex_metrics.get(key), droid_metrics.get(key), severity="expected"))

    for key, message in (
        ("primary_cwd", "Primary cwd differs"),
        ("git_branch", "Git branch differs"),
        ("git_sha", "Git sha differs"),
        ("provider", "Provider differs"),
        ("model", "Model differs"),
    ):
        codex_value = codex_metrics.get(key)
        droid_value = droid_metrics.get(key)
        if (
            key == "provider"
            and codex_value
            and droid_value
            and _canonical_droid_provider(codex_value, codex_metrics.get("model")) == _canonical_droid_provider(droid_value, droid_metrics.get("model"))
        ):
            continue
        if (
            key == "model"
            and codex_value
            and droid_value
            and _canonical_model(codex_value) == _canonical_model(droid_value)
        ):
            continue
        if (codex_value or droid_value) and codex_value != droid_value:
            severity = "expected" if key == "git_branch" else "warn"
            issues.append(_doctor_issue(key, message, codex_value, droid_value, severity=severity))
    has_errors = any(issue.get("severity") == "error" for issue in issues)
    return {
        "version": 1,
        "kind": "chat_bridge_doctor_pair",
        "read_only": True,
        "codex_session_id": str(codex_session_id or ""),
        "droid_session_id": str(droid_session_id or ""),
        "status": "error" if has_errors else ("warn" if issues else "ok"),
        "metrics": {
            "codex": codex_metrics,
            "droid": droid_metrics,
        },
        "issues": issues,
    }


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
    compaction_mode="archived",
    target_provider=None,
    target_model=None,
    codex_desktop_compat=False,
):
    validate_bridge(bridge)
    compaction_mode = _normalize_compaction_mode(compaction_mode)
    codex_dir = Path(codex_dir)
    state_db = Path(state_db)
    sessions_dir = Path(sessions_dir)
    source = bridge["source"]
    session = bridge["session"]
    model_provider = target_provider or session.get("provider") or ""
    model = target_model or session.get("model") or ""
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

    codex_id = _new_codex_thread_id()
    date_dir = sessions_dir / f"{_dt_from_ms(created_ms).year:04d}" / f"{_dt_from_ms(created_ms).month:02d}" / f"{_dt_from_ms(created_ms).day:02d}"
    date_dir.mkdir(parents=True, exist_ok=True)
    if codex_desktop_compat:
        ts_str = _dt_from_ms(created_ms).strftime("%Y-%m-%dT%H-%M-%SZ")
        final_path = date_dir / f"rollout-{ts_str}-{codex_id}.jsonl"
    else:
        final_path = date_dir / f"rollout-{codex_id}.jsonl"
    fd, tmp_name = tempfile.mkstemp(prefix=f"rollout-{codex_id}.", suffix=".tmp", dir=str(date_dir))
    tmp_path = Path(tmp_name)
    conn = None
    committed = False
    raw_replay = ""
    try:
        if compaction_mode == "raw" and not codex_desktop_compat:
            raw_replay = _render_codex_raw_replay(bridge, codex_id, created_ms, target_provider=model_provider, target_model=model)
        rollout_text = raw_replay or _render_codex_rollout(
            bridge,
            codex_id,
            created_ms,
            updated_ms,
            preserve_message_timestamps=preserve_timestamps,
            compaction_mode=compaction_mode,
            target_provider=model_provider,
            target_model=model,
            codex_desktop_compat=codex_desktop_compat,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rollout_text)
        fd = None
        _validate_codex_rollout(tmp_path, codex_id, 0 if raw_replay else len(bridge.get("messages", [])), codex_desktop_compat=codex_desktop_compat)
        tmp_path.replace(final_path)
        row = {
            "id": codex_id,
            "rollout_path": str(final_path),
            "created_at": created_ms // 1000,
            "updated_at": updated_ms // 1000,
            "source": CODEX_DESKTOP_SOURCE if codex_desktop_compat else "chat_bridge",
            "model_provider": model_provider,
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
            "cli_version": CODEX_DESKTOP_CLI_VERSION if codex_desktop_compat else "",
            "first_user_message": _first_user_text(bridge.get("messages")),
            "agent_nickname": None,
            "agent_role": None,
            "memory_mode": "enabled",
            "model": model,
            "reasoning_effort": session.get("reasoning_effort") or None,
            "agent_path": None,
            "created_at_ms": created_ms,
            "updated_at_ms": updated_ms,
            "thread_source": CODEX_DESKTOP_THREAD_SOURCE if codex_desktop_compat else "chat_bridge",
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
        meta = _validate_codex_rollout(final_path, codex_id, 0 if raw_replay else len(bridge.get("messages", [])), codex_desktop_compat=codex_desktop_compat)
        payload = meta.get("payload") or {}
        provider_match = payload.get("model_provider") == verified["model_provider"]
        model_match = payload.get("model") == verified["model"] or codex_desktop_compat
        if not provider_match or not model_match:
            raise ValueError("Codex import verification failed: provider/model mismatch")
        _upsert_codex_session_index(codex_dir, codex_id, row["title"], updated_ms)

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
    if part_type == "reasoning":
        return _droid_thinking_part(part)
    if part_type == "tool_call":
        return {"type": "tool_use", "id": part.get("id") or "", "name": part.get("name") or "", "input": _droid_tool_input(part.get("input"))}
    if part_type == "tool_result":
        result = {
            "type": "tool_result",
            "tool_use_id": str(part.get("tool_call_id") or ""),
            "content": _normalize_droid_tool_result_content(part.get("content")),
        }
        if "is_error" in part:
            result["is_error"] = bool(part.get("is_error"))
        return result
    return {"type": "text", "text": f"[unsupported bridge part: {part_type}]"}


def _json_diagnostic_text(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _droid_image_from_data_url(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"data:(image/(?:jpeg|jpg|png|gif|webp));base64,([A-Za-z0-9+/=\s]+)", value.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    media_type = match.group(1).lower()
    if media_type == "image/jpg":
        media_type = "image/jpeg"
    encoded = re.sub(r"\s+", "", match.group(2))
    try:
        base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "data": encoded,
            "media_type": media_type,
        },
    }


def _normalize_droid_image_block(value):
    if not isinstance(value, dict):
        return None
    image_url = value.get("image_url")
    if isinstance(image_url, dict):
        image_url = image_url.get("url")
    image = _droid_image_from_data_url(image_url or value.get("url"))
    if image:
        return image
    source = value.get("source") if isinstance(value.get("source"), dict) else {}
    media_type = str(source.get("media_type") or source.get("mediaType") or "").lower()
    if media_type == "image/jpg":
        media_type = "image/jpeg"
    data = source.get("data")
    if source.get("type") != "base64" or media_type not in DROID_IMAGE_MEDIA_TYPES or not isinstance(data, str):
        return None
    encoded = re.sub(r"\s+", "", data)
    try:
        base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "data": encoded,
            "media_type": media_type,
        },
    }


def _normalize_droid_tool_result_block(value):
    if isinstance(value, str):
        return {"type": "text", "text": value}
    if not isinstance(value, dict):
        return {"type": "text", "text": _json_diagnostic_text(value)}
    part_type = str(value.get("type") or "")
    if part_type in ("input_image", "image"):
        image = _normalize_droid_image_block(value)
        if image:
            return image
    if part_type in ("text", "input_text", "output_text"):
        return {"type": "text", "text": str(value.get("text") or "")}
    return {"type": "text", "text": _json_diagnostic_text(value)}


def _normalize_droid_tool_result_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_normalize_droid_tool_result_block(item) for item in value]
    if isinstance(value, dict):
        normalized = _normalize_droid_tool_result_block(value)
        if normalized.get("type") in ("text", "image") and value.get("type") in (
            "text",
            "input_text",
            "output_text",
            "input_image",
            "image",
        ):
            return [normalized]
    return _json_diagnostic_text(value)


def _droid_thinking_part(part):
    part = part if isinstance(part, dict) else {}
    summary = _reasoning_summary_list(part)
    summary_text = str(part.get("summary_text") or _reasoning_summary_text(summary) or "")
    encrypted_content = str(part.get("encrypted_content") or "")
    reasoning_id = str(part.get("reasoning_id") or "")
    result = {
        "type": "thinking",
        "thinking": str(part.get("text") or summary_text or ""),
    }
    signature = part.get("signature") if isinstance(part.get("signature"), str) else ""
    if not signature and (encrypted_content or summary or reasoning_id):
        signature_payload = {"type": "reasoning"}
        if reasoning_id:
            signature_payload["id"] = reasoning_id
        if encrypted_content:
            signature_payload["encrypted_content"] = encrypted_content
        if summary:
            signature_payload["summary"] = summary
        signature = json.dumps(signature_payload, ensure_ascii=False)
    result["signature"] = signature
    if part.get("signature_provider") or encrypted_content:
        result["signatureProvider"] = str(part.get("signature_provider") or "openai")
    if part.get("duration_ms") is not None:
        result["durationMs"] = _int_or_default(part.get("duration_ms"), 0)
    if encrypted_content:
        result["openaiEncryptedContent"] = encrypted_content
    if reasoning_id:
        result["openaiReasoningId"] = reasoning_id
    if summary_text:
        result["openaiReasoningSummary"] = summary_text
    return result


def _droid_bridge_source_event(source_event, index, source_app):
    source_event = source_event if isinstance(source_event, dict) else {}
    raw = source_event.get("raw") if isinstance(source_event.get("raw"), dict) else {}
    timestamp = source_event.get("timestamp") or raw.get("timestamp") or _iso(_utc_now())
    source_index = _int_or_default(source_event.get("index"), index)
    event_source_app = _bridge_source_app(source_event, source_app)
    return {
        "type": "bridge_source_event",
        "id": f"bridge-source-event-{source_index:06d}",
        "timestamp": _iso(_parse_datetime(timestamp) or _utc_now()),
        "source": event_source_app,
        "sourceIndex": source_index,
        "outerType": str(source_event.get("outer_type") or ""),
        "payloadType": str(source_event.get("payload_type") or ""),
        "representedBy": str(source_event.get("represented_by") or ""),
        "raw": raw,
    }


def _validate_droid_image_block(block, location):
    source = block.get("source") if isinstance(block.get("source"), dict) else {}
    if source.get("type") != "base64":
        raise ValueError(f"{location} image source must use base64")
    media_type = source.get("media_type")
    if media_type not in DROID_IMAGE_MEDIA_TYPES:
        raise ValueError(f"{location} image has unsupported media_type")
    data = source.get("data")
    if not isinstance(data, str):
        raise ValueError(f"{location} image data must be a string")
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{location} image data is not valid base64") from exc


def _validate_droid_document_block(block, location):
    source = block.get("source") if isinstance(block.get("source"), dict) else {}
    source_type = source.get("type")
    media_type = source.get("media_type")
    if source_type == "base64" and media_type == "application/pdf":
        if not isinstance(source.get("data", ""), str):
            raise ValueError(f"{location} PDF data must be a string")
        return
    if source_type == "text" and media_type == "text/plain":
        if not isinstance(source.get("data", ""), str):
            raise ValueError(f"{location} document data must be a string")
        return
    raise ValueError(f"{location} has unsupported document source")


def _validate_droid_content_block(block, location, tool_result_inner=False):
    if not isinstance(block, dict):
        raise ValueError(f"{location} must be an object")
    block_type = block.get("type")
    if block_type == "text":
        if not isinstance(block.get("text"), str):
            raise ValueError(f"{location} text must be a string")
        return
    if block_type == "image":
        _validate_droid_image_block(block, location)
        return
    if tool_result_inner:
        raise ValueError(f"{location} has unsupported tool result content type: {block_type}")
    if block_type == "thinking":
        if not isinstance(block.get("thinking"), str) or not isinstance(block.get("signature"), str):
            raise ValueError(f"{location} thinking and signature must be strings")
        if "signatureProvider" in block and not isinstance(block.get("signatureProvider"), str):
            raise ValueError(f"{location} signatureProvider must be a string")
        return
    if block_type == "redacted_thinking":
        if not isinstance(block.get("data"), str):
            raise ValueError(f"{location} redacted thinking data must be a string")
        return
    if block_type == "tool_use":
        if not isinstance(block.get("id"), str) or not isinstance(block.get("name"), str):
            raise ValueError(f"{location} tool id and name must be strings")
        if not isinstance(block.get("input"), dict):
            raise ValueError(f"{location} tool input must be an object")
        return
    if block_type == "tool_result":
        if not isinstance(block.get("tool_use_id"), str):
            raise ValueError(f"{location} tool_use_id must be a string")
        content = block.get("content")
        if isinstance(content, str):
            return
        if not isinstance(content, list):
            raise ValueError(f"{location} tool result content must be a string or list")
        for index, inner_block in enumerate(content):
            _validate_droid_content_block(inner_block, f"{location}.content[{index}]", tool_result_inner=True)
        return
    if block_type == "document":
        _validate_droid_document_block(block, location)
        return
    raise ValueError(f"{location} has unsupported content type: {block_type}")


def _validate_droid_events(events):
    if not isinstance(events, list) or not events:
        raise ValueError("Droid events must be a non-empty list")
    session_starts = [event for event in events if isinstance(event, dict) and event.get("type") == "session_start"]
    if len(session_starts) != 1 or events[0] is not session_starts[0]:
        raise ValueError("Droid events must start with exactly one session_start")
    if not isinstance(session_starts[0].get("id"), str) or not session_starts[0].get("id"):
        raise ValueError("Droid session_start id must be a non-empty string")

    message_ids = set()
    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"Droid event {event_index} must be an object")
        event_type = event.get("type")
        if event_type not in DROID_NATIVE_EVENT_TYPES:
            raise ValueError(f"Droid event {event_index} has unsupported type: {event_type}")
        if event_type != "message":
            continue
        message_id = event.get("id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError(f"Droid message {event_index} id must be a non-empty string")
        if message_id in message_ids:
            raise ValueError(f"Droid message id is duplicated: {message_id}")
        parent_id = event.get("parentId")
        if parent_id is not None and (not isinstance(parent_id, str) or parent_id not in message_ids):
            raise ValueError(f"Droid message {message_id} has invalid parentId")
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, str) or _parse_datetime(timestamp) is None:
            raise ValueError(f"Droid message {message_id} has invalid timestamp")
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        if message.get("role") not in ("user", "assistant"):
            raise ValueError(f"Droid message {message_id} has unsupported role")
        content = message.get("content")
        if not isinstance(content, list):
            raise ValueError(f"Droid message {message_id} content must be a list")
        for block_index, block in enumerate(content):
            _validate_droid_content_block(block, f"message {message_id} content[{block_index}]")
        message_ids.add(message_id)


def _droid_compaction_state_event(compaction, index):
    compaction = compaction if isinstance(compaction, dict) else {}
    timestamp = _iso(_parse_datetime(compaction.get("timestamp")) or _utc_now())
    event = {
        "type": "compaction_state",
        "id": str(compaction.get("id") or f"bridge-compaction-{index:06d}"),
        "timestamp": timestamp,
        "summaryText": str(compaction.get("summary_text") or ""),
        "summaryTokens": _int_or_default(compaction.get("summary_tokens"), 0),
        "summaryKind": str(compaction.get("summary_kind") or "llm_summary"),
        "removedCount": _int_or_default(
            compaction.get("removed_count"),
            len(compaction.get("replacement_history") or []) if isinstance(compaction.get("replacement_history"), list) else 0,
        ),
    }
    anchor_id = str(compaction.get("anchor_message_id") or "")
    anchor_index = _int_or_default(compaction.get("anchor_message_index"), -1)
    if anchor_id or anchor_index >= 0:
        anchor = {}
        if anchor_id:
            anchor["id"] = anchor_id
        if anchor_index >= 0:
            anchor["index"] = anchor_index
        event["anchorMessage"] = anchor
    if isinstance(compaction.get("system_info"), dict):
        event["systemInfo"] = compaction.get("system_info")
    if compaction.get("ui_render_cutoff_message_id"):
        event["uiRenderCutoffMessageId"] = str(compaction.get("ui_render_cutoff_message_id"))
    return event


def _message_is_droid_tool_result(message):
    if not isinstance(message, dict):
        return False
    if message.get("role") == "tool":
        return True
    parts = message.get("parts")
    return bool(parts) and all(isinstance(part, dict) and part.get("type") == "tool_result" for part in parts)


def _latest_compaction(compactions):
    best = None
    best_key = (-1, "")
    for index, compaction in enumerate(compactions or []):
        if not isinstance(compaction, dict):
            continue
        key = (_int_or_default(compaction.get("source_event_index"), index), str(compaction.get("timestamp") or ""))
        if key >= best_key:
            best = compaction
            best_key = key
    return best


def _droid_native_suffix_messages(messages, compaction):
    messages = list(messages or [])
    anchor = _compaction_anchor_index(compaction or {}, messages)
    start = max(0, anchor + 1)
    while start < len(messages) and _message_is_droid_tool_result(messages[start]):
        start += 1
    return messages[start:]


def _droid_anchorless_compaction(compaction):
    result = dict(compaction or {})
    result["anchor_message_id"] = ""
    result["anchor_message_index"] = -1
    return result


def _droid_raw_replay_events(bridge, droid_id, title, cwd="", host_id=""):
    events = _copy_raw_events_for_replay(bridge, "droid", "session_start")
    if not events:
        return []
    first = events[0]
    first["id"] = droid_id
    if title and not first.get("title"):
        first["title"] = title
    if title and not first.get("sessionTitle"):
        first["sessionTitle"] = title
    if cwd and not first.get("cwd"):
        first["version"] = first.get("version") or 2
        first["cwd"] = cwd
    if host_id and not first.get("hostId"):
        first["hostId"] = host_id
    return events


def _droid_tool_input(value):
    if isinstance(value, dict):
        return value
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {"raw": value}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return {"value": value}


def _droid_project_dir_name(cwd):
    text = _normalize_droid_cwd(cwd)
    if not text:
        return ""
    is_drive_path = len(text) >= 2 and text[1] == ":"
    if is_drive_path:
        text = text[0] + text[2:]
    chars = []
    for char in text:
        if char.isalnum() or char in ("_", ".", "-"):
            chars.append(char)
        elif char in (":", "\\", "/"):
            chars.append("-")
        else:
            chars.append("-")
    name = "-".join(part for part in "".join(chars).split("-") if part)
    if is_drive_path or str(cwd).startswith(("\\", "/")):
        name = f"-{name}"
    return name or ""


def _droid_root_sessions_dir(factory_home):
    return Path(factory_home) / "sessions"


def _normalize_droid_cwd(cwd):
    text = str(cwd or "").strip()
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[len("\\\\?\\UNC\\"):]
    if text.startswith("\\\\?\\"):
        return text[len("\\\\?\\"):]
    return text


def _droid_session_dir(factory_home, cwd):
    sessions_dir = _droid_root_sessions_dir(factory_home)
    project_name = _droid_project_dir_name(cwd)
    return sessions_dir / project_name if project_name else sessions_dir


def _droid_host_id(factory_home):
    data = _read_json_file(Path(factory_home) / "host.json")
    return str(data.get("hostId") or "")


def _canonical_model(model):
    text = str(model or "").strip()
    if text.lower().startswith("custom:"):
        text = text.split(":", 1)[1].strip()
    normalized = re.sub(r"[\s_]+", "-", text.casefold())
    match = re.search(r"(gpt-\d+(?:\.\d+)?(?:-[a-z]+)?)", normalized)
    if match:
        return match.group(1)
    return normalized


def _canonical_droid_provider(provider, model):
    text = str(provider or "").strip()
    lower = text.lower().replace("-", "_")
    known = {
        "openai": "openai",
        "anthropic": "anthropic",
        "google": "google",
        "gemini": "google",
        "xai": "xai",
        "groq": "groq",
        "mistral": "mistral",
        "deepseek": "deepseek",
        "openrouter": "openrouter",
        "ollama": "ollama",
    }
    if lower in known:
        return known[lower]
    if "anthropic" in lower or "claude" in lower:
        return "anthropic"
    if "openai" in lower or "neurogate" in lower:
        return "openai"

    model_text = str(model or "").strip().lower()
    if model_text.startswith(("gpt-", "o1", "o3", "o4", "o5")):
        return "openai"
    if model_text.startswith("claude"):
        return "anthropic"
    if model_text.startswith("gemini"):
        return "google"
    return text


def _resolve_droid_session_settings(factory_home, session, timestamp, target_provider=None, target_model=None):
    session = session if isinstance(session, dict) else {}
    session_model = str(session.get("model") or "")
    session_provider = str(session.get("provider") or "")
    session_reasoning = str(session.get("reasoning_effort") or session.get("reasoningEffort") or "")
    droid_settings = _bridge_droid_settings({"extras": session.get("extras")}) if isinstance(session.get("extras"), dict) else {}
    models = []
    effective_settings = {}
    try:
        import droid_provider_adapter as droid

        ctx = droid.load_factory_context(factory_home)
        models = ctx.get("models") or []
        effective_settings = ctx.get("settings") if isinstance(ctx.get("settings"), dict) else {}
    except Exception:
        models = []
        effective_settings = {}

    effective_model = target_model or session_model
    match = None
    for model in models:
        if str(model.get("id") or "") == effective_model:
            match = model
            break
    if match is None and effective_model:
        for model in models:
            if str(model.get("model") or "") != effective_model:
                continue
            model_provider = str(model.get("provider") or "")
            if not session_provider or not model_provider or model_provider == session_provider:
                match = model
                break
    if match is None and not target_model and session_model:
        for model in models:
            if str(model.get("id") or "") == session_model:
                match = model
                break
        if match is None:
            for model in models:
                if str(model.get("model") or "") != session_model:
                    continue
                model_provider = str(model.get("provider") or "")
                if not session_provider or not model_provider or model_provider == session_provider:
                    match = model
                    break

    defaults = effective_settings.get("sessionDefaultSettings") if isinstance(effective_settings.get("sessionDefaultSettings"), dict) else {}
    selected_model = str((match or {}).get("id") or effective_model)
    selected_model_name = str((match or {}).get("model") or effective_model)
    if target_provider:
        provider_lock = _canonical_droid_provider(target_provider, target_model or selected_model_name)
    else:
        provider_lock = str((match or {}).get("provider") or _canonical_droid_provider(session_provider, selected_model_name) or "")
    reasoning = str(session_reasoning or (match or {}).get("reasoningEffort") or defaults.get("reasoningEffort") or effective_settings.get("reasoningEffort") or "")
    settings = {
        "assistantActiveTimeMs": _int_or_default(droid_settings.get("assistantActiveTimeMs"), 0) if "assistantActiveTimeMs" in droid_settings else 0,
        "providerLockTimestamp": droid_settings.get("providerLockTimestamp") or timestamp,
        "tokenUsage": droid_settings.get("tokenUsage") if isinstance(droid_settings.get("tokenUsage"), dict) else {},
    }
    if selected_model:
        settings["model"] = selected_model
    if reasoning:
        settings["reasoningEffort"] = reasoning
    if provider_lock:
        settings["providerLock"] = provider_lock
    return settings


def _file_mtime_ms(path):
    return int(Path(path).stat().st_mtime * 1000)


def _update_droid_discovery_index(
    factory_home,
    session_id,
    title,
    jsonl_path,
    settings_path,
    message_count,
    cwd="",
    created_ms=None,
    modified_ms=None,
):
    factory_home = Path(factory_home)
    cache_dir = factory_home / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_path = cache_dir / "session-discovery-index.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except Exception:
        data = {}
    data["version"] = int(data.get("version") or 1)
    sessions_root = factory_home / "sessions"
    data["sessionsDir"] = str(sessions_root)
    data["updatedAt"] = int(_utc_now().timestamp() * 1000)
    if not isinstance(data.get("projectDirectories"), list):
        data["projectDirectories"] = []
    if not isinstance(data.get("directories"), dict):
        data["directories"] = {}
    entries = data.get("entries") if isinstance(data.get("entries"), dict) else {}
    jsonl_path = Path(jsonl_path)
    settings_path = Path(settings_path)
    mtime_ms = int(modified_ms) if modified_ms is not None else _file_mtime_ms(jsonl_path)
    created_time_ms = int(created_ms) if created_ms is not None else mtime_ms
    settings_mtime_ms = _file_mtime_ms(settings_path)
    entry = {
        "id": session_id,
        "sessionPath": str(jsonl_path),
        "directoryPath": str(jsonl_path.parent),
        "title": title,
        "sessionTitle": title,
        "owner": "codex-provider-manager",
        "messageCount": message_count,
        "modifiedTimeMs": mtime_ms,
        "createdTimeMs": created_time_ms,
        "isExec": False,
        "isBtwFork": False,
        "sessionFingerprint": {
            "mtimeMs": mtime_ms,
            "size": jsonl_path.stat().st_size,
        },
        "settingsFingerprint": {
            "mtimeMs": settings_mtime_ms,
            "size": settings_path.stat().st_size,
        },
    }
    if cwd:
        entry["cwd"] = str(cwd)
    entries[session_id] = entry
    data["entries"] = entries
    directory_path = str(jsonl_path.parent)
    data["directories"][directory_path] = {
        "sessionFiles": sorted(path.name for path in jsonl_path.parent.glob("*.jsonl")),
    }
    root_path = str(sessions_root)
    if root_path not in data["directories"]:
        data["directories"][root_path] = {
            "sessionFiles": sorted(path.name for path in sessions_root.glob("*.jsonl")),
        }
    if jsonl_path.parent != sessions_root:
        data["projectDirectories"] = sorted(set(data["projectDirectories"]) | {directory_path})
    if not isinstance(data.get("favorites"), dict):
        data["favorites"] = {"exists": False, "sessionIds": []}
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _update_droid_index(
    factory_home,
    session_id,
    title,
    jsonl_path,
    settings_path,
    message_count,
    cwd="",
    host_id="",
    created_ms=None,
    modified_ms=None,
):
    index_path = Path(factory_home) / "sessions-index.json"
    try:
        data = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    except Exception:
        data = {}
    data["version"] = int(data.get("version") or 1)
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    entries = [entry for entry in entries if entry.get("sessionId") != session_id]
    entry = {
        "sessionId": session_id,
        "mtime": int(modified_ms) if modified_ms is not None else _file_mtime_ms(jsonl_path),
        "settingsMtime": _file_mtime_ms(settings_path),
        "title": title,
        "messagesCount": message_count,
    }
    if cwd:
        entry["cwd"] = str(cwd)
    if host_id:
        entry["hostId"] = str(host_id)
    entries.append(entry)
    data["entries"] = entries
    if index_path.exists():
        backup_path = index_path.with_name(f"{index_path.name}.{int(_utc_now().timestamp())}.bak")
        try:
            shutil.copy2(index_path, backup_path)
        except OSError:
            pass
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    _update_droid_discovery_index(
        factory_home,
        session_id,
        title,
        jsonl_path,
        settings_path,
        message_count,
        cwd,
        created_ms=created_ms,
        modified_ms=modified_ms,
    )


def import_bridge_to_droid(bridge, factory_home, preserve_timestamps=True, compaction_mode="archived", target_provider=None, target_model=None, mirror_to_root=True):
    validate_bridge(bridge)
    compaction_mode = _normalize_compaction_mode(compaction_mode)
    factory_home = Path(factory_home)
    work = bridge.get("work_context") if isinstance(bridge.get("work_context"), dict) else {}
    current = work.get("current") if isinstance(work.get("current"), dict) else {}
    cwd = _normalize_droid_cwd(work.get("primary_cwd") or current.get("cwd") or "")
    droid_session_start = _bridge_droid_session_start(bridge)
    original_host_id = str(droid_session_start.get("hostId") or "")
    host_id = original_host_id or (_droid_host_id(factory_home) if cwd else "")
    sessions_dir = _droid_session_dir(factory_home, cwd)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    source = bridge["source"]
    session = bridge["session"]
    session_with_extras = dict(session)
    session_with_extras["extras"] = _bridge_extras(bridge)
    droid_id = _new_id("bridge-droid")
    jsonl_path = sessions_dir / f"{droid_id}.jsonl"
    settings_path = sessions_dir / f"{droid_id}.settings.json"
    archive_path = _droid_source_archive_path(jsonl_path)
    jsonl_tmp = None
    settings_tmp = None
    archive_tmp = None
    now = _utc_now()
    now_ms = int(now.timestamp() * 1000)
    source_created_ms = _ms(session.get("created_at"), default=now_ms)
    created_ms = source_created_ms if preserve_timestamps else now_ms
    imported_ms = now_ms
    try:
        title = session.get("title") or droid_id
        manual_title = bool(session.get("is_title_manually_set")) or bool(droid_session_start.get("isSessionTitleManuallySet")) or bool(session.get("title"))
        compactions = bridge.get("compactions") or []
        events = _droid_raw_replay_events(bridge, droid_id, title, cwd=cwd, host_id=host_id) if compaction_mode == "raw" else []
        if events:
            message_count = sum(1 for event in events if event.get("type") == "message")
        else:
            native_compaction = _latest_compaction(compactions) if compaction_mode == "native" else None
            active_messages = _droid_native_suffix_messages(bridge.get("messages", []), native_compaction) if native_compaction else list(bridge.get("messages", []))
            session_start = {
                "type": "session_start",
                "id": droid_id,
                "title": title,
                "sessionTitle": title,
                "owner": str(droid_session_start.get("owner") or "codex-provider-manager"),
                "isSessionTitleManuallySet": manual_title,
            }
            parent_session_id = str(droid_session_start.get("parent") or "")
            if not parent_session_id and native_compaction and native_compaction.get("parent_session_id"):
                parent_session_id = str(native_compaction.get("parent_session_id"))
            if parent_session_id:
                session_start["parent"] = parent_session_id
            if not manual_title:
                session_start["sessionTitleAutoStage"] = str(droid_session_start.get("sessionTitleAutoStage") or session.get("title_auto_stage") or "first_message")
            if cwd:
                session_start.update({
                    "version": _int_or_default(droid_session_start.get("version"), 2),
                    "cwd": cwd,
                })
                if host_id:
                    session_start["hostId"] = host_id
            events = [session_start]

            parent_id = ""
            emitted_message_ids = set()
            if native_compaction:
                events.append(_droid_compaction_state_event(_droid_anchorless_compaction(native_compaction), 0))

            for index, message in enumerate(active_messages):
                role = message.get("role") if message.get("role") in ("user", "assistant") else "user"
                if preserve_timestamps:
                    timestamp = message.get("created_at") or session.get("created_at") or _iso(now)
                else:
                    timestamp = _iso(now + datetime.timedelta(milliseconds=index))
                event_id = message.get("id") or f"message-{index}"
                event = {
                    "type": "message",
                    "id": event_id,
                    "timestamp": timestamp,
                    "message": {
                        "role": role,
                        "content": [_droid_content_part(part) for part in message.get("parts", [])],
                    },
                }
                if message.get("role") not in ("user", "assistant"):
                    event["bridgeRole"] = str(message.get("role") or "unknown")
                explicit_parent_id = str(message.get("parent_id") or "")
                if explicit_parent_id in emitted_message_ids:
                    event["parentId"] = explicit_parent_id
                elif parent_id:
                    event["parentId"] = parent_id
                events.append(event)
                parent_id = event_id
                emitted_message_ids.add(event_id)

            if compaction_mode == "inline":
                for compaction_index, compaction in enumerate(compactions):
                    events.append(_droid_compaction_state_event(compaction, compaction_index))

            message_count = len(active_messages)

        _validate_droid_events(events)
        jsonl_fd, jsonl_tmp_name = tempfile.mkstemp(prefix=f"{droid_id}.", suffix=".jsonl.tmp", dir=str(sessions_dir))
        jsonl_tmp = Path(jsonl_tmp_name)
        with os.fdopen(jsonl_fd, "w", encoding="utf-8") as handle:
            handle.write("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events))
        settings = _resolve_droid_session_settings(factory_home, session_with_extras, session.get("updated_at") or _iso(now), target_provider=target_provider, target_model=target_model)
        settings_fd, settings_tmp_name = tempfile.mkstemp(prefix=f"{droid_id}.", suffix=".settings.json.tmp", dir=str(sessions_dir))
        settings_tmp = Path(settings_tmp_name)
        with os.fdopen(settings_fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(settings, indent=2, ensure_ascii=True) + "\n")
        source_events = [event for event in (bridge.get("source_events") or []) if isinstance(event, dict)]
        if source_events:
            archive_fd, archive_tmp_name = tempfile.mkstemp(prefix=f"{droid_id}.", suffix=".bridge-source-events.json.gz.tmp", dir=str(sessions_dir))
            archive_tmp = Path(archive_tmp_name)
            archive_payload = {
                "format": DROID_SOURCE_ARCHIVE_FORMAT,
                "version": DROID_SOURCE_ARCHIVE_VERSION,
                "droid_session_id": droid_id,
                "source_app": str(source.get("app") or ""),
                "events": source_events,
            }
            with os.fdopen(archive_fd, "wb") as raw_handle:
                with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as gzip_handle:
                    gzip_handle.write(json.dumps(archive_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        jsonl_tmp.replace(jsonl_path)
        settings_tmp.replace(settings_path)
        if archive_tmp is not None:
            archive_tmp.replace(archive_path)
        os.utime(jsonl_path, (imported_ms / 1000.0, imported_ms / 1000.0))
        os.utime(settings_path, (imported_ms / 1000.0, imported_ms / 1000.0))
        if archive_path.exists():
            os.utime(archive_path, (imported_ms / 1000.0, imported_ms / 1000.0))
        _update_droid_index(
            factory_home,
            droid_id,
            title,
            jsonl_path,
            settings_path,
            message_count,
            cwd=cwd,
            host_id=host_id,
            created_ms=created_ms,
            modified_ms=imported_ms,
        )
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
            "droid_source_archive_path": str(archive_path) if archive_path.exists() else "",
            "droid_list_jsonl_path": str(jsonl_path),
            "droid_list_settings_path": str(settings_path),
            "mapping_path": str(mapping_path),
            "mirror_mode": "",
            "warnings": warnings,
        }
    except Exception:
        for path in (jsonl_tmp, settings_tmp, archive_tmp, jsonl_path, settings_path, archive_path):
            try:
                if path is not None and Path(path).exists():
                    Path(path).unlink()
            except OSError:
                pass
        raise

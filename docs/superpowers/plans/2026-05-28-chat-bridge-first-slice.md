# Chat Bridge First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the smallest useful Codex <-> Droid chat bridge: read/list sessions, convert to a normalized bridge object, import Droid sessions into Codex as a consistent SQLite+rollout pair, export a small Codex session into Droid, and record a pair mapping for later sync.

**Architecture:** Add a focused `chat_bridge.py` module with no external dependencies. Keep CLI glue in `codex_chat_transformer.py` small. Extend `test_smoke.py` first with temp Codex/Factory homes only.

**Tech Stack:** Python stdlib (`json`, `sqlite3`, `zipfile`, `uuid`, `datetime`, `pathlib`, `tempfile`), existing smoke test runner.

---

### Task 1: Tests for Bridge Normalization

**Files:**
- Modify: `test_smoke.py`
- Create later: `chat_bridge.py`

- [ ] **Step 1: Write failing tests**

Add tests that import `chat_bridge`, create temp Droid JSONL/settings files, and assert `droid_session_to_bridge()` produces:

- `format == "codex-droid-chat-bridge"`;
- `source.app == "droid"`;
- text messages;
- `tool_use` and `tool_result` parts;
- `work_context.current.confidence == "unknown"`;
- `timeline_complete is False`.

- [ ] **Step 2: Run RED**

Run: `python test_smoke.py`

Expected: FAIL with `No module named 'chat_bridge'` or missing function.

- [ ] **Step 3: Implement minimal bridge parsing**

Create `chat_bridge.py` with constants, JSONL reader helpers, timestamp normalization, Droid JSONL parsing, bridge validation, and no writes.

- [ ] **Step 4: Run GREEN**

Run: `python test_smoke.py`

Expected: new normalization tests pass; existing tests unchanged.

### Task 2: Tests for Droid -> Codex Import Consistency

**Files:**
- Modify: `test_smoke.py`
- Modify: `chat_bridge.py`

- [ ] **Step 1: Write failing tests**

Add a test that converts a Droid session to bridge, calls `import_bridge_to_codex()`, then verifies:

- a `threads` row exists;
- `threads.rollout_path` exists on disk;
- rollout first event is `session_meta`;
- session id/provider/model/timestamps match between DB and rollout;
- old Droid session imported with `pin_old=True` adds the new Codex id to `.codex-global-state.json`;
- `preserve_timestamps=True` keeps old `created_at_ms`/`updated_at_ms`;
- `preserve_timestamps=False` writes a fresh timestamp greater than the source timestamp.

Add a failure test using a deliberately invalid bridge message that proves no visible DB row remains when rollout validation fails.

- [ ] **Step 2: Run RED**

Run: `python test_smoke.py`

Expected: FAIL because `import_bridge_to_codex()` is missing.

- [ ] **Step 3: Implement import**

Implement `import_bridge_to_codex(bridge, codex_dir, state_db, sessions_dir, global_state_path, preserve_timestamps=True, pin_old=False, old_before_ms=None)`:

- allocate new session id by default;
- render rollout to temp file;
- validate JSONL and `session_meta`;
- move temp rollout to final path;
- insert row in SQLite transaction;
- verify DB+rollout consistency after commit;
- write mapping state under `.codex/chat_bridge_mappings.json`;
- optionally pin old imported Droid sessions.

- [ ] **Step 4: Run GREEN**

Run: `python test_smoke.py`

Expected: import tests pass.

### Task 3: Tests for Codex -> Droid Sample Export

**Files:**
- Modify: `test_smoke.py`
- Modify: `chat_bridge.py`

- [ ] **Step 1: Write failing tests**

Add a test using existing `store_temp_session()` to create a small Codex rollout, convert it to bridge, then call `import_bridge_to_droid()` into a temp Factory home. Verify:

- `.factory/sessions/<id>.jsonl` exists;
- first event is `session_start`;
- messages include text from the Codex rollout;
- `.settings.json` contains provider/model lock metadata when present;
- `.factory/chat_bridge_mappings.json` maps Codex id to Droid id.

- [ ] **Step 2: Run RED**

Run: `python test_smoke.py`

Expected: FAIL because Codex export/import-to-Droid functions are missing.

- [ ] **Step 3: Implement Codex side**

Implement `codex_session_to_bridge(row, rollout_path)` and `import_bridge_to_droid(bridge, factory_home, preserve_timestamps=True)`.

- [ ] **Step 4: Run GREEN**

Run: `python test_smoke.py`

Expected: Codex -> Droid test passes.

### Task 4: CLI Glue

**Files:**
- Modify: `codex_chat_transformer.py`
- Modify: `test_smoke.py`

- [ ] **Step 1: Write failing CLI parser tests**

Add parser tests for:

- `--droid-sessions`;
- `--codex-sessions`;
- `--codex-to-droid`;
- `--droid-to-codex`;
- `--chat-session`;
- `--chat-preserve-timestamps`;
- `--chat-fresh-timestamps`;
- `--chat-pin-old`.

- [ ] **Step 2: Run RED**

Run: `python test_smoke.py`

Expected: FAIL because flags are missing.

- [ ] **Step 3: Implement CLI glue**

Add flags and handlers that call `chat_bridge` functions. First version:

- list commands are read-only;
- transfer commands require explicit `--chat-session`;
- default is `--chat-preserve-timestamps`;
- `--chat-fresh-timestamps` overrides preservation;
- `--chat-pin-old` only affects Droid -> Codex.

- [ ] **Step 4: Run GREEN**

Run: `python test_smoke.py`

Expected: CLI tests pass.

### Task 5: Final Verification

**Files:**
- Modify docs only if flags differ from plan.

- [ ] **Step 1: Compile**

Run: `python -m py_compile codex_chat_transformer.py codex_sync.py droid_provider_adapter.py chat_bridge.py test_smoke.py`

Expected: no output, exit 0.

- [ ] **Step 2: Whitespace**

Run: `git diff --check`

Expected: no errors.

- [ ] **Step 3: Full smoke**

Run: `python test_smoke.py`

Expected: all tests pass.

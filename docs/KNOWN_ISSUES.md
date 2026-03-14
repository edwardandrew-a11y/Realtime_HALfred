# Known Issues and Deferred Fixes

This document tracks known issues that have been analyzed but deferred for future resolution.

---

## TTS-001: Concurrent ElevenLabs TTS Task Interleaving

**Status:** Partially resolved (list growth fixed 2026-02-28); interleaving risk deferred
**Severity:** Low (theoretical risk, rarely manifests in practice)
**Identified:** January 25, 2026
**Location:** `main.py:519-585` (ElevenLabsTTS class)

### Description

The `ElevenLabsTTS.add_text()` method spawns overlapping `_speak_async` tasks that all write to the same `AudioPlayer` buffer. This creates two potential issues:

1. **Audio interleaving**: If multiple tasks run concurrently, sentence audio could interleave
2. **Premature `is_speaking` False**: Each task independently sets `is_speaking = False` in its `finally` block, so if Task A finishes while Task B is still streaming, the flag becomes incorrect

#### Sub-issue resolved (2026-02-28): `_speaking_tasks` unbounded list growth

Tasks appended to `_speaking_tasks` were only pruned in `flush()` and `interrupt()`. During long sessions with many TTS sentences, the list would grow without bound between those calls. Fixed by adding a `done_callback` that removes the task from the list on natural completion:

```python
task = asyncio.create_task(self._speak_async(complete.strip()))
self._speaking_tasks.append(task)
# Append first; callback fires on event-loop thread so list access is safe.
task.add_done_callback(
    lambda t: self._speaking_tasks.remove(t) if t in self._speaking_tasks else None
)
```

The `if t in self._speaking_tasks` guard prevents `ValueError` when `interrupt()` has already called `clear()` before the callback fires.

### Current Behavior (post-fix)

```python
def add_text(self, text: str):
    # ... sentence extraction ...
    if complete.strip():
        task = asyncio.create_task(self._speak_async(complete.strip()))  # Concurrent!
        self._speaking_tasks.append(task)
        task.add_done_callback(...)  # Prunes list on completion
```

### Why It Rarely Manifests

- LLM streaming has natural pauses between sentences
- ElevenLabs API has network latency that naturally serializes requests
- AudioPlayer buffer smooths minor timing variations
- `tts.flush()` properly waits for all tasks before mic restart

### Affected Functionality

- **PTT interrupt logic**: Uses `is_speaking` to determine if speech should be interrupted
- **Sentence ordering**: Could theoretically be wrong under burst conditions

### Why We're Deferring

1. No observed issues in normal usage
2. Natural timing characteristics prevent the race condition in practice
3. Higher priority: testing all 39+ tools for correct functionality
4. Low practical impact vs. implementation effort

### Recommended Fix (When Ready)

**Queue + Worker Pattern** (guarantees FIFO ordering):

```python
class ElevenLabsTTS:
    def __init__(self, ...):
        # ... existing init ...
        self._speech_queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

    def add_text(self, text: str):
        # ... existing sentence extraction logic ...
        if complete.strip():
            self._speech_queue.put_nowait(complete.strip())
            # Start worker if not running
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._speech_worker())

    async def _speech_worker(self):
        """Single worker that processes speech sequentially."""
        self.is_speaking = True
        try:
            while True:
                try:
                    text = await asyncio.wait_for(
                        self._speech_queue.get(),
                        timeout=0.5
                    )
                    await self._speak_async(text)
                    self._speech_queue.task_done()
                except asyncio.TimeoutError:
                    if self._speech_queue.empty():
                        break
        finally:
            self.is_speaking = False

    async def flush(self) -> None:
        # Wait for queue to drain
        if not self._speech_queue.empty():
            await self._speech_queue.join()
        # Wait for worker to finish
        if self._worker_task and not self._worker_task.done():
            await self._worker_task
        # Wait for audio playback
        while self.player.is_playing():
            await asyncio.sleep(0.1)
```

### Alternative Fix (Simpler, Less Robust)

**Lock inside task** (simpler but doesn't guarantee FIFO under races):

```python
def __init__(self, ...):
    self._tts_lock = asyncio.Lock()

def add_text(self, text: str):
    if complete.strip():
        task = asyncio.create_task(self._speak_with_lock(complete.strip()))
        self._speaking_tasks.append(task)

async def _speak_with_lock(self, text: str):
    async with self._tts_lock:
        await self._speak_async(text)
```

### References

- Original analysis by CodeX agent (January 25, 2026)
- Reviewed and validated by Claude Code
- Related: Issue #2 (blocking ElevenLabs call) — also deferred, same code section

---

## TTS-002: Blocking ElevenLabs Call in Async Function

**Status:** Deferred
**Severity:** Medium (can stall event loop during TTS generation)
**Identified:** January 25, 2026
**Location:** `main.py:541-556` (ElevenLabsTTS._speak_async)

### Description

The `self.client.text_to_speech.convert()` call inside `async def _speak_async()` is a synchronous blocking HTTP call, not wrapped in `asyncio.to_thread()`. This blocks the event loop during TTS generation.

### Current Behavior

```python
async def _speak_async(self, text: str) -> None:
    # ...
    audio_stream = self.client.text_to_speech.convert(  # Blocking!
        voice_id=self.voice_id,
        text=text,
        # ...
    )
```

### Impact

While TTS is generating (network request in flight), other async tasks (mic handling, event processing) may stall.

### Why We're Deferring

1. ElevenLabs uses streaming with `optimize_streaming_latency=3`, so blocking time is minimized
2. No observed performance issues in normal usage
3. Fix is straightforward when needed
4. Same rationale as TTS-001: focus on tool testing first

### Recommended Fix (When Ready)

```python
async def _speak_async(self, text: str) -> None:
    # ...
    audio_stream = await asyncio.to_thread(
        self.client.text_to_speech.convert,
        voice_id=self.voice_id,
        text=text,
        model_id=self.model_id,
        output_format="pcm_24000",
        optimize_streaming_latency=3,
    )
```

**Note:** If the returned `audio_stream` is an iterator, the iteration also needs to be wrapped or converted to a list inside the thread.

---

## CONV-001: Background Tasks Should Use safe_print()

**Status:** Coding Convention (not a bug)
**Severity:** Low
**Identified:** January 25, 2026

### Description

The codebase uses a `safe_print()` function in `main.py` that respects `_input_active` to avoid garbling the user's input prompt. However, a repo-wide search found multiple `print()` calls in background/async code:

| File | print() calls | Purpose |
|------|---------------|---------|
| `anki_agent.py` | 14 | Debug logging during agent execution |
| `supervisor.py` | 13 | Debug logging in supervisor loop |
| `session_logger.py` | 18 | Logging and error reporting |

### Why It Rarely Matters in Practice

- When the user is typing (`_input_active` is set), the agent is typically idle waiting for input
- When the agent is processing (and these prints fire), the user has already submitted their message
- The timing rarely overlaps

### Guideline

**All async/background code should use `safe_print()` instead of `print()` when outputting to the console during normal operation.**

Exception: MCP servers (like `pty_proxy_mcp.py`) that run as separate processes can use `print()` to stderr since they don't share the console with `user_input_loop`.

### Future Enforcement Options

1. Add a pre-commit hook or linter rule to flag `print()` in async functions
2. Refactor debug prints to use a proper logging framework with configurable output
3. Migrate all prints to `safe_print()` during a future cleanup pass

---

---

## ASYNC-001: `asyncio.get_event_loop()` used inside coroutines

**Status:** Fixed (2026-02-28)
**Severity:** Low (deprecation warning, potential silent misbehavior on Python 3.10+)
**Identified:** February 28, 2026
**Location:** `main.py` — `mic_send_loop()` (two call sites)

### Description

Two uses of `asyncio.get_event_loop().time()` existed inside the `async def mic_send_loop` coroutine. In Python 3.10+, `asyncio.get_event_loop()` emits a `DeprecationWarning` when called without a running loop set on the current thread, and its semantics differ from `get_running_loop()`. Inside any running coroutine, `asyncio.get_running_loop()` is the correct API — it is guaranteed to return the current running loop and raises `RuntimeError` if there is none (rather than silently creating a new one).

### Fix Applied

```python
# Before
start_time = asyncio.get_event_loop().time()
elapsed = asyncio.get_event_loop().time() - start_time

# After
start_time = asyncio.get_running_loop().time()
elapsed = asyncio.get_running_loop().time() - start_time
```

---

## DEAD-001: Duplicate PTT environment variable loading in `main()`

**Status:** Fixed (2026-02-28)
**Severity:** Low (dead code, no runtime impact)
**Identified:** February 28, 2026
**Location:** `main.py` — `main()` function, approx. line 2091 (pre-fix)

### Description

`ptt_enabled`, `ptt_key`, and `ptt_interrupts` were read from environment variables twice inside `main()`. The first read (with a comment "needs to be early to configure turn detection") was correct and necessary. A second identical block appeared ~80 lines later after the escalation tool was wired up, immediately before `create_ptt_handlers()`. Since the values are immutable env reads, the second block was pure dead code.

### Fix Applied

Removed the second `# Load push-to-talk configuration` block and its three redundant assignments.

---

---

## ANKI-001: Malformed tool arguments crash agent turn in `anki_agent.py`

**Status:** Fixed (2026-03-08)
**Severity:** High (one bad function-call payload aborted the entire agent loop)
**Location:** `anki_agent.py` — `AnkiSubagent._run_turn()` tool execution loop

### Description

`json.loads(raw_args)` was called bare before any exception handler. A malformed Responses API payload (e.g. truncated JSON or a non-object top-level value) raised `JSONDecodeError` and crashed the `while` loop, dropping the entire turn instead of surfacing a tool-scoped error.

### Fix Applied

Added `parse_tool_args()` helper that normalizes `None`, `dict`, and `str` payloads into a validated `dict`. The call site wraps it in `try/except (json.JSONDecodeError, TypeError, ValueError)` — errors are serialized as `{"error": "..."}` and sent back to the model so the loop continues.

---

## ANKI-002: Only `AnkiConnectError` caught in tool dispatch loop

**Status:** Fixed (2026-03-08)
**Severity:** Medium (unexpected exceptions escaped the loop and broke supervisor delegation)
**Location:** `anki_agent.py` — `AnkiSubagent._run_turn()` tool execution loop

### Description

The `except` clause after `dispatch_tool()` only caught `AnkiConnectError`. A `KeyError`, `TypeError`, `AttributeError`, or any other exception from the dispatcher propagated out of the `for call in current_tool_calls` loop, terminating the agentic turn with an unhandled exception instead of a structured error message.

### Fix Applied

Added `except Exception as e` fallback that serializes the exception as `{"error": "Unexpected tool error in {tool_name}: {ExcType}: {e}"}` and sets `success = False`, keeping the loop alive.

---

## ANKI-003: State updates only applied to `anki_add_cloze`

**Status:** Fixed (2026-03-08)
**Severity:** Medium (weakened session context; follow-up turns lost deck/note awareness)
**Location:** `anki_agent.py` — `AnkiSubagent._run_turn()` memory-write block

### Description

The docstring at `AnkiSubagent` stated the class maintains `last_deck` and `last_note_ids`. The implementation only updated both fields for `anki_add_cloze`. Tools like `anki_find_notes`, `anki_notes_info`, `anki_update_note_fields`, `anki_add_tags`, `anki_create_deck`, `anki_change_deck`, `anki_gui_add_cards`, and `anki_gui_deck_review` left state unchanged, so follow-up turns had no awareness of which deck or notes were just operated on.

### Fix Applied

Extracted all state logic into `_update_state_from_tool_result()`. It updates `last_deck` for five deck-targeting tools and `last_note_ids` for four note-targeting tools. Guard: skips updates when result has `"error"` key or `"ok": False` (catches `anki_gui_deck_review` failures which return no `"error"` key).

---

## ANKI-004: `anki_gui_add_cards` default model was `"AnKingOverhaul"`

**Status:** Fixed (2026-03-08)
**Severity:** Low (third-party note type absent from most Anki installs; violates cloze-only contract)
**Location:** `anki_agent.py` — `dispatch_tool()` + tool schema description

### Description

`dispatch_tool` defaulted `model` to `"AnKingOverhaul"` (a note type bundled with the AnKing medical deck). On installs without that deck, `gui_add_cards` fails or silently opens with an unexpected model. The tool schema description additionally claimed "Defaults to 'Basic' if not specified", contradicting both the implementation and the agent's hard rule of cloze-only card creation.

### Fix Applied

Changed the implementation default to `"Cloze"` (built-in Anki model, always present) and updated the schema description to `"Defaults to 'Cloze' if not specified"`.

---

## ANKI-005: Per-turn `import time` and session-logger imports

**Status:** Fixed (2026-03-08)
**Severity:** Low (minor overhead on every agent turn)
**Location:** `anki_agent.py` — `AnkiSubagent._run_turn()`

### Description

`import time` and the three `session_logger` helper imports (`log_llm_call_sync`, `log_llm_response_sync`, `log_tool_dispatch_sync`) were placed inside `_run_turn()`, so Python re-executed the import machinery on every call. While Python caches modules after first import, the lookup overhead and readability cost were unnecessary — these imports are unconditionally needed on every turn.

### Fix Applied

Hoisted all four imports to module scope.

---

## SESSION-001: Realtime session expiry after long idle/runtime

**Status:** Fixed (2026-03-12)
**Severity:** Medium (forced full app restart after websocket expiry)
**Location:** `main.py` — session lifecycle / dormant reconnect flow

### Description

The OpenAI Realtime websocket has a hard 60-minute session cap. Earlier HALfred builds treated the Realtime session as process-lifetime, so a `session_expired` error or long idle timeout forced the user to restart the entire program and wait for audio, MCP, and supervisor initialization again.

### Fix Applied

HALfred now separates process lifetime from websocket-session lifetime:

- Idle sessions enter a dormant state after `DORMANT_TIMEOUT_MINUTES`
- Pressing PTT or sending text wakes the app and reconnects the Realtime websocket
- The app proactively rotates the websocket before the 60-minute hard cap using `SESSION_MAX_MINUTES`
- MCP servers, the Supervisor agent, keyboard listener, mic pipeline, and logger stay loaded across reconnects
- `/retry` provides manual recovery if reconnect attempts fail

---

## Document History

| Date | Change |
|------|--------|
| 2026-01-25 | Initial creation with TTS-001 and TTS-002 |
| 2026-01-25 | Added CONV-001 (safe_print convention) after repo-wide audit |
| 2026-02-28 | TTS-001 partially resolved: `_speaking_tasks` list-growth sub-issue fixed with `done_callback` |
| 2026-02-28 | Added ASYNC-001 (resolved): `get_event_loop()` → `get_running_loop()` in `mic_send_loop` |
| 2026-02-28 | Added DEAD-001 (resolved): removed duplicate PTT env-var block in `main()` |
| 2026-03-08 | Added ANKI-001 through ANKI-005 (all resolved): AG2 debate review of `anki_agent.py` |
| 2026-03-12 | Added SESSION-001 (resolved): dormant reconnect + proactive session rotation for Realtime websocket expiry |

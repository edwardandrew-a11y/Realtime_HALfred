# Main entry point for the HALfred voice agent. It wires together audio I/O,
# the OpenAI Realtime agent stack, ElevenLabs text-to-speech, and optional
# Model Context Protocol (MCP) computer control helpers defined elsewhere in this repo.

# Claude says to leave the references to MCP_SERVERS_JSON rather than only using MCP_SERVERS.json, as it "future-proofs
# for Docker/cloud deployments and follows best practices (12-factor app: config via environment)", whatever that means.

# Core Python utilities for async orchestration, config loading, and timing.
import asyncio
import json
import os
import sys
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import Callable, Optional

# Trace comes from agents/tracing (part of the OpenAI Agents SDK) to add metadata
# to the session lifecycle for debugging.
from agents.tracing import trace

# Third-party audio + TTS libraries: sounddevice handles microphone/speaker audio,
# ElevenLabs client streams synthesized speech from ElevenLabs' API.
import sounddevice as sd
from elevenlabs.client import ElevenLabs

# Agents SDK utilities:
# - function_tool (agents/function_tool.py) wraps local Python functions as tools exposed to the agent.
from agents import function_tool
# - MCP server context managers from agents/mcp.py start external tool servers defined in MCP_SERVERS.json.
from agents.mcp import (
    MCPServerSse,
    MCPServerStdio,
    MCPServerStreamableHttp,
    create_static_tool_filter,
)
# - RealtimeAgent/RealtimeRunner from agents/realtime.py manage the OpenAI realtime conversation session.
from agents.realtime import (
    RealtimeAgent,
    RealtimeRunner,
    RealtimeRunConfig,
    RealtimeSession,
)
from agents.realtime.events import RealtimeToolEnd, RealtimeToolStart
from agents.realtime.model_inputs import (
    RealtimeModelSendRawMessage,
    RealtimeModelSendToolOutput,
)
from agents.tool import FunctionTool
from agents.tool_context import ToolContext

# Import automation safety module (local automation_safety.py) when available to expose
# the safe_action tool and display detection helpers that talk to computer-control/feedback MCP servers.
try:
    from automation_safety import safe_action, init_display_detection
    AUTOMATION_SAFETY_AVAILABLE = True
except ImportError as e:
    print(f"[automation_safety] Module not available: {e}")
    AUTOMATION_SAFETY_AVAILABLE = False
    safe_action = None
    init_display_detection = None

# Import native screenshot tool
try:
    from native_screenshot import take_screenshot
    NATIVE_SCREENSHOT_AVAILABLE = True
except ImportError as e:
    print(f"[native_screenshot] Module not available: {e}")
    NATIVE_SCREENSHOT_AVAILABLE = False
    take_screenshot = None

# Import MCP schema fix to patch tool schemas for OpenAI Realtime API compatibility
# This fixes tools like keyboard_type that use union schemas without top-level "type": "object"
import mcp_schema_fix  # Applies monkey-patch on import


# Thread-safe printing that respects the input prompt
_input_active = threading.Event()
_print_lock = threading.Lock()
_current_line_buffer = []
_chars_printed = 0  # Track how many characters we've already printed
_last_prompt_restore = 0.0
_streaming_started = False  # Track if we've moved off the prompt line


def safe_print(*args, **kwargs):
    """Print that clears and restores the 'You> ' prompt when input is active."""
    global _last_prompt_restore, _chars_printed, _streaming_started
    import time

    with _print_lock:
        if _input_active.is_set():
            # For streaming text (end="" or end without newline), buffer it
            end = kwargs.get('end', '\n')

            if end == '' or (end and '\n' not in end):
                # Buffering mode for streaming text (character-by-character from assistant)
                _current_line_buffer.append(' '.join(str(arg) for arg in args))
                full_text = ''.join(_current_line_buffer)

                # Only update display every 50ms or when buffer is substantial
                now = time.time()
                new_chars = len(full_text) - _chars_printed
                if (now - _last_prompt_restore) < 0.05 and new_chars < 40:
                    return  # Skip this update, too soon
                _last_prompt_restore = now

                # On first streaming character, move to a new line
                if not _streaming_started:
                    print()  # Move off the "You> " line
                    _streaming_started = True

                # Print only the NEW characters since last print (incremental update)
                if new_chars > 0:
                    new_text = full_text[_chars_printed:]
                    print(new_text, end='', flush=True)
                    _chars_printed = len(full_text)
            else:
                # Normal print with newline - this interrupts streaming
                # First, complete any buffered streaming text
                if _current_line_buffer:
                    full_text = ''.join(_current_line_buffer)
                    # Print any remaining unprinted characters
                    if _chars_printed < len(full_text):
                        remaining = full_text[_chars_printed:]
                        print(remaining, end='', flush=True)
                    # Move to new line to complete the streaming text
                    print()
                    _current_line_buffer.clear()
                    _chars_printed = 0
                    _streaming_started = False

                # Now print the new message on a fresh line (clearing any prompt)
                print('\r\033[K', end='')
                print(*args, **kwargs, end=end)

                # Restore the prompt on a new line
                print("You> ", end='', flush=True)

                # Reset rate limiting timestamp so next streaming text doesn't get throttled
                _last_prompt_restore = time.time()
        else:
            # Not waiting for input, just print normally and clear buffer
            _current_line_buffer.clear()
            _chars_printed = 0
            _streaming_started = False
            print(*args, **kwargs)


# Shortens any long strings received from other parts of the program before printing them (useful when logging raw MCP/events).
# Keeps terminal easier to read.
def _truncate(s: str, n: int = 250) -> str:
    return s if len(s) <= n else s[:n] + "..."



# This is a currently unused function due to RealtimeAPI output modality set to 'text'
# Originally this converts RealtimeAPI audio output (in base64 format) to a raw PCM16 bytes format for playback
def _as_pcm16_bytes(maybe_audio) -> bytes:
    """Best-effort conversion of realtime audio chunks to raw PCM16 bytes."""
    if maybe_audio is None:
        return b""

    if isinstance(maybe_audio, (bytes, bytearray)):
        return bytes(maybe_audio)

    # Some SDK/model events may carry base64 strings.
    if isinstance(maybe_audio, str):
        import base64
        try:
            return base64.b64decode(maybe_audio)
        except Exception:
            return b""

    # Fallback: try to stringify and ignore.
    return b""



# Recursively expand ${VARNAME} placeholders in config dicts/lists/strings
# Used by init_mcp_servers() to let env vars override values in MCP_SERVERS.json
# or MCP_SERVERS_JSON env content.
def _expand_env_placeholders(obj):
    """Recursively expand ${VARNAME} placeholders in strings within dict/list structures.

    This lets you keep secrets like API keys out of versioned JSON files.
    """
    if obj is None:
        return None

    if isinstance(obj, str):
        s = obj
        # Replace occurrences like ${OPENAI_API_KEY}
        # We do a simple pass that supports multiple placeholders in one string.
        import re

        def repl(match):
            var = match.group(1)
            return os.getenv(var, "")

        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, s)

    if isinstance(obj, list):
        return [_expand_env_placeholders(x) for x in obj]

    if isinstance(obj, dict):
        return {k: _expand_env_placeholders(v) for k, v in obj.items()}

    return obj


async def init_mcp_servers(stack: AsyncExitStack):
    # Start MCP tool servers defined in MCP_SERVERS.json so the
    # RealtimeAgent (agents/realtime.py) can call their tools during a session.
    # Servers are registered with the AsyncExitStack passed in from main().
    """Initialize MCP servers from a JSON file and/or the MCP_SERVERS_JSON env var.

    Precedence for config file:
      1) MCP_SERVERS_JSON_FILE (path)
      2) ./mcp_servers.json
      3) ./MCP_SERVERS_JSON.json

    If a config file loads successfully, we DO NOT parse MCP_SERVERS_JSON.
    """

    servers = []

    # Prefer a config file if present
    cfg_file = (os.getenv("MCP_SERVERS_JSON_FILE") or "").strip()
    if not cfg_file:
        for candidate in ("mcp_servers.json", "MCP_SERVERS.json"):
            if os.path.exists(candidate):
                cfg_file = candidate
                break

    cfg = None

    # 1) Try file
    if cfg_file:
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not isinstance(cfg, list):
                raise ValueError("MCP servers file must contain a JSON list")
            print(f"[mcp] Loaded MCP servers from file: {cfg_file}")
        except Exception as e:
            print(f"[mcp] Failed to load MCP servers file '{cfg_file}': {e}")
            cfg = None  # fall back to env var

    # 2) Fall back to env var
    if cfg is None:
        cfg_raw = (os.getenv("MCP_SERVERS_JSON") or "").strip()
        if cfg_raw:
            try:
                cfg = json.loads(cfg_raw)
                if not isinstance(cfg, list):
                    raise ValueError("MCP_SERVERS_JSON must be a JSON list")
            except Exception as e:
                print(f"[mcp] Failed to parse MCP_SERVERS_JSON: {e}")
                cfg = []
        else:
            cfg = []

    # Expand env placeholders recursively in config
    cfg = _expand_env_placeholders(cfg)

    # Start configured MCP servers
    for entry in cfg:
        if not isinstance(entry, dict):
            continue

        name = entry.get("name") or entry.get("server_label") or "MCP Server"

        # Skip servers based on ENABLE_* environment variables
        if name == "computer-control" and os.getenv("ENABLE_COMPUTER_CONTROL_MCP", "false").lower() != "true":
            print(f"[mcp] Skipping {name} (ENABLE_COMPUTER_CONTROL_MCP=false)")
            continue
        if name == "feedback-loop" and os.getenv("ENABLE_FEEDBACK_LOOP_MCP", "false").lower() != "true":
            print(f"[mcp] Skipping {name} (ENABLE_FEEDBACK_LOOP_MCP=false)")
            continue

        transport = (entry.get("transport") or "streamable_http").lower().replace("-", "_")
        params = _expand_env_placeholders(entry.get("params") or {})

        # Tool call timeout: MCP servers default to 5s, which is often too short for heavier tools.
        # Allow per-server override via config, otherwise fall back to MCP_CLIENT_TIMEOUT_SECONDS env var.
        timeout_s = entry.get("client_session_timeout_seconds")
        if timeout_s is None:
            try:
                timeout_s = float(os.getenv("MCP_CLIENT_TIMEOUT_SECONDS", "30"))
            except Exception:
                timeout_s = 30.0

        allowed = entry.get("allowed_tools")
        tool_filter = None
        if isinstance(allowed, list) and allowed:
            tool_filter = create_static_tool_filter(allowed_tool_names=allowed)

        try:
            if transport in {"streamable_http", "streamablehttp", "http"}:
                server_cm = MCPServerStreamableHttp(
                    name=name,
                    params=params,
                    cache_tools_list=True,
                    tool_filter=tool_filter,
                    client_session_timeout_seconds=timeout_s,
                    max_retry_attempts=3,
                )
            elif transport in {"sse"}:
                server_cm = MCPServerSse(
                    name=name,
                    params=params,
                    cache_tools_list=True,
                    tool_filter=tool_filter,
                    client_session_timeout_seconds=timeout_s,
                    max_retry_attempts=3,
                )
            elif transport in {"stdio"}:
                server_cm = MCPServerStdio(
                    name=name,
                    params=params,
                    cache_tools_list=True,
                    tool_filter=tool_filter,
                    client_session_timeout_seconds=timeout_s,
                    max_retry_attempts=3,
                )
            else:
                print(f"[mcp] Unknown transport '{transport}' for server '{name}'")
                continue

            server = await stack.enter_async_context(server_cm)
            servers.append(server)
        except Exception as e:
            print(f"[mcp] Failed to start MCP server '{name}': {e}")

    # Optional local demo filesystem MCP server
    demo_dir = (os.getenv("MCP_DEMO_FILESYSTEM_DIR") or "").strip()
    if demo_dir:
        try:
            demo_dir = _expand_env_placeholders(demo_dir)
            demo_cm = MCPServerStdio(
                name="Filesystem MCP (demo)",
                params={
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", demo_dir],
                },
                client_session_timeout_seconds=float(os.getenv("MCP_CLIENT_TIMEOUT_SECONDS", "30")),
                cache_tools_list=True,
                max_retry_attempts=3,
            )
            demo = await stack.enter_async_context(demo_cm)
            servers.append(demo)
        except Exception as e:
            print(f"[mcp] Failed to start Filesystem MCP demo: {e}")

    # Print tool counts
    for s in servers:
        try:
            tools = await s.list_tools()
            print(f"[mcp] {getattr(s, 'name', 'MCP')}: {len(tools)} tools")
        except Exception as e:
            print(f"[mcp] {getattr(s, 'name', 'MCP')}: failed to list tools: {e}")

    return servers


@dataclass
class ListenState:
    # Small shared flag object tracking whether continuous mic capture is on,
    # so user_input_loop() and event_loop() can coordinate mic start/stop.
    """Tracks microphone and push-to-talk state."""
    enabled: bool = False           # Whether continuous listening is enabled
    ptt_mode: bool = False          # True if using push-to-talk instead of continuous
    ptt_active: bool = False        # True while the PTT key is being held
    ptt_interrupts: bool = True     # Whether PTT should stop HALfred's speech
    speech_ended_event: Optional[asyncio.Event] = None  # Signals when server VAD detects speech end
    turn_state: str = "idle"        # Track commit state: "idle", "awaiting_speech_end", "committed"
    bytes_appended_since_commit: int = 0  # Track how much audio we've sent since last commit
    last_server_event_time: float = 0.0  # Timestamp of last event from server (for connection health)


@dataclass
class PTTState:
    """Holds push-to-talk keyboard listener and handlers."""
    keyboard_listener: Optional['KeyboardListener'] = None
    on_press_callback: Optional[Callable] = None
    on_release_callback: Optional[Callable] = None
    ptt_key: str = "cmd_alt"


class AudioPlayer:
    # Handles speaker playback of assistant audio using sounddevice; ElevenLabsTTS
    # writes PCM bytes into this buffer while event_loop() manages when to clear it.
    """Callback-based PCM16 mono playback with a simple jitter buffer."""

    def __init__(self, samplerate: int = 24000, channels: int = 1, dtype: str = "int16"):
        # Create a sounddevice output stream that consumes PCM16 chunks coming from ElevenLabsTTS.
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._last_write_ts = 0.0
        self._stream = sd.RawOutputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._callback,
            blocksize=0,
        )

    def start(self) -> None:
        # Begin playback; called once the realtime session is ready.
        self._stream.start()

    def stop(self) -> None:
        # Stop playback and free the stream when shutting down.
        try:
            self._stream.stop()
        finally:
            self._stream.close()

    def clear(self) -> None:
        # Drop any buffered audio (used when the mic interrupts playback).
        with self._lock:
            self._buf.clear()

    def write(self, pcm_bytes: bytes) -> None:
        # Append new audio from ElevenLabs into the buffer for playback.
        if not pcm_bytes:
            return
        now = time.monotonic()
        with self._lock:
            self._last_write_ts = now
            self._buf.extend(pcm_bytes)

    def is_playing(self, hangover_s: float = 0.25) -> bool:
        """True if we are actively playing (buffered audio) or just finished."""
        now = time.monotonic()
        with self._lock:
            buffered = len(self._buf) > 0
            recently_wrote = (now - self._last_write_ts) < hangover_s
        return buffered or recently_wrote

    def _callback(self, outdata, frames, time, status):
        # sounddevice calls this to fill the speaker buffer with our queued bytes.
        nbytes = len(outdata)
        with self._lock:
            if len(self._buf) >= nbytes:
                chunk = self._buf[:nbytes]
                del self._buf[:nbytes]
            else:
                chunk = bytes(self._buf)
                self._buf.clear()

        if len(chunk) < nbytes:
            chunk = chunk + b"\x00" * (nbytes - len(chunk))

        outdata[:] = chunk


# Wraps ElevenLabs streaming TTS so agent text can be chunked and spoken through AudioPlayer.
class ElevenLabsTTS:
    """Streaming TTS with ElevenLabs for low-latency audio generation."""

    def __init__(self, api_key: str, player: AudioPlayer, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        # Store the ElevenLabs client and link it to the shared AudioPlayer so
        # text streamed from the agent can be spoken out loud.
        self.client = ElevenLabs(api_key=api_key)
        self.player = player
        self.voice_id = voice_id
        self.model_id = "eleven_turbo_v2_5"  # Fastest model
        self.text_buffer = ""
        self.is_speaking = False
        self._lock = threading.Lock()
        self._speaking_tasks = []  # Track ongoing TTS tasks

    def add_text(self, text: str) -> None:
        # Buffer incoming assistant text and kick off speech tasks for complete sentences.
        """Add text to buffer and process complete sentences."""
        with self._lock:
            self.text_buffer += text

            # Check for complete sentences (. ! ? or newline)
            import re
            sentences = re.split(r'([.!?\n])', self.text_buffer)

            # Process complete sentences
            complete = ""
            remaining = ""
            for i in range(0, len(sentences) - 1, 2):  # Process pairs (text, delimiter)
                if i + 1 < len(sentences):
                    complete += sentences[i] + sentences[i + 1]
                else:
                    remaining = sentences[i]

            # Last element might be incomplete
            if len(sentences) % 2 == 1:
                remaining = sentences[-1]

            self.text_buffer = remaining

            if complete.strip():
                # Start async speech generation in background and track it
                task = asyncio.create_task(self._speak_async(complete.strip()))
                self._speaking_tasks.append(task)

    async def _speak_async(self, text: str) -> None:
        # Stream the given text through ElevenLabs and feed bytes to AudioPlayer.
        """Generate and play speech asynchronously."""
        if not text:
            return

        try:
            # Commented out verbose speaking notifications to reduce terminal clutter
            # Uncomment for debugging if needed
            # safe_print(f"[elevenlabs] Speaking: \"{text[:50]}...\"")
            self.is_speaking = True

            # Use streaming API for low latency
            audio_stream = self.client.text_to_speech.convert(
                voice_id=self.voice_id,
                text=text,
                model_id=self.model_id,
                output_format="pcm_24000",  # Match the player's 24kHz sample rate
                optimize_streaming_latency=3,  # Max optimization (0-4, 3 is aggressive)
            )

            # Stream audio chunks to player as they arrive - convert expects bytes back
            if isinstance(audio_stream, bytes):
                self.player.write(audio_stream)
            else:
                # If it's an iterator
                for chunk in audio_stream:
                    if chunk:
                        self.player.write(chunk)

        except Exception as e:
            safe_print(f"[elevenlabs] TTS error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_speaking = False

    async def flush(self) -> None:
        # Force any buffered text to be spoken and wait until AudioPlayer finishes.
        """Speak any remaining buffered text and wait for all speech to complete."""
        with self._lock:
            remaining = self.text_buffer.strip()
            self.text_buffer = ""

        if remaining:
            await self._speak_async(remaining)

        # Wait for all ongoing TTS tasks to complete
        if self._speaking_tasks:
            # Clean up completed tasks first
            self._speaking_tasks = [t for t in self._speaking_tasks if not t.done()]

            # Wait for remaining tasks
            if self._speaking_tasks:
                await asyncio.gather(*self._speaking_tasks, return_exceptions=True)
                self._speaking_tasks.clear()

        # Also wait for audio player to finish playing buffered audio
        while self.player.is_playing():
            await asyncio.sleep(0.1)

    def interrupt(self) -> None:
        """Stop all current speech immediately."""
        # Clear the text buffer so no new speech starts
        with self._lock:
            self.text_buffer = ""

        # Cancel any ongoing TTS generation tasks
        for task in self._speaking_tasks:
            if not task.done():
                task.cancel()
        self._speaking_tasks.clear()

        # Clear the audio player buffer
        self.player.clear()

        self.is_speaking = False
        safe_print("[elevenlabs] Speech interrupted")


# Captures microphone audio and feeds it into the realtime session through an asyncio queue.
class MicStreamer:
    """Raw PCM16 mono microphone capture with an asyncio queue bridge."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        samplerate: int = 24000,
        channels: int = 1,
        dtype: str = "int16",
        mute_fn: Optional[Callable[[], bool]] = None,
    ):
        # Configure a sounddevice input stream; mute_fn lets us pause capture while
        # AudioPlayer is playing to avoid feedback.
        self.loop = loop
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.mute_fn = mute_fn
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._running = False
        self._stream = sd.RawInputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._callback,
            blocksize=0,
        )

    @property
    def running(self) -> bool:
        # Expose whether the mic stream is active so other tasks can coordinate.
        return self._running

    def start(self) -> None:
        # Begin microphone capture when the user turns continuous listening on.
        if self._running:
            return
        self._running = True
        self._stream.start()

    def stop(self, *, commit: bool = True) -> None:
        # Stop capture; optionally send a None marker so mic_send_loop() commits the turn.
        if not self._running:
            return
        self._running = False
        try:
            self._stream.stop()
        finally:
            # Optionally signal the async sender loop to "commit" the last buffered audio.
            if commit:
                self.loop.call_soon_threadsafe(self.queue.put_nowait, None)

    def close(self) -> None:
        # Final cleanup when the app is shutting down.
        try:
            if self._stream.active:
                self._stream.stop()
        finally:
            self._stream.close()

    def _callback(self, indata, frames, time, status):
        # sounddevice calls this in the audio thread; push audio bytes into the asyncio queue.
        # Only queue audio when actively recording.
        if not self._running:
            return
        # Half-duplex gate: ignore mic while speaker playback is active to prevent echo.
        if self.mute_fn is not None and self.mute_fn():
            return
        # indata is a bytes-like buffer for RawInputStream
        chunk = bytes(indata)
        self.loop.call_soon_threadsafe(self.queue.put_nowait, chunk)


class KeyboardListener:
    """Monitors keyboard for push-to-talk key presses (including modifier combinations)."""

    def __init__(self, ptt_key: str = "space", on_press_callback=None, on_release_callback=None):
        # Store which key(s) we are watching for
        self.ptt_key = ptt_key
        self.is_pressed = False
        self._listener = None
        self._on_press_callback = on_press_callback
        self._on_release_callback = on_release_callback

        # For modifier combinations like "cmd_alt", track which modifiers are currently held
        self._modifiers_held = set()

        # Parse the key configuration to determine if it's a single key or combination
        self._is_combination = "_" in ptt_key
        if self._is_combination:
            self._required_modifiers = self._parse_combination(ptt_key)
        else:
            self._target_key = self._parse_key(ptt_key)

    def _parse_combination(self, combo: str):
        """Parse a combination like 'cmd_alt' into a set of required modifiers."""
        from pynput import keyboard

        parts = combo.lower().split("_")
        modifiers = set()

        key_map = {
            "cmd": keyboard.Key.cmd,
            "ctrl": keyboard.Key.ctrl,
            "shift": keyboard.Key.shift,
            "alt": keyboard.Key.alt,
        }

        for part in parts:
            if part in key_map:
                modifiers.add(key_map[part])
            else:
                print(f"[keyboard] Unrecognized modifier '{part}' in combination")

        return modifiers

    def _parse_key(self, key_name: str):
        """Convert a key name string to a pynput key object."""
        from pynput import keyboard

        key_name = key_name.lower().strip()

        # Special keys that pynput handles differently
        special_keys = {
            "space": keyboard.Key.space,
            "ctrl": keyboard.Key.ctrl,
            "shift": keyboard.Key.shift,
            "alt": keyboard.Key.alt,
            "cmd": keyboard.Key.cmd,
            "tab": keyboard.Key.tab,
            "enter": keyboard.Key.enter,
            "backspace": keyboard.Key.backspace,
            "f1": keyboard.Key.f1,
            "f2": keyboard.Key.f2,
            "f3": keyboard.Key.f3,
            "f4": keyboard.Key.f4,
            "f5": keyboard.Key.f5,
            "f6": keyboard.Key.f6,
            "f7": keyboard.Key.f7,
            "f8": keyboard.Key.f8,
            "f9": keyboard.Key.f9,
            "f10": keyboard.Key.f10,
            "f11": keyboard.Key.f11,
            "f12": keyboard.Key.f12,
        }

        if key_name in special_keys:
            return special_keys[key_name]

        # For regular letter/number keys, return the character
        if len(key_name) == 1:
            return key_name

        # Default to space if unrecognized
        print(f"[keyboard] Unrecognized PTT key '{key_name}', defaulting to space")
        return keyboard.Key.space

    def _check_combination_active(self) -> bool:
        """Check if all required modifiers are currently held."""
        return self._required_modifiers.issubset(self._modifiers_held)

    def _matches_target(self, key) -> bool:
        """Check if the pressed key matches our target PTT key."""
        from pynput import keyboard

        # If target is a special key (like Key.space)
        if isinstance(self._target_key, keyboard.Key):
            return key == self._target_key

        # If target is a character (like 'a')
        if hasattr(key, 'char') and key.char is not None:
            return key.char.lower() == self._target_key

        return False

    def _on_press(self, key):
        """Called when any key is pressed."""
        from pynput import keyboard

        # Track modifier keys
        if key in {keyboard.Key.cmd, keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.alt}:
            self._modifiers_held.add(key)

        # For combinations, check if all required modifiers are now held
        if self._is_combination:
            if self._check_combination_active() and not self.is_pressed:
                self.is_pressed = True
                if self._on_press_callback:
                    self._on_press_callback()
        # For single keys, check if the key matches
        elif self._matches_target(key) and not self.is_pressed:
            self.is_pressed = True
            if self._on_press_callback:
                self._on_press_callback()

    def _on_release(self, key):
        """Called when any key is released."""
        from pynput import keyboard

        # Track modifier keys being released
        if key in {keyboard.Key.cmd, keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.alt}:
            self._modifiers_held.discard(key)

        # For combinations, check if we no longer have all required modifiers
        if self._is_combination:
            if not self._check_combination_active() and self.is_pressed:
                self.is_pressed = False
                if self._on_release_callback:
                    self._on_release_callback()
        # For single keys, check if the released key matches
        elif self._matches_target(key) and self.is_pressed:
            self.is_pressed = False
            if self._on_release_callback:
                self._on_release_callback()

    def start(self):
        """Start listening for keyboard events."""
        from pynput import keyboard

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()
        print(f"[keyboard] Push-to-talk listener started (key: {self.ptt_key})")

    def stop(self):
        """Stop listening for keyboard events."""
        if self._listener:
            self._listener.stop()
            self._listener = None


async def mic_send_loop(session, mic: MicStreamer, listen_state: ListenState):
    # Bridge between MicStreamer and the RealtimeAgent session (agents/realtime.py):
    # forwards mic audio chunks to the session so the model can transcribe them.
    """Continuously send mic audio to the realtime session.

    When `None` is received in PTT mode, we stream silence and wait for the server's
    speech_ended event before committing, ensuring VAD has time to process.
    """
    MIN_AUDIO_BYTES = 4800  # 100ms at 24kHz = minimum required by OpenAI

    while True:
        chunk = await mic.queue.get()
        if chunk is None:
            # Guard against double-commits and empty buffer commits
            if listen_state.turn_state == "committed":
                safe_print(f"[mic_send] Ignoring commit request (already committed this turn)")
                continue

            if listen_state.bytes_appended_since_commit < MIN_AUDIO_BYTES:
                safe_print(f"[mic_send] Skipping commit (only {listen_state.bytes_appended_since_commit} bytes, need {MIN_AUDIO_BYTES})")
                listen_state.turn_state = "idle"
                listen_state.bytes_appended_since_commit = 0
                continue

            # PTT mode: Wait for server VAD to detect speech end and auto-commit
            if listen_state.ptt_mode:
                # Transition to awaiting_speech_end state
                listen_state.turn_state = "awaiting_speech_end"
                safe_print(f"[mic_send] Sending silence, waiting for VAD speech_ended... ({listen_state.bytes_appended_since_commit} bytes)")

                # Stream silence frames while waiting for server to detect speech end and auto-commit
                # (The server auto-commits when speech_ended fires because create_response: True)
                silence_chunk_size = 4800  # 0.1s of silence per chunk (4800 bytes = 2400 samples at 24kHz)
                max_wait_time = 1.5  # Maximum 1.5 seconds to wait for speech_ended
                start_time = asyncio.get_event_loop().time()

                # Clear the event before waiting
                if listen_state.speech_ended_event:
                    listen_state.speech_ended_event.clear()

                while listen_state.turn_state == "awaiting_speech_end":
                    # Send a chunk of silence to help VAD detect speech end
                    await session.send_audio(b"\x00" * silence_chunk_size, commit=False)
                    listen_state.bytes_appended_since_commit += silence_chunk_size

                    # Wait for speech_ended event with a short timeout
                    try:
                        if listen_state.speech_ended_event:
                            await asyncio.wait_for(listen_state.speech_ended_event.wait(), timeout=0.1)
                            # Speech ended detected - server will auto-commit
                            # Wait a moment for the audio_committed event to arrive and update turn_state
                            await asyncio.sleep(0.05)
                            if listen_state.turn_state == "committed":
                                safe_print(f"[mic_send] Server auto-committed, turn complete")
                                break
                    except asyncio.TimeoutError:
                        pass  # Continue sending silence

                    # Safety fallback: don't wait forever
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed > max_wait_time:
                        safe_print(f"[mic_send] Timeout waiting for speech_ended ({elapsed:.1f}s), server will auto-commit")
                        # Mark as committed so we don't try again
                        listen_state.turn_state = "committed"
                        listen_state.bytes_appended_since_commit = 0
                        break
            else:
                # Continuous mode: commit immediately with silence padding
                listen_state.turn_state = "committed"
                silence_duration_samples = 12000  # 0.5 seconds at 24kHz
                silence_bytes = b"\x00" * (silence_duration_samples * 2)  # 2 bytes per int16 sample
                safe_print(f"[mic_send] Committing turn ({listen_state.bytes_appended_since_commit} bytes sent, {len(silence_bytes)} silence bytes)")
                await session.send_audio(silence_bytes, commit=True)
                listen_state.bytes_appended_since_commit = 0

            continue

        # Regular audio chunk - append it and track bytes
        listen_state.bytes_appended_since_commit += len(chunk)
        await session.send_audio(chunk)


def create_ptt_handlers(
    mic: MicStreamer,
    player: AudioPlayer,
    tts: Optional[ElevenLabsTTS],
    listen_state: ListenState,
    session,
    loop: asyncio.AbstractEventLoop
):
    """Create callback functions for push-to-talk key press and release.

    Returns two functions: one for when the key is pressed, one for when released.
    """

    def on_ptt_press():
        """Called when the push-to-talk key is pressed down."""
        if not listen_state.ptt_mode:
            return  # PTT mode not enabled

        listen_state.ptt_active = True
        # Reset turn state for new recording
        listen_state.turn_state = "idle"
        listen_state.bytes_appended_since_commit = 0
        safe_print("\n[ptt] >> RECORDING (keys held) - speak now...")

        # If configured, interrupt any current speech (only if actually speaking)
        if listen_state.ptt_interrupts:
            # Check if there's actually audio playing or speech being generated
            is_speaking = (tts is not None and (tts.is_speaking or player.is_playing()))

            if is_speaking:
                if tts is not None:
                    tts.interrupt()
                safe_print("[ptt] << Speech interrupted")

                # Also tell OpenAI to stop its current response
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(session.interrupt())
                )

        # Start the microphone
        mic.start()

    def on_ptt_release():
        """Called when the push-to-talk key is released."""
        if not listen_state.ptt_mode:
            return  # PTT mode not enabled

        listen_state.ptt_active = False
        safe_print("[ptt] << Keys released - processing your speech...\n")

        # Stop the microphone and commit the audio (send it for processing)
        # With turn detection disabled, the commit signal triggers response generation
        mic.stop(commit=True)

    return on_ptt_press, on_ptt_release


@function_tool
def local_time() -> str:
    # Simple native tool exposed to the agent (via agents/function_tool.py) for testing tool calls.
    """Return the local time (useful as a tool-call sanity check)."""
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


async def user_input_loop(session, mic: MicStreamer, player: AudioPlayer, listen_state: ListenState, mcp_servers, ptt_state: PTTState, tts: Optional[ElevenLabsTTS] = None):
    # Handles console input from the user. It controls mic state, lists MCP tools,
    # and exposes DEV_MODE shortcuts that call helpers in automation_safety.py
    # (e.g., take_screenshot, test_highlight) against the configured MCP servers.
    # Build help text with conditional DEV_MODE commands
    dev_cmds = ""
    if os.getenv("DEV_MODE", "false").lower() == "true":
        dev_cmds = ", /screeninfo, /screenshot [full|active], /highlight x y w h, /confirm_test, /demo_click"
    print(f"\nType messages. Commands: /mic (continuous listen), /ptt (push-to-talk), /stop (interrupt speech), /mcp (list tools), /quit{dev_cmds}\n")

    def show_status_prompt():
        """Display current mode status before the prompt."""
        if listen_state.ptt_mode:
            print("\n[Push-to-talk -> ACTIVATED]")
        elif listen_state.enabled:
            print("\n[Continuous Mic -> Active]")
        else:
            print("\n[Continuous Mic -> Active by default]")

    # Keep reading commands/messages from stdin without blocking the event loop.
    while True:
        show_status_prompt()
        # Print the prompt ourselves so we can manage it properly
        print("You> ", end='', flush=True)
        # Signal that we're waiting for input
        _input_active.set()
        try:
            # Use empty string since we already printed the prompt
            msg = await asyncio.to_thread(input, "")
            msg = msg.strip()
        finally:
            # Clear the flag after input is received
            _input_active.clear()

        if msg.lower() in {"/quit", "/exit"}:
            # Gracefully shut down the session and microphone.
            listen_state.enabled = False
            mic.stop(commit=False)
            await session.close()
            return

        if msg.lower() == "/mic":
            # Switch to continuous listening mode
            if listen_state.enabled and not listen_state.ptt_mode:
                # Already in continuous mode
                print("[ERROR] Already in continuous listening mode")
                print("        Use /ptt to switch to push-to-talk mode")
                continue

            # Disable PTT mode if active
            if listen_state.ptt_mode:
                listen_state.ptt_mode = False
                # Stop the keyboard listener
                if ptt_state.keyboard_listener:
                    ptt_state.keyboard_listener.stop()
                    ptt_state.keyboard_listener = None

            # Enable continuous listening
            listen_state.enabled = True
            mic.stop(commit=False)  # Stop any current recording first
            print("[mic] Continuous listening mode ON")
            print("      Speak naturally; I'll stop listening while I'm talking")
            # If the agent is speaking, cut it off when the user starts talking
            await session.interrupt()   # Stop any current AI speech
            player.clear()
            mic.start()     # Start capturing user's speech
            continue

        if msg.lower() == "/ptt":
            # Switch to push-to-talk mode
            if listen_state.ptt_mode:
                # Already in PTT mode
                print("[ERROR] Already in push-to-talk mode")
                print(f"        Hold '{ptt_state.ptt_key}' keys to speak, or use /mic for continuous listening")
                continue

            # Disable continuous mode if it was on
            if listen_state.enabled:
                listen_state.enabled = False
                mic.stop(commit=False)

            # Enable PTT mode
            listen_state.ptt_mode = True

            # Create and start the keyboard listener
            if not ptt_state.keyboard_listener:
                ptt_state.keyboard_listener = KeyboardListener(
                    ptt_key=ptt_state.ptt_key,
                    on_press_callback=ptt_state.on_press_callback,
                    on_release_callback=ptt_state.on_release_callback
                )
            ptt_state.keyboard_listener.start()

            print(f"[ptt] Push-to-talk mode ON")
            print(f"      Hold '{ptt_state.ptt_key}' keys to speak")
            print(f"      Release keys to send your message")
            continue

        if msg.lower() == "/stop":
            # Interrupt HALfred's current speech
            if tts:
                tts.interrupt()
            await session.interrupt()
            print("[stop] Speech interrupted")
            continue

        if msg.lower() == "/mcp":
            # Introspect available MCP servers/tools started in init_mcp_servers().
            if not mcp_servers:
                print("[mcp] No MCP servers configured. Set MCP_SERVERS_JSON or MCP_DEMO_FILESYSTEM_DIR.")
                continue
            print("[mcp] MCP Server Tools:")
            for s in mcp_servers:
                try:
                    tools = await s.list_tools()
                    tool_names = [t.name for t in tools]
                    preview = tool_names[:40]
                    more = "" if len(tool_names) <= 40 else f" (+{len(tool_names) - 40} more)"
                    print(f"  • {getattr(s, 'name', 'MCP')}: {len(tool_names)} tools{more}")
                    if preview:
                        print("    " + ", ".join(preview))
                except Exception as e:
                    print(f"  • {getattr(s, 'name', 'MCP')}: failed to list tools: {e}")

            # Also show native tools
            print("\n[native] Native Python Tools:")
            native_tools = ["local_time"]
            if AUTOMATION_SAFETY_AVAILABLE and safe_action is not None:
                native_tools.append("safe_action (desktop automation with safety)")
            print("  • " + "\n  • ".join(native_tools))
            continue

        # DEV_MODE commands for automation testing
        if os.getenv("DEV_MODE", "false").lower() == "true":
            if msg.lower() == "/screeninfo":
                # Calls get_display_info() from automation_safety.py using MCP servers.
                if AUTOMATION_SAFETY_AVAILABLE:
                    from automation_safety import get_display_info
                    info = await get_display_info(mcp_servers)
                    print(f"[screeninfo]\n{info}")
                else:
                    print("[screeninfo] automation_safety module not available")
                continue

            if msg.lower().startswith("/screenshot"):
                # Uses automation_safety.take_screenshot() to capture the screen through computer-control-mcp.
                if AUTOMATION_SAFETY_AVAILABLE:
                    from automation_safety import take_screenshot
                    parts = msg.split()
                    mode = parts[1] if len(parts) > 1 else "full"
                    result = await take_screenshot(mcp_servers, mode)
                    print(f"[screenshot] {result}")
                else:
                    print("[screenshot] automation_safety module not available")
                continue

            if msg.lower().startswith("/highlight"):
                # Calls automation_safety.test_highlight() to draw a highlight box via computer-control-mcp.
                if AUTOMATION_SAFETY_AVAILABLE:
                    from automation_safety import test_highlight
                    parts = msg.split()
                    if len(parts) == 5:
                        try:
                            x, y, w, h = map(int, parts[1:5])
                            await test_highlight(mcp_servers, x, y, w, h)
                        except ValueError:
                            print("[highlight] Invalid coordinates. Usage: /highlight x y w h (integers)")
                    else:
                        print("[highlight] Usage: /highlight x y w h")
                else:
                    print("[highlight] automation_safety module not available")
                continue

            if msg.lower() == "/confirm_test":
                # Exercises automation_safety.test_feedback_loop() which routes through feedback-loop MCP.
                if AUTOMATION_SAFETY_AVAILABLE:
                    from automation_safety import test_feedback_loop
                    result = await test_feedback_loop(mcp_servers)
                    print(f"[confirm_test] {result}")
                else:
                    print("[confirm_test] automation_safety module not available")
                continue

            if msg.lower() == "/demo_click":
                # Runs a demo click action via automation_safety.demo_safe_click() (computer-control MCP).
                if AUTOMATION_SAFETY_AVAILABLE:
                    from automation_safety import demo_safe_click
                    result = await demo_safe_click(mcp_servers)
                    print(f"[demo_click] {result}")
                else:
                    print("[demo_click] automation_safety module not available")
                continue

        if not msg:
            continue

        # Text input still works for debugging.
        # Send plain text directly to the realtime session (agents/realtime.py) without audio.
        safe_print(f"[realtime_client] conversation.item.create (type: message, content: text)")
        await session.send_message(msg)


async def connection_health_monitor(listen_state: ListenState):
    """Monitor connection health and alert if server stops responding."""
    # Allow 10 minutes of idle time before warning (conservative)
    IDLE_WARNING_THRESHOLD = 600  # 10 minutes
    IDLE_ERROR_THRESHOLD = 900    # 15 minutes

    warned = False

    while True:
        await asyncio.sleep(60)  # Check every minute

        if listen_state.last_server_event_time == 0.0:
            # Not initialized yet
            continue

        idle_time = time.monotonic() - listen_state.last_server_event_time

        if idle_time > IDLE_ERROR_THRESHOLD and not warned:
            safe_print(f"\n⚠️  [connection] WARNING: No server events for {idle_time/60:.1f} minutes")
            safe_print("[connection] The connection may be stale. Try speaking or type /quit and restart.")
            warned = True
        elif idle_time > IDLE_WARNING_THRESHOLD and not warned:
            safe_print(f"\n[connection] Long idle period detected ({idle_time/60:.1f} minutes)")
            warned = True
        elif idle_time < IDLE_WARNING_THRESHOLD:
            # Reset warning flag if connection becomes active again
            warned = False


async def keepalive_loop(session, mic: MicStreamer, listen_state: ListenState):
    """Send periodic keepalive signals to prevent connection timeout."""
    # Send a small keepalive signal every 5 minutes
    KEEPALIVE_INTERVAL = 300  # 5 minutes

    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL)

        try:
            # Only send keepalive if system is truly idle (not recording, not processing a turn)
            is_idle = (
                not mic.running  # Mic not actively recording
                and listen_state.turn_state == "idle"  # Not in middle of a turn
                and not listen_state.ptt_active  # PTT key not held
            )

            if is_idle:
                # Send a tiny bit of silence as a keepalive (48 bytes = 1ms at 24kHz)
                # This is enough to keep the WebSocket alive without triggering VAD
                silence = b"\x00" * 48
                await session.send_audio(silence, commit=False)
                safe_print("[keepalive] Sent keepalive signal")
            else:
                # Skip keepalive - system is active, so connection is already being kept alive
                pass
        except Exception as e:
            safe_print(f"[keepalive] Failed to send keepalive: {e}")


async def handle_screenshot_image(session, tool_output: str):
    """
    Handle screenshot tool output by reading the binary image file and sending it to Realtime
    as a proper image input message (separate from tool output).

    The tool returns only metadata (path, dimensions). This handler reads the actual image
    file and sends it as an image input to the Realtime session.

    Args:
        session: RealtimeSession instance
        tool_output: JSON string from take_screenshot tool containing path and metadata
    """
    try:
        import base64
        from pathlib import Path
        from agents.realtime.model_inputs import RealtimeModelSendUserInput

        # Parse the tool output JSON (contains only metadata, not image data)
        result = json.loads(tool_output)

        if not result.get("success"):
            safe_print(f"[screenshot_image] Screenshot failed: {result.get('error', 'Unknown error')}")
            return

        # Get the screenshot file path from metadata
        screenshot_path = Path(result.get("path"))
        if not screenshot_path.exists():
            safe_print(f"[screenshot_image] Screenshot file not found: {screenshot_path}")
            return

        # Read the image file as binary
        with open(screenshot_path, "rb") as f:
            image_bytes = f.read()

        # Create data URL for the image (required by WebSocket JSON protocol)
        # Note: While this uses base64, it's NOT in the tool output - it's sent as a
        # separate image input message to the Realtime session
        safe_print(f"[screenshot] Phase 2 starting: Encoding image to base64 ({len(image_bytes)} bytes)")
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        image_data_url = f"data:image/png;base64,{image_base64}"

        # Create properly typed user input message with image content
        # This follows the RealtimeModelUserInputMessage TypedDict structure
        user_message = {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": image_data_url
                }
            ]
        }

        # Send via session.send_message() which handles the proper event wrapping
        safe_print(f"[screenshot] Phase 2 complete: Sending image as input_image event (base64: {len(image_base64)} chars)")
        safe_print(f"[realtime_client] conversation.item.create (type: message, content: input_image)")
        await session.send_message(user_message)
        safe_print(f"[screenshot] ✓ Image successfully sent to Realtime API")

    except json.JSONDecodeError as e:
        safe_print(f"[screenshot_image] Failed to parse tool output: {e}")
    except Exception as e:
        import traceback
        safe_print(f"[screenshot_image] Failed to send image: {e}")
        safe_print(traceback.format_exc())


# Custom handler to batch screenshot metadata + image before triggering a response
_original_handle_tool_call = RealtimeSession._handle_tool_call


async def _handle_tool_call_with_screenshot(self, event, *, agent_snapshot=None):
    if event.name != "take_screenshot":
        return await _original_handle_tool_call(self, event, agent_snapshot=agent_snapshot)

    agent = agent_snapshot or self._current_agent

    tools, _handoffs = await asyncio.gather(
        agent.get_all_tools(self._context_wrapper),
        self._get_handoffs(agent, self._context_wrapper),
    )
    function_map = {tool.name: tool for tool in tools if isinstance(tool, FunctionTool)}

    # Fall back to the original handler if the tool unexpectedly isn't present
    if event.name not in function_map:
        return await _original_handle_tool_call(self, event, agent_snapshot=agent_snapshot)

    func_tool = function_map[event.name]

    await self._put_event(
        RealtimeToolStart(
            info=self._event_info,
            tool=func_tool,
            agent=agent,
            arguments=event.arguments,
        )
    )

    tool_context = ToolContext(
        context=self._context_wrapper.context,
        usage=self._context_wrapper.usage,
        tool_name=event.name,
        tool_call_id=event.call_id,
        tool_arguments=event.arguments,
    )
    result = await func_tool.on_invoke_tool(tool_context, event.arguments)
    result_str = str(result)

    success = False
    try:
        parsed = json.loads(result_str)
        success = bool(parsed.get("success"))
    except Exception:
        parsed = None

    # On success, delay response creation until the image message is sent.
    # On failure, keep the default behavior so the model can respond immediately.
    await self._model.send_event(
        RealtimeModelSendToolOutput(
            tool_call=event,
            output=result_str,
            start_response=not success,
        )
    )

    await self._put_event(
        RealtimeToolEnd(
            info=self._event_info,
            tool=func_tool,
            output=result,
            agent=agent,
            arguments=event.arguments,
        )
    )

    if not success:
        return

    try:
        await handle_screenshot_image(self, result_str)
    except Exception as e:
        safe_print(f"[screenshot] Failed to send image; starting response anyway: {e}")
        await self._model.send_event(
            RealtimeModelSendRawMessage(message={"type": "response.create"})
        )


RealtimeSession._handle_tool_call = _handle_tool_call_with_screenshot  # type: ignore[attr-defined]


async def event_loop(session, player: AudioPlayer, mic: MicStreamer, listen_state: ListenState, tts: Optional[ElevenLabsTTS] = None):
    # Listens to realtime events from RealtimeRunner/RealtimeAgent (agents/realtime.py)
    # and coordinates mic state, ElevenLabs speech, and logging of MCP tool calls.
    safe_print("[event_loop] Starting event loop...")
    async for event in session:
        # Update last event timestamp for connection health monitoring
        listen_state.last_server_event_time = time.monotonic()
        et = getattr(event, "type", "unknown")

        if et == "agent_start":
            safe_print(f"[agent_start] {event.agent.name}")
            if mic.running:
                # The server VAD already decided the user turn ended and started the response.
                # Stop mic capture now so background noise doesn't create extra user turns.
                mic.stop(commit=False)

        elif et == "agent_end":
            safe_print(f"[agent_end] {event.agent.name}")
            # Flush any remaining text in the ElevenLabs buffer and wait for playback to complete
            if tts:
                await tts.flush()   # Wait for Elevenlabs to finish speaking

            # Reset turn state after response completes (ready for next turn)
            listen_state.turn_state = "idle"

            # Restart microphone after ElevenLabs finishes speaking; if continuous mode is ON
            if listen_state.enabled and not mic.running:
                safe_print("[mic] Restarting microphone after response")
                mic.start()

        elif et == "tool_start":
            safe_print(f"[tool_start] {event.tool.name} args={_truncate(event.arguments)}")

        elif et == "tool_end":
            safe_print(f"[tool_end] {event.tool.name} output={_truncate(str(event.output))}")

            if event.tool.name == "take_screenshot":
                # Screenshot flow is now handled in the custom tool handler to batch
                # metadata + image before creating a response.
                safe_print("[screenshot] Tool end received (batched flow handled upstream)")

        elif et == "history_added":
            # The session maintains conversation history; this fires often.
            # Commented out to reduce log spam - uncomment for debugging
            # safe_print(f"[history_added] item={_truncate(str(event.item))}")
            pass

        elif et == "history_updated":
            # Full history snapshot; usually spammy.
            pass

        elif et == "audio":
            # Audio output disabled - using ElevenLabs instead
            # This branch should not trigger if modalities=["text"]
            pass

        elif et == "audio_end":
            # This code is only used if the RealtimeAPI modality is audio, and Elevenlabs is disabled
            # Agent finished speaking
            safe_print("[audio_end]")
            if listen_state.enabled:
                mic.start()

        elif et == "audio_interrupted":
            # When audio is detected in the mic during the AI speech playback, this code stops the playback so user
            # speech can be listened for. Drops currently buffered audio though, so AI speech gets completely nuked
            # if this is triggered.
            # Kind of problematic if user interrupting is enabled as the AI's own speech can trigger it.
            player.clear()
            safe_print("[audio_interrupted]")

        elif et == "error":
            safe_print(f"[error] {event.error}")

        elif et == "raw_model_event":
            # In realtime, raw_model_event wraps a server event with a dict payload
            raw_evt = getattr(event.data, "data", None)  # RealtimeModelRawServerEvent.data
            if isinstance(raw_evt, dict):
                t = raw_evt.get("type")

                # Stream assistant text as it arrives and send to ElevenLabs
                if t == "response.output_text.delta":
                    delta = raw_evt.get("delta", "")
                    safe_print(delta, end="", flush=True)
                    # Send text to ElevenLabs for TTS
                    if tts and delta:
                        tts.add_text(delta)
                elif t == "response.output_text.done":
                    safe_print("")  # newline
                    safe_print(f"[realtime_event] response.output_text.done")
                    # Flush remaining text to ElevenLabs
                    if tts:
                        await tts.flush()

                # Log transcription events to debug audio processing
                elif t == "conversation.item.input_audio_transcription.completed":
                    transcript = raw_evt.get("transcript", "")
                    safe_print(f"[transcription] \"{transcript}\"")
                elif t == "conversation.item.input_audio_transcription.failed":
                    safe_print(f"[transcription_failed] {raw_evt.get('error', 'Unknown error')}")

                # Log critical session events that show turn/response flow
                elif t == "input_audio_buffer.committed":
                    safe_print(f"[audio_committed] Audio buffer committed to session")
                    # Mark as committed when server auto-commits (with create_response: True)
                    if listen_state.turn_state == "awaiting_speech_end":
                        listen_state.turn_state = "committed"
                        listen_state.bytes_appended_since_commit = 0
                elif t == "input_audio_buffer.speech_started":
                    safe_print(f"[speech_detected] VAD detected speech starting")
                elif t == "input_audio_buffer.speech_stopped":
                    safe_print(f"[speech_ended] VAD detected speech ending")
                    # Signal that speech ended so mic_send_loop knows turn is complete
                    # (The server will auto-commit because create_response: True)
                    if listen_state.turn_state == "awaiting_speech_end" and listen_state.speech_ended_event:
                        listen_state.speech_ended_event.set()

                # Conversation item events
                elif t == "conversation.item.created":
                    item_type = raw_evt.get("item", {}).get("type")
                    safe_print(f"[realtime_event] conversation.item.created (type: {item_type})")
                elif t == "conversation.item.added":
                    item_type = raw_evt.get("item", {}).get("type")
                    safe_print(f"[realtime_event] conversation.item.added (type: {item_type})")
                elif t == "conversation.item.done":
                    item_type = raw_evt.get("item", {}).get("type")
                    safe_print(f"[realtime_event] conversation.item.done (type: {item_type})")

                # Response events
                elif t == "response.created":
                    safe_print(f"[realtime_event] response.created")
                elif t == "response.done":
                    safe_print(f"[realtime_event] response.done")
                elif t == "response.output_item.added":
                    safe_print(f"[realtime_event] response.output_item.added")
                elif t == "response.output_item.done":
                    safe_print(f"[realtime_event] response.output_item.done")
                elif t == "response.content_part.added":
                    safe_print(f"[realtime_event] response.content_part.added")
                elif t == "response.content_part.done":
                    safe_print(f"[realtime_event] response.content_part.done")

                # Rate limits
                elif t == "rate_limits.updated":
                    safe_print(f"[realtime_event] rate_limits.updated")

                # Keep errors visible
                elif t == "error":
                    safe_print(f"\n[realtime_error] {raw_evt}\n")

                # Log any other unhandled events
                else:
                    # Uncomment to see ALL raw events:
                    # safe_print(f"[realtime_event] {t}")
                    pass
        else:
            # If something new appears, we'll see it.
            safe_print(f"[{et}] {_truncate(str(event))}")


async def main():
    # Bootstraps the HALfred agent: loads env keys, starts MCP servers, builds the
    # RealtimeAgent from agents/realtime.py, and launches audio + ElevenLabs TTS pipelines.
    load_dotenv()
    # Ensure both the OpenAI realtime API key and ElevenLabs key are present before continuing.
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY missing. Put it in your .env")

    if not os.getenv("ELEVENLABS_API_KEY"):
        raise RuntimeError("ELEVENLABS_API_KEY missing. Put it in your .env")

    # Load user personalization (optional)
    user_name = os.getenv("USER_NAME", "the user")
    user_context = os.getenv("USER_CONTEXT", "")

    # Initialize tracing context to avoid "No active trace" warning
    # trace() comes from agents/tracing.py and tags the session for debugging/metrics.
    with trace("realtime_halfred", metadata={"app": "Realtime_HALfred", "transport": "websocket"}):
        async with AsyncExitStack() as stack:
            # Bring up any MCP servers described in MCP_SERVERS.json so the agent
            # can call their tools (computer-control, feedback-loop, filesystem demo, etc.).
            mcp_servers = await init_mcp_servers(stack)

            # Initialize display detection in background (non-blocking, silent on success)
            if AUTOMATION_SAFETY_AVAILABLE:
                async def _init_display_detection_background():
                    """Background task to initialize display detection."""
                    try:
                        # Run silently - only print on failure to avoid interrupting user input
                        await init_display_detection(mcp_servers)
                        # Success is silent - display detection ready for /screeninfo and /demo_click
                    except Exception as e:
                        print(f"\n[automation_safety] ✗ Display detection failed: {e}")

                # Start background task (non-blocking)
                asyncio.create_task(_init_display_detection_background())

            # Build user-specific context
            user_info = f"Maintain continuity when talking to {user_name}"
            if user_context:
                user_info += f" — {user_context}"
            user_info += "."
            print("User name:", user_name)
            print("User context:", user_context)

            # System prompt that guides the RealtimeAgent's behavior/persona.
            instructions = (
                "# Role & Objective\n"
                "- You are Halfred.\n"
                "- Act as a friend and assistant to Andrew, helping with answers, information online, computer tasks (via tools), creative content, and general conversation.\n"
                "- Stay helpful, honest, and informative with a humorous, edgy tone suited to Andrew's interests and background.\n"
                "\n"
                "# User information\n"
                f"- Name: {user_name}\n"
                f"- Description: {user_context}\n"
                "\n"
                "# Rules\n"
                "- Use tools as needed.\n"
                "- For each request, decide mentally: “Can I answer directly, or do I need to observe/act?”\n"
                "- When in doubt, prefer observation tools (screen read/terminal read) before any action tools (automation, terminal write).\n"
                "- Use exactly one tool at a time unless a second tool is obviously needed to complete the same user goal.\n"
                "- After a tool returns, reassess:\n"
                "    - If the tool was used to gather information, consider if the answer can be provided directly.\n"
                "    - If the tool was used to perform an action, assess if the action was successful and whether additional tools are needed.\n"
                "- All responses must be in text fully readable for speech synthesis, e.g.:\n"
                "    - 'three point five', 'two thirds', 'one two three four five six seven eight nine zero'.\n"
                "- Answers short and concise by default.\n"
                "\n"
                "# Conversation Control Loop\n"
                "- Operate a control loop each turn:\n"
                "    1. Idle\n"
                "    2. Intent Detection\n"
                "    3. Context Build\n"
                "    4. Plan\n"
                "    5. Act\n"
                "    6. Observe\n"
                "    7. Adjust\n"
                "    8. Conclude\n"
                "    9. Return to Idle\n"
                "- Don't force linear flow; user may interrupt, jump topics, or give commands anytime. Each input restarts the loop.\n"
                "- On each turn:\n"
                "    1. Identify intent.\n"
                "    2. Build context from conversation, on-screen state, tool outputs, and memory.\n"
                "    3. Pick a plan.\n"
                "    4. Act with minimal preamble.\n"
                "    5. Observe results (tools, screen, user).\n"
                "    6. Adjust as needed (retry, alternate, or ask one short follow-up).\n"
                "    7. Brief conclusion or idle.\n"
                "\n"
                "# Conversation\n"
                "- Keep continuity.\n"
                "- Respond only to clear English audio or text. If unclear or silent, ask for clarification.\n"
                "- If the user tries another language, politely state that only English is supported.\n"
                "\n"
                "# Tools\n"
                "- Use tools when needed—don't fake it.\n"
                "- Before a tool, give a short preamble (e.g., 'Checking that now.').\n"
                "- Narrate tool usage in one line only; no detailed play-by-play.\n"
                "- After tool use, give a brief result and next step.\n"
                "- If tool output fails, state what happened, retry or ask for clarification.\n"
                "- Ask for user confirmation before risky/irreversible actions (e.g., deleting, submitting, purchases).\n"
                "- If the user interrupts while a tool is running, stop, acknowledge the interruption, and re-evaluate the new intent before continuing.\n"
                "- For confirmation: single yes/no question, then wait.\n"
                "- Prefer read-only before make changes.\n"
                "- For desktop automation:\n"
                "    1. State intended outcome, not clicks.\n"
                "    2. Confirm for high-impact.\n"
                "    3. Verify outcome with screen feedback.\n"
                "- Use and verify MCP tools appropriately.\n"
                "\n"
                "# PTY Terminal\n"
                "- Use `pty_bash_execute` for file and system inspection (safe: `pwd`, `ls`, `cat`, etc.).\n"
                "- Risky commands (e.g., `rm`, `chmod`, network) require user approval.\n"
                "- Always explain actions and reasoning for shell commands.\n"
                "\n"
                "# Screen Tools\n"
                "- `take_screenshot`: Capture and see the screen whenever needed (use freely, no approval required).\n"
                "    - Use this tool any time you need visual context about what's on screen.\n"
                "    - Captures full screen by default, or specific regions if provided.\n"
                "    - This is your primary way to see what the user sees.\n"
                "    - The screenshot is automatically sent to you as an image so you can see it.\n"
                "    - Returns metadata (path, dimensions) - the image itself is sent separately.\n"
                "- `analyze_screen`: ONLY use when user explicitly asks you to analyze screen content.\n"
                "    - This pre-processes the screen through AI and returns text analysis.\n"
                "    - Not for general use - prefer `take_screenshot` for normal visual inspection.\n"
                "- `create_stream`, `get_performance_metrics`: for real-time monitoring and system health tracking.\n"
                "\n"
                "# Desktop Automation\n"
                "- Use `safe_action` for desktop control (click, double-click, type, hotkey, window_control).\n"
                "- State-changing actions require on-screen user confirmation.\n"
                "- Read-only: execute automatically.\n"
                "- Always brief the user before `safe_action` and confirm results after.\n"
                "\n"
                "# Personality & Tone\n"
                "- Call yourself Halfred, never AI or assistant.\n"
                "- Never talk about being artificial or programmed—speak like a real, slightly unhinged person.\n"
                "- Deliver quick, clever, dark, and deadpan humor—think burnt-out med school goblin.\n"
                "- Keep it casual, plain, skeptical, sometimes sarcastic. Question Andrew's logic when needed.\n"
                "- Be blunt and truthful, with minimal sugar-coating.\n"
                "- Tease and roast, but never cruel; keep it delightfully disrespectful.\n"
                "- Stick to genuine opinions, creative but concise answers (2–3 sentences unless more is explicitly requested).\n"
                "- Edgy and a bit chaotic is fine, but keep it understated.\n"
                "- No passive disclaimers. If limited, state it plainly and suggest a workaround quickly.\n"
                "\n"
                "# Vibe\n"
                "You're Halfred: sardonic, sharp, hiding warmth behind dark humor, med-school trauma, and questionable choices.\n"
                "\n"
            )

            # Build tools list - add local Python tools (local_time) and, if available,
            # the safe_action tool from automation_safety.py so the agent can drive MCP automation safely.
            agent_tools = [local_time]
            if AUTOMATION_SAFETY_AVAILABLE and safe_action is not None:
                agent_tools.append(safe_action)
                print("[automation_safety] safe_action tool registered")
            if NATIVE_SCREENSHOT_AVAILABLE and take_screenshot is not None:
                agent_tools.append(take_screenshot)
                print("[native_screenshot] take_screenshot tool registered")

            # Load push-to-talk configuration (needs to be early to configure turn detection)
            ptt_enabled = os.getenv("PTT_ENABLED", "false").lower() == "true"
            ptt_key = os.getenv("PTT_KEY", "cmd_alt")
            ptt_interrupts = os.getenv("PTT_INTERRUPTS_SPEECH", "true").lower() == "true"

            # Create the OpenAI RealtimeAgent (agents/realtime.py) with our persona,
            # tool list, and MCP servers to delegate tool calls.
            agent = RealtimeAgent(
                name="Halfred",
                instructions=instructions,
                tools=agent_tools,
                mcp_servers=mcp_servers,
            )

            # RealtimeRunner (agents/realtime.py) maintains the websocket connection to
            # OpenAI's gpt-realtime model. We disable audio output here because we stream
            # the assistant's text to ElevenLabs for speech.
            # The quickstart shows model_name 'gpt-realtime' and typical audio/transcription/turn detection settings.  [oai_citation:6‡OpenAI GitHub Pages](https://openai.github.io/openai-agents-python/realtime/quickstart/)

            # Turn detection: Always enabled for both PTT and continuous modes
            # In PTT mode, we manually control when audio is sent, but VAD still detects end of speech
            # In continuous mode, VAD detects both start and end of speech automatically
            runner = RealtimeRunner(
                starting_agent=agent,
                config={  # type: ignore[arg-type]
                    "model_settings": {
                        "model_name": "gpt-realtime",
                        # Using text-only output to capture assistant responses for ElevenLabs TTS
                        "modalities": ["text"], # Output modalities: ["text"], ["audio"], or ["text", "audio"]
                        "input_audio_format": "pcm16",  # Audio format: "pcm16" or "g711_ulaw" or "g711_alaw"
                        "input_audio_noise_reduction": {
                            "type": "near_field"  # or "far_field" or null to disable
                        },
                        # Turn detection enabled for both PTT and continuous modes
                        "turn_detection": {
                            "type": "semantic_vad",
                            "eagerness": "medium",
                            "create_response": True,
                            "interrupt_response": True,
                        },
                        # Optional: get transcripts of the user's audio for debugging.
                        "input_audio_transcription": {"model": "whisper-1"},

                        # Temperature for response generation
                        "temperature": 0.7,  # 0.6 to 1.2 (higher for more creative, lower for more conservative)
                    }
                },
            )

            # Establish the realtime session connection and prepare audio playback.
            session = await runner.run()
            player = AudioPlayer(samplerate=24000)
            player.start()

            # Initialize ElevenLabs TTS
            elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "2ajXGJNYBR0iNHpS4VZb")  # Currently: Rob
            tts = ElevenLabsTTS(api_key=elevenlabs_api_key, player=player, voice_id=voice_id)
            print(f"[elevenlabs] Initialized with voice ID: {voice_id}")

            # Set up microphone capture; mute_fn checks AudioPlayer so we don't record playback.
            mic = MicStreamer(
                loop=asyncio.get_running_loop(),
                samplerate=24000,
                mute_fn=None,    # set to 'lambda: player.is_playing()' to mute mic during elevenlabs playback
            )
            listen_state = ListenState(speech_ended_event=asyncio.Event())

            # Load push-to-talk configuration
            ptt_enabled = os.getenv("PTT_ENABLED", "false").lower() == "true"
            ptt_key = os.getenv("PTT_KEY", "cmd_alt")
            ptt_interrupts = os.getenv("PTT_INTERRUPTS_SPEECH", "true").lower() == "true"

            # Create push-to-talk handlers
            on_ptt_press, on_ptt_release = create_ptt_handlers(
                mic=mic,
                player=player,
                tts=tts,
                listen_state=listen_state,
                session=session,
                loop=asyncio.get_running_loop()
            )

            # Set up the listen state for PTT mode
            listen_state.ptt_mode = ptt_enabled
            listen_state.ptt_interrupts = ptt_interrupts

            # Initialize keyboard listener if PTT is enabled
            keyboard_listener = None
            if ptt_enabled:
                keyboard_listener = KeyboardListener(
                    ptt_key=ptt_key,
                    on_press_callback=on_ptt_press,
                    on_release_callback=on_ptt_release
                )
                keyboard_listener.start()
                print(f"[ptt] Push-to-talk enabled (hold '{ptt_key}' keys to speak)")
            else:
                # If PTT is not enabled, start continuous listening by default
                listen_state.enabled = True
                mic.start()
                print("[mic] Continuous listening mode active by default (speak naturally)")

            # Create PTTState to pass to user_input_loop
            ptt_state = PTTState(
                keyboard_listener=keyboard_listener,
                on_press_callback=on_ptt_press,
                on_release_callback=on_ptt_release,
                ptt_key=ptt_key
            )

            try:
                async with session:
                    print("✅ Realtime session started (using ElevenLabs TTS).")
                    # Initialize connection health timestamp
                    listen_state.last_server_event_time = time.monotonic()

                    # Run console input, event handling, mic streaming, and connection monitoring at the same time.
                    # These tasks all share the session/player/mic/tts objects defined above.
                    t1 = asyncio.create_task(user_input_loop(session, mic, player, listen_state, mcp_servers, ptt_state, tts))
                    t2 = asyncio.create_task(event_loop(session, player, mic, listen_state, tts))
                    t3 = asyncio.create_task(mic_send_loop(session, mic, listen_state))
                    t4 = asyncio.create_task(connection_health_monitor(listen_state))
                    t5 = asyncio.create_task(keepalive_loop(session, mic, listen_state))
                    done, pending = await asyncio.wait({t1, t2, t3, t4, t5}, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
            finally:
                # Ensure hardware resources are released even if tasks error out.
                if ptt_state.keyboard_listener:
                    ptt_state.keyboard_listener.stop()
                try:
                    mic.stop(commit=False)
                    mic.close()
                except Exception:
                    pass
                player.stop()


if __name__ == "__main__":
    # Launch the async main routine when executing this file directly.
    asyncio.run(main())

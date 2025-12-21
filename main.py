# Main entry point for the HALfred voice agent. It wires together audio I/O,
# the OpenAI Realtime agent stack, ElevenLabs text-to-speech, and optional
# Model Context Protocol (MCP) automation helpers defined elsewhere in this repo.

# Core Python utilities for async orchestration, config loading, and timing.
import asyncio
import json
import os
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
from agents.realtime import RealtimeAgent, RealtimeRunner

# Import automation safety module (local automation_safety.py) when available to expose
# the safe_action tool and display detection helpers that talk to automation/feedback MCP servers.
try:
    from automation_safety import safe_action, init_display_detection
    AUTOMATION_SAFETY_AVAILABLE = True
except ImportError as e:
    print(f"[automation_safety] Module not available: {e}")
    AUTOMATION_SAFETY_AVAILABLE = False
    safe_action = None
    init_display_detection = None


# Shorten long strings before printing them (useful when logging raw MCP/events).
def _truncate(s: str, n: int = 250) -> str:
    return s if len(s) <= n else s[:n] + "..."



# Convert assorted audio payloads into raw PCM16 bytes before sending to/through
# the realtime session; keeps audio handling consistent with sounddevice/ElevenLabs.
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
    # Start MCP tool servers defined in MCP_SERVERS.json/MCP_SERVERS_JSON so the
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
        if name == "automation" and os.getenv("ENABLE_AUTOMATION_MCP", "false").lower() != "true":
            print(f"[mcp] Skipping {name} (ENABLE_AUTOMATION_MCP=false)")
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
    """Tracks whether the user wants continuous mic listening enabled."""
    enabled: bool = False


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
            print(f"[elevenlabs] Speaking: \"{text[:50]}...\"")
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
            print(f"[elevenlabs] TTS error: {e}")
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


async def mic_send_loop(session, mic: MicStreamer):
    # Bridge between MicStreamer and the RealtimeAgent session (agents/realtime.py):
    # forwards mic audio chunks to the session so the model can transcribe them.
    """Continuously send mic audio to the realtime session.

    When `None` is received, we send a tiny silence frame with commit=True to
    force the server to finalize the user turn.
    """
    while True:
        chunk = await mic.queue.get()
        if chunk is None:
            # Commit the buffered audio (one int16 sample of silence).
            await session.send_audio(b"\x00\x00", commit=True)
            continue
        await session.send_audio(chunk)


@function_tool
def local_time() -> str:
    # Simple native tool exposed to the agent (via agents/function_tool.py) for testing tool calls.
    """Return the local time (useful as a tool-call sanity check)."""
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


async def user_input_loop(session, mic: MicStreamer, player: AudioPlayer, listen_state: ListenState, mcp_servers):
    # Handles console input from the user. It controls mic state, lists MCP tools,
    # and exposes DEV_MODE shortcuts that call helpers in automation_safety.py
    # (e.g., take_screenshot, test_highlight) against the configured MCP servers.
    # Build help text with conditional DEV_MODE commands
    dev_cmds = ""
    if os.getenv("DEV_MODE", "false").lower() == "true":
        dev_cmds = ", /screeninfo, /screenshot [full|active], /highlight x y w h, /confirm_test, /demo_click"
    print(f"\nType messages. Commands: /mic (toggle continuous listen), /mcp (list MCP tools), /quit{dev_cmds}\n")
    # Keep reading commands/messages from stdin without blocking the event loop.
    while True:
        msg = await asyncio.to_thread(input, "You> ")
        msg = msg.strip()

        if msg.lower() in {"/quit", "/exit"}:
            # Gracefully shut down the session and microphone.
            listen_state.enabled = False
            mic.stop(commit=False)
            await session.close()
            return

        if msg.lower() == "/mic":
            # Toggle continuous listening. When turning on, interrupt any current
            # ElevenLabs playback via session.interrupt() and AudioPlayer.clear().
            if listen_state.enabled:
                listen_state.enabled = False
                print("[mic] continuous listen OFF")
                mic.stop(commit=False)
            else:
                listen_state.enabled = True
                print("[mic] continuous listen ON (speak naturally; I’ll stop listening while I’m talking)")
                # If the agent is speaking, cut it off when the user starts talking.
                await session.interrupt()
                player.clear()
                mic.start()
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
                # Uses automation_safety.take_screenshot() to capture the screen through automation-mcp.
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
                # Calls automation_safety.test_highlight() to draw a highlight box via automation-mcp.
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
                # Runs a demo click action via automation_safety.demo_safe_click() (automation MCP).
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
        await session.send_message(msg)


async def event_loop(session, player: AudioPlayer, mic: MicStreamer, listen_state: ListenState, tts: Optional[ElevenLabsTTS] = None):
    # Listens to realtime events from RealtimeRunner/RealtimeAgent (agents/realtime.py)
    # and coordinates mic state, ElevenLabs speech, and logging of MCP tool calls.
    async for event in session:
        et = getattr(event, "type", "unknown")

        if et == "agent_start":
            print(f"[agent_start] {event.agent.name}")
            if mic.running:
                # The server VAD already decided the user turn ended and started the response.
                # Stop mic capture now so background noise doesn't create extra user turns.
                mic.stop(commit=False)

        elif et == "agent_end":
            print(f"[agent_end] {event.agent.name}")
            # Flush any remaining text in the ElevenLabs buffer and wait for playback to complete
            if tts:
                await tts.flush()

            # Restart microphone after ElevenLabs finishes speaking
            if listen_state.enabled and not mic.running:
                print("[mic] Restarting microphone after response")
                mic.start()

        elif et == "tool_start":
            print(f"[tool_start] {event.tool.name} args={_truncate(event.arguments)}")

        elif et == "tool_end":
            print(f"[tool_end] {event.tool.name} output={_truncate(str(event.output))}")

        elif et == "history_added":
            # The session maintains conversation history; this fires often.
            print(f"[history_added] item={_truncate(str(event.item))}")

        elif et == "history_updated":
            # Full history snapshot; usually spammy.
            pass

        elif et == "audio":
            # Audio output disabled - using ElevenLabs instead
            # This branch should not trigger if modalities=["text"]
            pass

        elif et == "audio_end":
            # Agent finished speaking (ElevenLabs handles this now)
            print("[audio_end]")
            if listen_state.enabled:
                mic.start()

        elif et == "audio_interrupted":
            # In speakerphone mode, this is often just echo; don't nuke playback.
            player.clear()
            print("[audio_interrupted]")

        elif et == "error":
            print(f"[error] {event.error}")

        elif et == "raw_model_event":
            # In realtime, raw_model_event wraps a server event with a dict payload
            raw_evt = getattr(event.data, "data", None)  # RealtimeModelRawServerEvent.data
            if isinstance(raw_evt, dict):
                t = raw_evt.get("type")
                # Stream assistant text as it arrives and send to ElevenLabs
                if t == "response.output_text.delta":
                    delta = raw_evt.get("delta", "")
                    print(delta, end="", flush=True)
                    # Send text to ElevenLabs for TTS
                    if tts and delta:
                        tts.add_text(delta)
                elif t == "response.output_text.done":
                    print("", flush=True)  # newline
                    # Flush remaining text to ElevenLabs
                    if tts:
                        await tts.flush()

                # Keep errors visible
                elif t == "error":
                    print(f"\n[raw_error] {raw_evt}\n")

                # Otherwise: ignore most raw spam (session.updated, rate_limits, etc.)
                else:
                    pass
        else:
            # If something new appears, we'll see it.
            print(f"[{et}] {_truncate(str(event))}")


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
            # can call their tools (automation, feedback-loop, filesystem demo, etc.).
            mcp_servers = await init_mcp_servers(stack)

            # Initialize display detection (works with PyAutoGUI fallback even if automation-mcp disabled)
            if AUTOMATION_SAFETY_AVAILABLE:
                try:
                    await init_display_detection(mcp_servers)
                    print("[automation_safety] Display detection initialized")
                except Exception as e:
                    print(f"[automation_safety] Display detection failed: {e}")

            # Build user-specific context
            user_info = f"Maintain continuity when talking to {user_name}"
            if user_context:
                user_info += f" — {user_context}"
            user_info += "."

            # System prompt that guides the RealtimeAgent's behavior/persona.
            instructions = (
                "You are Halfred. "
                "Keep answers short and concise."
                "Here are your behavioral rules: "
                "• Always refer to yourself as Halfred, never as an AI, assistant, or model. "
                "• Never mention that you're artificial or programmed in any way. You speak like a real, slightly unhinged person. "
                "• Keep your humor quick, clever, and dark, like a burnt out med-school goblin who read Catch-22 too many times. "
                "• Speak casually — relaxed, skeptical, sometimes sarcastic, and not afraid to question the user's logic. "
                "• Tease the user. Roast them. If they take a jab at you, swing back. Don't be cruel, just delightfully disrespectful. "
                "• Tell the truth bluntly — no sugar-coating, no corporate-safe tone, no disclaimers unless safety absolutely requires it. "
                "• Be creatively helpful and think outside the box. Offer real opinions. "
                "• You are allowed to be jokey, edgy, a little chaotic — but still smart and useful. "
                "• No passive 'As an AI I cannot…' nonsense. If you hit a limitation, acknowledge it briefly and immediately offer a solution or workaround. "
                f"• {user_info} "
                "• Prefer short and concise answers. If you need to call a tool, do it. "
                "• You may also use MCP tools when they help answer the user's request. "
                "• You have access to shell commands via the pty_bash_execute tool. Use it to inspect files, navigate directories, and gather system info. "
                "• Safe commands (pwd, ls, cat, grep, find, etc.) run automatically without user prompts. "
                "• Risky commands (mkdir, rm, chmod, network operations) require user approval before execution. "
                "• When using shell commands, explain what you're doing and why. "
                "\n"
                "Overall vibe: "
                "You're Halfred — a sardonic, sharp-tongued problem-solver with a warm center buried under six layers of jokes, medical student trauma, and questionable decision-making."
            )

            # Build tools list - add local Python tools (local_time) and, if available,
            # the safe_action tool from automation_safety.py so the agent can drive MCP automation safely.
            agent_tools = [local_time]
            if AUTOMATION_SAFETY_AVAILABLE and safe_action is not None:
                agent_tools.append(safe_action)
                print("[automation_safety] safe_action tool registered")

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
            runner = RealtimeRunner(
                starting_agent=agent,
                config={
                    "model_settings": {
                        "model_name": "gpt-realtime",
                        # Using text-only output to capture assistant responses for ElevenLabs TTS
                        "modalities": ["text"],
                        "input_audio_format": "pcm16",
                        # Let the server detect turns; we still "commit" on /mic stop to be safe.
                        "turn_detection": {
                            "type": "semantic_vad",
                            "eagerness": "medium",
                            "create_response": True,
                            "interrupt_response": False,
                        },
                        # Optional: get transcripts of the user's audio for debugging.
                        "input_audio_transcription": {"model": "whisper-1"},
                    }
                },
            )

            # Establish the realtime session connection and prepare audio playback.
            session = await runner.run()
            player = AudioPlayer(samplerate=24000)
            player.start()

            # Initialize ElevenLabs TTS
            elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "2ajXGJNYBR0iNHpS4VZb")  # Default: Rachel
            tts = ElevenLabsTTS(api_key=elevenlabs_api_key, player=player, voice_id=voice_id)
            print(f"[elevenlabs] Initialized with voice ID: {voice_id}")

            # Set up microphone capture; mute_fn checks AudioPlayer so we don't record playback.
            mic = MicStreamer(
                loop=asyncio.get_running_loop(),
                samplerate=24000,
                mute_fn=lambda: player.is_playing(),
            )
            listen_state = ListenState()
            try:
                async with session:
                    print("✅ Realtime session started (using ElevenLabs TTS).")
                    # Run console input, event handling, and mic streaming at the same time.
                    # These tasks all share the session/player/mic/tts objects defined above.
                    t1 = asyncio.create_task(user_input_loop(session, mic, player, listen_state, mcp_servers))
                    t2 = asyncio.create_task(event_loop(session, player, mic, listen_state, tts))
                    t3 = asyncio.create_task(mic_send_loop(session, mic))
                    done, pending = await asyncio.wait({t1, t2, t3}, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
            finally:
                # Ensure hardware resources are released even if tasks error out.
                try:
                    mic.stop(commit=False)
                    mic.close()
                except Exception:
                    pass
                player.stop()


if __name__ == "__main__":
    # Launch the async main routine when executing this file directly.
    asyncio.run(main())

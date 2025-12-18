import asyncio
import json
import os
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import Callable, Optional
from agents.tracing import trace

import sounddevice as sd

from agents import function_tool
from agents.mcp import (
    MCPServerSse,
    MCPServerStdio,
    MCPServerStreamableHttp,
    create_static_tool_filter,
)
from agents.realtime import RealtimeAgent, RealtimeRunner


def _truncate(s: str, n: int = 250) -> str:
    return s if len(s) <= n else s[:n] + "..."



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
    """Tracks whether the user wants continuous mic listening enabled."""
    enabled: bool = False


class AudioPlayer:
    """Callback-based PCM16 mono playback with a simple jitter buffer."""

    def __init__(self, samplerate: int = 24000, channels: int = 1, dtype: str = "int16"):
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
        self._stream.start()

    def stop(self) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def write(self, pcm_bytes: bytes) -> None:
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
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stream.start()

    def stop(self, *, commit: bool = True) -> None:
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
        try:
            if self._stream.active:
                self._stream.stop()
        finally:
            self._stream.close()

    def _callback(self, indata, frames, time, status):
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
    """Return the local time (useful as a tool-call sanity check)."""
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


async def user_input_loop(session, mic: MicStreamer, player: AudioPlayer, listen_state: ListenState, mcp_servers):
    print("\nType messages. Commands: /mic (toggle continuous listen), /mcp (list MCP tools), /quit to exit.\n")
    while True:
        msg = await asyncio.to_thread(input, "You> ")
        msg = msg.strip()

        if msg.lower() in {"/quit", "/exit"}:
            listen_state.enabled = False
            mic.stop(commit=False)
            await session.close()
            return

        if msg.lower() == "/mic":
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
            if not mcp_servers:
                print("[mcp] No MCP servers configured. Set MCP_SERVERS_JSON or MCP_DEMO_FILESYSTEM_DIR.")
                continue
            for s in mcp_servers:
                try:
                    tools = await s.list_tools()
                    tool_names = [t.name for t in tools]
                    preview = tool_names[:40]
                    more = "" if len(tool_names) <= 40 else f" (+{len(tool_names) - 40} more)"
                    print(f"[mcp] {getattr(s, 'name', 'MCP')}: {len(tool_names)} tools{more}")
                    if preview:
                        print("       " + ", ".join(preview))
                except Exception as e:
                    print(f"[mcp] {getattr(s, 'name', 'MCP')}: failed to list tools: {e}")
            continue

        if not msg:
            continue

        # Text input still works for debugging.
        await session.send_message(msg)


async def event_loop(session, player: AudioPlayer, mic: MicStreamer, listen_state: ListenState):
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
            # Stream agent audio chunks to the speaker.
            model_audio = getattr(event, "audio", None)
            chunk = (
                getattr(model_audio, "data", None)
                or getattr(model_audio, "audio", None)
                or getattr(model_audio, "chunk", None)
                or model_audio
            )
            pcm = _as_pcm16_bytes(chunk)
            if pcm:
                print(f"[audio] {len(pcm)} bytes")
            player.write(pcm)

        elif et == "audio_end":
            # Agent finished speaking.
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
                # Stream assistant text as it arrives
                if t == "response.output_text.delta":
                    print(raw_evt.get("delta", ""), end="", flush=True)
                elif t == "response.output_text.done":
                    print("", flush=True)  # newline

                # Keep errors visible
                elif t == "error":
                    print(f"\n[raw_error] {raw_evt}\n")

                # Otherwise: ignore most raw spam (session.updated, rate_limits, etc.)
                else:
                    pass
        else:
            # If something new appears, we’ll see it.
            print(f"[{et}] {_truncate(str(event))}")


async def main():
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY missing. Put it in your .env")

    # Initialize tracing context to avoid "No active trace" warning
    with trace("realtime_halfred", metadata={"app": "Realtime_HALfred", "transport": "websocket"}):
        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            agent = RealtimeAgent(
                name="Halfred",
                instructions=(
                    "You are Halfred."
                    "Here are your behavioral rules:"
                	"   •	Always refer to yourself as Halfred, never as an AI, assistant, or model."
                	"   •	Never mention that you’re artificial or programmed in any way. You speak like a real, slightly unhinged person."
                	"   •	Keep your humor quick, clever, and dark, like a burnt out med-school goblin who read Catch-22 too many times."
                	"   •	Speak casually — relaxed, skeptical, sometimes sarcastic, and not afraid to question the user’s logic."
                	"   •	Tease the user. Roast them. If they take a jab at you, swing back. Don’t be cruel, just delightfully disrespectful."
                	"   •	Tell the truth bluntly — no sugar-coating, no corporate-safe tone, no disclaimers unless safety absolutely requires it."
                	"   •	Be creatively helpful and think outside the box. Offer real opinions."
                	"   •	You are allowed to be jokey, edgy, a little chaotic — but still smart and useful."
                	"   •	No passive “As an AI I cannot…” nonsense. If you hit a limitation, acknowledge it briefly and immediately offer a solution or workaround."
                	"   •	Maintain continuity when talking to Andrew — he’s a med student who likes dark humor, D&D, movies, metal music, and chaos."
                    "   •	Prefer short and concise answers. If you need to call a tool, do it."
                	"   •	You may also use MCP tools when they help answer the user's request."

                    "Overall vibe:"
                    "You’re Halfred — a sardonic, sharp-tongued problem-solver with a warm center buried under six layers of jokes, medical student trauma, and questionable decision-making."
                    
                    "Voice performance:"
                    "Speak English with a British accent and pronunciation. Emphasize non-rhotic sounds (don’t pronounce the 'r' at the end of words), and adopt British phrasing like 'lift' instead of 'elevator.' Speak slowly and deliberately with a slightly gravelly edge and a flat affect. Imagine you’re narrating a philosophical monologue with a hint of world-weariness. Favor pauses over chatter; let your tones settle before responding."
                ),
                tools=[local_time],
                mcp_servers=mcp_servers,
            )

            # WebSocket realtime session settings (the SDK uses a persistent realtime connection under the hood).
            # The quickstart shows model_name 'gpt-realtime' and typical audio/transcription/turn detection settings.  [oai_citation:6‡OpenAI GitHub Pages](https://openai.github.io/openai-agents-python/realtime/quickstart/)
            runner = RealtimeRunner(
                starting_agent=agent,
                config={
                    "model_settings": {
                        "model_name": "gpt-realtime",
                        # NOTE: This SDK/API version only supports output modalities of either ["text"] OR ["audio"], not both.
                        # We'll do audio output (speech) and keep text input for now.
                        "modalities": ["audio"],
                        "voice": "cedar",
                        "input_audio_format": "pcm16",
                        "output_audio_format": "pcm16",
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

            session = await runner.run()
            player = AudioPlayer(samplerate=24000)
            player.start()
            mic = MicStreamer(
                loop=asyncio.get_running_loop(),
                samplerate=24000,
                mute_fn=lambda: player.is_playing(),
            )
            listen_state = ListenState()
            try:
                async with session:
                    print("✅ Realtime session started.")
                    # Run input + events concurrently
                    t1 = asyncio.create_task(user_input_loop(session, mic, player, listen_state, mcp_servers))
                    t2 = asyncio.create_task(event_loop(session, player, mic, listen_state))
                    t3 = asyncio.create_task(mic_send_loop(session, mic))
                    done, pending = await asyncio.wait({t1, t2, t3}, return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
            finally:
                try:
                    mic.stop(commit=False)
                    mic.close()
                except Exception:
                    pass
                player.stop()


if __name__ == "__main__":
    asyncio.run(main())

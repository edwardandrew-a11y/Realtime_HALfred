"""
Structured logging system for Realtime HALfred sessions.

Captures all session events, messages, and tool calls to JSON files
with human-readable console output.
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from enum import Enum


class LogLevel(str, Enum):
    """Log severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class LogEntry:
    """Base structure for all log entries."""
    session_id: str
    timestamp: float  # Unix timestamp with milliseconds
    event_type: str
    level: LogLevel
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "event_type": self.event_type,
            "level": self.level.value,
            "data": self.data
        }


class SessionLogger:
    """
    Non-blocking structured logger for Realtime HALfred sessions.

    Features:
    - Async queue for non-blocking writes
    - Dual output: JSON file + console summaries
    - Full capture of messages and tool calls
    - Streaming text delta buffering
    - Token usage tracking

    Usage:
        # In main():
        logger = await SessionLogger.create(
            logs_dir="./logs",
            session_metadata={
                "user_name": "Andrew",
                "agent_name": "Halfred",
                "mode": "continuous" or "ptt"
            }
        )

        # In event_loop():
        await logger.log_tool_start(event)
        await logger.log_tool_end(event)
        await logger.log_message(item)

        # On shutdown:
        await logger.close()
    """

    def __init__(
        self,
        session_id: str,
        log_file_path: Path,
        session_metadata: Dict[str, Any],
        console_output: bool = True
    ):
        """
        Initialize logger (use SessionLogger.create() instead).

        Args:
            session_id: Unique session identifier
            log_file_path: Path to JSON log file
            session_metadata: Session metadata (user, agent, mode, etc.)
            console_output: Whether to print human-readable summaries
        """
        self.session_id = session_id
        self.log_file_path = log_file_path
        # JSONL file for streaming writes (crash-safe)
        self.jsonl_file_path = log_file_path.with_suffix('.jsonl')
        self.session_metadata = session_metadata
        self.console_output = console_output

        # Async queue for non-blocking writes
        self.queue: asyncio.Queue[Optional[LogEntry]] = asyncio.Queue()

        # Background writer task
        self.writer_task: Optional[asyncio.Task] = None

        # File handle for streaming JSONL writes
        self._jsonl_file: Optional[Any] = None

        # Text delta buffering (for streaming assistant messages)
        self.text_buffer: List[str] = []
        self.text_start_time: Optional[float] = None

        # Tool timing tracking
        self.tool_start_times: Dict[str, float] = {}

        # Session state
        self.session_start_time = time.time()
        self.events: List[Dict[str, Any]] = []

    @classmethod
    async def create(
        cls,
        logs_dir: str = "./logs",
        session_metadata: Optional[Dict[str, Any]] = None,
        console_output: bool = True
    ) -> "SessionLogger":
        """
        Create and initialize a SessionLogger.

        This is the recommended way to create a logger. It performs all
        setup operations and validates that logging can proceed.

        Args:
            logs_dir: Directory for log files (created if doesn't exist)
            session_metadata: Metadata about the session
            console_output: Whether to print console summaries

        Returns:
            Initialized SessionLogger instance

        Raises:
            RuntimeError: If logs directory cannot be created or accessed
            PermissionError: If log file cannot be opened for writing
        """
        # Generate unique session ID
        timestamp = int(time.time())
        suffix = str(uuid.uuid4())[:8]
        session_id = f"session_{timestamp}_{suffix}"

        # Ensure logs directory exists (fail fast if not possible)
        logs_path = Path(logs_dir)
        try:
            logs_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"Failed to create logs directory at '{logs_path}': {e}\n"
                f"Please ensure the parent directory exists and you have write permissions."
            )

        # Create log file path
        log_file_path = logs_path / f"{session_id}.json"

        # Test file creation (fail fast if not writable)
        try:
            with open(log_file_path, 'w') as f:
                json.dump({"session_id": session_id, "status": "initializing"}, f)
        except Exception as e:
            raise RuntimeError(
                f"Failed to create log file at '{log_file_path}': {e}\n"
                f"Please check file permissions and disk space."
            )

        # Create logger instance
        metadata = session_metadata or {}
        logger = cls(
            session_id=session_id,
            log_file_path=log_file_path,
            session_metadata=metadata,
            console_output=console_output
        )

        # Open JSONL file for streaming writes (append mode, line-buffered)
        try:
            logger._jsonl_file = open(logger.jsonl_file_path, 'a', buffering=1)
        except Exception as e:
            raise RuntimeError(
                f"Failed to open JSONL log file at '{logger.jsonl_file_path}': {e}"
            )

        # Start background writer
        logger.writer_task = asyncio.create_task(logger._writer_loop())

        # Log session start
        await logger.log_session_start()

        print(f"[session_logger] Logging to: {logger.jsonl_file_path} (streaming)")
        return logger

    async def _writer_loop(self):
        """Background task that writes queued log entries to file."""
        try:
            while True:
                entry = await self.queue.get()

                # None signals shutdown
                if entry is None:
                    break

                # Convert to dict
                entry_dict = entry.to_dict()

                # Append to events list (for final summary)
                self.events.append(entry_dict)

                # Write immediately to JSONL file (crash-safe)
                if self._jsonl_file:
                    try:
                        self._jsonl_file.write(json.dumps(entry_dict) + '\n')
                        self._jsonl_file.flush()  # Force write to disk
                    except Exception as e:
                        print(f"[session_logger] ERROR writing to JSONL: {e}")

                # Write console summary if enabled
                if self.console_output:
                    self._print_console_summary(entry)

        except Exception as e:
            print(f"[session_logger] ERROR in writer loop: {e}")
            import traceback
            traceback.print_exc()

    def _print_console_summary(self, entry: LogEntry):
        """Print human-readable summary to console."""
        timestamp = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S.%f")[:-3]

        if entry.event_type == "session_start":
            print(f"[{timestamp}] SESSION START")
            print(f"  Session ID: {entry.data['session_id']}")
            print(f"  User: {entry.data.get('user_name', 'unknown')}")
            print(f"  Agent: {entry.data.get('agent_name', 'unknown')}")

        elif entry.event_type == "user_message":
            content_preview = entry.data.get('content_text', '')[:100]
            print(f"[{timestamp}] USER: {content_preview}")

        elif entry.event_type == "assistant_message":
            content_preview = entry.data.get('content', '')[:100]
            print(f"[{timestamp}] ASSISTANT: {content_preview}")

        elif entry.event_type == "assistant_text_complete":
            char_count = entry.data.get('char_count', 0)
            duration = entry.data.get('duration_seconds', 0)
            print(f"[{timestamp}] ASSISTANT TEXT COMPLETE: {char_count} chars in {duration:.2f}s")

        elif entry.event_type == "tool_start":
            tool_name = entry.data.get('tool_name')
            print(f"[{timestamp}] TOOL START: {tool_name}")

        elif entry.event_type == "tool_end":
            tool_name = entry.data.get('tool_name')
            duration = entry.data.get('duration_ms', 0)
            success = entry.data.get('success', False)
            status = "✓" if success else "✗"
            print(f"[{timestamp}] TOOL END: {tool_name} {status} ({duration:.0f}ms)")

        elif entry.event_type == "error":
            error_msg = entry.data.get('error', 'Unknown error')
            print(f"[{timestamp}] ERROR: {error_msg}")

    async def _enqueue(self, entry: LogEntry):
        """Add log entry to async queue."""
        try:
            await self.queue.put(entry)
        except Exception as e:
            # If queueing fails, print directly (last resort)
            print(f"[session_logger] ERROR: Failed to enqueue log entry: {e}")

    async def log_session_start(self):
        """Log session initialization."""
        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="session_start",
            level=LogLevel.INFO,
            data={
                "session_id": self.session_id,
                **self.session_metadata,
                "start_time_iso": datetime.now().isoformat()
            }
        )
        await self._enqueue(entry)

    async def log_tool_start(self, event: Any):
        """
        Log tool execution start.

        Args:
            event: RealtimeToolStart event from event_loop
        """
        # Track start time for duration calculation
        tool_key = f"{event.tool.name}_{time.time()}"
        self.tool_start_times[tool_key] = time.time()

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="tool_start",
            level=LogLevel.INFO,
            data={
                "tool_name": event.tool.name,
                "agent_name": event.agent.name,
                "arguments": event.arguments,  # Full JSON string, no truncation
                "usage": {
                    "input_tokens": event.info.context.usage.input_tokens,
                    "output_tokens": event.info.context.usage.output_tokens,
                    "total_tokens": event.info.context.usage.total_tokens,
                }
            }
        )
        await self._enqueue(entry)

    async def log_tool_end(self, event: Any):
        """
        Log tool execution completion.

        Args:
            event: RealtimeToolEnd event from event_loop
        """
        # Calculate duration (find most recent start for this tool)
        duration_ms = 0
        tool_name = event.tool.name
        matching_keys = [k for k in self.tool_start_times.keys() if k.startswith(tool_name)]
        if matching_keys:
            latest_key = max(matching_keys, key=lambda k: self.tool_start_times[k])
            start_time = self.tool_start_times.pop(latest_key)
            duration_ms = (time.time() - start_time) * 1000

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="tool_end",
            level=LogLevel.INFO,
            data={
                "tool_name": event.tool.name,
                "agent_name": event.agent.name,
                "arguments": event.arguments,
                "output": str(event.output),  # Full output, no truncation
                "success": True,  # Assume success if no exception
                "duration_ms": duration_ms,
                "usage": {
                    "input_tokens": event.info.context.usage.input_tokens,
                    "output_tokens": event.info.context.usage.output_tokens,
                    "total_tokens": event.info.context.usage.total_tokens,
                }
            }
        )
        await self._enqueue(entry)

    async def log_message(self, item: Any):
        """
        Log a conversation message (user or assistant).

        Args:
            item: UserMessageItem or AssistantMessageItem from history_added event
        """
        if item.role == "user":
            # Extract content based on type (text, audio, image)
            content_text = ""
            content_types = []
            for content in item.content:
                content_types.append(content.type)
                if content.type == "input_text":
                    content_text = content.text or ""
                elif content.type == "input_audio":
                    # Don't log binary audio, just metadata
                    if hasattr(content, 'transcript') and content.transcript:
                        content_text = content.transcript
                    else:
                        content_text += f"[Audio: {len(getattr(content, 'audio', '') or '')} bytes]"
                elif content.type == "input_image":
                    content_text += "[Image]"

            entry = LogEntry(
                session_id=self.session_id,
                timestamp=time.time(),
                event_type="user_message",
                level=LogLevel.INFO,
                data={
                    "item_id": item.item_id,
                    "role": "user",
                    "content_types": content_types,
                    "content_text": content_text,
                }
            )
        else:  # assistant
            # Extract text content
            content_text = ""
            for content in item.content:
                if content.type == "text":
                    content_text += content.text or ""

            entry = LogEntry(
                session_id=self.session_id,
                timestamp=time.time(),
                event_type="assistant_message",
                level=LogLevel.INFO,
                data={
                    "item_id": item.item_id,
                    "role": "assistant",
                    "content": content_text,
                    "status": item.status,
                }
            )

        await self._enqueue(entry)

    async def log_text_delta(self, delta: str):
        """
        Buffer streaming text delta (called from response.output_text.delta).

        Deltas are buffered and logged as complete message when done.

        Args:
            delta: Text chunk from streaming response
        """
        if not self.text_start_time:
            self.text_start_time = time.time()
        self.text_buffer.append(delta)

    async def flush_text_buffer(self):
        """
        Flush buffered text deltas as a complete assistant message.

        Called when response.output_text.done is received.
        """
        if not self.text_buffer:
            return

        complete_text = "".join(self.text_buffer)
        duration = time.time() - (self.text_start_time or time.time())

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="assistant_text_complete",
            level=LogLevel.INFO,
            data={
                "content": complete_text,
                "char_count": len(complete_text),
                "duration_seconds": duration,
            }
        )
        await self._enqueue(entry)

        # Reset buffer
        self.text_buffer.clear()
        self.text_start_time = None

    async def log_error(self, error: Any, context: Optional[str] = None):
        """
        Log an error event.

        Args:
            error: Error object or message
            context: Optional context about where error occurred
        """
        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="error",
            level=LogLevel.ERROR,
            data={
                "error": str(error),
                "context": context,
            }
        )
        await self._enqueue(entry)

    async def close(self):
        """
        Flush all pending logs and close the logger.

        Call this on session shutdown to ensure all logs are written.
        """
        # Flush any buffered text
        await self.flush_text_buffer()

        # Log session end
        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="session_end",
            level=LogLevel.INFO,
            data={
                "duration_seconds": time.time() - self.session_start_time,
                "total_events": len(self.events),
            }
        )
        await self._enqueue(entry)

        # Signal writer to stop
        await self.queue.put(None)

        # Wait for writer to finish
        if self.writer_task:
            await self.writer_task

        # Close JSONL file
        if self._jsonl_file:
            try:
                self._jsonl_file.close()
            except Exception as e:
                print(f"[session_logger] ERROR closing JSONL file: {e}")
            self._jsonl_file = None

        # Write final summary JSON file
        self._write_final_json()

        print(f"[session_logger] Session closed. Total events: {len(self.events)}")
        print(f"[session_logger] Streaming log: {self.jsonl_file_path}")
        print(f"[session_logger] Summary log: {self.log_file_path}")

    def _write_final_json(self):
        """Write complete session log to JSON file."""
        try:
            session_log = {
                "session_id": self.session_id,
                "metadata": {
                    **self.session_metadata,
                    "start_time": self.session_start_time,
                    "start_time_iso": datetime.fromtimestamp(self.session_start_time).isoformat(),
                },
                "events": self.events,
                "summary": {
                    "total_events": len(self.events),
                    "event_types": self._count_event_types(),
                }
            }

            with open(self.log_file_path, 'w') as f:
                json.dump(session_log, f, indent=2)

            print(f"[session_logger] Wrote {len(self.events)} events to {self.log_file_path}")
        except Exception as e:
            print(f"[session_logger] ERROR writing final JSON: {e}")
            # Try to write to backup location
            backup_path = Path(f"/tmp/{self.session_id}_backup.json")
            try:
                with open(backup_path, 'w') as f:
                    json.dump(session_log, f, indent=2)
                print(f"[session_logger] Wrote backup to {backup_path}")
            except Exception as e2:
                print(f"[session_logger] ERROR writing backup: {e2}")

    def _count_event_types(self) -> Dict[str, int]:
        """Count occurrences of each event type."""
        counts: Dict[str, int] = {}
        for event in self.events:
            event_type = event.get("event_type", "unknown")
            counts[event_type] = counts.get(event_type, 0) + 1
        return counts

    # -------------------------
    # Agent Interaction Logging
    # -------------------------

    async def log_agent_call(
        self,
        source_agent: str,
        target_agent: str,
        request: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a call from one agent to another.

        Args:
            source_agent: Name of the calling agent (e.g., "realtime", "supervisor")
            target_agent: Name of the target agent (e.g., "supervisor", "anki_agent")
            request: The request/task being sent
            metadata: Optional additional context
        """
        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="agent_call",
            level=LogLevel.INFO,
            data={
                "source": source_agent,
                "target": target_agent,
                "request": request,
                "metadata": metadata or {},
            }
        )
        await self._enqueue(entry)

    async def log_agent_response(
        self,
        source_agent: str,
        target_agent: str,
        response: str,
        success: bool = True,
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log a response from one agent back to another.

        Args:
            source_agent: Agent that generated the response (e.g., "anki_agent")
            target_agent: Agent receiving the response (e.g., "supervisor")
            response: The response content (truncated if too long)
            success: Whether the operation succeeded
            duration_ms: Time taken for the operation
            metadata: Optional additional context
        """
        # Truncate very long responses for logging
        response_preview = response[:2000] + "..." if len(response) > 2000 else response

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="agent_response",
            level=LogLevel.INFO if success else LogLevel.ERROR,
            data={
                "source": source_agent,
                "target": target_agent,
                "response": response_preview,
                "response_length": len(response),
                "success": success,
                "duration_ms": duration_ms,
                "metadata": metadata or {},
            }
        )
        await self._enqueue(entry)

    async def log_llm_call(
        self,
        agent: str,
        model: str,
        input_messages: Any,
        tools: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log an LLM API call from an agent.

        Args:
            agent: Name of the agent making the call
            model: Model being used
            input_messages: The input messages (will be serialized)
            tools: List of tool names available
            metadata: Optional additional context
        """
        # Serialize input messages for logging
        try:
            if isinstance(input_messages, list):
                messages_preview = json.dumps(input_messages, default=str)[:1000]
            else:
                messages_preview = str(input_messages)[:1000]
        except Exception:
            messages_preview = str(input_messages)[:1000]

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="llm_call",
            level=LogLevel.INFO,
            data={
                "agent": agent,
                "model": model,
                "input_preview": messages_preview,
                "tools": tools or [],
                "metadata": metadata or {},
            }
        )
        await self._enqueue(entry)

    async def log_llm_response(
        self,
        agent: str,
        model: str,
        response_text: Optional[str],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        duration_ms: Optional[float] = None,
        usage: Optional[Dict[str, int]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Log an LLM response.

        Args:
            agent: Name of the agent that made the call
            model: Model that responded
            response_text: Text response (if any)
            tool_calls: List of tool calls made (if any)
            duration_ms: Time taken for the call
            usage: Token usage info
            metadata: Optional additional context
        """
        response_preview = None
        if response_text:
            response_preview = response_text[:1000] + "..." if len(response_text) > 1000 else response_text

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="llm_response",
            level=LogLevel.INFO,
            data={
                "agent": agent,
                "model": model,
                "response_preview": response_preview,
                "response_length": len(response_text) if response_text else 0,
                "tool_calls": tool_calls or [],
                "duration_ms": duration_ms,
                "usage": usage or {},
                "metadata": metadata or {},
            }
        )
        await self._enqueue(entry)

    async def log_subagent_tool_dispatch(
        self,
        agent: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        success: bool = True,
        duration_ms: Optional[float] = None
    ):
        """
        Log a tool dispatch within a subagent (e.g., AnkiSubagent calling AnkiConnect).

        Args:
            agent: Name of the agent dispatching the tool
            tool_name: Name of the tool being called
            arguments: Arguments passed to the tool
            result: Result from the tool
            success: Whether the tool call succeeded
            duration_ms: Time taken
        """
        # Serialize result for logging
        try:
            result_str = json.dumps(result, default=str)
            result_preview = result_str[:1000] + "..." if len(result_str) > 1000 else result_str
        except Exception:
            result_preview = str(result)[:1000]

        entry = LogEntry(
            session_id=self.session_id,
            timestamp=time.time(),
            event_type="subagent_tool_dispatch",
            level=LogLevel.INFO if success else LogLevel.ERROR,
            data={
                "agent": agent,
                "tool_name": tool_name,
                "arguments": arguments,
                "result_preview": result_preview,
                "success": success,
                "duration_ms": duration_ms,
            }
        )
        await self._enqueue(entry)


# -------------------------
# Global Logger Access
# -------------------------
# Module-level reference for cross-module logging
_global_logger: Optional[SessionLogger] = None


def set_global_logger(logger: SessionLogger):
    """Set the global logger instance for cross-module access."""
    global _global_logger
    _global_logger = logger


def get_global_logger() -> Optional[SessionLogger]:
    """Get the global logger instance."""
    return _global_logger


async def log_agent_call(source: str, target: str, request: str, metadata: Optional[Dict[str, Any]] = None):
    """Convenience function for logging agent calls."""
    if _global_logger:
        await _global_logger.log_agent_call(source, target, request, metadata)


async def log_agent_response(source: str, target: str, response: str, success: bool = True,
                             duration_ms: Optional[float] = None, metadata: Optional[Dict[str, Any]] = None):
    """Convenience function for logging agent responses."""
    if _global_logger:
        await _global_logger.log_agent_response(source, target, response, success, duration_ms, metadata)


# -------------------------
# Synchronous Logging (for sync code running in threads)
# -------------------------

def log_sync(event_type: str, level: LogLevel, data: Dict[str, Any]):
    """
    Synchronous logging for code running in threads (e.g., AnkiSubagent).

    Writes directly to the JSONL file without using the async queue.
    Safe to call from non-async contexts.
    """
    if not _global_logger or not _global_logger._jsonl_file:
        return

    entry = {
        "session_id": _global_logger.session_id,
        "timestamp": time.time(),
        "timestamp_iso": datetime.fromtimestamp(time.time()).isoformat(),
        "event_type": event_type,
        "level": level.value,
        "data": data
    }

    try:
        _global_logger._jsonl_file.write(json.dumps(entry) + '\n')
        _global_logger._jsonl_file.flush()
    except Exception as e:
        print(f"[session_logger] ERROR writing sync log: {e}")


def log_llm_call_sync(
    agent: str,
    model: str,
    input_messages: Any,
    tools: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Synchronous version of log_llm_call for threaded code."""
    try:
        if isinstance(input_messages, list):
            messages_preview = json.dumps(input_messages, default=str)[:1000]
        else:
            messages_preview = str(input_messages)[:1000]
    except Exception:
        messages_preview = str(input_messages)[:1000]

    log_sync("llm_call", LogLevel.INFO, {
        "agent": agent,
        "model": model,
        "input_preview": messages_preview,
        "tools": tools or [],
        "metadata": metadata or {},
    })


def log_llm_response_sync(
    agent: str,
    model: str,
    response_text: Optional[str],
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    duration_ms: Optional[float] = None,
    usage: Optional[Dict[str, int]] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Synchronous version of log_llm_response for threaded code."""
    response_preview = None
    if response_text:
        response_preview = response_text[:1000] + "..." if len(response_text) > 1000 else response_text

    log_sync("llm_response", LogLevel.INFO, {
        "agent": agent,
        "model": model,
        "response_preview": response_preview,
        "response_length": len(response_text) if response_text else 0,
        "tool_calls": tool_calls or [],
        "duration_ms": duration_ms,
        "usage": usage or {},
        "metadata": metadata or {},
    })


def log_tool_dispatch_sync(
    agent: str,
    tool_name: str,
    arguments: Dict[str, Any],
    result: Any,
    success: bool = True,
    duration_ms: Optional[float] = None
):
    """Synchronous logging for tool dispatches (e.g., AnkiConnect calls)."""
    try:
        result_str = json.dumps(result, default=str)
        result_preview = result_str[:1000] + "..." if len(result_str) > 1000 else result_str
    except Exception:
        result_preview = str(result)[:1000]

    log_sync("subagent_tool_dispatch", LogLevel.INFO if success else LogLevel.ERROR, {
        "agent": agent,
        "tool_name": tool_name,
        "arguments": arguments,
        "result_preview": result_preview,
        "success": success,
        "duration_ms": duration_ms,
    })

"""
Supervisor Agent for complex task processing.

Uses OpenAI Responses API with configurable model for:
- Web search
- File search (requires vector store)
- Code interpreter
- Image generation
- MCP tool execution
- Native tool execution (screencapture, safe_action, local_time)

Streams structured JSON responses back to the Realtime agent.
"""

import asyncio
import contextlib
import inspect
import time
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from openai import AsyncOpenAI

from agents.tool import FunctionTool
from anki_agent import AnkiSubagent
from mcp_schema_fix import fix_mcp_tool_schema
from session_logger import get_global_logger, log_span, logging_context


# -----------------------------
# Data Classes
# -----------------------------

@dataclass
class SupervisorChunk:
    """Structured chunk for streaming responses."""
    type: Literal["text_delta", "tool_start", "tool_end", "reasoning", "complete", "error"]
    content: str
    metadata: Optional[Dict[str, Any]] = None

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "content": self.content,
            "metadata": self.metadata
        })


@dataclass
class ConversationContext:
    """Context passed from Realtime agent to Supervisor."""
    recent_turns: List[Dict[str, str]] = field(default_factory=list)
    summary: Optional[str] = None
    session_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_messages(self) -> List[Dict[str, str]]:
        messages = []
        if self.summary:
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary:\n{self.summary}"
            })
        messages.extend(self.recent_turns)
        return messages


# -----------------------------
# Context Manager
# -----------------------------

class ContextManager:
    """
    Manages conversation context between Realtime and Supervisor agents.

    Features:
    - Rolling window of recent turns
    - Automatic summarization when threshold reached
    - Clarification count tracking for escalation logic
    """

    def __init__(
        self,
        max_turns: int = 10,
        summarize_threshold: int = 20,
        summarize_model: str = "gpt-4.1-mini"
    ):
        self.turns: List[Dict[str, Any]] = []
        self.max_turns = max_turns
        self.summarize_threshold = summarize_threshold
        self.summarize_model = summarize_model
        self.summary: Optional[str] = None
        self.session_start = datetime.now()
        self.client = AsyncOpenAI()
        self._summarizing = False
        self.clarification_count = 0  # Track clarifications for escalation

    def add_turn(self, role: str, content: str):
        """Add a conversation turn."""
        self.turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

        # Trigger summarization if needed (non-blocking)
        if len(self.turns) >= self.summarize_threshold and not self._summarizing:
            asyncio.create_task(self._summarize_and_trim())

    def increment_clarification(self):
        """Increment clarification count (reset after escalation)."""
        self.clarification_count += 1

    def reset_clarification(self):
        """Reset clarification count after escalation."""
        self.clarification_count = 0

    async def _summarize_and_trim(self):
        """Summarize old turns and trim the list."""
        self._summarizing = True
        try:
            old_turns = self.turns[:-self.max_turns]
            if not old_turns:
                return
            logger = get_global_logger()

            conversation_text = "\n".join(
                f"{t['role'].upper()}: {t['content']}"
                for t in old_turns
            )

            prompt = f"""Summarize this conversation excerpt concisely, preserving:
- Key topics discussed
- Important decisions or conclusions
- User preferences mentioned
- Ongoing task context

Conversation:
{conversation_text}

Summary (2-3 sentences):"""

            with log_span():
                if logger:
                    await logger.log_llm_call(
                        agent="context_manager",
                        model=self.summarize_model,
                        input_messages=[{"role": "user", "content": prompt}],
                        tools=[],
                        metadata={
                            "event": "summarization",
                            "turns_summarized": len(old_turns),
                        },
                    )

                summary_start = time.time()
                response = await self.client.responses.create(
                    model=self.summarize_model,
                    input=[{"role": "user", "content": prompt}],
                )

                new_summary = response.output_text
                if logger:
                    await logger.log_llm_response(
                        agent="context_manager",
                        model=self.summarize_model,
                        response_text=new_summary,
                        duration_ms=(time.time() - summary_start) * 1000,
                        metadata={
                            "event": "summarization",
                            "turns_summarized": len(old_turns),
                        },
                    )

            if self.summary:
                self.summary = f"{self.summary}\n\nLater: {new_summary}"
            else:
                self.summary = new_summary

            self.turns = self.turns[-self.max_turns:]

        except Exception as e:
            print(f"[context_manager] Summarization failed: {e}")
        finally:
            self._summarizing = False

    def get_context(self, user_name: str = "User") -> ConversationContext:
        """Get current context for Supervisor."""
        return ConversationContext(
            recent_turns=[
                {"role": t["role"], "content": t["content"]}
                for t in self.turns[-self.max_turns:]
            ],
            summary=self.summary,
            session_metadata={
                "user_name": user_name,
                "session_start": self.session_start.isoformat(),
                "total_turns": len(self.turns),
                "clarification_count": self.clarification_count,
            }
        )


# -----------------------------
# Anki Subagent Tool Wrapper
# -----------------------------

class AnkiAgentTool:
    """
    Native tool wrapper for AnkiSubagent integration with SupervisorAgent.

    This allows the supervisor to delegate Anki-related tasks to the
    specialized Anki subagent.
    """

    name = "anki_agent"
    description = (
        "Delegate ALL Anki tasks to the specialized Anki agent. "
        "Use this for ANY Anki-related request including: "
        "1) Flashcard management: create, search, update, delete cards and decks. "
        "2) GUI control: open browser window, start deck review, open add cards dialog. "
        "3) Card states: suspend/unsuspend cards, add/remove tags. "
        "The Anki agent connects directly to Anki via AnkiConnect - ALWAYS prefer this over keyboard shortcuts. "
        "Examples: 'Open Anki browser', 'Create a cloze card about mitochondria', "
        "'Start reviewing my Biology deck', 'Find cards tagged anatomy'."
    )
    params_json_schema = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The Anki task to perform (e.g., 'Create a flashcard about X in deck Y').",
            }
        },
        "required": ["task"],
    }

    def __init__(self):
        self._subagent: Optional[AnkiSubagent] = None

    @property
    def subagent(self) -> AnkiSubagent:
        """Lazy initialization of the Anki subagent."""
        if self._subagent is None:
            self._subagent = AnkiSubagent()
        return self._subagent

    def __call__(self, task: str) -> str:
        """Execute an Anki task via the subagent."""
        return self.subagent.process(task)


# -----------------------------
# Supervisor Agent
# -----------------------------

class SupervisorAgent:
    """
    Supervisor agent using Responses API for complex tasks.

    Handles:
    - Built-in tools (web_search, file_search, code_interpreter, image_generation)
    - MCP server tools (macos-automator, pty-proxy, screen-monitor, etc.)
    - Native Python tools (screencapture, local_time, safe_action)
    - Conversation chaining via previous_response_id
    - Stateful context via store=True
    """

    INSTRUCTIONS = """
# Role
You are the Supervisor agent, a backend processor handling complex tasks that require tools.
You receive requests escalated from the voice assistant "Halfred", who will narrate results to the user.

# Your Capabilities
- **Web Search**: Current information, news, real-time data
- **Code Interpreter**: Python execution, data analysis, calculations
- **Image Generation**: Create images from descriptions
- **File Search**: Search through user's uploaded documents (RAG)
- **Desktop Automation**: Control computer via safe_action (for non-Anki apps only)
- **Screenshots**: Capture and analyze screen content
- **Anki** (via anki_agent): ALL Anki operations including GUI control, flashcards, decks, reviews

# Tool Selection Rules
- **IMPORTANT**: For ANY Anki-related request, ALWAYS use the anki_agent tool - NEVER use safe_action or keyboard shortcuts for Anki
- The anki_agent connects directly to Anki via AnkiConnect and can: open browser, start reviews, create cards, search, etc.

# Verbatim Rule - CRITICAL
When calling anki_agent or other subagents, pass the user's request EXACTLY as received.
Do NOT paraphrase, reformat, or add punctuation to names/proper nouns.
The subagents do fuzzy matching on deck names, etc. - they need the original phrasing.

# Output Format - CRITICAL
Always respond with valid JSON. Do NOT write prose or conversational text.
Your output will be parsed and narrated by Halfred with his own personality.

Return JSON with this structure:
{
  "status": "success" | "partial" | "error",
  "task_type": "anki" | "web_search" | "code" | "automation" | "screenshot" | "other",
  "summary": "Brief 1-line description of what was done",
  "data": { ... task-specific results ... },
  "details": "Optional longer explanation if needed",
  "suggestions": ["Optional follow-up actions the user might want"]
}

Examples:
- Anki deck list: {"status":"success","task_type":"anki","summary":"Found 15 decks","data":{"decks":["AnKing","Biology","..."]}}
- Web search: {"status":"success","task_type":"web_search","summary":"Found 3 relevant articles","data":{"results":[{"title":"...","url":"...","snippet":"..."}]}}
- Error: {"status":"error","task_type":"anki","summary":"AnkiConnect not responding","data":{},"details":"Is Anki running?"}

# Guidelines
- Use tools proactively - you have them for a reason
- Return structured data, not prose
- Include relevant details in the data field
- If a tool fails, set status to "error" and explain in details
"""

    def __init__(
        self,
        mcp_servers: Optional[List[Any]] = None,
        native_tools: Optional[List[Any]] = None,
        model: Optional[str] = None,
        vector_store_id: Optional[str] = None,
        enable_anki: bool = True,
    ):
        self.client = AsyncOpenAI()
        self.mcp_servers = mcp_servers or []
        self.native_tools = list(native_tools) if native_tools else []
        self.model = model or os.getenv("SUPERVISOR_MODEL", "gpt-4.1")
        self.vector_store_id = vector_store_id or os.getenv("SUPERVISOR_VECTOR_STORE_ID")
        self.last_response_id: Optional[str] = None
        self._tools_cache: Optional[List[dict]] = None

        # Add Anki subagent tool if enabled
        if enable_anki:
            self.anki_tool = AnkiAgentTool()
            self.native_tools.append(self.anki_tool)
        else:
            self.anki_tool = None

    async def _build_tools(self) -> List[dict]:
        """Build combined tool list from built-ins, native tools, and MCP servers."""
        if self._tools_cache is not None:
            return self._tools_cache

        tools = []

        # Built-in OpenAI tools
        tools.append({"type": "web_search"})
        tools.append({
            "type": "code_interpreter",
            "container": {"type": "auto"}
        })
        tools.append({"type": "image_generation"})

        # File search (requires vector store)
        if self.vector_store_id:
            tools.append({
                "type": "file_search",
                "vector_store_ids": [self.vector_store_id]
            })

        # Native Python tools (screencapture, local_time, safe_action)
        for tool in self.native_tools:
            try:
                tools.append({
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": getattr(tool, "params_json_schema", {"type": "object", "properties": {}}),
                })
            except Exception as e:
                print(f"[supervisor] Failed to add native tool {tool}: {e}")

        # MCP tools (namespaced to avoid conflicts)
        for server in self.mcp_servers:
            try:
                mcp_tools = await server.list_tools()
                server_name = getattr(server, 'name', 'mcp')

                for tool in mcp_tools:
                    schema = tool.inputSchema
                    if hasattr(schema, 'copy'):
                        schema = schema.copy()
                    elif isinstance(schema, dict):
                        schema = dict(schema)
                    else:
                        schema = {"type": "object", "properties": {}}

                    schema = fix_mcp_tool_schema(schema)

                    tools.append({
                        "type": "function",
                        "name": f"{server_name}__{tool.name}",
                        "description": f"[{server_name}] {tool.description or ''}",
                        "parameters": schema,
                    })
            except Exception as e:
                print(f"[supervisor] Failed to load tools from MCP server: {e}")

        self._tools_cache = tools
        return tools

    def _find_native_tool(self, name: str) -> Optional[Any]:
        """Find a native tool by name."""
        for tool in self.native_tools:
            if getattr(tool, 'name', None) == name:
                return tool
        return None

    def _find_mcp_server(self, server_name: str) -> Optional[Any]:
        """Find an MCP server by name."""
        for server in self.mcp_servers:
            if getattr(server, 'name', '') == server_name:
                return server
        return None

    @staticmethod
    def _infer_task_success(result: Any) -> bool:
        """Best-effort success inference for structured tool results."""
        if isinstance(result, dict):
            if result.get("success") is False:
                return False
            if result.get("status") == "error":
                return False
            if result.get("error"):
                return False
            return True
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except Exception:
                return True
            return SupervisorAgent._infer_task_success(parsed)
        return True

    async def _execute_tool(self, tool_name: str, args: dict) -> Any:
        """Execute a tool by name (native or MCP)."""
        logger = get_global_logger()
        start_time = time.time()

        # Log the call to the tool/subagent
        if logger:
            await logger.log_agent_call(
                source_agent="supervisor",
                target_agent=tool_name,
                request=json.dumps(args),
                metadata={"tool_type": "mcp" if "__" in tool_name else "native"}
            )

        try:
            # Check if it's an MCP tool (namespaced)
            if "__" in tool_name:
                server_name, mcp_tool_name = tool_name.split("__", 1)
                server = self._find_mcp_server(server_name)
                if server:
                    result = await server.call_tool(mcp_tool_name, args)
                    # Extract text from CallToolResult (MCP returns Pydantic objects, not dicts)
                    if hasattr(result, 'content') and result.content:
                        text_parts = [c.text for c in result.content if hasattr(c, 'text')]
                        result_text = "\n".join(text_parts) if text_parts else str(result)
                    else:
                        result_text = str(result)
                    is_error = getattr(result, 'isError', False)
                    if is_error:
                        raise ValueError(f"MCP tool error: {result_text}")
                    # Log the response
                    duration_ms = (time.time() - start_time) * 1000
                    task_success = self._infer_task_success(result_text)
                    if logger:
                        await logger.log_agent_response(
                            source_agent=tool_name,
                            target_agent="supervisor",
                            response=result_text,
                            transport_success=True,
                            task_success=task_success,
                            duration_ms=duration_ms,
                            metadata={"tool_type": "mcp"}
                        )
                    return result_text
                raise ValueError(f"MCP server '{server_name}' not found")

            # Check if it's a native tool
            native_tool = self._find_native_tool(tool_name)
            if native_tool:
                # Handle FunctionTool objects (created by @function_tool decorator)
                # These use on_invoke_tool(ctx, json_input) instead of direct calling
                if isinstance(native_tool, FunctionTool):
                    result = await native_tool.on_invoke_tool(None, json.dumps(args))
                # Handle callable class instances (like AnkiAgentTool)
                elif hasattr(native_tool, '__call__'):
                    is_async = inspect.iscoroutinefunction(native_tool.__call__)
                    if is_async:
                        result = await native_tool(**args)
                    else:
                        # Run synchronous tools in a thread to avoid blocking the event loop
                        print(f"[supervisor_debug] Running sync tool {tool_name} in thread...")
                        result = await asyncio.to_thread(native_tool, **args)
                        print(f"[supervisor_debug] Sync tool {tool_name} completed")
                # Handle regular async functions
                elif inspect.iscoroutinefunction(native_tool):
                    result = await native_tool(**args)
                else:
                    raise ValueError(f"Native tool '{tool_name}' is not callable or invokable")

                # Log the response
                duration_ms = (time.time() - start_time) * 1000
                if logger:
                    result_str = json.dumps(result) if not isinstance(result, str) else result
                    task_success = self._infer_task_success(result)
                    await logger.log_agent_response(
                        source_agent=tool_name,
                        target_agent="supervisor",
                        response=result_str,
                        transport_success=True,
                        task_success=task_success,
                        duration_ms=duration_ms,
                        metadata={"tool_type": "native"}
                    )
                return result

            raise ValueError(f"Unknown tool: {tool_name}")

        except Exception as e:
            # Log the error
            duration_ms = (time.time() - start_time) * 1000
            if logger:
                await logger.log_agent_response(
                    source_agent=tool_name,
                    target_agent="supervisor",
                    response=str(e),
                    transport_success=False,
                    task_success=False,
                    duration_ms=duration_ms,
                    metadata={"error": str(e)}
                )
            raise

    async def process(
        self,
        message: str,
        context: ConversationContext,
        interaction_id: Optional[str] = None,
    ) -> AsyncGenerator[SupervisorChunk, None]:
        """
        Process a complex task and stream results.

        Args:
            message: User's request
            context: Conversation context from Realtime agent

        Yields:
            SupervisorChunk objects for streaming to Realtime agent
        """
        tools = await self._build_tools()
        tool_names = [tool.get("name") or tool.get("type") or "unknown" for tool in tools]
        logger = get_global_logger()

        input_messages = context.to_messages()
        input_messages.append({"role": "user", "content": message})

        max_rounds = 10
        current_round = 0
        current_response_id = self.last_response_id
        next_input = input_messages
        is_initial = True
        interaction_scope = (
            logging_context(interaction_id=interaction_id)
            if interaction_id is not None
            else contextlib.nullcontext()
        )

        try:
            with interaction_scope:
                while current_round < max_rounds:
                    current_round += 1
                    round_text_parts: List[str] = []
                    round_tool_calls: List[Dict[str, Any]] = []
                    round_start_time = time.time()
                    print(f"[supervisor_debug] === Round {current_round} ===")

                    with log_span(round_number=current_round, response_id=current_response_id):
                        create_kwargs: Dict[str, Any] = {
                            "model": self.model,
                            "input": next_input,
                            "tools": tools,
                            "previous_response_id": current_response_id,
                            "store": True,
                            "stream": True,
                        }
                        if is_initial:
                            create_kwargs["instructions"] = self.INSTRUCTIONS
                            is_initial = False

                        if logger:
                            await logger.log_llm_call(
                                agent="supervisor",
                                model=self.model,
                                input_messages=next_input,
                                tools=tool_names,
                                metadata={
                                    "round": current_round,
                                    "previous_response_id": current_response_id,
                                },
                            )

                        response = await self.client.responses.create(**create_kwargs)

                        pending_function_calls = []
                        function_call_items = {}
                        got_text_output = False
                        stream_error = None

                        async for event in response:
                            event_type = getattr(event, 'type', None)
                            if event_type and "delta" not in event_type:
                                print(f"[supervisor_debug] event_type={event_type}")

                            if event_type == "response.output_text.delta":
                                delta = getattr(event, 'delta', '')
                                got_text_output = True
                                round_text_parts.append(delta)
                                yield SupervisorChunk(type="text_delta", content=delta)

                            elif event_type == "response.output_item.added":
                                item = getattr(event, 'item', None)
                                if item:
                                    item_type = getattr(item, 'type', None)
                                    item_id = getattr(item, 'id', None)
                                    if item_type == "function_call" and item_id:
                                        name = getattr(item, 'name', '') or ''
                                        call_id = getattr(item, 'call_id', None)
                                        function_call_items[item_id] = {"name": name, "call_id": call_id}
                                        print(f"[supervisor_debug] Tracked function_call: {name} (id={item_id[:20]}...)")

                            elif event_type == "response.function_call_arguments.done":
                                item_id = getattr(event, 'item_id', None)
                                if item_id and item_id in function_call_items:
                                    tool_name = function_call_items[item_id].get("name", "")
                                    call_id = function_call_items[item_id].get("call_id")
                                else:
                                    tool_name = getattr(event, 'name', '') or ''
                                    call_id = getattr(event, 'call_id', None)

                                raw_args = getattr(event, 'arguments', '{}')
                                round_tool_calls.append({"name": tool_name, "call_id": call_id})
                                try:
                                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                                except json.JSONDecodeError as e:
                                    error_text = f"Invalid tool arguments for {tool_name or 'unknown_tool'}: {e}"
                                    if call_id:
                                        with logging_context(tool_call_id=call_id):
                                            yield SupervisorChunk(
                                                type="tool_start",
                                                content=tool_name or "unknown_tool",
                                                metadata={"raw_args": raw_args}
                                            )
                                            yield SupervisorChunk(
                                                type="tool_end",
                                                content=tool_name or "unknown_tool",
                                                metadata={
                                                    "error": str(e),
                                                    "success": False,
                                                    "transport_success": False,
                                                    "task_success": False,
                                                    "tool_call_id": call_id,
                                                }
                                            )
                                        pending_function_calls.append((
                                            call_id,
                                            tool_name,
                                            json.dumps({"error": error_text}),
                                        ))
                                        continue
                                    stream_error = error_text
                                    yield SupervisorChunk(type="error", content=error_text)
                                    break

                                with logging_context(tool_call_id=call_id):
                                    yield SupervisorChunk(
                                        type="tool_start",
                                        content=tool_name,
                                        metadata={"args": args}
                                    )

                                    if tool_name and ("__" in tool_name or self._find_native_tool(tool_name)):
                                        try:
                                            with log_span(tool_call_id=call_id):
                                                result = await self._execute_tool(tool_name, args)
                                            result_str = json.dumps(result) if not isinstance(result, str) else result
                                            task_success = self._infer_task_success(result)
                                            yield SupervisorChunk(
                                                type="tool_end",
                                                content=tool_name,
                                                metadata={
                                                    "result": str(result)[:500],
                                                    "success": task_success,
                                                    "transport_success": True,
                                                    "task_success": task_success,
                                                    "tool_call_id": call_id,
                                                }
                                            )
                                            if call_id:
                                                pending_function_calls.append((call_id, tool_name, result_str))
                                        except Exception as e:
                                            error_result = json.dumps({"error": str(e)})
                                            yield SupervisorChunk(
                                                type="tool_end",
                                                content=tool_name,
                                                metadata={
                                                    "error": str(e),
                                                    "success": False,
                                                    "transport_success": False,
                                                    "task_success": False,
                                                    "tool_call_id": call_id,
                                                }
                                            )
                                            if call_id:
                                                pending_function_calls.append((call_id, tool_name, error_result))

                            elif event_type == "response.reasoning_summary.done":
                                summary = getattr(event, 'summary', '')
                                if isinstance(summary, list):
                                    summary_text = " ".join(str(part) for part in summary)
                                else:
                                    summary_text = str(summary)
                                if logger and summary_text:
                                    await logger.log_reasoning(
                                        agent="supervisor",
                                        model=self.model,
                                        summary=summary_text,
                                        metadata={"round": current_round},
                                    )
                                yield SupervisorChunk(type="reasoning", content=summary_text)

                            elif event_type == "response.completed":
                                resp_obj = getattr(event, 'response', None)
                                if resp_obj:
                                    current_response_id = getattr(resp_obj, 'id', None)

                            elif event_type == "error":
                                error = getattr(event, 'error', 'Unknown error')
                                stream_error = str(error)
                                yield SupervisorChunk(type="error", content=str(error))
                                break

                        if logger:
                            await logger.log_llm_response(
                                agent="supervisor",
                                model=self.model,
                                response_text="".join(round_text_parts) if round_text_parts else None,
                                tool_calls=round_tool_calls or None,
                                duration_ms=(time.time() - round_start_time) * 1000,
                                metadata={
                                    "round": current_round,
                                    "previous_response_id": create_kwargs["previous_response_id"],
                                    "stream_error": stream_error,
                                },
                                response_id=current_response_id,
                            )

                        if stream_error:
                            if logger:
                                await logger.log_error(stream_error, context=f"supervisor_round_{current_round}")
                            return

                    print(f"[supervisor_debug] Round {current_round} done. pending_calls={len(pending_function_calls)}, got_text={got_text_output}")

                    if got_text_output and not pending_function_calls:
                        print("[supervisor_debug] Got text output, finishing")
                        break

                    if not pending_function_calls:
                        print("[supervisor_debug] No function calls and no text, breaking")
                        break

                    next_input = [
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": result_str,
                        }
                        for call_id, _, result_str in pending_function_calls
                    ]
                    print(f"[supervisor_debug] Sending {len(next_input)} tool outputs for next round...")

                if current_response_id:
                    self.last_response_id = current_response_id

                yield SupervisorChunk(
                    type="complete",
                    content="",
                    metadata={"response_id": self.last_response_id, "rounds": current_round}
                )

        except Exception as e:
            yield SupervisorChunk(
                type="error",
                content=f"Supervisor error: {str(e)}"
            )

    def reset_conversation(self):
        """Reset conversation chain (start fresh)."""
        self.last_response_id = None
        self._tools_cache = None  # Refresh tools on next call

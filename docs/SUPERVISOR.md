# Supervisor Agent Architecture

This document describes the hierarchical agent architecture introduced in v0.18, where the Realtime agent acts as a "front desk" and routes complex tasks to a Supervisor agent.

## Overview

HALfred now uses a two-tier agent architecture:

1. **Realtime Agent (main.py)** - "Front desk" for fast, conversational interactions
2. **Supervisor Agent (supervisor.py)** - Handles complex tasks requiring tools

```
User Voice → Realtime Agent (gpt-realtime)
                    │
        ┌───────────┴───────────┐
        ↓                       ↓
   HANDLE LOCALLY          ESCALATE TO SUPERVISOR
   - Simple Q&A            - Needs any tool (screenshots, web, code, MCP)
   - Definitions           - Multi-step planning
   - 1 clarifying Q        - Retrieval/RAG tasks
   - UI glue/confirm       - High-stakes actions
                           - Ambiguity after 1 clarification
                                   ↓
                           Supervisor (configurable model)
                           - web_search, code_interpreter
                           - image_generation, file_search
                           - ALL MCP tools + native tools
                                   ↓
                           Stream JSON → TTS speaks result
```

## Why This Architecture?

### Benefits

1. **Lower Latency** - Simple conversations stay in the fast Realtime API path
2. **Better Tool Support** - Supervisor uses Responses API with richer built-in tools
3. **Stateful Context** - Supervisor maintains conversation state via `store=true` and `previous_response_id`
4. **Cost Efficiency** - Only complex tasks use the more capable (and expensive) Supervisor model
5. **Clear Separation** - Realtime handles voice UX, Supervisor handles task execution

### Tool Distribution

| Tool | Realtime Agent | Supervisor Agent |
|------|----------------|------------------|
| `escalate_to_supervisor` | YES (only tool) | NO |
| `screencapture` | NO | YES |
| `local_time` | NO | YES |
| `safe_action` | NO | YES |
| `web_search` | NO | YES (built-in) |
| `code_interpreter` | NO | YES (built-in) |
| `image_generation` | NO | YES (built-in) |
| `file_search` | NO | YES (built-in) |
| MCP tools | NO | YES (namespaced) |

## Escalation Rules

### Realtime Handles Locally

- Simple Q&A, definitions, short explanations (no external data needed)
- One clarifying question to understand vague requests (max 1 before escalating)
- UI glue: restate requests, confirm intent, summarize what happens next
- General conversation, banter, jokes

### Escalate to Supervisor When

- User needs ANY tool (screenshots, web search, code, desktop automation, etc.)
- Task requires multi-step planning, comparison, or synthesis
- User mentions document search/retrieval ("search my docs", "find that file")
- High-stakes or irreversible actions (send, delete, purchase, deploy)
- Ambiguity remains after 1 clarifying question

### Tool-Based Escalation

The Realtime agent has an `escalate_to_supervisor` tool that it uses when it determines
a task requires capabilities beyond simple conversation. The agent uses its own reasoning
to decide when to call this tool - no keyword matching is involved.

```python
@function_tool
async def escalate_to_supervisor(request: str) -> str:
    """
    Escalate a task to the Supervisor agent for complex processing.

    Use this tool when you need capabilities beyond simple conversation, including:
    - Web search, current news, real-time information
    - Code execution, Python computations, data analysis
    - File search in user's documents (RAG)
    - Desktop automation (terminal commands, AppleScript, clicking, typing)
    - Interacting with applications (Anki, browsers, etc.)
    - Multi-step tasks requiring planning or synthesis
    """
```

This approach is more intelligent than keyword matching because:
- The agent can infer intent from context (e.g., "add that to my decks" after discussing Anki)
- The agent can ask clarifying questions before deciding to escalate
- No brittle keyword lists to maintain

## Configuration

### Environment Variables

```bash
# Supervisor model (default: gpt-4.1)
SUPERVISOR_MODEL=gpt-4.1

# Optional: Vector store ID for file_search capability
SUPERVISOR_VECTOR_STORE_ID=vs_xxx
```

### Context Management

The `ContextManager` class tracks conversation context:

- **Rolling window**: Last 10 turns by default
- **Auto-summarization**: Triggers at 20 turns, compresses older history
- **Clarification tracking**: Counts clarifying questions for escalation logic

## Supervisor Capabilities

### Built-in OpenAI Tools

1. **web_search** - Search the internet for current information
2. **code_interpreter** - Execute Python code in a sandbox
3. **image_generation** - Create images from text descriptions
4. **file_search** - Search uploaded documents (requires vector store)

### Native Python Tools

- `local_time` - Current time
- `safe_action` - Desktop automation with safety confirmation
- `screencapture` - Screenshot capture

### MCP Tools (Namespaced)

All MCP server tools are available with `server__tool` naming:

- `screen-monitor__capture_screen`
- `screen-monitor__analyze_screen`
- `pty-proxy__pty_bash_execute`
- `macos-automator__execute_script`
- `macos-automator__accessibility_query`
- etc.

## Implementation Details

### Files

| File | Purpose |
|------|---------|
| `supervisor.py` | Supervisor agent implementation |
| `main.py` | Realtime agent + routing integration |

### Key Classes

#### `SupervisorAgent`

Main supervisor class using Responses API:

```python
class SupervisorAgent:
    def __init__(self, mcp_servers, native_tools, model, vector_store_id):
        # ...

    async def process(self, message, context) -> AsyncGenerator[SupervisorChunk, None]:
        # Streams structured chunks back to Realtime
        # ...
```

#### `ContextManager`

Manages conversation context:

```python
class ContextManager:
    def add_turn(self, role, content): ...
    def get_context(self) -> ConversationContext: ...
    def increment_clarification(self): ...
    def reset_clarification(self): ...
```

#### `SupervisorChunk`

Structured streaming response:

```python
@dataclass
class SupervisorChunk:
    type: Literal["text_delta", "tool_start", "tool_end", "reasoning", "complete", "error"]
    content: str
    metadata: Optional[Dict[str, Any]] = None
```

### Flow Diagram

```
1. User speaks → Microphone → Realtime API
2. Transcription received → Realtime agent processes
3. Agent decides (using its own reasoning):
   a. If simple task: Handle directly, respond via TTS
   b. If complex task: Call escalate_to_supervisor tool
4. If escalated:
   a. Tool stops mic
   b. Gets context from ContextManager
   c. Calls supervisor.process(message, context)
   d. Streams chunks to TTS
   e. On complete, adds to context
   f. Restarts mic
   g. Returns result to Realtime agent
5. Realtime agent can acknowledge or add context to response
```

## Testing

### Test Escalation Behavior

The agent decides when to escalate based on reasoning, not keywords.
Examples that should trigger escalation:

```python
# Should escalate (agent infers tools needed)
"Search for the latest news about AI"    # needs web_search
"Write Python code to sort a list"       # needs code_interpreter
"Generate an image of a cat"             # needs image_generation
"What decks are in my Anki program?"     # needs Anki tools
"Open the browser and go to Google"      # needs desktop automation

# Should NOT escalate (simple conversation)
"Tell me a joke"
"What's your name?"
"How are you today?"
```

### Test Full Integration

1. Start HALfred: `python main.py`
2. Say: "Search the web for today's weather"
3. Verify: Supervisor processes, TTS speaks result

## Troubleshooting

### Supervisor Not Responding

1. Check `SUPERVISOR_MODEL` is valid
2. Verify OpenAI API key has access to the model
3. Check console for `[supervisor]` log messages

### Tools Not Working

1. Verify MCP servers are loaded: `/mcp` command
2. Check tool namespacing in supervisor logs
3. Ensure `mcp_schema_fix.py` is imported

### Context Issues

1. Check `ContextManager` is initialized
2. Verify turns are being added on transcription
3. Check summarization isn't failing (look for errors in logs)

## Version History

- **v0.18** - Initial Supervisor architecture implementation
  - Added `supervisor.py` with Responses API integration
  - Modified `main.py` for routing and integration
  - Realtime agent reduced to "front desk" role
  - All tools/MCPs moved to Supervisor

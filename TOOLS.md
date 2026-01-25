# HALfred Agent Tools Documentation

This document describes all tools available to the HALfred agents, organized by agent and source.

**Last Updated:** 2026-01-22
**Agent Version:** HALfred v0.18+

---

## Architecture Overview

HALfred uses a **two-tier agent architecture**:

```
User Voice Input
       │
       ▼
┌─────────────────────────────────────────────────────┐
│           REALTIME AGENT (Front Desk)               │
│   Model: gpt-realtime | Low latency voice interface │
│   Tools: escalate_to_supervisor (1 tool only)       │
├─────────────────────────────────────────────────────┤
│   Handles locally:          │   Escalates to        │
│   • Simple Q&A              │   Supervisor:         │
│   • Definitions             │   • Any tool use      │
│   • Quick clarifications    │   • Multi-step tasks  │
│   • Confirmations           │   • Web search        │
│   • Conversational UI       │   • Screenshots       │
└─────────────────────────────┴───────────────────────┘
       │ (escalate_to_supervisor)
       ▼
┌─────────────────────────────────────────────────────┐
│            SUPERVISOR AGENT (Backend)               │
│   Model: Configurable (GPT-4, etc.)                 │
│   Tools: All native, built-in, MCP, and Anki tools  │
└─────────────────────────────────────────────────────┘
```

---

## Tool Summary

| Agent | Tool Source | Tool Count | Description |
|-------|-------------|------------|-------------|
| **Realtime** | Native | 1 | `escalate_to_supervisor` only |
| **Supervisor** | OpenAI Built-in | 4 | web_search, code_interpreter, image_generation, file_search |
| **Supervisor** | Native Python | 4 | local_time, safe_action, screencapture, anki_agent |
| **Supervisor** | ScreenMonitorMCP | 26 | Screen analysis, streaming, memory tools |
| **Supervisor** | PTY Proxy MCP | 1 | Terminal command execution |
| **Supervisor** | macOS-Automator MCP | 3 | AppleScript, accessibility, scripting tips |
| **Supervisor** | Feedback Loop MCP | 1 | Human-in-the-loop confirmation |
| **Anki Subagent** | Internal | 14 | Anki flashcard management (via anki_agent) |

**Total Supervisor Tools:** ~39 (+ 14 internal Anki tools)

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Realtime Agent Tools](#realtime-agent-tools) (1 tool)
- [Supervisor Agent Tools](#supervisor-agent-tools)
  - [OpenAI Built-in Tools](#openai-built-in-tools) (4 tools)
  - [Native Python Tools](#native-python-tools) (4 tools)
  - [ScreenMonitorMCP Tools](#screenmonitormcp-tools) (26 tools)
  - [PTY Proxy Tools](#pty-proxy-tools) (1 tool)
  - [macOS-Automator MCP Tools](#macos-automator-mcp-tools) (3 tools)
  - [Feedback Loop MCP Tools](#feedback-loop-mcp-tools) (1 tool)
- [Anki Subagent Tools](#anki-subagent-tools) (14 tools)
- [Tool Usage Guidelines](#tool-usage-guidelines)

---

## Realtime Agent Tools

The Realtime agent acts as a "front desk" for voice interactions. It has **only one tool** and uses its own reasoning to decide when to escalate.

### `escalate_to_supervisor`

**Source:** `main.py`
**Status:** Always Enabled

**Description:**
Route a complex task to the Supervisor agent for processing. The Realtime agent calls this when a request requires tools, multi-step planning, or capabilities beyond simple conversation.

**Parameters:**
- `task_description` (required, string): Description of what the user wants to accomplish
- `context` (optional, string): Additional context from the conversation

**Returns:** The Supervisor's response (streamed to TTS)

**When to Escalate:**
- User needs any tool (screenshots, web search, code execution, MCP tools)
- Task requires multi-step planning or synthesis
- User wants file/document search or RAG retrieval
- High-stakes or irreversible actions
- Ambiguity remains after one clarifying question

---

## Supervisor Agent Tools

The Supervisor handles all tool-requiring tasks. It has access to OpenAI built-in tools, native Python tools, and MCP server tools.

---

### OpenAI Built-in Tools

These tools are provided by OpenAI's Responses API and execute on OpenAI's infrastructure.

#### `web_search`

**Description:** Search the web for current information.

**When to Use:**
- Real-time information (news, weather, stock prices)
- Research topics requiring current data
- Fact-checking and verification

---

#### `code_interpreter`

**Description:** Execute Python code in a sandboxed environment.

**When to Use:**
- Data analysis and calculations
- File format conversions
- Generate visualizations and charts
- Process uploaded files

---

#### `image_generation`

**Description:** Generate images using DALL-E.

**When to Use:**
- Create images from text descriptions
- Visual content generation

---

#### `file_search`

**Description:** Search through uploaded documents using vector search.

**Status:** Only available if `OPENAI_VECTOR_STORE_ID` is configured in `.env`

**When to Use:**
- RAG (Retrieval Augmented Generation) queries
- Search through document collections

---

### Native Python Tools

These tools are defined in Python and run locally.

#### 1. `local_time`

**Source:** `main.py`
**Status:** Always Enabled

**Description:**
Return the local time (useful as a tool-call sanity check).

**Parameters:** None

**Returns:** Current local time in ISO format

---

#### 2. `safe_action`

**Source:** `automation_safety.py`
**Status:** Enabled (requires AUTOMATION_SAFETY_AVAILABLE)

**Description:**
Execute a desktop automation action with safety confirmation. This tool automatically handles the complete safety flow:
1. Takes a screenshot for context
2. Highlights the target region (if coordinates provided)
3. Requests user confirmation via overlay UI
4. Executes the action only if approved

**Parameters:**
- `action_type` (required, enum): Type of action
  - `"click"` - Requires: x, y
  - `"double_click"` - Requires: x, y
  - `"type"` - Requires: text (string, min length 1)
  - `"hotkey"` - Requires: hotkey (string, min length 1)
  - `"window_control"` - Requires: window_title (string, min length 1)
- `description` (required, string): Human-readable description of what the action will do
- `x` (optional, integer): X coordinate (for click, double_click)
- `y` (optional, integer): Y coordinate (for click, double_click)
- `text` (optional, string): Text to type (for type action)
- `window_title` (optional, string): Window title substring (for window_control)
- `hotkey` (optional, string): Hotkey combination (e.g., "cmd+tab", "ctrl+c")

**Returns:** Success message or error description

---

#### 3. `screencapture`

**Source:** `native_screenshot.py`
**Status:** Enabled (requires NATIVE_SCREENSHOT_AVAILABLE)

**Description:**
Capture a screenshot using native OS APIs and save it to the `screenshots/` directory. Returns metadata only; the image is automatically sent to the agent for visual analysis.

**Parameters:**
- `region` (optional, string): Region to capture in format "x,y,width,height"
- `description` (optional, string): Human-readable description of what this screenshot is for

**Returns:** JSON with screenshot metadata (path, dimensions, timestamp)

**Platform Support:**
- **macOS:** Uses native `screencapture` command
- **Windows/Linux:** Uses PIL/Pillow

---

#### 4. `anki_agent`

**Source:** `supervisor.py` (wraps `anki_agent.py`)
**Status:** Enabled by default

**Description:**
Delegate ALL Anki tasks to the specialized Anki subagent. This tool connects directly to Anki via AnkiConnect and should be used for ANY Anki-related request - never use safe_action or keyboard shortcuts for Anki.

**Parameters:**
- `task` (required, string): The Anki-related task to perform (e.g., "Open Anki browser", "Create a flashcard about photosynthesis", "Start reviewing Biology deck")

**Returns:** JSON with status, action, summary, and data

**Capabilities:**
- **GUI Control**: Open browser window, start deck review, open Add Cards dialog
- **Deck Management**: List, create, and manage decks
- **Card Creation**: Create cloze cards with proper syntax
- **Search & Browse**: Search and browse cards
- **Card States**: Manage tags, suspend/unsuspend cards

See [Anki Subagent Tools](#anki-subagent-tools) for the 14 internal tools.

---

### ScreenMonitorMCP Tools

**Source:** `ScreenMonitorMCP/screenmonitormcp_v2/`
**Status:** Always Enabled
**Total:** 26 tools

#### Screen Analysis Tools

| Tool | Description |
|------|-------------|
| `analyze_screen` | Analyze current screen content using AI vision |
| `detect_ui_elements` | Detect and classify UI elements |
| `assess_system_performance` | Assess visible system performance indicators |
| `detect_anomalies` | Detect visual anomalies and unusual patterns |
| `generate_monitoring_report` | Generate comprehensive monitoring report |

#### AI Service Tools

| Tool | Description |
|------|-------------|
| `chat_completion` | Generate chat completion using AI models |
| `list_ai_models` | List available AI models |
| `get_ai_status` | Get AI service configuration status |

#### Streaming Tools

| Tool | Description |
|------|-------------|
| `create_stream` | Create a new screen streaming session |
| `list_streams` | List all active streaming sessions |
| `get_stream_info` | Get information about a specific stream |
| `get_stream_diagnostics` | Get detailed diagnostics for a stream |
| `stop_stream` | Stop a specific streaming session |

#### Memory System Tools

| Tool | Description |
|------|-------------|
| `analyze_scene_from_memory` | Analyze scene based on stored memory data |
| `query_memory` | Query the memory system for stored analysis data |
| `get_memory_statistics` | Get memory system statistics |
| `get_stream_memory_stats` | Get memory system statistics for streaming |
| `configure_stream_memory` | Configure memory system for streaming |
| `get_memory_usage` | Get detailed memory usage and performance metrics |
| `configure_auto_cleanup` | Configure automatic memory cleanup settings |

#### Resource Management Tools

| Tool | Description |
|------|-------------|
| `get_stream_resource_stats` | Get streaming resource usage statistics |
| `configure_stream_resources` | Configure streaming resource limits |
| `get_database_pool_stats` | Get database connection pool statistics |
| `database_pool_health_check` | Perform database pool health check |

#### System Status Tools

| Tool | Description |
|------|-------------|
| `get_performance_metrics` | Get detailed performance metrics and system health |
| `get_system_status` | Get overall system status and health information |

---

### PTY Proxy Tools

**Source:** `pty_proxy_mcp.py`
**Status:** Always Enabled
**Total:** 1 tool

#### `pty_bash_execute`

**Description:** Execute a shell command in a bash environment. Safe commands execute immediately; risky commands require user confirmation.

**Parameters:**
- `command` (required, string): Shell command to execute
- `working_directory` (optional, string): Working directory for command execution
- `timeout_seconds` (optional, number, default: 30): Maximum execution time

**Safe Commands (auto-execute):** pwd, ls, cat, grep, find, head, tail, etc.

**Risky Commands (require approval):** mkdir, rm, chmod, network operations, etc.

---

### macOS-Automator MCP Tools

**Source:** `macos-automator-mcp` (local patched version)
**Status:** Enabled (requires `ENABLE_MACOS_AUTOMATOR_MCP=true`)
**Total:** 3 tools

#### 1. `execute_script`

**Description:** Execute AppleScript or JXA (JavaScript for Automation) code on macOS.

**Parameters:**
- `input` (required, object):
  - `script_content` (optional, string): Inline AppleScript/JXA code
  - `script_path` (optional, string): Path to script file
  - `kb_script_id` (optional, string): ID of pre-built script from knowledge base
  - `input_data` (optional, object): Parameters for knowledge base scripts
  - `language` (optional, string, default: "applescript"): "applescript" or "javascript"
  - `timeout_seconds` (optional, integer, default: 60): Execution timeout

---

#### 2. `accessibility_query`

**Description:** Query and interact with macOS UI elements using accessibility APIs.

**Parameters:**
- `command` (required, string): Operation ("query", "click", "set_value", etc.)
- `locator` (required, object): UI element locator (app, role, label, match)
- `value` (optional, any): Value to set (for set_value command)

---

#### 3. `get_scripting_tips`

**Description:** Search through 200+ pre-built automation recipes and get contextual help.

**Parameters:**
- `query` (optional, string): Search keywords
- `category` (optional, string): Filter by category
- `limit` (optional, integer, default: 10): Maximum results

---

### Feedback Loop MCP Tools

**Source:** `npx feedback-loop-mcp` (via wrapper)
**Status:** Enabled (requires `ENABLE_FEEDBACK_LOOP_MCP=true`)
**Total:** 1 tool

#### `feedback_loop`

**Description:** Request human-in-the-loop feedback via native macOS overlay UI.

**Parameters:**
- `project_directory` (required, string): Full path to the project directory
- `prompt` (required, string): Summary and question for the user
- `quickFeedbackOptions` (optional, array): Predefined feedback options as clickable buttons

**Returns:** User feedback response

---

## Anki Subagent Tools

These tools are **internal to the Anki subagent** and are accessed via the `anki_agent` wrapper tool on the Supervisor.

**Source:** `anki_agent.py`
**Model:** gpt-4.1-mini
**Total:** 14 tools

### Deck Management

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `anki_list_decks` | List all Anki deck names | None |
| `anki_create_deck` | Create a deck (supports nested like 'Parent::Child') | deck |

### Card Creation & Editing

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `anki_add_cloze` | Add a Cloze note with {{c1::...}} syntax | deck, text |
| `anki_update_note_fields` | Update fields of an existing note | note_id, fields |

### Search & Query

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `anki_find_notes` | Find note IDs using Anki search query | query |
| `anki_notes_info` | Fetch note info (fields, tags, etc.) | note_ids |

### Card Management

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `anki_add_tags` | Add tags to existing notes | note_ids, tags |
| `anki_change_deck` | Move cards to a different deck | deck + (card_ids OR query) |
| `anki_unsuspend` | Unsuspend cards | card_ids OR query |
| `anki_are_suspended` | Check if cards are suspended | card_ids OR query |

### GUI Control

| Tool | Description | Required Params |
|------|-------------|-----------------|
| `anki_gui_browse` | Open Anki's card browser with search | query |
| `anki_gui_add_cards` | Open Add Cards dialog (empty or with preset values) | None (deck, model, fields optional) |
| `anki_gui_current_card` | Get info about card currently being reviewed | None |
| `anki_gui_deck_review` | Open a deck for review | deck |

### Agent Behavior: Missing Parameters

When the user's request is missing required parameters, the Anki agent returns a `needs_info` status instead of guessing or failing silently:

```json
{
  "status": "needs_info",
  "action": "create_card",
  "summary": "Need deck name to create flashcard",
  "missing_params": ["deck"],
  "details": "Which deck should I add this card to?"
}
```

This allows the Supervisor to ask the user for the missing information.

---

## Tool Usage Guidelines

### Escalation Decision (Realtime Agent)

The Realtime agent should escalate to Supervisor when:
- **Tool needed:** Any tool use (screenshots, web search, terminal, automation)
- **Multi-step:** Task requires planning or multiple operations
- **Information retrieval:** Web search, file search, RAG queries
- **High-stakes:** Irreversible actions (delete, send, purchase)
- **Ambiguity:** User's intent unclear after one clarification

### Confirmation Requirements

| Requires Confirmation | No Confirmation Needed |
|-----------------------|------------------------|
| Risky/irreversible actions | Read-only operations |
| Desktop automation (safe_action) | screencapture |
| Risky shell commands (rm, chmod) | Safe shell commands (ls, cat) |
| State-changing operations | Information retrieval |

### Tool Selection Priority

**For Visual Inspection:**
1. `screencapture` - Primary tool for seeing the screen
2. `analyze_screen` - Only when user explicitly requests analysis

**For Desktop Automation:**
1. `safe_action` - For all desktop control (handles confirmation flow)
2. Direct `execute_script` - For custom AppleScript when needed

**For Shell Commands:**
- `pty_bash_execute` - Safe commands auto-execute, risky commands prompt

**For Anki:**
- `anki_agent` with task description - Handles all Anki operations

---

## Configuration

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENABLE_MACOS_AUTOMATOR_MCP` | Enable macOS automation tools | false |
| `ENABLE_FEEDBACK_LOOP_MCP` | Enable feedback loop UI | false |
| `OPENAI_VECTOR_STORE_ID` | Enable file_search tool | None |
| `AUTOMATION_REQUIRE_APPROVAL` | Require confirmation for actions | true |

### MCP Servers Configuration

See `MCP_SERVERS.json` for MCP server definitions.

---

**Last Updated:** 2026-01-22
**Agent Version:** HALfred v0.18+

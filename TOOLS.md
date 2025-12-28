# HALfred Agent Tools Documentation

This document describes all tools available to the HALfred agent, organized by source.

**Last Updated:** 2025-12-27
**Total Tools Available:** 50

---

## Current Configuration

### ✅ **Tools Currently Provided to Agent: 50/50**

All tools from all sources are currently being sent to the OpenAI Realtime API agent.

**Breakdown:**
- ✅ **Native Python Tools:** 2/2 provided
  - `local_time`
  - `safe_action`
- ✅ **ScreenMonitorMCP Tools:** 26/26 provided
  - All screen analysis, streaming, memory, and system monitoring tools
- ✅ **PTY Proxy Tools:** 1/1 provided
  - `pty_bash_execute`
- ✅ **Automation MCP Tools:** 20/20 provided
  - All mouse, keyboard, screen, window, and advanced automation tools
  - Requires: `ENABLE_AUTOMATION_MCP=true` in `.env`
- ✅ **Feedback Loop MCP Tools:** 1/1 provided
  - `feedback_loop`
  - Requires: `ENABLE_FEEDBACK_LOOP_MCP=true` in `.env`

### Configuration Status

| MCP Server | Status | Tool Count | Config Required |
|------------|--------|------------|-----------------|
| Native Python | ✅ Always On | 2 | None |
| ScreenMonitorMCP | ✅ Always On | 26 | None |
| PTY Proxy | ✅ Always On | 1 | None |
| Automation MCP | ✅ **Enabled** | 20 | `ENABLE_AUTOMATION_MCP=true` |
| Feedback Loop MCP | ✅ **Enabled** | 1 | `ENABLE_FEEDBACK_LOOP_MCP=true` |

**Note:** While all 50 tools are technically available to the agent, usage guidelines in the prompt instruct when each tool should be used. For example:
- `screenshot` - Use freely whenever visual context is needed
- `analyze_screen` - Only when user explicitly requests screen analysis
- `safe_action` - For all desktop automation with user confirmation

---

## Table of Contents

- [Current Configuration](#current-configuration)
- [Native Python Tools](#native-python-tools) (2 tools)
- [ScreenMonitorMCP Tools](#screenmonitormcp-tools) (26 tools)
- [PTY Proxy Tools](#pty-proxy-tools) (1 tool)
- [Automation MCP Tools](#automation-mcp-tools) (20 tools)
- [Feedback Loop MCP Tools](#feedback-loop-mcp-tools) (1 tool)
- [Tool Usage Guidelines](#tool-usage-guidelines)

---

## Native Python Tools

### 1. `local_time`

**Source:** `main.py`
**Status:** ✅ Always Enabled

**Description:**
Return the local time (useful as a tool-call sanity check).

**Parameters:** None

**Returns:** Current local time in ISO format

**When to Use:**
- As a sanity check for tool execution
- When user asks for current time

---

### 2. `safe_action`

**Source:** `automation_safety.py`
**Status:** ✅ Always Enabled

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

**Schema Notes:**
- Only `action_type` and `description` are always required
- Conditional requirements enforced via JSON Schema `allOf`
- No null values allowed for required conditional fields
- String fields have `minLength: 1` validation

**Returns:** Success message or error description

**When to Use:**
- For all desktop control actions
- Click/double-click UI elements
- Type text into fields
- Execute keyboard shortcuts
- Control windows

**Usage Guidelines:**
- State-changing actions require on-screen user confirmation
- Read-only actions execute automatically
- Always brief the user before using and confirm results after

---

## ScreenMonitorMCP Tools

**Source:** `ScreenMonitorMCP/screenmonitormcp_v2/`
**Status:** ✅ Always Enabled
**Total:** 26 tools

### Screen Analysis Tools

#### `analyze_screen`

**Description:** Analyze the current screen content using AI vision

**Parameters:**
- `query` (required, string): What to analyze or look for in the screen
- `monitor` (optional, integer, default: 0): Monitor number to analyze
- `detail_level` (optional, enum, default: "high"): Level of detail
  - `"low"`
  - `"high"`

**Returns:** Analysis result as text

**When to Use:**
- ⚠️ **ONLY when user explicitly asks** to analyze screen content
- Not for general visual inspection - use `screenshot` instead
- When you need text-based analysis rather than raw visual data

---

#### `detect_ui_elements`

**Description:** Detect and classify UI elements in the current screen

**Parameters:**
- `monitor` (optional, integer, default: 0): Monitor number to analyze

**Returns:** UI elements detection results as text

---

#### `assess_system_performance`

**Description:** Assess system performance indicators visible on screen

**Parameters:**
- `monitor` (optional, integer, default: 0): Monitor number to analyze

**Returns:** Performance assessment results as text

---

#### `detect_anomalies`

**Description:** Detect visual anomalies and unusual patterns in the screen

**Parameters:**
- `monitor` (optional, integer, default: 0): Monitor number to analyze
- `baseline_description` (optional, string): Optional description of normal state for comparison

**Returns:** Anomaly detection results as text

---

#### `generate_monitoring_report`

**Description:** Generate comprehensive monitoring report from screen analysis

**Parameters:**
- `monitor` (optional, integer, default: 0): Monitor number to analyze
- `context` (optional, string): Additional context for the report

**Returns:** Comprehensive monitoring report as text

---

### AI Service Tools

#### `chat_completion`

**Description:** Generate chat completion using AI models

**Parameters:**
- `messages` (required, array of ChatMessage objects): Array of chat messages with role and content
  - Each message must have:
    - `role` (required, enum): `"system"`, `"user"`, `"assistant"`, or `"tool"`
    - `content` (required, string): Message content text
- `model` (optional, string): AI model to use
- `max_tokens` (optional, integer, default: 1000): Maximum tokens for response
- `temperature` (optional, number, default: 0.7): Temperature for response generation

**Returns:** AI response as text

**Example message structure:**
```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "What is the weather today?"}
]
```

---

#### `list_ai_models`

**Description:** List available AI models from the configured provider

**Parameters:** None

**Returns:** List of available models as text

---

#### `get_ai_status`

**Description:** Get AI service configuration status

**Parameters:** None

**Returns:** AI service status information

---

### Streaming Tools

#### `create_stream`

**Description:** Create a new screen streaming session

**Parameters:**
- `monitor` (optional, integer, default: 0): Monitor number to stream
- `fps` (optional, integer, default: 10): Frames per second for streaming
- `quality` (optional, integer, default: 80): Image quality (1-100)
- `format` (optional, enum, default: "jpeg"): Image format
  - `"jpeg"`
  - `"png"`

**Returns:** Stream ID or error message

**Important:** Save the stream_id! Must use it when calling `analyze_scene_from_memory()` or `query_memory()`.

---

#### `list_streams`

**Description:** List all active streaming sessions

**Parameters:** None

**Returns:** List of active streams

---

#### `get_stream_info`

**Description:** Get information about a specific stream

**Parameters:**
- `stream_id` (required, string): Stream ID to get information for

**Returns:** Stream information

---

#### `get_stream_diagnostics`

**Description:** Get detailed diagnostics for a stream to debug why it might have stopped

**Parameters:**
- `stream_id` (required, string): Stream ID to diagnose

**Returns:** Diagnostic information including task state and any exceptions

---

#### `stop_stream`

**Description:** Stop a specific streaming session

**Parameters:**
- `stream_id` (required, string): Stream ID to stop

**Returns:** Success or error message

---

### Memory System Tools

#### `analyze_scene_from_memory`

**Description:** Analyze scene based on stored memory data

**Parameters:**
- `query` (required, string): What to analyze or look for in the stored scenes
- `stream_id` (optional, string): Stream ID to query (REQUIRED when analyzing active streams)
- `time_range_minutes` (optional, integer, default: 30): Time range to search in minutes
- `limit` (optional, integer, default: 10): Maximum number of results to analyze

**Returns:** Scene analysis based on memory data with metadata about data freshness

**Critical:** You MUST provide stream_id when querying memory for an active screen stream.

---

#### `query_memory`

**Description:** Query the memory system for stored analysis data

**Parameters:**
- `query` (required, string): Search query for memory entries
- `stream_id` (optional, string): Stream ID to filter by (REQUIRED when querying active streams)
- `time_range_minutes` (optional, integer, default: 60): Time range to search in minutes
- `limit` (optional, integer, default: 20): Maximum number of results

**Returns:** Memory query results with metadata about data freshness

**Critical:** You MUST provide stream_id when querying memory for an active screen stream.

---

#### `get_memory_statistics`

**Description:** Get memory system statistics and health information

**Parameters:** None

**Returns:** Memory system statistics

---

#### `get_stream_memory_stats`

**Description:** Get memory system statistics for streaming

**Parameters:** None

**Returns:** Streaming memory statistics

---

#### `configure_stream_memory`

**Description:** Configure memory system for streaming

**Parameters:**
- `enabled` (optional, boolean, default: true): Enable or disable memory system for streaming
- `analysis_interval` (optional, integer, default: 5): Analysis interval in frames

**Returns:** Configuration result

---

#### `get_memory_usage`

**Description:** Get detailed memory usage and performance metrics

**Parameters:** None

**Returns:** Detailed memory usage statistics

---

#### `configure_auto_cleanup`

**Description:** Configure automatic memory cleanup settings

**Parameters:**
- `enabled` (required, boolean): Enable or disable auto cleanup
- `max_age_days` (optional, integer, default: 7): Maximum age for entries in days

**Returns:** Configuration result

---

### Resource Management Tools

#### `get_stream_resource_stats`

**Description:** Get streaming resource usage statistics

**Parameters:** None

**Returns:** Streaming resource usage statistics

---

#### `configure_stream_resources`

**Description:** Configure streaming resource limits

**Parameters:**
- `max_memory_mb` (optional, integer): Maximum memory usage in MB
- `max_streams` (optional, integer): Maximum concurrent streams
- `frame_buffer_size` (optional, integer): Maximum frames to buffer per stream
- `cleanup_interval` (optional, integer): Cleanup interval in seconds

**Returns:** Configuration result

---

#### `get_database_pool_stats`

**Description:** Get database connection pool statistics

**Parameters:** None

**Returns:** Database pool usage statistics

---

#### `database_pool_health_check`

**Description:** Perform database pool health check

**Parameters:** None

**Returns:** Database pool health status

---

### System Status Tools

#### `get_performance_metrics`

**Description:** Get detailed performance metrics and system health

**Parameters:** None

**Returns:** Performance metrics as text

**When to Use:**
- For real-time monitoring
- System health tracking

---

#### `get_system_status`

**Description:** Get overall system status and health information

**Parameters:** None

**Returns:** System status information

---

## PTY Proxy Tools

**Source:** `pty_proxy_mcp.py`
**Status:** ✅ Always Enabled
**Total:** 1 tool

### `pty_bash_execute`

**Description:** Execute a shell command in a bash environment. Safe commands (pwd, ls, cat, grep, find, etc.) are executed immediately. Risky commands (mkdir, rm, chmod, network operations) require user confirmation. Use this tool to inspect files, navigate directories, and gather system information.

**Parameters:**
- `command` (required, string): Shell command to execute (will be run in bash)
- `working_directory` (optional, string): Optional working directory for command execution (defaults to current directory)
- `timeout_seconds` (optional, number, default: 30): Maximum execution time in seconds

**Returns:** Command output or error

**When to Use:**
- File and system inspection (safe: `pwd`, `ls`, `cat`, etc.)
- Risky commands (e.g., `rm`, `chmod`, network) require user approval
- Always explain actions and reasoning for shell commands

**Safety:**
- Safe commands execute automatically
- Risky commands require user confirmation
- Timeout protection (30 seconds default)

---

## Automation MCP Tools

**Source:** `node_modules/automation-mcp/`
**Status:** ✅ Always Enabled (ENABLE_AUTOMATION_MCP=true)
**Total:** 20 tools

### Mouse Control Tools (7 tools)

#### `mouseClick`

**Description:** Simulate a mouse click at the given screen coordinates.

**Parameters:**
- `x` (required, number): Horizontal screen coordinate (pixels)
- `y` (required, number): Vertical screen coordinate (pixels)
- `button` (optional, enum, default: "left"): Mouse button to click
  - `"left"`
  - `"right"`
  - `"middle"`

---

#### `mouseDoubleClick`

**Description:** Simulate a mouse double-click at the given screen coordinates.

**Parameters:**
- `x` (required, number): Horizontal screen coordinate (pixels)
- `y` (required, number): Vertical screen coordinate (pixels)
- `button` (optional, enum, default: "left"): Mouse button to double-click
  - `"left"`
  - `"right"`
  - `"middle"`

---

#### `mouseMove`

**Description:** Move the mouse to specific coordinates.

**Parameters:**
- `x` (required, number): Horizontal screen coordinate (pixels)
- `y` (required, number): Vertical screen coordinate (pixels)

---

#### `mouseGetPosition`

**Description:** Get the current mouse cursor position.

**Parameters:** None

**Returns:** Current mouse coordinates

---

#### `mouseScroll`

**Description:** Scroll the mouse wheel in a specified direction.

**Parameters:**
- `direction` (required, enum): Direction to scroll
  - `"up"`
  - `"down"`
  - `"left"`
  - `"right"`
- `amount` (optional, number, default: 3): Number of scroll steps

---

#### `mouseDrag`

**Description:** Drag the mouse from current position to target coordinates.

**Parameters:**
- `x` (required, number): Target horizontal coordinate (pixels)
- `y` (required, number): Target vertical coordinate (pixels)

---

#### `mouseButtonControl`

**Description:** Press or release a mouse button without clicking.

**Parameters:**
- `action` (required, enum): Action to perform
  - `"press"`
  - `"release"`
- `button` (optional, enum, default: "left"): Mouse button to control
  - `"left"`
  - `"right"`
  - `"middle"`

---

### Keyboard Control Tools (2 tools)

#### `keyboard_type`

**Description:** Simulate typing text or pressing key combinations. Provide either 'text' to type literal text, OR 'keys' as comma-separated key names for key combinations (not both).

**Parameters (mutually exclusive):**
- `text` (string, min length 1): Literal text to type
  - **OR**
- `keys` (string, min length 1): Comma-separated key names to press simultaneously (e.g. 'LeftControl,C')

**Note:** Schema enforces exactly one of `text` OR `keys` must be provided.

---

#### `keyControl`

**Description:** Press or release specific keys for advanced key combinations.

**Parameters:**
- `action` (required, enum): Action to perform
  - `"press"`
  - `"release"`
- `keys` (required, string): Comma-separated key names to control (e.g. 'LeftControl,LeftShift')

---

### Screen Tools (4 tools)

#### `screenshot`

**Description:** Capture a screenshot (full screen, region, or window). Default to full screen if no preference. This will also provide information about the user's screen in order to correctly position mouse clicks and keyboard inputs.

**Parameters:**
- `mode` (optional, enum, default: "full"): Capture mode
  - `"full"` - Entire screen
  - `"region"` - Specific region
  - `"window"` - Specific window
- `regionX` (optional, number): Region X coordinate (for region mode)
- `regionY` (optional, number): Region Y coordinate (for region mode)
- `regionWidth` (optional, number): Region width (for region mode)
- `regionHeight` (optional, number): Region height (for region mode)
- `windowName` (optional, string): Window title (if mode=window)
- `windowId` (optional, number): Window ID (if mode=window)

**Returns:** Screenshot image + screen dimensions

**When to Use:**
- ✅ **Use freely, no approval required**
- Use any time you need visual context about what's on screen
- Your primary way to see what the user sees
- For UI automation (finding buttons, reading coordinates)
- For understanding screen layout and content

**Important:** This is the agent's primary visual tool. Use it whenever you need to see the screen.

---

#### `screenInfo`

**Description:** Get screen dimensions and information.

**Parameters:** None

**Returns:** Screen width, height, and configuration

---

#### `screenHighlight`

**Description:** Highlight a region on the screen for visual feedback.

**Parameters:**
- `x` (required, number): Left coordinate of region
- `y` (required, number): Top coordinate of region
- `width` (required, number): Width of region
- `height` (required, number): Height of region

---

#### `colorAt`

**Description:** Get the color of a pixel at specific screen coordinates.

**Parameters:**
- `x` (required, number): X coordinate
- `y` (required, number): Y coordinate

**Returns:** RGB color values

---

### Window Management Tools (3 tools)

#### `getWindows`

**Description:** Get information about all open windows.

**Parameters:** None

**Returns:** List of all open windows with titles and IDs

---

#### `getActiveWindow`

**Description:** Get information about the currently active window.

**Parameters:** None

**Returns:** Active window information

---

#### `windowControl`

**Description:** Control a window (focus, move, resize, minimize, restore).

**Parameters:**
- `action` (required, enum): Action to perform
  - `"focus"`
  - `"move"`
  - `"resize"`
  - `"minimize"`
  - `"restore"`
- `windowTitle` (optional, string): Window title to target (uses active window if not provided)
- `x` (optional, number): X coordinate for move action
- `y` (optional, number): Y coordinate for move action
- `width` (optional, number): Width for resize action
- `height` (optional, number): Height for resize action

---

### Advanced Automation Tools (4 tools)

#### `waitForImage`

**Description:** Wait for an image to appear on screen and return its location.

**Parameters:**
- `imagePath` (required, string): Path to the template image file
- `timeoutMs` (optional, number, default: 5000): Timeout in milliseconds
- `confidence` (optional, number, default: 0.8): Match confidence (0-1)

**Returns:** Image location coordinates

---

#### `sleep`

**Description:** Pause execution for a specified amount of time.

**Parameters:**
- `ms` (required, number): Time to sleep in milliseconds

---

#### `mouseMovePath`

**Description:** Move mouse along a path of coordinates with smooth animation.

**Parameters:**
- `path` (required, array of numbers): Array of coordinates to move through (alternating x,y values: [x1,y1,x2,y2,...])

---

#### `systemCommand`

**Description:** Execute common system key combinations (copy, paste, undo, etc.).

**Parameters:**
- `command` (required, enum): System command to execute
  - `"copy"`
  - `"paste"`
  - `"cut"`
  - `"undo"`
  - `"redo"`
  - `"selectAll"`
  - `"save"`
  - `"quit"`
  - `"minimize"`
  - `"switchApp"`
  - `"newTab"`
  - `"closeTab"`

---

## Feedback Loop MCP Tools

**Source:** `npx feedback-loop-mcp`
**Status:** ✅ Enabled (ENABLE_FEEDBACK_LOOP_MCP=true)
**Total:** 1 tool

### `feedback_loop`

**Description:** Request feedback loop for a given project directory and summary

**Parameters:**
- `project_directory` (required, string): Full path to the project directory
- `prompt` (required, string): Combined summary and question, describing what was done and asking for specific feedback
- `quickFeedbackOptions` (optional, array of strings): Optional array of predefined feedback strings to present as clickable options

**Returns:** User feedback response

**When to Use:**
- When automation safety system needs user confirmation
- For human-in-the-loop decision making
- Used internally by `safe_action` for confirmations

---

## Tool Usage Guidelines

### General Principles

1. **Use tools when needed** - Don't fake it, actually use the tools
2. **Brief preamble** - Before a tool call, give a short explanation (e.g., "Checking that now.")
3. **One-line narration** - Narrate tool usage briefly; no detailed play-by-play
4. **Report results** - After tool use, give a brief result and next step
5. **Handle failures** - If tool output fails, state what happened, retry or ask for clarification
6. **Prefer read-only first** - Use read-only tools before making changes
7. **Verify with tools** - Use appropriate tools; avoid excessive calls

### Confirmation Requirements

**Require User Confirmation For:**
- Risky/irreversible actions (deleting, submitting, purchases)
- State-changing desktop automation
- Risky shell commands (rm, chmod, network operations)

**No Confirmation Needed:**
- Read-only operations
- `screenshot` tool (use freely)
- Safe shell commands (pwd, ls, cat, grep, find)
- Information retrieval

### Tool Selection Priority

**For Visual Inspection:**
1. **Primary:** `screenshot` - Use this whenever you need to see the screen
2. **Secondary:** `analyze_screen` - Only when user explicitly requests analysis

**For Desktop Automation:**
1. **Primary:** `safe_action` - For all desktop control (click, type, hotkey, window control)
2. **Fallback:** Direct automation-mcp tools (if safe_action unavailable)

**For Shell Commands:**
- Use `pty_bash_execute` for all shell operations
- Safe commands execute automatically
- Risky commands require user approval

### Conversation Control Loop

Each turn should follow this flow:
1. **Idle**
2. **Intent Detection** - Identify what user wants
3. **Context Build** - Gather context from conversation, screen state, tool outputs
4. **Plan** - Pick a plan
5. **Act** - Execute with minimal preamble
6. **Observe** - Check results (tools, screen, user feedback)
7. **Adjust** - Retry, alternate, or ask one short follow-up if needed
8. **Conclude** - Brief conclusion or return to idle

User may interrupt, jump topics, or give commands anytime. Each input restarts the loop.

---

## Configuration Files

- **MCP Servers:** `MCP_SERVERS.json`
- **Environment:** `.env`
  - `ENABLE_AUTOMATION_MCP=true`
  - `ENABLE_FEEDBACK_LOOP_MCP=true`
  - `AUTOMATION_REQUIRE_APPROVAL=true`

---

## Notes

- Total of 50 tools available to the agent
- All tools use OpenAI function calling JSON Schema format
- Tools are sent as a flat list to the Realtime API
- Conditional requirements implemented via JSON Schema `allOf` for `safe_action`
- Enums enforced for action types, detail levels, and format options

---

**Last Updated:** 2025-12-27
**Agent Version:** HALfred v0.10

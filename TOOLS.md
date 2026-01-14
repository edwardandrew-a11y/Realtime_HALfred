# HALfred Agent Tools Documentation

This document describes all tools available to the HALfred agent, organized by source.

**Last Updated:** 2026-01-03
**Total Tools Available:** 45

---

## Current Configuration

### ✅ **Tools Currently Provided to Agent: 45/45**

All tools from all sources are currently being sent to the OpenAI Realtime API agent.

**Breakdown:**
- ✅ **Native Python Tools:** 3/3 provided
  - `local_time`
  - `safe_action`
  - `screencapture` (native OS implementation - replaces Computer-Control MCP's version)
- ✅ **ScreenMonitorMCP Tools:** 26/26 provided
  - All screen analysis, streaming, memory, and system monitoring tools
- ✅ **PTY Proxy Tools:** 1/1 provided
  - `pty_bash_execute`
- ✅ **macOS-Automator MCP Tools:** 3/3 provided
  - AppleScript/JXA execution (1 tool), accessibility querying (1 tool), scripting tips (1 tool)
  - Note: Replaces Computer-Control MCP for better performance and native macOS integration
  - Requires: `ENABLE_MACOS_AUTOMATOR_MCP=true` in `.env`
- ✅ **Feedback Loop MCP Tools:** 1/1 provided
  - `feedback_loop`
  - Requires: `ENABLE_FEEDBACK_LOOP_MCP=true` in `.env`

### Configuration Status

| MCP Server | Status | Tool Count | Config Required |
|------------|--------|------------|-----------------|
| Native Python | ✅ Always On | 3 | None |
| ScreenMonitorMCP | ✅ Always On | 26 | None |
| PTY Proxy | ✅ Always On | 1 | None |
| macOS-Automator MCP | ✅ **Enabled** | 3 | `ENABLE_MACOS_AUTOMATOR_MCP=true` |
| Feedback Loop MCP | ✅ **Enabled** | 1 | `ENABLE_FEEDBACK_LOOP_MCP=true` |

**Note:** While all 45 tools are technically available to the agent, usage guidelines in the prompt instruct when each tool should be used. For example:
- `screencapture` - Use freely whenever visual context is needed (native OS implementation)
- `analyze_screen` - Only when user explicitly requests screen analysis
- `safe_action` - For all desktop automation with user confirmation

---

## Table of Contents

- [Current Configuration](#current-configuration)
- [Native Python Tools](#native-python-tools) (3 tools)
- [ScreenMonitorMCP Tools](#screenmonitormcp-tools) (26 tools)
- [PTY Proxy Tools](#pty-proxy-tools) (1 tool)
- [macOS-Automator MCP Tools](#macos-automator-mcp-tools) (3 tools)
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

### 3. `screencapture`

**Source:** `native_screenshot.py`
**Status:** ✅ Always Enabled

**Description:**
Capture a screenshot using native OS APIs and save it to the `screenshots/` directory. The tool returns only metadata (file path, dimensions, timestamp) and does NOT include base64-encoded image data in the response. The screenshot image is automatically sent to the Realtime API as a visual input so the agent can see what's on screen.

**Parameters:**
- `region` (optional, string): Region to capture in format "x,y,width,height" (e.g., "0,0,1920,1080"). If not specified, captures the full screen.
- `description` (optional, string): Human-readable description of what this screenshot is for.

**Returns:**
JSON string with screenshot metadata:
```json
{
  "success": true,
  "path": "screenshots/screenshot_20250129_143025_123.png",
  "filename": "screenshot_20250129_143025_123.png",
  "width": 1920,
  "height": 1080,
  "timestamp": "2025-01-29T14:30:25.123",
  "description": "Optional description"
}
```

**Platform Support:**
- **macOS:** Uses native `screencapture` command (fast, no dependencies)
- **Windows/Linux:** Uses PIL/Pillow (requires: `pip install Pillow`)

**When to Use:**
- Any time you need visual context about what's on screen
- This is your primary way to see what the user sees
- Use freely - no approval required
- The image is automatically sent to you for visual analysis

**Usage Guidelines:**
- Captures full screen by default
- Can capture specific regions by providing coordinates
- Screenshots are saved to `screenshots/` directory with timestamp filenames
- The agent receives both the metadata AND the actual screenshot image
- Prefer this over `analyze_screen` for general visual inspection

**Examples:**
```python
screencapture()  # Capture full screen
screencapture(region="100,100,800,600")  # Capture specific region
screencapture(description="Browser window showing error message")
```

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
- Not for general visual inspection - use `screencapture` instead
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

## macOS-Automator MCP Tools

**Source:** `macos-automator-mcp` via npx
**Status:** ✅ Enabled (ENABLE_MACOS_AUTOMATOR_MCP=true)
**Total:** 3 tools

**Migration Note:** This section replaces Computer-Control MCP Tools. The project migrated from PyAutoGUI-based automation to native macOS AppleScript/JXA for better performance, lower latency, and superior image processing capabilities. See `docs/MACOS_AUTOMATOR_MIGRATION.md` for details.

**Note:** Desktop automation actions are exposed through the `safe_action` wrapper tool which uses macos-automator-mcp internally via AppleScript execution.

### 1. `execute_script`

**Description:** Execute AppleScript or JXA (JavaScript for Automation) code on macOS. This is the primary tool for desktop automation, providing access to native macOS scripting capabilities.

**Parameters:**
- `input` (required, object): Execution parameters
  - `script_content` (optional, string): Inline AppleScript/JXA code to execute
  - `script_path` (optional, string): Path to script file to execute
  - `kb_script_id` (optional, string): ID of pre-built script from knowledge base (e.g., "safari_get_front_tab_url")
  - `input_data` (optional, object): Parameters to pass to knowledge base scripts
  - `language` (optional, string, default: "applescript"): Script language ("applescript" or "javascript")
  - `timeout_seconds` (optional, integer, default: 60): Execution timeout in seconds
  - `output_format_mode` (optional, string, default: "auto"): Output format mode

**Returns:** Script execution result as text, JSON, or plist depending on output_format

**Examples:**
```javascript
// Get screen size
execute_script({
  input: {
    script_content: `tell application "Finder"
      set screenBounds to bounds of window of desktop
      return "width: " & item 3 of screenBounds & ", height: " & item 4 of screenBounds
    end tell`
  }
})

// Click using cliclick
execute_script({
  input: {
    script_content: 'do shell script "/opt/homebrew/bin/cliclick c:100,200"'
  }
})

// Type text
execute_script({
  input: {
    script_content: `tell application "System Events"
      keystroke "Hello World"
    end tell`
  }
})

// Use knowledge base script
execute_script({
  input: {
    kb_script_id: "finder_create_new_folder_desktop",
    input_data: {"folder_name": "My New Folder"}
  }
})
```

**When to Use:**
- Directly executing automation actions (via `safe_action` wrapper)
- Running pre-built automation recipes from knowledge base
- Custom macOS automation tasks
- Application-specific automation (Safari, Finder, etc.)

---

### 2. `accessibility_query`

**Description:** Query and interact with macOS UI elements using accessibility APIs. Enables semantic UI automation without pixel-perfect coordinates.

**Parameters:**
- `command` (required, string): Operation to perform ("query", "click", "set_value", etc.)
- `locator` (required, object): UI element locator
  - `app` (optional, string): Application name to target
  - `role` (optional, string): Accessibility role (e.g., "AXButton", "AXTextField", "AXStaticText")
  - `label` (optional, string): Element label or title
  - `match` (optional, object): Additional matching criteria
- `value` (optional, any): Value to set (for set_value command)

**Returns:** Query results or action confirmation

**Examples:**
```javascript
// Find all buttons in Safari
accessibility_query({
  command: "query",
  locator: {
    app: "Safari",
    role: "AXButton"
  }
})

// Click a button by label
accessibility_query({
  command: "click",
  locator: {
    app: "Safari",
    role: "AXButton",
    label: "Go"
  }
})

// Find text fields
accessibility_query({
  command: "query",
  locator: {
    app: "Safari",
    role: "AXTextField"
  }
})
```

**When to Use:**
- Finding UI elements without knowing exact coordinates
- Clicking buttons/links by label instead of position
- Querying application UI structure
- More reliable automation across different screen resolutions

---

### 3. `get_scripting_tips`

**Description:** Search through 200+ pre-built automation recipes and get contextual help for macOS automation tasks.

**Parameters:**
- `query` (optional, string): Search keywords (e.g., "safari", "finder", "screenshot")
- `category` (optional, string): Filter by category (e.g., "browser", "system", "applications")
- `limit` (optional, integer, default: 10): Maximum number of results

**Returns:** List of relevant automation recipes with:
- Script ID (use with `execute_script`)
- Description
- Example usage
- Required parameters

**Examples:**
```javascript
// Search for Safari automation
get_scripting_tips({
  query: "safari open tab"
})

// Get Finder scripts
get_scripting_tips({
  category: "finder"
})

// Search for screenshot scripts
get_scripting_tips({
  query: "screenshot"
})
```

**When to Use:**
- Discovering automation capabilities
- Finding pre-built scripts for common tasks
- Learning automation patterns
- Getting examples for complex operations

---

**Note:** macOS-Automator-MCP provides native macOS automation through AppleScript/JXA and accessibility APIs. For most automation tasks, use the `safe_action` wrapper tool which internally calls `execute_script` with appropriate AppleScript code.

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
- `screencapture` tool (use freely)
- Safe shell commands (pwd, ls, cat, grep, find)
- Information retrieval

### Tool Selection Priority

**For Visual Inspection:**
1. **Primary:** `screencapture` - Use this whenever you need to see the screen
2. **Secondary:** `analyze_screen` - Only when user explicitly requests analysis

**For Desktop Automation:**
1. **Primary:** `safe_action` - For all desktop control (click, type, hotkey, window control)
2. **Fallback:** Direct automation-mcp tools (if safe_action unavailable)

**For Shell Commands:**
- Use `pty_bash_execute` for all shell operations
- Safe commands execute automatically
- Risky commands require user approval

### Coordinate Detection Strategies

When you need to click on UI elements, choose the right approach based on the element type:

**For TEXT elements (buttons with labels, menu items, text in fields):**

1. Use `take_screenshot_with_ocr` to extract text with precise coordinates
2. Returns `[[4 corners], text, confidence]` tuples with absolute screen coordinates
3. Use these exact coordinates for pixel-perfect clicking
4. Processing takes ~20 seconds at 1080p resolution
5. Best for: labeled buttons, menu items, any text you can click

**For VISUAL/GRAPHICAL elements (icons, colored buttons, close buttons, graphics):**

1. Use `screencapture` to get visual snapshot (image automatically sent to you)
2. Visually analyze the screenshot to locate the element
3. Estimate coordinates based on:
   - Visual position relative to screen edges
   - Common UI conventions (macOS close buttons at ~70,30-60; Windows close buttons in top-right)
   - Relative positioning to other visible elements and windows
4. If you need window information, use `execute_script` with AppleScript:
   ```applescript
   tell application "System Events"
     set appList to name of every process whose background only is false
   end tell
   ```
5. Explain your coordinate estimation reasoning to the user
6. Important: OCR completely omits small/low-contrast button text - if OCR fails, immediately fall back to visual estimation

**Example Decision Tree:**

- "Click the Send button" → `take_screenshot_with_ocr` (text-based button)
- "Click the red X close button" → `screencapture` + visual estimation (icon, not text)
- "Click the gear icon" → `screencapture` + visual estimation (icon, not text)
- "Click where it says 'Submit'" → `take_screenshot_with_ocr` (looking for specific text)
- "Click the green checkmark" → `screencapture` + visual estimation (colored icon, not text)

**Common UI Conventions for Estimation:**

- macOS window controls: Top-left at approximately (70, 30-60)
- Windows window controls: Top-right corner
- Toolbar icons: Usually evenly spaced in fixed toolbars
- Menu items: Vertically stacked with consistent spacing

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
  - `ENABLE_COMPUTER_CONTROL_MCP=true`
  - `ENABLE_FEEDBACK_LOOP_MCP=true`
  - `AUTOMATION_REQUIRE_APPROVAL=true`

---

## Notes

- Total of 45 tools available to the agent
- All tools use OpenAI function calling JSON Schema format
- Tools are sent as a flat list to the Realtime API
- Conditional requirements implemented via JSON Schema `allOf` for `safe_action`
- Enums enforced for action types, detail levels, and format options
- Computer-Control-MCP provides cross-platform automation via PyAutoGUI

---

**Last Updated:** 2026-01-03
**Agent Version:** HALfred v0.16

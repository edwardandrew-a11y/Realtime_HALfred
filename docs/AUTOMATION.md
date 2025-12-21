# Desktop Automation + Human-in-the-Loop Integration

Comprehensive guide to using automation-mcp and feedback-loop-mcp with Realtime HALfred.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Safety Features](#safety-features)
- [Developer Commands](#developer-commands)
- [Troubleshooting](#troubleshooting)
- [Platform Support](#platform-support)
- [API Reference](#api-reference)

---

## Overview

Realtime HALfred now supports desktop automation with built-in safety confirmations. This integration combines:

- **automation-mcp** (ashwwwin/automation-mcp): Provides desktop automation capabilities including:
  - Mouse clicks and movement
  - Keyboard typing and hotkeys
  - Window control and focus
  - Screenshot capture
  - Screen highlighting
  - Screen and window information queries

- **feedback-loop-mcp** (tuandinh-org/feedback-loop-mcp): Provides human-in-the-loop confirmation:
  - Native macOS overlay windows
  - Quick feedback buttons
  - Terminal fallback for non-macOS platforms

### Safety Architecture

All state-changing actions (clicks, typing, etc.) go through the `safe_action()` tool which:

1. **Takes a screenshot** for context
2. **Highlights the target** region on screen
3. **Requests confirmation** via overlay UI or terminal prompt
4. **Executes the action** only if approved

Read-only actions (screenshots, window queries) bypass confirmation for efficiency.

---

## Prerequisites

### 1. Bun Runtime (for automation-mcp)

**macOS/Linux:**
```bash
curl -fsSL https://bun.sh/install | bash
```

**Alternative (Homebrew on macOS):**
```bash
brew install bun
```

**Verify installation:**
```bash
bun --version
# Should show: bun 1.x.x
```

### 2. macOS Permissions (Required for automation-mcp)

automation-mcp requires system permissions to control your computer:

#### Grant Accessibility Permission:
1. Open **System Preferences → Security & Privacy → Privacy**
2. Click **Accessibility** in the left sidebar
3. Click the lock icon to make changes
4. Add your terminal app (Terminal.app, iTerm2, etc.)
5. Check the box to enable it

#### Grant Screen Recording Permission:
1. In the same **Privacy** pane, select **Screen Recording**
2. Add your terminal app
3. Check the box to enable it

**Important:** You must **restart your terminal** after granting permissions.

#### Verify Permissions:

After granting permissions, test with:
```bash
bun run node_modules/automation-mcp/index.ts --stdio
```

If you see errors like "AXIsProcessTrusted" or "CGWindow", permissions are not granted correctly.

### 3. Node.js (for npm/npx)

**macOS:**
```bash
brew install node
```

**Verify:**
```bash
node --version
npm --version
```

---

## Installation

### 1. Install Node.js Dependencies

From the Realtime HALfred project root:

```bash
npm install
# or
bun install
```

This installs:
- `automation-mcp` from GitHub (ashwwwin/automation-mcp)
- `feedback-loop-mcp` from npm

### 2. Verify Installation

Check that the MCP servers are installed:

```bash
ls node_modules/automation-mcp
ls node_modules/feedback-loop-mcp
```

### 3. Test MCP Servers

**Test automation-mcp:**
```bash
bun run node_modules/automation-mcp/index.ts --stdio
```

You should see JSON-RPC initialization messages. Press Ctrl+C to exit.

**Test feedback-loop-mcp:**
```bash
npx feedback-loop-mcp
```

---

## Configuration

### Environment Variables

Add to your `.env` file (copy from `.env.example` if needed):

```bash
# Desktop Automation MCP Settings
ENABLE_AUTOMATION_MCP=true          # Enable desktop automation
ENABLE_FEEDBACK_LOOP_MCP=true       # Enable confirmation UI
AUTOMATION_MCP_TIMEOUT=600          # Tool timeout (seconds)
FEEDBACK_LOOP_MCP_TIMEOUT=600
PREFERRED_DISPLAY_INDEX=0           # 0=primary, 1=secondary monitor
AUTOMATION_REQUIRE_APPROVAL=true    # Always confirm before actions

# Developer Mode
DEV_MODE=true                       # Enable debug commands
```

### Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_AUTOMATION_MCP` | `false` | Enable automation-mcp server |
| `ENABLE_FEEDBACK_LOOP_MCP` | `false` | Enable feedback-loop-mcp server |
| `AUTOMATION_MCP_TIMEOUT` | `600` | Timeout for automation tool calls (seconds) |
| `FEEDBACK_LOOP_MCP_TIMEOUT` | `600` | Timeout for feedback loop (seconds) |
| `PREFERRED_DISPLAY_INDEX` | `0` | For dual monitors: which display to use (0=primary) |
| `AUTOMATION_REQUIRE_APPROVAL` | `true` | Require confirmation for state-changing actions |
| `DEV_MODE` | `false` | Enable developer debug commands |

### MCP Server Configuration

The MCP servers are configured in `MCP_SERVERS.json`:

```json
{
  "name": "automation",
  "transport": "stdio",
  "params": {
    "command": "bun",
    "args": ["run", "node_modules/automation-mcp/index.ts", "--stdio"],
    "env": {}
  },
  "client_session_timeout_seconds": 600,
  "comment": "Desktop automation (macOS: requires permissions)"
},
{
  "name": "feedback-loop",
  "transport": "stdio",
  "params": {
    "command": "npx",
    "args": ["feedback-loop-mcp"],
    "env": {}
  },
  "client_session_timeout_seconds": 600,
  "comment": "Human-in-the-loop confirmation UI"
}
```

---

## Usage

### Basic Workflow

1. **Start HALfred:**
   ```bash
   python main.py
   ```

2. **Enable mic (optional):**
   ```
   /mic
   ```

3. **Ask HALfred to perform an action:**
   ```
   You> Click the Safari icon in my dock
   ```

4. **Review confirmation:**
   - A screenshot is taken
   - The target is highlighted (red rectangle)
   - A confirmation dialog appears (overlay or terminal)

5. **Approve or deny:**
   - Click "Proceed ✅" to execute
   - Click "Cancel ❌" to abort
   - Click "Adjust target 🎯" to refine coordinates

### Example Interactions

#### Example 1: Open an Application
```
You> Open Spotify for me
```

HALfred will:
1. Identify the Spotify icon location
2. Take a screenshot
3. Highlight the icon
4. Ask: "Click at (x, y) to open Spotify?"
5. Click if you approve

#### Example 2: Type Text
```
You> Type "hello@example.com" in the email field
```

HALfred will:
1. Take a screenshot
2. Show confirmation: "Type 'hello@example.com'?"
3. Type the text if approved

#### Example 3: Window Management
```
You> Focus the Chrome window
```

HALfred will:
1. Query available windows
2. Find Chrome
3. Ask confirmation
4. Bring Chrome to front

### Read-Only Actions (No Confirmation)

These actions execute immediately without confirmation:

- Taking screenshots
- Getting screen information
- Querying window list
- Getting active window
- Getting pixel colors
- Waiting for images

Example:
```
You> Show me my screen resolution
```

HALfred calls `screenInfo` tool directly (no confirmation needed).

---

## Safety Features

### Multi-Layer Safety

1. **Explicit Opt-In:** Desktop automation is disabled by default (`ENABLE_AUTOMATION_MCP=false`)

2. **Action Classification:**
   - **Read-only:** screenshot, getWindows, screenInfo → No confirmation
   - **State-changing:** click, type, windowControl → Always confirm

3. **Visual Context:**
   - Screenshot shows what HALfred can see
   - Highlight shows exactly where action will occur

4. **User Confirmation:**
   - Native overlay UI (macOS)
   - Terminal fallback (all platforms)
   - Clear action description

5. **Graceful Degradation:**
   - If screenshot fails → still ask confirmation
   - If highlight fails → still show dialog
   - If overlay UI fails → fall back to terminal

### Disabling Safety (Not Recommended)

To skip confirmations (e.g., for automated scripts):

```bash
AUTOMATION_REQUIRE_APPROVAL=false
```

**Warning:** This allows HALfred to click/type without asking. Only use in controlled environments.

---

## Developer Commands

Enable with `DEV_MODE=true` in `.env`.

### Available Commands

#### `/screeninfo`
Display screen dimensions and active window info.

**Example:**
```
You> /screeninfo

Display Information:
  Screens: 1
    [0] 1920x1080 at (0, 0)
  Active Window: Terminal - 1
  Preferred Display (PREFERRED_DISPLAY_INDEX=0): 1920x1080
```

#### `/screenshot [full|active]`
Capture a screenshot.

**Examples:**
```
You> /screenshot full
[screenshot] Screenshot captured: /tmp/screenshot_20240101_120000.png

You> /screenshot active
[screenshot] Screenshot captured (active window): /tmp/screenshot_active.png
```

#### `/highlight x y w h`
Draw a highlight rectangle on screen.

**Example:**
```
You> /highlight 100 100 200 200
[highlight] Drawing highlight at (100, 100) size 200x200
[highlight] Highlight should be visible for 3 seconds
```

A red rectangle appears at coordinates (100, 100) with size 200x200 for 3 seconds.

#### `/confirm_test`
Test the feedback loop confirmation UI.

**Example:**
```
You> /confirm_test
[confirm_test] Showing test confirmation dialog...
[confirm_test] User response: Yes, it works ✅
```

#### `/demo_click`
Demonstrate the full safe_action flow with a harmless click.

**Example:**
```
You> /demo_click
[demo_click] Demonstrating safe click at (1820, 980)
[safe_action] 📸 Taking screenshot...
[safe_action] 🎯 Highlighting target at (1820, 980)...
[safe_action] ⏳ Requesting user confirmation...
[safe_action] ✓ Executing action: click...
[demo_click] ✅ Action completed successfully: Demo click in safe area
```

---

## Troubleshooting

### "bun: command not found"

**Problem:** Bun runtime not installed.

**Solution:**
```bash
curl -fsSL https://bun.sh/install | bash
# Restart terminal
bun --version
```

### "Permission denied" or "AXIsProcessTrusted" errors

**Problem:** macOS Accessibility/Screen Recording permissions not granted.

**Solution:**
1. System Preferences → Security & Privacy → Privacy
2. Grant both Accessibility and Screen Recording to your terminal app
3. **Restart terminal** (critical!)
4. Test with: `bun run node_modules/automation-mcp/index.ts --stdio`

### "MCP server 'automation' not found"

**Problem:** automation-mcp not enabled or not installed.

**Solution:**
1. Check `.env`: `ENABLE_AUTOMATION_MCP=true`
2. Install dependencies: `npm install` or `bun install`
3. Verify: `ls node_modules/automation-mcp`

### "Cannot find module automation-mcp"

**Problem:** Node.js dependencies not installed.

**Solution:**
```bash
npm install
# or
bun install
```

### Confirmation UI doesn't appear

**Problem:** feedback-loop-mcp not enabled or not working.

**Solution:**
1. Check `.env`: `ENABLE_FEEDBACK_LOOP_MCP=true`
2. Test: `npx feedback-loop-mcp`
3. If npx fails: `npm install -g feedback-loop-mcp`
4. **Fallback:** System falls back to terminal prompts automatically

### Highlight doesn't show

**Problem:** Non-critical - highlight functionality may not work on all displays.

**Solution:**
- This is non-critical; confirmation will still work
- Check macOS Screen Recording permission
- Try adjusting coordinates with `/highlight` command

### Actions fail silently

**Problem:** Tool call timeout or MCP server crash.

**Solution:**
1. Check MCP server logs (main.py prints MCP errors)
2. Increase timeout: `AUTOMATION_MCP_TIMEOUT=900` (15 minutes)
3. Test servers manually:
   ```bash
   bun run node_modules/automation-mcp/index.ts --stdio
   npx feedback-loop-mcp
   ```

---

## Platform Support

### macOS (Fully Supported)
- ✅ automation-mcp: Full support (native macOS APIs)
- ✅ feedback-loop-mcp: Native overlay windows
- ✅ Requirements: Accessibility + Screen Recording permissions
- ✅ Installation: `brew install bun` or curl installer

### Windows (Limited Support)
- ⚠️ automation-mcp: **Not supported** (uses macOS APIs)
- ✅ feedback-loop-mcp: Should work (cross-platform Node.js)
- ⚠️ Fallback: automation_safety.py will use PyAutoGUI if available
  - Install: `pip install pyautogui`
  - Limited to basic click/type operations

### Linux (Limited Support)
- ⚠️ automation-mcp: **Not supported** (uses macOS APIs)
- ✅ feedback-loop-mcp: Should work (cross-platform Node.js)
- ⚠️ Fallback: automation_safety.py will use PyAutoGUI if available
  - Install: `pip install pyautogui`
  - Requires X11 (Wayland support limited)

### Cross-Platform Summary

| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Mouse clicks | ✅ Full | ⚠️ PyAutoGUI | ⚠️ PyAutoGUI |
| Typing | ✅ Full | ⚠️ PyAutoGUI | ⚠️ PyAutoGUI |
| Screenshots | ✅ Full | ⚠️ PyAutoGUI | ⚠️ PyAutoGUI |
| Window control | ✅ Full | ❌ No | ❌ No |
| Screen highlighting | ✅ Full | ❌ No | ❌ No |
| Overlay confirmation | ✅ Native | ⚠️ Terminal | ⚠️ Terminal |
| Terminal confirmation | ✅ Fallback | ✅ Fallback | ✅ Fallback |

---

## API Reference

### `safe_action()` Tool

The main composite tool for desktop automation with safety confirmations.

#### Signature

```python
async def safe_action(
    action_type: str,
    description: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    text: Optional[str] = None,
    window_title: Optional[str] = None,
    hotkey: Optional[str] = None
) -> str
```

#### Parameters

- **action_type** (str, required): Type of action to perform
  - `"click"` - Single mouse click
  - `"double_click"` - Double click
  - `"move"` - Move mouse without clicking
  - `"type"` - Type text
  - `"hotkey"` - Press hotkey combination
  - `"window_control"` - Focus/manage window

- **description** (str, required): Human-readable description shown to user
  - Example: "Click Safari icon in dock"

- **x** (int, optional): X coordinate for click/move actions

- **y** (int, optional): Y coordinate for click/move actions

- **text** (str, optional): Text to type (required for `action_type="type"`)

- **window_title** (str, optional): Window title substring (required for `action_type="window_control"`)

- **hotkey** (str, optional): Hotkey combination (required for `action_type="hotkey"`)
  - Examples: "cmd+tab", "ctrl+c", "alt+f4"

#### Returns

- **str**: Success message or error description

#### Examples

**Click at coordinates:**
```python
result = await safe_action(
    action_type="click",
    description="Click Safari icon in dock",
    x=100,
    y=1050
)
# Returns: "✅ Action completed successfully: Click Safari icon in dock"
```

**Type text:**
```python
result = await safe_action(
    action_type="type",
    description="Type email address",
    text="user@example.com"
)
# Returns: "✅ Action completed successfully: Type email address"
```

**Hotkey:**
```python
result = await safe_action(
    action_type="hotkey",
    description="Copy selection",
    hotkey="cmd+c"
)
# Returns: "✅ Action completed successfully: Copy selection"
```

**Window control:**
```python
result = await safe_action(
    action_type="window_control",
    description="Focus Chrome window",
    window_title="Chrome"
)
# Returns: "✅ Action completed successfully: Focus Chrome window"
```

### Direct MCP Tools (Read-Only)

These tools are available directly from automation-mcp and don't require confirmation:

#### `screenshot`
Capture a screenshot.

**Parameters:**
- `full` (bool): True for full screen, false for active window

#### `screenInfo`
Get screen dimensions and information.

**Returns:** Screen resolution and display info

#### `getWindows`
List all open windows.

**Returns:** Array of window objects with titles and bounds

#### `getActiveWindow`
Get the currently active window.

**Returns:** Active window object

#### `colorAt`
Get the color of a pixel at specific coordinates.

**Parameters:**
- `x` (int): X coordinate
- `y` (int): Y coordinate

**Returns:** RGB color value

---

## Best Practices

### 1. Start with Read-Only Actions

Before using state-changing actions, test with read-only queries:

```
You> What windows are open?
You> What's my screen resolution?
You> Take a screenshot
```

### 2. Use Descriptive Action Descriptions

Good:
```python
safe_action(action_type="click", description="Click 'Submit' button in login form", ...)
```

Bad:
```python
safe_action(action_type="click", description="Click", ...)
```

### 3. Prefer Active Window Coordinates

For single-monitor setups, use active window coordinates when possible:

```python
# Better: Relative to active window
safe_action(..., x=50, y=100)

# Less reliable: Absolute screen coordinates
safe_action(..., x=1500, y=900)
```

### 4. Test in Safe Areas First

Use `/demo_click` or test in areas unlikely to trigger actions:

- Bottom-right corner of screen
- Empty desktop space
- Dock/taskbar (for positioning tests)

### 5. Monitor Logs

Watch the console output for:
- `[automation_safety]` messages
- `[mcp]` server status
- Error messages

### 6. Dual Monitor Setup

For dual monitors, set `PREFERRED_DISPLAY_INDEX`:

```bash
PREFERRED_DISPLAY_INDEX=1  # Show confirmations on secondary display
```

This keeps the confirmation UI from covering the target window.

---

## Security Considerations

### What HALfred Can Do

- ✅ Click anywhere on your screen
- ✅ Type any text (including passwords if instructed)
- ✅ Open applications
- ✅ Focus/switch windows
- ✅ Execute hotkeys (could trigger shortcuts)

### Recommendations

1. **Keep AUTOMATION_REQUIRE_APPROVAL=true** unless you have a specific automation use case

2. **Review each confirmation carefully** - the agent might misunderstand your intent

3. **Don't grant automation in sensitive environments** where accidental clicks could cause issues

4. **Use DEV_MODE commands** to test before real usage

5. **Consider creating a "safe zone"** - a dedicated desktop/space for automation testing

6. **Monitor agent behavior** - if HALfred starts making unexpected requests, deny them and investigate

---

## Advanced Usage

### Custom Automation Workflows

You can chain multiple safe_action calls in your instructions:

```
You> Open Spotify, maximize the window, and play my Discover Weekly playlist
```

HALfred will:
1. safe_action(action_type="click", description="Click Spotify icon", ...)
2. safe_action(action_type="hotkey", description="Maximize window", hotkey="cmd+ctrl+f")
3. safe_action(action_type="click", description="Click Discover Weekly", ...)

Each step requires separate confirmation (safety preserved).

### Scripting with safe_action

For automated scripts, you can import and use safe_action directly:

```python
from automation_safety import safe_action

# Automated workflow (requires AUTOMATION_REQUIRE_APPROVAL=false)
await safe_action(
    action_type="click",
    description="Automated click for screenshot tool",
    x=100, y=100
)
```

---

## Support and Contributing

### Getting Help

- **Issues:** https://github.com/andrewhuckleby/Realtime_HALfred/issues
- **Discussions:** https://github.com/andrewhuckleby/Realtime_HALfred/discussions

### Contributing

Contributions welcome! Areas for improvement:

- Windows/Linux automation support (PyAutoGUI integration)
- Better multi-monitor handling
- Visual feedback improvements
- Action templates/macros

See CONTRIBUTING.md for guidelines.

---

## Changelog

### v0.6.0 (Current)
- ✨ Added automation-mcp integration
- ✨ Added feedback-loop-mcp integration
- ✨ Implemented safe_action composite tool
- ✨ Added DEV_MODE debug commands
- ✨ Cross-platform fallback with PyAutoGUI
- 📚 Comprehensive documentation

---

## License

See LICENSE file in project root.

automation-mcp: MIT License (ashwwwin/automation-mcp)
feedback-loop-mcp: MIT License (tuandinh-org/feedback-loop-mcp)

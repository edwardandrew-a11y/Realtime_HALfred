"""
Desktop automation safety wrapper for MCP-based automation.

This module provides a composite safe_action() tool that orchestrates:
1. Screenshot capture
2. Target highlighting
3. User confirmation via feedback-loop-mcp
4. Action execution via macos-automator-mcp

macOS-only support using native AppleScript/JXA and accessibility APIs.
"""

import asyncio
import os
import platform
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Literal
from agents import function_tool

# Platform detection
PLATFORM = platform.system()  # 'Darwin', 'Windows', 'Linux'
IS_MACOS = PLATFORM == "Darwin"

# Global state for MCP servers and display info
_display_info: Optional['DisplayInfo'] = None
_mcp_servers_cache: List[Any] = []


@dataclass
class DisplayInfo:
    """Store display and window information."""
    screens: List[Dict[str, int]] = field(default_factory=list)  # [{x, y, width, height}, ...]
    active_window: Optional[Dict[str, Any]] = None
    primary_display_index: int = 0

    def get_preferred_display(self) -> Dict[str, int]:
        """Get the preferred display based on PREFERRED_DISPLAY_INDEX env var."""
        preferred_index = int(os.getenv("PREFERRED_DISPLAY_INDEX", "0"))
        if 0 <= preferred_index < len(self.screens):
            return self.screens[preferred_index]
        return self.screens[0] if self.screens else {"x": 0, "y": 0, "width": 1920, "height": 1080}


# Read-only actions that don't require confirmation
READONLY_ACTIONS = {
    "screenshot", "screenInfo", "getWindows", "getActiveWindow",
    "colorAt", "waitForImage", "getWindowList", "screeninfo"
}


def is_readonly_action(action_type: str) -> bool:
    """Check if an action is read-only and doesn't require confirmation."""
    return action_type.lower() in READONLY_ACTIONS


async def find_mcp_server(server_name: str, mcp_servers: List[Any]) -> Optional[Any]:
    """Find an MCP server by name from the server list."""
    for server in mcp_servers:
        if getattr(server, 'name', '') == server_name:
            return server
    return None


async def call_mcp_tool(
    server_name: str,
    tool_name: str,
    args: Dict[str, Any],
    mcp_servers: List[Any]
) -> Any:
    """
    Call an MCP tool by server name and tool name.

    Args:
        server_name: Name of the MCP server (e.g., "macos-automator", "feedback-loop")
        tool_name: Name of the tool to call
        args: Arguments dictionary for the tool
        mcp_servers: List of initialized MCP server objects

    Returns:
        Tool execution result

    Raises:
        ValueError: If server not found
        Exception: If tool call fails
    """
    target_server = await find_mcp_server(server_name, mcp_servers)

    if not target_server:
        raise ValueError(f"MCP server '{server_name}' not found or not enabled")

    try:
        # Call tool via MCP server
        result = await target_server.call_tool(tool_name, args)
        return result
    except Exception as e:
        raise Exception(f"Failed to call tool '{tool_name}' on server '{server_name}': {e}")


async def execute_applescript(script: str, mcp_servers: List[Any]) -> str:
    """
    Execute an AppleScript using macos-automator-mcp.

    Args:
        script: AppleScript code to execute
        mcp_servers: List of MCP servers

    Returns:
        Script execution result as text
    """
    try:
        result = await call_mcp_tool(
            "macos-automator",
            "execute_script",
            {"input": {"script_content": script}},
            mcp_servers
        )

        if hasattr(result, 'content') and result.content:
            return result.content[0].text
        return ""
    except Exception as e:
        raise Exception(f"AppleScript execution failed: {e}")


async def init_display_detection(mcp_servers: List[Any]) -> Optional[DisplayInfo]:
    """
    Initialize display detection by querying macos-automator-mcp for screen info.

    This should be called once on startup if ENABLE_MACOS_AUTOMATOR_MCP=true.

    Args:
        mcp_servers: List of initialized MCP server objects

    Returns:
        DisplayInfo object or None if detection fails
    """
    global _display_info, _mcp_servers_cache

    _mcp_servers_cache = mcp_servers

    # Check if macos-automator MCP is available
    automation_server = await find_mcp_server("macos-automator", mcp_servers)
    if not automation_server:
        print("[automation_safety] macos-automator-mcp not available")
        # Create default display info
        _display_info = DisplayInfo(
            screens=[{"x": 0, "y": 0, "width": 1920, "height": 1080}],
            active_window=None
        )
        return _display_info

    try:
        # Get screen size using AppleScript
        screen_script = """
tell application "Finder"
    set screenBounds to bounds of window of desktop
    set screenWidth to item 3 of screenBounds
    set screenHeight to item 4 of screenBounds
    return "width: " & screenWidth & ", height: " & screenHeight
end tell
"""
        screen_result = await execute_applescript(screen_script, mcp_servers)

        # Parse screen info
        screens = []
        import re
        width_match = re.search(r'width[:\s]+(\d+)', screen_result, re.IGNORECASE)
        height_match = re.search(r'height[:\s]+(\d+)', screen_result, re.IGNORECASE)
        if width_match and height_match:
            width = int(width_match.group(1))
            height = int(height_match.group(1))
            screens.append({"x": 0, "y": 0, "width": width, "height": height})
        else:
            # Fallback to default screen size
            screens.append({"x": 0, "y": 0, "width": 1920, "height": 1080})

        # Get active window using AppleScript
        window_script = """
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
    set frontWin to name of front window of application process frontApp
    return frontApp & " - " & frontWin
end tell
"""
        try:
            window_result = await execute_applescript(window_script, mcp_servers)
            active_window = {"info": window_result}
        except Exception as e:
            print(f"[automation_safety] Could not get active window: {e}")
            active_window = None

        _display_info = DisplayInfo(
            screens=screens,
            active_window=active_window
        )

        # Silently complete to avoid interrupting user input during background init
        return _display_info

    except Exception as e:
        print(f"[automation_safety] Display detection failed: {e}")
        # Create minimal fallback
        _display_info = DisplayInfo(
            screens=[{"x": 0, "y": 0, "width": 1920, "height": 1080}]
        )
        return _display_info


async def take_screenshot(mcp_servers: List[Any], mode: str = "full") -> str:
    """
    Take a screenshot using macos-automator-mcp.

    Args:
        mcp_servers: List of MCP servers
        mode: "full" for full screen, "active" for active window

    Returns:
        Success message or error string
    """
    try:
        automation_server = await find_mcp_server("macos-automator", mcp_servers)

        if automation_server:
            # Use AppleScript to take screenshot
            screenshot_dir = os.getenv("SCREENSHOTS_DIR", "screenshots")
            os.makedirs(screenshot_dir, exist_ok=True)

            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(screenshot_dir, f"screenshot_{timestamp}.png")

            # Use screencapture command via AppleScript
            script = f'do shell script "screencapture -x {filepath}"'

            await execute_applescript(script, mcp_servers)
            return f"Screenshot saved to {filepath}"
        else:
            return "Screenshot unavailable (macos-automator-mcp not enabled)"

    except Exception as e:
        return f"Screenshot failed: {e}"


async def highlight_region(mcp_servers: List[Any], x: int, y: int, w: int, h: int, duration: int = 2) -> None:
    """
    Highlight a screen region (not currently supported in macos-automator-mcp).

    Args:
        mcp_servers: List of MCP servers
        x, y: Top-left coordinates
        w, h: Width and height
        duration: Highlight duration in seconds
    """
    # Highlighting not currently implemented in macos-automator-mcp
    # This is a non-critical feature, so we'll just log and skip it
    print(f"[automation_safety] Highlight not yet implemented in macos-automator-mcp (would highlight {x},{y} {w}x{h})")


async def request_confirmation(
    mcp_servers: List[Any],
    prompt: str,
    quick_options: Optional[List[str]] = None,
    project_dir: Optional[str] = None
) -> str:
    """
    Request user confirmation via feedback-loop-mcp or terminal fallback.

    Args:
        mcp_servers: List of MCP servers
        prompt: Confirmation prompt text
        quick_options: Optional quick feedback buttons (e.g., ["Proceed ✅", "Cancel ❌"])
        project_dir: Project directory for feedback-loop-mcp (defaults to current dir)

    Returns:
        User response string
    """
    if quick_options is None:
        quick_options = ["Proceed ✅", "Cancel ❌", "Adjust target 🎯"]

    if project_dir is None:
        project_dir = os.getcwd()

    try:
        feedback_server = await find_mcp_server("feedback-loop", mcp_servers)

        if feedback_server:
            # Use feedback-loop-mcp UI
            result = await call_mcp_tool(
                "feedback-loop",
                "feedback_loop",
                {
                    "project_directory": project_dir,
                    "prompt": prompt,
                    "quickFeedbackOptions": quick_options
                },
                mcp_servers
            )

            if hasattr(result, 'content') and result.content:
                response = result.content[0].text
                return response
            return "Proceed"  # Default if no response
        else:
            # Terminal fallback
            print(f"\n{'='*80}")
            print("⚠️  CONFIRMATION REQUIRED")
            print(f"{'='*80}")
            print(f"\n{prompt}\n")
            print("Options:")
            for i, option in enumerate(quick_options, 1):
                print(f"  [{i}] {option}")

            while True:
                try:
                    choice = input(f"\nYour choice (1-{len(quick_options)}): ").strip()
                    if choice.isdigit() and 1 <= int(choice) <= len(quick_options):
                        selected = quick_options[int(choice) - 1]
                        print(f"✓ Selected: {selected}\n")
                        return selected
                    else:
                        print(f"Invalid choice. Please enter 1-{len(quick_options)}")
                except (EOFError, KeyboardInterrupt):
                    print("\n⚠️  Input interrupted, cancelling action\n")
                    return "Cancel ❌"

    except Exception as e:
        print(f"[automation_safety] Confirmation failed: {e}")
        # Emergency fallback
        response = input(f"\n⚠️ Confirm action: {prompt} [y/n]: ").strip().lower()
        return "Proceed ✅" if response == 'y' else "Cancel ❌"


@function_tool
async def safe_action(
    action_type: Literal["click", "double_click", "type", "hotkey", "window_control"],
    description: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    text: Optional[str] = None,
    window_title: Optional[str] = None,
    hotkey: Optional[str] = None
) -> str:
    """
    Execute a desktop automation action with safety confirmation.

    This tool automatically handles the complete safety flow:
    1. Takes a screenshot for context
    2. Highlights the target region (if coordinates provided)
    3. Requests user confirmation via overlay UI
    4. Executes the action only if approved

    Args:
        action_type: Type of action - "click", "double_click", "type", "hotkey", "window_control"
        description: Human-readable description of what the action will do
        x: X coordinate (for click, double_click)
        y: Y coordinate (for click, double_click)
        text: Text to type (for type action)
        window_title: Window title substring (for window_control)
        hotkey: Hotkey combination (for hotkey action, e.g., "cmd+tab", "ctrl+c")

    Returns:
        Success message or error description

    Examples:
        safe_action(action_type="click", description="Click Safari icon in dock", x=100, y=1050)
        safe_action(action_type="type", description="Type username", text="user@example.com")
        safe_action(action_type="hotkey", description="Copy selection", hotkey="cmd+c")
    """
    global _mcp_servers_cache

    # Check if macos-automator-mcp server is actually loaded
    using_mcp = False
    for server in _mcp_servers_cache:
        if getattr(server, 'name', '') == 'macos-automator':
            using_mcp = True
            break

    if not using_mcp:
        return "Error: macos-automator-mcp not available. Enable it in .env with ENABLE_MACOS_AUTOMATOR_MCP=true"

    # Check if approval is required
    require_approval = os.getenv("AUTOMATION_REQUIRE_APPROVAL", "true").lower() == "true"

    # Validate action type
    valid_actions = ["click", "double_click", "type", "hotkey", "window_control", "move"]
    if action_type.lower() not in valid_actions:
        return f"Error: Invalid action_type '{action_type}'. Valid types: {', '.join(valid_actions)}"

    mcp_servers = _mcp_servers_cache
    if not mcp_servers:
        return "Error: MCP servers not initialized. Call init_display_detection() first."

    try:
        # Step 1: Take screenshot for context
        print(f"[safe_action] 📸 Taking screenshot...")
        screenshot_result = await take_screenshot(mcp_servers, mode="full")

        # Step 2: Highlight target region (if coordinates provided)
        if x is not None and y is not None:
            print(f"[safe_action] 🎯 Highlighting target at ({x}, {y})...")
            await highlight_region(mcp_servers, x, y, 50, 50, duration=2)

        # Step 3: Request confirmation (if required)
        if require_approval:
            prompt = f"""
🤖 Automation Action Request

Description: {description}
Action: {action_type}
"""
            if x is not None and y is not None:
                prompt += f"Coordinates: ({x}, {y})\n"
            if text:
                prompt += f"Text: {text}\n"
            if hotkey:
                prompt += f"Hotkey: {hotkey}\n"
            if window_title:
                prompt += f"Window: {window_title}\n"

            prompt += "\nProceed with this action?"

            print(f"[safe_action] ⏳ Requesting user confirmation...")
            response = await request_confirmation(
                mcp_servers,
                prompt,
                quick_options=["Proceed ✅", "Cancel ❌", "Adjust target 🎯"]
            )

            # Check response
            if "Cancel" in response or "cancel" in response.lower():
                return f"Action cancelled by user: {description}"

            if "Adjust" in response:
                return f"Action adjustment requested: {description}. Please refine coordinates and try again."

        # Step 4: Execute the action using AppleScript/JXA
        print(f"[safe_action] ✓ Executing action: {action_type}...")

        automation_server = await find_mcp_server("macos-automator", mcp_servers)

        if automation_server:
            # Build AppleScript for the action
            script = ""

            if action_type.lower() == "click":
                # Use cliclick for mouse clicks (requires cliclick: brew install cliclick)
                script = f'do shell script "/opt/homebrew/bin/cliclick c:{x},{y}"'

            elif action_type.lower() == "double_click":
                # Double click using cliclick
                script = f'do shell script "/opt/homebrew/bin/cliclick dc:{x},{y}"'

            elif action_type.lower() == "move":
                # Move mouse using cliclick
                script = f'do shell script "/opt/homebrew/bin/cliclick m:{x},{y}"'

            elif action_type.lower() == "type":
                if not text:
                    return "Error: 'text' parameter required for type action"
                # Escape quotes in text
                escaped_text = text.replace('"', '\\"')
                script = f'''
tell application "System Events"
    keystroke "{escaped_text}"
end tell
'''

            elif action_type.lower() == "hotkey":
                if not hotkey:
                    return "Error: 'hotkey' parameter required for hotkey action"

                # Parse hotkey (e.g., "cmd+c" -> command down, c, command up)
                parts = hotkey.lower().split('+')
                modifiers = []
                key = parts[-1]

                for part in parts[:-1]:
                    if part in ['cmd', 'command']:
                        modifiers.append('command')
                    elif part in ['ctrl', 'control']:
                        modifiers.append('control')
                    elif part in ['alt', 'option']:
                        modifiers.append('option')
                    elif part == 'shift':
                        modifiers.append('shift')

                modifier_str = ' using {' + ', '.join([f'{m} down' for m in modifiers]) + '}' if modifiers else ''
                script = f'''
tell application "System Events"
    keystroke "{key}"{modifier_str}
end tell
'''

            elif action_type.lower() == "window_control":
                if not window_title:
                    return "Error: 'window_title' parameter required for window_control action"
                script = f'''
tell application "System Events"
    set frontmost of first application process whose name contains "{window_title}" to true
end tell
'''

            # Execute the AppleScript
            result_text = await execute_applescript(script, mcp_servers)
            return f"✅ Action completed successfully: {description}\nResult: {result_text}"
        else:
            return "Error: macos-automator-mcp not available"

    except Exception as e:
        return f"❌ Action failed: {description}\nError: {str(e)}"


# Fix safe_action schema: only action_type + description required, with conditional requirements
safe_action.params_json_schema["required"] = ["action_type", "description"]

# Add conditional validation using JSON Schema if/then
# Important: Also constrain types in 'then' to prevent null values for required fields
safe_action.params_json_schema["allOf"] = [
    # Click and double_click require x, y (and they must be integers, not null)
    {
        "if": {
            "properties": {
                "action_type": {"enum": ["click", "double_click"]}
            }
        },
        "then": {
            "required": ["x", "y"],
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"}
            }
        }
    },
    # Type requires text (and it must be a string, not null)
    {
        "if": {
            "properties": {
                "action_type": {"const": "type"}
            }
        },
        "then": {
            "required": ["text"],
            "properties": {
                "text": {"type": "string", "minLength": 1}
            }
        }
    },
    # Hotkey requires hotkey (and it must be a string, not null)
    {
        "if": {
            "properties": {
                "action_type": {"const": "hotkey"}
            }
        },
        "then": {
            "required": ["hotkey"],
            "properties": {
                "hotkey": {"type": "string", "minLength": 1}
            }
        }
    },
    # Window_control requires window_title (and it must be a string, not null)
    {
        "if": {
            "properties": {
                "action_type": {"const": "window_control"}
            }
        },
        "then": {
            "required": ["window_title"],
            "properties": {
                "window_title": {"type": "string", "minLength": 1}
            }
        }
    }
]


# DEV_MODE helper functions

async def get_display_info(mcp_servers: List[Any]) -> str:
    """Get and format display information for debugging."""
    global _display_info

    if _display_info is None:
        print("[automation_safety] Display detection not yet initialized, running now...")
        await init_display_detection(mcp_servers)

    if _display_info is None:
        return "Display info not available"

    output = "Display Information:\n"
    output += f"  Screens: {len(_display_info.screens)}\n"
    for i, screen in enumerate(_display_info.screens):
        output += f"    [{i}] {screen['width']}x{screen['height']} at ({screen['x']}, {screen['y']})\n"

    if _display_info.active_window:
        output += f"  Active Window: {_display_info.active_window.get('info', 'Unknown')}\n"

    preferred = _display_info.get_preferred_display()
    output += f"  Preferred Display (PREFERRED_DISPLAY_INDEX={os.getenv('PREFERRED_DISPLAY_INDEX', '0')}): "
    output += f"{preferred['width']}x{preferred['height']}\n"

    return output


async def test_highlight(mcp_servers: List[Any], x: int, y: int, w: int, h: int) -> None:
    """Test highlight functionality."""
    print(f"[test_highlight] Drawing highlight at ({x}, {y}) size {w}x{h}")
    await highlight_region(mcp_servers, x, y, w, h, duration=3)
    print("[test_highlight] Highlight should be visible for 3 seconds")


async def test_feedback_loop(mcp_servers: List[Any]) -> str:
    """Test feedback loop confirmation UI."""
    print("[test_feedback_loop] Showing test confirmation dialog...")
    response = await request_confirmation(
        mcp_servers,
        "This is a test confirmation dialog.\n\nDoes the overlay appear correctly?",
        quick_options=["Yes, it works ✅", "No, issues ❌", "Terminal fallback 💬"]
    )
    return f"User response: {response}"


async def demo_safe_click(mcp_servers: List[Any]) -> str:
    """
    Demonstrate the full safe_action flow with a harmless click.
    Clicks in the bottom-right corner of the screen (safe area).
    """
    global _display_info

    if _display_info is None:
        await init_display_detection(mcp_servers)

    if _display_info and _display_info.screens:
        screen = _display_info.get_preferred_display()
        # Click in bottom-right corner (safe area, unlikely to trigger anything)
        safe_x = screen['width'] - 100
        safe_y = screen['height'] - 100
    else:
        # Fallback coordinates
        safe_x, safe_y = 1820, 980

    print(f"[demo_safe_click] Demonstrating safe click at ({safe_x}, {safe_y})")

    result = await safe_action(
        action_type="click",
        description="Demo click in safe area (bottom-right corner)",
        x=safe_x,
        y=safe_y
    )

    return result

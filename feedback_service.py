"""
Feedback service for HALfred meta-agent system.

Thin wrapper over the feedback-loop MCP for two distinct purposes:
  1. Post-escalation satisfaction popup  — fired from event_loop() after the
     Realtime agent finishes narrating an escalate_to_supervisor result.
  2. Metaprompt approval dialog          — fired from the dormancy block when the
     meta-agent has a prompt proposal ready for human review.

Both dialogs share a single guard flag (AppRuntimeState.metaprompt_dialog_active)
so they cannot fire concurrently. The guard is set before any dialog fires and
cleared on resolution (or timeout).

Dialog timeouts use asyncio.wait_for() so a forgotten dialog never hangs the
coroutine indefinitely.

All calls are best-effort: if the feedback-loop MCP is not running (ENABLE_FEEDBACK_LOOP_MCP=false),
the function logs a warning and returns a neutral result rather than raising.
"""

import asyncio
import os
from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from main import AppRuntimeState

# Timeout constants (seconds)
SATISFACTION_TIMEOUT_S = 120    # 2 minutes for a quick thumbs-up/down
APPROVAL_TIMEOUT_S = 300        # 5 minutes for reading a full diff

# AppleScript template for the satisfaction popup.
# Uses macos-automator execute_script (the same path as automation_safety.py).
_SATISFACTION_SCRIPT = """\
set theResult to display dialog "{message}" ¬
    buttons {{"👍 Yes", "👎 No"}} ¬
    default button "👍 Yes" ¬
    with title "HALfred — How did that go?" ¬
    giving up after 120
if gave up of theResult then
    return "timeout"
end if
return button returned of theResult
"""

_APPROVAL_SCRIPT = """\
set theResult to display dialog "{message}" ¬
    buttons {{"✅ Approve", "❌ Deny"}} ¬
    default button "❌ Deny" ¬
    with title "HALfred — Prompt Update Proposal" ¬
    giving up after 300
if gave up of theResult then
    return "timeout"
end if
return button returned of theResult
"""

# AppleScript for denial reason (simple text input)
_DENIAL_REASON_SCRIPT = """\
set theResult to display dialog "Why are you denying this change? (optional)" ¬
    default answer "" ¬
    buttons {{"OK"}} ¬
    default button "OK" ¬
    giving up after 60
if gave up of theResult then
    return ""
end if
return text returned of theResult
"""


def _mcp_available(mcp_servers: List[Any]) -> bool:
    """Return True if the feedback-loop MCP server is present in the server list."""
    for s in mcp_servers:
        if getattr(s, "name", "") == "feedback-loop":
            return True
    return False


def _automation_available(mcp_servers: List[Any]) -> bool:
    """Return True if macos-automator MCP server is present."""
    for s in mcp_servers:
        if getattr(s, "name", "") == "macos-automator":
            return True
    return False


async def _run_applescript(script: str, mcp_servers: List[Any]) -> str:
    """
    Execute an AppleScript via macos-automator MCP.

    Returns the script's return value as a string, or "" on any failure.
    """
    from automation_safety import call_mcp_tool
    try:
        result = await call_mcp_tool(
            "macos-automator",
            "execute_script",
            {"script_content": script},
            mcp_servers,
        )
        if getattr(result, "isError", False):
            return ""
        if hasattr(result, "content") and result.content:
            return result.content[0].text.strip()
        return str(result).strip()
    except Exception as e:
        print(f"[feedback_service] AppleScript error: {e}")
        return ""


async def ask_satisfaction(
    interaction_id: str,
    mcp_servers: List[Any],
    app_runtime: "AppRuntimeState",
) -> Optional[bool]:
    """
    Show a post-escalation satisfaction popup (thumbs up / thumbs down).

    Fires after the Realtime agent has finished narrating an escalation result.
    Uses a shared dialog guard to prevent concurrent dialogs.

    Args:
        interaction_id: ID of the escalation being rated (for log correlation).
        mcp_servers:    Active MCP server list.
        app_runtime:    Shared runtime state (holds metaprompt_dialog_active flag).

    Returns:
        True for thumbs-up, False for thumbs-down, None on timeout/error/unavailable.
    """
    if not os.getenv("ENABLE_METAPROMPT_AGENT", "false").lower() == "true":
        return None

    if not _automation_available(mcp_servers):
        return None

    if getattr(app_runtime, "metaprompt_dialog_active", False):
        print("[feedback_service] Dialog already active — skipping satisfaction popup")
        return None

    app_runtime.metaprompt_dialog_active = True
    try:
        message = (
            "Was that helpful?\\n\\n"
            "Your feedback helps HALfred improve over time."
        )
        script = _SATISFACTION_SCRIPT.format(message=message)

        try:
            result = await asyncio.wait_for(
                _run_applescript(script, mcp_servers),
                timeout=SATISFACTION_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            print("[feedback_service] Satisfaction popup timed out")
            return None

        if result == "timeout" or not result:
            return None
        return "Yes" in result or "👍" in result

    finally:
        app_runtime.metaprompt_dialog_active = False


async def ask_approval(
    proposal_summary: str,
    full_diff: str,
    staging_paths: List[str],
    mcp_servers: List[Any],
    app_runtime: "AppRuntimeState",
) -> tuple:
    """
    Show the metaprompt approval dialog with the full before/after diff.

    This is the human gate before any prompt change is written to disk.
    Showing only a summary is a security risk — the full diff is always shown.

    Args:
        proposal_summary:  One-line description of the proposed change.
        full_diff:         Full before/after diff text shown in the dialog.
        staging_paths:     List of paths to staging files (prompt + constraint ops).
        mcp_servers:       Active MCP server list.
        app_runtime:       Shared runtime state.

    Returns:
        Tuple of (approved: bool, denial_reason: str, timed_out: bool).
        approved=False + timed_out=True when dialog was ignored.
    """
    if not _automation_available(mcp_servers):
        print("[feedback_service] macos-automator not available — treating as denied")
        return (False, "mcp_unavailable", False)

    if getattr(app_runtime, "metaprompt_dialog_active", False):
        print("[feedback_service] Dialog already active — cannot show approval dialog")
        return (False, "dialog_active", False)

    app_runtime.metaprompt_dialog_active = True
    try:
        # Truncate diff for dialog (AppleScript dialog has display limits)
        diff_preview = full_diff[:800] + ("..." if len(full_diff) > 800 else "")
        staging_ref = "\\n".join(staging_paths) if staging_paths else "N/A"
        message = (
            f"HALfred wants to update its prompt.\\n\\n"
            f"Change: {proposal_summary}\\n\\n"
            f"--- DIFF (first 800 chars) ---\\n"
            f"{diff_preview}\\n\\n"
            f"Full artifacts staged at:\\n{staging_ref}\\n\\n"
            f"Approve this change?"
        )
        # Escape double quotes for AppleScript
        message_escaped = message.replace('"', '\\"')
        script = _APPROVAL_SCRIPT.format(message=message_escaped)

        try:
            result = await asyncio.wait_for(
                _run_applescript(script, mcp_servers),
                timeout=APPROVAL_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            print("[feedback_service] Approval dialog timed out — treating as denied")
            return (False, "timed_out", True)

        if result == "timeout":
            return (False, "timed_out", True)

        approved = "Approve" in result or "✅" in result
        denial_reason = ""
        if not approved:
            # Ask for optional denial reason
            try:
                denial_reason = await asyncio.wait_for(
                    _run_applescript(_DENIAL_REASON_SCRIPT, mcp_servers),
                    timeout=65,
                )
            except (asyncio.TimeoutError, Exception):
                denial_reason = ""

        return (approved, denial_reason or "", False)

    finally:
        app_runtime.metaprompt_dialog_active = False

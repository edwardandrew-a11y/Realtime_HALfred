"""
Filesystem safety module for gating risky MCP filesystem operations.

This module implements confirmation prompts for:
- Write operations: Shows diff before confirming
- Delete/Move operations: Always requires explicit confirmation
"""

import os
import difflib
import json
from typing import Dict, Any, Optional, Tuple
from pathlib import Path


# Define risky filesystem operations
WRITE_OPERATIONS = {
    "write_file",
    "edit_file",
    "create_file",
}

DELETE_MOVE_OPERATIONS = {
    "delete_file",
    "move_file",
    "remove_file",
}

ALL_RISKY_OPERATIONS = WRITE_OPERATIONS | DELETE_MOVE_OPERATIONS


def is_risky_operation(tool_name: str) -> bool:
    """Check if a tool operation is risky and requires confirmation."""
    return tool_name in ALL_RISKY_OPERATIONS


def generate_diff(file_path: str, new_content: str) -> Optional[str]:
    """
    Generate a unified diff between existing file content and new content.

    Args:
        file_path: Path to the file being modified
        new_content: New content that will be written

    Returns:
        Unified diff string, or None if file doesn't exist
    """
    path = Path(file_path)

    if not path.exists():
        return f"[NEW FILE] {file_path}\n{new_content[:500]}{'...' if len(new_content) > 500 else ''}"

    try:
        with open(path, 'r', encoding='utf-8') as f:
            old_content = f.read()
    except Exception as e:
        return f"[ERROR reading existing file: {e}]"

    # Generate unified diff
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"{file_path} (current)",
        tofile=f"{file_path} (proposed)",
        lineterm='\n'
    )

    diff_text = ''.join(diff)

    # Truncate very long diffs
    if len(diff_text) > 2000:
        lines = diff_text.split('\n')
        truncated = '\n'.join(lines[:50])
        return f"{truncated}\n\n... [diff truncated, {len(lines)} total lines] ..."

    return diff_text if diff_text else "[No changes detected]"


def format_operation_details(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Format operation details for display in confirmation prompt.

    Args:
        tool_name: Name of the tool being invoked
        arguments: Tool arguments

    Returns:
        Formatted string describing the operation
    """
    details = [f"\nOperation: {tool_name}"]

    # Extract key arguments
    if "path" in arguments:
        details.append(f"Path: {arguments['path']}")
    elif "file_path" in arguments:
        details.append(f"Path: {arguments['file_path']}")
    elif "source" in arguments:
        details.append(f"Source: {arguments['source']}")
        if "destination" in arguments:
            details.append(f"Destination: {arguments['destination']}")

    # Show content preview for writes
    if tool_name in WRITE_OPERATIONS:
        content_key = next((k for k in ["content", "data", "text"] if k in arguments), None)
        if content_key:
            content = str(arguments[content_key])
            preview = content[:200] + "..." if len(content) > 200 else content
            details.append(f"Content preview: {preview}")

    return "\n".join(details)


async def prompt_confirmation(
    tool_name: str,
    arguments: Dict[str, Any],
    show_diff: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Prompt user for confirmation of a risky filesystem operation.

    Args:
        tool_name: Name of the tool being invoked
        arguments: Tool arguments dict
        show_diff: If True, generate and show diff for write operations

    Returns:
        Tuple of (approved: bool, reason: Optional[str])
    """
    print("\n" + "="*80)
    print("⚠️  FILESYSTEM OPERATION REQUIRES CONFIRMATION")
    print("="*80)

    # Show operation details
    details = format_operation_details(tool_name, arguments)
    print(details)

    # Show diff for write operations
    if show_diff and tool_name in WRITE_OPERATIONS:
        print("\n" + "-"*80)
        print("PROPOSED CHANGES:")
        print("-"*80)

        # Try to extract file path and content
        file_path = arguments.get("path") or arguments.get("file_path")
        content = arguments.get("content") or arguments.get("data") or arguments.get("text")

        if file_path and content:
            diff = generate_diff(str(file_path), str(content))
            if diff:
                print(diff)
        else:
            print("[Could not generate diff - missing path or content]")

        print("-"*80)

    # Prompt for confirmation
    print("\n❓ Approve this operation?")
    print("   [y] Yes, proceed")
    print("   [n] No, block this operation")
    print("   [a] Abort - stop the agent entirely")

    while True:
        try:
            # Use input() for synchronous terminal input
            response = input("\nYour choice (y/n/a): ").strip().lower()

            if response in ['y', 'yes']:
                print("✓ Operation approved\n")
                return True, None
            elif response in ['n', 'no']:
                print("✗ Operation blocked\n")
                return False, "User denied filesystem operation"
            elif response in ['a', 'abort']:
                print("⚠️  Agent execution aborted by user\n")
                return False, "User aborted agent execution"
            else:
                print("Invalid choice. Please enter 'y', 'n', or 'a'")
        except (EOFError, KeyboardInterrupt):
            print("\n⚠️  Input interrupted, blocking operation\n")
            return False, "User interrupted confirmation prompt"


async def check_filesystem_operation(
    tool_name: str,
    arguments: Dict[str, Any],
    require_approval: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    Main entry point for checking if a filesystem operation should proceed.

    Args:
        tool_name: Name of the tool being invoked
        arguments: Tool arguments dict
        require_approval: If False, always approve (useful for testing)

    Returns:
        Tuple of (approved: bool, denial_reason: Optional[str])
    """
    # If approval not required, always allow
    if not require_approval:
        return True, None

    # Check if operation is risky
    if not is_risky_operation(tool_name):
        return True, None

    # Write operations: show diff then confirm
    if tool_name in WRITE_OPERATIONS:
        return await prompt_confirmation(tool_name, arguments, show_diff=True)

    # Delete/move operations: always confirm
    elif tool_name in DELETE_MOVE_OPERATIONS:
        return await prompt_confirmation(tool_name, arguments, show_diff=False)

    # Default: allow non-risky operations
    return True, None

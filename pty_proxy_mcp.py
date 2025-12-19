#!/usr/bin/env python3
"""
PTY Proxy MCP Server

This MCP server provides safe terminal command execution with user confirmation
for risky operations. Safe commands (pwd, ls, cat, etc.) are auto-approved,
while risky commands require explicit user permission.

Usage:
    python pty_proxy_mcp.py

The server communicates via stdio using the MCP protocol.
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from pty_command_safety import (
    check_pty_command,
    RiskLevel,
)


# Initialize MCP server
app = Server("pty-proxy")


# Define PTY tools
PTY_TOOLS = [
    Tool(
        name="pty_bash_execute",
        description=(
            "Execute a shell command in a bash environment. "
            "Safe commands (pwd, ls, cat, grep, find, etc.) are executed immediately. "
            "Risky commands (mkdir, rm, chmod, network operations) require user confirmation. "
            "Use this tool to inspect files, navigate directories, and gather system information."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (will be run in bash)"
                },
                "working_directory": {
                    "type": "string",
                    "description": "Optional working directory for command execution (defaults to current directory)"
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Maximum execution time in seconds (default: 30)",
                    "default": 30
                }
            },
            "required": ["command"]
        }
    )
]


async def execute_command(
    command: str,
    working_dir: str = None,
    timeout_seconds: float = 30
) -> dict:
    """
    Execute a shell command via subprocess.

    Args:
        command: Command string to execute
        working_dir: Optional working directory
        timeout_seconds: Command timeout

    Returns:
        Dict with stdout, stderr, exit_code, and success flag
    """
    try:
        # Use the current working directory if none specified
        cwd = working_dir if working_dir and os.path.isdir(working_dir) else None

        # Determine shell executable based on platform
        system = platform.system()
        if system == "Windows":
            # Windows: use cmd.exe
            shell_executable = None  # Use default shell on Windows
            shell = True
        else:
            # Unix/Linux/macOS: use bash
            shell_executable = "/bin/bash"
            shell = True

        # Execute command in appropriate shell
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            shell=shell,
            executable=shell_executable
        )

        # Wait for completion with timeout
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            # Kill the process if it times out
            process.kill()
            await process.wait()
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout_seconds} seconds",
                "exit_code": -1,
                "success": False,
                "error": "timeout"
            }

        # Decode output
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')
        exit_code = process.returncode

        return {
            "stdout": stdout_str,
            "stderr": stderr_str,
            "exit_code": exit_code,
            "success": exit_code == 0
        }

    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "success": False,
            "error": "execution_failed"
        }


def format_result(result: dict, command: str) -> str:
    """
    Format command execution result for display.

    Args:
        result: Execution result dict
        command: Original command string

    Returns:
        Formatted string
    """
    lines = []

    # Show command
    lines.append(f"Command: {command}")
    lines.append(f"Exit code: {result['exit_code']}")

    # Show stdout if present
    if result['stdout']:
        lines.append("\n--- Output ---")
        lines.append(result['stdout'].rstrip())

    # Show stderr if present
    if result['stderr']:
        lines.append("\n--- Errors/Warnings ---")
        lines.append(result['stderr'].rstrip())

    # Show summary
    if result['success']:
        lines.append("\n✓ Command completed successfully")
    else:
        error_type = result.get('error', 'non_zero_exit')
        if error_type == 'timeout':
            lines.append("\n✗ Command timed out")
        else:
            lines.append(f"\n✗ Command failed with exit code {result['exit_code']}")

    return "\n".join(lines)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available PTY tools."""
    return PTY_TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """
    Handle tool calls with safety checks for risky commands.
    """
    if name != "pty_bash_execute":
        error_msg = f"Unknown tool: {name}"
        return [TextContent(type="text", text=error_msg)]

    # Extract arguments
    command = arguments.get("command", "").strip()
    working_dir = arguments.get("working_directory")
    timeout_seconds = arguments.get("timeout_seconds", 30)

    if not command:
        return [TextContent(type="text", text="Error: No command provided")]

    # Check if approval is required
    require_approval = os.getenv("PTY_REQUIRE_APPROVAL", "true").lower() == "true"

    if require_approval:
        # Check command safety
        approved, denial_reason = await check_pty_command(
            tool_name=name,
            arguments={"command": command}
        )

        if not approved:
            error_msg = f"Command blocked: {denial_reason or 'User denied execution'}"
            return [TextContent(type="text", text=error_msg)]

    # Execute approved command
    try:
        result = await execute_command(
            command=command,
            working_dir=working_dir,
            timeout_seconds=float(timeout_seconds)
        )

        formatted_result = format_result(result, command)
        return [TextContent(type="text", text=formatted_result)]

    except Exception as e:
        error_msg = f"Error executing command: {str(e)}"
        return [TextContent(type="text", text=error_msg)]


async def main():
    """Run the MCP server."""
    # Print startup message to stderr (stdout is used for MCP protocol)
    print("[pty-proxy] PTY Proxy MCP Server starting...", file=sys.stderr)
    print(f"[pty-proxy] Safety mode: {os.getenv('PTY_REQUIRE_APPROVAL', 'true')}", file=sys.stderr)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Filesystem Proxy MCP Server

This MCP server acts as a safety proxy for the filesystem MCP server.
It intercepts filesystem operations and requires user confirmation for risky operations:
- Write operations: Shows diff before confirming
- Delete/Move operations: Always requires explicit confirmation

Usage:
    python filesystem_proxy_mcp.py

The proxy connects to the actual filesystem MCP server and forwards approved operations.
"""

import asyncio
import json
import os
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from filesystem_safety import (
    check_filesystem_operation,
    is_risky_operation,
    WRITE_OPERATIONS,
    DELETE_MOVE_OPERATIONS,
)


# Initialize MCP server
app = Server("filesystem-proxy")


# Define filesystem tools (these match the @modelcontextprotocol/server-filesystem tools)
FILESYSTEM_TOOLS = [
    Tool(
        name="read_file",
        description="Read the complete contents of a file from the file system. Handles various text encodings and provides detailed error messages if the file cannot be read.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read"
                }
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="read_multiple_files",
        description="Read the contents of multiple files simultaneously. This is more efficient than reading files one by one when you need to analyze or compare multiple files.",
        inputSchema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read"
                }
            },
            "required": ["paths"]
        }
    ),
    Tool(
        name="write_file",
        description="Create a new file or completely overwrite an existing file with new content. Use with caution as it will overwrite existing files without warning.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path where to write the file"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["path", "content"]
        }
    ),
    Tool(
        name="edit_file",
        description="Make selective edits to a file by replacing specific content. Only the specified changes are applied, leaving the rest of the file unchanged.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit"
                },
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "oldText": {"type": "string"},
                            "newText": {"type": "string"}
                        },
                        "required": ["oldText", "newText"]
                    },
                    "description": "List of edit operations"
                },
                "dryRun": {
                    "type": "boolean",
                    "description": "Preview changes without applying them"
                }
            },
            "required": ["path", "edits"]
        }
    ),
    Tool(
        name="create_directory",
        description="Create a new directory or ensure a directory exists. Can create multiple nested directories in one operation.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the directory to create"
                }
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="list_directory",
        description="Get a detailed listing of all files and directories in a specified path.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the directory to list"
                }
            },
            "required": ["path"]
        }
    ),
    Tool(
        name="move_file",
        description="Move or rename a file or directory from one location to another.",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source path"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination path"
                }
            },
            "required": ["source", "destination"]
        }
    ),
    Tool(
        name="search_files",
        description="Recursively search for files and directories matching a pattern.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Starting path for the search"
                },
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (glob format)"
                }
            },
            "required": ["path", "pattern"]
        }
    ),
    Tool(
        name="get_file_info",
        description="Retrieve detailed metadata about a file or directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to get information about"
                }
            },
            "required": ["path"]
        }
    ),
]


# Store subprocess for the actual filesystem MCP
filesystem_process = None


async def call_filesystem_mcp(tool_name: str, arguments: dict) -> str:
    """
    Forward a tool call to the actual filesystem MCP server.

    In a real implementation, this would communicate with the Node.js
    @modelcontextprotocol/server-filesystem via subprocess or HTTP.

    For now, we'll implement basic operations directly in Python.
    """
    from pathlib import Path
    import shutil
    import glob as glob_module

    try:
        if tool_name == "read_file":
            path = Path(arguments["path"])
            return path.read_text(encoding="utf-8")

        elif tool_name == "read_multiple_files":
            results = {}
            for path_str in arguments["paths"]:
                try:
                    results[path_str] = Path(path_str).read_text(encoding="utf-8")
                except Exception as e:
                    results[path_str] = f"Error: {e}"
            return json.dumps(results, indent=2)

        elif tool_name == "write_file":
            path = Path(arguments["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments["content"], encoding="utf-8")
            return f"Successfully wrote {len(arguments['content'])} bytes to {path}"

        elif tool_name == "edit_file":
            path = Path(arguments["path"])
            content = path.read_text(encoding="utf-8")
            dry_run = arguments.get("dryRun", False)

            for edit in arguments["edits"]:
                old_text = edit["oldText"]
                new_text = edit["newText"]
                if old_text in content:
                    content = content.replace(old_text, new_text, 1)
                else:
                    return f"Error: Could not find text to replace: {old_text[:100]}"

            if not dry_run:
                path.write_text(content, encoding="utf-8")
                return f"Successfully edited {path}"
            else:
                return f"Dry run - changes not applied:\n{content[:500]}"

        elif tool_name == "create_directory":
            path = Path(arguments["path"])
            path.mkdir(parents=True, exist_ok=True)
            return f"Successfully created directory {path}"

        elif tool_name == "list_directory":
            path = Path(arguments["path"])
            items = []
            for item in path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })
            return json.dumps(items, indent=2)

        elif tool_name == "move_file":
            source = Path(arguments["source"])
            destination = Path(arguments["destination"])
            shutil.move(str(source), str(destination))
            return f"Successfully moved {source} to {destination}"

        elif tool_name == "search_files":
            path = arguments["path"]
            pattern = arguments["pattern"]
            matches = glob_module.glob(f"{path}/**/{pattern}", recursive=True)
            return json.dumps(matches[:100], indent=2)  # Limit to 100 results

        elif tool_name == "get_file_info":
            path = Path(arguments["path"])
            stat = path.stat()
            info = {
                "name": path.name,
                "path": str(path.absolute()),
                "type": "directory" if path.is_dir() else "file",
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "created": stat.st_ctime,
            }
            return json.dumps(info, indent=2)

        else:
            return f"Error: Unknown tool {tool_name}"

    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available filesystem tools."""
    return FILESYSTEM_TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """
    Handle tool calls with safety checks for risky operations.
    """
    # Check if this is a risky operation that requires confirmation
    require_approval = os.getenv("FILESYSTEM_REQUIRE_APPROVAL", "true").lower() == "true"

    if require_approval and is_risky_operation(name):
        # Prompt for confirmation
        approved, denial_reason = await check_filesystem_operation(name, arguments)

        if not approved:
            error_msg = f"Operation blocked: {denial_reason or 'User denied confirmation'}"
            return [TextContent(type="text", text=error_msg)]

    # If approved (or not risky), execute the operation
    try:
        result = await call_filesystem_mcp(name, arguments)
        return [TextContent(type="text", text=result)]
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        return [TextContent(type="text", text=error_msg)]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())

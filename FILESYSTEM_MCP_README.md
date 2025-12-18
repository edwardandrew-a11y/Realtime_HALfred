# Filesystem MCP Integration with Safety Controls

This document describes the filesystem MCP integration for the HALfred agent, which includes built-in safety controls for risky operations.

## Overview

The filesystem MCP server provides HALfred with the ability to read, write, and manipulate files on your system. To prevent accidental data loss or unwanted modifications, all risky operations are gated behind interactive confirmation prompts.

## Architecture

```
HALfred Agent
    ↓
Filesystem Proxy MCP (filesystem_proxy_mcp.py)
    ↓
Confirmation Handler (filesystem_safety.py)
    ↓
Actual Filesystem Operations
```

### Components

1. **filesystem_proxy_mcp.py**: MCP server that intercepts all filesystem tool calls
2. **filesystem_safety.py**: Safety module that handles confirmations and diff generation
3. **MCP_SERVERS.json**: Configuration that registers the filesystem proxy

## Safety Guidelines Implementation

### 1. Gate Risky Actions in the Host ✅

All risky filesystem operations are intercepted in the **host process** (the filesystem_proxy_mcp.py server) before they reach the actual filesystem. This ensures the agent cannot bypass safety controls.

### 2. For Writes, Require "Show Diff, Then Confirm" ✅

Write operations (`write_file`, `edit_file`, `create_file`) automatically:
- Generate a unified diff showing changes between current and proposed content
- Display the diff in the terminal
- Prompt for user confirmation before proceeding
- Block the operation if denied

Example confirmation prompt for a write operation:
```
================================================================================
⚠️  FILESYSTEM OPERATION REQUIRES CONFIRMATION
================================================================================

Operation: write_file
Path: /path/to/file.txt
Content preview: This is the new content...

--------------------------------------------------------------------------------
PROPOSED CHANGES:
--------------------------------------------------------------------------------
--- /path/to/file.txt (current)
+++ /path/to/file.txt (proposed)
@@ -1,3 +1,3 @@
-Old line 1
+New line 1
 Unchanged line 2
-Old line 3
+New line 3
--------------------------------------------------------------------------------

❓ Approve this operation?
   [y] Yes, proceed
   [n] No, block this operation
   [a] Abort - stop the agent entirely

Your choice (y/n/a):
```

### 3. For Deletes/Moves, Require Explicit Confirm Always ✅

Delete and move operations (`delete_file`, `move_file`, `remove_file`) always:
- Display operation details (source, destination)
- Require explicit user confirmation
- Cannot be bypassed or auto-approved

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Filesystem MCP Safety Settings
# Set to 'true' to require user confirmation for risky filesystem operations (recommended)
FILESYSTEM_REQUIRE_APPROVAL=true
```

Set to `false` only for testing or if you fully trust the agent's actions.

### MCP Server Configuration

In `MCP_SERVERS.json`:

```json
{
  "name": "filesystem",
  "transport": "stdio",
  "params": {
    "command": "python",
    "args": ["/Users/andrewhuckleby/PycharmProjects/Realtime_HALfred/filesystem_proxy_mcp.py"]
  }
}
```

## Available Filesystem Tools

The filesystem MCP provides the following tools to HALfred:

### Read Operations (No Confirmation Required)
- **read_file**: Read the complete contents of a file
- **read_multiple_files**: Read multiple files simultaneously
- **list_directory**: List files and directories
- **search_files**: Recursively search for files matching a pattern
- **get_file_info**: Get file metadata (size, modified date, etc.)

### Write Operations (Requires Confirmation + Diff)
- **write_file**: Create a new file or overwrite existing file
- **edit_file**: Make selective edits to a file
- **create_directory**: Create a new directory

### Move/Delete Operations (Requires Confirmation)
- **move_file**: Move or rename a file or directory

## Usage Examples

### Example 1: Agent Writes a File

```
User: "Create a new file called test.txt with the content 'Hello World'"

[Agent invokes write_file tool]

⚠️  FILESYSTEM OPERATION REQUIRES CONFIRMATION
Operation: write_file
Path: /Users/andrewhuckleby/PycharmProjects/Realtime_HALfred/test.txt

PROPOSED CHANGES:
[NEW FILE] /Users/andrewhuckleby/PycharmProjects/Realtime_HALfred/test.txt
Hello World

❓ Approve this operation?
Your choice (y/n/a): y

✓ Operation approved
[Agent proceeds with file creation]
```

### Example 2: Agent Edits a File

```
User: "Update README.md to add a new section"

[Agent invokes edit_file tool]

⚠️  FILESYSTEM OPERATION REQUIRES CONFIRMATION
Operation: edit_file
Path: README.md

PROPOSED CHANGES:
--- README.md (current)
+++ README.md (proposed)
@@ -10,3 +10,7 @@
 ## Installation
 ...
+
+## New Section
+This is the new content added by the agent.

❓ Approve this operation?
Your choice (y/n/a): y
```

### Example 3: Agent Moves a File

```
User: "Move old_file.txt to archive/old_file.txt"

[Agent invokes move_file tool]

⚠️  FILESYSTEM OPERATION REQUIRES CONFIRMATION
Operation: move_file
Source: /path/to/old_file.txt
Destination: /path/to/archive/old_file.txt

❓ Approve this operation?
Your choice (y/n/a): n

✗ Operation blocked
[Agent receives denial message and informs user]
```

## Security Considerations

1. **Full System Access**: The filesystem MCP has access to your entire filesystem. Always review operations carefully before approving.

2. **No Path Restrictions**: Unlike some configurations that restrict access to specific directories, this implementation allows full system access but gates risky operations behind confirmations.

3. **Terminal Access Required**: Confirmations require terminal input. The agent will pause and wait for your response.

4. **Abort Option**: You can press 'a' at any confirmation prompt to abort the entire agent execution.

5. **Interrupt Handling**: Pressing Ctrl+C during a confirmation prompt will block the operation.

## Customization

### Restricting Access to Specific Directories

If you want to limit filesystem access to specific directories, you can:

1. Modify `MCP_SERVERS.json` to specify allowed paths:
```json
{
  "name": "filesystem",
  "transport": "stdio",
  "params": {
    "command": "python",
    "args": [
      "/Users/andrewhuckleby/PycharmProjects/Realtime_HALfred/filesystem_proxy_mcp.py",
      "--allowed-paths",
      "/Users/andrewhuckleby/PycharmProjects/Realtime_HALfred",
      "/Users/andrewhuckleby/Documents"
    ]
  }
}
```

2. Update `filesystem_proxy_mcp.py` to parse and enforce these restrictions

### Adding New Risky Operations

To add more operations that require confirmation, edit `filesystem_safety.py`:

```python
# Add new operation to appropriate set
WRITE_OPERATIONS.add("your_new_write_operation")
DELETE_MOVE_OPERATIONS.add("your_new_delete_operation")
```

### Disabling Confirmations Temporarily

For testing or automation, set in your `.env`:
```bash
FILESYSTEM_REQUIRE_APPROVAL=false
```

**Warning**: This removes all safety gates. Use with extreme caution.

## Troubleshooting

### "Operation blocked" Error

If the agent reports that an operation was blocked:
1. Check that you answered the confirmation prompt
2. Verify `FILESYSTEM_REQUIRE_APPROVAL=true` in your `.env`
3. Check terminal for confirmation prompts

### Confirmation Prompts Not Appearing

1. Ensure you're running in a terminal with stdin access
2. Check that `filesystem_proxy_mcp.py` is executable: `chmod +x filesystem_proxy_mcp.py`
3. Verify the MCP server is running: Check for errors in agent startup logs

### Diff Not Showing for Writes

1. Ensure the file path is correct and accessible
2. Check file encoding (UTF-8 is expected)
3. Very large files may have truncated diffs

## Testing

To test the filesystem MCP integration:

```bash
# 1. Start HALfred
python main.py

# 2. Ask HALfred to create a test file
"Create a file called test.txt with content 'Hello World'"

# 3. Verify confirmation prompt appears
# 4. Approve the operation
# 5. Ask HALfred to read the file back
"What's in test.txt?"

# 6. Test edit operation
"Update test.txt to say 'Hello HALfred'"

# 7. Test move operation
"Move test.txt to test_backup.txt"

# 8. Clean up
"Delete test_backup.txt"
```

## Implementation Details

### Diff Generation

Diffs are generated using Python's `difflib.unified_diff()`:
- Shows line-by-line changes
- Truncated to 50 lines for large files
- New files show content preview
- Read errors are displayed

### Confirmation Flow

1. Tool call intercepted by `filesystem_proxy_mcp.py`
2. `filesystem_safety.check_filesystem_operation()` called
3. For risky operations:
   - Operation details formatted
   - Diff generated (for writes)
   - Terminal prompt displayed
   - User input collected
   - Result returned to proxy
4. If approved: operation forwarded to actual filesystem
5. If denied: error message returned to agent

### Error Handling

- Invalid file paths: Error message returned to agent
- Permission errors: Error message with details
- Interrupted confirmations: Operation blocked
- Encoding errors: Graceful fallback with error message

## Future Enhancements

Potential improvements to consider:
- [ ] Web-based confirmation UI instead of terminal
- [ ] Audit log of all filesystem operations
- [ ] Configurable allowed/denied path patterns
- [ ] Auto-approve specific operations based on rules
- [ ] Rollback capability for recent operations
- [ ] Integration with git for automatic commits

## License

Part of the Realtime_HALfred project.

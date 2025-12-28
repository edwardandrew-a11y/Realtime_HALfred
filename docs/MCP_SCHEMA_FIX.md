# MCP Schema Fix for OpenAI Realtime API

## Issue

The `automation-mcp` package's `keyboard_type` tool (and potentially other tools using Zod union schemas) generates JSON schemas that are incompatible with OpenAI's Realtime API.

### Error Message
```
[raw_error] {'type': 'error', 'event_id': 'event_...', 'error': {
  'type': 'invalid_request_error',
  'code': 'invalid_function_parameters',
  'message': 'Invalid schema for function \'keyboard_type\': schema must be a JSON Schema of \'type: "object"\', got \'type: "None"\'.',
  'param': 'session.tools[34].parameters'
}}
```

### Root Cause

The `keyboard_type` tool uses a Zod union schema:
```typescript
parameters: z.union([
  z.object({ text: z.string() }),
  z.object({ keys: z.string() })
])
```

When converted to JSON Schema by fastmcp (v2.2.4), this produces:
```json
{
  "anyOf": [
    { "type": "object", "properties": { "text": {...} } },
    { "type": "object", "properties": { "keys": {...} } }
  ],
  "$schema": "http://json-schema.org/draft-07/schema#"
}
```

**But OpenAI Realtime API requires a top-level `"type": "object"`:**
```json
{
  "type": "object",
  "anyOf": [...],
  "properties": {}
}
```

## Why This Started Happening

This issue emerged due to:

1. **FastMCP Version Change**: FastMCP 2.2.4 changed how it converts Zod union schemas to JSON Schema
2. **Automation-MCP from GitHub**: Installing from `github:ashwwwin/automation-mcp` means getting the latest version, which uses union schemas
3. **OpenAI API Strictness**: The Realtime API validates schemas strictly and rejects missing `type` fields

## The Fix

**File:** `mcp_schema_fix.py`

This module patches the agents SDK's `MCPUtil.to_function_tool()` method to ensure all MCP tool schemas have the required `type: "object"` field before being sent to OpenAI.

**How it works:**
1. Intercepts MCP tool schema conversion
2. Adds missing `type: "object"` field
3. Ensures `properties` field exists (OpenAI requirement)
4. Preserves union schemas (`anyOf`/`oneOf`) while making them compatible

**Applied in:** `main.py` (imported before MCP servers initialize)

```python
# Import MCP schema fix to patch tool schemas for OpenAI Realtime API compatibility
# This fixes tools like keyboard_type that use union schemas without top-level "type": "object"
import mcp_schema_fix  # Applies monkey-patch on import
```

## Impact

### Before Fix
- ❌ `keyboard_type` tool causes session to crash on startup
- ❌ Error occurs before agent can respond
- ❌ Other union-based tools would also fail
- ❌ No workaround available (tool cannot be used)

### After Fix
- ✅ All 20 automation tools load successfully
- ✅ `keyboard_type` works with both text and key combinations
- ✅ Union schemas properly handled
- ✅ Compatible with OpenAI Realtime API requirements

## Tools Fixed

This patch specifically fixes:
- `keyboard_type` (automation-mcp) - The primary tool using union schemas

And future-proofs against:
- Any MCP tool using Zod unions
- Any tool with missing `type` field
- Schema compatibility issues between fastmcp and OpenAI

## Verification

To verify the fix is working:

```bash
python3 main.py
```

**Expected output:**
```
[mcp_schema_fix] Patched MCPUtil.to_function_tool to fix tool schemas
[mcp] Loaded MCP servers from file: mcp_servers.json
[mcp] screen-monitor: 26 tools
[mcp] pty-proxy: 1 tools
[mcp] automation: 20 tools  ← Should show 20, not fail
[mcp] feedback-loop: 1 tools
...
✅ Realtime session started (using ElevenLabs TTS).  ← No errors!
```

**If the fix is NOT applied, you'll see:**
```
[raw_error] {'type': 'error', ..., 'message': 'Invalid schema for function \'keyboard_type\'...'}
```

## Testing the keyboard_type Tool

To test that the fixed tool works:

```bash
python3 test_keyboard_type_schema.py
```

Expected output shows the schema with `anyOf` structure (which is now properly wrapped with `type: "object"` when sent to OpenAI).

## Persistence

This fix is applied at **runtime** via monkey-patching, which means:

✅ **Advantages:**
- Works immediately without modifying installed packages
- Survives `npm install` / `npm update` (unlike node_modules patches)
- Can be version-controlled and shared
- Easy to enable/disable (comment out the import)

⚠️ **Limitations:**
- Must be imported in every entry point that uses MCP tools
- Patches the agents SDK at runtime (not upstream)

## Comparison with FastMCP Patch

| Fix | FastMCP Patch | MCP Schema Fix |
|-----|---------------|----------------|
| **What** | Fixes completion handler crash | Fixes schema validation |
| **Where** | `node_modules/fastmcp/dist/FastMCP.js` | `mcp_schema_fix.py` |
| **How** | Edit compiled JS file | Python monkey-patch |
| **Persistence** | Lost on `npm install` | Version-controlled |
| **Scope** | FastMCP initialization | MCP tool schema conversion |

Both patches are necessary for full automation-mcp functionality.

## Alternative Solutions

If this patch causes issues, alternatives include:

1. **Fork automation-mcp** and change `keyboard_type` to not use union schema:
   ```typescript
   // Instead of z.union([...])
   parameters: z.object({
     text: z.string().optional(),
     keys: z.string().optional()
   })
   ```

2. **Filter out keyboard_type**:
   ```json
   {
     "name": "automation",
     "allowed_tools": ["mouseClick", "mouseMove", ...] // exclude keyboard_type
   }
   ```

3. **Report to FastMCP**: File an issue requesting top-level `type` on union schemas

## Credits

- **Root Cause**: FastMCP 2.2.4 Zod union schema conversion
- **Affected Tool**: `keyboard_type` (automation-mcp)
- **Fix Applied**: December 2024
- **Issue**: OpenAI Realtime API schema validation strictness

## Related Documentation

- [FastMCP Compatibility Patch](FASTMCP_PATCH.md) - Related fix for completion handlers
- [Automation Implementation](AUTOMATION_IMPLEMENTATION.md) - Full automation setup guide

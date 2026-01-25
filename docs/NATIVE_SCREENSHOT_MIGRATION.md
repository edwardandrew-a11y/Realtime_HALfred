# Native Screenshot Tool Migration

**Date:** 2025-12-29
**Status:** ✅ Complete

## Summary

Replaced the MCP-based `take_screenshot` tool with a native OS screenshot implementation called `screencapture` that properly integrates with the OpenAI Realtime API's image input capabilities.

---

## Problem Statement

The original `take_screenshot` tool from computer-control-mcp had critical issues:
1. **String Size Limits:** Returned base64-encoded images in tool output, hitting Realtime API size caps
2. **Token Inefficiency:** Base64 images consume massive token counts
3. **Performance Issues:** Failed with "invalid ImageContent" errors
4. **Poor API Integration:** Didn't use Realtime's native multimodal input support

---

## Solution: Two-Phase Screenshot Flow

### Phase 1: Tool Execution (Native OS Capture)
- Tool captures screenshot using native OS APIs
- Saves image to `screenshots/` directory with timestamp filename
- Returns **only metadata** (path, width, height, timestamp) as JSON
- **No base64** in tool output ✅

**Example Tool Output:**
```json
{
  "success": true,
  "path": "screenshots/screenshot_20251229_143025_123.png",
  "filename": "screenshot_20251229_143025_123.png",
  "width": 1920,
  "height": 1080,
  "timestamp": "2025-12-29T14:30:25.123"
}
```

### Phase 2: Image Upload (Separate Message)
- `handle_screenshot_image()` handler triggered on tool completion
- Reads binary image file from disk
- Encodes to base64 (required by WebSocket JSON protocol)
- Sends as `conversation.item.create` message with `input_image` type
- Agent receives image as native multimodal input

**Upload Message Format:**
```json
{
  "type": "conversation.item.create",
  "item": {
    "type": "message",
    "role": "user",
    "content": [{
      "type": "input_image",
      "image_url": "data:image/png;base64,<image_data>"
    }]
  }
}
```

---

## Key Benefits

1. **✅ Avoids String Size Limits**
   - Tool output stays small (< 500 bytes of JSON)
   - Image data never appears in tool_output

2. **✅ Efficient Token Usage**
   - Image sent as proper multimodal input
   - Model processes pixels, not base64 text

3. **✅ Fast Native Capture**
   - macOS: Native `screencapture` command (no dependencies)
   - Windows/Linux: PIL/Pillow

4. **✅ Proper API Integration**
   - Uses Realtime's native image input support
   - Agent can actually see and analyze screenshots

---

## Files Created

### `native_screenshot.py` (New)
Cross-platform screenshot tool with:
- Native OS capture (macOS `screencapture`, Windows/Linux PIL)
- Saves to configurable directory
- Returns metadata-only JSON
- Helper functions for programmatic access

---

## Files Modified

### `main.py`
- **Lines 53-60:** Import native_screenshot module
- **Lines 1219-1286:** Added `handle_screenshot_image()` function
- **Lines 1326-1327:** Hook screenshot handler to tool_end event
- **Lines 1506-1508:** Register screencapture as native tool
- **Lines 1543-1548:** Updated instructions about screenshot behavior

### `TOOLS.md`
- Updated tool counts: 45 → 44 total
- Native Python Tools: 2 → 3 (added screencapture)
- Computer-Control MCP: 15 → 13 (removed 2 screenshot tools)
- Added comprehensive screencapture documentation
- Updated Computer-Control MCP section

### `README.md`
- Added "Native Screenshot Tool" section
- Documented two-phase flow
- Explained platform support and benefits

### `.env` & `.env.example`
- Added `SCREENSHOTS_DIR=screenshots` configuration

### `requirements.txt`
- Added Pillow as optional dependency (Windows/Linux)

---

## Configuration

### Environment Variables
```bash
# Optional: customize screenshot directory
SCREENSHOTS_DIR=screenshots  # Default: screenshots/
```

### Dependencies
- **macOS:** No dependencies (uses native `screencapture`)
- **Windows/Linux:** `pip install Pillow`

---

## Platform Support

| Platform | Method | Dependencies |
|----------|--------|--------------|
| macOS | Native `screencapture` command | None |
| Windows | PIL/Pillow `ImageGrab` | Pillow |
| Linux | PIL/Pillow `ImageGrab` | Pillow |

---

## Testing

### Test Screenshot Capture
```bash
# Start HALfred
python main.py

# In session, ask:
"Take a screenshot of my screen"
```

### Expected Behavior
1. Tool captures screen → saves to `screenshots/screenshot_TIMESTAMP.png`
2. Tool returns metadata JSON (no base64)
3. Handler reads image file
4. Handler sends image to Realtime API
5. Agent receives image and can describe what's visible

### Log Output
```
[tool_start] screencapture args={}
[native_screenshot] ✓ Screenshot saved: screenshots/screenshot_20251229_143025_123.png (1920x1080)
[tool_end] screencapture output={"success":true,"path":"screenshots/...","width":1920,"height":1080}
[screenshot_image] ✓ Sent screenshot to Realtime as image input (2847392 bytes)
```

---

## Architecture Comparison

### Before (MCP-based)
```
Agent → computer-control-mcp → take_screenshot
                                     ↓
                            Returns base64 in tool_output
                                     ↓
                            ❌ String size limit exceeded
                            ❌ Massive token consumption
                            ❌ Not proper multimodal input
```

### After (Native with Two-Phase)
```
Agent → native_screenshot.screencapture
              ↓
        Saves to disk
              ↓
        Returns metadata JSON (small)
              ↓
        ✅ Tool output is clean
              ↓
        handle_screenshot_image()
              ↓
        Reads binary file
              ↓
        Sends as conversation.item.create
              ↓
        ✅ Agent receives proper image input
```

---

## Why Base64 is Still Used (But Correctly)

**Important Clarification:**

Base64 encoding is still required because:
- The OpenAI Realtime API uses WebSocket JSON protocol
- `conversation.item.create` with `input_image` requires data URL format
- Data URLs require base64 encoding: `data:image/png;base64,...`

**But this is different from the old approach:**
- ✅ Base64 is NOT in the tool output
- ✅ Base64 is created in the handler (separate concern)
- ✅ Image is sent as a proper user input message
- ✅ Agent sees it as native multimodal input, not text

---

## Migration Checklist

- [x] Created `native_screenshot.py` with cross-platform capture
- [x] Updated `main.py` to register tool and handle image upload
- [x] Removed computer-control-mcp screenshot dependencies
- [x] Updated documentation (TOOLS.md, README.md)
- [x] Added configuration (.env, requirements.txt)
- [x] Created screenshots directory
- [x] Tested on macOS

---

## Rollback Plan

If issues arise, revert by:
1. Remove native_screenshot.py
2. Revert main.py changes (lines 53-60, 1219-1286, 1326-1327, 1506-1508, 1543-1548)
3. Re-enable computer-control-mcp screenshot tools in TOOLS.md
4. Remove screenshot configuration from .env files

---

## Future Improvements

Potential enhancements:
- [ ] Add OCR integration for text extraction from screenshots
- [ ] Support screenshot annotations (draw boxes, arrows)
- [ ] Implement screenshot diff tool (compare before/after)
- [ ] Add screenshot history/management commands
- [ ] Support multi-monitor selection

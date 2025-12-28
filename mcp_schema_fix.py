# MCP Tool Schema Fix for OpenAI Realtime API
# - Normalizes MCP tool parameter schemas so they satisfy OpenAI Realtime's
#   strict requirement: top-level must be {"type": "object"} with no
#   anyOf/oneOf/allOf/enum/not at the top level.
# - Fixes automation-mcp's keyboard_type tool (and similar union schemas).

import functools
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import Tool as MCPTool
    from agents.mcp.server import MCPServer
    from agents.tool import FunctionTool


def _merge_variant_properties(variants: list[Any]) -> dict[str, Any]:
    """Merge properties from anyOf/oneOf/allOf variants into a single dict."""
    merged: dict[str, Any] = {}
    for variant in variants or []:
        if not isinstance(variant, dict):
            continue
        for name, prop_schema in (variant.get("properties") or {}).items():
            merged.setdefault(name, prop_schema)
    return merged


def fix_mcp_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize MCP tool schemas to comply with Realtime tool schema rules.

    Realtime rejects top-level anyOf/oneOf/allOf/enum/not. We collapse unions
    by merging variant properties into a single object schema. This removes the
    "exactly one of" validation but keeps the parameter surface usable.
    """
    fixed = dict(schema or {})

    # Flatten top-level combinators the Realtime API rejects
    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in fixed:
            merged_props = _merge_variant_properties(fixed.get(combinator, []))
            fixed.pop(combinator, None)
            fixed.pop("required", None)  # avoid forcing union members together
            base_props = fixed.get("properties") or {}
            fixed["properties"] = {**merged_props, **base_props}
            break  # only handle the first combinator we find

    # Strip other forbidden top-level keywords
    for forbidden in ("enum", "not"):
        fixed.pop(forbidden, None)

    # Force required object shape
    fixed["type"] = "object"
    if "properties" not in fixed:
        fixed["properties"] = {}

    return fixed


def patch_mcp_util():
    """Monkey-patch MCPUtil.to_function_tool to fix schemas before registration."""
    from agents.mcp.util import MCPUtil

    original_to_function_tool = MCPUtil.to_function_tool

    @classmethod
    def patched_to_function_tool(
        cls, tool: "MCPTool", server: "MCPServer", convert_schemas_to_strict: bool
    ) -> "FunctionTool":
        from agents.tool import FunctionTool
        from agents.logger import logger
        from agents.strict_schema import ensure_strict_json_schema

        invoke_func = functools.partial(cls.invoke_mcp_tool, server, tool)
        schema = (
            tool.inputSchema.copy()
            if hasattr(tool.inputSchema, "copy")
            else dict(tool.inputSchema)
        )
        is_strict = False

        # Apply our schema fix first
        schema = fix_mcp_tool_schema(schema)

        if convert_schemas_to_strict:
            try:
                schema = ensure_strict_json_schema(schema)
                is_strict = True
            except Exception as e:
                logger.info(f"Error converting MCP schema to strict mode: {e}")

        return FunctionTool(
            name=tool.name,
            description=tool.description or "",
            params_json_schema=schema,
            on_invoke_tool=invoke_func,
            strict_json_schema=is_strict,
        )

    MCPUtil.to_function_tool = patched_to_function_tool
    print("[mcp_schema_fix] Patched MCPUtil.to_function_tool to fix tool schemas")


def patch_realtime_tools_conversion():
    """Patch the Realtime agent's tool schema conversion for native Python tools."""
    try:
        from agents.realtime.openai_realtime import OpenAIRealtimeWebSocketModel

        original_tools_to_session = OpenAIRealtimeWebSocketModel._tools_to_session_tools

        def patched_tools_to_session(self, tools, handoffs):
            """Patched version that fixes native Python tool schemas."""
            # Get the original converted tools
            converted_tools = original_tools_to_session(self, tools, handoffs)

            # Fix each tool's parameters schema
            for tool in converted_tools:
                if hasattr(tool, 'parameters') and isinstance(tool.parameters, dict):
                    tool.parameters = fix_mcp_tool_schema(tool.parameters)

            return converted_tools

        OpenAIRealtimeWebSocketModel._tools_to_session_tools = patched_tools_to_session
        print("[mcp_schema_fix] Patched Realtime tool schema conversion for native Python tools")
    except Exception as e:
        print(f"[mcp_schema_fix] Warning: Could not patch Realtime tool conversion: {e}")


patch_mcp_util()
patch_realtime_tools_conversion()

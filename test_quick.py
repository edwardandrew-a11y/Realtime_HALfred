#!/usr/bin/env python
"""
Quick test to verify automation MCP integration.
Run this before starting main.py to ensure everything is configured correctly.
"""

import asyncio
import os
import sys
from contextlib import AsyncExitStack


async def quick_test():
    # Load environment variables first
    from dotenv import load_dotenv
    load_dotenv()

    print("\n" + "="*80)
    print("AUTOMATION MCP - QUICK CONFIGURATION TEST")
    print("="*80)

    # Check environment variables
    print("\n1. Environment Configuration:")
    automation_enabled = os.getenv("ENABLE_AUTOMATION_MCP", "false")
    feedback_enabled = os.getenv("ENABLE_FEEDBACK_LOOP_MCP", "false")
    dev_mode = os.getenv("DEV_MODE", "false")

    print(f"   ENABLE_AUTOMATION_MCP: {automation_enabled}")
    print(f"   ENABLE_FEEDBACK_LOOP_MCP: {feedback_enabled}")
    print(f"   DEV_MODE: {dev_mode}")

    if automation_enabled != "true":
        print("\n   ℹ️  automation-mcp disabled (using PyAutoGUI fallback)")
        print("      This is expected due to FastMCP compatibility issues")
    else:
        print("\n   ℹ️  automation-mcp enabled (may have issues)")

    # Check Node.js packages
    print("\n2. Node.js Packages:")
    automation_exists = os.path.exists("node_modules/automation-mcp")
    feedback_exists = os.path.exists("node_modules/feedback-loop-mcp")

    print(f"   automation-mcp: {'✓ Installed' if automation_exists else '✗ Missing'}")
    print(f"   feedback-loop-mcp: {'✓ Installed' if feedback_exists else '✗ Missing'}")

    if not automation_exists or not feedback_exists:
        print("\n   ⚠️  Run: npm install")
        return False

    # Check bun
    print("\n3. Bun Runtime:")
    bun_path = os.path.expanduser("~/.bun/bin/bun")
    bun_exists = os.path.exists(bun_path)
    print(f"   Bun at {bun_path}: {'✓ Found' if bun_exists else '✗ Missing'}")

    if not bun_exists:
        print("\n   ⚠️  Install bun: curl -fsSL https://bun.sh/install | bash")
        return False

    # Test MCP server initialization
    print("\n4. MCP Server Test:")
    try:
        from main import init_mcp_servers
        from dotenv import load_dotenv

        # Reload environment
        load_dotenv(override=True)

        async with AsyncExitStack() as stack:
            print("   Initializing MCP servers...")
            mcp_servers = await init_mcp_servers(stack)

            # Check if automation server loaded
            automation_found = False
            feedback_found = False

            for server in mcp_servers:
                name = getattr(server, 'name', '')
                if name == 'automation':
                    automation_found = True
                    print("   ✓ automation-mcp server started")

                    # Try to list tools
                    try:
                        tools = await server.list_tools()
                        tool_names = [t.name for t in tools]
                        print(f"   ✓ Tools discovered: {len(tool_names)}")
                        print(f"      Sample: {', '.join(tool_names[:5])}")
                    except Exception as e:
                        print(f"   ⚠️  Tool discovery failed: {e}")

                elif name == 'feedback-loop':
                    feedback_found = True
                    print("   ✓ feedback-loop-mcp server started")

            if not automation_found and automation_enabled == "true":
                print("   ⚠️  automation-mcp did not start (expected if disabled)")
                print("   Using PyAutoGUI fallback instead")

            if not feedback_found and feedback_enabled == "true":
                print("   ⚠️  feedback-loop-mcp did not start")
                print("   Will use terminal confirmation fallback")

    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Check automation_safety module
    print("\n5. Automation Safety Module:")
    try:
        from automation_safety import safe_action, init_display_detection
        print("   ✓ automation_safety.py imported")
        print("   ✓ safe_action tool available")
    except Exception as e:
        print(f"   ✗ Failed to import: {e}")
        return False

    print("\n" + "="*80)
    print("✅ CONFIGURATION TEST PASSED")
    print("="*80)
    print("\nNext steps:")
    print("1. Grant macOS permissions:")
    print("   - System Preferences → Security & Privacy → Privacy")
    print("   - Enable Accessibility for Terminal/iTerm")
    print("   - Enable Screen Recording for Terminal/iTerm")
    print("   - Restart terminal after granting permissions")
    print("\n2. Run Realtime HALfred:")
    print("   python main.py")
    print("\n3. Try these commands:")
    print("   /mcp              # List all MCP tools")
    print("   /screeninfo       # Display screen info (DEV_MODE)")
    print("   /screenshot       # Capture screen (DEV_MODE)")
    print("   /demo_click       # Test safe_action (DEV_MODE)")
    print("\n4. Ask HALfred:")
    print("   'Take a screenshot for me'")
    print("   'What's my screen resolution?'")
    print("\n📚 For detailed guide: docs/AUTOMATION.md")

    return True


if __name__ == "__main__":
    try:
        result = asyncio.run(quick_test())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

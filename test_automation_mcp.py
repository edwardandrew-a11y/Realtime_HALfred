"""
Smoke tests for automation-mcp and feedback-loop-mcp integration.

Run with: python test_automation_mcp.py

These tests verify:
1. MCP server startup and tool discovery
2. Display detection
3. Screenshot functionality
4. Highlight functionality
5. Confirmation UI
6. Safe action flow (with manual confirmation)
"""

import asyncio
import os
import sys
from contextlib import AsyncExitStack


async def test_mcp_server_startup():
    """Test that automation and feedback-loop MCP servers start and list tools."""
    print("\n" + "="*80)
    print("TEST 1: MCP Server Startup and Tool Discovery")
    print("="*80)

    # Temporarily enable the servers for testing
    os.environ["ENABLE_AUTOMATION_MCP"] = "true"
    os.environ["ENABLE_FEEDBACK_LOOP_MCP"] = "true"

    try:
        # Import main.py functions
        from main import init_mcp_servers

        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            # Check automation server
            automation_found = False
            automation_tools = []
            for server in mcp_servers:
                if getattr(server, 'name', '') == 'automation':
                    automation_found = True
                    tools = await server.list_tools()
                    automation_tools = [t.name for t in tools]
                    print(f"\n✓ automation-mcp server found")
                    print(f"  Tools discovered: {len(automation_tools)}")
                    print(f"  Sample tools: {', '.join(automation_tools[:10])}")
                    break

            if not automation_found:
                print("⚠ automation-mcp server not found (may need to run: npm install)")

            # Check feedback-loop server
            feedback_found = False
            feedback_tools = []
            for server in mcp_servers:
                if getattr(server, 'name', '') == 'feedback-loop':
                    feedback_found = True
                    tools = await server.list_tools()
                    feedback_tools = [t.name for t in tools]
                    print(f"\n✓ feedback-loop-mcp server found")
                    print(f"  Tools discovered: {len(feedback_tools)}")
                    print(f"  Tools: {', '.join(feedback_tools)}")
                    break

            if not feedback_found:
                print("⚠ feedback-loop-mcp server not found (may need to run: npm install)")

            # Verify expected tools
            expected_automation_tools = {'mouseClick', 'screenshot', 'screenInfo', 'getWindows'}
            expected_feedback_tools = {'feedback_loop'}

            if automation_found:
                found_tools = set(automation_tools) & expected_automation_tools
                print(f"\n  Expected automation tools found: {found_tools}")

            if feedback_found:
                found_tools = set(feedback_tools) & expected_feedback_tools
                print(f"  Expected feedback tools found: {found_tools}")

            return automation_found and feedback_found

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_display_detection():
    """Test display detection functionality."""
    print("\n" + "="*80)
    print("TEST 2: Display Detection")
    print("="*80)

    os.environ["ENABLE_AUTOMATION_MCP"] = "true"

    try:
        from main import init_mcp_servers
        from automation_safety import init_display_detection, get_display_info

        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            print("\nInitializing display detection...")
            display_info = await init_display_detection(mcp_servers)

            if display_info:
                print("✓ Display detection successful")
                info_str = await get_display_info(mcp_servers)
                print(f"\n{info_str}")
                return True
            else:
                print("⚠ Display detection returned None")
                return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_screenshot():
    """Test screenshot functionality."""
    print("\n" + "="*80)
    print("TEST 3: Screenshot")
    print("="*80)

    os.environ["ENABLE_AUTOMATION_MCP"] = "true"

    try:
        from main import init_mcp_servers
        from automation_safety import take_screenshot

        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            print("\nTaking full screenshot...")
            result = await take_screenshot(mcp_servers, mode="full")
            print(f"Result: {result}")

            if "Screenshot" in result or "captured" in result:
                print("✓ Screenshot test passed")
                return True
            else:
                print("⚠ Screenshot result unclear")
                return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_highlight():
    """Test highlight functionality."""
    print("\n" + "="*80)
    print("TEST 4: Screen Highlight")
    print("="*80)

    os.environ["ENABLE_AUTOMATION_MCP"] = "true"

    try:
        from main import init_mcp_servers
        from automation_safety import test_highlight

        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            print("\nDrawing highlight at (100, 100) size 200x200 for 2 seconds...")
            print("You should see a red rectangle on your screen.")

            await test_highlight(mcp_servers, 100, 100, 200, 200)

            response = input("\nDid you see the highlight? [y/n]: ").strip().lower()
            if response == 'y':
                print("✓ Highlight test passed")
                return True
            else:
                print("⚠ Highlight not visible")
                return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_feedback_loop():
    """Test feedback loop confirmation UI."""
    print("\n" + "="*80)
    print("TEST 5: Feedback Loop Confirmation UI")
    print("="*80)

    os.environ["ENABLE_FEEDBACK_LOOP_MCP"] = "true"

    try:
        from main import init_mcp_servers
        from automation_safety import test_feedback_loop

        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            print("\nShowing test confirmation dialog...")
            print("A confirmation window should appear (or terminal fallback).")

            result = await test_feedback_loop(mcp_servers)
            print(f"\n{result}")

            if "response" in result.lower():
                print("✓ Feedback loop test passed")
                return True
            else:
                print("⚠ Feedback loop result unclear")
                return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_safe_action_demo():
    """Test the full safe_action flow with a harmless click."""
    print("\n" + "="*80)
    print("TEST 6: Safe Action Demo (Full Flow)")
    print("="*80)

    os.environ["ENABLE_AUTOMATION_MCP"] = "true"
    os.environ["ENABLE_FEEDBACK_LOOP_MCP"] = "true"
    os.environ["AUTOMATION_REQUIRE_APPROVAL"] = "true"

    try:
        from main import init_mcp_servers
        from automation_safety import demo_safe_click, init_display_detection

        async with AsyncExitStack() as stack:
            mcp_servers = await init_mcp_servers(stack)

            # Initialize display detection
            await init_display_detection(mcp_servers)

            print("\nExecuting safe click demo...")
            print("This will:")
            print("  1. Take a screenshot")
            print("  2. Highlight the target (bottom-right corner)")
            print("  3. Ask for confirmation")
            print("  4. Execute click if approved")
            print("\nThe click location is in a safe area (bottom-right corner).")

            result = await demo_safe_click(mcp_servers)
            print(f"\nResult: {result}")

            if "completed" in result.lower() or "cancelled" in result.lower():
                print("✓ Safe action demo completed")
                return True
            else:
                print("⚠ Safe action result unclear")
                return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all smoke tests."""
    print("\n" + "#"*80)
    print("# AUTOMATION MCP INTEGRATION - SMOKE TESTS")
    print("#"*80)

    print("\nPrerequisites:")
    print("  1. Run 'npm install' or 'bun install' to install Node.js dependencies")
    print("  2. On macOS: Grant Accessibility + Screen Recording permissions")
    print("  3. Set ENABLE_AUTOMATION_MCP=true and ENABLE_FEEDBACK_LOOP_MCP=true")

    proceed = input("\nHave you completed the prerequisites? [y/n]: ").strip().lower()
    if proceed != 'y':
        print("\n⚠️  Please complete prerequisites before running tests.")
        print("   See docs/AUTOMATION.md for detailed setup instructions.")
        return

    results = {}

    # Test 1: MCP server startup
    results['server_startup'] = await test_mcp_server_startup()

    # Only run remaining tests if servers started
    if results['server_startup']:
        # Test 2: Display detection
        results['display_detection'] = await test_display_detection()

        # Test 3: Screenshot
        results['screenshot'] = await test_screenshot()

        # Test 4: Highlight (requires visual confirmation)
        results['highlight'] = await test_highlight()

        # Test 5: Feedback loop
        results['feedback_loop'] = await test_feedback_loop()

        # Test 6: Safe action demo (full flow)
        results['safe_action'] = await test_safe_action_demo()
    else:
        print("\n⚠️  Skipping remaining tests due to server startup failure")
        print("   Make sure you've run: npm install")
        print("   And that bun is installed (for automation-mcp)")

    # Print summary
    print("\n" + "#"*80)
    print("# TEST SUMMARY")
    print("#"*80)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Automation MCP integration is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the output above for details.")

    print("\nNext steps:")
    print("  1. Try the DEV_MODE commands in main.py:")
    print("     Set DEV_MODE=true in .env, then run main.py")
    print("     Available commands: /screeninfo, /screenshot, /highlight, /confirm_test, /demo_click")
    print("  2. Test safe_action tool by asking HALfred to click or type something")
    print("  3. Check docs/AUTOMATION.md for usage examples")


if __name__ == "__main__":
    # Set up environment for testing
    if not os.path.exists(".env"):
        print("⚠️  .env file not found. Creating from .env.example...")
        try:
            with open(".env.example", "r") as f:
                env_content = f.read()
            with open(".env", "w") as f:
                f.write(env_content)
            print("✓ .env file created. Please configure API keys before running tests.")
        except Exception as e:
            print(f"❌ Failed to create .env: {e}")

    # Run tests
    try:
        asyncio.run(run_all_tests())
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        sys.exit(1)

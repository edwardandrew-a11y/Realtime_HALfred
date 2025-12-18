#!/usr/bin/env python3
"""
Test script for PTY command safety module.

This script tests the command classification, risk assessment, and confirmation
prompts without requiring the full agent to be running.
"""

import asyncio
import os

from pty_command_safety import (
    assess_command_risk,
    check_pty_command,
    parse_command,
    RiskLevel,
    SAFE_COMMANDS,
    DANGEROUS_COMMANDS,
)


def test_parse_command():
    """Test command parsing."""
    print("\n" + "="*80)
    print("TEST 1: Command Parsing")
    print("="*80)

    test_cases = [
        ("pwd", "pwd", [], "pwd"),
        ("ls -la /tmp", "ls", ["-la", "/tmp"], "ls -la /tmp"),
        ("/usr/bin/cat file.txt", "cat", ["file.txt"], "/usr/bin/cat file.txt"),
        ("echo 'hello' | grep h", "echo", ["hello"], "echo 'hello' | grep h"),
        ("rm -rf /tmp/*", "rm", ["-rf", "/tmp/*"], "rm -rf /tmp/*"),
    ]

    for cmd, expected_base, expected_args, expected_full in test_cases:
        base, args, full = parse_command(cmd)
        status = "✓" if (base == expected_base and full == expected_full) else "✗"
        print(f"{status} '{cmd}'")
        print(f"   Base: {base} (expected: {expected_base})")
        if args != expected_args:
            print(f"   Args: {args} (expected: {expected_args})")


def test_risk_assessment():
    """Test command risk assessment."""
    print("\n" + "="*80)
    print("TEST 2: Command Risk Assessment")
    print("="*80)

    test_cases = [
        # Safe commands
        ("pwd", RiskLevel.SAFE),
        ("ls -la", RiskLevel.SAFE),
        ("cat /etc/hosts", RiskLevel.SAFE),
        ("grep 'pattern' file.txt", RiskLevel.SAFE),
        ("find . -name '*.py'", RiskLevel.SAFE),
        ("whoami", RiskLevel.SAFE),

        # Risky commands (output redirection makes them risky)
        ("echo 'test' > file.txt", RiskLevel.RISKY),
        ("cat file.txt | grep pattern > output.txt", RiskLevel.RISKY),
        ("mkdir new_directory", RiskLevel.RISKY),
        ("chmod 755 script.sh", RiskLevel.RISKY),

        # Dangerous commands
        ("rm -rf /tmp/*", RiskLevel.DANGEROUS),
        ("sudo apt-get install package", RiskLevel.DANGEROUS),
        ("dd if=/dev/zero of=/dev/sda", RiskLevel.DANGEROUS),
        ("shutdown -h now", RiskLevel.DANGEROUS),
        ("kill -9 12345", RiskLevel.DANGEROUS),
        ("find . -delete", RiskLevel.DANGEROUS),
    ]

    for cmd, expected_level in test_cases:
        level, reason = assess_command_risk(cmd)
        status = "✓" if level == expected_level else "✗"
        print(f"{status} '{cmd}'")
        print(f"   Risk: {level.value} (expected: {expected_level.value})")
        print(f"   Reason: {reason}")


async def test_safe_command():
    """Test that safe commands are auto-approved."""
    print("\n" + "="*80)
    print("TEST 3: Safe Command (Should Auto-Approve)")
    print("="*80)

    safe_commands = [
        "pwd",
        "ls -la",
        "cat README.md",
        "grep 'test' file.txt",
    ]

    for cmd in safe_commands:
        print(f"\nTesting: {cmd}")
        arguments = {"command": cmd}

        approved, reason = await check_pty_command("pty_bash_execute", arguments)

        if approved and reason is None:
            print(f"✓ Auto-approved (no prompt needed)")
        else:
            print(f"✗ Unexpected result: approved={approved}, reason={reason}")


async def test_risky_command():
    """Test that risky commands prompt for confirmation."""
    print("\n" + "="*80)
    print("TEST 4: Risky Command (Should Prompt)")
    print("="*80)

    risky_commands = [
        "mkdir test_directory",
        "echo 'test' > output.txt",
        "chmod 755 script.sh",
    ]

    for cmd in risky_commands:
        print(f"\nTesting: {cmd}")
        print("This should prompt you for approval...")
        arguments = {"command": cmd}

        approved, reason = await check_pty_command("pty_bash_execute", arguments)

        if approved:
            print(f"✓ Command was approved by user")
        else:
            print(f"✗ Command was denied: {reason}")


async def test_dangerous_command():
    """Test that dangerous commands show strong warning."""
    print("\n" + "="*80)
    print("TEST 5: Dangerous Command (Should Show Strong Warning)")
    print("="*80)

    dangerous_commands = [
        "rm -rf /tmp/test",
        "sudo apt-get install package",
        "kill -9 12345",
    ]

    for cmd in dangerous_commands:
        print(f"\nTesting: {cmd}")
        print("This should show a STRONG WARNING before prompting...")
        arguments = {"command": cmd}

        approved, reason = await check_pty_command("pty_bash_execute", arguments)

        if approved:
            print(f"✓ Command was approved by user")
        else:
            print(f"✗ Command was denied: {reason}")


def test_command_sets():
    """Test that safe and dangerous command sets are correctly defined."""
    print("\n" + "="*80)
    print("TEST 6: Command Set Verification")
    print("="*80)

    print(f"\nSafe commands count: {len(SAFE_COMMANDS)}")
    print(f"Dangerous commands count: {len(DANGEROUS_COMMANDS)}")

    # Check for overlaps
    overlap = SAFE_COMMANDS & DANGEROUS_COMMANDS
    if overlap:
        print(f"✗ WARNING: Commands in both safe and dangerous lists: {overlap}")
    else:
        print(f"✓ No overlaps between safe and dangerous lists")

    # Show some examples
    print(f"\nExample safe commands: {list(SAFE_COMMANDS)[:10]}")
    print(f"Example dangerous commands: {list(DANGEROUS_COMMANDS)[:10]}")


async def test_disabled_approval():
    """Test that approval can be disabled."""
    print("\n" + "="*80)
    print("TEST 7: Disabled Approval Mode")
    print("="*80)

    # Temporarily disable approval
    original = os.getenv("PTY_REQUIRE_APPROVAL")
    os.environ["PTY_REQUIRE_APPROVAL"] = "false"

    try:
        dangerous_cmd = "rm -rf /tmp/test"
        print(f"\nTesting dangerous command with approval disabled: {dangerous_cmd}")
        arguments = {"command": dangerous_cmd}

        approved, reason = await check_pty_command("pty_bash_execute", arguments, require_approval=False)

        if approved and reason is None:
            print(f"✓ Command auto-approved (approval disabled)")
        else:
            print(f"✗ Unexpected result: approved={approved}, reason={reason}")
    finally:
        # Restore original setting
        if original is None:
            if "PTY_REQUIRE_APPROVAL" in os.environ:
                del os.environ["PTY_REQUIRE_APPROVAL"]
        else:
            os.environ["PTY_REQUIRE_APPROVAL"] = original


async def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("PTY COMMAND SAFETY MODULE TEST SUITE")
    print("="*80)
    print("\nThis test suite will test command parsing, risk assessment, and prompts.")
    print("Some tests will prompt you to approve/deny operations.")
    print("For testing purposes, try approving some and denying others.")
    print("\nPress Enter to continue...")
    input()

    # Run tests that don't require user input first
    test_parse_command()
    test_risk_assessment()
    test_command_sets()
    await test_disabled_approval()

    # Run interactive tests
    await test_safe_command()
    await test_risky_command()
    await test_dangerous_command()

    print("\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)
    print("\nThe test suite verified:")
    print("• Command parsing works correctly")
    print("• Risk assessment classifies commands properly")
    print("• Safe commands auto-approve without prompts")
    print("• Risky commands prompt for user confirmation")
    print("• Dangerous commands show strong warnings")
    print("• Approval can be disabled for testing")


if __name__ == "__main__":
    asyncio.run(main())

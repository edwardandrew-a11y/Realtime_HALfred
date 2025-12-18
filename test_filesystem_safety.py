#!/usr/bin/env python3
"""
Test script for filesystem safety module.

This script tests the confirmation prompts and diff generation
without requiring the full agent to be running.
"""

import asyncio
import os
import tempfile
from pathlib import Path

from filesystem_safety import (
    check_filesystem_operation,
    generate_diff,
    is_risky_operation,
)


async def test_write_operation():
    """Test write operation with diff generation."""
    print("\n" + "="*80)
    print("TEST 1: Write Operation with Diff")
    print("="*80)

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Old content\nLine 2\nLine 3\n")
        temp_path = f.name

    try:
        # Simulate a write_file operation
        arguments = {
            "path": temp_path,
            "content": "New content\nLine 2\nLine 3 modified\n"
        }

        print(f"\nSimulating write_file operation on: {temp_path}")
        approved, reason = await check_filesystem_operation("write_file", arguments)

        if approved:
            print("✓ Operation was approved")
            # Actually write the file
            Path(temp_path).write_text(arguments["content"])
            print(f"✓ File updated successfully")
        else:
            print(f"✗ Operation was denied: {reason}")

    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print(f"✓ Cleaned up temporary file")


async def test_new_file_operation():
    """Test creating a new file."""
    print("\n" + "="*80)
    print("TEST 2: New File Creation")
    print("="*80)

    temp_path = tempfile.mktemp(suffix='.txt')

    try:
        arguments = {
            "path": temp_path,
            "content": "This is a brand new file\nWith multiple lines\n"
        }

        print(f"\nSimulating write_file operation for new file: {temp_path}")
        approved, reason = await check_filesystem_operation("write_file", arguments)

        if approved:
            print("✓ Operation was approved")
            Path(temp_path).write_text(arguments["content"])
            print(f"✓ File created successfully")
        else:
            print(f"✗ Operation was denied: {reason}")

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print(f"✓ Cleaned up temporary file")


async def test_move_operation():
    """Test move/delete operation."""
    print("\n" + "="*80)
    print("TEST 3: Move Operation")
    print("="*80)

    # Create source file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_source.txt') as f:
        f.write("Content to be moved")
        source_path = f.name

    dest_path = tempfile.mktemp(suffix='_dest.txt')

    try:
        arguments = {
            "source": source_path,
            "destination": dest_path
        }

        print(f"\nSimulating move_file operation")
        print(f"From: {source_path}")
        print(f"To:   {dest_path}")

        approved, reason = await check_filesystem_operation("move_file", arguments)

        if approved:
            print("✓ Operation was approved")
            import shutil
            shutil.move(source_path, dest_path)
            print(f"✓ File moved successfully")
        else:
            print(f"✗ Operation was denied: {reason}")

    finally:
        # Cleanup both files
        for path in [source_path, dest_path]:
            if os.path.exists(path):
                os.remove(path)
        print(f"✓ Cleaned up temporary files")


async def test_read_operation():
    """Test that read operations don't require confirmation."""
    print("\n" + "="*80)
    print("TEST 4: Read Operation (Should Not Require Confirmation)")
    print("="*80)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        arguments = {"path": temp_path}

        print(f"\nSimulating read_file operation on: {temp_path}")
        print("This should be approved automatically without prompting...")

        approved, reason = await check_filesystem_operation("read_file", arguments)

        if approved and reason is None:
            print("✓ Operation was auto-approved (no confirmation needed)")
        else:
            print(f"✗ Unexpected result: approved={approved}, reason={reason}")

    finally:
        os.remove(temp_path)
        print(f"✓ Cleaned up temporary file")


def test_diff_generation():
    """Test diff generation without user interaction."""
    print("\n" + "="*80)
    print("TEST 5: Diff Generation")
    print("="*80)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Line 1\nLine 2\nLine 3\n")
        temp_path = f.name

    try:
        new_content = "Line 1 modified\nLine 2\nLine 3\nLine 4 added\n"

        print(f"\nGenerating diff for: {temp_path}")
        diff = generate_diff(temp_path, new_content)

        print("\nGenerated diff:")
        print("-" * 80)
        print(diff)
        print("-" * 80)

        if diff and ("Line 1" in diff or "NEW FILE" in diff):
            print("✓ Diff generated successfully")
        else:
            print("✗ Diff generation failed or empty")

    finally:
        os.remove(temp_path)
        print(f"✓ Cleaned up temporary file")


def test_risky_operation_detection():
    """Test that risky operations are correctly identified."""
    print("\n" + "="*80)
    print("TEST 6: Risky Operation Detection")
    print("="*80)

    test_cases = [
        ("write_file", True),
        ("edit_file", True),
        ("move_file", True),
        ("delete_file", True),
        ("read_file", False),
        ("list_directory", False),
        ("get_file_info", False),
    ]

    for tool_name, expected_risky in test_cases:
        result = is_risky_operation(tool_name)
        status = "✓" if result == expected_risky else "✗"
        print(f"{status} {tool_name}: risky={result} (expected {expected_risky})")


async def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("FILESYSTEM SAFETY MODULE TEST SUITE")
    print("="*80)
    print("\nThis test suite will prompt you to approve/deny operations.")
    print("For testing purposes, try approving some and denying others.")
    print("\nPress Enter to continue...")
    input()

    # Run tests that don't require user input first
    test_risky_operation_detection()
    test_diff_generation()

    # Run interactive tests
    await test_read_operation()
    await test_write_operation()
    await test_new_file_operation()
    await test_move_operation()

    print("\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)
    print("\nIf you approved all operations, all files should have been")
    print("created, modified, and cleaned up successfully.")
    print("\nIf you denied any operations, those operations were blocked")
    print("and no changes were made to your filesystem.")


if __name__ == "__main__":
    asyncio.run(main())

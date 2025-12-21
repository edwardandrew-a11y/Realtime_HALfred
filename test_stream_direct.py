#!/usr/bin/env python3
"""
Direct test of screen streaming to isolate the issue.
Run this to see exactly what's failing.
"""

import asyncio
import sys
from pathlib import Path

# Add ScreenMonitorMCP to path
sys.path.insert(0, str(Path(__file__).parent / "ScreenMonitorMCP" / "screenmonitormcp_v2"))

async def test_stream():
    """Test screen streaming directly."""
    print("=" * 60)
    print("DIRECT STREAM TEST")
    print("=" * 60)

    try:
        from core.streaming import stream_manager
        print("✓ Imported stream_manager")

        # Create stream
        print("\n[1] Creating stream...")
        stream_id = await stream_manager.create_stream("screen", fps=10, quality=80, format="jpeg")
        print(f"✓ Stream created: {stream_id}")

        # Get initial info
        print("\n[2] Getting stream info...")
        info = await stream_manager.get_stream_info(stream_id)
        print(f"   Status: {info['status']}")
        print(f"   FPS: {info['fps']}")
        print(f"   Quality: {info['quality']}")

        # Start stream
        print("\n[3] Starting stream...")
        started = await stream_manager.start_stream_direct(stream_id, quality=80, monitor=0)
        print(f"   start_stream_direct returned: {started}")

        # Wait a moment for frames to capture
        print("\n[4] Waiting 2 seconds for frames to capture...")
        await asyncio.sleep(2)

        # Get diagnostics
        print("\n[5] Getting diagnostics...")
        diagnostics = stream_manager.get_stream_diagnostics(stream_id)
        print(f"   Status: {diagnostics['status']}")
        print(f"   Task state: {diagnostics['task_state']}")
        print(f"   Sequence: {diagnostics['sequence']}")
        print(f"   Frame counter: {diagnostics['frame_counter']}")

        print("\n[6] Debug log:")
        debug_log = diagnostics.get('debug_log', [])
        if debug_log:
            for entry in debug_log:
                print(f"   {entry}")
        else:
            print("   (no debug log entries)")

        # Final info
        print("\n[7] Final stream info...")
        final_info = await stream_manager.get_stream_info(stream_id)
        print(f"   Status: {final_info['status']}")
        print(f"   Sequence: {final_info['sequence']}")

        # Stop stream
        print("\n[8] Stopping stream...")
        stopped = await stream_manager.stop_stream(stream_id)
        print(f"   Stopped: {stopped}")

        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        frames_captured = diagnostics['sequence']
        if frames_captured > 0:
            print(f"✓ SUCCESS: Captured {frames_captured} frames")
        else:
            print(f"✗ FAILURE: No frames captured")
            print(f"  Task state: {diagnostics['task_state']}")
            print(f"  Status: {diagnostics['status']}")

    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

    return frames_captured > 0

if __name__ == "__main__":
    print("Testing screen streaming functionality...\n")
    success = asyncio.run(test_stream())
    sys.exit(0 if success else 1)

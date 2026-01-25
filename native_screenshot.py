"""
Native OS screenshot tool for HALfred.

This module provides a cross-platform screenshot tool that:
1. Uses native OS screenshot APIs (macOS screencapture, Windows/Linux fallback to PIL)
2. Saves screenshots to a local directory (screenshots/)
3. Returns only metadata (path, dimensions) - NOT base64 data
4. Allows the calling code to read the file and send it to Realtime as an image input
"""

import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from agents import function_tool


# Get screenshots directory from environment or use default
SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", "screenshots")
PLATFORM = platform.system()  # 'Darwin', 'Windows', 'Linux'


def ensure_screenshots_dir() -> Path:
    """Ensure the screenshots directory exists and return its path."""
    screenshots_path = Path(SCREENSHOTS_DIR)
    screenshots_path.mkdir(exist_ok=True)
    return screenshots_path


def get_screenshot_filename() -> str:
    """Generate a unique screenshot filename with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # millisecond precision
    return f"screenshot_{timestamp}.png"


def get_image_dimensions(image_path: Path) -> tuple[int, int]:
    """
    Get image dimensions without loading the full image.

    Returns:
        (width, height) tuple
    """
    try:
        # Try using PIL if available (more reliable)
        from PIL import Image
        with Image.open(image_path) as img:
            return img.size
    except ImportError:
        # Fallback: try using sips on macOS
        if PLATFORM == "Darwin":
            try:
                result = subprocess.run(
                    ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(image_path)],
                    capture_output=True,
                    text=True,
                    check=True
                )
                lines = result.stdout.strip().split('\n')
                width = int([l for l in lines if 'pixelWidth' in l][0].split(':')[1].strip())
                height = int([l for l in lines if 'pixelHeight' in l][0].split(':')[1].strip())
                return (width, height)
            except (subprocess.CalledProcessError, IndexError, ValueError):
                pass

        # Ultimate fallback: return default dimensions
        return (1920, 1080)


def capture_screenshot_macos(output_path: Path, region: Optional[tuple[int, int, int, int]] = None) -> bool:
    """
    Capture screenshot on macOS using native screencapture command.

    Args:
        output_path: Path where screenshot will be saved
        region: Optional (x, y, width, height) for region capture

    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = ["screencapture", "-x", "-t", "png"]  # -x disables shutter sound

        if region:
            x, y, w, h = region
            # macOS screencapture region format: -R x,y,w,h
            cmd.extend(["-R", f"{x},{y},{w},{h}"])

        cmd.append(str(output_path))

        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[native_screenshot] macOS screencapture failed: {e}")
        return False


def capture_screenshot_windows_linux(output_path: Path, region: Optional[tuple[int, int, int, int]] = None) -> bool:
    """
    Capture screenshot on Windows/Linux using PIL (Pillow).

    Args:
        output_path: Path where screenshot will be saved
        region: Optional (x, y, width, height) for region capture

    Returns:
        True if successful, False otherwise
    """
    try:
        # Try PIL/Pillow
        from PIL import ImageGrab

        if region:
            # PIL uses (left, top, right, bottom) format
            x, y, w, h = region
            bbox = (x, y, x + w, y + h)
            screenshot = ImageGrab.grab(bbox=bbox)
        else:
            screenshot = ImageGrab.grab()

        screenshot.save(output_path, "PNG")
        return True
    except ImportError:
        print("[native_screenshot] PIL/Pillow not installed. Install with: pip install Pillow")
        return False
    except Exception as e:
        print(f"[native_screenshot] PIL screenshot failed: {e}")
        return False


@function_tool
def screencapture(
    region: Optional[str] = None,
    description: Optional[str] = None
) -> str:
    """
    Capture a screenshot and save it to disk.

    This tool captures the screen using native OS APIs and saves the image to the
    screenshots/ directory. It returns ONLY metadata (file path, dimensions, timestamp)
    and does NOT include base64-encoded image data in the response.

    The calling code is responsible for reading the image file and sending it to
    the Realtime API as an image input.

    Args:
        region: Optional region to capture in format "x,y,width,height" (e.g., "0,0,1920,1080").
                If not specified, captures the full screen.
        description: Optional human-readable description of what this screenshot is for.

    Returns:
        JSON string with screenshot metadata:
        {
            "success": true,
            "path": "screenshots/screenshot_20250129_143025_123.png",
            "filename": "screenshot_20250129_143025_123.png",
            "width": 1920,
            "height": 1080,
            "timestamp": "2025-01-29T14:30:25.123",
            "description": "Optional description"
        }

    Examples:
        screencapture() - Capture full screen
        screencapture(region="100,100,800,600") - Capture specific region
        screencapture(description="Browser window showing error message")
    """
    import json

    try:
        # Ensure screenshots directory exists
        screenshots_path = ensure_screenshots_dir()

        # Generate unique filename
        filename = get_screenshot_filename()
        output_path = screenshots_path / filename

        # Parse region if provided
        region_tuple = None
        if region:
            try:
                parts = region.split(',')
                if len(parts) == 4:
                    region_tuple = tuple(int(p.strip()) for p in parts)
            except ValueError:
                return json.dumps({
                    "success": False,
                    "error": f"Invalid region format: {region}. Expected 'x,y,width,height'"
                })

        # Capture screenshot using platform-specific method
        success = False
        if PLATFORM == "Darwin":
            success = capture_screenshot_macos(output_path, region_tuple)
        else:
            success = capture_screenshot_windows_linux(output_path, region_tuple)

        if not success:
            return json.dumps({
                "success": False,
                "error": "Failed to capture screenshot. Check logs for details."
            })

        # Get image dimensions
        width, height = get_image_dimensions(output_path)

        # Build response metadata
        result = {
            "success": True,
            "path": str(output_path),
            "filename": filename,
            "width": width,
            "height": height,
            "timestamp": datetime.now().isoformat(),
        }

        if description:
            result["description"] = description

        print(f"[native_screenshot] ✓ Screenshot saved: {output_path} ({width}x{height})")

        return json.dumps(result)

    except Exception as e:
        import traceback
        error_msg = f"Screenshot failed: {str(e)}"
        print(f"[native_screenshot] ✗ {error_msg}")
        print(traceback.format_exc())
        return json.dumps({
            "success": False,
            "error": error_msg
        })


# Helper function for programmatic access (not exposed as a tool)
def take_screenshot_sync(region: Optional[tuple[int, int, int, int]] = None) -> Optional[Path]:
    """
    Synchronous helper to capture a screenshot and return the file path.

    Args:
        region: Optional (x, y, width, height) for region capture

    Returns:
        Path to the saved screenshot, or None if failed
    """
    try:
        screenshots_path = ensure_screenshots_dir()
        filename = get_screenshot_filename()
        output_path = screenshots_path / filename

        if PLATFORM == "Darwin":
            success = capture_screenshot_macos(output_path, region)
        else:
            success = capture_screenshot_windows_linux(output_path, region)

        return output_path if success else None
    except Exception as e:
        print(f"[native_screenshot] Sync screenshot failed: {e}")
        return None

"""
PTY command safety module for gating risky terminal operations.

This module implements confirmation prompts for:
- Safe commands: Auto-approved (pwd, ls, cat, etc.)
- Risky commands: Require user confirmation
- Dangerous commands: Require confirmation with strong warning
"""

import os
import re
import shlex
from enum import Enum
from typing import Dict, Any, Optional, Tuple


class RiskLevel(Enum):
    """Risk levels for command classification."""
    SAFE = "safe"
    RISKY = "risky"
    DANGEROUS = "dangerous"


# Safe commands that can be executed without confirmation
SAFE_COMMANDS = {
    # Navigation
    "pwd", "cd", "ls", "tree", "find",
    # Reading files
    "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ripgrep",
    # File information
    "stat", "file", "du", "df", "wc",
    # System information
    "whoami", "uname", "id", "hostname", "uptime", "date",
    # Help commands
    "which", "type", "man", "help", "info",
    # Other safe utilities
    "echo", "printf", "true", "false", "yes", "sleep",
}

# Dangerous commands that should always prompt with strong warning
DANGEROUS_COMMANDS = {
    # Destructive file operations
    "rm", "rmdir", "shred", "dd",
    # Disk/filesystem operations
    "mkfs", "fdisk", "parted", "format",
    # Privilege escalation
    "sudo", "su", "doas",
    # System control
    "shutdown", "reboot", "halt", "poweroff", "init",
    # Process termination
    "kill", "killall", "pkill",
    # Network/firewall
    "iptables", "ufw", "firewall-cmd",
    # Package management (can install malware)
    "apt-get", "apt", "yum", "dnf", "pacman", "brew",
}

# Patterns that indicate dangerous operations
DANGEROUS_PATTERNS = [
    r"rm\s+.*-[rf]",  # rm with -r or -f flags
    r">\s*/dev/",      # Writing to device files
    r"dd\s+.*of=",     # dd output file
    r"mkfs\.",         # Creating filesystems
    r"\|\s*sh",        # Piping to shell
    r"\|\s*bash",      # Piping to bash
    r"curl.*\|\s*sh",  # Dangerous curl | sh pattern
    r"wget.*\|\s*sh",  # Dangerous wget | sh pattern
]


def parse_command(command_string: str) -> Tuple[str, list[str], str]:
    """
    Parse a shell command string to extract the base command.

    Args:
        command_string: Full command line string

    Returns:
        Tuple of (base_command, args, full_command)
    """
    # Remove leading/trailing whitespace
    command_string = command_string.strip()

    if not command_string:
        return "", [], ""

    # Handle shell operators (pipes, redirects, command chaining)
    # For safety, treat the entire command as one unit if it contains these
    if any(op in command_string for op in ["|", "&&", "||", ";", ">", "<", ">>"]):
        # Try to extract the first command before operators
        first_part = re.split(r'[|&;<>]', command_string)[0].strip()
        try:
            parts = shlex.split(first_part)
            base_command = parts[0].split('/')[-1] if parts else ""
            return base_command, parts[1:] if len(parts) > 1 else [], command_string
        except ValueError:
            # shlex.split failed (unmatched quotes, etc.)
            return "", [], command_string

    # Simple command - parse normally
    try:
        parts = shlex.split(command_string)
        if not parts:
            return "", [], command_string

        # Extract base command (remove path if present)
        base_command = parts[0].split('/')[-1]
        args = parts[1:] if len(parts) > 1 else []

        return base_command, args, command_string
    except ValueError:
        # shlex.split failed - treat as unknown
        return "", [], command_string


def has_dangerous_pattern(command: str) -> Tuple[bool, Optional[str]]:
    """
    Check if command matches any dangerous patterns.

    Args:
        command: Full command string

    Returns:
        Tuple of (is_dangerous, reason)
    """
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return True, f"Matches dangerous pattern: {pattern}"
    return False, None


def assess_command_risk(command: str) -> Tuple[RiskLevel, str]:
    """
    Assess the risk level of a shell command.

    Args:
        command: Full command string to assess

    Returns:
        Tuple of (risk_level, reason)
    """
    if not command or not command.strip():
        return RiskLevel.RISKY, "Empty command"

    # Check for dangerous patterns first
    is_dangerous, pattern_reason = has_dangerous_pattern(command)
    if is_dangerous:
        return RiskLevel.DANGEROUS, pattern_reason

    # Parse command to get base command
    base_command, args, full_command = parse_command(command)

    if not base_command:
        return RiskLevel.RISKY, "Could not parse command"

    # Check against dangerous commands list
    if base_command in DANGEROUS_COMMANDS:
        return RiskLevel.DANGEROUS, f"'{base_command}' is a dangerous command"

    # Check against safe commands list
    if base_command in SAFE_COMMANDS:
        # Additional checks for safe commands with dangerous arguments

        # Check for output redirection (makes 'echo' etc. risky)
        if any(op in full_command for op in [">", ">>", "|"]):
            return RiskLevel.RISKY, "Command includes output redirection or pipes"

        # Check for dangerous flags
        if base_command == "find" and "-delete" in args:
            return RiskLevel.DANGEROUS, "find with -delete flag"

        if base_command == "grep" and any(flag in args for flag in ["-r", "--recursive"]) and "-delete" in full_command:
            return RiskLevel.RISKY, "grep with recursive search and potential side effects"

        # Command is safe
        return RiskLevel.SAFE, "Read-only command with no side effects"

    # Unknown command - treat as risky by default
    return RiskLevel.RISKY, f"Unknown command '{base_command}' (not in safe list)"


def format_command_details(command: str, risk_level: RiskLevel, risk_reason: str) -> str:
    """
    Format command details for display in confirmation prompt.

    Args:
        command: Command string
        risk_level: Assessed risk level
        risk_reason: Reason for risk classification

    Returns:
        Formatted string describing the command
    """
    base_command, args, _ = parse_command(command)

    details = [f"\nCommand: {command}"]

    if base_command:
        details.append(f"Base command: {base_command}")

    details.append(f"Risk level: {risk_level.value.upper()}")
    details.append(f"Reason: {risk_reason}")

    # Show working directory
    try:
        cwd = os.getcwd()
        details.append(f"Working directory: {cwd}")
    except Exception:
        pass

    return "\n".join(details)


async def prompt_command_confirmation(
    command: str,
    risk_level: RiskLevel,
    risk_reason: str
) -> Tuple[bool, Optional[str]]:
    """
    Prompt user for confirmation of a risky or dangerous command.

    Args:
        command: Command string to execute
        risk_level: Assessed risk level
        risk_reason: Reason for risk classification

    Returns:
        Tuple of (approved: bool, denial_reason: Optional[str])
    """
    # Determine warning style based on risk level
    if risk_level == RiskLevel.DANGEROUS:
        border = "="*80
        warning = "⚠️  DANGEROUS COMMAND - REQUIRES CONFIRMATION ⚠️"
    else:
        border = "="*80
        warning = "⚠️  RISKY COMMAND - REQUIRES CONFIRMATION"

    print("\n" + border)
    print(warning)
    print(border)

    # Show command details
    details = format_command_details(command, risk_level, risk_reason)
    print(details)

    # Additional warning for dangerous commands
    if risk_level == RiskLevel.DANGEROUS:
        print("\n" + "!"*80)
        print("WARNING: This command could cause irreversible damage to your system!")
        print("!"*80)

    # Prompt for confirmation
    print("\n❓ Approve this command?")
    print("   [y] Yes, proceed")
    print("   [n] No, block this command")
    print("   [a] Abort - stop the agent entirely")

    while True:
        try:
            response = input("\nYour choice (y/n/a): ").strip().lower()

            if response in ['y', 'yes']:
                print("✓ Command approved\n")
                return True, None
            elif response in ['n', 'no']:
                print("✗ Command blocked\n")
                return False, "User denied command execution"
            elif response in ['a', 'abort']:
                print("⚠️  Agent execution aborted by user\n")
                return False, "User aborted agent execution"
            else:
                print("Invalid choice. Please enter 'y', 'n', or 'a'")
        except (EOFError, KeyboardInterrupt):
            print("\n⚠️  Input interrupted, blocking command\n")
            return False, "User interrupted confirmation prompt"


async def check_pty_command(
    tool_name: str,
    arguments: Dict[str, Any],
    require_approval: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    Main entry point for checking if a PTY command should proceed.

    Args:
        tool_name: Name of the tool being invoked
        arguments: Tool arguments dict (must contain 'command')
        require_approval: If False, always approve (useful for testing)

    Returns:
        Tuple of (approved: bool, denial_reason: Optional[str])
    """
    # Extract command from arguments
    command = arguments.get("command", "")

    if not command:
        return False, "No command provided"

    # If approval not required, always allow
    if not require_approval:
        return True, None

    # Assess command risk
    risk_level, risk_reason = assess_command_risk(command)

    # Safe commands auto-approve
    if risk_level == RiskLevel.SAFE:
        return True, None

    # Risky and dangerous commands require confirmation
    return await prompt_command_confirmation(command, risk_level, risk_reason)

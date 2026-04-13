"""
Prompt version store for HALfred meta-agent system.

Manages versioned prompt files for the Realtime and Supervisor agents:
- Loads prompts from prompts/ directory at startup
- Validates integrity via HMAC-SHA256 (PROMPT_HMAC_KEY env var)
- Persists a local version ledger (prompt_versions.json) with session-based scoring
- Exposes active version IDs for metadata tagging on Supervisor calls
- Atomic writes: temp file in same directory then os.rename()

Initialization order: prompt_store must be initialized BEFORE SupervisorAgent
is constructed, since SupervisorAgent reads the active prompt at __init__ time.

Usage:
    import prompt_store
    prompt_store.init()                         # call once at startup
    text = prompt_store.get_realtime_prompt()   # with {user_name}/{user_context} filled
    text = prompt_store.get_supervisor_prompt() # raw prompt text
    ver  = prompt_store.get_active_version("realtime")
    prompt_store.record_session(session_id)     # call when a session starts
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
PROMPTS_DIR = _HERE / "prompts"
LEDGER_PATH = _HERE / "prompt_versions.json"

REALTIME_PROMPT_FILE = PROMPTS_DIR / "realtime_prompt.md"
SUPERVISOR_PROMPT_FILE = PROMPTS_DIR / "supervisor_prompt.md"
CONTRACT_FILE = PROMPTS_DIR / "agent_contract.md"

# ---------------------------------------------------------------------------
# Hardcoded fallback prompts (used when file missing or HMAC fails)
# These are intentionally minimal so a file-load failure produces a safe degraded
# experience rather than crashing startup.
# ---------------------------------------------------------------------------
_REALTIME_FALLBACK = (
    "You are Halfred, a helpful voice assistant. "
    "Use escalate_to_supervisor for any task that requires tools, "
    "web search, code execution, screenshots, or desktop automation. "
    "Handle simple conversation locally. Keep answers concise."
)

_SUPERVISOR_FALLBACK = (
    "You are the Supervisor agent. Handle the escalated task using available tools. "
    "Always respond with valid JSON: "
    '{"status":"success"|"error","task_type":"other","summary":"...","data":{}}'
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PromptVersion:
    """One entry in the local version ledger."""
    version_id: str
    agent: str                      # "realtime" or "supervisor"
    prompt_text: str
    hmac_hex: str
    parent_version_id: Optional[str]
    deployed_at: float              # Unix timestamp
    deployed_at_iso: str
    feedback_thumbs_up: int = 0
    feedback_thumbs_down: int = 0
    session_ids: list = field(default_factory=list)   # distinct session_ids seen under this version
    tool_call_count: int = 0
    is_current: bool = False
    is_rollback_target: bool = False  # set True when this version is restored by a rollback

    def session_count(self) -> int:
        return len(set(self.session_ids))

    def score(self) -> Optional[float]:
        """
        Weighted score: 0.7 * explicit_feedback_rate + 0.3 * session_completion_proxy.

        Returns None when sample threshold not yet met (< 15 tool calls, < 2 sessions).
        The session_completion_proxy is simplified here as 1.0 (no premature-end detection
        yet); it will be populated by the meta-agent as it gains more signals.
        """
        if self.tool_call_count < 15 or self.session_count() < 2:
            return None
        total_fb = self.feedback_thumbs_up + self.feedback_thumbs_down
        if total_fb == 0:
            return None
        explicit_rate = self.feedback_thumbs_up / total_fb
        return round(explicit_rate * 0.7 + 1.0 * 0.3, 4)

    def is_stale(self, cutoff_days: int = 14) -> bool:
        """True when all collected data is older than cutoff_days."""
        age_days = (time.time() - self.deployed_at) / 86400
        return age_days > cutoff_days


@dataclass
class PromptLedger:
    """In-memory + on-disk ledger of all prompt versions."""
    versions: list = field(default_factory=list)      # List[PromptVersion]

    # Current active version IDs per agent
    current_realtime_version_id: Optional[str] = None
    current_supervisor_version_id: Optional[str] = None

    def get_version(self, version_id: str) -> Optional[PromptVersion]:
        for v in self.versions:
            if v.version_id == version_id:
                return v
        return None

    def get_current(self, agent: str) -> Optional[PromptVersion]:
        vid = (self.current_realtime_version_id if agent == "realtime"
               else self.current_supervisor_version_id)
        return self.get_version(vid) if vid else None

    def get_versions_for_agent(self, agent: str) -> list:
        return [v for v in self.versions if v.agent == agent]


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_ledger: Optional[PromptLedger] = None
_hmac_key: Optional[bytes] = None
_initialized: bool = False


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------

def _compute_hmac(text: str) -> str:
    """Compute HMAC-SHA256 of prompt text. Returns hex string."""
    if _hmac_key is None:
        return ""
    return hmac.new(_hmac_key, text.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_hmac(text: str, expected_hex: str) -> bool:
    """Constant-time HMAC verification."""
    if _hmac_key is None:
        return True   # HMAC disabled — allow all
    actual = _compute_hmac(text)
    return hmac.compare_digest(actual, expected_hex)


# ---------------------------------------------------------------------------
# Ledger persistence
# ---------------------------------------------------------------------------

def _load_ledger() -> PromptLedger:
    """Load ledger from disk. Returns empty ledger if file missing/corrupt."""
    if not LEDGER_PATH.exists():
        return PromptLedger()
    try:
        with open(LEDGER_PATH, "r") as f:
            raw = json.load(f)
        ledger = PromptLedger(
            current_realtime_version_id=raw.get("current_realtime_version_id"),
            current_supervisor_version_id=raw.get("current_supervisor_version_id"),
        )
        for vd in raw.get("versions", []):
            ledger.versions.append(PromptVersion(**vd))
        return ledger
    except Exception as e:
        print(f"[prompt_store] WARNING: Could not load ledger ({e}), starting fresh")
        return PromptLedger()


def _save_ledger() -> None:
    """Atomically write ledger to disk (same-dir temp + rename)."""
    if _ledger is None:
        return
    tmp = LEDGER_PATH.with_name(".tmp_prompt_versions.json")
    try:
        payload = {
            "current_realtime_version_id": _ledger.current_realtime_version_id,
            "current_supervisor_version_id": _ledger.current_supervisor_version_id,
            "versions": [asdict(v) for v in _ledger.versions],
            "saved_at_iso": datetime.now().isoformat(),
        }
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.rename(tmp, LEDGER_PATH)
    except Exception as e:
        print(f"[prompt_store] ERROR saving ledger: {e}")
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Prompt file I/O
# ---------------------------------------------------------------------------

def _load_prompt_file(path: Path, agent: str) -> Optional[str]:
    """
    Load a prompt file, verifying its HMAC if a key is configured.

    Returns None on failure (caller falls back to hardcoded default).
    """
    if not path.exists():
        print(f"[prompt_store] Prompt file not found: {path} — using fallback")
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            print(f"[prompt_store] Prompt file empty: {path} — using fallback")
            return None

        # HMAC check: look up expected hash in ledger
        if _hmac_key and _ledger:
            current = _ledger.get_current(agent)
            if current and current.hmac_hex:
                if not _verify_hmac(text, current.hmac_hex):
                    print(f"[prompt_store] HMAC MISMATCH for {agent} prompt — using fallback")
                    return None

        return text
    except Exception as e:
        print(f"[prompt_store] ERROR reading {path}: {e} — using fallback")
        return None


# ---------------------------------------------------------------------------
# Version registration
# ---------------------------------------------------------------------------

def _register_initial_version(agent: str, text: str) -> PromptVersion:
    """
    Register the prompt text as a new initial version in the ledger.
    Called at startup when no existing version is recorded for this agent.
    """
    version_id = f"v_{agent}_{uuid.uuid4().hex[:8]}"
    hmac_hex = _compute_hmac(text)
    now = time.time()
    version = PromptVersion(
        version_id=version_id,
        agent=agent,
        prompt_text=text,
        hmac_hex=hmac_hex,
        parent_version_id=None,
        deployed_at=now,
        deployed_at_iso=datetime.fromtimestamp(now).isoformat(),
        is_current=True,
    )
    _ledger.versions.append(version)
    if agent == "realtime":
        _ledger.current_realtime_version_id = version_id
    else:
        _ledger.current_supervisor_version_id = version_id
    return version


def _ensure_version_for_text(agent: str, text: str) -> PromptVersion:
    """
    Ensure the ledger has a version entry for the given prompt text.

    If an existing version's HMAC matches the text, reuse it (avoids creating
    duplicate versions on every startup). Otherwise register as new initial version.
    """
    h = _compute_hmac(text)
    for v in _ledger.get_versions_for_agent(agent):
        if _hmac_key:
            if hmac.compare_digest(v.hmac_hex, h):
                # Reuse: ensure it is marked current
                for other in _ledger.get_versions_for_agent(agent):
                    other.is_current = False
                v.is_current = True
                if agent == "realtime":
                    _ledger.current_realtime_version_id = v.version_id
                else:
                    _ledger.current_supervisor_version_id = v.version_id
                return v
        else:
            # No HMAC: match by text content
            if v.prompt_text == text:
                for other in _ledger.get_versions_for_agent(agent):
                    other.is_current = False
                v.is_current = True
                if agent == "realtime":
                    _ledger.current_realtime_version_id = v.version_id
                else:
                    _ledger.current_supervisor_version_id = v.version_id
                return v
    # No match — register new
    return _register_initial_version(agent, text)


# ---------------------------------------------------------------------------
# Cached prompt texts (raw, without template substitution)
# ---------------------------------------------------------------------------
_realtime_raw: str = _REALTIME_FALLBACK
_supervisor_raw: str = _SUPERVISOR_FALLBACK


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init() -> None:
    """
    Initialize the prompt store.

    Must be called once at startup, BEFORE SupervisorAgent is constructed.
    Loads prompt files, validates HMAC (if key configured), loads ledger,
    and registers any new initial versions.
    """
    global _ledger, _hmac_key, _initialized, _realtime_raw, _supervisor_raw

    if _initialized:
        return

    # Load HMAC key
    key_str = os.getenv("PROMPT_HMAC_KEY", "")
    if key_str:
        _hmac_key = key_str.encode("utf-8")
        print("[prompt_store] HMAC integrity checking enabled")
    else:
        print("[prompt_store] PROMPT_HMAC_KEY not set — HMAC checking disabled")

    # Load ledger before file loading (needed for HMAC lookup)
    _ledger = _load_ledger()

    # Load prompt files (fallback to hardcoded defaults on any failure)
    rt = _load_prompt_file(REALTIME_PROMPT_FILE, "realtime")
    _realtime_raw = rt if rt else _REALTIME_FALLBACK
    if rt is None:
        print("[prompt_store] Using hardcoded fallback for realtime prompt")

    sv = _load_prompt_file(SUPERVISOR_PROMPT_FILE, "supervisor")
    _supervisor_raw = sv if sv else _SUPERVISOR_FALLBACK
    if sv is None:
        print("[prompt_store] Using hardcoded fallback for supervisor prompt")

    # Ensure ledger has version entries for the loaded texts
    _ensure_version_for_text("realtime", _realtime_raw)
    _ensure_version_for_text("supervisor", _supervisor_raw)
    _save_ledger()

    _initialized = True
    rt_ver = _ledger.get_current("realtime")
    sv_ver = _ledger.get_current("supervisor")
    print(f"[prompt_store] Initialized — realtime: {rt_ver.version_id if rt_ver else 'none'}, "
          f"supervisor: {sv_ver.version_id if sv_ver else 'none'}")


def get_realtime_prompt(user_name: str = "the user", user_context: str = "") -> str:
    """
    Return the active Realtime prompt with {user_name}/{user_context} filled in.

    Falls back to hardcoded string if prompt_store was not initialized.
    """
    text = _realtime_raw if _initialized else _REALTIME_FALLBACK
    return text.replace("{user_name}", user_name).replace("{user_context}", user_context)


def get_supervisor_prompt() -> str:
    """Return the active Supervisor prompt (raw, no template substitution needed)."""
    return _supervisor_raw if _initialized else _SUPERVISOR_FALLBACK


def get_contract() -> str:
    """Return the agent_contract.md text (empty string if file missing)."""
    try:
        if CONTRACT_FILE.exists():
            return CONTRACT_FILE.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[prompt_store] Could not read contract file: {e}")
    return ""


def get_active_version(agent: str) -> Optional[str]:
    """
    Return the active version_id for 'realtime' or 'supervisor'.

    Used to tag Supervisor API calls with metadata={"prompt_version": ...}.
    Returns None if not initialized.
    """
    if not _initialized or _ledger is None:
        return None
    v = _ledger.get_current(agent)
    return v.version_id if v else None


def record_session(session_id: str) -> None:
    """
    Record that a new session started under the current prompt versions.

    Call once per session (e.g., just after SessionLogger is created).
    This increments the session counter used in the 2-session minimum window.
    """
    if not _initialized or _ledger is None:
        return
    for agent in ("realtime", "supervisor"):
        v = _ledger.get_current(agent)
        if v and session_id not in v.session_ids:
            v.session_ids.append(session_id)
    _save_ledger()


def record_tool_call(agent: str = "supervisor") -> None:
    """Increment tool_call_count on the current version (used for sample thresholds)."""
    if not _initialized or _ledger is None:
        return
    v = _ledger.get_current(agent)
    if v:
        v.tool_call_count += 1
    _save_ledger()


def record_feedback(thumbs_up: bool, agent: str = "supervisor") -> None:
    """Record an explicit thumbs-up or thumbs-down on the current version."""
    if not _initialized or _ledger is None:
        return
    v = _ledger.get_current(agent)
    if v:
        if thumbs_up:
            v.feedback_thumbs_up += 1
        else:
            v.feedback_thumbs_down += 1
    _save_ledger()


def deploy_new_version(
    agent: str,
    new_prompt_text: str,
    parent_version_id: Optional[str] = None,
) -> PromptVersion:
    """
    Deploy a new approved prompt version.

    Atomically writes the new text to the prompt file and registers it in the ledger.
    The caller is responsible for calling supervisor.reset_conversation() after this.

    Args:
        agent: "realtime" or "supervisor"
        new_prompt_text: The full new prompt text (already approved by user)
        parent_version_id: Version this was derived from (for lineage tracking)

    Returns:
        The newly created PromptVersion
    """
    if not _initialized or _ledger is None:
        raise RuntimeError("prompt_store.init() must be called before deploy_new_version()")

    # Mark all existing versions for this agent as non-current
    for v in _ledger.get_versions_for_agent(agent):
        v.is_current = False

    # Build new version record
    version_id = f"v_{agent}_{uuid.uuid4().hex[:8]}"
    hmac_hex = _compute_hmac(new_prompt_text)
    now = time.time()
    new_version = PromptVersion(
        version_id=version_id,
        agent=agent,
        prompt_text=new_prompt_text,
        hmac_hex=hmac_hex,
        parent_version_id=parent_version_id or get_active_version(agent),
        deployed_at=now,
        deployed_at_iso=datetime.fromtimestamp(now).isoformat(),
        is_current=True,
    )
    _ledger.versions.append(new_version)

    if agent == "realtime":
        _ledger.current_realtime_version_id = version_id
    else:
        _ledger.current_supervisor_version_id = version_id

    # Atomic file write
    target_file = REALTIME_PROMPT_FILE if agent == "realtime" else SUPERVISOR_PROMPT_FILE
    tmp = target_file.with_name(f".tmp_{target_file.name}")
    try:
        tmp.write_text(new_prompt_text, encoding="utf-8")
        os.rename(tmp, target_file)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to write prompt file for {agent}: {e}")

    # Update in-memory cache
    global _realtime_raw, _supervisor_raw
    if agent == "realtime":
        _realtime_raw = new_prompt_text
    else:
        _supervisor_raw = new_prompt_text

    _save_ledger()
    print(f"[prompt_store] Deployed new {agent} prompt version: {version_id}")
    return new_version


def deploy_batch(changes: list) -> dict:
    """
    Deploy prompt changes for one or more agents atomically.

    All-or-nothing semantics: if any file write fails, no changes are applied.
    In-memory state (caches, ledger pointers) is only mutated after all file
    writes succeed.

    Args:
        changes: List of dicts, each with keys:
            - agent (str): "realtime" or "supervisor"
            - new_prompt_text (str): Full new prompt text
            - parent_version_id (str|None): Version this was derived from

    Returns:
        Dict mapping agent name to the newly created PromptVersion.

    Raises:
        RuntimeError: If prompt_store not initialized or any file write fails.
    """
    if not _initialized or _ledger is None:
        raise RuntimeError("prompt_store.init() must be called before deploy_batch()")

    if not changes:
        return {}

    # Phase 1: Build all version records and write temp files (no renames yet)
    temp_files = []  # [(tmp_path, target_path, agent, new_version)]
    new_versions = {}

    try:
        for change in changes:
            agent = change["agent"]
            new_text = change["new_prompt_text"]
            parent_vid = change.get("parent_version_id")

            version_id = f"v_{agent}_{uuid.uuid4().hex[:8]}"
            hmac_hex = _compute_hmac(new_text)
            now = time.time()
            new_version = PromptVersion(
                version_id=version_id,
                agent=agent,
                prompt_text=new_text,
                hmac_hex=hmac_hex,
                parent_version_id=parent_vid or get_active_version(agent),
                deployed_at=now,
                deployed_at_iso=datetime.fromtimestamp(now).isoformat(),
                is_current=True,
            )

            target_file = REALTIME_PROMPT_FILE if agent == "realtime" else SUPERVISOR_PROMPT_FILE
            tmp = target_file.with_name(f".tmp_{target_file.name}")
            tmp.write_text(new_text, encoding="utf-8")
            temp_files.append((tmp, target_file, agent, new_version))
            new_versions[agent] = new_version

    except Exception as e:
        # Clean up any temp files written so far
        for tmp, _, _, _ in temp_files:
            tmp.unlink(missing_ok=True)
        raise RuntimeError(f"deploy_batch: temp file write failed: {e}")

    # Phase 2: Validate all temp files exist and are non-empty
    for tmp, _, agent, _ in temp_files:
        if not tmp.exists() or tmp.stat().st_size == 0:
            for t, _, _, _ in temp_files:
                t.unlink(missing_ok=True)
            raise RuntimeError(f"deploy_batch: temp file validation failed for {agent}")

    # Phase 3: Atomic rename each temp → target
    renamed = []
    try:
        for tmp, target, agent, _ in temp_files:
            os.rename(tmp, target)
            renamed.append((tmp, target, agent))
    except Exception as e:
        # Some renames may have succeeded — this is the accepted residual risk
        # of non-transactional filesystems. Log but don't try to undo renames.
        # Clean up any remaining temp files.
        for tmp, _, _, _ in temp_files:
            tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"deploy_batch: rename failed for {agent} after {len(renamed)} successful renames: {e}"
        )

    # Phase 4: All file writes succeeded — now mutate in-memory state
    global _realtime_raw, _supervisor_raw
    for agent, new_version in new_versions.items():
        # Mark all existing versions for this agent as non-current
        for v in _ledger.get_versions_for_agent(agent):
            v.is_current = False
        # Add new version to ledger
        _ledger.versions.append(new_version)
        if agent == "realtime":
            _ledger.current_realtime_version_id = new_version.version_id
            _realtime_raw = new_version.prompt_text
        else:
            _ledger.current_supervisor_version_id = new_version.version_id
            _supervisor_raw = new_version.prompt_text

    # Phase 5: Save ledger
    _save_ledger()
    agents_str = ", ".join(f"{a}: {v.version_id}" for a, v in new_versions.items())
    print(f"[prompt_store] Batch deployed — {agents_str}")
    return new_versions


def get_ledger_summary() -> dict:
    """
    Return a concise summary of the ledger for meta-agent context injection.

    Strips full prompt text to avoid bloating the context window.
    """
    if not _initialized or _ledger is None:
        return {}
    summary = {
        "current_realtime_version": _ledger.current_realtime_version_id,
        "current_supervisor_version": _ledger.current_supervisor_version_id,
        "versions": [],
    }
    for v in _ledger.versions:
        summary["versions"].append({
            "version_id": v.version_id,
            "agent": v.agent,
            "deployed_at_iso": v.deployed_at_iso,
            "parent_version_id": v.parent_version_id,
            "feedback_thumbs_up": v.feedback_thumbs_up,
            "feedback_thumbs_down": v.feedback_thumbs_down,
            "session_count": v.session_count(),
            "tool_call_count": v.tool_call_count,
            "score": v.score(),
            "is_current": v.is_current,
            "is_stale": v.is_stale(),
        })
    return summary

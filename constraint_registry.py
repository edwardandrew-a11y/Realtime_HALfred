"""
Constraint registry for HALfred metaprompt agent.

Stores feedback-derived behavioral constraints that the meta-agent must
consult before proposing prompt changes. Each constraint is a distilled
rule linked to the user feedback and prompt version that motivated it.

Architecture:
- Source of truth: prompts/constraint_registry.json (structured, app-owned)
- Human-readable summary: generated on demand, never stored as a file
- LLM interaction: meta-agent outputs discrete operations (add_constraint,
  supersede_constraint, mark_resolved); the application validates and applies
  them deterministically. The LLM never writes the registry directly.
- Trust model: registry content is injected as delimited reference data,
  NOT as trusted instructions.

Persistence:
- Atomic writes (same-dir temp + os.rename), consistent with prompt_store.py
- Schema-versioned with migration hooks from day one

Seed file:
- On first init, if prompts/constraint_seed.md exists, it is parsed into
  initial constraints and the seed file is renamed to .applied
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
REGISTRY_PATH = _HERE / "prompts" / "constraint_registry.json"
SEED_PATH = _HERE / "prompts" / "constraint_seed.md"

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------
_CURRENT_SCHEMA_VERSION = 1

VALID_AGENTS = {"realtime", "supervisor"}
VALID_KINDS = {"hard_constraint", "preference", "observation"}
VALID_STATUSES = {"active", "superseded", "resolved"}
VALID_OPS = {"add_constraint", "supersede_constraint", "mark_resolved"}

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_registry: Optional[dict] = None
_initialized: bool = False
_next_counters: dict = {}  # {"realtime": 1, "supervisor": 1} — for ID generation


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _agent_prefix(agent: str) -> str:
    return "RT" if agent == "realtime" else "SV"


def _next_id(agent: str) -> str:
    """Generate the next constraint ID for an agent (e.g., RT-001, SV-002)."""
    prefix = _agent_prefix(agent)
    counter = _next_counters.get(agent, 1)
    cid = f"{prefix}-{counter:03d}"
    _next_counters[agent] = counter + 1
    return cid


def _rebuild_counters() -> None:
    """Rebuild next-ID counters from existing constraints."""
    global _next_counters
    _next_counters = {"realtime": 1, "supervisor": 1}
    if not _registry:
        return
    for c in _registry.get("constraints", []):
        agent = c.get("agent", "")
        cid = c.get("id", "")
        prefix = _agent_prefix(agent) if agent in VALID_AGENTS else ""
        if cid.startswith(prefix + "-"):
            try:
                num = int(cid.split("-")[1])
                if num >= _next_counters.get(agent, 1):
                    _next_counters[agent] = num + 1
            except (ValueError, IndexError):
                pass


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

def _load_registry_file(path: Path) -> dict:
    """Load and migrate the registry file."""
    if not path.exists():
        return {"schema_version": _CURRENT_SCHEMA_VERSION, "constraints": []}
    try:
        with open(path, "r") as f:
            raw = json.load(f)
        version = raw.get("schema_version", 0)
        if version == _CURRENT_SCHEMA_VERSION:
            return raw
        if version < _CURRENT_SCHEMA_VERSION:
            return _migrate(raw, version)
        raise ValueError(
            f"Registry schema_version {version} is newer than supported {_CURRENT_SCHEMA_VERSION}"
        )
    except Exception as e:
        print(f"[constraint_registry] WARNING: Could not load registry ({e}), starting fresh")
        return {"schema_version": _CURRENT_SCHEMA_VERSION, "constraints": []}


def _migrate(raw: dict, from_version: int) -> dict:
    """Apply sequential migrations. Each migration bumps version by 1."""
    data = raw
    if from_version < 1:
        data = _migrate_0_to_1(data)
    # Future: if from_version < 2: data = _migrate_1_to_2(data)
    return data


def _migrate_0_to_1(data: dict) -> dict:
    """v0 (no schema_version field) -> v1."""
    data["schema_version"] = 1
    data.setdefault("constraints", [])
    return data


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _save_registry() -> None:
    """Atomically write registry to disk (same-dir temp + rename)."""
    if _registry is None:
        return
    tmp = REGISTRY_PATH.with_name(".tmp_constraint_registry.json")
    try:
        payload = dict(_registry)
        payload["saved_at_iso"] = datetime.now().isoformat()
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.rename(tmp, REGISTRY_PATH)
    except Exception as e:
        print(f"[constraint_registry] ERROR saving registry: {e}")
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Seed file parsing
# ---------------------------------------------------------------------------

def _parse_seed_file(path: Path) -> list:
    """
    Parse a constraint_seed.md file into constraint entries.

    Format:
        ## realtime hard_constraint
        Rule text here.

        ## supervisor preference
        Another rule text.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[constraint_registry] Could not read seed file: {e}")
        return []

    constraints = []
    current_agent = None
    current_kind = None
    current_lines = []

    def _flush():
        if current_agent and current_kind and current_lines:
            rule = " ".join(current_lines).strip()
            if rule:
                constraints.append({
                    "agent": current_agent,
                    "kind": current_kind,
                    "rule": rule,
                    "source": "manual_seed",
                })

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            _flush()
            current_lines = []
            parts = stripped[3:].strip().split(None, 1)
            if len(parts) == 2 and parts[0] in VALID_AGENTS and parts[1] in VALID_KINDS:
                current_agent = parts[0]
                current_kind = parts[1]
            else:
                current_agent = None
                current_kind = None
        elif stripped.startswith("# "):
            # Top-level heading, skip
            _flush()
            current_agent = None
            current_kind = None
            current_lines = []
        elif stripped and current_agent:
            current_lines.append(stripped)

    _flush()
    return constraints


def _apply_seed(constraints: list) -> int:
    """Apply parsed seed constraints to the registry. Returns count added."""
    if not _registry or not constraints:
        return 0
    count = 0
    now_iso = datetime.now().isoformat()
    for c in constraints:
        entry = {
            "id": _next_id(c["agent"]),
            "agent": c["agent"],
            "kind": c["kind"],
            "rule": c["rule"][:500],
            "evidence_interaction_ids": [],
            "source": c.get("source", "manual_seed"),
            "status": "active",
            "introduced_by_version": None,
            "introduced_by_proposal": None,
            "superseded_by": None,
            "supersedes": None,
            "created_at": now_iso,
            "last_reviewed_at": now_iso,
        }
        _registry["constraints"].append(entry)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init() -> None:
    """
    Initialize the constraint registry.

    Call after prompt_store.init() at startup. Loads registry from disk,
    applies seed file if present on first run, rebuilds ID counters.
    """
    global _registry, _initialized

    if _initialized:
        return

    _registry = _load_registry_file(REGISTRY_PATH)
    _rebuild_counters()

    # Apply seed file on first run (if registry is empty and seed exists)
    if not _registry["constraints"] and SEED_PATH.exists():
        seed_constraints = _parse_seed_file(SEED_PATH)
        if seed_constraints:
            count = _apply_seed(seed_constraints)
            _save_registry()
            # Rename seed file so it's only processed once
            applied_path = SEED_PATH.with_suffix(".md.applied")
            try:
                os.rename(SEED_PATH, applied_path)
            except Exception as e:
                print(f"[constraint_registry] Could not rename seed file: {e}")
            print(f"[constraint_registry] Applied {count} seed constraints")

    _initialized = True
    active_count = len([c for c in _registry["constraints"] if c.get("status") == "active"])
    print(f"[constraint_registry] Initialized — {active_count} active constraints")


def get_active_constraints(agent: str = None) -> list:
    """
    Return active constraints, optionally filtered by agent.

    Args:
        agent: If provided, filter to "realtime" or "supervisor" only.

    Returns:
        List of constraint dicts with status "active".
    """
    if not _initialized or not _registry:
        return []
    constraints = [
        c for c in _registry["constraints"]
        if c.get("status") == "active"
    ]
    if agent:
        constraints = [c for c in constraints if c.get("agent") == agent]
    return constraints


def get_summary_for_llm(max_tokens_approx: int = 2000) -> str:
    """
    Generate a compact text summary of active constraints for LLM context injection.

    Hard constraints are never omitted. If the summary exceeds the token budget,
    oldest observations are dropped first, then oldest preferences.

    Returns text to be wrapped in <constraint_registry_data> delimiters by the caller.
    """
    if not _initialized or not _registry:
        return "(no constraint registry loaded)"

    active = get_active_constraints()
    if not active:
        return "(no active constraints)"

    # Sort: hard_constraints first, then preferences, then observations
    # Within each kind, newest first
    kind_order = {"hard_constraint": 0, "preference": 1, "observation": 2}
    active.sort(key=lambda c: (kind_order.get(c.get("kind"), 9), c.get("created_at", "")))

    lines = []
    for c in active:
        cid = c.get("id", "?")
        agent = c.get("agent", "?")
        kind = c.get("kind", "?")
        rule = c.get("rule", "")[:200]
        evidence = c.get("evidence_interaction_ids", [])
        evidence_str = f" evidence=[{', '.join(evidence[:3])}]" if evidence else ""
        lines.append(f"[{cid}] {agent} {kind}: {rule}{evidence_str}")

    summary = "\n".join(lines)

    # Rough token estimate: ~4 chars per token
    while len(summary) > max_tokens_approx * 4 and lines:
        # Drop last line (lowest priority: oldest observation/preference)
        lines.pop()
        summary = "\n".join(lines)

    return summary


def get_readable_markdown() -> str:
    """
    Generate a full human-readable Markdown summary of all constraints.

    Used for staging files in the approval flow and manual inspection.
    """
    if not _initialized or not _registry:
        return "# Constraint Registry\n\n(not initialized)\n"

    sections = {
        "realtime": {"active": [], "other": []},
        "supervisor": {"active": [], "other": []},
    }

    for c in _registry.get("constraints", []):
        agent = c.get("agent", "unknown")
        if agent not in sections:
            sections[agent] = {"active": [], "other": []}
        bucket = "active" if c.get("status") == "active" else "other"
        sections[agent][bucket].append(c)

    lines = ["# Constraint Registry\n"]

    for agent in ("realtime", "supervisor"):
        lines.append(f"\n## {agent.title()} Agent — Active Constraints\n")
        if not sections[agent]["active"]:
            lines.append("(none)\n")
        for c in sections[agent]["active"]:
            lines.append(f"### {c['id']}: {c.get('kind', '?')} ({c.get('created_at', '?')[:10]})")
            lines.append(f"- **Rule:** {c.get('rule', '')}")
            evidence = c.get("evidence_interaction_ids", [])
            if evidence:
                lines.append(f"- **Evidence:** {', '.join(evidence[:5])}")
            ver = c.get("introduced_by_version")
            if ver:
                lines.append(f"- **Introduced by:** {ver}")
            lines.append("")

        if sections[agent]["other"]:
            lines.append(f"\n## {agent.title()} Agent — Superseded/Resolved\n")
            for c in sections[agent]["other"]:
                status = c.get("status", "?")
                lines.append(f"### {c['id']}: [{status.upper()}] {c.get('rule', '')[:80]}")
                sup = c.get("superseded_by")
                if sup:
                    lines.append(f"- Superseded by: {sup}")
                lines.append("")

    return "\n".join(lines)


def apply_operations(
    ops: list,
    proposal_id: str,
    version_map: dict,
) -> list:
    """
    Apply constraint operations from a meta-agent proposal.

    Each operation is validated before application. Invalid operations are
    logged and skipped (non-fatal).

    Args:
        ops: List of operation dicts from the meta-agent's JSON output.
        proposal_id: The proposal ID for audit trail.
        version_map: Dict mapping agent name to new version ID
                     (e.g., {"realtime": "v_realtime_x1y2"}).

    Returns:
        List of constraint IDs that were actually affected.
    """
    if not _initialized or not _registry:
        print("[constraint_registry] Not initialized — skipping operations")
        return []

    if not ops or not isinstance(ops, list):
        return []

    affected_ids = []
    now_iso = datetime.now().isoformat()

    for op in ops:
        if not isinstance(op, dict):
            print(f"[constraint_registry] Skipping non-dict operation: {op}")
            continue

        op_type = op.get("op", "")
        if op_type not in VALID_OPS:
            print(f"[constraint_registry] Skipping unknown operation: {op_type}")
            continue

        try:
            if op_type == "add_constraint":
                cid = _apply_add(op, proposal_id, version_map, now_iso)
                if cid:
                    affected_ids.append(cid)

            elif op_type == "supersede_constraint":
                cid = _apply_supersede(op, proposal_id, now_iso)
                if cid:
                    affected_ids.append(cid)

            elif op_type == "mark_resolved":
                cid = _apply_resolve(op, proposal_id, now_iso)
                if cid:
                    affected_ids.append(cid)

        except Exception as e:
            print(f"[constraint_registry] Error applying {op_type}: {e}")

    if affected_ids:
        _rebuild_counters()

    return affected_ids


def _apply_add(op: dict, proposal_id: str, version_map: dict, now_iso: str) -> Optional[str]:
    """Apply an add_constraint operation. Returns the new constraint ID or None."""
    agent = op.get("agent", "")
    kind = op.get("kind", "")
    rule = op.get("rule", "")
    evidence = op.get("evidence_interaction_ids", [])
    supersedes = op.get("supersedes")

    # Validation
    if agent not in VALID_AGENTS:
        print(f"[constraint_registry] add_constraint: invalid agent '{agent}'")
        return None
    if kind not in VALID_KINDS:
        print(f"[constraint_registry] add_constraint: invalid kind '{kind}'")
        return None
    if not rule or not isinstance(rule, str):
        print("[constraint_registry] add_constraint: empty or non-string rule")
        return None
    if len(rule) > 500:
        rule = rule[:500]

    # Check version_map has this agent
    version_id = version_map.get(agent)
    if not version_id:
        print(f"[constraint_registry] add_constraint: no version_id for agent '{agent}' in version_map")
        return None

    if not isinstance(evidence, list):
        evidence = []

    cid = _next_id(agent)
    entry = {
        "id": cid,
        "agent": agent,
        "kind": kind,
        "rule": rule,
        "evidence_interaction_ids": evidence[:10],
        "source": "metaprompt_proposal",
        "status": "active",
        "introduced_by_version": version_id,
        "introduced_by_proposal": proposal_id,
        "superseded_by": None,
        "supersedes": supersedes,
        "created_at": now_iso,
        "last_reviewed_at": now_iso,
    }
    _registry["constraints"].append(entry)
    print(f"[constraint_registry] Added {cid} ({agent} {kind}): {rule[:60]}")
    return cid


def _apply_supersede(op: dict, proposal_id: str, now_iso: str) -> Optional[str]:
    """Apply a supersede_constraint operation. Returns the target constraint ID or None."""
    target_id = op.get("target_id", "")
    reason = op.get("reason", "")

    target = _find_constraint(target_id)
    if not target:
        print(f"[constraint_registry] supersede_constraint: '{target_id}' not found")
        return None
    if target.get("status") != "active":
        print(f"[constraint_registry] supersede_constraint: '{target_id}' is not active")
        return None

    target["status"] = "superseded"
    target["superseded_by"] = f"proposal:{proposal_id}"
    target["last_reviewed_at"] = now_iso
    print(f"[constraint_registry] Superseded {target_id}: {reason[:60]}")
    return target_id


def _apply_resolve(op: dict, proposal_id: str, now_iso: str) -> Optional[str]:
    """Apply a mark_resolved operation. Returns the target constraint ID or None."""
    target_id = op.get("target_id", "")
    reason = op.get("reason", "")

    target = _find_constraint(target_id)
    if not target:
        print(f"[constraint_registry] mark_resolved: '{target_id}' not found")
        return None
    if target.get("status") != "active":
        print(f"[constraint_registry] mark_resolved: '{target_id}' is not active")
        return None

    target["status"] = "resolved"
    target["last_reviewed_at"] = now_iso
    print(f"[constraint_registry] Resolved {target_id}: {reason[:60]}")
    return target_id


def _find_constraint(constraint_id: str) -> Optional[dict]:
    """Find a constraint by ID."""
    if not _registry:
        return None
    for c in _registry.get("constraints", []):
        if c.get("id") == constraint_id:
            return c
    return None


def save() -> None:
    """Save the registry to disk (atomic write). Call after apply_operations()."""
    _save_registry()


def get_all_constraints() -> list:
    """Return all constraints (all statuses). For testing and inspection."""
    if not _initialized or not _registry:
        return []
    return list(_registry.get("constraints", []))

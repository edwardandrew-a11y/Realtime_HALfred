# Metaprompt Agent — Architecture & Operations Guide

This document describes the autonomous prompt optimization system added in v1.23.
It is the authoritative reference for both human developers and AI coding agents
working in this codebase.

---

## What It Is

A single LLM call that runs **between sessions** (during dormancy). It reads session
logs and user feedback, reasons about which agent failed and why, and proposes new
prompt text for one or both agents. All proposals require explicit human approval
before anything is written to disk.

**Important distinction:**
- The **meta-agent** (this system) is the *brain* — it reasons and generates candidates
- **OpenAI Evals** is the *ledger* — version tagging via `metadata={"prompt_version": ...}`
  happens on every Supervisor API call (essentially free). Batch comparisons are done
  offline via a separate script, not inline.

---

## File Map

### New files (added in v1.23)

| File | Purpose |
|---|---|
| [`prompts/realtime_prompt.md`](../prompts/realtime_prompt.md) | Halfred's system prompt — now editable as a plain text file with `{user_name}`/`{user_context}` placeholders |
| [`prompts/supervisor_prompt.md`](../prompts/supervisor_prompt.md) | Supervisor system prompt — editable without touching Python |
| [`prompts/agent_contract.md`](../prompts/agent_contract.md) | Interface contract injected into the meta-agent on every run |
| [`prompt_store.py`](../prompt_store.py) | Versioned prompt loader: HMAC integrity, local ledger, atomic writes, version tracking by `session_id` |
| [`feedback_service.py`](../feedback_service.py) | Wrapper over macos-automator for satisfaction popups and approval dialogs; shared dialog guard |
| [`metaprompt_agent.py`](../metaprompt_agent.py) | The meta-agent: log reading, tool-output stripping, feedback injection-mitigation, champion/challenger scoring, LLM call, approval flow |
| [`docs/METAPROMPT.md`](METAPROMPT.md) | Full architecture, flow, security model, config reference |
| [`test_metaprompt.py`](../test_metaprompt.py) | 39 tests covering all critical paths — all passing |

### New files (added in v1.24 — constraint registry)

| File | Purpose |
|---|---|
| [`constraint_registry.py`](../constraint_registry.py) | Structured registry of feedback-derived behavioral constraints: CRUD, validation, schema migration, LLM summary generation, atomic persistence |
| [`prompts/constraint_registry.json`](../prompts/constraint_registry.json) | App-owned JSON registry of learned constraints — source of truth |
| [`prompts/constraint_seed.md`](../prompts/constraint_seed.md) | (Optional) User-authored bootstrap file for initial constraints; renamed to `.applied` after processing |

### Modified files

| File | Change |
|---|---|
| `session_logger.py` | `log_user_feedback()`, `log_metaprompt_proposal()`, `log_metaprompt_decision()`, `drain()`; writer loop calls `queue.task_done()`; proposal/decision logs include `constraint_operations` and `constraint_ids_affected` fields |
| `supervisor.py` | Loads instructions from `prompt_store` with class-constant fallback; `reset_conversation()`; tags API calls with `metadata={"prompt_version": ...}` |
| `main.py` | `ListenState` + `AppRuntimeState` new fields; `prompt_store.init()` + `constraint_registry.init()` at startup; satisfaction popup handshake in `event_loop`; meta-agent trigger in DORMANT block |
| `prompt_store.py` | `deploy_batch()` for all-or-nothing multi-agent prompt deployment |
| `metaprompt_agent.py` | Fixed feedback consumption bug; injects constraint registry as delimited reference data; expanded JSON schema with `constraint_operations` and `contradicts_constraints`; uses `deploy_batch()` instead of per-agent loop; gates constraint writes behind successful prompt deployment |
| `feedback_service.py` | `ask_approval()` signature changed from `staging_file_path: str` to `staging_paths: list[str]` for multi-artifact approval bundles |
| `.env.example` | `ENABLE_METAPROMPT_AGENT`, `METAPROMPT_MODEL`, `PROMPT_HMAC_KEY` |
| `prompt_versions.json` | Auto-generated local version ledger — do not edit manually |

---

## End-to-End Flow

```
User voice session
    ↓
[tool_end: escalate_to_supervisor]
    → ListenState.last_turn_had_escalation = True
    → prompt_store.record_tool_call()

[agent_end: Halfred finishes narrating]
    → feedback_service.ask_satisfaction() fires (if ENABLE_METAPROMPT_AGENT=true)
    → User clicks 👍 or 👎 in macOS dialog
    → session_logger.log_user_feedback() stores result under event_type="user_feedback"
    → prompt_store.record_feedback() updates thumbs up/down on current version

Session ends → DORMANT state entered
    ↓
main.py DORMANT block (line ~2560):
    → session_logger.drain()              ← wait for all writes to flush
    → metaprompt_agent.run_if_eligible()  ← pre-flight checks, then evaluation
    ↓
Pre-flight checks (all must pass):
    1. ENABLE_METAPROMPT_AGENT=true
    2. metaprompt_dialog_active == False   (no dialog already open)
    3. user_resumed event NOT set          (user hasn't woken the session)
    4. Unprocessed feedback entries exist
    5. ≥ 15 tool calls AND ≥ 2 distinct session_ids in recent logs
    ↓
Evaluation:
    → Read last 5 JSONL session log files
    → Strip tool output payloads (security: removes adversarial web content)
    → Wrap feedback text in <user_feedback_data> delimiters (injection mitigation)
    → Build context: logs + feedback + ledger summary + contract + current prompts
    → AsyncOpenAI.chat.completions.create() with response_format={"type":"json_object"}
    ↓
Champion/Challenger decision:
    PROMOTE:  challenger_score > champion_score + 0.05 AND sample window met
    HOLD:     within ±0.05 OR window not yet met → no dialog, done
    ROLLBACK: challenger_score < champion_score - 0.10
    ↓
[If PROMOTE or ROLLBACK]:
    → Write staging file to prompts/.staging_<agent>_prompt.md
    → feedback_service.ask_approval() fires
    → macOS dialog shows FULL DIFF + proposal summary + staging file path
    → User clicks ✅ Approve or ❌ Deny (5-minute timeout → treated as Deny)
    ↓
On Approve:
    → prompt_store.deploy_new_version() — atomic write (same-dir temp + os.rename)
    → supervisor.reset_conversation()    — clears last_response_id so next turn is fresh
    → session_logger.log_metaprompt_decision(decision="approved")
    → Staging file deleted

On Deny / Timeout:
    → Optional denial reason logged
    → session_logger.log_metaprompt_decision(decision="denied"|"timed_out")
    → No file changes

Mark feedback entries as processed
Wake event → reconnect → new session loads updated prompt via build_runner()
```

---

## Prompt Version Scoring

Every prompt version accumulates a running score from user feedback.

```
version_score = (explicit_feedback_rate × 0.7) + (session_completion_rate × 0.3)
```

Where:
- `explicit_feedback_rate` = thumbs_up / (thumbs_up + thumbs_down)
- `session_completion_rate` = currently 1.0 (placeholder; will be updated as implicit
  signals are implemented)

A score is only computed when:
- `tool_call_count >= 15` AND
- `session_count >= 2` (distinct `session_id` values, NOT WebSocket reconnect events)

Data older than 14 days is not used for scoring comparisons (`is_stale()` check).

---

## Champion/Challenger States

| State | Condition | Action |
|---|---|---|
| **PROMOTE** | challenger_score > champion + 0.05 AND threshold met | Show approval dialog |
| **HOLD** | Within ±0.05 OR threshold not met | No action (silent) |
| **ROLLBACK** | challenger_score < champion − 0.10 | Show rollback dialog |

Version lineage is tracked via `parent_version_id` in `prompt_versions.json`. Every
approved change creates a new version entry (append-only; old versions are never deleted).

---

## Security Model

### Threat: Prompt Injection via Free-Text Feedback
**Mitigation:** All feedback text is wrapped in `<user_feedback_data>...</user_feedback_data>`
delimiters before LLM injection. The meta-agent system prompt explicitly instructs the model
to treat this block as DATA, not instructions.

### Threat: Prompt Injection via Tool Outputs in Logs
**Mitigation:** `_strip_tool_outputs()` removes `result`/`output` fields from `tool_end` and
`subagent_tool_dispatch` entries before the log excerpt is passed to the meta-agent. Only
`tool_name`, `success`, `duration_ms`, and `agent` are preserved.

### Threat: Meta-Agent Describing a Harmful Change as Benign
**Mitigation:** The approval dialog ALWAYS shows the full before/after diff, never just a
plain-English summary. The user must read the actual text change before approving.

### Threat: On-Disk Prompt Tampering
**Mitigation:** When `PROMPT_HMAC_KEY` is set, every prompt file is verified against an
HMAC-SHA256 hash stored in `prompt_versions.json` before loading. If the hash doesn't match,
the hardcoded fallback is used and the mismatch is logged.

### Threat: Corrupted Prompt Write (Power Loss / Disk Full)
**Mitigation:** `prompt_store.deploy_new_version()` writes to a `.tmp_` file in the same
directory first, then uses `os.rename()` which is atomic within a single filesystem partition.

---

## Configuration (.env)

```bash
# Enable the meta-agent (default: false — opt-in)
ENABLE_METAPROMPT_AGENT=true

# Model for the meta-agent LLM call (separate from SUPERVISOR_MODEL)
METAPROMPT_MODEL=gpt-4.1

# HMAC key for prompt file integrity checking (optional but recommended)
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
PROMPT_HMAC_KEY=your-random-hex-string-here
```

The feature is **off by default** (`ENABLE_METAPROMPT_AGENT=false`). The satisfaction
popup and all meta-agent evaluation are gated behind this flag, so there is zero user
experience impact when disabled.

---

## Local Ledger: prompt_versions.json

Auto-generated in the project root. Format:

```json
{
  "current_realtime_version_id": "v_realtime_a1b2c3d4",
  "current_supervisor_version_id": "v_supervisor_e5f6a7b8",
  "versions": [
    {
      "version_id": "v_realtime_a1b2c3d4",
      "agent": "realtime",
      "prompt_text": "...",
      "hmac_hex": "...",
      "parent_version_id": null,
      "deployed_at": 1744300000.0,
      "deployed_at_iso": "2026-04-10T10:00:00",
      "feedback_thumbs_up": 12,
      "feedback_thumbs_down": 2,
      "session_ids": ["session_abc", "session_def"],
      "tool_call_count": 47,
      "is_current": true,
      "is_rollback_target": false
    }
  ]
}
```

**Do not edit this file manually.** To roll back a prompt, approve a ROLLBACK proposal
from the meta-agent, or edit the `.md` file directly and restart (the new content will
register as a new initial version on the next `prompt_store.init()` call).

---

## Constraint Registry

The constraint registry is the meta-agent's **institutional memory** — a structured
store of feedback-derived behavioral rules that persist across sessions and prevent
prompt changes from undoing past fixes.

### Architecture

- **Source of truth:** `prompts/constraint_registry.json` (structured JSON, app-owned)
- **LLM interaction:** The meta-agent outputs discrete operations (`add_constraint`,
  `supersede_constraint`, `mark_resolved`); the application validates and applies them
  deterministically. The LLM never writes the registry directly.
- **Trust model:** Registry content is injected into the meta-agent as **delimited
  reference data** (`<constraint_registry_data>` tags), NOT as trusted instructions.
  This prevents the registry from becoming a persistent prompt-injection surface.
- **Contract separation:** The `agent_contract.md` file holds hard interface rules.
  The constraint registry holds only feedback-derived learnings and preferences.

### Constraint Schema

Each entry in `constraint_registry.json`:

```json
{
  "id": "RT-001",
  "agent": "realtime",
  "kind": "hard_constraint",
  "rule": "Never paraphrase proper nouns when escalating to Supervisor",
  "evidence_interaction_ids": ["int_a1b2", "int_c3d4"],
  "source": "metaprompt_proposal",
  "status": "active",
  "introduced_by_version": "v_realtime_a1b2c3d4",
  "introduced_by_proposal": "proposal_abc123",
  "superseded_by": null,
  "supersedes": null,
  "created_at": "2026-04-10T14:30:00",
  "last_reviewed_at": "2026-04-15T09:00:00"
}
```

### Constraint Kinds (Three Tiers)

| Kind | Meaning | Durability |
|---|---|---|
| `hard_constraint` | Behavioral rule the user explicitly corrected. Violating it = regression. | High — requires explicit override with evidence |
| `preference` | User expressed a preference but not a hard rule | Medium — can be adjusted with newer conflicting feedback |
| `observation` | Meta-agent's own inference from log analysis | Low — can be superseded silently |

**Kind assignment policy:** The meta-agent defaults new constraints to `preference`.
It may propose `hard_constraint` only when the user's feedback contains absolute
language ("always", "never", "must", "don't ever"). The user can manually promote
any constraint by editing the registry directly.

### Operations

The meta-agent outputs constraint operations as structured JSON, not raw text:

| Operation | Effect | Validation |
|---|---|---|
| `add_constraint` | Creates a new active entry | Requires valid agent, kind, non-empty rule, matching version in version_map |
| `supersede_constraint` | Marks target as "superseded" | Target must exist and be active |
| `mark_resolved` | Marks target as "resolved" | Target must exist and be active |

Invalid operations are logged and skipped (non-fatal).

### Seed File (Manual Bootstrap)

On first `constraint_registry.init()`, if `prompts/constraint_seed.md` exists and the
registry is empty, the seed file is parsed into initial constraints:

```markdown
# Initial Constraints

## realtime hard_constraint
Never paraphrase proper nouns (deck names, app names) when escalating.

## supervisor preference
Keep JSON responses compact.
```

Format: `## {agent} {kind}` header followed by rule text on the next line(s).
The seed file is renamed to `constraint_seed.md.applied` after processing.

### Editing Constraints Manually

You can edit `prompts/constraint_registry.json` directly. Changes are authoritative
immediately — the meta-agent reads whatever is on disk at the start of its next run.
No approval is needed for user-initiated edits (the user is the authority).

### Schema Versioning

The registry includes `schema_version` and a migration path from day one:
- Current version: 1
- Files without `schema_version` are auto-migrated to v1
- Loader rejects files with a version newer than supported

---

## Batch Prompt Deployment

Multi-agent prompt proposals are deployed via `prompt_store.deploy_batch()` with
all-or-nothing semantics:

1. Write all temp files (no renames yet)
2. Validate all temp files exist and are non-empty
3. Atomic rename each temp → target
4. Update in-memory state (only after ALL renames succeed)
5. Save ledger once

If any step fails before all renames complete, all temp files are cleaned up and
no changes are applied. The constraint registry is only updated after successful
prompt deployment — never independently.

---

## Session Log Events Added

The following `event_type` values appear in JSONL session logs:

| event_type | When logged | Key fields |
|---|---|---|
| `user_feedback` | After each escalation (if feature enabled) | `interaction_id`, `rating` (thumbs_up/down), `text`, `prompt_version`, `processed` |
| `metaprompt_proposal` | When meta-agent produces a PROMOTE/ROLLBACK decision | `proposal_id`, `decision_state`, `before_preview`, `after_preview`, `reasoning`, `scores`, `constraint_operations`, `contradicts_constraints` |
| `metaprompt_decision` | After user approves/denies/times out | `proposal_id`, `decision` (approved/denied/skipped/deploy_failed), `reason_text`, `new_version_id`, `timed_out`, `constraint_ids_affected` |
| `metaprompt_skip` | When meta-agent aborts early | `reason` (e.g., `no_unprocessed_feedback`, `insufficient_tool_calls`) |
| `feedback_processed` | After a meta-agent run marks feedback as consumed | `processed_interaction_ids` |

---

## Editing Prompts Manually

You can edit `prompts/realtime_prompt.md` and `prompts/supervisor_prompt.md` directly
in a text editor. On the next startup, `prompt_store.init()` will detect the new content
(different HMAC), register it as a new initial version, and load it.

**Template variables in `realtime_prompt.md`:**
- `{user_name}` — replaced with `USER_NAME` env var at load time
- `{user_context}` — replaced with `USER_CONTEXT` env var at load time

`supervisor_prompt.md` has no template variables.

`agent_contract.md` is read-only reference text for the meta-agent. Edit it to document
escalation rule changes, but be aware that the meta-agent treats it as authoritative when
attributing routing failures.

---

## Interaction with Other Modules

| Module | Change |
|---|---|
| `main.py` | `ListenState.last_turn_had_escalation` (bool) and `last_escalation_interaction_id` (str\|None) added; `AppRuntimeState.metaprompt_dialog_active` (bool) and `user_resumed` (asyncio.Event) added; `prompt_store.init()` + `constraint_registry.init()` called at startup before `SupervisorAgent`; meta-agent trigger in DORMANT block |
| `supervisor.py` | `_active_instructions` loaded from `prompt_store` with class-constant fallback; `reset_conversation()` method added; `metadata={"prompt_version": ...}` tagged on every `responses.create()` call |
| `session_logger.py` | New methods: `log_user_feedback()`, `log_metaprompt_proposal()`, `log_metaprompt_decision()`, `drain()`; writer loop now calls `queue.task_done()` so `drain()` / `queue.join()` works correctly; proposal/decision logs include constraint operation audit fields |
| `prompt_store.py` | `deploy_batch()` method for all-or-nothing multi-agent deployment |
| `metaprompt_agent.py` | Fixed feedback consumption bug; constraint registry integration; `deploy_batch()` replaces per-agent loop; constraint staging in approval flow |
| `feedback_service.py` | `ask_approval()` now accepts `staging_paths: list[str]` instead of `staging_file_path: str` |
| `constraint_registry.py` | **New module** — constraint CRUD, validation, migration, summaries, persistence |

---

## Disabling or Removing the Feature

1. Set `ENABLE_METAPROMPT_AGENT=false` (or leave unset) — all meta-agent code paths are
   gated behind this flag and become no-ops.
2. The `ListenState` and `AppRuntimeState` fields added are zero-cost when unused.
3. The `prompt_store.init()` call at startup is safe regardless of whether the feature is
   enabled; it simply loads prompts from files (or falls back to hardcoded strings) and is
   a net improvement even without the meta-agent.

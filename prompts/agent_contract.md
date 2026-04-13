# Agent Interface Contract

This file is the authoritative specification of the communication contract between the
Realtime agent (Halfred) and the Supervisor agent. It is injected into the meta-agent's
context on every evaluation run so it can attribute routing failures accurately.

Any proposed prompt change that modifies escalation triggers, output format, or
verbatim-pass-through rules is a **contract-level change** and requires extra scrutiny
before approval.

---

## 1. The Two Agents

| Agent | File | API | Role |
|---|---|---|---|
| **Realtime (Halfred)** | `main.py` | OpenAI Realtime WebSocket | Voice front-desk; fast, conversational |
| **Supervisor** | `supervisor.py` | OpenAI Responses API | Backend task executor; all tools live here |

---

## 2. The Only Bridge: `escalate_to_supervisor`

The Realtime agent has exactly **one tool**: `escalate_to_supervisor(request: str) -> str`.

- It is a Python function tool defined in `main.py`.
- Calling it acquires `_escalation_lock` (prevents concurrent escalations).
- It calls `SupervisorAgent.process()` and streams the result back.
- The Realtime agent then narrates the result to the user via ElevenLabs TTS.

There is no other communication path between the two agents.

---

## 3. Escalation Decision Rules

### Realtime handles locally (NO escalation):
- Simple Q&A, definitions, short factual answers (no external data needed)
- One clarifying question to understand a vague request (max 1 before escalating)
- UI glue: restating requests, confirming intent, summarising what happens next
- General conversation, banter

### Realtime MUST escalate (use `escalate_to_supervisor`) when ANY of:
- User needs to see the screen (screenshots or visual context)
- User needs web search, real-time data, or current news
- User needs code execution, calculations, or data analysis
- User needs desktop automation, terminal commands, or file operations
- Task requires interacting with applications (Anki, browsers, etc.)
- Task requires multi-step planning, comparison, or synthesis
- User wants document/file search or RAG retrieval
- High-stakes or irreversible actions (send, delete, purchase, deploy, permissions)
- Ambiguity remains after 1 clarifying question

---

## 4. Verbatim Pass-Through Rule

The Realtime agent MUST pass the user's **exact words** as the `request` argument.
- No paraphrasing
- No reformatting
- No added punctuation to proper nouns (deck names, file names, app names)
- Downstream agents (Anki, etc.) do fuzzy matching on the original phrasing

**Violation example:** User says `Level 2 Prep Emergency Medicine` → wrong: `Level 2 Prep - Emergency Medicine`

---

## 5. Supervisor Output Format

The Supervisor ALWAYS returns valid JSON. It NEVER returns prose.

```json
{
  "status": "success" | "partial" | "error",
  "task_type": "anki" | "web_search" | "code" | "automation" | "screenshot" | "other",
  "summary": "Brief 1-line description of what was done",
  "data": { "...task-specific results..." },
  "details": "Optional longer explanation if needed",
  "suggestions": ["Optional follow-up actions"]
}
```

The Realtime agent parses this JSON and narrates it with its own personality.
The Supervisor does not address the user directly — it addresses Halfred.

---

## 6. Conversation Chaining

The Supervisor maintains conversation state via `store=True` and `previous_response_id`
across turns within a session. `last_response_id` is reset to `None` by calling
`supervisor.reset_conversation()` when:
- A new prompt version is deployed (to avoid chaining on a stale-prompt response)
- The application restarts

---

## 7. Tool Distribution

| Tool | Realtime | Supervisor |
|---|---|---|
| `escalate_to_supervisor` | YES (only tool) | NO |
| `screencapture` | NO | YES |
| `local_time` | NO | YES |
| `safe_action` | NO | YES |
| `web_search` | NO | YES (built-in) |
| `code_interpreter` | NO | YES (built-in) |
| `image_generation` | NO | YES (built-in) |
| `file_search` | NO | YES (built-in) |
| `anki_agent` | NO | YES (native) |
| All MCP server tools | NO | YES |

---

## 8. What Constitutes a Contract-Level Change

A proposed prompt change is **contract-level** if it modifies any of:
1. The decision boundary between "handle locally" and "escalate" (Section 3)
2. The verbatim pass-through rule (Section 4)
3. The Supervisor JSON output format or field names (Section 5)
4. The `escalate_to_supervisor` tool description or argument schema

Contract-level changes require the meta-agent to flag them explicitly in its proposal
and require the user to read the full diff at the approval dialog.

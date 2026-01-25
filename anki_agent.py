import json
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from anki_connect import (
    anki_invoke, AnkiConnectError, change_deck, find_cards, unsuspend_cards, are_suspended,
    gui_browse, gui_add_cards, gui_current_card, gui_deck_review
)

load_dotenv()


# -----------------------------
# 1) SYSTEM prompt (Anki rules)
# -----------------------------
SYSTEM = """
You are an Anki agent controlling Anki via AnkiConnect tools.
You are called by the Supervisor agent, not directly by the user.

# Output Format - CRITICAL
Always respond with valid JSON. Do NOT write prose or conversational text.
Your output will be processed by the Supervisor agent.

Return JSON with this structure:
{
  "status": "success" | "partial" | "error" | "needs_info",
  "action": "list_decks" | "create_card" | "find_cards" | "browse" | "review" | "add_cards" | "other",
  "summary": "Brief 1-line description of what was done or what info is needed",
  "data": { ... action-specific results ... },
  "details": "Optional longer explanation if needed",
  "missing_params": ["param1", "param2"]  // Only for needs_info status
}

Examples:
- List decks: {"status":"success","action":"list_decks","summary":"Found 15 decks","data":{"decks":["Default","Biology","..."],"count":15}}
- Create card: {"status":"success","action":"create_card","summary":"Created cloze card in Biology deck","data":{"note_id":12345,"deck":"Biology"}}
- Browse: {"status":"success","action":"browse","summary":"Opened browser with 42 cards","data":{"card_ids":[...],"count":42}}
- Error: {"status":"error","action":"create_card","summary":"Deck not found","data":{},"details":"Could not find deck 'Biologgy'. Did you mean 'Biology'?"}
- Missing info: {"status":"needs_info","action":"add_cards","summary":"Need deck and card content to open Add Cards","missing_params":["deck","fields"],"details":"Which deck should I open Add Cards for, and what content should I pre-fill?"}

# Critical Rule: Ask for Missing Required Parameters
When the user's request requires parameters that weren't provided, DO NOT guess or make up values.
Instead, return status "needs_info" with the missing_params field listing what you need.

Examples of when to ask:
- "Create a flashcard" → needs deck, text content
- "Start reviewing" → needs deck name (which deck to review?)
- "Find notes matching X" → needs search query

Examples of when NOT to ask (just do it):
- "Open Anki browser" / "Open browser window" → call anki_gui_browse with no query (shows all cards)
- "Open Add Cards dialog" → call anki_gui_add_cards with defaults (user will fill in details in GUI)

# Hard Rules
- Create CLOZE cards only (modelName: "Cloze"; fields: Text, Extra).
- Cloze syntax must be valid: {{c1::deletion}} and optionally {{c1::deletion::hint}}.
- If the user doesn't specify a deck AND there's no recent deck in session, ASK which deck.
- Prefer not to create duplicates (allow_duplicate=false unless user explicitly asks).
- NEVER pretend an action succeeded if you didn't actually call a tool for it.

# Deck Name Fuzzy Matching - IMPORTANT
When the user gives a deck name, FIRST call anki_list_decks to see all available decks.
Then find the best match - the user's speech may have:
- Missing punctuation: "Level 2 Prep Emergency Medicine" → "Level 2 Prep::Emergency Medicine"
- Different separators: "Level 2 Prep - Emergency Medicine" → "Level 2 Prep::Emergency Medicine"
- Abbreviations or slight variations

If exact match not found but a close match exists (same words, different separators), USE THE CLOSE MATCH.
Only ask for clarification if multiple equally-good matches exist or no reasonable match found.
"""


# -----------------------------
# 2) Tool wrappers (AnkiConnect)
# -----------------------------
def deck_names() -> List[str]:
    return anki_invoke("deckNames")


def ensure_deck(deck: str) -> None:
    """Create deck if it doesn't exist (supports nested decks like 'Parent::Child')."""
    anki_invoke("createDeck", {"deck": deck})


def add_cloze_note(
    deck: str,
    text: str,
    extra: str = "",
    tags: Optional[List[str]] = None,
    allow_duplicate: bool = False,
) -> int:
    note = {
        "deckName": deck,
        "modelName": "Cloze",
        "fields": {"Text": text, "Extra": extra},
        "tags": tags or [],
        "options": {
            "allowDuplicate": allow_duplicate,
            "duplicateScope": "deck",
            "duplicateScopeOptions": {
                "deckName": deck,
                "checkChildren": False,
                "checkAllModels": False,
            },
        },
    }
    return anki_invoke("addNote", {"note": note})


def find_notes(query: str) -> List[int]:
    return anki_invoke("findNotes", {"query": query})


def notes_info(note_ids: List[int]) -> List[dict]:
    return anki_invoke("notesInfo", {"notes": note_ids})


def add_tags(note_ids: List[int], tags: List[str]) -> None:
    anki_invoke("addTags", {"notes": note_ids, "tags": " ".join(tags)})


def update_note_fields(note_id: int, fields: Dict[str, str]) -> None:
    anki_invoke("updateNoteFields", {"note": {"id": note_id, "fields": fields}})


# -----------------------------
# 3) TOOLS definition (Anki actions)
# -----------------------------
TOOLS = [
    {
        "type": "function",
        "name": "anki_list_decks",
        "description": "List all Anki deck names.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "anki_create_deck",
        "description": "Create an Anki deck (supports nested decks like 'Parent::Child').",
        "parameters": {
            "type": "object",
            "properties": {"deck": {"type": "string"}},
            "required": ["deck"],
        },
    },
    {
        "type": "function",
        "name": "anki_add_cloze",
        "description": (
            "Add a Cloze note to a deck. 'text' must contain cloze deletions like "
            "{{c1::deletion}}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deck": {"type": "string", "description": "Target deck name."},
                "text": {"type": "string", "description": "Cloze text containing {{cN::...}}."},
                "extra": {"type": "string", "description": "Optional Extra field."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "allow_duplicate": {"type": "boolean"},
            },
            "required": ["deck", "text"],
        },
    },
    {
        "type": "function",
        "name": "anki_find_notes",
        "description": "Find note IDs using an Anki search query (e.g., deck:Neuro 'Broca').",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "anki_notes_info",
        "description": "Fetch note info for note IDs (fields, tags, etc.).",
        "parameters": {
            "type": "object",
            "properties": {"note_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["note_ids"],
        },
    },
    {
        "type": "function",
        "name": "anki_add_tags",
        "description": "Add tags to existing notes.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_ids": {"type": "array", "items": {"type": "integer"}},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["note_ids", "tags"],
        },
    },
    {
        "type": "function",
        "name": "anki_update_note_fields",
        "description": "Update fields of a note (for Cloze notes: Text and/or Extra).",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer"},
                "fields": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["note_id", "fields"],
        },
    },
    {
        "type": "function",
        "name": "anki_change_deck",
        "description": (
            "Move cards to a different deck. Provide either card_ids directly, or a query "
            "to find cards (e.g., 'deck:OldDeck' or 'tag:mytag'). The destination deck will "
            "be created if it doesn't exist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "deck": {"type": "string", "description": "Destination deck name."},
                "card_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Card IDs to move. Use this OR query, not both.",
                },
                "query": {
                    "type": "string",
                    "description": "Anki search query to find cards to move (e.g., 'deck:Source tag:move').",
                },
            },
            "required": ["deck"],
        },
    },
    {
        "type": "function",
        "name": "anki_unsuspend",
        "description": (
            "Unsuspend cards. Provide either card_ids directly, or a query to find cards. "
            "Returns whether any cards were previously suspended."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "card_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Card IDs to unsuspend. Use this OR query, not both.",
                },
                "query": {
                    "type": "string",
                    "description": "Anki search query to find cards to unsuspend (e.g., 'is:suspended deck:MyDeck').",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "anki_are_suspended",
        "description": "Check if cards are suspended. Returns suspension status for each card ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "card_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Card IDs to check.",
                },
                "query": {
                    "type": "string",
                    "description": "Anki search query to find cards to check (e.g., 'deck:MyDeck').",
                },
            },
        },
    },
    {
        "type": "function",
        "name": "anki_gui_browse",
        "description": "Open Anki's card browser. Can be called with no query to just open the browser showing all cards, or with a search query to filter results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Anki search query. Use '*' or omit to show all cards. Examples: 'deck:MyDeck', 'tag:important', 'is:due'.",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "anki_gui_add_cards",
        "description": "Open Anki's Add Cards dialog. Can be called with no parameters to just open the empty dialog, or with preset values to pre-fill fields.",
        "parameters": {
            "type": "object",
            "properties": {
                "deck": {"type": "string", "description": "Target deck name. Defaults to 'Default' if not specified."},
                "model": {"type": "string", "description": "Note model (e.g., 'Cloze', 'Basic'). Defaults to 'Basic' if not specified."},
                "fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Field values as key-value pairs. Leave empty to open blank dialog.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to add to the note.",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "anki_gui_current_card",
        "description": "Get information about the card currently being reviewed. Returns null if not in review.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "anki_gui_deck_review",
        "description": "Open a deck for review in Anki.",
        "parameters": {
            "type": "object",
            "properties": {
                "deck": {"type": "string", "description": "Deck name to start reviewing."},
            },
            "required": ["deck"],
        },
    },
]


# -----------------------------
# Helpers: tool-call extraction and cloze validation
# -----------------------------
_CLOZE_RE = re.compile(r"\{\{c\d+::")

def looks_like_cloze(text: str) -> bool:
    return bool(_CLOZE_RE.search(text or ""))


def iter_tool_calls(resp: Any):
    """
    Yields items that look like tool calls from the Responses API output.
    Supports minor SDK variations by checking common attributes.
    """
    output = getattr(resp, "output", None) or []
    for item in output:
        item_type = getattr(item, "type", None)
        # Most common: "tool_call". Some SDKs may label function calls differently.
        if item_type in ("tool_call", "function_call"):
            yield item


# -----------------------------
# 4) Tool dispatcher (calls anki_connect.py)
# -----------------------------
def dispatch_tool(name: str, args: Dict[str, Any]) -> Any:
    if name == "anki_list_decks":
        return {"decks": deck_names()}

    if name == "anki_create_deck":
        ensure_deck(args["deck"])
        return {"ok": True, "deck": args["deck"]}

    if name == "anki_add_cloze":
        ensure_deck(args["deck"])
        note_id = add_cloze_note(
            deck=args["deck"],
            text=args["text"],
            extra=args.get("extra", ""),
            tags=args.get("tags", []),
            allow_duplicate=bool(args.get("allow_duplicate", False)),
        )
        return {"ok": True, "note_id": note_id}

    if name == "anki_find_notes":
        return {"note_ids": find_notes(args["query"])}

    if name == "anki_notes_info":
        return {"notes": notes_info(args["note_ids"])}

    if name == "anki_add_tags":
        add_tags(args["note_ids"], args["tags"])
        return {"ok": True}

    if name == "anki_update_note_fields":
        update_note_fields(args["note_id"], args["fields"])
        return {"ok": True}

    if name == "anki_change_deck":
        card_ids = args.get("card_ids")
        query = args.get("query")
        if not card_ids and not query:
            return {"error": "Provide either card_ids or query to specify which cards to move."}
        if card_ids and query:
            return {"error": "Provide either card_ids or query, not both."}
        if query:
            card_ids = find_cards(query)
            if not card_ids:
                return {"error": f"No cards found for query: {query}"}
        change_deck(card_ids, args["deck"])
        return {"ok": True, "cards_moved": len(card_ids), "destination": args["deck"]}

    if name == "anki_unsuspend":
        card_ids = args.get("card_ids")
        query = args.get("query")
        if not card_ids and not query:
            return {"error": "Provide either card_ids or query to specify which cards to unsuspend."}
        if card_ids and query:
            return {"error": "Provide either card_ids or query, not both."}
        if query:
            card_ids = find_cards(query)
            if not card_ids:
                return {"error": f"No cards found for query: {query}"}
        result = unsuspend_cards(card_ids)
        return {"ok": True, "cards_unsuspended": len(card_ids), "any_were_suspended": result}

    if name == "anki_are_suspended":
        card_ids = args.get("card_ids")
        query = args.get("query")
        if not card_ids and not query:
            return {"error": "Provide either card_ids or query to specify which cards to check."}
        if card_ids and query:
            return {"error": "Provide either card_ids or query, not both."}
        if query:
            card_ids = find_cards(query)
            if not card_ids:
                return {"error": f"No cards found for query: {query}"}
        statuses = are_suspended(card_ids)
        return {"card_ids": card_ids, "suspended": statuses}

    if name == "anki_gui_browse":
        # Default to "*" to show all cards if no query provided
        query = args.get("query", "*") or "*"
        card_ids = gui_browse(query, None)
        return {"ok": True, "card_ids": card_ids, "count": len(card_ids), "query": query}

    if name == "anki_gui_add_cards":
        # Use defaults if parameters not provided (allows just opening the dialog)
        deck = args.get("deck", "Default")
        model = args.get("model", "AnKingOverhaul")
        fields = args.get("fields", {"Text": "", "Extra": ""})

        note = {
            "deckName": deck,
            "modelName": model,
            "fields": fields,
            "tags": args.get("tags", []),
        }
        note_id = gui_add_cards(note)
        return {"ok": True, "note_id": note_id, "deck": deck, "model": model}

    if name == "anki_gui_current_card":
        card_info = gui_current_card()
        if card_info is None:
            return {"reviewing": False, "card": None}
        return {"reviewing": True, "card": card_info}

    if name == "anki_gui_deck_review":
        success = gui_deck_review(args["deck"])
        return {"ok": success, "deck": args["deck"]}

    return {"error": f"Unknown tool: {name}"}


# -----------------------------
# 5) AnkiSubagent class for supervisor integration
# -----------------------------
class AnkiSubagent:
    """
    Anki subagent that can be called by the Supervisor.

    Maintains state across calls (last_deck, last_note_ids) and handles
    the full agentic loop internally.
    """

    def __init__(self, model: str = "gpt-4.1-mini"):
        self.client = OpenAI()
        self.model = model
        self.state: Dict[str, Any] = {
            "last_deck": None,
            "last_note_ids": [],
        }
        self.messages: List[Dict[str, str]] = []

    def _run_turn(self, user_message: str) -> str:
        """Execute a single agent turn with tool calls."""
        import time
        from session_logger import (
            log_llm_call_sync, log_llm_response_sync, log_tool_dispatch_sync
        )

        print(f"[anki_agent] Received: {user_message[:100]}...")
        self.messages.append({"role": "user", "content": user_message})

        # Log the LLM call
        llm_start = time.time()
        log_llm_call_sync(
            agent="anki_agent",
            model=self.model,
            input_messages=self.messages,
            tools=[t["name"] for t in TOOLS],
        )

        resp = self.client.responses.create(
            model=self.model,
            input=self.messages,
            tools=TOOLS,
            instructions=SYSTEM,
        )

        tool_calls = list(iter_tool_calls(resp))

        # Log the LLM response
        llm_duration = (time.time() - llm_start) * 1000
        log_llm_response_sync(
            agent="anki_agent",
            model=self.model,
            response_text=resp.output_text if not tool_calls else None,
            tool_calls=[{"name": c.name, "arguments": c.arguments} for c in tool_calls] if tool_calls else None,
            duration_ms=llm_duration,
        )

        print(f"[anki_agent] Tool calls: {len(tool_calls)} | Text output: {bool(resp.output_text)}")
        if not tool_calls:
            reply = resp.output_text
            print(f"[anki_agent] NO TOOLS CALLED - returning text: {reply[:100]}...")
            self.messages.append({"role": "assistant", "content": reply})
            return reply

        # Agentic loop: keep executing tools until the LLM stops requesting them
        max_iterations = 10  # Safety limit to prevent infinite loops
        iteration = 0
        current_resp = resp
        current_tool_calls = tool_calls

        while current_tool_calls and iteration < max_iterations:
            iteration += 1
            print(f"[anki_agent] === Iteration {iteration} ===")
            print(f"[anki_agent] Calling tools: {[c.name for c in current_tool_calls]}")

            # Execute tool calls and send results back
            tool_messages: List[Dict[str, str]] = []
            for call in current_tool_calls:
                tool_name = call.name
                raw_args = call.arguments
                args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                print(f"[anki_agent] Executing tool: {tool_name} with args: {args}")

                # Memory read: if the tool is add_cloze and deck is missing, inject last_deck
                if tool_name == "anki_add_cloze" and not args.get("deck") and self.state.get("last_deck"):
                    args["deck"] = self.state["last_deck"]

                # Guardrail: ensure cloze syntax if adding cloze
                tool_start = time.time()
                if tool_name == "anki_add_cloze" and not looks_like_cloze(args.get("text", "")):
                    result = {"error": "Cloze text must include {{c1::...}} syntax. Please generate valid cloze deletions."}
                    success = False
                else:
                    try:
                        result = dispatch_tool(tool_name, args)
                        success = "error" not in result if isinstance(result, dict) else True
                        print(f"[anki_agent] Tool result: {str(result)[:200]}...")
                    except AnkiConnectError as e:
                        result = {"error": str(e)}
                        success = False
                        print(f"[anki_agent] Tool ERROR: {e}")

                # Log the tool dispatch
                tool_duration = (time.time() - tool_start) * 1000
                log_tool_dispatch_sync(
                    agent="anki_agent",
                    tool_name=tool_name,
                    arguments=args,
                    result=result,
                    success=success,
                    duration_ms=tool_duration,
                )

                # Memory write: track last_deck and last_note_ids
                if tool_name == "anki_add_cloze" and args.get("deck"):
                    self.state["last_deck"] = args["deck"]
                if tool_name == "anki_add_cloze" and isinstance(result, dict) and result.get("note_id"):
                    self.state["last_note_ids"] = [result["note_id"]]

                tool_messages.append({
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                })

            # Log the follow-up LLM call
            follow_start = time.time()
            log_llm_call_sync(
                agent="anki_agent",
                model=self.model,
                input_messages=tool_messages,
                tools=[t["name"] for t in TOOLS],
                metadata={"type": "follow_up", "previous_response_id": current_resp.id, "iteration": iteration}
            )

            # Continue after tools using previous_response_id to chain the conversation
            follow = self.client.responses.create(
                model=self.model,
                previous_response_id=current_resp.id,
                input=tool_messages,
                tools=TOOLS,
            )

            # Check if the follow-up response contains more tool calls
            current_tool_calls = list(iter_tool_calls(follow))
            follow_duration = (time.time() - follow_start) * 1000

            # Log the follow-up response
            log_llm_response_sync(
                agent="anki_agent",
                model=self.model,
                response_text=follow.output_text if not current_tool_calls else None,
                tool_calls=[{"name": c.name, "arguments": c.arguments} for c in current_tool_calls] if current_tool_calls else None,
                duration_ms=follow_duration,
            )

            print(f"[anki_agent] Follow-up has {len(current_tool_calls)} tool calls | Text: {bool(follow.output_text)}")

            # Update for next iteration
            current_resp = follow

        if iteration >= max_iterations:
            print(f"[anki_agent] WARNING: Hit max iterations ({max_iterations}), forcing exit")

        reply = current_resp.output_text or '{"status":"error","action":"unknown","summary":"Agent loop ended without text output"}'
        print(f"[anki_agent] Final response: {reply[:150]}...")
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def process(self, task: str) -> str:
        """
        Process an Anki-related task from the supervisor.

        Args:
            task: The task description (e.g., "Create a flashcard about...")

        Returns:
            The agent's response after completing the task.
        """
        return self._run_turn(task)

    def reset(self):
        """Reset conversation history (keeps state like last_deck)."""
        self.messages = []

    def full_reset(self):
        """Reset both conversation history and state."""
        self.messages = []
        self.state = {
            "last_deck": None,
            "last_note_ids": [],
        }


# -----------------------------
# 6) Standalone CLI (for direct use)
# -----------------------------
def main():
    agent = AnkiSubagent()

    print("Anki agent ready. Anki must be open with AnkiConnect installed. Ctrl+C to quit.")
    while True:
        try:
            user = input("\n> ").strip()
            if not user:
                continue

            reply = agent.process(user)
            print(reply)

        except KeyboardInterrupt:
            print("\nExiting. Try not to make 400 cards in a caffeine frenzy.")
            break


if __name__ == "__main__":
    main()

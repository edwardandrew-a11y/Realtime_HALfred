import requests

ANKI_CONNECT_URL = "http://127.0.0.1:8765"

class AnkiConnectError(RuntimeError):
    pass

def anki_invoke(action: str, params: dict | None = None, version: int = 6):
    """Call AnkiConnect API."""
    payload = {
        "action": action,
        "version": version,
        "params": params or {}
    }

    try:
        r = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise AnkiConnectError(
            f"Failed to reach AnkiConnect at {ANKI_CONNECT_URL}. "
            f"Is Anki open and AnkiConnect installed? ({e})"
        )

    if "error" not in data or "result" not in data:
        raise AnkiConnectError(f"Malformed AnkiConnect response: {data}")

    if data["error"] is not None:
        raise AnkiConnectError(f"AnkiConnect error for action '{action}': {data['error']}")

    return data["result"]


def change_deck(card_ids: list[int], deck: str) -> None:
    """Move cards to a different deck, creating the deck if it doesn't exist."""
    anki_invoke("changeDeck", {"cards": card_ids, "deck": deck})


def find_cards(query: str) -> list[int]:
    """Find card IDs using an Anki search query."""
    return anki_invoke("findCards", {"query": query})


def unsuspend_cards(card_ids: list[int]) -> bool:
    """Unsuspend cards. Returns True if any card was previously suspended."""
    return anki_invoke("unsuspend", {"cards": card_ids})


def are_suspended(card_ids: list[int]) -> list[bool | None]:
    """Check suspension status of cards. Returns list of bools (None for non-existent cards)."""
    return anki_invoke("areSuspended", {"cards": card_ids})


def gui_browse(query: str, reorder_cards: dict | None = None) -> list[int]:
    """Open the card browser with a search query. Returns matching card IDs."""
    params = {"query": query}
    if reorder_cards:
        params["reorderCards"] = reorder_cards
    return anki_invoke("guiBrowse", params)


def gui_add_cards(note: dict) -> int:
    """Open the Add Cards dialog with preset values. Returns note ID if user confirms."""
    return anki_invoke("guiAddCards", {"note": note})


def gui_current_card() -> dict | None:
    """Get info about the card currently being reviewed. Returns None if not reviewing."""
    return anki_invoke("guiCurrentCard")


def gui_deck_review(deck_name: str) -> bool:
    """Open a deck for review. Returns True if successful."""
    return anki_invoke("guiDeckReview", {"name": deck_name})
"""Conversation history for Insight Copilot.

Unlike the dashboard — which persists a *spec* and recomputes values on every open — a
conversation is a **record of what was said**, so turns are stored verbatim, numbers and
all. Reopening an old thread shows what the answer was at the time, not what it would be
today. That distinction matters for an internal analytics tool: a decision was made on the
strength of a specific number, and the transcript is the audit trail for it.
"""

import json
import os
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

STORE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "conversations.json"
)
TITLE_MAX = 42


def _read_all() -> dict:
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_all(data: dict) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        # `default=str` is a deliberate safety net: an answer payload gaining a date or
        # any other exotic type must never take down the app mid-conversation.
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, STORE_PATH)


def list_conversations(user_key: str) -> List[dict]:
    """Most-recently-updated first, which is the order a history list wants."""
    convs = _read_all().get(user_key, {})
    return sorted(convs.values(), key=lambda c: c.get("updated", ""), reverse=True)


def get_turns(user_key: str, conv_id: Optional[str]) -> List[Tuple[str, dict]]:
    if not conv_id:
        return []
    conv = _read_all().get(user_key, {}).get(conv_id)
    if not conv:
        return []
    return [(t["question"], t["answer"]) for t in conv.get("turns", [])]


def create(user_key: str, first_question: str) -> str:
    conv_id = uuid.uuid4().hex[:12]
    title = first_question.strip()
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rstrip() + "…"

    data = _read_all()
    data.setdefault(user_key, {})[conv_id] = {
        "id": conv_id,
        "title": title,
        "created": datetime.now().isoformat(timespec="seconds"),
        "updated": datetime.now().isoformat(timespec="seconds"),
        "turns": [],
    }
    _write_all(data)
    return conv_id


def append_turn(user_key: str, conv_id: str, question: str, answer: dict) -> None:
    data = _read_all()
    conv = data.get(user_key, {}).get(conv_id)
    if conv is None:
        return
    conv["turns"].append(
        {
            "question": question,
            "answer": answer,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    conv["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_all(data)


def delete(user_key: str, conv_id: str) -> None:
    data = _read_all()
    data.get(user_key, {}).pop(conv_id, None)
    _write_all(data)


def reset(user_key: str) -> None:
    data = _read_all()
    data.pop(user_key, None)
    _write_all(data)

"""Answer-level feedback from the people who asked the question.

The thumbs under an answer are the cheapest signal this product gets, and the only one
that comes from the person who actually needed the answer. This module keeps that signal
— and, more importantly, shapes it into work. Ratings are stored per turn, but the analyst
never reads them one at a time: `queue_items` groups them **by question**, because one bad
answer served to twenty people is one fix, not twenty tickets.

Same file-backed pattern as `chat_store` and `dashboard_store`. The interface, not the
JSON file, is the seam where a real event store would go.
"""

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from typing import List, Optional

STORE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "feedback.json"
)

# Mirrors `analyst_data.LOW_RATED` — the outcome pill the queue renders for these rows.
OUTCOME = "thumbs down"

# The reasons are *this product's* failure taxonomy, not a generic "bad response" list.
# Each one names a different owner, which is the entire point of asking: a definition
# complaint is an analyst's job, a cause complaint is a prompt or tool fix, a missing
# metric is semantic-layer work. Declaration order is severity order, and ties in the
# tally below break toward the earlier entry.
REASONS = {
    "Wrong number": {
        "suggested": "Investigate the query",
        "severity": "high",
        "route": "the query and the tables under it",
    },
    "Wrong metric definition": {
        "suggested": "Certify the definition",
        "severity": "high",
        "route": "the metric owner",
    },
    "Claimed a cause it can't support": {
        "suggested": "Review the evidence tier",
        "severity": "high",
        "route": "the evidence ladder",
    },
    "Missing metric or data": {
        "suggested": "Define a new metric",
        "severity": "high",
        "route": "the semantic layer",
    },
    "Didn't answer the question": {
        "suggested": "Improve answer quality",
        "severity": "medium",
        "route": "routing — a prompt or tool fix",
    },
    "Too vague to act on": {
        "suggested": "Improve answer quality",
        "severity": "low",
        "route": "narration",
    },
}

# A grouped row is escalated once this many people have rated the same question down —
# at that point it is a pattern, whatever any individual reason said.
_ESCALATE_AT = 3


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
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, STORE_PATH)


def _turn_key(conv_id: str, turn: int) -> str:
    return f"{conv_id}:{turn}"


def _norm(question: str) -> str:
    """Group key. Case, spacing and trailing punctuation should not split a row."""
    return re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.! ")


# --- Reading and writing one rating --------------------------------------------------

def get(user_key: str, conv_id: Optional[str], turn: int) -> Optional[dict]:
    if not conv_id:
        return None
    return _read_all().get(user_key, {}).get(_turn_key(conv_id, turn))


def rate(user_key: str, conv_id: str, turn: int, rating: str, context: dict = None) -> None:
    """Record 👍/👎 for one turn, replacing whatever was there before."""
    data = _read_all()
    turns = data.setdefault(user_key, {})
    prev = turns.get(_turn_key(conv_id, turn), {})

    record = dict(context or {})
    record["rating"] = rating
    record["rated_at"] = datetime.now().isoformat(timespec="seconds")
    # Detail belongs to the rating it was given for. Flipping 👎 to 👍 and back should not
    # resurrect the old complaint, so it only survives when the rating is unchanged.
    keep = prev.get("rating") == rating
    record["reasons"] = prev.get("reasons", []) if keep else []
    record["comment"] = prev.get("comment", "") if keep else ""

    turns[_turn_key(conv_id, turn)] = record
    _write_all(data)


def clear(user_key: str, conv_id: str, turn: int) -> None:
    """Un-rate a turn — the rating and its detail both go."""
    data = _read_all()
    data.get(user_key, {}).pop(_turn_key(conv_id, turn), None)
    _write_all(data)


def add_detail(user_key: str, conv_id: str, turn: int,
               reasons: List[str], comment: str) -> None:
    data = _read_all()
    record = data.get(user_key, {}).get(_turn_key(conv_id, turn))
    if record is None:
        return
    record["reasons"] = list(reasons or [])
    record["comment"] = (comment or "").strip()
    record["detailed_at"] = datetime.now().isoformat(timespec="seconds")
    _write_all(data)


# --- Shaping it into the analyst's queue ---------------------------------------------

def _dominant(tally: Counter) -> Optional[str]:
    """Most-reported reason, ties broken by the severity order REASONS is declared in."""
    if not tally:
        return None
    order = list(REASONS)
    return min(tally, key=lambda tag: (-tally[tag], order.index(tag)))


def _diagnosis(recs: List[dict], tally: Counter, roles: List[str]) -> str:
    n = len(recs)
    lead = f"{n} thumbs-down from {', '.join(roles)}."

    if tally:
        reported = ", ".join(f"{tag.lower()} ×{c}" for tag, c in tally.most_common())
        route = REASONS[_dominant(tally)]["route"]
        body = f" Reported as {reported} — routes to {route}."
    else:
        body = (
            " No reason given, so the rating is the whole signal: treat it as a lead to "
            "reproduce, not a diagnosis."
        )

    # Verbatim comments are usually where the real diagnosis is, so the two most recent
    # ones are carried through rather than summarised away.
    quotes = [r["comment"] for r in recs if r.get("comment")][-2:]
    if quotes:
        body += " " + " ".join(f'"{c}"' for c in reversed(quotes))
    return lead + body


def queue_items() -> List[dict]:
    """Live thumbs-down, grouped by question, in the shape the feedback queue renders.

    Grouping is the product decision: the analyst should see *one row per broken answer*
    with a count, not one row per irritated person.
    """
    groups: dict = {}
    for turns in _read_all().values():
        for rec in turns.values():
            if rec.get("rating") != "down":
                continue
            question = (rec.get("question") or "").strip()
            if question:
                groups.setdefault(_norm(question), []).append(rec)

    items = []
    for norm, recs in groups.items():
        recs.sort(key=lambda r: r.get("rated_at", ""))
        tally = Counter(tag for r in recs for tag in r.get("reasons", []) if tag in REASONS)
        top = _dominant(tally)

        roles, seen = [], set()
        for r in recs:
            role = r.get("role") or "Unknown"
            if role not in seen:
                seen.add(role)
                roles.append(role)

        severity = REASONS[top]["severity"] if top else "low"
        if len(recs) >= _ESCALATE_AT:
            severity = "high"

        items.append(
            {
                # Stable across reruns and restarts, so dismissing a row makes it stay
                # dismissed even as new downvotes land on the same question.
                "id": "ufb_" + hashlib.sha1(norm.encode()).hexdigest()[:10],
                "question": recs[-1].get("question", "").strip(),
                "outcome": OUTCOME,
                "asks_30d": len(recs),
                "count_label": "thumbs-down",
                "asked_by": ", ".join(roles),
                "diagnosis": _diagnosis(recs, tally, roles),
                "suggested": REASONS[top]["suggested"] if top else "Improve answer quality",
                "severity": severity,
                "live": True,
            }
        )

    # Loudest first — the queue is a work list, not a log.
    items.sort(key=lambda i: (-i["asks_30d"], i["question"]))
    return items


def summary() -> dict:
    """Counts for the queue header: how much signal has actually come in."""
    up = down = detailed = 0
    for turns in _read_all().values():
        for rec in turns.values():
            if rec.get("rating") == "up":
                up += 1
            elif rec.get("rating") == "down":
                down += 1
                if rec.get("reasons") or rec.get("comment"):
                    detailed += 1
    return {"up": up, "down": down, "detailed": detailed}

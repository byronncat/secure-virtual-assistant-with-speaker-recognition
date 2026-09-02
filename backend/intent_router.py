"""
Intent routing: decides whether corrected text is a "conversation"
turn (free-form, goes to the LLM) or a "command" turn
(matches an entry in the command database).

Security note: this module, and the LLM behind it, may only ever choose
*which* intent applies. It must never be trusted to authenticate the
speaker -- that's `speaker_verification.py`'s job, gated by the
`important` flag on the matched command (see `pipeline.py`). If the
model hallucinates an intent that isn't actually registered, routing
fails safe to "conversation" rather than executing something undefined.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ollama import chat

import command_db

logger = logging.getLogger(__name__)

MODEL = "llama3.1:8b"


@dataclass
class RoutedIntent:
    kind: str  # "conversation" | "command"
    intent: str | None  # matched intent name, only set when kind == "command"
    entities: dict[str, Any]


def _build_system_prompt() -> str:
    intents = command_db.list_intents()
    intents_block = (
        "\n".join(f"- {i}" for i in intents) if intents else "(none registered)"
    )
    return f"""
You are an intent router for a voice assistant.

Given the user's (already corrected) text, decide whether it is:
- "conversation": a question, chit-chat, or anything that should be
  answered in free text by an assistant LLM, OR
- "command": a request to perform one of the following registered
  actions:
{intents_block}

Rules:
- Only classify as "command" if the text clearly matches one of the
  registered intents above. If it's close but not a real match, or no
  intents are registered, classify as "conversation".
- Return JSON only, no explanation, in this exact shape:
  {{"kind": "conversation" | "command", "intent": "<intent_name_or_null>", "entities": {{}}}}
- "entities" holds any parameters mentioned for the command (e.g. room
  name, device name). Use an empty object if none.
"""


def route(text: str) -> RoutedIntent:
    if not text.strip():
        return RoutedIntent(kind="conversation", intent=None, entities={})

    try:
        response = chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": text},
            ],
            format="json",
        )
        parsed = json.loads(response.message.content)
    except Exception:
        logger.exception("Intent routing failed; defaulting to conversation.")
        return RoutedIntent(kind="conversation", intent=None, entities={})

    kind = parsed.get("kind")
    intent = parsed.get("intent")
    entities = parsed.get("entities") or {}

    if kind != "command" or not intent or command_db.get_by_intent(intent) is None:
        # Model said conversation, or hallucinated an unregistered intent --
        # fail safe to conversation either way.
        return RoutedIntent(kind="conversation", intent=None, entities={})

    return RoutedIntent(kind="command", intent=intent, entities=entities)

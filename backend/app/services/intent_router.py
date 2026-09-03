"""
Intent routing service: decides whether text is conversation or command.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ollama import chat

from app.core.config import settings
from app.db.models import RoutedIntent
from app.repositories import command_repository

logger = logging.getLogger(__name__)


def _build_system_prompt(username: str | None = None) -> str:
    intents = command_repository.list_intents(username=username)
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


def route(text: str, username: str | None = None) -> RoutedIntent:
    if not text.strip():
        return RoutedIntent(kind="conversation", intent=None, entities={})

    try:
        response = chat(
            model=settings.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": _build_system_prompt(username=username)},
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

    if (
        kind != "command"
        or not intent
        or command_repository.get_by_intent(intent, username=username) is None
    ):
        # Model said conversation, or hallucinated an unregistered intent --
        # fail safe to conversation either way.
        return RoutedIntent(kind="conversation", intent=None, entities={})

    return RoutedIntent(kind="command", intent=intent, entities=entities)

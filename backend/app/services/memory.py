"""
Memory extraction and retrieval service for user personalization.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from ollama import chat

from app.core.config import settings
from app.db.models import MemoryRecord
from app.repositories import memory_repository

logger = logging.getLogger(__name__)

# Stopwords to filter out when scoring keyword overlap
_STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "about",
    "and",
    "or",
    "but",
    "so",
    "it",
    "this",
    "that",
    "my",
    "your",
    "his",
    "her",
    "their",
    "our",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "me",
    "him",
    "us",
    "them",
    "what",
    "which",
    "who",
    "when",
    "where",
    "why",
    "how",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "tôi",
    "bạn",
    "của",
    "và",
    "là",
    "ở",
    "trong",
    "cho",
    "với",
    "về",
    "có",
    "không",
    "được",
    "này",
    "đó",
    "thì",
    "sẽ",
    "đã",
    "đang",
    "gì",
    "nào",
    "sao",
    "thế",
}

_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase words, stripping common stopwords."""
    words = _WORD_RE.findall(text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _token_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity over word tokens."""
    toks_a = _tokenize(a)
    toks_b = _tokenize(b)
    if not toks_a or not toks_b:
        return 0.0
    intersection = toks_a & toks_b
    union = toks_a | toks_b
    return len(intersection) / len(union)


def _is_duplicate_or_subsumed(new_content: str, existing_contents: list[str]) -> bool:
    """Check if new_content is essentially identical to or subsumed by an existing memory."""
    new_lower = new_content.lower().strip()
    toks_new = _tokenize(new_lower)

    for ex in existing_contents:
        ex_lower = ex.lower().strip()
        if new_lower == ex_lower or new_lower in ex_lower or ex_lower in new_lower:
            return True
        toks_ex = _tokenize(ex_lower)
        if not toks_new or not toks_ex:
            continue
        intersection = toks_new & toks_ex
        jaccard = len(intersection) / len(toks_new | toks_ex)
        containment = len(intersection) / min(len(toks_new), len(toks_ex))
        if jaccard >= 0.6 or containment >= 0.75:
            return True
    return False


def retrieve_relevant_memories(
    username: str,
    query: str,
    top_k: int = 6,
) -> list[str]:
    """
    Retrieve the most relevant stored memories for a user given their current query.
    If the user has few total memories (<= 8), returns all of them to give the LLM
    complete user context. Otherwise, scores memories by lexical relevance.
    """
    memories = memory_repository.list_memories(username)
    if not memories:
        return []

    # If small memory bank, provide all memories so LLM always has full user persona
    if len(memories) <= 8:
        return [m.content for m in memories]

    query_tokens = _tokenize(query)
    if not query_tokens:
        # If query has no substantive keywords (e.g. "hi"), return most recent memories
        return [m.content for m in reversed(memories[-top_k:])]

    scored: list[tuple[float, MemoryRecord]] = []
    for m in memories:
        mem_tokens = _tokenize(m.content)
        overlap = len(query_tokens & mem_tokens)

        # Base score on token overlap
        score = float(overlap * 2)

        # Bonus for category match
        query_lower = query.lower()
        if m.category == "preference" and any(
            k in query_lower
            for k in ["like", "prefer", "love", "hate", "thích", "ghét"]
        ):
            score += 1.5
        elif m.category == "work" and any(
            k in query_lower
            for k in ["work", "job", "code", "project", "công việc", "làm"]
        ):
            score += 1.5

        # Substring match bonus
        if any(term in m.content.lower() for term in query_tokens):
            score += 0.5

        scored.append((score, m))

    # Sort descending by score, then recency
    scored.sort(key=lambda item: item[0], reverse=True)

    # Take top scored items with score > 0, backfill with recent items if needed
    selected: list[str] = [m.content for score, m in scored if score > 0][:top_k]
    if len(selected) < 3:
        for _, m in scored:
            if m.content not in selected:
                selected.append(m.content)
            if len(selected) >= min(top_k, 4):
                break

    return selected


_EXTRACTION_SYSTEM_PROMPT = """
You are a personal memory extraction assistant.
Your task is to analyze a conversation exchange between a user and an assistant, and extract permanent, useful facts or preferences about the USER to remember for future personalization.

GUIDELINES FOR EXTRACTION:
1. ONLY extract information specifically about the USER (personal preferences, habits, profession, background, dietary restrictions, relationships, tech stack, pets, identity).
2. DO NOT extract:
   - General knowledge, assistant facts, or answers provided by the assistant.
   - Ephemeral or transient states ("I am tired right now", "I'm going to sleep", "I feel hungry").
   - Generic questions, commands, greetings, or conversational filler ("What is the weather?", "Hello", "Thanks").
   - Facts that are already listed in the "Existing User Memories" list below.
3. Keep each extracted memory clear, concise, and written in third-person (e.g. "Prefers dark roast coffee without sugar", "Works as a backend Python engineer", "Has a dog named Rex").
4. Assign an appropriate category to each memory from: "preference", "personal_fact", "work", "habit", "general".

Output MUST be strict JSON in this exact structure:
{
  "memories": [
    {"content": "<concise fact about user>", "category": "<category>"}
  ]
}
If no permanent facts or preferences about the user are found, return:
{
  "memories": []
}
"""


def extract_memories_from_exchange(
    user_text: str,
    assistant_text: str,
    existing_memories: list[str],
) -> list[dict[str, str]]:
    """
    Extract useful new user memories from a single conversation exchange.
    Returns a list of dicts: [{"content": "...", "category": "..."}].
    """
    if not user_text.strip():
        return []

    # Fast heuristic check: if the user query is extremely short or a pure command/question, skip extraction
    user_lower = user_text.strip().lower()
    if len(user_text.split()) < 3 and not any(
        k in user_lower for k in ["i ", "my ", "tôi ", "mình ", "em ", "anh "]
    ):
        return []

    existing_bullet_list = (
        "\n".join(f"- {m}" for m in existing_memories)
        if existing_memories
        else "(none)"
    )

    user_prompt = f"""
Existing User Memories:
{existing_bullet_list}

Current Conversation Exchange:
User: {user_text}
Assistant: {assistant_text}

Extract any new, useful user facts or preferences:
"""

    try:
        response = chat(
            model=settings.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format="json",
        )
        content = response.message.content
        parsed = json.loads(content)
        raw_memories = parsed.get("memories", [])
    except Exception:
        logger.exception("Failed to extract memories via LLM; skipping extraction.")
        return []

    cleaned: list[dict[str, str]] = []
    for item in raw_memories:
        if not isinstance(item, dict):
            continue
        mem_text = str(item.get("content", "")).strip()
        cat = str(item.get("category", "general")).strip()
        if not mem_text:
            continue
        if _is_duplicate_or_subsumed(mem_text, existing_memories):
            continue
        cleaned.append({"content": mem_text, "category": cat})

    return cleaned


def extract_and_save_sync(
    username: str,
    user_text: str,
    assistant_text: str,
) -> list[MemoryRecord]:
    """Synchronous extraction and storage worker."""
    existing = [m.content for m in memory_repository.list_memories(username)]
    extracted = extract_memories_from_exchange(user_text, assistant_text, existing)
    if not extracted:
        return []

    created = memory_repository.add_memories_batch(username, extracted)
    logger.info(
        "Extracted and saved %d new memories for user '%s': %s",
        len(created),
        username,
        [m.content for m in created],
    )
    return created


async def extract_and_save_async(
    username: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """
    Non-blocking background extraction task to run after conversation completes.
    Safely catches any errors so main request/stream is never affected.
    """
    try:
        await asyncio.to_thread(
            extract_and_save_sync, username, user_text, assistant_text
        )
    except Exception:
        logger.exception("Background memory extraction failed for user '%s'", username)

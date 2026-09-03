"""
Text correction / normalization service for raw ASR transcripts.
"""

from __future__ import annotations

import logging

from ollama import chat

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a transcription normalizer for a voice assistant.

You receive a raw automatic-speech-recognition (ASR) transcript, which may
contain spelling mistakes, misheard words, homophone substitutions, or
dropped words -- especially in proper nouns, command words, and technical
terms.

Your ONLY job is to fix transcription-level errors so the text reads the
way the speaker actually said it. You must NOT:
- add or remove negation words,
- change the meaning, intent, or implied action of the sentence,
- rephrase, summarize, or answer the sentence,
- add words the speaker didn't say, beyond obvious ASR corrections,
- translate the text into another language.

If the transcript is already clean, or you are unsure whether something
is an ASR error, return it unchanged.

Return ONLY the corrected text. No explanations, no quotes, no JSON.
"""


def correct_text(raw_text: str, language: str | None = None) -> str:
    """
    Normalize a raw ASR transcript. Returns the corrected text, or the
    original text unchanged if correction fails or the model returns
    something clearly degenerate (empty string).
    """
    if not raw_text.strip():
        return raw_text

    user_prompt = raw_text
    if language:
        user_prompt = f"[language={language}]\n{raw_text}"

    try:
        response = chat(
            model=settings.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        corrected = response.message.content.strip()
    except Exception:
        logger.exception("Text correction failed; falling back to raw ASR text.")
        return raw_text

    if not corrected:
        return raw_text

    return corrected

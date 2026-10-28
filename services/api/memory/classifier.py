"""Intention classifier for memory proposal responses.

The API currently uses the conservative deterministic fallback so classifying
a proposal does not incur a second LLM call. Only explicit signals resolve it.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from pydantic import BaseModel, Field

from memory.models import IntentionClassification

logger = logging.getLogger("brasaland.memory.classifier")

_SYSTEM_PROMPT = """You are a precise intention classifier for a memory management system.

A memory proposal has been presented to the user. The proposal suggests:
"<PROPOSAL_SUMMARY>"

The user's next message must be classified into ONE of these categories:

1. "approved" - The user explicitly accepts/confirms/approves the proposal.
    Accept only clear affirmative language that refers to the proposal.

2. "rejected" - The user explicitly rejects/declines the proposal.
    Accept only clear rejection of the proposal.

3. "edited" - The user provides a correction or modification to the proposal.
   Look for: a corrected version of the fact, "en realidad es...",
   "mejor dicho...", "cámbialo a...", "actually it's...", "change it to...",
   or similar modification language.

4. "topic_change" - The user does NOT address the proposal at all and
   asks something completely different. Never assume approval by silence.

5. "unrelated" - The message is ambiguous, unclear, or doesn't clearly fit
    any of the above categories. Keep the proposal pending.

IMPORTANT RULES:
- Never assume approval by silence or ambiguity.
- If the user changes topic without addressing the proposal -> topic_change.
- If the message is ambiguous -> unrelated.
- If the user clearly says yes -> approved.
- Only classify as "edited" if the user provides specific corrections.
"""


def classify_intention(
    proposal_summary: str,
    user_message: str,
) -> IntentionClassification:
    """Classify the user's intention regarding a pending memory proposal.

    Uses an LLM call with structured output to determine if the user
    approves, rejects, edits, changes topic, or is unrelated.
    """
    api_key = os.getenv("LLM_API_KEY")
    gateway = os.getenv("LLM_GATEWAY")
    if not api_key or not gateway:
        logger.warning("LLM_GATEWAY or LLM_API_KEY not set; falling back to default classification")
        return _fallback_classify(proposal_summary, user_message)

    from openai import OpenAI

    system_prompt = _SYSTEM_PROMPT.replace("<PROPOSAL_SUMMARY>", proposal_summary)

    client = OpenAI(
        api_key=api_key,
        base_url=gateway,
        timeout=15,
        max_retries=0,
    )

    try:
        response = client.beta.chat.completions.parse(
            model=os.getenv("GEN_MODEL", "litellm/madrid-spain/openrouter/deepseek/deepseek-v4-flash").removeprefix("litellm/"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User message: {user_message}"},
            ],
            response_format=IntentionClassification,
            temperature=0.1,
            max_tokens=200,
        )
        result = response.choices[0].message.parsed
        if not result:
            return _fallback_classify(proposal_summary, user_message)
        return result
    except Exception as exc:
        logger.exception("Intention classification failed: %s", exc)
        return IntentionClassification(intention="unrelated")


def _fallback_classify(
    proposal_summary: str,
    user_message: str,
) -> IntentionClassification:
    """Simple keyword-based fallback when LLM is unavailable."""
    msg_lower = user_message.lower().strip()

    # Check for explicit rejection
    if msg_lower in {"no", "nope", "no gracias", "no thanks", "rechazar", "rechazo"} or any(
        phrase in msg_lower for phrase in ("no guardes", "no lo guardes", "no la guardes", "don't save", "do not save", "not correct", "wrong")
    ):
        return IntentionClassification(intention="rejected")

    # Check for explicit approval
    if msg_lower in {"sí", "si", "sí, por favor", "si por favor", "yes", "yes, please", "ok", "okay", "de acuerdo", "está bien", "esta bien", "adelante", "correcto", "guárdalo", "guardalo", "save it", "go ahead", "approved"}:
        return IntentionClassification(intention="approved")

    # Check for edit patterns
    edit_patterns = ["en realidad", "mejor dicho", "cámbialo", "change it to",
                     "actually", "correct it", "it's actually"]
    if any(pattern in msg_lower for pattern in edit_patterns):
        return IntentionClassification(
            intention="edited",
            edited_summary=user_message,
        )

    # The deterministic fallback cannot safely distinguish ambiguity from a
    # topic change. Fail closed and preserve the pending proposal.
    return IntentionClassification(intention="unrelated")
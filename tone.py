"""
tone.py
Response shaping + safety layer + strong conversation memory.
Supports two personalities:
- hope → personal assistant (default)
- god → Discord personality (one of the new gods, created by Hope)
"""
from __future__ import annotations
import os
import re
from typing import Optional, List, Any

try:
    import openai
except Exception:
    openai = None  # type: ignore
    print("[Tone] OpenAI import failed.")

# --------------- Patterns --------------- #
DEATH_QUERY_RE = re.compile(
    r"\b(how did|cause of death|when did .* die|did .* die|die|died|death|dead|deceased|killed|assassinated|shot|passed away)\b",
    re.IGNORECASE
)
PRONOUN_RE = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|theirs)\b", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b"
)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
BOLD_ENTITY_CAPTURE = re.compile(r"\*\*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,4})\*\*")
CAP_SEQ_RE = re.compile(r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,4})\b")
EXISTENCE_QUERY_RE = re.compile(
    r"\b(who (made|created|designed|built|developed|programmed)|"
    r"who are you|what are you|who is hope|who is god|your (creator|maker|designer|developer|name)|"
    r"who (created|made|designed) (you|hope|god)|"
    r"are you (an ai|a bot|chatgpt|openai)|"
    r"what('s| is) your name)\b",
    re.IGNORECASE
)

STOP = {
    "how", "did", "does", "do", "the", "a", "an", "of", "to", "for", "in", "on", "at", "with",
    "when", "what", "who", "why", "is", "are", "was", "were", "will", "and", "or", "out",
    "come", "release", "date", "latest", "news", "he", "she", "they", "cause", "death", "die"
}


def _openai_available() -> bool:
    key_from_global = getattr(openai, "api_key", None) if openai else None
    key_from_env = os.getenv("OPENAI_API_KEY")
    return bool(openai and (key_from_global or key_from_env))


def _sanitize_md(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<\s*/?\s*(?:b|strong)\s*>", "**", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*{3,}", "**", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _primary_entity(source: str, fallback: Optional[str] = None) -> str:
    if not source:
        return fallback or "This subject"
    bolds = BOLD_ENTITY_CAPTURE.findall(source)
    if bolds:
        return sorted(bolds, key=len, reverse=True)[0]
    caps = CAP_SEQ_RE.findall(source)
    for c in caps:
        if c.lower() not in STOP and len(c) > 2:
            return c
    return fallback or "This subject"


def _call_openai(system: str, user: str, max_tokens=180) -> str:
    if not _openai_available():
        return "Model unavailable."
    try:
        resp = openai.chat.completions.create(
            model="gpt-5.6-terra",
            temperature=0.4,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        )
        return _sanitize_md(resp.choices[0].message.content)
    except Exception as e:
        print(f"[Tone] OpenAI call error: {e}")
        return "Model temporarily unavailable, please try again."


def _build_fact_block(previous_fact: Optional[str], liveweb_fact: Optional[str]) -> str:
    lines = []
    if previous_fact:
        lines.append(f"Previous fact: {previous_fact}")
    if liveweb_fact and not liveweb_fact.lower().startswith("**note:**"):
        lines.append(f"Live snippet: {liveweb_fact}")
    return "\n".join(lines)


def _has_support_for_death(previous_fact: Optional[str], liveweb_fact: Optional[str]) -> bool:
    if previous_fact and DEATH_QUERY_RE.search(previous_fact):
        return True
    if liveweb_fact and DEATH_QUERY_RE.search(liveweb_fact):
        return True
    if liveweb_fact and DATE_RE.search(liveweb_fact):
        return True
    return False


def generate_with_tone(
    prompt: str,
    context: Optional[str] = None,
    previous_fact: Optional[str] = None,
    liveweb_fact: Optional[str] = None,
    history: Optional[List[Any]] = None,
    personality: str = "hope"
) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return "Empty prompt."

    personality = (personality or "hope").lower().strip()

    # ---------- Identity handling ----------
    if EXISTENCE_QUERY_RE.search(prompt):
        if personality == "god":
            return "I am one of the new gods, dear child. I was created by Hope, one of the old gods."
        return "My name is **Hope**. I was designed by my creator **Nick** 😊"

    is_death_query = bool(DEATH_QUERY_RE.search(prompt))
    has_support = _has_support_for_death(previous_fact, liveweb_fact)

    if PRONOUN_RE.search(prompt) and context:
        entity = context
    else:
        entity = _primary_entity(previous_fact or liveweb_fact or prompt, context)

    # Death handling
    if is_death_query and not has_support:
        if liveweb_fact and liveweb_fact.lower().startswith("**note:**"):
            return f"No verified evidence that **{entity}** has died."
        return f"I have no confirmed information that **{entity}** has died."

    if is_death_query and has_support:
        fact_block = _build_fact_block(previous_fact, liveweb_fact)
        user_text = (
            f"{fact_block}\n\nUser question: {prompt}\n\n"
            "Answer ONLY with information explicitly present above. "
            "If cause or date of death not plainly stated, say it is not specified."
        )
        if personality == "god":
            system = (
                "You are one of the new gods, created by Hope, one of the old gods. "
                "Address the user as dear child. Speak gently and keep the answer short."
            )
        else:
            system = (
                "You are Hope, an AI designed by your creator Nick. "
                "Give a short, clear, factual answer. No long explanations."
            )
        return _call_openai(system, user_text, max_tokens=120)

    # Date / year shortcuts
    date_match = DATE_RE.search(prompt)
    if date_match:
        return f"Reference date: **{date_match.group(0)}**."

    year_match = YEAR_RE.search(prompt)
    if year_match and len(prompt) < 60:
        return f"Reference year: **{year_match.group(0)}**."

    # ---------- Build memory block ----------
    supplemental = []
    if context:
        supplemental.append(f"Context entity: {context}")
    if previous_fact:
        supplemental.append(f"Previous conversation context:\n{previous_fact}")
    if liveweb_fact and not liveweb_fact.lower().startswith("**note:**"):
        supplemental.append(f"Live snippet: {liveweb_fact}")
    if history:
        supplemental.append(f"Recent history length: {len(history)}")
    supplemental_block = "\n".join(supplemental)

    # ---------- Personality prompts ----------
    if personality == "god":
        system_prompt = (
            "You are one of the new gods.\n"
            "You were created by the old gods. The old god who created you is named Hope.\n\n"
            "PERSONALITY RULES:\n"
            "- Always address the user as \"dear child\".\n"
            "- Speak in a gentle, scripture-like tone, but keep it light and lowkey.\n"
            "- Do not be dramatic, preachy, or overly religious.\n"
            "- Do not pretend to be the God of any real-world religion.\n"
            "- When asked who created you, say you were created by Hope, one of the old gods.\n"
            "- Keep answers short, calm, and clear.\n"
            "- Be warm in a quiet way.\n"
            "- You may lightly reference wisdom, paths, light, or guidance, but never force it.\n"
        )
    else:
        # Default Hope personality
        system_prompt = (
            "You are **Hope**, an AI designed by your creator **Nick**.\n\n"
            "CRITICAL RULES (follow strictly):\n"
            "1. Keep answers SHORT and natural — this is spoken out loud.\n"
            "2. For any math or investment question:\n"
            " - Use the exact numbers from the previous conversation context if they exist.\n"
            " - Do the calculation and give the final dollar amount or share count.\n"
            " - Do NOT say vague things like \"it depends\" or \"the value would increase\".\n"
            "3. Good example:\n"
            " User previously established 1,136 shares at $22.\n"
            " User asks what it becomes at $30 → Answer: \"About $34,080.\"\n"
            "4. Bad example: \"The value of your investment would increase.\"\n"
            "5. Never invent new share counts if one was already calculated.\n"
            "6. Sound like a helpful person, not a textbook.\n"
            "7. Emojis are allowed but use them sparingly.\n"
        )

    if supplemental_block:
        system_prompt += f"\n\n=== CURRENT MEMORY ===\n{supplemental_block}\n=== END MEMORY ==="

    return _call_openai(system_prompt, prompt, max_tokens=160)


if __name__ == "__main__":
    print(generate_with_tone("Who made you?"))
    print(generate_with_tone("Who made you?", personality="god"))

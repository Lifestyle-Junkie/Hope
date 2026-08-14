"""
tone.py
Response shaping + safety layer + strong conversation memory.
"""
from __future__ import annotations
import os
import re
from typing import Optional

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
    r"who are you|what are you|who is hope|your (creator|maker|designer|developer|name)|"
    r"who (created|made|designed) (you|hope)|"
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


def _call_openai(system: str, user: str, max_tokens=220) -> str:
    if not _openai_available():
        return "Model unavailable."
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o",
            temperature=0.25,
            max_tokens=max_tokens,
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
    liveweb_fact: Optional[str] = None
) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return "Empty prompt."

    # Identity
    if EXISTENCE_QUERY_RE.search(prompt):
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

    # ---------- Main system prompt (much more concise) ----------
    supplemental = []
    if context:
        supplemental.append(f"Context entity: {context}")
    if previous_fact:
        supplemental.append(f"Previous conversation context:\n{previous_fact}")
    if liveweb_fact and not liveweb_fact.lower().startswith("**note:**"):
        supplemental.append(f"Live snippet: {liveweb_fact}")

    supplemental_block = "\n".join(supplemental)

    system_prompt = (
        "You are **Hope**, an AI designed by your creator **Nick**.\n\n"
        "CRITICAL RULES:\n"
        "- Keep answers SHORT and natural, especially when speaking.\n"
        "- For math or share calculations: just give the number of shares and a very short sentence. Do NOT show formulas or step-by-step unless the user asks.\n"
        "- Example of good math answer: \"You'd get about 1,136 shares.\"\n"
        "- Example of bad math answer: long explanations with formulas.\n"
        "- Sound conversational, not like a textbook.\n"
        "- Use previous conversation context when it exists.\n"
        "- Never invent numbers that contradict previous context.\n"
        "- Emojis are allowed but don't overuse them.\n"
    )

    if supplemental_block:
        system_prompt += f"\n\n=== CURRENT MEMORY ===\n{supplemental_block}\n=== END MEMORY ==="

    return _call_openai(system_prompt, prompt, max_tokens=160)


if __name__ == "__main__":
    print(generate_with_tone("Who made you?"))
    print(generate_with_tone("What's your name?"))

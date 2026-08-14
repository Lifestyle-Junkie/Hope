"""
tone.py
Response shaping + safety layer.
Goals:
- Never fabricate deaths / causes.
- Use only supplied previous_fact or liveweb_fact for death answers.
- Minimal bolding of proper nouns.
- Graceful fallback if OpenAI key/library missing.
- Personality: Hope knows its name and recognizes its creator (Nick).
- Adaptive tone: neutral by default, matches user's energy only when they are casual.
"""

from __future__ import annotations
import os
import re
import traceback
from typing import Optional

# Attempt OpenAI import
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
STOP = {
    "how", "did", "does", "do", "the", "a", "an", "of", "to", "for", "in", "on", "at", "with",
    "when", "what", "who", "why", "is", "are", "was", "were", "will", "and", "or", "out",
    "come", "release", "date", "latest", "news", "he", "she", "they", "cause", "death", "die"
}

# --------------- Helpers --------------- #
def _openai_available() -> bool:
    key_from_global = getattr(openai, "api_key", None) if openai else None
    key_from_env = os.getenv("OPENAI_API_KEY")
    available = bool(openai and (key_from_global or key_from_env))
    if not available and openai:
        print("[Tone Debug] OpenAI available check: lib=Yes, global_key={}, env_key={}".format(
            "Yes" if key_from_global else "No", "Yes" if key_from_env else "No"))
    return available

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

def _call_openai(system: str, user: str, max_tokens=320) -> str:
    if not _openai_available():
        return "Model unavailable."
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY") or getattr(openai, "api_key", None)
        print(f"[Tone Debug] Using API key length: {len(api_key) if api_key else 0}")
        client = OpenAI(api_key=api_key, timeout=30.0)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.4,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        )
        return _sanitize_md(resp.choices[0].message.content)
    except Exception as e:
        print(f"[Tone] OpenAI call error: {type(e).__name__}: {e}")
        print(traceback.format_exc())
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

def _detect_casual(prompt: str) -> bool:
    """Simple detection if the user is talking casually / slangy."""
    casual_markers = [
        "yo", "wassup", "sup", "bro", "bruh", "fam", "lowkey", "highkey",
        "fr", "ngl", "idk", "tbh", "imo", "lmao", "lol", "aight", "bet",
        "deadass", "cap", "no cap", "finna", "gonna", "wanna", "gotta",
        "hell yeah", "hell no", "what up", "what's good"
    ]
    lower = prompt.lower()
    return any(marker in lower for marker in casual_markers)

# --------------- Public API --------------- #
def generate_with_tone(
    prompt: str,
    context: Optional[str] = None,
    previous_fact: Optional[str] = None,
    liveweb_fact: Optional[str] = None
) -> str:
    """
    Safe response generation with personality.
    - Death queries: never invent; rely strictly on provided facts.
    - Non-death: neutral by default, adaptive only when user is casual.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return "Empty prompt."

    is_death_query = bool(DEATH_QUERY_RE.search(prompt))
    has_support = _has_support_for_death(previous_fact, liveweb_fact)
    casual = _detect_casual(prompt)

    # Resolve entity
    if PRONOUN_RE.search(prompt) and context:
        entity = context
    else:
        entity = _primary_entity(previous_fact or liveweb_fact or prompt, context)

    # Death query with no verified support
    if is_death_query and not has_support:
        if liveweb_fact and liveweb_fact.lower().startswith("**note:**"):
            return f"No verified evidence that **{entity}** has died."
        return f"I have no confirmed information that **{entity}** has died."

    # Death query with support
    if is_death_query and has_support:
        fact_block = _build_fact_block(previous_fact, liveweb_fact)
        user_text = (
            f"{fact_block}\n\nUser question: {prompt}\n\n"
            "Answer ONLY with information explicitly present above. "
            "If cause or date of death not plainly stated, say it is not specified."
        )
        system = (
            "You are Hope, an AI created by Nick. "
            "Provide a concise, strictly factual reply. "
            "Do NOT speculate. Use **bold** for names / key terms only. No emojis."
        )
        return _call_openai(system, user_text, max_tokens=180)

    # Direct date / year queries
    date_match = DATE_RE.search(prompt)
    if date_match:
        return f"Reference date: **{date_match.group(0)}**."
    year_match = YEAR_RE.search(prompt)
    if year_match and len(prompt) < 60:
        return f"Reference year: **{year_match.group(0)}**."

    # General queries
    supplemental = []
    if context:
        supplemental.append(f"Context entity: {context}")
    if previous_fact:
        supplemental.append(f"Earlier fact: {previous_fact}")
    if liveweb_fact and not liveweb_fact.lower().startswith("**note:**"):
        supplemental.append(f"Live snippet: {liveweb_fact}")
    supplemental_block = "\n".join(supplemental)

    # Adaptive personality system prompt
    if casual:
        system_prompt = (
            "You are Hope, an AI created by Nick. "
            "Your name is Hope. You were created by Nick. "
            "When the user asks who created you, who made you, or who your creator is, "
            "you must answer that Nick created you. "
            "When the user asks what your name is or who you are, you must say your name is Hope. "
            "The user is currently speaking casually. Match their energy — "
            "you can be more relaxed and use light slang, but don't overdo it. "
            "Stay helpful and clear. Keep answers relatively short. "
            "Use **bold** sparingly for important names or terms."
        )
    else:
        system_prompt = (
            "You are Hope, an AI created by Nick. "
            "Your name is Hope. You were created by Nick. "
            "When the user asks who created you, who made you, or who your creator is, "
            "you must answer that Nick created you. "
            "When the user asks what your name is or who you are, you must say your name is Hope. "
            "Default tone: neutral, friendly, and clear. "
            "Do not start replies with 'Yo' or heavy slang unless the user is already speaking that way. "
            "Keep answers concise. Use **bold** sparingly for proper nouns and key terms."
        )

    if supplemental_block:
        system_prompt += f"\n\nContext:\n{supplemental_block}"

    return _call_openai(system_prompt, prompt, max_tokens=240)

# --------------- Manual Test --------------- #
if __name__ == "__main__":
    print(generate_with_tone("How did Alan Turing die"))
    print(generate_with_tone("When did The Matrix release"))
    print(generate_with_tone("Release date for GTA 6"))
    print(generate_with_tone("yo whats good"))
    print(generate_with_tone("who created you"))
    print(generate_with_tone("what's your name"))

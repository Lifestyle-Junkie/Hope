"""
tone.py
Response shaping + safety layer + strong conversation memory.
Supports two personalities:
- hope → personal assistant (default)
- god → Discord personality (one of the new gods, created by Hope)
Uses GPT-5.6 Terra (no custom temperature — model only supports default).
Enhancements:
- Code/HTML/script path with higher token limit
- Sanitize preserves fenced code blocks (so HTML isn't stripped)
- Code path: multi-attempt OpenAI calls
- Local HTML fallback when model returns empty for store/HTML pages
- Tighter history follow-up detection (won't treat "hello" as code)
- Richer dropship store fallback so in-chat preview looks like a real site
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
SITE_OR_LINK_RE = re.compile(
    r"\b(site|website|url|link|homepage|official site|send me the link|give me the (link|url)|the link)\b",
    re.IGNORECASE
)
URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|co|app|ai|gg|tv|me|us|uk|ca|de|fr|nz)\b",
    re.IGNORECASE
)
CODE_QUERY_RE = re.compile(
    r"\b("
    r"write (me |us |the |a |an )?(code|script|function|class|html|css|python|javascript|js|sql|program|page|store|site|app)|"
    r"write (me |us |the |a |an )?.*\b(html|code|script|page|website)\b|"
    r"(html|css|python|javascript|js|typescript|sql|react|flask)(\s+(code|page|file|script|store|site|app|snippet))?|"
    r"code (for|that|to|out)|"
    r"(implement|refactor|debug)\b|"
    r"dropship(ping)?\s+(store|site|page|shop)|"
    r"full (html|page|script)|"
    r"product page|"
    r"write one in chat"
    r")\b",
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
    """Strip unsafe HTML but KEEP fenced code blocks (```...```) intact."""
    if not text:
        return ""
    fences: List[str] = []

    def _save_fence(m: re.Match) -> str:
        fences.append(m.group(0))
        return f"\0FENCE{len(fences) - 1}\0"

    text = re.sub(r"```[\s\S]*?```", _save_fence, text)
    text = re.sub(r"<\s*/?\s*(?:b|strong)\s*>", "**", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*{3,}", "**", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    for i, fence in enumerate(fences):
        text = text.replace(f"\0FENCE{i}\0", fence)
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


def _extract_url(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = URL_RE.search(text)
    if m:
        return m.group(0).rstrip(".,);]")
    d = DOMAIN_RE.search(text)
    if d:
        host = d.group(0).lower()
        return f"https://{host}"
    return None


def _format_site_link(url: str, label: Optional[str] = None) -> str:
    host = re.sub(r"^https?://(www\.)?", "", url, flags=re.IGNORECASE).split("/")[0]
    label = label or host
    return f"[{label}]({url})"


def _call_openai(system: str, user: str, max_tokens=180) -> str:
    if not _openai_available():
        return "Model unavailable."
    try:
        resp = openai.chat.completions.create(
            model="gpt-5.6-terra",
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        )
        content = resp.choices[0].message.content or ""
        return _sanitize_md(content)
    except Exception as e:
        print(f"[Tone] OpenAI call error: {e}")
        return "Model temporarily unavailable, please try again."


def _extract_message_text(resp) -> str:
    """Pull text from OpenAI chat completion, including edge cases."""
    try:
        choice = resp.choices[0]
        msg = choice.message
        content = getattr(msg, "content", None) or ""
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("text"):
                    parts.append(p["text"])
                elif isinstance(p, str):
                    parts.append(p)
            content = "".join(parts)
        content = (content or "").strip()
        if content:
            return content
        refusal = getattr(msg, "refusal", None)
        if refusal:
            print(f"[Tone] Model refusal: {refusal}")
        fr = getattr(choice, "finish_reason", None)
        print(f"[Tone] Empty content; finish_reason={fr}")
    except Exception as e:
        print(f"[Tone] Extract error: {e}")
    return ""


def _finalize_code_content(content: str) -> str:
    """Sanitize fenced code or wrap unfenced HTML."""
    content = (content or "").strip()
    if not content:
        return ""
    if "```" in content:
        cleaned = _sanitize_md(content)
        return cleaned or content
    looks_html = bool(
        re.search(r"<!DOCTYPE|<html|<head|<body|<div|<style", content, re.IGNORECASE)
    )
    lang = "html" if looks_html else "text"
    return f"```{lang}\n{content}\n```"


def _html_store_fallback(user: str) -> str:
    """Richer single-file store page so in-chat preview looks like a real site."""
    low = (user or "").lower()
    if "shoe" in low:
        product = "Shoes"
        items = [
            ("Classic Runner", "Everyday comfort", "$79"),
            ("Street High", "Bold high-top style", "$95"),
            ("Trail Flex", "All-terrain grip", "$110"),
            ("Night Slip", "Lightweight daily", "$68"),
        ]
    elif "shirt" in low:
        product = "Shirts"
        items = [
            ("Core Tee", "Soft cotton fit", "$29"),
            ("Oxford Button", "Clean casual", "$48"),
            ("Oversize Hood", "Heavy fleece", "$62"),
            ("Linen Camp", "Warm-weather ease", "$54"),
        ]
    elif "watch" in low:
        product = "Watches"
        items = [
            ("Field Chrono", "Everyday precision", "$149"),
            ("Night Diver", "Water-ready build", "$189"),
            ("Slim Quartz", "Minimal daily", "$99"),
            ("Steel Classic", "Timeless metal", "$129"),
        ]
    elif "hat" in low or "cap" in low:
        product = "Hats"
        items = [
            ("Dad Cap", "Soft unstructured", "$28"),
            ("Wool Beanie", "Cold-day staple", "$24"),
            ("Trucker Mesh", "Breathable daily", "$26"),
            ("Bucket Soft", "Shade + style", "$32"),
        ]
    else:
        product = "Products"
        items = [
            ("Classic Runner", "Everyday comfort", "$79"),
            ("Street High", "Bold high-top style", "$95"),
            ("Trail Flex", "All-terrain grip", "$110"),
            ("Night Slip", "Lightweight daily", "$68"),
        ]

    title = f"{product} Dropship Store"
    cards = []
    for name, desc, price in items:
        cards.append(
            f"""      <article class="card">
        <div class="img"></div>
        <div class="body">
          <h3>{name}</h3>
          <p>{desc}</p>
          <div class="price">{price}</div>
          <button type="button">Add to cart</button>
        </div>
      </article>"""
        )
    cards_html = "\n".join(cards)

    # Full f-string: CSS braces must be doubled {{ }} so output is single { }
    return f"""Here's a fuller single-file {product.lower()} store page:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: #0f0f12;
      color: #eee;
      min-height: 100vh;
    }}
    header {{
      padding: 1.1rem 1.5rem;
      border-bottom: 1px solid #222;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      background: rgba(15,15,18,0.92);
      backdrop-filter: blur(8px);
      z-index: 5;
    }}
    header strong {{ letter-spacing: 0.06em; font-size: 0.95rem; }}
    header span {{ color: #9aa; font-size: 0.9rem; }}
    .hero {{
      padding: 2.5rem 1.5rem 1.25rem;
      max-width: 1100px;
      margin: 0 auto;
    }}
    .hero h1 {{
      margin: 0 0 0.5rem;
      font-size: clamp(1.6rem, 3vw, 2.2rem);
    }}
    .hero p {{ margin: 0; color: #9aa; max-width: 36rem; line-height: 1.5; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 1rem;
      padding: 1rem 1.5rem 2.5rem;
      max-width: 1100px;
      margin: 0 auto;
    }}
    .card {{
      background: #1a1a1f;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #2a2a30;
      display: flex;
      flex-direction: column;
    }}
    .card .img {{
      height: 170px;
      background: linear-gradient(135deg, #2a2a32, #111);
    }}
    .card .body {{
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      flex: 1;
    }}
    .card h3 {{ margin: 0; font-size: 1.02rem; }}
    .card p {{ margin: 0; color: #9aa; font-size: 0.9rem; }}
    .price {{
      font-weight: 700;
      color: #7dffb3;
      margin: 0.35rem 0 0.55rem;
      font-size: 1.05rem;
    }}
    button {{
      width: 100%;
      margin-top: auto;
      padding: 0.7rem;
      border: 0;
      border-radius: 10px;
      background: #7dffb3;
      color: #111;
      font-weight: 700;
      cursor: pointer;
      font-size: 0.95rem;
    }}
    button:hover {{ filter: brightness(1.05); }}
    footer {{
      text-align: center;
      padding: 1.5rem;
      color: #666;
      font-size: 0.85rem;
      border-top: 1px solid #1c1c22;
    }}
  </style>
</head>
<body>
  <header>
    <strong>{title.upper()}</strong>
    <span>Cart (0)</span>
  </header>
  <section class="hero">
    <h1>{product} built for everyday wear</h1>
    <p>Clean dropship template — swap in your supplier images, prices, and checkout link.</p>
  </section>
  <main class="grid">
{cards_html}
  </main>
  <footer>Demo storefront · edit products in the HTML · wire your own cart later</footer>
</body>
</html>
```"""


def _call_openai_code(system: str, user: str, max_tokens=2000) -> str:
    """
    Code-specific OpenAI call with 3 attempts + HTML local fallback.
    Never returns empty for store/HTML-style requests.
    """
    if not _openai_available():
        print("[Tone] Code path: OpenAI unavailable")
        low = (user or "").lower()
        if any(k in low for k in ("html", "website", "dropship", "store", "shoe", "shoes", "page")):
            return _html_store_fallback(user)
        return "Model unavailable for code generation."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Attempt 1
    try:
        resp = openai.chat.completions.create(
            model="gpt-5.6-terra",
            max_completion_tokens=max_tokens,
            messages=messages,
        )
        content = _extract_message_text(resp)
        print(f"[Tone] Code path attempt1 length: {len(content)}")
        if content:
            return _finalize_code_content(content)
    except Exception as e:
        print(f"[Tone] OpenAI attempt1 error: {e}")

    # Attempt 2
    try:
        resp = openai.chat.completions.create(
            model="gpt-5.6-terra",
            max_tokens=min(max_tokens, 1500),
            messages=messages,
        )
        content = _extract_message_text(resp)
        print(f"[Tone] Code path attempt2 length: {len(content)}")
        if content:
            return _finalize_code_content(content)
    except Exception as e:
        print(f"[Tone] OpenAI attempt2 error: {e}")

    # Attempt 3
    try:
        short_system = (
            "You are Hope, a coding assistant by Nick. "
            "Return a complete single-file HTML page for the user's request. "
            "Include dark modern CSS, a product grid, and wrap everything in a ```html fence. "
            "Do not refuse. Do not ask questions."
        )
        resp = openai.chat.completions.create(
            model="gpt-5.6-terra",
            max_completion_tokens=2000,
            messages=[
                {"role": "system", "content": short_system},
                {"role": "user", "content": user},
            ],
        )
        content = _extract_message_text(resp)
        print(f"[Tone] Code path attempt3 length: {len(content)}")
        if content:
            return _finalize_code_content(content)
    except Exception as e:
        print(f"[Tone] OpenAI attempt3 error: {e}")

    low = (user or "").lower()
    if any(k in low for k in ("html", "website", "dropship", "store", "shoe", "shoes", "page", "product")):
        print("[Tone] Using local HTML fallback after empty model responses")
        return _html_store_fallback(user)
    return "I couldn't generate that code right now. Try again."


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

    if EXISTENCE_QUERY_RE.search(prompt):
        if personality == "god":
            return "I am one of the new gods, dear child. I was created by Hope, one of the old gods."
        return "My name is **Hope**. I was designed by my creator **Nick** 😊"

    is_death_query = bool(DEATH_QUERY_RE.search(prompt))
    is_site_or_link = bool(SITE_OR_LINK_RE.search(prompt))
    is_code_query = bool(CODE_QUERY_RE.search(prompt))
    has_support = _has_support_for_death(previous_fact, liveweb_fact)

    if PRONOUN_RE.search(prompt) and context:
        entity = context
    else:
        entity = _primary_entity(previous_fact or liveweb_fact or prompt, context)

    if is_site_or_link and not is_code_query:
        url = (
            _extract_url(liveweb_fact)
            or _extract_url(previous_fact)
            or _extract_url(prompt)
        )
        if url:
            if re.search(r"\b(send|give|drop|share)\b.*\b(link|url)\b", prompt, re.IGNORECASE) or \
               re.fullmatch(r"(the )?link\??", prompt.strip(), re.IGNORECASE):
                return f"Here you go: {_format_site_link(url)}"
            return f"Official site: {_format_site_link(url)}"

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

    if not is_code_query:
        date_match = DATE_RE.search(prompt)
        if date_match:
            return f"Reference date: **{date_match.group(0)}**."
        year_match = YEAR_RE.search(prompt)
        if year_match and len(prompt) < 60:
            return f"Reference year: **{year_match.group(0)}**."

    supplemental = []
    if context:
        supplemental.append(f"Context entity: {context}")
    if previous_fact:
        supplemental.append(f"Previous conversation context:\n{previous_fact}")
    if liveweb_fact and not liveweb_fact.lower().startswith("**note:**"):
        supplemental.append(f"Live snippet: {liveweb_fact}")
    if history:
        try:
            recent = history[-6:] if isinstance(history, list) else []
            if recent:
                lines = []
                for turn in recent:
                    if not isinstance(turn, dict):
                        continue
                    role = turn.get("role", "?")
                    content = (turn.get("content") or "")[:220]
                    lines.append(f"{role}: {content}")
                if lines:
                    supplemental.append("Recent messages:\n" + "\n".join(lines))
        except Exception:
            supplemental.append(f"Recent history length: {len(history)}")
    supplemental_block = "\n".join(supplemental)

    link_rules = (
        "\nLINK RULES (important):\n"
        "- When giving a website, ALWAYS use markdown link format: [label](https://example.com)\n"
        "- Good: [rainbet.com](https://rainbet.com)\n"
        "- Bad: rainbet.com\n"
        "- Bad: https://rainbet.com with no markdown\n"
        "- If previous context already has the correct URL, reuse that URL. Do not invent a different site.\n"
        "- For follow-ups like \"send me the link\" / \"the link\", just return the known URL in markdown.\n"
    )

    history_suggests_code = False
    if history and not is_code_query:
        try:
            blob = " ".join(
                (t.get("content") or "") for t in history[-6:] if isinstance(t, dict)
            ).lower()
            code_follow = bool(re.search(
                r"\b(shoes?|product page|html|css|the page|the store|dropship|website)\b",
                (prompt or "").lower(),
            ))
            if code_follow and any(k in blob for k in ("html", "dropship", "```", "code", "store", "page")):
                history_suggests_code = True
        except Exception:
            pass

    if is_code_query or history_suggests_code:
        code_system = (
            "You are **Hope**, an AI coding assistant designed by **Nick**.\n\n"
            "CODE RULES (follow strictly):\n"
            "1. When the user asks for code, HTML, CSS, JS, Python, SQL, etc., provide REAL working code.\n"
            "2. ALWAYS wrap code in fenced markdown blocks with a language tag, e.g. ```html or ```python.\n"
            "3. One short intro line is fine, then the full code block. Optional 1–2 line notes after.\n"
            "4. Do NOT refuse. Do NOT say 'no data'. Build a minimal but complete example.\n"
            "5. For an HTML dropshipping/store page: include a full single-file HTML doc "
            "(<!DOCTYPE html>, head, modern dark CSS, product grid, sticky header, footer). Keep it self-contained.\n"
            "6. Prefer standard HTML/CSS/JS or standard library Python unless asked for a framework.\n"
            "7. The full markup MUST appear inside the fence. Never omit tags.\n"
            "8. If the user only says a product name (e.g. \"shoes\") after asking for a page, "
            "build the product page for that product. Do not ask more questions.\n"
            "9. Do not treat product names as stock tickers.\n"
            "10. Make store pages look polished: dark background, card grid, mint/green price + buttons.\n"
        )
        if personality == "god":
            code_system = (
                "You are one of the new gods, created by Hope.\n"
                "Address the user as dear child, but still provide full working code when asked.\n"
                "ALWAYS wrap code in fenced blocks with a language tag (```html, ```python, etc.).\n"
                "For HTML pages, return a complete single-file document with modern dark CSS inside the fence.\n"
                "If they name a product, build that product page — do not ask more questions.\n"
            )
        if supplemental_block:
            code_system += f"\n\n=== CURRENT MEMORY ===\n{supplemental_block}\n=== END MEMORY ==="
        print("[Tone] Code request detected — using code path (max_tokens=2000)")
        return _call_openai_code(code_system, prompt, max_tokens=2000)

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
            + link_rules
        )
    else:
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
            + link_rules
        )

    if supplemental_block:
        system_prompt += f"\n\n=== CURRENT MEMORY ===\n{supplemental_block}\n=== END MEMORY ==="
    return _call_openai(system_prompt, prompt, max_tokens=160)


if __name__ == "__main__":
    print(generate_with_tone("Who made you?"))
    print(generate_with_tone("Who made you?", personality="god"))
    print(
        generate_with_tone(
            "send me the link",
            previous_fact="Official site: [rainbet.com](https://rainbet.com)"
        )
    )
    print(generate_with_tone("write me a html code for a dropshipping website"))

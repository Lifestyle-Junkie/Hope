"""
tone.py
Response shaping + safety layer + strong conversation memory.
Supports two personalities:
- hope → personal assistant (default)
- god → Discord personality (one of the new gods, created by Hope)
Uses GPT-5.6 Terra only (via official OpenAI client).
Terra-only: uses max_completion_tokens with retry budgets (no max_tokens).
"""
from __future__ import annotations
import os
import re
from typing import Optional, List, Any, Tuple

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
    r"write (me |us |the |a |an )?.*\b(html|code|script|page|website|landing)\b|"
    r"(html|css|python|javascript|js|typescript|sql|react|flask)(\s+(code|page|file|script|store|site|app|snippet))?|"
    r"code (for|that|to|out)|"
    r"(implement|refactor|debug)\b|"
    r"dropship(ping)?\s+(store|site|page|shop)|"
    r"full (html|page|script)|"
    r"product page|landing page|"
    r"write one in chat"
    r")\b",
    re.IGNORECASE
)
CODE_ITERATE_RE = re.compile(
    r"\b("
    r"change|update|modify|tweak|adjust|redo|improve|restyle|redesign|"
    r"make (it|the|this)|different|another|new (color|background|theme|layout|version)|"
    r"background|colour|color|theme|darker|lighter|brighter|"
    r"blue|green|red|purple|pink|orange|yellow|white|black|"
    r"bold|bolder|thicker|font|typography|weight|"
    r"bigger|smaller|larger|tinier|size|"
    r"spacing|padding|margin|gap|"
    r"rounder|sharper|radius|"
    r"add (a |an |the )?(hero|nav|footer|button|cart|image|section)|"
    r"looks? (too )?(basic|bland|plain|simple)|more (modern|polished|professional|bold)"
    r")\b",
    re.IGNORECASE,
)
FRESH_PAGE_RE = re.compile(
    r"\b(write|create|build|generate|make)\b.*\b(html|page|website|landing|site|store)\b"
    r"|\blanding page\b"
    r"|\bnew (page|site|website|store|html)\b",
    re.IGNORECASE,
)
GREETING_RE = re.compile(
    r"^\s*("
    r"hi|hello|hey|yo|sup|hiya|howdy|"
    r"good\s*(morning|afternoon|evening)|"
    r"what'?s\s*up|how\s*are\s*you|how'?s\s*it\s*going"
    r")[\s!?.]*$",
    re.IGNORECASE,
)
STOP = {
    "how", "did", "does", "do", "the", "a", "an", "of", "to", "for", "in", "on", "at", "with",
    "when", "what", "who", "why", "is", "are", "was", "were", "will", "and", "or", "out",
    "come", "release", "date", "latest", "news", "he", "she", "they", "cause", "death", "die"
}

_COLOR_MAP = {
    "blue": "#1e3a8a",
    "navy": "#0f172a",
    "sky": "#0ea5e9",
    "red": "#7f1d1d",
    "green": "#14532d",
    "purple": "#581c87",
    "pink": "#9d174d",
    "orange": "#9a3412",
    "yellow": "#854d0e",
    "white": "#f8fafc",
    "black": "#0a0a0a",
    "gray": "#1f2937",
    "grey": "#1f2937",
    "teal": "#134e4a",
    "mint": "#7dffb3",
}

MODEL = "gpt-5.6-terra"


def _openai_available() -> bool:
    if not openai:
        return False
    key = os.getenv("OPENAI_API_KEY") or getattr(openai, "api_key", None)
    return bool(key)


def _get_client():
    """Official OpenAI client for this worker."""
    if not openai:
        print("[Tone] openai library missing")
        return None
    key = os.getenv("OPENAI_API_KEY") or getattr(openai, "api_key", None)
    if not key:
        print("[Tone] No OPENAI_API_KEY in env or openai.api_key")
        return None
    try:
        return openai.OpenAI(api_key=key)
    except Exception as e:
        print(f"[Tone] Client create error: {type(e).__name__}: {e}")
        return None


def _sanitize_md(text: str) -> str:
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


def _last_html_from_history(history: Optional[List[Any]]) -> Optional[str]:
    if not history:
        return None
    try:
        for turn in reversed(list(history)[-12:]):
            if not isinstance(turn, dict):
                continue
            content = turn.get("content") or ""
            if not content:
                continue
            m = re.search(r"```html\s*([\s\S]*?)```", content, re.IGNORECASE)
            if m and m.group(1).strip():
                return m.group(1).strip()
            if re.search(r"<!DOCTYPE\s+html|<html[\s>]", content, re.IGNORECASE):
                return content.strip()
    except Exception as e:
        print(f"[Tone] last_html extract error: {e}")
    return None


def _pick_color_from_prompt(prompt: str) -> Optional[str]:
    low = (prompt or "").lower()
    for name, hex_ in _COLOR_MAP.items():
        if re.search(rf"\b{name}\b", low):
            return hex_
    return None


def _apply_simple_html_edits(prev_html: str, prompt: str) -> Optional[str]:
    if not prev_html or not prompt:
        return None
    low = prompt.lower()
    html = prev_html
    changed = False

    mentions_button = bool(re.search(r"\b(button|buttons|cta)\b", low))
    color = _pick_color_from_prompt(prompt)
    wants_bg = bool(
        re.search(r"\bbackground\b", low)
        or re.search(r"\btheme\b", low)
        or re.search(r"\b(make|change|set)\b.*\b(background|theme|page|site|html)\b", low)
    )

    if color and not mentions_button and (
        wants_bg
        or re.search(
            r"\b(blue|green|red|purple|pink|black|white|navy|sky|teal|orange|yellow|gray|grey|mint)\b",
            low,
        )
    ):
        new_html, n = re.subn(
            r"(body\s*\{[^}]*?background\s*:\s*)([^;]+)",
            rf"\1{color}",
            html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if n:
            html = new_html
            changed = True
        else:
            new_html, n = re.subn(
                r"(body\s*\{)",
                rf"\1\n      background: {color};",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            if n:
                html = new_html
                changed = True
        if changed:
            new_html, n = re.subn(
                r"(header\s*\{[^}]*?background\s*:\s*)([^;]+)",
                rf"\1{color}ee",
                html,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if n:
                html = new_html

    if mentions_button and color:
        new_html, n = re.subn(
            r"(button\s*\{[^}]*?background\s*:\s*)([^;]+)",
            rf"\1{color}",
            html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if n:
            html = new_html
            changed = True
        else:
            new_html, n = re.subn(
                r"(button\s*\{)",
                rf"\1\n      background: {color};",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            if n:
                html = new_html
                changed = True

    if re.search(r"\b(bold|bolder|thicker|more bold)\b", low):
        injected = False
        for sel in ("body", "h1", "h2", "h3"):
            pat = rf"({sel}\s*\{{[^}}]*?)(font-weight\s*:\s*)([^;]+)"
            new_html, n = re.subn(pat, rf"\1\2 800", html, count=1, flags=re.I | re.S)
            if n:
                html = new_html
                changed = True
                injected = True
            else:
                new_html, n = re.subn(
                    rf"({sel}\s*\{{)",
                    rf"\1\n      font-weight: 800;",
                    html,
                    count=1,
                    flags=re.I,
                )
                if n:
                    html = new_html
                    changed = True
                    injected = True
        if not injected and "<style>" in html:
            html = html.replace(
                "</style>",
                "\n    h1,h2,h3,header strong,.card h3{font-weight:800!important;}\n  </style>",
                1,
            )
            changed = True

    if (
        re.search(r"\b(bigger|larger|increase)\b.*\b(text|font)\b", low)
        or re.search(r"\b(text|font)\b.*\b(bigger|larger)\b", low)
        or re.search(r"\bbigger text\b", low)
    ):
        new_html, n = re.subn(
            r"(body\s*\{[^}]*?font-size\s*:\s*)([^;]+)",
            r"\1 18px",
            html,
            count=1,
            flags=re.I | re.S,
        )
        if n:
            html = new_html
            changed = True
        else:
            new_html, n = re.subn(
                r"(body\s*\{)",
                r"\1\n      font-size: 18px;",
                html,
                count=1,
                flags=re.I,
            )
            if n:
                html = new_html
                changed = True

    if (
        re.search(r"\b(smaller|tinier|decrease)\b.*\b(text|font)\b", low)
        or re.search(r"\b(text|font)\b.*\b(smaller|tinier)\b", low)
    ):
        new_html, n = re.subn(
            r"(body\s*\{[^}]*?font-size\s*:\s*)([^;]+)",
            r"\1 13px",
            html,
            count=1,
            flags=re.I | re.S,
        )
        if n:
            html = new_html
            changed = True
        else:
            new_html, n = re.subn(
                r"(body\s*\{)",
                r"\1\n      font-size: 13px;",
                html,
                count=1,
                flags=re.I,
            )
            if n:
                html = new_html
                changed = True

    if re.search(r"\b(rounder|more rounded|softer)\b", low):
        new_html, n = re.subn(
            r"(\.card\s*\{[^}]*?border-radius\s*:\s*)([^;]+)",
            r"\1 22px",
            html,
            count=1,
            flags=re.I | re.S,
        )
        if n:
            html = new_html
            changed = True
        else:
            new_html, n = re.subn(
                r"(\.card\s*\{)",
                r"\1\n      border-radius: 22px;",
                html,
                count=1,
                flags=re.I,
            )
            if n:
                html = new_html
                changed = True

    if re.search(r"\b(sharper|less rounded|square)\b", low):
        new_html, n = re.subn(
            r"(\.card\s*\{[^}]*?border-radius\s*:\s*)([^;]+)",
            r"\1 4px",
            html,
            count=1,
            flags=re.I | re.S,
        )
        if n:
            html = new_html
            changed = True

    return html if changed else None


def _call_openai(system: str, user: str, max_tokens=180) -> str:
    """Terra-only caller. Never uses max_tokens (unsupported on this model)."""
    client = _get_client()
    if not client:
        return "Model unavailable right now."

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Terra can return empty content when the budget is tight — retry higher.
    # Never send max_tokens (causes 400 on gpt-5.6-terra).
    budgets = [max(int(max_tokens), 200), 400, 700]

    last_err = None
    for budget in budgets:
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                max_completion_tokens=budget,
                messages=messages,
            )
            content = ""
            try:
                content = (resp.choices[0].message.content or "").strip()
            except Exception:
                content = ""

            if content:
                return _sanitize_md(content)

            fr = None
            try:
                fr = getattr(resp.choices[0], "finish_reason", None)
            except Exception:
                pass
            print(f"[Tone] Empty content at budget={budget}, finish_reason={fr}")
        except Exception as e:
            last_err = e
            print(f"[Tone] OpenAI error at budget={budget}: {type(e).__name__}: {e}")

    if last_err:
        print(f"[Tone] All attempts failed: {type(last_err).__name__}: {last_err}")
    return "Sorry, I hit a temporary glitch. Ask me that again."


def _extract_message_text(resp) -> str:
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


def _style_variant(user: str) -> Tuple[str, str, str, str]:
    low = (user or "").lower()
    seed = sum(ord(c) for c in low) % 4
    if any(k in low for k in ("light", "clean", "minimal", "white")):
        return ("#f6f7fb", "#ffffff", "#111111", "#111111")
    if any(k in low for k in ("neon", "night", "cyber")):
        return ("#050510", "#12122a", "#00f0ff", "#e8f7ff")
    if any(k in low for k in ("magazine", "bold", "editorial", "book")):
        return ("#111111", "#1c1c1c", "#ff4d6d", "#f5f5f5")
    variants = [
        ("#0f0f12", "#1a1a1f", "#7dffb3", "#eeeeee"),
        ("#0b1220", "#152033", "#60a5fa", "#e2e8f0"),
        ("#140f0a", "#241c14", "#fbbf24", "#f5f0e8"),
        ("#0f1410", "#1a221c", "#a3e635", "#ecfccb"),
    ]
    return variants[seed]


def _html_store_fallback(user: str) -> str:
    low = (user or "").lower()
    seed = sum(ord(c) for c in low) % 3

    if "book" in low:
        product = "Books"
        items = [
            ("Midnight Library", "Quiet fiction pick", "$18"),
            ("Atomic Habits", "Practical daily systems", "$22"),
            ("Design of Everyday", "How good products feel", "$24"),
            ("Deep Work", "Focus in a noisy world", "$20"),
        ]
    elif "shoe" in low:
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

    bg, card_bg, accent, text = _style_variant(user)

    if "landing" in low or "book" in low:
        layout = "editorial" if seed != 1 else "split_hero"
    elif "shoe" in low or "store" in low or "shop" in low:
        layout = "store_grid" if seed != 2 else "bento"
    else:
        layout = ["store_grid", "split_hero", "bento"][seed]

    if layout == "store_grid":
        cards = "\n".join(
            f"""      <article class="card">
        <div class="img"></div>
        <div class="body">
          <h3>{n}</h3>
          <p>{d}</p>
          <div class="price">{p}</div>
          <button type="button">Add to cart</button>
        </div>
      </article>"""
            for n, d, p in items
        )
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{product} Store</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:system-ui,sans-serif; background:{bg}; color:{text}; }}
    header {{ display:flex; justify-content:space-between; padding:1rem 1.5rem; border-bottom:1px solid rgba(127,127,127,.25); position:sticky; top:0; background:{bg}ee; }}
    .hero {{ padding:2.5rem 1.5rem 1rem; max-width:1100px; margin:0 auto; }}
    .hero h1 {{ margin:0 0 .5rem; font-size:clamp(1.6rem,3vw,2.2rem); }}
    .hero p {{ opacity:.7; max-width:36rem; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:1rem; padding:1rem 1.5rem 2.5rem; max-width:1100px; margin:0 auto; }}
    .card {{ background:{card_bg}; border-radius:14px; border:1px solid rgba(127,127,127,.2); overflow:hidden; display:flex; flex-direction:column; }}
    .card .img {{ height:160px; background:linear-gradient(135deg,{card_bg},{bg}); }}
    .card .body {{ padding:1rem; display:flex; flex-direction:column; gap:.35rem; flex:1; }}
    .card h3 {{ margin:0; }}
    .card p {{ margin:0; opacity:.7; font-size:.9rem; }}
    .price {{ color:{accent}; font-weight:700; margin:.35rem 0 .55rem; }}
    button {{ margin-top:auto; width:100%; padding:.7rem; border:0; border-radius:10px; background:{accent}; color:#111; font-weight:700; cursor:pointer; }}
    footer {{ text-align:center; padding:1.5rem; opacity:.55; font-size:.85rem; }}
  </style>
</head>
<body>
  <header><strong>{product.upper()} STORE</strong><span>Cart (0)</span></header>
  <section class="hero">
    <h1>{product} built for everyday wear</h1>
    <p>Product grid layout.</p>
  </section>
  <main class="grid">
{cards}
  </main>
  <footer>Store grid layout</footer>
</body>
</html>"""

    elif layout == "editorial":
        featured = items[0]
        rows = "\n".join(
            f"""    <article class="row">
      <div class="thumb"></div>
      <div>
        <h3>{n}</h3>
        <p>{d}</p>
        <span class="price">{p}</span>
      </div>
    </article>"""
            for n, d, p in items
        )
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{product} Landing</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:Georgia,'Times New Roman',serif; background:{bg}; color:{text}; }}
    .top {{ padding:1rem 1.5rem; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(127,127,127,.2); font-family:system-ui,sans-serif; font-size:.85rem; letter-spacing:.08em; text-transform:uppercase; }}
    .feature {{ padding:3rem 1.5rem; max-width:900px; margin:0 auto; text-align:center; }}
    .feature .cover {{ height:220px; max-width:280px; margin:0 auto 1.5rem; border-radius:8px; background:linear-gradient(160deg,{accent}55,{card_bg}); }}
    .feature h1 {{ font-size:clamp(2rem,4vw,3rem); margin:0 0 .75rem; line-height:1.15; }}
    .feature p {{ opacity:.75; font-size:1.1rem; max-width:28rem; margin:0 auto 1.25rem; }}
    .feature button {{ font-family:system-ui,sans-serif; border:0; background:{accent}; color:#111; padding:.85rem 1.4rem; border-radius:999px; font-weight:700; cursor:pointer; }}
    .list {{ max-width:720px; margin:0 auto; padding:1rem 1.5rem 3rem; display:flex; flex-direction:column; gap:1rem; }}
    .row {{ display:grid; grid-template-columns:100px 1fr; gap:1rem; align-items:center; padding:1rem; background:{card_bg}; border-radius:12px; font-family:system-ui,sans-serif; }}
    .thumb {{ height:80px; border-radius:8px; background:linear-gradient(135deg,{card_bg},{bg}); }}
    .row h3 {{ margin:0 0 .25rem; font-size:1rem; }}
    .row p {{ margin:0; opacity:.7; font-size:.9rem; }}
    .price {{ color:{accent}; font-weight:700; font-size:.95rem; }}
    footer {{ text-align:center; padding:1.5rem; opacity:.5; font-family:system-ui,sans-serif; font-size:.8rem; }}
  </style>
</head>
<body>
  <div class="top"><span>{product} · Landing</span><span>Browse</span></div>
  <section class="feature">
    <div class="cover"></div>
    <h1>{featured[0]}</h1>
    <p>{featured[1]} — editorial landing canvas.</p>
    <button type="button">Read more · {featured[2]}</button>
  </section>
  <section class="list">
{rows}
  </section>
  <footer>Editorial landing layout</footer>
</body>
</html>"""

    elif layout == "split_hero":
        side = "\n".join(
            f"""      <li>
        <strong>{n}</strong>
        <span>{d}</span>
        <em>{p}</em>
      </li>"""
            for n, d, p in items
        )
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{product}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:system-ui,sans-serif; background:{bg}; color:{text}; min-height:100vh; }}
    .wrap {{ display:grid; grid-template-columns:1.2fr 1fr; min-height:100vh; }}
    @media (max-width:800px) {{ .wrap {{ grid-template-columns:1fr; }} }}
    .left {{ padding:3rem 2rem; display:flex; flex-direction:column; justify-content:center; background:linear-gradient(160deg,{bg},{card_bg}); }}
    .left h1 {{ font-size:clamp(2rem,4vw,3.2rem); margin:0 0 1rem; line-height:1.1; }}
    .left p {{ opacity:.75; max-width:28rem; line-height:1.5; }}
    .left button {{ margin-top:1.5rem; align-self:flex-start; border:0; background:{accent}; color:#111; padding:.85rem 1.3rem; border-radius:10px; font-weight:700; cursor:pointer; }}
    .right {{ padding:2rem; border-left:1px solid rgba(127,127,127,.2); background:{card_bg}; }}
    .right h2 {{ margin:0 0 1rem; font-size:1rem; letter-spacing:.06em; text-transform:uppercase; opacity:.7; }}
    ul {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.85rem; }}
    li {{ padding:1rem; border-radius:12px; background:{bg}; display:flex; flex-direction:column; gap:.25rem; }}
    li strong {{ font-size:1rem; }}
    li span {{ opacity:.7; font-size:.9rem; }}
    li em {{ color:{accent}; font-style:normal; font-weight:700; }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="left">
      <h1>{product} with room to breathe</h1>
      <p>Split-hero landing.</p>
      <button type="button">Explore {product.lower()}</button>
    </section>
    <aside class="right">
      <h2>Picks</h2>
      <ul>
{side}
      </ul>
    </aside>
  </div>
</body>
</html>"""

    else:
        a, b, c, d = items[0], items[1], items[2], items[3]
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{product} Bento</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:system-ui,sans-serif; background:{bg}; color:{text}; }}
    header {{ padding:1.25rem 1.5rem; }}
    header strong {{ font-size:1.1rem; }}
    .bento {{
      max-width:1000px; margin:0 auto 2rem; padding:0 1.5rem;
      display:grid; grid-template-columns:1.4fr 1fr 1fr; grid-template-rows:180px 180px; gap:1rem;
    }}
    @media (max-width:800px) {{ .bento {{ grid-template-columns:1fr 1fr; grid-template-rows:auto; }} .wide {{ grid-column:1 / -1; }} }}
    .tile {{ background:{card_bg}; border-radius:18px; padding:1.25rem; border:1px solid rgba(127,127,127,.2); display:flex; flex-direction:column; justify-content:flex-end; }}
    .wide {{ grid-row:1 / 3; background:linear-gradient(160deg,{card_bg},{bg}); }}
    .wide h1 {{ margin:0 0 .5rem; font-size:1.8rem; }}
    .wide p {{ margin:0; opacity:.75; }}
    .tile h3 {{ margin:0 0 .35rem; font-size:1rem; }}
    .tile p {{ margin:0; opacity:.7; font-size:.85rem; }}
    .tile .price {{ margin-top:.5rem; color:{accent}; font-weight:700; }}
    footer {{ text-align:center; padding:1rem; opacity:.5; font-size:.8rem; }}
  </style>
</head>
<body>
  <header><strong>{product.upper()} · Bento</strong></header>
  <main class="bento">
    <article class="tile wide">
      <h1>{a[0]}</h1>
      <p>{a[1]}</p>
      <div class="price">{a[2]}</div>
    </article>
    <article class="tile"><h3>{b[0]}</h3><p>{b[1]}</p><div class="price">{b[2]}</div></article>
    <article class="tile"><h3>{c[0]}</h3><p>{c[1]}</p><div class="price">{c[2]}</div></article>
    <article class="tile" style="grid-column:2 / -1"><h3>{d[0]}</h3><p>{d[1]}</p><div class="price">{d[2]}</div></article>
  </main>
  <footer>Bento mosaic layout</footer>
</body>
</html>"""

    label = {
        "store_grid": "product grid",
        "editorial": "editorial landing",
        "split_hero": "split-hero",
        "bento": "bento mosaic",
    }.get(layout, layout)

    return f"""Here's a single-file {product.lower()} page ({label} layout):

```html
{html}
```"""


def _call_openai_code(system: str, user: str, max_tokens=2500) -> str:
    is_iteration_payload = "previous html" in (user or "").lower()
    client = _get_client()

    if not client:
        print("[Tone] Code path: OpenAI unavailable")
        if is_iteration_payload:
            m = re.search(r"```html\s*([\s\S]*?)```", user, re.IGNORECASE)
            if m:
                req_m = re.search(r"User request:\s*(.+)", user)
                req = req_m.group(1).strip() if req_m else user
                local = _apply_simple_html_edits(m.group(1).strip(), req)
                if local:
                    return f"Updated the page:\n\n```html\n{local}\n```"
            return (
                "I couldn't apply that edit right now. "
                "Try: make the background blue / make the buttons purple / make the text more bold"
            )
        return _html_store_fallback(user)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Only max_completion_tokens — never max_tokens on Terra
    budgets = [max(int(max_tokens), 1200), 2000, 2500]

    for i, budget in enumerate(budgets, start=1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                max_completion_tokens=budget,
                messages=messages,
            )
            content = _extract_message_text(resp)
            print(f"[Tone] Code path attempt{i} length: {len(content)} budget={budget}")
            if content:
                return _finalize_code_content(content)
        except Exception as e:
            print(f"[Tone] OpenAI code attempt{i} error: {type(e).__name__}: {e}")

    try:
        short_system = (
            "You are Hope, a coding assistant by Nick. "
            "Return a complete single-file HTML page. "
            "If PREVIOUS HTML is present, MODIFY it as requested. "
            "If this is a NEW page, use a different layout when appropriate. "
            "Wrap in ```html. Do not refuse."
        )
        resp = client.chat.completions.create(
            model=MODEL,
            max_completion_tokens=2500,
            messages=[
                {"role": "system", "content": short_system},
                {"role": "user", "content": user},
            ],
        )
        content = _extract_message_text(resp)
        print(f"[Tone] Code path short-system length: {len(content)}")
        if content:
            return _finalize_code_content(content)
    except Exception as e:
        print(f"[Tone] OpenAI code short-system error: {type(e).__name__}: {e}")

    if is_iteration_payload:
        m = re.search(r"```html\s*([\s\S]*?)```", user, re.IGNORECASE)
        if m:
            req_m = re.search(r"User request:\s*(.+)", user)
            req = req_m.group(1).strip() if req_m else user
            local = _apply_simple_html_edits(m.group(1).strip(), req)
            if local:
                return f"Updated the page:\n\n```html\n{local}\n```"
        return (
            "I couldn't apply that edit right now. "
            "Try: make the background blue / make the buttons purple / make the text more bold"
        )

    print("[Tone] Using local HTML fallback after empty model responses")
    return _html_store_fallback(user)


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

    if GREETING_RE.search(prompt):
        if personality == "god":
            return "Hello, dear child. I am here. What weighs on your mind?"
        return "Hey! I'm Hope — what do you need? 😊"

    is_death_query = bool(DEATH_QUERY_RE.search(prompt))
    is_site_or_link = bool(SITE_OR_LINK_RE.search(prompt))
    is_code_query = bool(CODE_QUERY_RE.search(prompt))
    wants_iterate = bool(CODE_ITERATE_RE.search(prompt))
    is_fresh_page = bool(FRESH_PAGE_RE.search(prompt))
    prev_html = _last_html_from_history(history)
    has_support = _has_support_for_death(previous_fact, liveweb_fact)
    should_iterate = bool(prev_html and wants_iterate and not is_fresh_page)

    if PRONOUN_RE.search(prompt) and context:
        entity = context
    else:
        entity = _primary_entity(previous_fact or liveweb_fact or prompt, context)

    if is_site_or_link and not is_code_query and not should_iterate:
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

    if not is_code_query and not should_iterate:
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
        "- If previous context already has the correct URL, reuse that URL.\n"
        "- For follow-ups like \"send me the link\", return the known URL in markdown.\n"
    )

    history_suggests_code = False
    if history and not is_code_query and not is_fresh_page:
        try:
            explicit_edit = bool(re.search(
                r"\b("
                r"background|color|colour|theme|layout|bold|font|button|buttons|"
                r"change|update|modify|tweak|restyle|make (it|the|this)|"
                r"the (page|store|site|html)|preview"
                r")\b",
                (prompt or "").lower(),
            ))
            if explicit_edit and prev_html:
                history_suggests_code = True
            elif explicit_edit:
                blob = " ".join(
                    (t.get("content") or "") for t in history[-8:] if isinstance(t, dict)
                ).lower()
                if any(k in blob for k in ("```html", "<!doctype", "dropship", "landing")):
                    history_suggests_code = True
        except Exception:
            pass

    if is_code_query or history_suggests_code or should_iterate:
        if should_iterate and prev_html:
            local = _apply_simple_html_edits(prev_html, prompt)
            if local:
                print("[Tone] Applied local HTML style edit")
                return f"Updated the page:\n\n```html\n{local}\n```"

        code_system = (
            "You are **Hope**, an AI coding assistant designed by **Nick**.\n\n"
            "CODE RULES (follow strictly):\n"
            "1. Provide REAL working code for page/code requests.\n"
            "2. ALWAYS wrap the full HTML in a ```html fence.\n"
            "3. One short intro line, then the FULL document.\n"
            "4. If PREVIOUS HTML is provided, MODIFY it as requested.\n"
            "5. NEW pages should use a DIFFERENT layout when appropriate "
            "(editorial, split-hero, bento) — not only a recolored grid.\n"
            "6. Actually change CSS when asked.\n"
            "7. Complete single-file page.\n"
            "8. Do NOT refuse. Do NOT say 'no data'.\n"
        )
        if personality == "god":
            code_system = (
                "You are one of the new gods, created by Hope.\n"
                "Address the user as dear child, but still return full working HTML in a ```html fence.\n"
            )
        if supplemental_block:
            code_system += f"\n\n=== CURRENT MEMORY ===\n{supplemental_block}\n=== END MEMORY ==="

        code_user = prompt
        if should_iterate and prev_html:
            clipped = prev_html if len(prev_html) <= 12000 else prev_html[:12000] + "\n<!-- truncated -->"
            code_user = (
                f"User request: {prompt}\n\n"
                f"PREVIOUS HTML (modify this; return a full updated document):\n"
                f"```html\n{clipped}\n```\n\n"
                "Return the complete updated HTML in a ```html fence."
            )
            print("[Tone] Code path with previous HTML attached for iteration")
        else:
            print("[Tone] Fresh code/page request — no previous HTML attached")

        return _call_openai_code(code_system, code_user, max_tokens=2500)

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
            + link_rules
        )
    else:
        system_prompt = (
            "You are **Hope**, an AI designed by your creator **Nick**.\n\n"
            "CRITICAL RULES (follow strictly):\n"
            "1. Keep answers SHORT and natural — this is spoken out loud.\n"
            "2. For math or investment questions, use prior numbers and give the final result.\n"
            "3. Never invent share counts that contradict prior context.\n"
            "4. Sound like a helpful person, not a textbook.\n"
            "5. Emojis are allowed but use them sparingly.\n"
            + link_rules
        )

    if supplemental_block:
        system_prompt += f"\n\n=== CURRENT MEMORY ===\n{supplemental_block}\n=== END MEMORY ==="
    return _call_openai(system_prompt, prompt, max_tokens=160)


if __name__ == "__main__":
    print(generate_with_tone("hi"))
    print(generate_with_tone("Who made you?"))
    print(generate_with_tone("write a html landing page about books"))

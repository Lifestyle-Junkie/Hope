"""
backend.py
Hope v2 API server
- Session memory via memory.py
- Sanitize via sanitize.py
- Yahoo Finance quotes via market.py
- Safer stock detection / link memory / ElevenLabs / Discord
"""
from __future__ import annotations
import os
import re
import threading
import traceback
import importlib.metadata
from typing import Optional, Dict, Any, List, Tuple
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests

from sanitize import sanitize_reply
from memory import (
    WEB_MEMORY_KEY,
    get_session,
    update_session,
    topic_of,
    same_topic,
    clear_web_memory,
    STOPWORDS,
)

# ---------- Version Diagnostics ----------
try:
    print(f"[Debug] Flask version: {importlib.metadata.version('flask')}")
except Exception:
    pass
try:
    import openai
    print(f"[Debug] OpenAI lib present.")
except Exception:
    openai = None  # type: ignore
    print("[Debug] OpenAI import failed.")


def safe_import(name: str):
    try:
        m = __import__(name)
        print(f"[Debug] Imported {name}.py")
        return m
    except Exception as e:
        print(f"[Error] Import {name} failed: {e}")
        return None


tone = safe_import("tone")
emailer = safe_import("emailer")
image_mod = safe_import("image")
liveweb = safe_import("liveweb") or safe_import("Liveweb")
market = safe_import("market")

print("📂 Working directory:", os.getcwd())
for fn in [
    "tone.py", "emailer.py", "image.py", "liveweb.py", "Liveweb.py",
    "discord_bot.py", "market.py", "sanitize.py", "memory.py",
]:
    if os.path.exists(fn):
        print(f"✅ {fn} found")

# ---------- OpenAI Key ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
print(f"[Debug] OpenAI key loaded (length: {len(OPENAI_API_KEY)} chars).")
OPENAI_AVAILABLE = bool(OPENAI_API_KEY and openai)
if not OPENAI_AVAILABLE:
    print("⚠️ OPENAI_API_KEY not set or openai lib missing. Tone generation disabled.")
else:
    openai.api_key = OPENAI_API_KEY
    print("🔐 OpenAI enabled.")

# ---------- ElevenLabs Config ----------
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = "weA4Q36twV5kwSaTEL0Q"

# ---------- Flask App ----------
app = Flask(__name__)
CORS(app)

# ---------- Regex / constants still used by routes ----------
PRONOUN_RE = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|theirs)\b", re.IGNORECASE)
VAGUE_FOLLOWUP_RE = re.compile(
    r"\b(who was (he|she|that)|what did (he|she|they)|who was the killer|what did he represent|"
    r"how did (he|she|they) die|what about|and if|what if|if (it|that|they|he|she)|"
    r"what would|how much would|how many would|my (money|investment|1k|thousand)|"
    r"at that price|at the price|goes to|reaches|turns to|what would my|"
    r"on top of|like of|the 1k|of the|that one|same one|previous|earlier)\b",
    re.IGNORECASE
)
NUMBER_FOLLOWUP_RE = re.compile(r"\b(\d+[\d,]*\.?\d*\s*\$?|\$\s*\d+|\d+\s*shares?|1k|thousand)\b", re.IGNORECASE)
CAP_SEQ_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
BOLD_ENTITY_RE = re.compile(r"\*\*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\*\*")

LINK_FOLLOWUP_RE = re.compile(
    r"^\s*((please|pls|can you|could you)\s+)?"
    r"(send|give|drop|share|post)?\s*"
    r"(me\s+)?(the\s+)?(link|url|website|site)\s*\??\s*$",
    re.IGNORECASE
)
LINK_TO_RE = re.compile(
    r"\b(?:(?:official|the)\s+)?(?:link|url|website|site)\s+(?:to|for)\s+([A-Za-z0-9][\w.-]*)\b",
    re.IGNORECASE
)
URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|co|app|ai|gg|tv|me|us|uk|ca|de|fr|nz)\b",
    re.IGNORECASE
)

STOCK_KEYWORD_RE = re.compile(
    r"\b(stock|share|shares|ticker|quote|trading at|price of|stock price|share price|"
    r"current price|at rn|right now price|market cap)\b",
    re.IGNORECASE
)
STOCK_FOLLOWUP_RE = re.compile(
    r"\b(check( it)? again|check again|update( it)?|refresh|price now|how about now|"
    r"what(?:'s| is)? (?:it|that|the price) now)\b",
    re.IGNORECASE
)
IDENTITY_RE = re.compile(
    r"\b(who made you|who created you|who designed you|who are you|what are you|"
    r"what(?:'s| is)? your name|are you (an ai|a bot)|who is hope|who is god)\b",
    re.IGNORECASE
)
WHAT_IS_RE = re.compile(
    r"^\s*(what(?:'s| is| are)|who is|tell me about|explain)\b",
    re.IGNORECASE
)

COMPANY_TO_TICKER = {
    "shopify": "SHOP", "apple": "AAPL", "comcast": "CMCSA", "tesla": "TSLA",
    "nvidia": "NVDA", "microsoft": "MSFT", "amazon": "AMZN", "google": "GOOGL",
    "alphabet": "GOOGL", "meta": "META", "facebook": "META", "netflix": "NFLX",
    "disney": "DIS", "amd": "AMD", "intel": "INTC", "coinbase": "COIN",
    "robinhood": "HOOD",
}

SITE_NAME_TO_URL = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "yahoo": "https://www.yahoo.com",
    "rainbet": "https://rainbet.com",
    "shopify": "https://www.shopify.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "reddit": "https://www.reddit.com",
    "github": "https://github.com",
    "openai": "https://openai.com",
    "amazon": "https://www.amazon.com",
    "netflix": "https://www.netflix.com",
    "apple": "https://www.apple.com",
    "microsoft": "https://www.microsoft.com",
    "tesla": "https://www.tesla.com",
}

IGNORE_TICKERS = {
    "WHAT", "IS", "THE", "FOR", "AND", "NOW", "RN", "PRICE", "STOCK",
    "SHARE", "SHARES", "HOW", "MUCH", "AT", "TODAY", "CURRENT",
    "CHECK", "AGAIN", "WHEN", "WAS", "IT", "THIS", "THAT", "UPDATE",
    "ME", "MY", "ON", "OF", "TO", "A", "AN", "RIGHT", "ABOUT", "WITH",
    "FROM", "JUST", "LIKE", "CAN", "YOU", "GET", "GIVE", "SHOW", "TELL",
    "WHO", "HI", "HEY", "HELLO", "MADE", "CREATE", "CREATED", "DESIGN",
    "DESIGNED", "NAME", "HOPE", "GOD", "YES", "NO", "OK", "OKAY", "PLS",
    "PLEASE", "THANKS", "THANK", "WHY", "WHERE", "WHICH", "YOUR",
    "ARE", "AM", "BE", "DO", "DID", "DOES", "HAVE", "HAS", "HAD",
    "U", "I", "GO", "OR", "IF", "SO", "WE", "US", "BY", "AS", "UP",
    "IN", "OUT", "ALL", "ANY", "NOT", "BUT", "PER", "VIA", "LINK", "URL",
    "SITE", "WEBSITE", "OFFICIAL",
}


def _extract_entity_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    text = sanitize_reply(text)
    bolds = BOLD_ENTITY_RE.findall(text)
    for b in bolds:
        if b.lower() not in STOPWORDS and len(b) > 2 and b.lower() != "note":
            return b
    caps = CAP_SEQ_RE.findall(text)
    for c in caps:
        if c.lower() not in STOPWORDS and len(c) > 2:
            return c
    return None


def _extract_url_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = sanitize_reply(text)
    md = MD_LINK_RE.search(text)
    if md:
        return md.group(2).rstrip(".,);]")
    m = URL_RE.search(text)
    if m:
        return m.group(0).rstrip(".,);]\"'")
    d = DOMAIN_RE.search(text)
    if d:
        return f"https://{d.group(0).lower()}"
    return None


def _format_md_link(url: str) -> str:
    host = re.sub(r"^https?://(www\.)?", "", url, flags=re.IGNORECASE).split("/")[0]
    return f"[{host}]({url})"


def _is_unverified_death_line(text: str) -> bool:
    if not text:
        return False
    return "**Note:**" in text and (
        "unverified" in text.lower()
        or "no reliable" in text.lower()
        or "unconfirmed" in text.lower()
    )


def error_response(msg: str, status=500):
    return jsonify({"error": msg}), status


def merge_facts(previous_fact: Optional[str], liveweb_fact: Optional[str]) -> Optional[str]:
    previous_fact = sanitize_reply(previous_fact) if previous_fact else None
    liveweb_fact = sanitize_reply(liveweb_fact) if liveweb_fact else None
    if previous_fact and liveweb_fact:
        if liveweb_fact.lower().startswith("**note:**"):
            return previous_fact
        if previous_fact.lower().startswith("**note:**"):
            return liveweb_fact
        if previous_fact == liveweb_fact:
            return previous_fact
        return f"{previous_fact} | {liveweb_fact}"
    return previous_fact or liveweb_fact


def _concise_trim(text: str) -> str:
    if not text:
        return text
    first = re.split(r"(?<=[.!?])\s+", text)[0].strip()
    if len(first) > 10:
        return first
    return text[:160]


def _extract_company_ticker(prompt: str) -> Optional[str]:
    lower = (prompt or "").lower()
    for name, ticker in COMPANY_TO_TICKER.items():
        if re.search(rf"\b{re.escape(name)}\b", lower):
            return ticker
    return None


def _extract_explicit_ticker(prompt: str) -> Optional[str]:
    text = (prompt or "").strip()
    candidates = re.findall(r"\b[A-Z]{2,5}\b", text)
    if not candidates:
        candidates = re.findall(r"\b[A-Z]{2,5}\b", text.upper())
    for tok in candidates:
        up = tok.upper()
        if up not in IGNORE_TICKERS and 2 <= len(up) <= 5:
            return up
    return None


def _looks_like_stock_question(prompt: str, has_last_ticker: bool = False) -> bool:
    if not prompt:
        return False
    if IDENTITY_RE.search(prompt):
        return False
    if WHAT_IS_RE.search(prompt) and not STOCK_KEYWORD_RE.search(prompt):
        return False
    company = _extract_company_ticker(prompt)
    explicit = _extract_explicit_ticker(prompt)
    has_stock_kw = bool(STOCK_KEYWORD_RE.search(prompt))
    is_followup = bool(STOCK_FOLLOWUP_RE.search(prompt))
    if company and has_stock_kw:
        return True
    if explicit and has_stock_kw:
        return True
    if explicit and re.fullmatch(r"[A-Za-z]{2,5}\??", prompt.strip()):
        return True
    if has_last_ticker and is_followup:
        return True
    return False


def _link_request_reply(prompt: str) -> Optional[Tuple[str, str]]:
    if not prompt:
        return None
    name = None
    m = LINK_TO_RE.search(prompt)
    if m:
        name = m.group(1).lower().strip(".,!?")
    else:
        if re.search(r"\b(link|url|website|site)\b", prompt, re.IGNORECASE):
            m2 = re.search(
                r"\b(?:link|url|website|site)\b.*?\b([A-Za-z][A-Za-z0-9.-]{1,30})\b",
                prompt,
                re.IGNORECASE,
            )
            if m2:
                name = m2.group(1).lower().strip(".,!?")
    if not name or name in STOPWORDS or name in {"official", "the", "me", "a", "an", "for", "to"}:
        return None
    url = SITE_NAME_TO_URL.get(name)
    if not url:
        if re.fullmatch(r"[a-z0-9-]+", name) and len(name) >= 3:
            url = f"https://www.{name}.com"
        else:
            return None
    reply = f"Here you go: {_format_md_link(url)}"
    return reply, url


def _quote_reply_for_prompt(prompt: str, last_ticker: Optional[str] = None) -> Optional[Tuple[str, str]]:
    if not market or not hasattr(market, "get_quote"):
        return None
    has_last = bool(last_ticker)
    if not _looks_like_stock_question(prompt, has_last_ticker=has_last):
        return None
    ticker = _extract_company_ticker(prompt) or _extract_explicit_ticker(prompt)
    if not ticker and has_last and STOCK_FOLLOWUP_RE.search(prompt or ""):
        ticker = last_ticker
    if not ticker:
        return None
    if re.search(
        r"\b(when was|what day|which day|history|historical|last time it)\b",
        prompt or "",
        re.IGNORECASE,
    ):
        return None
    print(f"[Market] Detected stock question for ticker={ticker}")
    q = market.get_quote(ticker)
    if not q:
        return (f"I couldn't fetch a live quote for **{ticker}** right now.", ticker)
    price = q.get("price")
    prev = q.get("previous_close")
    chg = q.get("change_percent")
    if price is None:
        return (f"I couldn't get a current price for **{ticker}**.", ticker)
    if prev is not None and chg is not None:
        direction = "up" if chg >= 0 else "down"
        reply = (
            f"**{ticker}** is around **${price:,.2f}** right now. "
            f"Previous close was **${prev:,.2f}** ({direction} {abs(chg):.2f}%)."
        )
    else:
        reply = f"**{ticker}** is around **${price:,.2f}** right now."
    return (reply, ticker)


# ---------- Core Route ----------
@app.route("/ask", methods=["POST", "OPTIONS"])
def ask():
    if request.method == "OPTIONS":
        return ("", 200)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return error_response("Invalid JSON", 400)

    user_prompt = (data.get("message") or "").strip()
    concise = bool(data.get("concise", True))
    explicit_context = data.get("context") or None
    previous_fact_client = data.get("previous_fact") or None
    image_data = data.get("image") or None
    personality = (data.get("personality") or "hope").lower().strip()
    print(f"[Ask] Incoming: {user_prompt!r} concise={concise} personality={personality}")

    if not user_prompt and not image_data:
        return error_response("Empty prompt", 400)

    vision_description = None
    if image_data and image_mod and hasattr(image_mod, "process_image_upload"):
        try:
            vision_description = image_mod.process_image_upload(image_data)
        except Exception as e:
            print(f"[Image] Error: {e}")

    if personality == "god":
        session_id = f"discord-{(request.remote_addr or 'anon')}"
    else:
        session_id = WEB_MEMORY_KEY

    session_data = get_session(session_id) or {}
    last_person = session_data.get("last_person") or ""
    last_fact_mem = sanitize_reply(session_data.get("last_fact") or "")
    last_topic = session_data.get("last_topic") or ""
    last_ticker = session_data.get("last_ticker") or ""
    last_url = session_data.get("last_url") or ""
    history: List[Dict[str, str]] = session_data.get("history") or []
    history = [
        {"role": h.get("role", "user"), "content": sanitize_reply(h.get("content") or "")}
        for h in history
    ]

    new_topic = topic_of(user_prompt)
    topic_overlap = same_topic(last_topic, new_topic)
    pronoun_detected = PRONOUN_RE.search(user_prompt)
    vague_followup_detected = VAGUE_FOLLOWUP_RE.search(user_prompt)
    number_followup = NUMBER_FOLLOWUP_RE.search(user_prompt)
    link_followup = bool(LINK_FOLLOWUP_RE.match(user_prompt))
    word_count = len(user_prompt.split())
    is_short_message = word_count <= 12

    reuse_context = False
    if (pronoun_detected or vague_followup_detected or number_followup
            or topic_overlap or is_short_message or link_followup):
        reuse_context = True
    if explicit_context:
        reuse_context = True
    if last_fact_mem and is_short_message:
        reuse_context = True

    chosen_context_person = explicit_context if explicit_context else (last_person if reuse_context else None)
    chosen_previous_fact = previous_fact_client or (last_fact_mem if reuse_context else None)

    print(
        f"[Session] id={session_id} Reuse: {reuse_context} | Short: {is_short_message} | "
        f"Words: {word_count} | History: {len(history)} | last_ticker={last_ticker} | last_url={last_url}"
    )

    link_req = _link_request_reply(user_prompt)
    if link_req:
        reply, url = link_req
        reply = sanitize_reply(reply)
        new_history = history + [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": reply},
        ]
        update_session(
            session_id,
            last_person=None,
            last_fact=reply[:400],
            last_topic=new_topic or "website",
            history=new_history,
            last_ticker=None,
            last_url=url,
        )
        return jsonify({
            "reply": reply,
            "context_used": False,
            "liveweb_raw": None,
            "liveweb_analyzed": None,
            "vision_note": vision_description if vision_description else None,
            "memory": {
                "last_person": None,
                "topic_overlap": False,
                "topic": new_topic or "website",
                "last_ticker": None,
                "last_url": url,
                "history_length": len(new_history),
            },
        })

    if link_followup:
        url = last_url or _extract_url_from_text(chosen_previous_fact) or _extract_url_from_text(last_fact_mem)
        if url:
            reply = f"Here you go: {_format_md_link(url)}"
            reply = sanitize_reply(reply)
            store_fact = reply[:400]
            new_history = history + [
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": reply},
            ]
            update_session(
                session_id,
                last_person=None,
                last_fact=store_fact,
                last_topic=new_topic or last_topic or "website",
                history=new_history,
                last_ticker=last_ticker or None,
                last_url=url,
            )
            return jsonify({
                "reply": reply,
                "context_used": True,
                "liveweb_raw": None,
                "liveweb_analyzed": None,
                "vision_note": vision_description if vision_description else None,
                "memory": {
                    "last_person": None,
                    "topic_overlap": topic_overlap,
                    "topic": new_topic or last_topic or "website",
                    "last_ticker": last_ticker or None,
                    "last_url": url,
                    "history_length": len(new_history),
                },
            })

    market_result = _quote_reply_for_prompt(user_prompt, last_ticker=last_ticker or None)
    if market_result:
        reply, used_ticker = market_result
        reply = sanitize_reply(reply)
        store_fact = reply[:400]
        new_history = history + [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": reply},
        ]
        update_session(
            session_id,
            last_person=None,
            last_fact=store_fact,
            last_topic=new_topic or "stocks",
            history=new_history,
            last_ticker=used_ticker,
            last_url=last_url or None,
        )
        return jsonify({
            "reply": reply,
            "context_used": bool(used_ticker),
            "liveweb_raw": None,
            "liveweb_analyzed": None,
            "vision_note": vision_description if vision_description else None,
            "memory": {
                "last_person": None,
                "topic_overlap": topic_overlap,
                "topic": new_topic or "stocks",
                "last_ticker": used_ticker,
                "last_url": last_url or None,
                "history_length": len(new_history),
            },
        })

    liveweb_raw = None
    liveweb_analyzed = None
    if liveweb and hasattr(liveweb, "needs_live_data") and liveweb.needs_live_data(user_prompt):
        search_query = user_prompt
        if "die" in user_prompt.lower() or "death" in user_prompt.lower() or "killer" in user_prompt.lower():
            if chosen_context_person and (pronoun_detected or vague_followup_detected):
                search_query = (
                    search_query
                    .replace("he", chosen_context_person)
                    .replace("she", chosen_context_person)
                    .replace("they", chosen_context_person)
                )
            search_query += " death date"
        print(f"[LiveWeb] Performing live search for: {search_query}")
        try:
            raw, analyzed = liveweb.perform_live_search(search_query)
            liveweb_raw, liveweb_analyzed = raw, sanitize_reply(analyzed or "")
            if liveweb_analyzed:
                print(f"[LiveWeb] Analyzed (trunc): {liveweb_analyzed[:180]}{'...' if len(liveweb_analyzed) > 180 else ''}")
        except Exception as e:
            print(f"[LiveWeb] Error: {e}")

    chained_fact = merge_facts(chosen_previous_fact, liveweb_analyzed)
    effective_prompt = user_prompt
    if vision_description:
        effective_prompt += f"\n\nImage context: {vision_description}"

    reply = None
    if tone and hasattr(tone, "generate_with_tone") and OPENAI_AVAILABLE:
        try:
            reply = tone.generate_with_tone(
                effective_prompt,
                context=chosen_context_person,
                previous_fact=chained_fact,
                liveweb_fact=liveweb_analyzed,
                history=history,
                personality=personality,
            )
        except Exception as e:
            print(f"[Tone] Error: {e}")
            reply = None

    if not reply:
        reply = liveweb_analyzed if liveweb_analyzed else "No data available."

    reply = sanitize_reply(reply)
    if concise:
        reply = _concise_trim(reply)
        reply = sanitize_reply(reply)

    if last_topic and new_topic and not topic_overlap:
        new_entity = _extract_entity_from_text(reply) or _extract_entity_from_text(liveweb_analyzed or "")
    else:
        new_entity = (
            last_person if _is_unverified_death_line(liveweb_analyzed or "") else
            _extract_entity_from_text(reply) or
            _extract_entity_from_text(liveweb_analyzed or "") or
            chosen_context_person
        )

    store_fact = None
    if reply and not _is_unverified_death_line(reply):
        store_fact = reply[:400]
    elif liveweb_analyzed and not _is_unverified_death_line(liveweb_analyzed):
        store_fact = liveweb_analyzed[:300]
    elif chained_fact and not _is_unverified_death_line(chained_fact):
        store_fact = sanitize_reply(chained_fact)[:300]

    found_url = (
        _extract_url_from_text(reply)
        or _extract_url_from_text(liveweb_analyzed)
        or _extract_url_from_text(store_fact)
        or last_url
        or None
    )
    for site_name, site_url in SITE_NAME_TO_URL.items():
        if re.search(rf"\b{re.escape(site_name)}\b", user_prompt, re.IGNORECASE):
            found_url = site_url
            break

    new_history = history + [
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": reply},
    ]
    update_session(
        session_id,
        last_person=new_entity,
        last_fact=store_fact,
        last_topic=new_topic,
        history=new_history,
        last_ticker=last_ticker or None,
        last_url=found_url,
    )

    return jsonify({
        "reply": reply,
        "context_used": bool(chosen_context_person or chosen_previous_fact or link_followup),
        "liveweb_raw": liveweb_raw,
        "liveweb_analyzed": liveweb_analyzed,
        "vision_note": vision_description if vision_description else None,
        "memory": {
            "last_person": new_entity,
            "topic_overlap": topic_overlap,
            "topic": new_topic,
            "last_ticker": last_ticker or None,
            "last_url": found_url,
            "history_length": len(new_history),
        },
    })


@app.route("/welcome", methods=["GET", "POST", "OPTIONS"])
def welcome():
    if request.method == "OPTIONS":
        return ("", 200)
    session_data = get_session(WEB_MEMORY_KEY) or {}
    last_topic = (session_data.get("last_topic") or "").strip()
    last_fact = sanitize_reply(session_data.get("last_fact") or "").strip()
    history = session_data.get("history") or []
    if not history and not last_topic and not last_fact:
        reply = (
            "Welcome back. I'm ready when you are. "
            "Want today's briefing, or do you just want to ask me something?"
        )
    elif last_fact:
        short = re.sub(r"\s+", " ", last_fact)[:110].strip()
        reply = (
            f"Welcome back. Last time we left off around this: {short}. "
            "Want me to catch you up, or give you today's briefing?"
        )
    elif last_topic:
        reply = (
            f"Welcome back. Last time we were on {last_topic}. "
            "Want a quick catch-up, or should I give you today's briefing?"
        )
    else:
        reply = (
            "Welcome back. Want a quick catch-up on our last conversation, "
            "or should I give you today's briefing?"
        )
    reply = sanitize_reply(reply)
    print(f"[Welcome] topic={last_topic!r} history={len(history)}")
    return jsonify({
        "reply": reply,
        "memory": {
            "last_topic": last_topic,
            "has_history": bool(history),
        },
    })


@app.route("/quote", methods=["GET", "OPTIONS"])
def quote():
    if request.method == "OPTIONS":
        return ("", 200)
    if not market or not hasattr(market, "get_quote"):
        return error_response("Market module not available", 500)
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return error_response("Missing symbol", 400)
    q = market.get_quote(symbol)
    if not q:
        return error_response(f"No quote for {symbol}", 404)
    line = market.format_quote_line(q) if hasattr(market, "format_quote_line") else symbol
    return jsonify({
        "symbol": q.get("symbol"),
        "price": q.get("price"),
        "previous_close": q.get("previous_close"),
        "change": q.get("change"),
        "change_percent": q.get("change_percent"),
        "currency": q.get("currency"),
        "market_state": q.get("market_state"),
        "line": line,
    })


@app.route("/speak", methods=["POST", "OPTIONS"])
def speak():
    if request.method == "OPTIONS":
        return ("", 200)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return error_response("Invalid JSON", 400)
    text = (data.get("text") or "").strip()
    if not text:
        return error_response("No text provided", 400)
    clean_text = sanitize_reply(text)
    clean_text = re.sub(r"\*\*(.*?)\*\*", r"\1", clean_text)
    clean_text = re.sub(r"`[^`]+`", "", clean_text)
    clean_text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 \2", clean_text)
    clean_text = clean_text.strip()
    print(f"[Speak] Generating voice for: {clean_text[:80]}...")
    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY,
            },
            json={
                "text": clean_text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
            },
            timeout=30,
        )
        if response.status_code != 200:
            print(f"[Speak] ElevenLabs error: {response.status_code} - {response.text}")
            return error_response(f"ElevenLabs error: {response.status_code}", 500)
        return Response(response.content, mimetype="audio/mpeg")
    except Exception as e:
        print(f"[Speak] Error: {e}")
        return error_response(f"TTS failed: {str(e)}", 500)


@app.route("/send-email", methods=["POST"])
def send_email_route():
    if not emailer:
        return error_response("Emailer module not available", 500)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return error_response("Invalid JSON", 400)
    recipient = data.get("recipient")
    subject = data.get("subject") or "(No Subject)"
    message = data.get("message") or ""
    if not recipient:
        return error_response("Missing recipient", 400)
    if hasattr(emailer, "send_email"):
        try:
            ok, info = emailer.send_email(recipient, subject, message)
            if ok:
                return jsonify({"reply": f"Email sent to {recipient} ✅"})
            return error_response(f"Send failed: {info}", 500)
        except Exception as e:
            print(f"[Email] Error: {e}")
            return error_response("Internal email error", 500)
    return error_response("send_email function not found", 500)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/clear-memory", methods=["POST", "OPTIONS"])
def clear_memory():
    if request.method == "OPTIONS":
        return ("", 200)
    clear_web_memory()
    print("[Memory] Cleared WEB_MEMORY_KEY")
    return jsonify({"ok": True, "cleared": WEB_MEMORY_KEY})


_discord_started = False


def _start_discord_background():
    global _discord_started
    if _discord_started:
        return
    _discord_started = True

    def run_discord():
        try:
            from discord_bot import start_discord_bot
            print("🤖 Starting Discord bot...")
            start_discord_bot()
        except Exception as e:
            print(f"[Discord] Failed to start: {e}")

    t = threading.Thread(target=run_discord, daemon=True)
    t.start()
    print("🤖 Discord bot thread started (gunicorn mode)")


_start_discord_background()

if __name__ == "__main__":
    host = os.getenv("HOPE_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("HOPE_PORT", "5002")))
    debug = False
    print("🚀 Starting Hope v2 Backend + Discord...")
    print(f"📡 Listening: http://{host}:{port}")
    print("🔐 OpenAI enabled:" if OPENAI_AVAILABLE else "🛑 OpenAI disabled (no key).")
    print("🎤 ElevenLabs voice enabled.")
    print("📈 Market quotes enabled:" if market else "🛑 Market module missing.")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\nShutting down.")
    except Exception as e:
        print(f"[Fatal] {e}")
        traceback.print_exc()

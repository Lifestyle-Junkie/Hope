"""
backend.py
Hope v2 API server
- sanitize.py / memory.py / links.py / market.py
- ElevenLabs + Discord
- /browse-frame for live browser panel
- browse_mode: Computer Use only when the globe icon is on
- /ask-stream: SSE token stream so the UI can paint the reply as it arrives
- /maps-embed: Google Maps directions iframe (key stays in Railway)
"""
from __future__ import annotations
import os
import re
import json
import threading
import traceback
import importlib.metadata
from typing import Optional, Dict, Any, List, Iterator
from flask import Flask, request, jsonify, Response, redirect
from urllib.parse import quote as urlquote
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
from links import (
    is_link_followup,
    extract_url_from_text,
    format_md_link,
    link_request_reply,
    prefer_site_url_from_prompt,
)
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
    "discord_bot.py", "market.py", "sanitize.py", "memory.py", "links.py",
    "webagent.py",
]:
    if os.path.exists(fn):
        print(f"✅ {fn} found")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
print(f"[Debug] OpenAI key loaded (length: {len(OPENAI_API_KEY)} chars).")
OPENAI_AVAILABLE = bool(OPENAI_API_KEY and openai)
if not OPENAI_AVAILABLE:
    print("⚠️ OPENAI_API_KEY not set or openai lib missing. Tone generation disabled.")
else:
    openai.api_key = OPENAI_API_KEY
    print("🔐 OpenAI enabled.")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = "DAQ2lZdypaQsApLOpVPq"
MAPS_API_KEY = os.getenv("MAPS_API_KEY", "")
print(f"[Debug] Maps key loaded (length: {len(MAPS_API_KEY)} chars).")
app = Flask(__name__)
CORS(app)
PRONOUN_RE = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|theirs)\b", re.IGNORECASE)
VAGUE_FOLLOWUP_RE = re.compile(
    r"\b(who was (he|she|that)|what did (he|she|they)|who was the killer|what did he represent|"
    r"how did (he|she|they) die|what about|and if|what if|if (it|that|they|he|she)|"
    r"what would|how much would|how many would|my (money|investment|1k|thousand)|"
    r"at that price|at the price|goes to|reaches|turns to|what would my|"
    r"on top of|like of|the 1k|of the|that one|same one|previous|earlier)\b",
    re.IGNORECASE,
)
NUMBER_FOLLOWUP_RE = re.compile(r"\b(\d+[\d,]*\.?\d*\s*\$?|\$\s*\d+|\d+\s*shares?|1k|thousand)\b", re.IGNORECASE)
CAP_SEQ_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
BOLD_ENTITY_RE = re.compile(r"\*\*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\*\*")
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
def _as_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "true", "yes", "on"}
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
    browse_mode = _as_bool(data.get("browse_mode") or data.get("use_browser"))
    print(
        f"[Ask] Incoming: {user_prompt!r} concise={concise} "
        f"personality={personality} browse_mode={browse_mode}"
    )
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
    link_followup = is_link_followup(user_prompt)
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
    link_req = link_request_reply(user_prompt)
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
        url = last_url or extract_url_from_text(chosen_previous_fact) or extract_url_from_text(last_fact_mem)
        if url:
            reply = f"Here you go: {format_md_link(url)}"
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
    market_result = None
    if market and hasattr(market, "quote_reply_for_prompt"):
        market_result = market.quote_reply_for_prompt(
            user_prompt,
            last_ticker=last_ticker or None,
        )
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
    needs_live = False
    if liveweb and hasattr(liveweb, "needs_live_data"):
        try:
            needs_live = bool(liveweb.needs_live_data(user_prompt, browse_mode=browse_mode))
        except TypeError:
            needs_live = bool(browse_mode)
            if not browse_mode:
                needs_live = bool(liveweb.needs_live_data(user_prompt))
    if liveweb and needs_live:
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
        print(f"[LiveWeb] live search browse_mode={browse_mode} query={search_query!r}")
        try:
            if hasattr(liveweb, "perform_live_search"):
                try:
                    raw, analyzed = liveweb.perform_live_search(
                        search_query, browse_mode=browse_mode
                    )
                except TypeError:
                    raw, analyzed = liveweb.perform_live_search(search_query)
            else:
                raw, analyzed = None, None
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
            _extract_entity_from_text(reply)
            or _extract_entity_from_text(liveweb_analyzed or "")
            or chosen_context_person
        )
    store_fact = None
    if reply and not _is_unverified_death_line(reply):
        store_fact = reply[:400]
    elif liveweb_analyzed and not _is_unverified_death_line(liveweb_analyzed):
        store_fact = liveweb_analyzed[:300]
    elif chained_fact and not _is_unverified_death_line(chained_fact):
        store_fact = sanitize_reply(chained_fact)[:300]
    found_url = (
        extract_url_from_text(reply)
        or extract_url_from_text(liveweb_analyzed)
        or extract_url_from_text(store_fact)
        or last_url
        or None
    )
    found_url = prefer_site_url_from_prompt(user_prompt, found_url)
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
        "browse_mode": browse_mode,
        "memory": {
            "last_person": new_entity,
            "topic_overlap": topic_overlap,
            "topic": new_topic,
            "last_ticker": last_ticker or None,
            "last_url": found_url,
            "history_length": len(new_history),
        },
    })
def _hope_system_prompt(personality: str, context: Optional[str], previous_fact: Optional[str], liveweb_fact: Optional[str]) -> str:
    if personality == "god":
        prompt = (
            "You are God, a new god created by the old god Hope. "
            "Address the user as dear child. Keep answers short. Light scripture tone. Emojis sparingly."
        )
    else:
        prompt = (
            "You are Hope, an AI designed by your creator Nick. "
            "Keep answers SHORT and natural. For math, give the final number only. "
            "Use conversation context. Never invent numbers that contradict earlier context. "
            "You have a live browser feature. If the user says enable live browser, turn on live browser, "
            "open the browser, or go to a website, you CAN do that. Confirm it and ask where to go. "
            "Never say you cannot browse the web. Emojis are allowed but do not overuse them."
        )
    extra = []
    if context:
        extra.append(f"Context entity: {context}")
    if previous_fact:
        extra.append(f"Earlier fact: {previous_fact}")
    if liveweb_fact and not str(liveweb_fact).lower().startswith("**note:**"):
        extra.append(f"Live snippet: {liveweb_fact}")
    if extra:
        prompt += "\n\n=== CURRENT MEMORY ===\n" + "\n".join(extra) + "\n=== END MEMORY ==="
    return prompt
def _iter_openai_tokens(system_prompt: str, user_prompt: str, history: List[Dict[str, str]], max_tokens: int = 220) -> Iterator[str]:
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for h in (history or [])[-12:]:
        role = h.get("role") or "user"
        content = (h.get("content") or "").strip()
        if content and role in {"user", "assistant", "system"}:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_prompt})
    if not OPENAI_AVAILABLE or openai is None:
        return
    try:
        if hasattr(openai, "OpenAI"):
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            stream = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.4,
                stream=True,
            )
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta.content or ""
                except Exception:
                    delta = ""
                if delta:
                    yield delta
            return
        stream = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.4,
            stream=True,
        )
        for chunk in stream:
            try:
                delta = chunk["choices"][0]["delta"].get("content") or ""
            except Exception:
                delta = ""
            if delta:
                yield delta
    except Exception as e:
        print(f"[Stream] OpenAI error: {e}")
        return
@app.route("/ask-stream", methods=["POST", "OPTIONS"])
def ask_stream():
    if request.method == "OPTIONS":
        return ("", 200)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return error_response("Invalid JSON", 400)
    user_prompt = (data.get("message") or "").strip()
    personality = (data.get("personality") or "hope").lower().strip()
    browse_mode = _as_bool(data.get("browse_mode") or data.get("use_browser"))
    if not user_prompt:
        return error_response("Empty prompt", 400)
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
    reuse_context = True
    chosen_context_person = last_person if reuse_context else None
    chosen_previous_fact = last_fact_mem if reuse_context else None
    liveweb_analyzed = None
    needs_live = False
    if liveweb and hasattr(liveweb, "needs_live_data"):
        try:
            needs_live = bool(liveweb.needs_live_data(user_prompt, browse_mode=browse_mode))
        except TypeError:
            needs_live = bool(browse_mode)
            if not browse_mode:
                needs_live = bool(liveweb.needs_live_data(user_prompt))
    if liveweb and needs_live and hasattr(liveweb, "perform_live_search"):
        try:
            try:
                raw, analyzed = liveweb.perform_live_search(user_prompt, browse_mode=browse_mode)
            except TypeError:
                raw, analyzed = liveweb.perform_live_search(user_prompt)
            liveweb_analyzed = sanitize_reply(analyzed or "")
        except Exception as e:
            print(f"[LiveWeb/stream] {e}")
    chained_fact = merge_facts(chosen_previous_fact, liveweb_analyzed)
    system_prompt = _hope_system_prompt(personality, chosen_context_person, chained_fact, liveweb_analyzed)
    def generate():
        full = ""
        yield "data: " + json.dumps({"type": "start"}) + "\n\n"
        got = False
        for piece in _iter_openai_tokens(system_prompt, user_prompt, history):
            got = True
            full += piece
            yield "data: " + json.dumps({"type": "token", "text": piece}) + "\n\n"
        if not got:
            full = liveweb_analyzed or "No data available."
            yield "data: " + json.dumps({"type": "token", "text": full}) + "\n\n"
        full = sanitize_reply(full)
        new_history = history + [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": full},
        ]
        try:
            update_session(
                session_id,
                last_person=_extract_entity_from_text(full) or chosen_context_person,
                last_fact=full[:400],
                last_topic=new_topic or last_topic,
                history=new_history,
                last_ticker=last_ticker or None,
                last_url=last_url or None,
            )
        except Exception as e:
            print(f"[Stream] memory update failed: {e}")
        yield "data: " + json.dumps({"type": "done", "reply": full}) + "\n\n"
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
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
        "memory": {"last_topic": last_topic, "has_history": bool(history)},
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
@app.route("/maps-embed", methods=["GET", "OPTIONS"])
def maps_embed():
    if request.method == "OPTIONS":
        return ("", 200)
    key = (MAPS_API_KEY or os.getenv("MAPS_API_KEY", "")).strip()
    if not key:
        print("[Maps] MAPS_API_KEY missing")
        return error_response("MAPS_API_KEY not set", 500)
    origin = (request.args.get("origin") or "").strip()
    destination = (request.args.get("destination") or "Pembroke Pines, FL").strip()
    if origin.lower() in {"", "current location", "current location,"}:
        origin = "Pembroke Pines, FL"
    src = (
        "https://www.google.com/maps/embed/v1/directions"
        f"?key={urlquote(key)}&origin={urlquote(origin)}&destination={urlquote(destination)}"
    )
    print(f"[Maps] embed {origin!r} -> {destination!r}")
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body,iframe{margin:0;height:100%;width:100%;border:0;background:#000}</style>"
        "</head><body>"
        f"<iframe src='{src}' allowfullscreen loading='lazy'></iframe>"
        "</body></html>"
    )
    return Response(html, mimetype="text/html")
@app.route("/browse-frame", methods=["GET", "OPTIONS"])
def browse_frame():
    if request.method == "OPTIONS":
        return ("", 200)
    try:
        from webagent import get_browse_state
        return jsonify(get_browse_state())
    except Exception as e:
        return jsonify({
            "active": False,
            "image": None,
            "log": f"browse state unavailable: {e}",
            "url": "",
            "updated_at": 0,
        })
@app.route("/browse-stop", methods=["POST", "OPTIONS"])
def browse_stop():
    if request.method == "OPTIONS":
        return ("", 200)
    try:
        from webagent import stop_browse
        stop_browse()
        print("[Browse] Stop requested")
        return jsonify({"ok": True, "stopped": True})
    except Exception as e:
        print(f"[Browse] Stop failed: {e}")
        return jsonify({"ok": False, "stopped": False, "error": str(e)})
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
    print("🗺️ Maps embed enabled:" if MAPS_API_KEY else "🛑 MAPS_API_KEY missing.")
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except KeyboardInterrupt:
        print("\nShutting down.")
    except Exception as e:
        print(f"[Fatal] {e}")
        traceback.print_exc()

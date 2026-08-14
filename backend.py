"""
backend.py
Hope v2 API server
- Stronger session memory + follow-up detection
- ElevenLabs text-to-speech (/speak)
"""

from __future__ import annotations
import os
import re
import time
import threading
import traceback
import importlib.metadata
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import requests

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

# ---------- Safe dynamic imports ----------
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

print("📂 Working directory:", os.getcwd())
for fn in ["tone.py", "emailer.py", "image.py", "liveweb.py", "Liveweb.py"]:
    if os.path.exists(fn):
        print(f"✅ {fn} found")

# ---------- OpenAI Key ----------
# Uses environment variable first, falls back to the new key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")
print(f"[Debug] OpenAI key loaded (length: {len(OPENAI_API_KEY)} chars).")
OPENAI_AVAILABLE = bool(OPENAI_API_KEY and openai)

if not OPENAI_AVAILABLE:
    print("⚠️ OPENAI_API_KEY not set or openai lib missing. Tone generation disabled.")
else:
    openai.api_key = OPENAI_API_KEY
    print("🔐 OpenAI enabled.")

# ---------- ElevenLabs Config ----------
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "sk_35a6ce0cabc68945dc35de9f317580c2d72201481dee1916")
ELEVENLABS_VOICE_ID = "N4dLkbUobIjAlAsGddNU"

# ---------- Flask App ----------
app = Flask(__name__)
CORS(app)

# ---------- Session Memory ----------
SESSION_TTL_SECONDS = 1800  # 30 minutes
_session_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}

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

STOPWORDS = {
    "how", "did", "does", "do", "the", "a", "an", "of", "to", "for", "in", "on", "at", "with",
    "when", "what", "who", "why", "is", "are", "was", "were", "will", "and", "or", "out",
    "come", "release", "date", "latest", "news", "did", "die", "he", "she", "they", "note"
}

def _now() -> float:
    return time.time()

def _prune_sessions():
    now = _now()
    with _session_lock:
        stale = [k for k, v in _sessions.items() if now - v["ts"] > SESSION_TTL_SECONDS]
        for k in stale:
            _sessions.pop(k, None)

def _topic_of(text: str) -> str:
    tokens = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)]
    filtered = [t for t in tokens if t not in STOPWORDS]
    return " ".join(filtered[:5])

def _same_topic(old: str, new: str) -> bool:
    if not old or not new:
        return False
    a = set(old.split())
    b = set(new.split())
    return len(a & b) >= 1

def _get_session(sid: str) -> Optional[Dict[str, Any]]:
    _prune_sessions()
    with _session_lock:
        return _sessions.get(sid)

def _update_session(sid: str, *, last_person: Optional[str], last_fact: Optional[str], last_topic: str):
    with _session_lock:
        prev = _sessions.get(sid, {})
        _sessions[sid] = {
            "last_person": last_person or prev.get("last_person") or "",
            "last_fact": last_fact or prev.get("last_fact") or "",
            "last_topic": last_topic or prev.get("last_topic") or "",
            "ts": _now()
        }

def _extract_entity_from_text(text: str) -> Optional[str]:
    if not text:
        return None
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
    return "**Note:**" in text and ("unverified" in text.lower() or "no reliable" in text.lower() or "unconfirmed" in text.lower())

def error_response(msg: str, status=500):
    return jsonify({"error": msg}), status

def merge_facts(previous_fact: Optional[str], liveweb_fact: Optional[str]) -> Optional[str]:
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
    m = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}\b", text, re.IGNORECASE)
    if m:
        sentence_parts = re.split(r"(?<=[.!?])\s+", text)
        for s in sentence_parts:
            if m.group(0) in s:
                return s.strip()
        return m.group(0)
    first = re.split(r"(?<=[.!?])\s+", text)[0].strip()
    if len(first) < 12 and "." not in text:
        return text[:120]
    return first

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
    concise = bool(data.get("concise"))
    explicit_context = data.get("context") or None
    previous_fact_client = data.get("previous_fact") or None
    image_data = data.get("image") or None

    print(f"[Ask] Incoming: {user_prompt!r} concise={concise}")

    if not user_prompt and not image_data:
        return error_response("Empty prompt", 400)

    # Image processing
    vision_description = None
    if image_data and image_mod and hasattr(image_mod, "process_image_upload"):
        try:
            vision_description = image_mod.process_image_upload(image_data)
        except Exception as e:
            print(f"[Image] Error: {e}")

    # ----- Session memory -----
    session_id = request.remote_addr or "anon"
    session_data = _get_session(session_id)
    last_person = (session_data or {}).get("last_person") or ""
    last_fact_mem = (session_data or {}).get("last_fact") or ""
    last_topic = (session_data or {}).get("last_topic") or ""
    new_topic = _topic_of(user_prompt)
    topic_overlap = _same_topic(last_topic, new_topic)

    pronoun_detected = PRONOUN_RE.search(user_prompt)
    vague_followup_detected = VAGUE_FOLLOWUP_RE.search(user_prompt)
    number_followup = NUMBER_FOLLOWUP_RE.search(user_prompt)
    word_count = len(user_prompt.split())
    is_short_message = word_count <= 12

    reuse_context = False
    if (pronoun_detected or vague_followup_detected or number_followup
        or topic_overlap or is_short_message):
        reuse_context = True
    if explicit_context:
        reuse_context = True
    if last_fact_mem and is_short_message:
        reuse_context = True

    chosen_context_person = explicit_context if explicit_context else (last_person if reuse_context else None)
    chosen_previous_fact = previous_fact_client or (last_fact_mem if reuse_context else None)

    print(f"[Session] Reuse: {reuse_context} | Short: {is_short_message} | Words: {word_count} | Topic overlap: {topic_overlap}")

    # ----- Live Web Search -----
    liveweb_raw = None
    liveweb_analyzed = None
    if liveweb and hasattr(liveweb, "needs_live_data") and liveweb.needs_live_data(user_prompt):
        search_query = user_prompt
        if "die" in user_prompt.lower() or "death" in user_prompt.lower() or "killer" in user_prompt.lower():
            if chosen_context_person and (pronoun_detected or vague_followup_detected):
                search_query = search_query.replace("he", chosen_context_person).replace("she", chosen_context_person).replace("they", chosen_context_person)
            search_query += " death date"
        print(f"[LiveWeb] Performing live search for: {search_query}")
        try:
            raw, analyzed = liveweb.perform_live_search(search_query)
            liveweb_raw, liveweb_analyzed = raw, analyzed
            if analyzed:
                print(f"[LiveWeb] Analyzed (trunc): {analyzed[:180]}{'...' if len(analyzed) > 180 else ''}")
        except Exception as e:
            print(f"[LiveWeb] Error: {e}")

    chained_fact = merge_facts(chosen_previous_fact, liveweb_analyzed)

    effective_prompt = user_prompt
    if vision_description:
        effective_prompt += f"\n\nImage context: {vision_description}"

    # ----- Tone / Model Generation -----
    reply = None
    if tone and hasattr(tone, "generate_with_tone") and OPENAI_AVAILABLE:
        try:
            reply = tone.generate_with_tone(
                effective_prompt,
                context=chosen_context_person,
                previous_fact=chained_fact,
                liveweb_fact=liveweb_analyzed
            )
        except Exception as e:
            print(f"[Tone] Error: {e}")
            reply = None

    if not reply:
        if liveweb_analyzed:
            reply = liveweb_analyzed
        else:
            reply = "No data available."

    if concise:
        reply = _concise_trim(reply)

    # ----- Update memory -----
    new_entity = (
        last_person if _is_unverified_death_line(liveweb_analyzed or "") else
        _extract_entity_from_text(reply) or
        _extract_entity_from_text(liveweb_analyzed or "") or
        chosen_context_person
    )

    store_fact = None
    if reply and not _is_unverified_death_line(reply):
        store_fact = reply[:550]
    elif liveweb_analyzed and not _is_unverified_death_line(liveweb_analyzed):
        store_fact = liveweb_analyzed[:400]
    elif chained_fact and not _is_unverified_death_line(chained_fact):
        store_fact = chained_fact[:400]

    _update_session(
        session_id,
        last_person=new_entity,
        last_fact=store_fact,
        last_topic=new_topic
    )

    return jsonify({
        "reply": reply,
        "context_used": bool(chosen_context_person or chosen_previous_fact),
        "liveweb_raw": liveweb_raw,
        "liveweb_analyzed": liveweb_analyzed,
        "vision_note": vision_description if vision_description else None,
        "memory": {
            "last_person": new_entity,
            "topic_overlap": topic_overlap,
            "topic": new_topic
        }
    })

# ---------- ElevenLabs Speak Route ----------
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

    # Clean markdown for better speech
    clean_text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    clean_text = re.sub(r"`[^`]+`", "", clean_text)
    clean_text = clean_text.strip()

    print(f"[Speak] Generating voice for: {clean_text[:80]}...")

    try:
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": ELEVENLABS_API_KEY
            },
            json={
                "text": clean_text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {
                    "stability": 0.4,
                    "similarity_boost": 0.8
                }
            },
            timeout=30
        )

        if response.status_code != 200:
            print(f"[Speak] ElevenLabs error: {response.status_code} - {response.text}")
            return error_response(f"ElevenLabs error: {response.status_code}", 500)

        return Response(response.content, mimetype="audio/mpeg")

    except Exception as e:
        print(f"[Speak] Error: {e}")
        return error_response(f"TTS failed: {str(e)}", 500)

# ---------- Email Route ----------
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

# ---------- Health ----------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# ---------- Main Entrypoint ----------
if __name__ == "__main__":
    host = os.getenv("HOPE_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("HOPE_PORT", "5002")))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    print("🚀 Starting Hope v2 Backend...")
    print(f"📡 Listening: http://{host}:{port}")
    print("🔐 OpenAI enabled:" if OPENAI_AVAILABLE else "🛑 OpenAI disabled (no key).")
    print("🎤 ElevenLabs voice enabled.")
    try:
        app.run(host=host, port=port, debug=debug)
    except KeyboardInterrupt:
        print("\nShutting down.")
    except Exception as e:
        print(f"[Fatal] {e}")
        traceback.print_exc()

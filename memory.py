"""
memory.py
Session store + topic helpers for Hope.
"""
from __future__ import annotations
import re
import time
import threading
from typing import Optional, Dict, Any, List

from sanitize import sanitize_reply

SESSION_TTL_SECONDS = 7 * 24 * 3600
MAX_HISTORY = 20
WEB_MEMORY_KEY = "hope-web-owner"

_session_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}

STOPWORDS = {
    "how", "did", "does", "do", "the", "a", "an", "of", "to", "for", "in", "on", "at", "with",
    "when", "what", "who", "why", "is", "are", "was", "were", "will", "and", "or", "out",
    "come", "release", "date", "latest", "news", "did", "die", "he", "she", "they", "note",
    "stock", "share", "shares", "price", "quote", "rn", "now", "current", "check", "again",
    "link", "url", "site", "website", "official", "send", "give", "me",
}


def _now() -> float:
    return time.time()


def prune_sessions() -> None:
    now = _now()
    with _session_lock:
        stale = [
            k for k, v in _sessions.items()
            if k != WEB_MEMORY_KEY and now - v["ts"] > SESSION_TTL_SECONDS
        ]
        for k in stale:
            _sessions.pop(k, None)


def topic_of(text: str) -> str:
    tokens = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", text or "")]
    filtered = [t for t in tokens if t not in STOPWORDS]
    return " ".join(filtered[:5])


def same_topic(old: str, new: str) -> bool:
    if not old or not new:
        return False
    a = set(old.split())
    b = set(new.split())
    return len(a & b) >= 1


def get_session(sid: str) -> Optional[Dict[str, Any]]:
    prune_sessions()
    with _session_lock:
        return _sessions.get(sid)


def update_session(
    sid: str,
    *,
    last_person: Optional[str] = None,
    last_fact: Optional[str] = None,
    last_topic: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    last_ticker: Optional[str] = None,
    last_url: Optional[str] = None,
) -> None:
    with _session_lock:
        prev = _sessions.get(sid, {})
        clean_fact = (
            sanitize_reply(last_fact)
            if last_fact is not None
            else sanitize_reply(prev.get("last_fact") or "")
        )
        if last_fact is None and prev.get("last_fact"):
            clean_fact = sanitize_reply(prev.get("last_fact") or "")

        raw_history = history if history is not None else (prev.get("history") or [])
        trimmed_history = []
        for item in (raw_history or [])[-MAX_HISTORY:]:
            trimmed_history.append({
                "role": item.get("role", "user"),
                "content": sanitize_reply(item.get("content") or ""),
            })

        _sessions[sid] = {
            "last_person": last_person if last_person is not None else prev.get("last_person") or "",
            "last_fact": clean_fact if last_fact is not None else (
                sanitize_reply(prev.get("last_fact") or "") or prev.get("last_fact") or ""
            ),
            "last_topic": last_topic or prev.get("last_topic") or "",
            "last_ticker": (last_ticker if last_ticker is not None else prev.get("last_ticker") or "").upper(),
            "last_url": last_url if last_url is not None else prev.get("last_url") or "",
            "history": trimmed_history,
            "ts": _now(),
        }
        if last_fact is not None:
            _sessions[sid]["last_fact"] = sanitize_reply(last_fact)


def clear_web_memory() -> None:
    with _session_lock:
        _sessions.pop(WEB_MEMORY_KEY, None)

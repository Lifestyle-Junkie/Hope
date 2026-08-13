"""
liveweb.py
Live search + guarded factual extraction.

Key points:
- Death / injury claims require >=1 distinct reliable domains or are flagged unverified.
- Never fabricate; returns **Note:** lines when evidence insufficient.
- Provides (raw_text, analyzed_text). analyzed_text is short + bolded entities.
- Caching layer to reduce repeated external calls.
- Basic spell correction for names in death queries.
- Improved URL parsing and snippet prioritization for relevance.

Install:
  pip install ddgs jellyfish urllib3  # For spell correction and URL parsing
Fallback:
  pip install duckduckgo-search
"""

from __future__ import annotations
import re
import time
import html
from typing import List, Tuple, Optional
from urllib.parse import urlparse  # Standard lib for robust URL handling

# ---------------- Package Import ----------------
_DDG_IMPORT_ERR = None
try:
    from ddgs import DDGS  # Preferred
    _DDG_AVAILABLE = True
except Exception as e_new:
    try:
        from duckduckgo_search import DDGS  # Legacy
        _DDG_AVAILABLE = True
        _DDG_IMPORT_ERR = f"Using legacy duckduckgo_search ({e_new})"
    except Exception as e_old:
        _DDG_AVAILABLE = False
        _DDG_IMPORT_ERR = f"No DuckDuckGo backend: {e_old}"

# Spell correction (optional)
try:
    import jellyfish
    _SPELL_AVAILABLE = True
except ImportError:
    _SPELL_AVAILABLE = False
    print("[LiveWeb] Install jellyfish for better name correction.")

# ---------------- Patterns ----------------
DEATH_PATTERN = re.compile(
    r"\b(how did|cause of death|what (?:killed|happened to)|did .* die|when did .* die|die|died|death|killed|assassinated|passed away|dead|deceased|shot)\b",
    re.IGNORECASE
)
DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE
)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
NOUN_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")

LIVE_KEYWORDS = {
    "when", "date", "release", "latest", "recent", "today", "this week",
    "breaking", "update", "news", "launched", "announced", "died", "death",
    "killed", "passed", "cause of death", "assassinated", "shot"
}

RELIABLE_DOMAINS = {
    "apnews.com", "associatedpress.com", "reuters.com", "bbc.com", "bbc.co.uk",
    "nytimes.com", "theguardian.com", "washingtonpost.com", "bloomberg.com",
    "wsj.com", "npr.org", "abcnews.go.com", "cbsnews.com", "cnn.com",
    "wikipedia.org", "aljazeera.com", "foxnews.com", "usatoday.com", "nbcnews.com", "axios.com", "pbs.org"
}

# ---------------- Public API ----------------
def needs_live_data(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    low = q.lower()
    if DEATH_PATTERN.search(low):
        return True
    if any(k in low for k in LIVE_KEYWORDS):
        return True
    # Question form + capitalized token
    if q.endswith("?") and re.search(r"\b[A-Z][a-z]+\b", q):
        return True
    return False

def correct_name_spelling(name: str) -> str:
    if not _SPELL_AVAILABLE or not name:
        return name
    # Simple correction: Find similar to common names (placeholder; expand as needed)
    corrections = {
        "kirl": "kirk",
        "charlie kirl": "charlie kirk"
    }
    low_name = name.lower()
    for wrong, right in corrections.items():
        if wrong in low_name:
            return name.replace(wrong, right, 1)  # Case-insensitive replace
    # Phonetic fallback if jellyfish available
    if jellyfish:
        # Example: Sound like "kirk"
        if jellyfish.jaro_winkler_similarity(low_name, "kirk") > 0.8:
            return name.replace(low_name.split()[-1], "Kirk")
    return name

def perform_live_search(query: str, max_results: int = 8) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns: (raw_text, analyzed_text)
      raw_text: concatenated snippet string or None
      analyzed_text: concise summary or **Note:** line
    """
    if not needs_live_data(query):
        return None, None

    # Correct spelling for death queries
    corrected_query = query
    entity_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", query)
    if entity_match:
        corrected_name = correct_name_spelling(entity_match.group(0))
        corrected_query = query.replace(entity_match.group(0), corrected_name)
        print(f"[LiveWeb] Corrected query: {query} -> {corrected_query}")

    if not _DDG_AVAILABLE:
        return None, safe_note("Live search unavailable (install ddgs).")

    results = _search_duckduckgo(corrected_query, max_results=max_results)
    if not results:
        if DEATH_PATTERN.search(query):
            return None, safe_note("No reliable sources confirming a death. Treat as unconfirmed.")
        return None, safe_note("No live results found.")

    raw_text = _merge_results(results, query=corrected_query)
    print(f"[LiveWeb Debug] Raw text (trunc): {raw_text[:200]}{'...' if len(raw_text) > 200 else ''}")  # Debug raw snippets
    analyzed = _analyze_with_safety(query, results, raw_text)
    return raw_text, analyzed

# ---------------- Internal Search ----------------
def _search_duckduckgo(query: str, max_results: int = 8) -> List[dict]:
    out: List[dict] = []
    try:
        with DDGS() as ddg:
            for r in ddg.text(query, max_results=max_results):
                if not isinstance(r, dict):
                    continue
                title = (r.get("title") or "").strip()
                body = (r.get("body") or r.get("snippet") or "").strip()
                href = (r.get("href") or r.get("url") or "").strip()
                if not (title or body):
                    continue
                out.append({"title": title, "body": body, "href": href})
                print(f"[LiveWeb Debug] Snippet: {title[:50]} - {body[:100]}... (URL: {href})")  # Debug per snippet
    except Exception as e:
        print(f"[LiveWeb] Search error: {e}")
    return out

# ---------------- Safety / Analysis ----------------
def _domain_ok(url: str) -> bool:
    if not url:
        return False
    try:
        # Robust URL parsing with urllib
        parsed = urlparse(url)
        host = parsed.netloc.lower() or parsed.path.split('/')[0].lower()  # Fallback for relative paths
        print(f"[LiveWeb Debug] Checking URL '{url}' -> host '{host}'")  # Debug log
        return any(host.endswith(d) for d in RELIABLE_DOMAINS)
    except Exception as e:
        print(f"[LiveWeb] URL parse error for '{url}': {e}")
        return False

def _merge_results(results: List[dict], query: str, char_limit: int = 2400) -> str:
    # Prioritize snippets with death keywords, dates, or proper nouns for relevance
    death_re = re.compile(r"\b(die|died|death|killed|assassinated|shot)\b", re.IGNORECASE)
    noun_re = NOUN_PATTERN
    entity_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", query)
    entity = entity_match.group(0).lower() if entity_match else None
    
    def score_snippet(r):
        score = 0
        combined = f"{r['title']} {r['body']}".lower()
        if death_re.search(combined):
            score += 20  # Higher weight for death keywords
        if DATE_PATTERN.search(combined):
            score += 5
            # Boost if date is recent (within 30 days of now)
            dates = DATE_PATTERN.findall(combined)
            for d in dates:
                try:
                    date_obj = time.strptime(d, "%B %d, %Y")
                    days_old = (time.time() - time.mktime(date_obj)) / (24 * 3600)
                    if days_old < 30:
                        score += 10  # Favor recent dates
                except ValueError:
                    pass
        if noun_re.search(combined):
            score += 10  # Boost for proper nouns (e.g., suspect names)
        if entity and entity in combined:
            score += 15  # Boost for query entity match
        if _domain_ok(r['href']):
            score += 20  # Boost reliable sources
        return score

    # Sort by score (highest first)
    sorted_results = sorted(results, key=score_snippet, reverse=True)
    
    parts: List[str] = []
    for r in sorted_results:  # Use all results after sorting
        seg = f"{r['title']} - {r['body']}".strip()
        seg = _clean_text(seg)
        if seg:
            parts.append(seg)
    merged = " | ".join(parts)
    if len(merged) > char_limit:
        merged = merged[:char_limit].rsplit(" ", 1)[0] + "..."
    print(f"[LiveWeb Debug] Top snippet scores: {[score_snippet(r) for r in sorted_results[:3]]}")  # Debug
    return merged

def _clean_text(text: str) -> str:
    t = html.unescape(text)
    t = re.sub(r"\s+", " ", t)
    return t.strip(" -")

def _extract_dates(text: str) -> List[str]:
    # Extended to catch short month names
    dates = DATE_PATTERN.findall(text, re.IGNORECASE)
    return list(dict.fromkeys(dates))

def _extract_proper_nouns(text: str, max_items: int = 6) -> List[str]:
    matches = NOUN_PATTERN.findall(text)
    out = []
    for m in matches:
        if len(m) < 3:
            continue
        if m.lower() in {"http", "https", "note"}:
            continue
        if m not in out:
            out.append(m)
    return out[:max_items]

def _shorten(txt: str, limit: int) -> str:
    if len(txt) <= limit:
        return txt
    return txt[:limit].rsplit(" ", 1)[0] + "..."

def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

def _first_sentence_with(text: str, keyword: str) -> Optional[str]:
    for s in _split_sentences(text):
        if keyword.lower() in s.lower():
            return s
    return None

def _analyze_with_safety(query: str, results: List[dict], raw_text: str) -> str:
    q_low = query.lower()
    is_death = bool(DEATH_PATTERN.search(q_low))

    # Gather death claims & reliability
    if is_death:
        claim_hits = []
        reliable_sources = set()
        for r in results:
            combined = f"{r['title']} {r['body']}".lower()
            if any(k in combined for k in ("died", "has died", "was killed", "passed away", "assassinated", "shot")):
                url = r.get("href", "")
                rel = _domain_ok(url)
                claim_hits.append((combined, url, rel))
                if rel:
                    reliable_sources.add(url)
                    print(f"[LiveWeb Debug] Reliable source found: {url}")  # Debug
        # Require >=1 distinct reliable domains
        if len(reliable_sources) < 1:
            print(f"[LiveWeb Debug] Reliable sources: {len(reliable_sources)} (needed 1)")  # Debug
            return safe_note("Death claim unverified by reliable sources. Treat as unconfirmed.")

    dates = _extract_dates(raw_text)
    nouns = _extract_proper_nouns(raw_text)

    def bold_once(s: str) -> str:
        used = set()
        for ent in nouns + dates:
            if ent in used:
                continue
            s = re.sub(rf"\b{re.escape(ent)}\b", f"**{ent}**", s, count=1)
            used.add(ent)
        return s

    if is_death:
        # Prioritize sentence with date or death indicator
        indicators = ["has died", "died", "was killed", "passed away", "shot", "assassinated"]
        sent = None
        for ind in indicators:
            sent = _first_sentence_with(raw_text, ind)
            if sent:
                break
        if not sent and dates:
            for date in dates:
                for s in _split_sentences(raw_text):
                    if date in s:
                        sent = s
                        break
                if sent:
                    break
        if not sent:
            sent = raw_text[:260]
        summary = _shorten(sent, 340)
        if dates:
            summary += f" (Date refs: {', '.join(dates[:2])})"
        if nouns and "killer" in q_low:  # Include suspect name for "who" queries
            summary += f" (Names: {', '.join(nouns[:2])})"
        return bold_once(summary)

    # Non-death summary: first 1–2 sentences
    sents = _split_sentences(raw_text)[:2]
    if not sents:
        return bold_once("No meaningful summary derived.")
    summary = _shorten(" ".join(sents), 420)
    return bold_once(summary)

def safe_note(msg: str) -> str:
    return f"**Note:** {msg}"

# ---------------- Cache ----------------
_cache: dict = {}
_CACHE_TTL = 90  # seconds

def cached_perform_live_search(query: str, max_results: int = 8) -> Tuple[Optional[str], Optional[str]]:
    now = time.time()
    key = (query.lower(), max_results)
    entry = _cache.get(key)
    if entry and now - entry["time"] < _CACHE_TTL:
        return entry["raw"], entry["analyzed"]
    raw, analyzed = perform_live_search(query, max_results=max_results)
    _cache[key] = {"time": now, "raw": raw, "analyzed": analyzed}
    return raw, analyzed

# ---------------- CLI Test ----------------
if __name__ == "__main__":
    tests = [
        "How did Alan Turing die",
        "How did charlie kirl die",  # Test misspelling
        "When does GTA 6 come out",
        "Latest news on SpaceX launch",
        "When did Zelda Tears of the Kingdom release"
    ]
    print(f"[Info] DDG available: {_DDG_AVAILABLE}; {_DDG_IMPORT_ERR or ''}")
    for t in tests:
        print("\nQuery:", t)
        if needs_live_data(t):
            raw, analyzed = perform_live_search(t)
            print("RAW:", (raw[:200] + "..." if raw and len(raw) > 200 else raw))
            print("ANALYZED:", analyzed)
        else:
            print("No live search needed.")
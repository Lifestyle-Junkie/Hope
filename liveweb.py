"""
liveweb.py
Live search + guarded factual extraction + optional real browser surfing.
Two separate tools:
- Text search (DuckDuckGo) → normal chat. Does NOT need the globe.
- Computer Use browse     → ONLY when browse_mode=True (globe icon on).
No hardcoded years or canned answers. Rank snippets against the user's question.
When snippets contain a date or place, put those facts first in the summary.
Ignore wiki "last edited on" stamps — those are not event dates.
Prefer event years that match "next" / future wording in the query.
"""
from __future__ import annotations
import re
import time
import html
from typing import List, Tuple, Optional
from urllib.parse import urlparse

_DDG_IMPORT_ERR = None
try:
    from ddgs import DDGS
    _DDG_AVAILABLE = True
except Exception as e_new:
    try:
        from duckduckgo_search import DDGS
        _DDG_AVAILABLE = True
        _DDG_IMPORT_ERR = f"Using legacy duckduckgo_search ({e_new})"
    except Exception as e_old:
        _DDG_AVAILABLE = False
        _DDG_IMPORT_ERR = f"No DuckDuckGo backend: {e_old}"

try:
    import jellyfish
    _SPELL_AVAILABLE = True
except ImportError:
    _SPELL_AVAILABLE = False
    print("[LiveWeb] Install jellyfish for better name correction.")

DEATH_PATTERN = re.compile(
    r"\b(how did|cause of death|what (?:killed|happened to)|did .* die|when did .* die|"
    r"die|died|death|killed|assassinated|passed away|dead|deceased|shot)\b",
    re.IGNORECASE
)
SITE_PATTERN = re.compile(
    r"\b(what(?:'s| is)? the (official\s+)?(site|website|url|link) for)\b|"
    r"\b(official\s+(site|website|page|homepage))\b|"
    r"\b((site|website|url|homepage) for [a-z0-9][\w-]*)\b|"
    r"\b(where (?:can|do) i (find|go to|visit) .{2,40})\b",
    re.IGNORECASE
)
LINK_FOLLOWUP_ONLY_RE = re.compile(
    r"^\s*((please|pls|can you|could you)\s+)?"
    r"(send|give|drop|share|post)?\s*"
    r"(me\s+)?(the\s+)?(link|url|website|site)\s*\??\s*$",
    re.IGNORECASE
)
CODE_INTENT_RE = re.compile(
    r"\b("
    r"write|code|html|css|javascript|js|python|script|function|class|"
    r"dropship|product page|source code|full page|markup|"
    r"write me|write a|write the|write one"
    r")\b",
    re.IGNORECASE
)
BROWSE_RE = re.compile(
    r"\b("
    r"go to|visit|navigate|browse|surf|"
    r"open (?!source\b)|"
    r"look (this|that|it) up on the (site|page|website)|"
    r"on (the )?(site|page|website)|"
    r"click|fill (out|in)|scroll (down|up|to)|"
    r"read (the|this|that) (page|site|article)|"
    r"check (the|this|that) (page|site|website)"
    r")\b",
    re.IGNORECASE,
)
IDENTITY_RE = re.compile(
    r"\b(who (made|created|designed|built) you|who are you|what are you|"
    r"your (name|creator|maker)|what'?s your name|training (data|cutoff)|"
    r"knowledge cutoff|cut[- ]?off)\b",
    re.IGNORECASE,
)
GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|sup|hiya|howdy|good\s*(morning|afternoon|evening)|"
    r"what'?s\s*up|how\s*are\s*you|how'?s\s*it\s*going)[\s!?.]*$",
    re.IGNORECASE,
)
FACT_QUESTION_RE = re.compile(
    r"^\s*(who|what|when|where|which|whom|whose|how (many|much|long|far|old)|"
    r"did|does|is|are|was|were|has|have|will|can)\b",
    re.IGNORECASE,
)
HISTORY_PAGE_RE = re.compile(
    r"\b(papal bull|inter gravissimas|gregory xiii|julian calendar|"
    r"calendar era|modification of the julian)\b",
    re.IGNORECASE,
)
PAST_GAMES_NOISE_RE = re.compile(
    r"\b(paris 2024|tokyo 2020|rio 2016|london 2012|beijing 2008|"
    r"2024 summer olympics medal|medal table 2024)\b",
    re.IGNORECASE,
)
VAGUE_SEASON_RE = re.compile(
    r"\b(this (fall|spring|summer|winter)|coming soon|later this year)\b",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE
)
MONTH_YEAR_RE = re.compile(
    r"\b("
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    r")\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s*)?((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
PLACE_RE = re.compile(
    r"\b(?:in|at|held in|hosted (?:in|by)|takes place in|coming to|opens? in|"
    r"will be held in|host city)\s+"
    r"([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})"
)
EVENT_YEAR_RE = re.compile(
    r"\b((?:19|20)\d{2})\s+(Summer |Winter )?Olympics\b|"
    r"\bOlympics\s+(?:in|of)\s+((?:19|20)\d{2})\b|"
    r"\b((?:19|20)\d{2})\s+Olympic Games\b",
    re.IGNORECASE,
)
EDIT_STAMP_RE = re.compile(
    r"(last edited|posted on|updated on|published on|page last changed|"
    r"this page was last edited)\b",
    re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
NOUN_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")

STOP = {
    "the", "a", "an", "of", "to", "for", "in", "on", "at", "with", "and", "or",
    "is", "are", "was", "were", "be", "been", "what", "when", "where", "who",
    "which", "how", "why", "do", "does", "did", "can", "could", "would",
    "i", "me", "my", "you", "your", "it", "its", "this", "that", "please",
}
PLACE_STOP = {
    "the", "a", "an", "this", "that", "these", "those", "disney", "theaters",
    "theatres", "theater", "theatre", "october", "november", "december",
    "january", "february", "march", "april", "june", "july", "august", "september",
    "wikipedia", "wikimedia",
}
LIVE_KEYWORDS = {
    "when", "date", "release", "released", "latest", "recent", "today", "tonight",
    "this week", "this year", "this month", "right now", "currently", "current",
    "breaking", "update", "updated", "news", "headline", "launched", "announced",
    "announcement", "came out", "coming out", "out now", "dropped",
    "died", "death", "killed", "passed", "cause of death", "assassinated", "shot",
    "who won", "winner", "score", "final score", "standings", "schedule",
    "price", "stock", "worth", "net worth", "box office",
    "weather", "forecast", "temperature",
    "president", "election", "elected",
    "album", "movie", "game", "trailer", "season",
    "olympics", "olympic", "world cup", "next",
}
RELIABLE_DOMAINS = {
    "apnews.com", "associatedpress.com", "reuters.com", "bbc.com", "bbc.co.uk",
    "nytimes.com", "theguardian.com", "washingtonpost.com", "bloomberg.com",
    "wsj.com", "npr.org", "abcnews.go.com", "cbsnews.com", "cnn.com",
    "wikipedia.org", "aljazeera.com", "foxnews.com", "usatoday.com",
    "nbcnews.com", "axios.com", "pbs.org", "olympics.com", "ioc.ch",
}
SKIP_HOST_PARTS = {
    "facebook.", "twitter.", "x.com", "instagram.", "youtube.", "reddit.",
    "substack.com", "medium.com", "tiktok.", "linkedin.", "pinterest."
}

def _now_year() -> int:
    return int(time.strftime("%Y"))


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w for w in words if w not in STOP and len(w) > 1]


def _overlap(query: str, text: str) -> int:
    q = set(_tokens(query))
    t = set(_tokens(text))
    if not q:
        return 0
    return len(q & t)


def _wants_next(query: str) -> bool:
    return bool(re.search(r"\b(next|upcoming|coming|future)\b", query or "", re.I))


def _rewrite_query(query: str) -> str:
    q = (query or "").strip()
    low = q.lower()
    if re.search(r"\b(next|upcoming).{0,20}olympics?\b", low) or re.search(
        r"\bolympics?.{0,20}(next|where|when)\b", low
    ):
        if "winter" in low:
            return "next Winter Olympics host city year"
        return "next Summer Olympics host city year"
    if re.search(r"\bwhen does\b.+\b(come|come out|release|drop)\b", low):
        return re.sub(r"[?!.]", "", q) + " release date"
    if re.search(r"\bwhat year is it\b", low):
        return "current year today's date"
    return q


def should_browse(query: str, browse_mode: bool = False) -> bool:
    if not browse_mode:
        return False
    q = (query or "").strip()
    if not q:
        return False
    if CODE_INTENT_RE.search(q) and not BROWSE_RE.search(q):
        return False
    if LINK_FOLLOWUP_ONLY_RE.match(q):
        return False
    if BROWSE_RE.search(q):
        return True
    if re.search(r"https?://", q) and re.search(
        r"\b(what|find|get|read|tell|summarize|check|open|go)\b", q, re.I
    ):
        return True
    return True


def browse_and_summarize(query: str) -> str:
    try:
        from webagent import browse_sync
    except Exception as e:
        print(f"[LiveWeb] webagent import failed: {e}")
        return ""
    try:
        print(f"[LiveWeb] Using Computer Use browser for: {query}")
        result = browse_sync(query)
        return (result or "").strip()
    except Exception as e:
        print(f"[LiveWeb] browse_and_summarize error: {e}")
        return ""


def needs_live_data(query: str, browse_mode: bool = False) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if GREETING_RE.search(q) or IDENTITY_RE.search(q):
        return False
    if CODE_INTENT_RE.search(q) and not BROWSE_RE.search(q):
        return False
    if LINK_FOLLOWUP_ONLY_RE.match(q):
        return False
    if should_browse(q, browse_mode):
        return True
    low = q.lower()
    if DEATH_PATTERN.search(low):
        return True
    if SITE_PATTERN.search(q):
        return True
    if YEAR_PATTERN.search(q):
        return True
    if any(k in low for k in LIVE_KEYWORDS):
        return True
    if FACT_QUESTION_RE.search(q) and len(q.split()) >= 3:
        return True
    return False


def correct_name_spelling(name: str) -> str:
    if not _SPELL_AVAILABLE or not name:
        return name
    corrections = {
        "kirl": "kirk",
        "charlie kirl": "charlie kirk"
    }
    low_name = name.lower()
    for wrong, right in corrections.items():
        if wrong in low_name:
            return re.sub(re.escape(wrong), right, name, count=1, flags=re.IGNORECASE)
    if jellyfish:
        if jellyfish.jaro_winkler_similarity(low_name, "kirk") > 0.8:
            parts = name.split()
            if parts:
                parts[-1] = "Kirk"
                return " ".join(parts)
    return name


def perform_live_search(
    query: str,
    max_results: int = 8,
    browse_mode: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    if not needs_live_data(query, browse_mode=browse_mode):
        return None, None

    if should_browse(query, browse_mode=browse_mode):
        browsed = browse_and_summarize(query)
        if browsed:
            return browsed, browsed
        print("[LiveWeb] Browser agent unavailable — falling back to snippet search.")

    corrected_query = _rewrite_query(query)
    entity_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", corrected_query or "")
    if entity_match:
        corrected_name = correct_name_spelling(entity_match.group(0))
        corrected_query = corrected_query.replace(entity_match.group(0), corrected_name)
    if corrected_query != query:
        print(f"[LiveWeb] Corrected query: {query} -> {corrected_query}")

    if SITE_PATTERN.search(query or ""):
        if "official" not in corrected_query.lower():
            corrected_query = f"{corrected_query} official website"

    if not _DDG_AVAILABLE:
        return None, safe_note("Live search unavailable (install ddgs).")

    results = _search_duckduckgo(corrected_query, max_results=max_results)
    results = _filter_offtopic(query, results)
    if not results:
        if DEATH_PATTERN.search(query or ""):
            return None, safe_note("No reliable sources confirming a death. Treat as unconfirmed.")
        return None, safe_note("No live results found.")

    raw_text = _merge_results(results, query=query)
    print(f"[LiveWeb Debug] Raw text (trunc): {raw_text[:200]}{'...' if len(raw_text) > 200 else ''}")
    analyzed = _analyze_with_safety(query, results, raw_text)
    print(f"[LiveWeb Debug] Analyzed: {analyzed[:180]}")
    return raw_text, analyzed


def _filter_offtopic(query: str, results: List[dict]) -> List[dict]:
    q_tokens = set(_tokens(query))
    wants_next = _wants_next(query)
    kept = []
    for r in results:
        href = (r.get("href") or "").lower()
        blob = f"{r.get('title', '')} {r.get('body', '')}"
        if any(x in href for x in SKIP_HOST_PARTS):
            continue
        if HISTORY_PAGE_RE.search(blob) and _overlap(query, blob) < 2:
            print(f"[LiveWeb] Dropped off-topic: {(r.get('title') or '')[:70]}")
            continue
        if wants_next and PAST_GAMES_NOISE_RE.search(blob) and not re.search(r"\b2028\b|\b2032\b|\b2034\b", blob):
            print(f"[LiveWeb] Dropped past-games noise: {(r.get('title') or '')[:70]}")
            continue
        if q_tokens and _overlap(query, blob) == 0 and "wiki" in href:
            continue
        kept.append(r)
    return kept or results


def _search_duckduckgo(query: str, max_results: int = 8) -> List[dict]:
    out: List[dict] = []
    try:
        ddg = DDGS()
        rows = ddg.text(query, max_results=max_results)
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            title = (r.get("title") or "").strip()
            body = (r.get("body") or r.get("snippet") or r.get("description") or "").strip()
            href = (r.get("href") or r.get("url") or r.get("link") or "").strip()
            if not (title or body or href):
                continue
            out.append({"title": title, "body": body, "href": href})
            print(f"[LiveWeb Debug] Snippet: {title[:50]} - {body[:80]}... (URL: {href})")
    except TypeError:
        try:
            with DDGS() as ddg:
                for r in ddg.text(query, max_results=max_results):
                    if not isinstance(r, dict):
                        continue
                    title = (r.get("title") or "").strip()
                    body = (r.get("body") or r.get("snippet") or "").strip()
                    href = (r.get("href") or r.get("url") or "").strip()
                    if not (title or body or href):
                        continue
                    out.append({"title": title, "body": body, "href": href})
        except Exception as e:
            print(f"[LiveWeb] Search error (legacy path): {e}")
    except Exception as e:
        print(f"[LiveWeb] Search error: {e}")
    return out


def _domain_ok(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return any(host == d or host.endswith("." + d) for d in RELIABLE_DOMAINS)
    except Exception as e:
        print(f"[LiveWeb] URL parse error for '{url}': {e}")
        return False


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    return url


def _pretty_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host or url
    except Exception:
        return url


def _best_site_result(query: str, results: List[dict]) -> Optional[dict]:
    if not results:
        return None
    q = re.sub(r"[^a-z0-9\s]", " ", (query or "").lower())
    stop = STOP | {"site", "website", "url", "link", "official", "page", "homepage",
                   "send", "give", "drop", "share", "find", "go"}
    tokens = [t for t in q.split() if t and t not in stop]
    brand = tokens[0] if tokens else ""
    scored = []
    for r in results:
        href = _normalize_url(r.get("href") or "")
        if not href:
            continue
        host = _pretty_domain(href)
        score = _overlap(query, f"{r.get('title', '')} {r.get('body', '')} {host}")
        title = (r.get("title") or "").lower()
        body = (r.get("body") or "").lower()
        if any(x in host for x in SKIP_HOST_PARTS):
            score -= 40
        if brand and brand in host:
            score += 50
        if brand and brand in title:
            score += 20
        if "official" in title or "official" in body:
            score += 10
        if host.count(".") <= 2:
            score += 15
        path = urlparse(href).path or ""
        if path in ("", "/"):
            score += 8
        scored.append((score, {**r, "href": href}))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 2:
        return None
    return best


def _year_from_chunk(chunk: str) -> Optional[int]:
    m = YEAR_PATTERN.search(chunk or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _merge_results(results: List[dict], query: str, char_limit: int = 2400) -> str:
    death_re = re.compile(r"\b(die|died|death|killed|assassinated|shot)\b", re.IGNORECASE)
    wants_next = _wants_next(query)
    now_y = _now_year()

    def score_snippet(r):
        blob = f"{r.get('title', '')} {r.get('body', '')}"
        score = _overlap(query, blob) * 10
        if death_re.search(blob):
            score += 20
        if DATE_PATTERN.search(blob) or MONTH_YEAR_RE.search(blob) or EVENT_YEAR_RE.search(blob):
            score += 18
        if _domain_ok(r.get("href", "")):
            score += 12
        if "olympics.com" in (r.get("href") or "").lower():
            score += 20
        if HISTORY_PAGE_RE.search(blob) and _overlap(query, blob) < 3:
            score -= 40
        if EDIT_STAMP_RE.search(blob):
            score -= 25
        if wants_next and PAST_GAMES_NOISE_RE.search(blob):
            score -= 30
        years = [int(m.group(1)) for m in re.finditer(r"\b((?:19|20)\d{2})\b", blob)]
        if wants_next and years:
            future = [y for y in years if y >= now_y]
            past = [y for y in years if y < now_y]
            if future:
                score += 28
            if past and not future:
                score -= 18
        return score

    sorted_results = sorted(results, key=score_snippet, reverse=True)
    parts: List[str] = []
    for r in sorted_results:
        href = (r.get("href") or "").strip()
        seg = f"{r.get('title', '')} - {r.get('body', '')}".strip()
        if href:
            seg = f"{seg} ({href})"
        seg = _clean_text(seg)
        if seg:
            parts.append(seg)
    merged = " | ".join(parts)
    if len(merged) > char_limit:
        merged = merged[:char_limit].rsplit(" ", 1)[0] + "..."
    return merged


def _clean_text(text: str) -> str:
    t = html.unescape(text or "")
    t = re.sub(r"\s+", " ", t)
    return t.strip(" -")


def _sentence_window(text: str, start: int, end: int, pad: int = 90) -> str:
    a = max(0, start - pad)
    b = min(len(text or ""), end + pad)
    return text[a:b]


def _extract_dates(text: str, query: str = "") -> List[str]:
    text = text or ""
    wants_next = _wants_next(query)
    now_y = _now_year()
    scored: List[Tuple[int, str]] = []

    for m in MONTH_YEAR_RE.finditer(text):
        window = _sentence_window(text, m.start(), m.end())
        if EDIT_STAMP_RE.search(window):
            continue
        month, day, year = m.group(1), m.group(2), m.group(3)
        chunk = f"{month} {day}, {year}" if day else f"{month} {year}"
        chunk = re.sub(r"\s+", " ", chunk).strip()
        score = _overlap(query, window) * 8
        if re.search(r"\b(held|host|opens?|begins?|games|olympics?|release|debut|premiere)\b", window, re.I):
            score += 20
        y = _year_from_chunk(year)
        if wants_next and y is not None:
            score += 22 if y >= now_y else -12
        scored.append((score, chunk))

    for d in DATE_PATTERN.findall(text):
        idx = text.find(d)
        window = _sentence_window(text, idx, idx + len(d)) if idx >= 0 else text
        if EDIT_STAMP_RE.search(window):
            continue
        score = _overlap(query, window) * 8
        if re.search(r"\b(held|host|opens?|begins?|games|olympics?|release|debut)\b", window, re.I):
            score += 20
        y = _year_from_chunk(d)
        if wants_next and y is not None:
            score += 22 if y >= now_y else -12
        scored.append((score, d))

    for m in EVENT_YEAR_RE.finditer(text):
        window = _sentence_window(text, m.start(), m.end())
        if EDIT_STAMP_RE.search(window):
            continue
        label = re.sub(r"\s+", " ", m.group(0)).strip()
        score = _overlap(query, window) + 25
        y = _year_from_chunk(label)
        if wants_next and y is not None:
            score += 30 if y >= now_y else -20
        scored.append((score, label))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[str] = []
    for score, chunk in scored:
        if score < 6:
            continue
        if VAGUE_SEASON_RE.search(chunk):
            continue
        if chunk not in out:
            out.append(chunk)
    return out


def _extract_places(text: str, query: str = "") -> List[str]:
    places = []
    text = text or ""
    wants_next = _wants_next(query)
    now_y = _now_year()
    for m in PLACE_RE.finditer(text):
        window = _sentence_window(text, m.start(), m.end())
        if EDIT_STAMP_RE.search(window):
            continue
        p = m.group(1).strip()
        if p.lower() in PLACE_STOP:
            continue
        if query and _overlap(query, window) == 0 and _overlap(query, p) == 0:
            continue
        years = [int(x.group(1)) for x in re.finditer(r"\b((?:19|20)\d{2})\b", window)]
        if wants_next and years and max(years) < now_y and not any(y >= now_y for y in years):
            continue
        if p not in places:
            places.append(p)
    return places


def _extract_proper_nouns(text: str, max_items: int = 6) -> List[str]:
    matches = NOUN_PATTERN.findall(text or "")
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
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _first_sentence_with(text: str, keyword: str) -> Optional[str]:
    for s in _split_sentences(text):
        if keyword.lower() in s.lower():
            return s
    return None


def _best_sentences(query: str, raw_text: str, n: int = 3) -> List[str]:
    sents = _split_sentences(raw_text)
    wants_next = _wants_next(query)
    now_y = _now_year()
    ranked = []
    for s in sents:
        if HISTORY_PAGE_RE.search(s) and _overlap(query, s) < 2:
            continue
        if EDIT_STAMP_RE.search(s):
            continue
        if VAGUE_SEASON_RE.search(s) and not YEAR_PATTERN.search(s):
            continue
        score = _overlap(query, s) * 10
        if EVENT_YEAR_RE.search(s):
            score += 30
        if MONTH_YEAR_RE.search(s) or DATE_PATTERN.search(s):
            score += 20
        if PLACE_RE.search(s) and re.search(r"\b(where|hosted|city|venue|olympics)\b", query or "", re.I):
            score += 15
        years = [int(m.group(1)) for m in re.finditer(r"\b((?:19|20)\d{2})\b", s)]
        if wants_next and years:
            if any(y >= now_y for y in years):
                score += 24
            elif max(years) < now_y:
                score -= 16
        ranked.append((score, s))
    ranked.sort(key=lambda x: x[0], reverse=True)
    picked = [s for score, s in ranked if score > 0][:n]
    return picked or [s for _, s in ranked[:n]] or sents[:n]


def _analyze_with_safety(query: str, results: List[dict], raw_text: str) -> str:
    q_low = (query or "").lower()
    is_death = bool(DEATH_PATTERN.search(q_low))
    is_site = bool(SITE_PATTERN.search(query or ""))
    wants_when = bool(re.search(
        r"\b(when|date|release|released|schedule|scheduled|due|coming out|opens?|debut|olympics?|next)\b",
        q_low,
    ))
    wants_where = bool(re.search(
        r"\b(where|hosted|location|city|venue|held|olympics?|next)\b",
        q_low,
    ))

    if is_site:
        best = _best_site_result(query, results)
        if best and best.get("href"):
            url = _normalize_url(best["href"])
            label = _pretty_domain(url) or "official site"
            return f"Official site: **[{label}]({url})**"
        return safe_note("Couldn't confidently find an official website link.")

    if is_death:
        reliable_sources = set()
        for r in results:
            combined = f"{r.get('title', '')} {r.get('body', '')}".lower()
            if any(k in combined for k in ("died", "has died", "was killed", "passed away", "assassinated", "shot")):
                url = r.get("href", "")
                if _domain_ok(url):
                    reliable_sources.add(url)
                    print(f"[LiveWeb Debug] Reliable source found: {url}")
        if len(reliable_sources) < 1:
            return safe_note("Death claim unverified by reliable sources. Treat as unconfirmed.")

    dates = _extract_dates(raw_text, query)
    places = _extract_places(raw_text, query)
    nouns = _extract_proper_nouns(raw_text)

    def bold_once(s: str) -> str:
        used = set()
        for ent in dates + places + nouns:
            if not ent or ent in used:
                continue
            s = re.sub(rf"\b{re.escape(ent)}\b", f"**{ent}**", s, count=1)
            used.add(ent)
        return s

    if is_death:
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
        if nouns and "killer" in q_low:
            summary += f" (Names: {', '.join(nouns[:2])})"
        return bold_once(summary)

    parts = []
    if dates and wants_when:
        parts.append(f"Date: {dates[0]}.")
    if places and wants_where:
        parts.append(f"Place: {places[0]}.")
    sents = _best_sentences(query, raw_text, n=2)
    if sents:
        parts.append(_shorten(" ".join(sents), 360))
    if not parts:
        return "No meaningful summary derived."
    return bold_once(" ".join(parts))


def safe_note(msg: str) -> str:
    return f"**Note:** {msg}"


_cache: dict = {}
_CACHE_TTL = 90


def cached_perform_live_search(
    query: str,
    max_results: int = 8,
    browse_mode: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    now = time.time()
    key = ((query or "").lower(), max_results, bool(browse_mode))
    entry = _cache.get(key)
    if entry and now - entry["time"] < _CACHE_TTL:
        return entry["raw"], entry["analyzed"]
    raw, analyzed = perform_live_search(query, max_results=max_results, browse_mode=browse_mode)
    _cache[key] = {"time": now, "raw": raw, "analyzed": analyzed}
    return raw, analyzed


if __name__ == "__main__":
    tests = [
        "what year is it",
        "when does VisionQuest come out",
        "when is the next olympics and where",
        "Spider-Man Brand New Day release date",
        "hi",
    ]
    print(f"[Info] DDG available: {_DDG_AVAILABLE}; {_DDG_IMPORT_ERR or ''}")
    for t in tests:
        print("\nQuery:", t)
        print("  needs_live:", needs_live_data(t, False))
        print("  rewritten:", _rewrite_query(t))

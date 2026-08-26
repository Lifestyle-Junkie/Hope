"""
liveweb.py
Live search + guarded factual extraction + optional real browser surfing.
Browse / Computer Use ONLY when browse_mode=True (globe icon on).
"""
from __future__ import annotations
import re
import time
import html
from typing import List, Tuple, Optional
from urllib.parse import urlparse
# ---------------- Package Import ----------------
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
# ---------------- Patterns ----------------
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
    r"go to|open|visit|navigate|browse|surf|"
    r"look (this|that|it) up on the (site|page|website)|"
    r"on (the )?(site|page|website)|"
    r"click|fill (out|in)|scroll (down|up|to)|"
    r"read (the|this|that) (page|site|article)|"
    r"check (the|this|that) (page|site|website)"
    r")\b",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE
)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
NOUN_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
LIVE_KEYWORDS = {
    "when", "date", "release", "latest", "recent", "today", "this week",
    "breaking", "update", "news", "launched", "announced", "died", "death",
    "killed", "passed", "cause of death", "assassinated", "shot",
}
RELIABLE_DOMAINS = {
    "apnews.com", "associatedpress.com", "reuters.com", "bbc.com", "bbc.co.uk",
    "nytimes.com", "theguardian.com", "washingtonpost.com", "bloomberg.com",
    "wsj.com", "npr.org", "abcnews.go.com", "cbsnews.com", "cnn.com",
    "wikipedia.org", "aljazeera.com", "foxnews.com", "usatoday.com",
    "nbcnews.com", "axios.com", "pbs.org"
}
SKIP_HOST_PARTS = {
    "facebook.", "twitter.", "x.com", "instagram.", "youtube.", "reddit.",
    "substack.com", "medium.com", "tiktok.", "linkedin.", "pinterest."
}
# ---------------- Browser agent ----------------
def should_browse(query: str, browse_mode: bool = False) -> bool:
    """Computer Use only when the globe (browse_mode) is on."""
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
    return True  # globe on = user asked to use the live browser
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
# ---------------- Public API ----------------
def needs_live_data(query: str, browse_mode: bool = False) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    if CODE_INTENT_RE.search(q) and not should_browse(q, browse_mode):
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
    if any(k in low for k in LIVE_KEYWORDS):
        return True
    # Do NOT treat every "Are there open source smart rings?" as live search
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
    corrected_query = query
    entity_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", query or "")
    if entity_match:
        corrected_name = correct_name_spelling(entity_match.group(0))
        corrected_query = query.replace(entity_match.group(0), corrected_name)
        if corrected_query != query:
            print(f"[LiveWeb] Corrected query: {query} -> {corrected_query}")
    if SITE_PATTERN.search(query or ""):
        if "official" not in corrected_query.lower():
            corrected_query = f"{corrected_query} official website"
    if not _DDG_AVAILABLE:
        return None, safe_note("Live search unavailable (install ddgs).")
    results = _search_duckduckgo(corrected_query, max_results=max_results)
    if not results:
        if DEATH_PATTERN.search(query or ""):
            return None, safe_note("No reliable sources confirming a death. Treat as unconfirmed.")
        return None, safe_note("No live results found.")
    raw_text = _merge_results(results, query=corrected_query)
    print(f"[LiveWeb Debug] Raw text (trunc): {raw_text[:200]}{'...' if len(raw_text) > 200 else ''}")
    analyzed = _analyze_with_safety(query, results, raw_text)
    return raw_text, analyzed
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
    stop = {
        "what", "is", "the", "site", "website", "url", "link", "for", "official",
        "page", "homepage", "of", "a", "an", "to", "go", "find", "where", "can", "i",
        "send", "me", "give", "drop", "share"
    }
    tokens = [t for t in q.split() if t and t not in stop]
    brand = tokens[0] if tokens else ""
    scored = []
    for r in results:
        href = _normalize_url(r.get("href") or "")
        if not href:
            continue
        host = _pretty_domain(href)
        score = 0
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
        elif path.count("/") >= 3:
            score -= 5
        scored.append((score, {**r, "href": href}))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < 10:
        return None
    return best
def _merge_results(results: List[dict], query: str, char_limit: int = 2400) -> str:
    death_re = re.compile(r"\b(die|died|death|killed|assassinated|shot)\b", re.IGNORECASE)
    entity_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", query or "")
    entity = entity_match.group(0).lower() if entity_match else None
    def score_snippet(r):
        score = 0
        combined = f"{r.get('title', '')} {r.get('body', '')}".lower()
        if death_re.search(combined):
            score += 20
        if DATE_PATTERN.search(combined):
            score += 5
        if NOUN_PATTERN.search(combined):
            score += 10
        if entity and entity in combined:
            score += 15
        if _domain_ok(r.get("href", "")):
            score += 20
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
def _extract_dates(text: str) -> List[str]:
    dates = DATE_PATTERN.findall(text or "")
    return list(dict.fromkeys(dates))
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
def _analyze_with_safety(query: str, results: List[dict], raw_text: str) -> str:
    q_low = (query or "").lower()
    is_death = bool(DEATH_PATTERN.search(q_low))
    is_site = bool(SITE_PATTERN.search(query or ""))
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
    sents = _split_sentences(raw_text)[:2]
    if not sents:
        return bold_once("No meaningful summary derived.")
    summary = _shorten(" ".join(sents), 420)
    return bold_once(summary)
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
        "are there opensource smart rings",
        "what is the site for rainbet",
        "send me the link",
        "How did Alan Turing die",
        "write me a html code for a dropshipping website",
        "go to home-assistant.io and tell me what it can do",
    ]
    print(f"[Info] DDG available: {_DDG_AVAILABLE}; {_DDG_IMPORT_ERR or ''}")
    for t in tests:
        print("\nQuery:", t)
        print("  browse_mode=False should_browse:", should_browse(t, False))
        print("  browse_mode=True  should_browse:", should_browse(t, True))
        print("  needs_live (off):", needs_live_data(t, False))

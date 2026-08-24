"""
links.py
URL extraction, site map, and "link to X" / follow-up helpers.
"""
from __future__ import annotations
import re
from typing import Optional, Tuple

from sanitize import sanitize_reply
from memory import STOPWORDS

LINK_FOLLOWUP_RE = re.compile(
    r"^\s*((please|pls|can you|could you)\s+)?"
    r"(send|give|drop|share|post)?\s*"
    r"(me\s+)?(the\s+)?(link|url|website|site)\s*\??\s*$",
    re.IGNORECASE,
)

LINK_TO_RE = re.compile(
    r"\b(?:(?:official|the)\s+)?(?:link|url|website|site)\s+(?:to|for)\s+([A-Za-z0-9][\w.-]*)\b",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|co|app|ai|gg|tv|me|us|uk|ca|de|fr|nz)\b",
    re.IGNORECASE,
)

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


def is_link_followup(prompt: str) -> bool:
    return bool(LINK_FOLLOWUP_RE.match(prompt or ""))


def extract_url_from_text(text: Optional[str]) -> Optional[str]:
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


def format_md_link(url: str) -> str:
    host = re.sub(r"^https?://(www\.)?", "", url, flags=re.IGNORECASE).split("/")[0]
    return f"[{host}]({url})"


def link_request_reply(prompt: str) -> Optional[Tuple[str, str]]:
    """
    Explicit "link to X" / "official link for yahoo" → (reply, url).
    """
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

    reply = f"Here you go: {format_md_link(url)}"
    return reply, url


def prefer_site_url_from_prompt(prompt: str, current: Optional[str] = None) -> Optional[str]:
    """If user mentions a known site name, prefer that URL for memory."""
    found = current
    for site_name, site_url in SITE_NAME_TO_URL.items():
        if re.search(rf"\b{re.escape(site_name)}\b", prompt or "", re.IGNORECASE):
            found = site_url
            break
    return found

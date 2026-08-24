"""
sanitize.py
Clean HTML / mangled anchors out of model replies and stored memory.
"""
from __future__ import annotations
import re
from typing import Optional


def sanitize_reply(text: Optional[str]) -> str:
    """
    Convert HTML anchors / mangled link junk into clean markdown or plain URLs.
    Never leave target= / rel= debris in stored memory or API replies.
    """
    if not text:
        return ""
    s = str(text)
    s = re.sub(
        r'<a\s+[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        lambda m: f"[{(m.group(2) or m.group(1)).strip()}]({m.group(1).strip()})",
        s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    s = re.sub(
        r'(https?://[^\s"\'<>]+)"\s*target=["\']?_blank["\']?\s*rel=["\'][^"\']*["\']\s*>([^\n<]+)',
        lambda m: f"[{m.group(2).strip()}]({m.group(1).strip()})",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"<[^>]+>", "", s)
    s = (
        s.replace("&nbsp;", " ")
         .replace("&amp;", "&")
         .replace("&lt;", "<")
         .replace("&gt;", ">")
         .replace("&quot;", '"')
         .replace("&#39;", "'")
    )
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

"""
sanitize.py
Clean HTML / mangled anchors out of model replies and stored memory.
Preserves fenced code blocks (```...```) so HTML previews stay intact.
"""
from __future__ import annotations
import re
from typing import Optional, List


def sanitize_reply(text: Optional[str]) -> str:
    """
    Convert HTML anchors / mangled link junk into clean markdown or plain URLs.
    Never leave target= / rel= debris in stored memory or API replies.
    Keep ``` fenced blocks untouched (needed for live HTML preview in chat).
    """
    if not text:
        return ""
    s = str(text)

    # Protect fenced code blocks so tags inside ```html ... ``` are not stripped
    fences: List[str] = []

    def _save_fence(m: re.Match) -> str:
        fences.append(m.group(0))
        return f"\0FENCE{len(fences) - 1}\0"

    s = re.sub(r"```[\s\S]*?```", _save_fence, s)

    # Real HTML anchors → markdown
    s = re.sub(
        r'<a\s+[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        lambda m: f"[{(m.group(2) or m.group(1)).strip()}]({m.group(1).strip()})",
        s,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Mangled target=_blank debris
    s = re.sub(
        r'(https?://[^\s"\'<>]+)"\s*target=["\']?_blank["\']?\s*rel=["\'][^"\']*["\']\s*>([^\n<]+)',
        lambda m: f"[{m.group(2).strip()}]({m.group(1).strip()})",
        s,
        flags=re.IGNORECASE,
    )

    # Strip remaining tags only outside fences
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

    # Restore fenced blocks
    for i, fence in enumerate(fences):
        s = s.replace(f"\0FENCE{i}\0", fence)

    return s.strip()

"""
market.py
Yahoo Finance quote helper for Hope
+ stock-question detection used by /ask

Fixes:
- Common English / product words (shoes, html, page, etc.) are never treated as tickers
- Pure single-word messages only count as tickers if not in COMMON_WORDS
"""
from __future__ import annotations
import re
import requests
from typing import Optional, Dict, Any, List, Tuple

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ---------- Stock intent maps / regex ----------
COMPANY_TO_TICKER = {
    "shopify": "SHOP",
    "apple": "AAPL",
    "comcast": "CMCSA",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "disney": "DIS",
    "amd": "AMD",
    "intel": "INTC",
    "coinbase": "COIN",
    "robinhood": "HOOD",
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
    # product / code words that were being misread as tickers
    "SHOES", "SHOE", "HTML", "CODE", "PAGE", "STORE", "BASIC", "FULL",
    "PRODUCT", "DROP", "CSS", "JSON", "HTTP", "HTTPS", "FILE", "SCRIPT",
    "CLASS", "STYLE", "IMAGE", "VIDEO", "AUDIO", "TEXT", "WRITE", "MAKE",
}

# Lowercase common words — pure messages like "shoes" must NOT hit the stock path
COMMON_WORDS = {
    "shoes", "shoe", "html", "css", "code", "page", "store", "basic", "full",
    "just", "product", "website", "hello", "thanks", "please", "price",
    "script", "function", "class", "file", "image", "video", "audio", "text",
    "write", "make", "create", "build", "dropship", "dropshipping", "shop",
    "yes", "no", "ok", "okay", "hi", "hey", "thanks", "thank", "please",
    "python", "javascript", "java", "sql", "react", "flask",
}

STOCK_KEYWORD_RE = re.compile(
    r"\b(stock|share|shares|ticker|quote|trading at|price of|stock price|share price|"
    r"current price|at rn|right now price|market cap)\b",
    re.IGNORECASE,
)
STOCK_FOLLOWUP_RE = re.compile(
    r"\b(check( it)? again|check again|update( it)?|refresh|price now|how about now|"
    r"what(?:'s| is)? (?:it|that|the price) now)\b",
    re.IGNORECASE,
)
IDENTITY_RE = re.compile(
    r"\b(who made you|who created you|who designed you|who are you|what are you|"
    r"what(?:'s| is)? your name|are you (an ai|a bot)|who is hope|who is god)\b",
    re.IGNORECASE,
)
WHAT_IS_RE = re.compile(
    r"^\s*(what(?:'s| is| are)|who is|tell me about|explain)\b",
    re.IGNORECASE,
)
CODE_OR_BUILD_RE = re.compile(
    r"\b(html|css|python|javascript|js|code|script|dropship|product page|write me|write a)\b",
    re.IGNORECASE,
)


def _safe_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def get_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a single quote from Yahoo Finance.
    Example:
        get_quote("SHOP")
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None

    url = YAHOO_CHART_URL.format(symbol=symbol)
    params = {
        "interval": "1d",
        "range": "5d",
        "includePrePost": "true",
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=12)
        if resp.status_code != 200:
            print(f"[Market] Yahoo error {resp.status_code} for {symbol}: {resp.text[:200]}")
            return None
        data = resp.json()
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            print(f"[Market] No result for {symbol}")
            return None
        meta = result[0].get("meta") or {}
        price = _safe_float(
            meta.get("regularMarketPrice")
            or meta.get("postMarketPrice")
            or meta.get("preMarketPrice")
        )
        previous_close = _safe_float(
            meta.get("chartPreviousClose")
            or meta.get("previousClose")
        )
        change = None
        change_percent = None
        if price is not None and previous_close is not None and previous_close != 0:
            change = price - previous_close
            change_percent = (change / previous_close) * 100.0
        return {
            "symbol": symbol,
            "price": price,
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
            "market_state": meta.get("marketState"),
            "raw_meta": {
                "regularMarketPrice": meta.get("regularMarketPrice"),
                "previousClose": meta.get("previousClose"),
                "chartPreviousClose": meta.get("chartPreviousClose"),
            },
        }
    except Exception as e:
        print(f"[Market] Exception for {symbol}: {e}")
        return None


def get_quotes(symbols: List[str]) -> List[Dict[str, Any]]:
    """Fetch multiple quotes."""
    out = []
    for sym in symbols:
        q = get_quote(sym)
        if q:
            out.append(q)
    return out


def format_quote_line(q: Dict[str, Any]) -> str:
    """
    Short readable line for briefing.
    Example:
      SHOP: $97.20 (prev close $95.40, +1.89%)
    """
    if not q:
        return "No data"
    symbol = q.get("symbol", "?")
    price = q.get("price")
    prev = q.get("previous_close")
    change_percent = q.get("change_percent")
    if price is None:
        return f"{symbol}: price unavailable"
    price_txt = f"${price:,.2f}"
    prev_txt = f"${prev:,.2f}" if prev is not None else "n/a"
    if change_percent is None:
        return f"{symbol}: {price_txt} (prev close {prev_txt})"
    sign = "+" if change_percent >= 0 else ""
    return f"{symbol}: {price_txt} (prev close {prev_txt}, {sign}{change_percent:.2f}%)"


# ---------- Stock detection for /ask ----------
def extract_company_ticker(prompt: str) -> Optional[str]:
    lower = (prompt or "").lower()
    for name, ticker in COMPANY_TO_TICKER.items():
        if re.search(rf"\b{re.escape(name)}\b", lower):
            return ticker
    return None


def extract_explicit_ticker(prompt: str) -> Optional[str]:
    text = (prompt or "").strip()
    candidates = re.findall(r"\b[A-Z]{2,5}\b", text)
    if not candidates:
        candidates = re.findall(r"\b[A-Z]{2,5}\b", text.upper())
    for tok in candidates:
        up = tok.upper()
        if up not in IGNORE_TICKERS and 2 <= len(up) <= 5:
            # also block if the original token is a common word
            if tok.lower() in COMMON_WORDS or up.lower() in COMMON_WORDS:
                continue
            return up
    return None


def looks_like_stock_question(prompt: str, has_last_ticker: bool = False) -> bool:
    """Stock path only when price/stock language is present, or pure ticker, or follow-up."""
    if not prompt:
        return False
    if IDENTITY_RE.search(prompt):
        return False
    if CODE_OR_BUILD_RE.search(prompt):
        return False
    if WHAT_IS_RE.search(prompt) and not STOCK_KEYWORD_RE.search(prompt):
        return False

    lower = prompt.strip().lower()
    # Single common word (e.g. "shoes") is never a stock question
    if lower in COMMON_WORDS:
        return False
    # Strip trailing ? for the same check
    if lower.rstrip("?") in COMMON_WORDS:
        return False

    company = extract_company_ticker(prompt)
    explicit = extract_explicit_ticker(prompt)
    has_stock_kw = bool(STOCK_KEYWORD_RE.search(prompt))
    is_followup = bool(STOCK_FOLLOWUP_RE.search(prompt))

    if company and has_stock_kw:
        return True
    if explicit and has_stock_kw:
        return True
    # Pure ticker message (e.g. "AAPL" or "SHOP") — but not common words
    if explicit and re.fullmatch(r"[A-Za-z]{2,5}\??", prompt.strip()):
        if lower.rstrip("?") not in COMMON_WORDS:
            return True
    if has_last_ticker and is_followup:
        return True
    return False


def quote_reply_for_prompt(
    prompt: str,
    last_ticker: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    If this looks like a stock question, return (reply_text, ticker_used).
    Otherwise None.
    """
    has_last = bool(last_ticker)
    if not looks_like_stock_question(prompt, has_last_ticker=has_last):
        return None

    ticker = extract_company_ticker(prompt) or extract_explicit_ticker(prompt)
    if not ticker and has_last and STOCK_FOLLOWUP_RE.search(prompt or ""):
        ticker = last_ticker
    if not ticker:
        return None

    # Extra safety: never quote common words even if something slipped through
    if ticker.lower() in COMMON_WORDS or ticker in IGNORE_TICKERS:
        return None

    if re.search(
        r"\b(when was|what day|which day|history|historical|last time it)\b",
        prompt or "",
        re.IGNORECASE,
    ):
        return None

    print(f"[Market] Detected stock question for ticker={ticker}")
    q = get_quote(ticker)
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


if __name__ == "__main__":
    for s in ["SHOP", "AAPL", "CMCSA"]:
        q = get_quote(s)
        print(format_quote_line(q) if q else f"{s}: failed")

    # Sanity checks
    assert looks_like_stock_question("shoes") is False
    assert looks_like_stock_question("html") is False
    assert looks_like_stock_question("AAPL") is True
    assert looks_like_stock_question("what's the stock price of shopify") is True
    print("market.py self-checks passed")

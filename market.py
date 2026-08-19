"""
market.py
Yahoo Finance quote helper for Hope
Returns current price, previous close, and change data.
"""

from __future__ import annotations
import requests
from typing import Optional, Dict, Any, List

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


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


if __name__ == "__main__":
    for s in ["SHOP", "AAPL", "CMCSA"]:
        q = get_quote(s)
        print(format_quote_line(q) if q else f"{s}: failed")

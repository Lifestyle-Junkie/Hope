"""
places.py
Live Google Places lookup around the user's GPS.
No hardcoded stores — query is whatever the user said.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

NEAR_RE = re.compile(
    r"\b(near me|nearby|closest|nearest|how far|how long|minutes? away|"
    r"distance (to|from)|where is|find (a |an |the )?|"
    r"restaurants?|arcades?|gas stations?|coffee|pizza|stores?)\b",
    re.IGNORECASE,
)

STRIP_RE = re.compile(
    r"\b(open maps|show maps|maps are on|hope[,.]?|tell me|"
    r"how far( am i)?( from)?|how long|nearest|closest|nearby|near me|"
    r"the|a|an|to|from|me|my|please|whats|what's|where is)\b",
    re.IGNORECASE,
)


def looks_like_place_query(text: str) -> bool:
    return bool(NEAR_RE.search(text or ""))


def query_from_prompt(text: str) -> str:
    q = STRIP_RE.sub(" ", text or "")
    q = re.sub(r"[?!.]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q or (text or "").strip()


def _parse_origin(origin: Optional[str]) -> Optional[Tuple[float, float]]:
    if not origin:
        return None
    m = re.match(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$", origin)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1, math.sqrt(h)))


def search_nearby(origin: Optional[str], prompt: str, key: Optional[str] = None) -> Dict[str, Any]:
    key = (key or os.getenv("MAPS_API_KEY", "")).strip()
    q = query_from_prompt(prompt)
    coords = _parse_origin(origin)
    if not key:
        return {"ok": False, "error": "MAPS_API_KEY missing", "places": [], "reply": None}
    if not q:
        return {"ok": False, "error": "empty query", "places": [], "reply": None}

    params: Dict[str, Any] = {"query": q, "key": key}
    if coords:
        params["location"] = f"{coords[0]},{coords[1]}"
        params["radius"] = 16000

    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/textsearch/json",
            params=params,
            timeout=12,
        )
        data = r.json()
    except Exception as e:
        return {"ok": False, "error": str(e), "places": [], "reply": None}

    status = data.get("status")
    results = data.get("results") or []
    places: List[Dict[str, Any]] = []
    for item in results[:5]:
        loc = ((item.get("geometry") or {}).get("location") or {})
        lat, lng = loc.get("lat"), loc.get("lng")
        miles = None
        if coords and lat is not None and lng is not None:
            miles = round(_miles(coords, (float(lat), float(lng))), 1)
        places.append({
            "name": item.get("name") or "",
            "address": item.get("formatted_address") or item.get("vicinity") or "",
            "lat": lat,
            "lng": lng,
            "miles": miles,
            "rating": item.get("rating"),
        })

    if not places:
        msg = f"I couldn't find {q} near you."
        if status and status != "OK":
            msg += f" ({status})"
        return {"ok": False, "error": status or "zero results", "places": [], "reply": msg, "query": q}

    top = places[0]
    miles_bit = f", about {top['miles']} miles away" if top.get("miles") is not None else ""
    reply = f"Closest {q} is {top['name']} at {top['address']}{miles_bit}."
    extras = []
    for p in places[1:3]:
        m = f" ({p['miles']} mi)" if p.get("miles") is not None else ""
        extras.append(f"{p['name']}{m}")
    if extras:
        reply += " Also nearby: " + "; ".join(extras) + "."

    return {
        "ok": True,
        "query": q,
        "places": places,
        "reply": reply,
        "destination": top.get("address") or top.get("name"),
    }

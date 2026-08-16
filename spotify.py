"""
spotify.py
Spotify helper for Hope / God Discord music bot
"""

import os
import base64
import aiohttp
from typing import Optional, Dict, Any, List

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

_token_cache = {
    "access_token": None,
    "expires_at": 0
}


async def _get_access_token() -> Optional[str]:
    """Get a Spotify app access token (Client Credentials flow)."""
    import time

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("[Spotify] Missing CLIENT_ID or CLIENT_SECRET")
        return None

    # Return cached token if still valid
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    auth = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth.encode()).decode()

    url = "https://accounts.spotify.com/api/token"
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[Spotify] Token error {resp.status}: {text}")
                    return None
                payload = await resp.json()
                _token_cache["access_token"] = payload["access_token"]
                _token_cache["expires_at"] = time.time() + payload.get("expires_in", 3600)
                return _token_cache["access_token"]
    except Exception as e:
        print(f"[Spotify] Token exception: {e}")
        return None


async def search_track(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search Spotify for tracks.
    Returns a list of dicts: name, artists, url, uri, duration_ms
    """
    token = await _get_access_token()
    if not token:
        return []

    url = "https://api.spotify.com/v1/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": query,
        "type": "track",
        "limit": limit
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[Spotify] Search error {resp.status}: {text}")
                    return []
                data = await resp.json()
                items = data.get("tracks", {}).get("items", [])
                results = []
                for t in items:
                    artists = ", ".join(a["name"] for a in t.get("artists", []))
                    results.append({
                        "name": t.get("name"),
                        "artists": artists,
                        "url": t.get("external_urls", {}).get("spotify"),
                        "uri": t.get("uri"),
                        "duration_ms": t.get("duration_ms"),
                        "album": t.get("album", {}).get("name")
                    })
                return results
    except Exception as e:
        print(f"[Spotify] Search exception: {e}")
        return []


async def format_track(track: Dict[str, Any]) -> str:
    """Nice display string for a track."""
    return f"**{track['name']}** — {track['artists']}"

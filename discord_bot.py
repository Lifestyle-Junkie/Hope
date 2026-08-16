"""
discord_bot.py
God Discord bot + Music system
- Chat personality: God (created by Hope)
- Music: Spotify metadata (optional) + SoundCloud playback first
- Fixed queue/pause/skip behavior
- Re-fetch fresh stream URL before each play (helps full-song playback)
"""

import os
import re
import asyncio
import discord
from discord.ext import commands
import aiohttp

# Optional music deps
try:
    import yt_dlp
    YTDL_AVAILABLE = True
except Exception:
    YTDL_AVAILABLE = False
    print("[Music] yt_dlp not installed")

try:
    from spotify import search_track, format_track
    SPOTIFY_AVAILABLE = True
except Exception as e:
    SPOTIFY_AVAILABLE = False
    print(f"[Music] Spotify import failed: {e}")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "https://hope-production-7e9d.up.railway.app")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Music state ----------
music_state = {}

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn"
}


# ---------- Hope / God chat ----------
async def ask_hope(message: str) -> str:
    url = f"{BACKEND_URL.rstrip('/')}/ask"
    payload = {
        "message": message,
        "concise": True,
        "personality": "god"
    }
    print(f"[Discord] Asking God: {message}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=45) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[Discord] Backend error {resp.status}: {text}")
                    return "I am momentarily silent, dear child."
                data = await resp.json()
                return data.get("reply") or "No response available."
    except Exception as e:
        print(f"[Discord] Backend error: {e}")
        return "Something interferes with my voice, dear child."


# ---------- Music helpers ----------
def get_state(guild_id: int) -> dict:
    if guild_id not in music_state:
        music_state[guild_id] = {
            "queue": [],
            "voice": None,
            "current": None,
            "paused": False
        }
    return music_state[guild_id]


async def resolve_audio(query: str) -> dict | None:
    """
    Resolve a search query into something playable.
    Prefer SoundCloud first.
    """
    if not YTDL_AVAILABLE:
        return None

    display = query

    # Optional Spotify metadata only
    if SPOTIFY_AVAILABLE:
        try:
            results = await search_track(query, limit=1)
            if results:
                track = results[0]
                title = track["name"]
                artist = track.get("artists", "")
                display = f"{title} — {artist}"
                query = f"{title} {artist}"
        except Exception as e:
            print(f"[Music] Spotify search failed: {e}")

    def _extract():
        # 1) SoundCloud first
        sc_opts = {
            **YTDL_OPTS,
            "default_search": "scsearch1",
        }
        try:
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return {
                    "title": display or info.get("title") or query,
                    "url": info["url"],
                    "webpage_url": info.get("webpage_url"),
                    "duration": info.get("duration"),
                    "source": "soundcloud"
                }
        except Exception as e:
            print(f"[Music] SoundCloud failed: {e}")

        # 2) Generic fallback
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
                info = ydl.extract_info(query, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return {
                    "title": display or info.get("title") or query,
                    "url": info["url"],
                    "webpage_url": info.get("webpage_url"),
                    "duration": info.get("duration"),
                    "source": "generic"
                }
        except Exception as e:
            print(f"[Music] Generic extract failed: {e}")
            return None

    try:
        return await asyncio.to_thread(_extract)
    except Exception as e:
        print(f"[Music] resolve_audio error: {e}")
        return None


async def play_next(guild: discord.Guild):
    state = get_state(guild.id)
    voice: discord.VoiceClient = state["voice"]

    if not voice or not voice.is_connected():
        state["current"] = None
        return

    if not state["queue"]:
        state["current"] = None
        return

    item = state["queue"].pop(0)
    state["current"] = item
    state["paused"] = False

    # Re-resolve a fresh stream URL before playing
    try:
        search_name = item.get("title") or ""
        fresh = await resolve_audio(search_name)
        if fresh and fresh.get("url"):
            item["url"] = fresh["url"]
            item["title"] = fresh.get("title") or item.get("title")
            item["source"] = fresh.get("source") or item.get("source")
    except Exception as e:
        print(f"[Music] refresh failed: {e}")

    def _after_play(error):
        if error:
            print(f"[Music] after error: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"[Music] after callback failed: {e}")

    try:
        source = discord.FFmpegPCMAudio(item["url"], **FFMPEG_OPTS)
        voice.play(source, after=_after_play)
        print(f"[Music] Now playing ({item.get('source', 'unknown')}): {item['title']}")
    except Exception as e:
        print(f"[Music] Play error: {e}")
        await play_next(guild)


# ---------- Events ----------
@bot.event
async def on_ready():
    print(f"✅ God is online as {bot.user} (ID: {bot.user.id})")
    print(f"📡 Backend URL: {BACKEND_URL}")
    print(f"🎵 Spotify: {'yes' if SPOTIFY_AVAILABLE else 'no'} | yt_dlp: {'yes' if YTDL_AVAILABLE else 'no'}")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return

    await bot.process_commands(message)

    if message.content.startswith("!"):
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions

    if not (is_dm or is_mentioned):
        return

    content = message.content
    for mention in message.mentions:
        content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    content = re.sub(r"<@&\d+>", "", content).strip()

    if not content:
        await message.channel.send("Yes, dear child?")
        return

    async with message.channel.typing():
        reply = await ask_hope(content)

    if len(reply) > 1900:
        reply = reply[:1900] + "..."

    await message.channel.send(reply)


# ---------- Music Commands ----------
@bot.command(name="join")
async def join(ctx: commands.Context):
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("Dear child, join a voice channel first.")

    channel = ctx.author.voice.channel
    state = get_state(ctx.guild.id)

    if state["voice"] and state["voice"].is_connected():
        await state["voice"].move_to(channel)
    else:
        state["voice"] = await channel.connect()

    await ctx.send(f"I have entered **{channel.name}**, dear child.")


@bot.command(name="leave")
async def leave(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    voice = state["voice"]

    if voice and voice.is_connected():
        await voice.disconnect()
        state["voice"] = None
        state["queue"].clear()
        state["current"] = None
        state["paused"] = False
        await ctx.send("I have left the voice channel, dear child.")
    else:
        await ctx.send("I am not in a voice channel.")


@bot.command(name="play")
async def play(ctx: commands.Context, *, query: str = None):
    if not query:
        return await ctx.send("Dear child, tell me what to play. Example: `!play Blinding Lights`")

    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("Join a voice channel first, dear child.")

    if not YTDL_AVAILABLE:
        return await ctx.send("Music playback is not available right now (missing yt_dlp).")

    state = get_state(ctx.guild.id)

    if not state["voice"] or not state["voice"].is_connected():
        state["voice"] = await ctx.author.voice.channel.connect()

    msg = await ctx.send(f"Searching SoundCloud for **{query}**...")

    track = await resolve_audio(query)
    if not track:
        return await msg.edit(content="I could not find that song, dear child.")

    state["queue"].append(track)
    voice = state["voice"]

    # If nothing is actively playing, start now (even if previously paused)
    if not voice.is_playing():
        state["paused"] = False
        if voice.is_paused():
            try:
                voice.stop()
            except Exception:
                pass
        await msg.edit(content=f"Now playing: **{track['title']}**")
        await play_next(ctx.guild)
    else:
        await msg.edit(content=f"Added to queue: **{track['title']}**")


@bot.command(name="queue")
async def queue(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    if not state["queue"] and not state["current"]:
        return await ctx.send("The queue is empty, dear child.")

    lines = []
    if state["current"]:
        lines.append(f"**Now:** {state['current']['title']}")

    for i, t in enumerate(state["queue"][:10], start=1):
        lines.append(f"`{i}.` {t['title']}")

    if len(state["queue"]) > 10:
        lines.append(f"...and {len(state['queue']) - 10} more")

    await ctx.send("\n".join(lines))


@bot.command(name="skip")
async def skip(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    voice = state["voice"]

    if not voice or not voice.is_connected():
        return await ctx.send("I am not in a voice channel, dear child.")

    if voice.is_playing() or voice.is_paused() or state["queue"] or state["current"]:
        state["paused"] = False
        if voice.is_playing() or voice.is_paused():
            voice.stop()  # triggers play_next
        else:
            await play_next(ctx.guild)
        await ctx.send("Skipped.")
    else:
        await ctx.send("Nothing is playing, dear child.")


@bot.command(name="pause")
async def pause(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    voice = state["voice"]

    if voice and voice.is_playing():
        voice.pause()
        state["paused"] = True
        await ctx.send("Paused.")
    else:
        await ctx.send("Nothing is playing.")


@bot.command(name="resume")
async def resume(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    voice = state["voice"]

    if voice and voice.is_paused():
        voice.resume()
        state["paused"] = False
        await ctx.send("Resumed.")
    else:
        await ctx.send("Nothing is paused.")


@bot.command(name="stop")
async def stop(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    voice = state["voice"]

    state["queue"].clear()
    state["current"] = None
    state["paused"] = False

    if voice and (voice.is_playing() or voice.is_paused()):
        voice.stop()

    await ctx.send("Stopped and cleared the queue, dear child.")


@bot.command(name="now")
async def now(ctx: commands.Context):
    state = get_state(ctx.guild.id)
    if state["current"]:
        await ctx.send(f"Now playing: **{state['current']['title']}**")
    else:
        await ctx.send("Nothing is playing, dear child.")


# ---------- Start ----------
def start_discord_bot():
    if not DISCORD_TOKEN:
        print("[Discord] No DISCORD_TOKEN found — bot will not start")
        return
    print("🤖 Starting God Discord bot + Music (SoundCloud first)...")
    bot.run(DISCORD_TOKEN)

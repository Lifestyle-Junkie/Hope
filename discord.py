"""
discord.py
Hope Discord bot
Talks to the existing Hope backend (/ask)
"""

import os
import discord
from discord.ext import commands
import aiohttp
import asyncio

# ---------- Config ----------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "https://hope-production-7e9d.up.railway.app")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is missing")

# ---------- Bot setup ----------
intents = discord.Intents.default()
intents.message_content = True  # required to read message text

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Helpers ----------
async def ask_hope(message: str) -> str:
    """Send a message to Hope backend and return the reply."""
    url = f"{BACKEND_URL.rstrip('/')}/ask"
    payload = {
        "message": message,
        "concise": True
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=45) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[Discord] Backend error {resp.status}: {text}")
                    return "Sorry, I'm having trouble thinking right now."

                data = await resp.json()
                return data.get("reply") or data.get("liveweb_analyzed") or "No response available."
    except Exception as e:
        print(f"[Discord] Error talking to backend: {e}")
        return "Sorry, I couldn't reach my brain right now."


# ---------- Events ----------
@bot.event
async def on_ready():
    print(f"✅ Hope is online as {bot.user}")
    print(f"📡 Backend: {BACKEND_URL}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore the bot's own messages
    if message.author == bot.user:
        return

    # Only respond when mentioned or in DMs
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions

    if not (is_dm or is_mentioned):
        return

    # Clean the message (remove the bot mention)
    content = message.content
    for mention in message.mentions:
        content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    content = content.strip()

    if not content:
        await message.channel.send("Yes? 😊")
        return

    # Show typing indicator
    async with message.channel.typing():
        reply = await ask_hope(content)

    # Discord has a 2000 character limit
    if len(reply) > 1900:
        reply = reply[:1900] + "..."

    await message.channel.send(reply)

    # Also allow normal commands if you add any later
    await bot.process_commands(message)


# ---------- Optional simple command ----------
@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("Pong ✨")


# ---------- Run ----------
if __name__ == "__main__":
    print("🚀 Starting Hope Discord bot...")
    bot.run(DISCORD_TOKEN)

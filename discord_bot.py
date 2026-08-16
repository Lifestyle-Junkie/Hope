"""
discord_bot.py
Hope Discord bot - runs alongside the Flask backend
"""

import os
import discord
from discord.ext import commands
import aiohttp

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "https://hope-production-7e9d.up.railway.app")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def ask_hope(message: str) -> str:
    url = f"{BACKEND_URL.rstrip('/')}/ask"
    payload = {"message": message, "concise": True}
    print(f"[Discord] Asking Hope: {message}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=45) as resp:
                print(f"[Discord] Backend status: {resp.status}")
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[Discord] Backend error body: {text}")
                    return "Sorry, I'm having trouble thinking right now."
                data = await resp.json()
                reply = data.get("reply") or data.get("liveweb_analyzed") or "No response available."
                print(f"[Discord] Hope replied: {reply[:100]}")
                return reply
    except Exception as e:
        print(f"[Discord] Backend error: {e}")
        return "Sorry, I couldn't reach my brain right now."


@bot.event
async def on_ready():
    print(f"✅ Hope Discord is online as {bot.user} (ID: {bot.user.id})")
    print(f"📡 Backend URL: {BACKEND_URL}")


@bot.event
async def on_message(message: discord.Message):
    print(f"[Discord] Message received from {message.author}: {message.content}")

    # Ignore the bot's own messages
    if message.author == bot.user or message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions

    print(f"[Discord] is_dm={is_dm} | is_mentioned={is_mentioned}")

    if not (is_dm or is_mentioned):
        return

    # Clean the message (remove the bot mention)
    content = message.content
    for mention in message.mentions:
        content = content.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    content = content.strip()

    print(f"[Discord] Cleaned content: '{content}'")

    if not content:
        await message.channel.send("Yes? 😊")
        return

    async with message.channel.typing():
        reply = await ask_hope(content)

    if len(reply) > 1900:
        reply = reply[:1900] + "..."

    await message.channel.send(reply)
    await bot.process_commands(message)


def start_discord_bot():
    if not DISCORD_TOKEN:
        print("[Discord] No DISCORD_TOKEN found — bot will not start")
        return
    print("🤖 Starting Discord bot...")
    bot.run(DISCORD_TOKEN)

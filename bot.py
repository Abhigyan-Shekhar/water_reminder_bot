# bot.py — Hydrate & Stretch Bot (pure slash edition)

import os
import random
import logging
import asyncio
import itertools
from pathlib import Path
from typing import Dict, Tuple, Optional, List

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ─────────── 0. Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ─────────── 1. Token / intents
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Put DISCORD_TOKEN=… inside .env")

intents = discord.Intents.default()
intents.message_content = False  # slash only, no text parsing

class HydrateBot(commands.Bot):
    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            logging.info("✅ Synced %d slash commands", len(synced))
        except Exception as e:
            logging.error(f"❌ Failed to sync slash commands: {e}")

bot = HydrateBot(command_prefix="!", intents=intents)

# ─────────── 2. Globals & storage
hydrate_tasks: Dict[int, Tuple[tasks.Loop, int]] = {}
stretch_tasks: Dict[int, Tuple[tasks.Loop, int]] = {}
TASKS_LOCK = asyncio.Lock()
PURGING = asyncio.Event()
MEME_CACHE: Dict[str, List[str]] = {}

status_list = [
    discord.Game("with water bottles 💧"),
    discord.Activity(type=discord.ActivityType.listening, name="hydration tips"),
    discord.Activity(type=discord.ActivityType.watching, name="your health"),
    discord.Streaming(name="hydration stream", url="https://twitch.tv/example"),
]
status_cycle = itertools.cycle(status_list)

@tasks.loop(seconds=10)
async def change_status():
    await bot.change_presence(activity=next(status_cycle))

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    if not change_status.is_running():
        change_status.start()

# ─────────── 3. Helpers
def get_random_meme(folder: str) -> Optional[str]:
    if folder not in MEME_CACHE:
        path = Path(folder)
        MEME_CACHE[folder] = [str(p) for p in path.iterdir() if p.is_file()] if path.is_dir() else []
    files = MEME_CACHE[folder]
    return random.choice(files) if files else None

async def cancel_loop(loop: tasks.Loop) -> None:
    if not loop.is_running():
        return
    loop.cancel()
    task = getattr(loop, "task", None) or getattr(loop, "_task", None)
    current = asyncio.current_task()
    if isinstance(task, asyncio.Task) and not task.done() and task is not current:
        try:
            await task
        except asyncio.CancelledError:
            pass

async def purge_all_reminders(reason: str) -> None:
    if PURGING.is_set():
        return
    PURGING.set()
    logging.warning("Purging all reminders – %s", reason)
    try:
        async with TASKS_LOCK:
            for uid, (loop, _) in list(hydrate_tasks.items()):
                await cancel_loop(loop)
                hydrate_tasks.pop(uid, None)
            for uid, (loop, _) in list(stretch_tasks.items()):
                await cancel_loop(loop)
                stretch_tasks.pop(uid, None)
    finally:
        PURGING.clear()

def make_reminder_loop(
    kind: str,
    minutes: int,
    channel: discord.TextChannel,
    mention: str,
    store: Dict[int, Tuple[tasks.Loop, int]],
    uid: int
) -> tasks.Loop:
    emoji = "💧" if kind == "hydrate" else "🤸"
    images_dir = "memes" if kind == "hydrate" else "stretch"

    async def tick():
        perms = channel.permissions_for(channel.guild.me)
        if not perms.send_messages:
            logging.warning("Lost send permission in %s – stopping loop", channel)
            loop.stop()
            async with TASKS_LOCK:
                store.pop(uid, None)
            return

        meme = get_random_meme(images_dir)
        content = f"{emoji} Time to {kind}, {mention}!"
        try:
            if meme and perms.attach_files:
                await channel.send(content, file=discord.File(meme))
            else:
                await channel.send(content)
        except discord.Forbidden:
            logging.warning("Forbidden in %s – stopping loop", channel)
            loop.stop()
            async with TASKS_LOCK:
                store.pop(uid, None)

    loop = tasks.loop(minutes=minutes)(tick)
    return loop

# ─────────── 4. Events
@bot.event
async def on_disconnect():
    await purge_all_reminders("gateway disconnect")

@bot.event
async def on_resumed():
    logging.info("Gateway resumed.")

# ─────────── 5. Slash commands
@bot.tree.command(name="help", description="Show instructions.")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Hydrate & Stretch Bot",
        colour=0x00B2FF,
        description="All reminders are per-user – only *you* are pinged.",
    )
    embed.add_field(name="/hydrate <minutes> [channel]", value="Start hydration reminders.", inline=False)
    embed.add_field(name="/stretch <minutes> [channel]", value="Start stretch reminders.", inline=False)
    embed.add_field(name="/stophydrate /stopstretch", value="Stop a reminder.", inline=False)
    embed.add_field(name="/stopreminders", value="Stop **all** your reminders.", inline=False)
    embed.set_footer(text="Slash only — no !commands here.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="hydrate", description="Start a hydration reminder.")
@app_commands.describe(
    minutes="Interval in minutes (1-1440)",
    channel="Channel to post reminders in",
)
async def hydrate(interaction: discord.Interaction, minutes: int, channel: Optional[discord.TextChannel] = None):
    if not 1 <= minutes <= 1440:
        return await interaction.response.send_message("⛔ Minutes must be 1-1440.", ephemeral=True)
    if PURGING.is_set():
        return await interaction.response.send_message("⏳ Bot is reconnecting.", ephemeral=True)

    channel = channel or interaction.channel
    if not channel.permissions_for(channel.guild.me).send_messages:
        return await interaction.response.send_message("❌ I can't send messages there.", ephemeral=True)

    async with TASKS_LOCK:
        if interaction.user.id in hydrate_tasks:
            return await interaction.response.send_message("💧 You already have a hydration reminder (use /stophydrate).", ephemeral=True)
        loop = make_reminder_loop("hydrate", minutes, channel, interaction.user.mention, hydrate_tasks, interaction.user.id)
        loop.start()
        hydrate_tasks[interaction.user.id] = (loop, channel.id)
    await interaction.response.send_message(f"💧 Hydration reminder every {minutes} min in {channel.mention}", ephemeral=True)

@bot.tree.command(name="stophydrate", description="Stop hydration reminder.")
async def stophydrate(interaction: discord.Interaction):
    if PURGING.is_set():
        return await interaction.response.send_message("⏳ Bot is reconnecting.", ephemeral=True)
    async with TASKS_LOCK:
        tup = hydrate_tasks.pop(interaction.user.id, None)
        if not tup:
            return await interaction.response.send_message("⚠️ No active hydration reminder.", ephemeral=True)
        await cancel_loop(tup[0])
    await interaction.response.send_message("🛑 Hydration reminder stopped.", ephemeral=True)

@bot.tree.command(name="stretch", description="Start a stretch reminder.")
@app_commands.describe(
    minutes="Interval in minutes (1-1440)",
    channel="Channel to post reminders in",
)
async def stretch(interaction: discord.Interaction, minutes: int, channel: Optional[discord.TextChannel] = None):
    if not 1 <= minutes <= 1440:
        return await interaction.response.send_message("⛔ Minutes must be 1-1440.", ephemeral=True)
    if PURGING.is_set():
        return await interaction.response.send_message("⏳ Bot is reconnecting.", ephemeral=True)

    channel = channel or interaction.channel
    if not channel.permissions_for(channel.guild.me).send_messages:
        return await interaction.response.send_message("❌ I can't send messages there.", ephemeral=True)

    async with TASKS_LOCK:
        if interaction.user.id in stretch_tasks:
            return await interaction.response.send_message("🤸 You already have a stretch reminder (use /stopstretch).", ephemeral=True)
        loop = make_reminder_loop("stretch", minutes, channel, interaction.user.mention, stretch_tasks, interaction.user.id)
        loop.start()
        stretch_tasks[interaction.user.id] = (loop, channel.id)
    await interaction.response.send_message(f"🤸 Stretch reminder every {minutes} min in {channel.mention}", ephemeral=True)

@bot.tree.command(name="stopstretch", description="Stop stretch reminder.")
async def stopstretch(interaction: discord.Interaction):
    if PURGING.is_set():
        return await interaction.response.send_message("⏳ Bot is reconnecting.", ephemeral=True)
    async with TASKS_LOCK:
        tup = stretch_tasks.pop(interaction.user.id, None)
        if not tup:
            return await interaction.response.send_message("⚠️ No active stretch reminder.", ephemeral=True)
        await cancel_loop(tup[0])
    await interaction.response.send_message("🛑 Stretch reminder stopped.", ephemeral=True)

@bot.tree.command(name="stopreminders", description="Stop all your reminders.")
async def stopreminders(interaction: discord.Interaction):
    if PURGING.is_set():
        return await interaction.response.send_message("⏳ Bot is reconnecting.", ephemeral=True)
    stopped = []
    async with TASKS_LOCK:
        tup = hydrate_tasks.pop(interaction.user.id, None)
        if tup:
            await cancel_loop(tup[0])
            stopped.append("💧 Hydration")
        tup = stretch_tasks.pop(interaction.user.id, None)
        if tup:
            await cancel_loop(tup[0])
            stopped.append("🤸 Stretch")

    if stopped:
        await interaction.response.send_message(f"🛑 Stopped: {', '.join(stopped)} reminders.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ You have no active reminders.", ephemeral=True)

@bot.tree.command(name="hello", description="Say hi!")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"👋 Hello, {interaction.user.mention}!", ephemeral=True)

# ─────────── 6. Run bot
if __name__ == "__main__":
    bot.run(TOKEN)

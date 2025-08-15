# bot.py – Hydrate & Stretch Bot
# Cancels **all** reminders whenever the bot disconnects from Discord.

import os
import random
import asyncio
import logging
from typing import Dict, Tuple, Optional

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────
# 0.  Logging
# ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────────────────
# 1.  Token & Intents
# ──────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Put DISCORD_TOKEN=… inside .env")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ──────────────────────────────────────────────────────────
# 2.  Helpers
# ──────────────────────────────────────────────────────────
def get_random_meme(folder: str) -> Optional[str]:
    if not os.path.isdir(folder):
        return None
    files = [f for f in os.listdir(folder)
             if os.path.isfile(os.path.join(folder, f))]
    return os.path.join(folder, random.choice(files)) if files else None

async def _cancel_loop(loop: tasks.Loop):
    """Cancel a discord.ext.tasks.Loop and wait until it is shut down."""
    loop.cancel()
    try:
        await loop._task                # type: ignore[attr-defined]
    except asyncio.CancelledError:
        pass

# ──────────────────────────────────────────────────────────
# 3.  Book-keeping  (user_id → (Loop, channel_id))
# ──────────────────────────────────────────────────────────
hydrate_tasks: Dict[int, Tuple[tasks.Loop, int]] = {}
stretch_tasks: Dict[int, Tuple[tasks.Loop, int]] = {}

async def purge_all_reminders():
    """Stop every running reminder (called on disconnect)."""
    logging.warning("Disconnect detected – purging all active reminders.")
    # Copy keys so we can modify dicts while iterating
    for uid in list(hydrate_tasks.keys()):
        loop, _ = hydrate_tasks.pop(uid)
        await _cancel_loop(loop)

    for uid in list(stretch_tasks.keys()):
        loop, _ = stretch_tasks.pop(uid)
        await _cancel_loop(loop)

# ──────────────────────────────────────────────────────────
# 4.  Events
# ──────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"{bot.user} is online ✅")

@bot.event
async def on_disconnect():
    # Cannot await inside on_disconnect → schedule the purge task
    asyncio.create_task(purge_all_reminders())

@bot.event
async def on_resumed():
    logging.info("Reconnected to Discord gateway.")

# ──────────────────────────────────────────────────────────
# 5.  Custom help
# ──────────────────────────────────────────────────────────
bot.remove_command("help")

@bot.command(name="help")
async def custom_help(ctx: commands.Context):
    embed = discord.Embed(
        title="Hydrate & Stretch Bot – commands",
        colour=0x00B2FF,
        description="All reminders are **per-user** – only *you* are pinged."
    )
    embed.add_field(
        name="!hydrate <minutes> [#channel]",
        value="Start hydration reminders. Current channel is default.",
        inline=False)
    embed.add_field(name="!stophydrate",
                    value="Stop your hydration reminder.", inline=False)
    embed.add_field(
        name="!stretch <minutes> [#channel]",
        value="Start stretch reminders.", inline=False)
    embed.add_field(name="!stopstretch",
                    value="Stop your stretch reminder.", inline=False)
    embed.add_field(
        name="!stop / !stopall / !stopreminders",
        value="Stop **all** of your reminders.", inline=False)
    await ctx.send(embed=embed)

# ──────────────────────────────────────────────────────────
# 6.  Error handler
# ──────────────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❓ Unknown command. Type `!help`.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing `{error.param.name}` argument. See `!help`.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ *minutes* must be a number; channel must be valid.")
    else:
        raise error

# ──────────────────────────────────────────────────────────
# 7.  Core loop factory
# ──────────────────────────────────────────────────────────
def make_reminder_loop(kind: str,
                       minutes: int,
                       channel: discord.TextChannel,
                       mention: str):

    images_dir = "memes" if kind == "hydrate" else "stretch"

    @tasks.loop(minutes=minutes)
    async def _loop():
        meme = get_random_meme(images_dir)
        content = f"{'💧' if kind == 'hydrate' else '🤸'} Time to {kind}, {mention}!"
        if meme:
            await channel.send(content, file=discord.File(meme))
        else:
            await channel.send(content)

    return _loop

# ──────────────────────────────────────────────────────────
# 8.  Hydration commands
# ──────────────────────────────────────────────────────────
@bot.command()
async def hydrate(ctx: commands.Context,
                  minutes: int,
                  channel: Optional[discord.TextChannel] = None):
    if minutes <= 0:
        return await ctx.send("⛔ Interval must be > 0 minutes.")

    hydrate_tasks.pop(ctx.author.id, None)

    existing = hydrate_tasks.get(ctx.author.id)
    if existing and existing[0].is_running():
        return await ctx.send("💧 You already have a hydration reminder. "
                              "Use `!stophydrate` first.")

    channel = channel or ctx.channel
    loop = make_reminder_loop("hydrate", minutes, channel, ctx.author.mention)
    loop.start()

    hydrate_tasks[ctx.author.id] = (loop, channel.id)
    await ctx.send(f"💧 Hydration reminder every {minutes} min in {channel.mention}")

@bot.command()
async def stophydrate(ctx: commands.Context):
    tup = hydrate_tasks.get(ctx.author.id)
    if tup and tup[0].is_running():
        await _cancel_loop(tup[0])
        hydrate_tasks.pop(ctx.author.id, None)
        await ctx.send("🛑 Hydration reminder stopped.")
    else:
        await ctx.send("⚠️ No active hydration reminder.")

# ──────────────────────────────────────────────────────────
# 9.  Stretch commands
# ──────────────────────────────────────────────────────────
@bot.command()
async def stretch(ctx: commands.Context,
                  minutes: int,
                  channel: Optional[discord.TextChannel] = None):
    if minutes <= 0:
        return await ctx.send("⛔ Interval must be > 0 minutes.")

    stretch_tasks.pop(ctx.author.id, None)

    existing = stretch_tasks.get(ctx.author.id)
    if existing and existing[0].is_running():
        return await ctx.send("🤸 You already have a stretch reminder. "
                              "Use `!stopstretch` first.")

    channel = channel or ctx.channel
    loop = make_reminder_loop("stretch", minutes, channel, ctx.author.mention)
    loop.start()

    stretch_tasks[ctx.author.id] = (loop, channel.id)
    await ctx.send(f"🤸 Stretch reminder every {minutes} min in {channel.mention}")

@bot.command()
async def stopstretch(ctx: commands.Context):
    tup = stretch_tasks.get(ctx.author.id)
    if tup and tup[0].is_running():
        await _cancel_loop(tup[0])
        stretch_tasks.pop(ctx.author.id, None)
        await ctx.send("🛑 Stretch reminder stopped.")
    else:
        await ctx.send("⚠️ No active stretch reminder.")

# ──────────────────────────────────────────────────────────
# 10.  Stop ALL reminders
# ──────────────────────────────────────────────────────────
@bot.command(aliases=["stop", "stopall"])
async def stopreminders(ctx: commands.Context):
    stopped = []

    tup = hydrate_tasks.get(ctx.author.id)
    if tup and tup[0].is_running():
        await _cancel_loop(tup[0])
        hydrate_tasks.pop(ctx.author.id, None)
        stopped.append("hydration")

    tup = stretch_tasks.get(ctx.author.id)
    if tup and tup[0].is_running():
        await _cancel_loop(tup[0])
        stretch_tasks.pop(ctx.author.id, None)
        stopped.append("stretch")

    if stopped:
        await ctx.send(f"🛑 Stopped {' & '.join(stopped)} reminder(s).")
    else:
        await ctx.send("⚠️ You have no active reminders.")

# ──────────────────────────────────────────────────────────
# 11.  Run the bot
# ──────────────────────────────────────────────────────────
bot.run(TOKEN)

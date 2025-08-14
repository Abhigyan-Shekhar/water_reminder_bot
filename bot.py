# bot.py  – Hydrate & Stretch Bot (channel-aware, bug-fixed)

import os
import random
import asyncio
import logging
from typing import Dict, Tuple, Optional

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────
# 0.  Logging (helps when you debug on Replit / Render)
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
intents.message_content = True          # also toggle in Dev-Portal
bot = commands.Bot(command_prefix="!", intents=intents)

# ──────────────────────────────────────────────────────────
# 2.  Remove default help → custom single-embed help
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
        value="Start hydration reminders. If no channel is given, "
              "the current channel is used.",
        inline=False)
    embed.add_field(
        name="!stophydrate",
        value="Stop your hydration reminder.", inline=False)
    embed.add_field(
        name="!stretch <minutes> [#channel]",
        value="Start stretch reminders.", inline=False)
    embed.add_field(
        name="!stopstretch",
        value="Stop your stretch reminder.", inline=False)
    embed.add_field(
        name="!stop / !stopall / !stopreminders",
        value="Stop **all** of your reminders.", inline=False)
    embed.add_field(
        name="Examples",
        value="`!hydrate 30 #wellness`\n`!stretch 15`\n`!stop`",
        inline=False)
    await ctx.send(embed=embed)

# ──────────────────────────────────────────────────────────
# 3.  Friendly error messages
# ──────────────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❓ Unknown command. Type `!help`.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing `{error.param.name}` argument. "
                       "See `!help` for usage.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ *minutes* must be a number; "
                       "channel must be a valid text channel.")
    else:
        # Re-raise so the full traceback shows in console/logs
        raise error

# ──────────────────────────────────────────────────────────
# 4.  Helper – choose a random meme image
# ──────────────────────────────────────────────────────────
def get_random_meme(folder: str) -> Optional[str]:
    """Return a random file path from *folder*, or None if empty/missing."""
    if not os.path.isdir(folder):
        return None
    files = [f for f in os.listdir(folder)
             if os.path.isfile(os.path.join(folder, f))]
    return os.path.join(folder, random.choice(files)) if files else None

# ──────────────────────────────────────────────────────────
# 5.  Book-keeping (user_id → (Loop, channel_id))
# ──────────────────────────────────────────────────────────
hydrate_tasks: Dict[int, Tuple[tasks.Loop, int]] = {}
stretch_tasks: Dict[int, Tuple[tasks.Loop, int]] = {}

async def _cancel_loop(loop: tasks.Loop):
    """Instantly cancel a discord.ext.tasks.Loop and wait for it to stop."""
    loop.cancel()                       # ← interrupts even during sleep
    try:
        await loop._task                # type: ignore[attr-defined]
    except asyncio.CancelledError:
        pass

# ──────────────────────────────────────────────────────────
# 6.  on_ready
# ──────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"{bot.user} is online ✅")

# ──────────────────────────────────────────────────────────
# 7.  Hydration commands
# ──────────────────────────────────────────────────────────
@bot.command()
async def hydrate(ctx: commands.Context,
                  minutes: int,
                  channel: Optional[discord.TextChannel] = None):
    if minutes <= 0:
        return await ctx.send("⛔ Interval must be > 0 minutes.")

    # Remove stale entry (e.g. after a restart)
    hydrate_tasks.pop(ctx.author.id, None)

    existing = hydrate_tasks.get(ctx.author.id)
    if existing and existing[0].is_running():
        return await ctx.send("💧 You already have a hydration reminder. "
                              "Use `!stophydrate` first.")

    channel = channel or ctx.channel

    @tasks.loop(minutes=minutes)
    async def hydration_loop():
        meme = get_random_meme("memes")
        if meme:
            await channel.send(f"💧 Time to hydrate, {ctx.author.mention}!",
                               file=discord.File(meme))
        else:
            await channel.send(f"💧 Time to hydrate, {ctx.author.mention}!")

    hydration_loop.start()
    hydrate_tasks[ctx.author.id] = (hydration_loop, channel.id)
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
# 8.  Stretch commands
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

    @tasks.loop(minutes=minutes)
    async def stretch_loop():
        meme = get_random_meme("stretch")
        if meme:
            await channel.send(f"🤸 Time to stretch, {ctx.author.mention}!",
                               file=discord.File(meme))
        else:
            await channel.send(f"🤸 Time to stretch, {ctx.author.mention}!")

    stretch_loop.start()
    stretch_tasks[ctx.author.id] = (stretch_loop, channel.id)
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
# 9.  Stop ALL reminders
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
# 10.  Run the bot
# ──────────────────────────────────────────────────────────
bot.run(TOKEN)
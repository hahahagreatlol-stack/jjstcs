"""
My Discord Bot (Turkish version)
================================
Moderation with logs, games, points and a role market, giveaways, welcome and
goodbye messages, suggestions, AFK and more - all with slash commands.
Everything people see in Discord is in Turkish; the code stays in English.

Before running:
  1. pip install discord.py
  2. Developer Portal -> your app -> Bot tab -> turn ON "Server Members Intent"
  3. Paste your bot token into token.txt (next to this file) - never share it!
  4. Run:  python bot.py
  5. Type /yardım in your server to see every command
"""

import asyncio
import json
import math
import os
import platform
import random
import re
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Literal, Optional


def wait_before_closing():
    """On Windows, a double-clicked bot.py closes its window the moment it stops.
    This keeps the window open so you can read why it stopped."""
    if os.name == "nt" and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to exit...")
        except EOFError:
            pass


try:
    import aiohttp  # comes with discord.py; used to look up Roblox profiles
    import discord
    from discord import app_commands
    from discord.ext import tasks
except ImportError:
    print("discord.py isn't installed yet. Run this command, then start the bot again:\n"
          "    py -m pip install discord.py      (on a Mac: pip3 install discord.py)")
    wait_before_closing()
    sys.exit(1)


# ================================================================
# SETTINGS - change these however you like
# ================================================================

RPS_WIN_POINTS = 5    # points for beating the bot at rock-paper-scissors
TRIVIA_POINTS = 10    # points for a correct trivia answer
DAILY_POINTS = 25     # points from /günlük, once every 24 hours
BOT_VERSION = "13"    # shown when the bot starts and in /ping, so you can tell copies apart

BASE_DIR = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.txt"      # your bot token goes in here
DATA_FILE = BASE_DIR / "bot_data.json"   # points, warnings and settings are saved here
TOKEN_PLACEHOLDER = "PASTE_YOUR_TOKEN_HERE"


def load_token():
    """Reads the token from a DISCORD_TOKEN environment variable, or from token.txt."""
    token = os.getenv("DISCORD_TOKEN", "")
    # "token.txt.txt" happens on Windows when file extensions are hidden
    for path in (TOKEN_FILE, BASE_DIR / "token.txt.txt"):
        if not token and path.exists():
            token = path.read_text(encoding="utf-8-sig")
    return token.strip().strip('"').strip("'").strip()


# ================================================================
# SAVED DATA - kept in bot_data.json so it survives restarts
# ================================================================

DATA_KEYS = (
    "points", "warnings", "daily", "shop", "afk", "giveaways",
    "welcome_channels", "goodbye_channels", "greeting_settings", "greeting_texts",
    "log_channels", "auto_roles", "suggestion_channels", "roblox_boards",
    "challenge_settings", "challenges",
)


def load_data():
    saved = {}
    if DATA_FILE.exists():
        saved = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    for key in DATA_KEYS:
        saved.setdefault(key, {})
    return saved


data = load_data()


def save_data():
    # Write to a temporary file first, then swap it in. If the bot crashes
    # halfway through saving, the old bot_data.json is still in one piece.
    temp_file = DATA_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp_file.replace(DATA_FILE)


def guild_data(key: str, guild_id) -> dict:
    """One server's part of the saved data, e.g. guild_data("points", guild.id)."""
    return data[key].setdefault(str(guild_id), {})


def get_setting(key: str, guild_id):
    """A single per-server setting, like the log channel's ID. None if it isn't set."""
    return data[key].get(str(guild_id))


def set_setting(key: str, guild_id, value):
    """Saves a per-server setting. Saving None removes it."""
    if value is None:
        data[key].pop(str(guild_id), None)
    else:
        data[key][str(guild_id)] = value
    save_data()


def get_points(guild_id, user_id) -> int:
    return guild_data("points", guild_id).get(str(user_id), 0)


def add_points(guild_id, user_id, amount: int) -> int:
    """Gives points (or takes them, with a negative amount) and returns the new total."""
    guild_points = guild_data("points", guild_id)
    guild_points[str(user_id)] = max(0, guild_points.get(str(user_id), 0) + amount)
    save_data()
    return guild_points[str(user_id)]


# ================================================================
# BOT SETUP
# ================================================================

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # lets the bot see people join and leave
        super().__init__(
            intents=intents,
            activity=discord.Game(name="/yardım"),  # shows "Playing /yardım" under the bot's name
            # Never ping @everyone or whole roles, even if someone types them into a message
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(GiveawayView())    # keeps giveaway buttons working after a restart
        self.add_view(ChallengeView())   # keeps 1v1 channel buttons working after a restart
        giveaway_checker.start()         # ends giveaways when their time is up
        board_refresher.start()          # keeps live Roblox leaderboards up to date
        await sync_commands()            # sends the slash commands to Discord


bot = MyBot()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (bot.py version {BOT_VERSION}) - ready to go!")


# Commands are registered directly in each server the bot is in. Discord shows server
# commands right away, while commands registered for all servers at once can take a
# long time to appear after an update.
ALL_COMMANDS = []


async def sync_to_server(guild):
    for command in ALL_COMMANDS:
        bot.tree.add_command(command, guild=guild, override=True)
    synced = await bot.tree.sync(guild=guild)
    print(f"Synced {len(synced)} slash commands to {guild.name}")


async def sync_commands():
    ALL_COMMANDS[:] = bot.tree.get_commands()
    try:
        async for guild in bot.fetch_guilds():
            await sync_to_server(guild)
        # Remove the old copies registered for all servers, so nothing shows up twice
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
    except discord.HTTPException as error:
        # Keep running with the commands Discord already has, and say what went wrong
        print(f"Could not update the slash commands: {error}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    try:
        await sync_to_server(guild)  # a new server gets the commands right away too
    except discord.HTTPException as error:
        print(f"Could not add the slash commands to {guild.name}: {error}")


# ================================================================
# ERRORS & SHARED HELPERS
# ================================================================

class CantDoThat(Exception):
    """Raise this with a message to show the user a friendly error."""


@bot.tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError):
        error = error.original  # the real error hiding underneath

    if isinstance(error, discord.HTTPException) and error.code == 10062:
        print("[!] A command reached the bot too late to answer (Discord only waits 3 seconds). "
              "The host is probably too slow or overloaded.")
        return
    if isinstance(error, discord.HTTPException) and error.code == 40060:
        print("[!] Another copy of this bot already answered that command. "
              "Make sure the bot is only running in one place.")
        return

    if isinstance(error, CantDoThat):
        message = f"❌ {error}"
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Yavaş ol! {math.ceil(error.retry_after)} saniye sonra tekrar dene."
    elif isinstance(error, app_commands.TransformerError):
        message = "❌ Bu üyeyi sunucuda bulamadım."
    elif isinstance(error, app_commands.CommandNotFound):
        message = "🔄 Bu komut güncellendi. Discord'u yenile (bilgisayarda Ctrl+R) ve tekrar dene."
    elif isinstance(error, discord.Forbidden):
        message = ("❌ Bunu yapmaya yetkim yok. Rolümün izinlerini kontrol et ve rolümün, "
                   "işlem yapacağım kişilerin ve rollerin üstünde olduğundan emin ol.")
    else:
        message = "❌ Bir şeyler ters gitti. Ayrıntılar için terminale bak."
        traceback.print_exception(type(error), error, error.__traceback__)

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def timestamp(moment, style: str = "D") -> str:
    """Discord's date format - everyone sees it in their own time zone and language.
    style "D" = date, "f" = date and time, "R" = relative (like "3 gün önce")."""
    seconds = moment if isinstance(moment, (int, float)) else moment.timestamp()
    return f"<t:{int(seconds)}:{style}>"


# Roles with any of these permissions are never handed out by the bot
DANGEROUS_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_webhooks",
    "kick_members", "ban_members", "moderate_members", "manage_messages", "mention_everyone",
)


def check_role_is_safe(role: discord.Role):
    """Makes sure the bot can give out this role, and that it doesn't carry staff powers."""
    if role.is_default() or role.managed:
        raise CantDoThat("Bu rol kimseye verilemez.")
    if not role.is_assignable():
        raise CantDoThat("Bu rol benim rolümün üstünde. Sunucu Ayarları > Roller kısmından "
                         "rolümü onun üstüne sürükle.")
    if any(getattr(role.permissions, permission) for permission in DANGEROUS_PERMISSIONS):
        raise CantDoThat("Güvenlik için yönetim izni olan roller kullanılamaz.")


async def log_action(guild: discord.Guild, embed: discord.Embed):
    """Copies a moderation action into the log channel picked with /log-kanalı."""
    channel_id = get_setting("log_channels", guild.id)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return
    log_embed = embed.copy()
    log_embed.timestamp = discord.utils.utcnow()
    try:
        await channel.send(embed=log_embed)
    except discord.HTTPException:
        pass  # can't post in the log channel - don't let that break the command


async def announce(interaction: discord.Interaction, embed: discord.Embed, ephemeral: bool = False):
    """Replies with a moderation action and copies it into the log channel."""
    if interaction.response.is_done():  # the command already showed "thinking..."
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    await log_action(interaction.guild, embed)


# ================================================================
# WELCOME & GOODBYE MESSAGES, AUTO-ROLE
# ================================================================

DEFAULT_GREETINGS = {
    "welcome": "Selam {üye}, **{sunucu}** sunucusuna hoş geldin!\nSunucumuzun {sayı}. üyesisin. İyi eğlenceler!",
    "goodbye": "**{isim}** sunucudan ayrıldı. Seni özleyeceğiz! 👋",
}


def get_greeting_channel(guild: discord.Guild, joined: bool):
    """Where to send a welcome (joined=True) or goodbye (joined=False) message.

    Welcomes go to the /karşılama-kanalı channel. Goodbyes go to the /veda-kanalı
    channel, or the welcome channel if no goodbye channel was picked. If neither
    is set, both use the server's default system channel.
    """
    welcome_id = get_setting("welcome_channels", guild.id)
    goodbye_id = get_setting("goodbye_channels", guild.id)
    channel_id = welcome_id if joined else (goodbye_id or welcome_id)
    channel = guild.get_channel(channel_id) if channel_id else None
    return channel or guild.system_channel


def greeting_on(guild_id, kind: str) -> bool:
    """Whether "welcome" or "goodbye" messages are switched on (both are on by default)."""
    return guild_data("greeting_settings", guild_id).get(kind, True)


def greeting_text(guild_id, kind: str) -> str:
    """The server's own welcome/goodbye text from /karşılama-mesajı, or the default one."""
    return guild_data("greeting_texts", guild_id).get(kind) or DEFAULT_GREETINGS[kind]


def fill_placeholders(text: str, member: discord.Member) -> str:
    return (text.replace("{üye}", member.mention)
                .replace("{isim}", member.display_name)
                .replace("{sunucu}", member.guild.name)
                .replace("{sayı}", str(member.guild.member_count)))


async def send_greeting(member: discord.Member, joined: bool):
    channel = get_greeting_channel(member.guild, joined)
    if channel is None:
        return
    kind = "welcome" if joined else "goodbye"
    embed = discord.Embed(
        title="👋 Hoş geldin!" if joined else "Güle güle!",
        description=fill_placeholders(greeting_text(member.guild.id, kind), member),
        color=discord.Color.green() if joined else discord.Color.red(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    # Ping new members so they notice the welcome (pings inside embeds don't notify)
    await channel.send(content=member.mention if joined else None, embed=embed)


async def give_auto_role(member: discord.Member):
    role_id = get_setting("auto_roles", member.guild.id)
    role = member.guild.get_role(role_id) if role_id else None
    if role is None or member.bot or role in member.roles:
        return
    try:
        await member.add_roles(role, reason="Otomatik rol")
    except discord.HTTPException:
        pass  # missing Manage Roles, or the role was moved above mine


@bot.event
async def on_member_join(member: discord.Member):
    if not member.pending:  # people still accepting the server rules get the role when they finish
        await give_auto_role(member)
    if greeting_on(member.guild.id, "welcome"):
        await send_greeting(member, joined=True)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.pending and not after.pending:  # they just accepted the server rules
        await give_auto_role(after)


@bot.event
async def on_member_remove(member: discord.Member):
    if greeting_on(member.guild.id, "goodbye"):
        await send_greeting(member, joined=False)


@bot.tree.command(name="karşılama-kanalı", description="Karşılama mesajlarının gideceği kanalı seç")
@app_commands.rename(channel="kanal")
@app_commands.describe(channel="Karşılama mesajlarının gönderileceği kanal")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def setwelcome(interaction: discord.Interaction, channel: discord.TextChannel):
    set_setting("welcome_channels", interaction.guild_id, channel.id)
    await interaction.response.send_message(
        f"✅ Karşılama mesajları artık {channel.mention} kanalına gönderilecek.", ephemeral=True)


@bot.tree.command(name="veda-kanalı", description="Veda mesajlarının gideceği kanalı seç")
@app_commands.rename(channel="kanal")
@app_commands.describe(channel="Veda mesajlarının gönderileceği kanal")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def setgoodbye(interaction: discord.Interaction, channel: discord.TextChannel):
    set_setting("goodbye_channels", interaction.guild_id, channel.id)
    await interaction.response.send_message(
        f"✅ Veda mesajları artık {channel.mention} kanalına gönderilecek.", ephemeral=True)


class GreetingTextForm(discord.ui.Modal, title="Karşılama ve veda mesajları"):
    welcome_text = discord.ui.TextInput(label="Karşılama mesajı", style=discord.TextStyle.paragraph,
                                        max_length=1000, required=False)
    goodbye_text = discord.ui.TextInput(label="Veda mesajı", style=discord.TextStyle.paragraph,
                                        max_length=1000, required=False)

    def __init__(self, guild_id):
        super().__init__()
        # Start with the current messages filled in, so they're easy to tweak
        self.welcome_text.default = greeting_text(guild_id, "welcome")
        self.goodbye_text.default = greeting_text(guild_id, "goodbye")

    async def on_submit(self, interaction: discord.Interaction):
        texts = guild_data("greeting_texts", interaction.guild_id)
        texts["welcome"] = self.welcome_text.value.strip()  # empty = use the default message
        texts["goodbye"] = self.goodbye_text.value.strip()
        save_data()
        await interaction.response.send_message(
            "✅ Mesajlar kaydedildi! Nasıl göründüklerine /karşılama-test ile bakabilirsin. "
            "Bir kutuyu boş bırakırsan varsayılan mesaj kullanılır.", ephemeral=True)


@bot.tree.command(name="karşılama-mesajı",
                  description="Karşılama ve veda mesajlarını düzenle: {üye} {isim} {sunucu} {sayı} kullanabilirsin")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def edit_greetings(interaction: discord.Interaction):
    await interaction.response.send_modal(GreetingTextForm(interaction.guild_id))  # opens a pop-up form


GREETING_MODES = {
    # choice shown in Discord: (welcome on?, goodbye on?)
    "İkisi de açık": (True, True),
    "İkisi de kapalı": (False, False),
    "Sadece karşılama": (True, False),
    "Sadece veda": (False, True),
}


@bot.tree.command(name="karşılama-aç-kapat", description="Karşılama ve veda mesajlarını aç veya kapat")
@app_commands.rename(mode="durum")
@app_commands.describe(mode="Hangi mesajlar gönderilsin?")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def toggle_greetings(interaction: discord.Interaction,
                           mode: Literal["İkisi de açık", "İkisi de kapalı", "Sadece karşılama", "Sadece veda"]):
    welcome_on, goodbye_on = GREETING_MODES[mode]
    data["greeting_settings"][str(interaction.guild_id)] = {"welcome": welcome_on, "goodbye": goodbye_on}
    save_data()
    await interaction.response.send_message(
        f"✅ Karşılama mesajları: **{'açık' if welcome_on else 'kapalı'}** • "
        f"Veda mesajları: **{'açık' if goodbye_on else 'kapalı'}**", ephemeral=True)


@bot.tree.command(name="karşılama-test", description="Karşılama ve veda mesajlarını önizle")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def testwelcome(interaction: discord.Interaction):
    welcome_channel = get_greeting_channel(interaction.guild, joined=True)
    goodbye_channel = get_greeting_channel(interaction.guild, joined=False)
    if welcome_channel is None and goodbye_channel is None:
        raise CantDoThat("Henüz kanal seçilmedi. /karşılama-kanalı ve /veda-kanalı ile kanal seç.")
    welcome_text = welcome_channel.mention if welcome_channel else "kanal yok"
    goodbye_text = goodbye_channel.mention if goodbye_channel else "kanal yok"
    await interaction.response.send_message(
        f"Test mesajları gönderiliyor... Karşılama: {welcome_text} • Veda: {goodbye_text}", ephemeral=True)
    await send_greeting(interaction.user, joined=True)
    await send_greeting(interaction.user, joined=False)


@bot.tree.command(name="otomatik-rol", description="Yeni üyelere otomatik verilecek rolü seç (boş bırakırsan kapanır)")
@app_commands.rename(role="rol")
@app_commands.describe(role="Verilecek rol (kapatmak için boş bırak)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def auto_role(interaction: discord.Interaction, role: Optional[discord.Role] = None):
    if role is None:
        set_setting("auto_roles", interaction.guild_id, None)
        await interaction.response.send_message("✅ Otomatik rol kapatıldı.", ephemeral=True)
        return
    check_role_is_safe(role)
    set_setting("auto_roles", interaction.guild_id, role.id)
    await interaction.response.send_message(f"✅ Yeni üyelere artık {role.mention} rolü verilecek.", ephemeral=True)


# ================================================================
# MODERATION & LOGS
# ================================================================

NO_REASON = "Sebep belirtilmedi"


def check_can_moderate(interaction: discord.Interaction, member: discord.Member, bot_acts: bool = True):
    """Stops mods from using the bot on themselves, the owner, or people ranked above them."""
    guild = interaction.guild
    if member.id == interaction.user.id:
        raise CantDoThat("Bunu kendine kullanamazsın.")
    if member.id == guild.owner_id:
        raise CantDoThat("Bunu sunucu sahibine kullanamazsın.")
    if interaction.user.id != guild.owner_id and member.top_role >= interaction.user.top_role:
        raise CantDoThat("Bu kişinin en yüksek rolü seninkiyle aynı ya da daha yukarıda.")
    if bot_acts and member.top_role >= guild.me.top_role:
        raise CantDoThat("Rolümün bu kişinin rolünden yukarıda olması gerekiyor. "
                         "Sunucu Ayarları > Roller kısmından rolümü yukarı sürükle.")


def text_channel_only(interaction: discord.Interaction) -> discord.TextChannel:
    if not isinstance(interaction.channel, discord.TextChannel):
        raise CantDoThat("Bu komut sadece yazı kanallarında çalışır.")
    return interaction.channel


def mod_embed(action: str, member, moderator: discord.Member, reason: Optional[str] = None):
    embed = discord.Embed(title=action, color=discord.Color.orange())
    embed.add_field(name="Üye", value=f"{member.mention} ({member})")
    embed.add_field(name="Moderatör", value=moderator.mention)
    if reason:
        embed.add_field(name="Sebep", value=reason, inline=False)
    return embed


def channel_embed(action: str, channel, moderator: discord.Member, detail: Optional[str] = None):
    embed = discord.Embed(title=action, color=discord.Color.orange())
    embed.add_field(name="Kanal", value=channel.mention)
    embed.add_field(name="Moderatör", value=moderator.mention)
    if detail:
        embed.add_field(name="Ayrıntı", value=detail, inline=False)
    return embed


@bot.tree.command(name="log-kanalı",
                  description="Moderasyon kayıtlarının gideceği kanalı seç (boş bırakırsan kapanır)")
@app_commands.rename(channel="kanal")
@app_commands.describe(channel="Kayıt kanalı - sadece yetkililerin görebildiği bir kanal seç")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def set_log_channel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    set_setting("log_channels", interaction.guild_id, channel.id if channel else None)
    if channel:
        text = f"✅ Moderasyon kayıtları artık {channel.mention} kanalına gönderilecek."
    else:
        text = "✅ Moderasyon kayıtları kapatıldı."
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="at", description="Bir üyeyi sunucudan at")
@app_commands.rename(member="üye", reason="sebep")
@app_commands.describe(member="Atılacak üye", reason="Neden atılıyor?")
@app_commands.default_permissions(kick_members=True)
@app_commands.guild_only()
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = NO_REASON):
    check_can_moderate(interaction, member)
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await member.kick(reason=reason)
    await announce(interaction, mod_embed("👢 Üye atıldı", member, interaction.user, reason))


@bot.tree.command(name="yasakla", description="Bir üyeyi sunucudan yasakla")
@app_commands.rename(member="üye", reason="sebep")
@app_commands.describe(member="Yasaklanacak üye", reason="Neden yasaklanıyor?")
@app_commands.default_permissions(ban_members=True)
@app_commands.guild_only()
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = NO_REASON):
    check_can_moderate(interaction, member)
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await member.ban(reason=reason)
    await announce(interaction, mod_embed("🔨 Üye yasaklandı", member, interaction.user, reason))


@bot.tree.command(name="yasak-kaldır", description="Kullanıcı ID'si ile bir yasağı kaldır")
@app_commands.rename(user_id="kullanıcı-id")
@app_commands.describe(user_id="Yasaklı kullanıcının ID'si")
@app_commands.default_permissions(ban_members=True)
@app_commands.guild_only()
async def unban(interaction: discord.Interaction, user_id: str):
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
    except (ValueError, discord.NotFound):
        raise CantDoThat("Bu ID'ye sahip yasaklı bir kullanıcı bulamadım.")
    await announce(interaction, mod_embed("✅ Yasak kaldırıldı", user, interaction.user))


@bot.tree.command(name="sustur", description="Bir üyeyi bir süreliğine sustur (zaman aşımı)")
@app_commands.rename(member="üye", minutes="dakika", reason="sebep")
@app_commands.describe(member="Susturulacak üye", minutes="Kaç dakika (en fazla 40320 = 28 gün)",
                       reason="Neden susturuluyor?")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def timeout(interaction: discord.Interaction, member: discord.Member,
                  minutes: app_commands.Range[int, 1, 40320], reason: str = NO_REASON):
    check_can_moderate(interaction, member)
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await announce(interaction, mod_embed(f"🔇 {minutes} dakika susturuldu", member, interaction.user, reason))


@bot.tree.command(name="susturma-kaldır", description="Bir üyenin susturmasını (zaman aşımını) erken kaldır")
@app_commands.rename(member="üye", reason="sebep")
@app_commands.describe(member="Susturması kaldırılacak üye", reason="Neden kaldırılıyor?")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str = NO_REASON):
    if not member.is_timed_out():
        raise CantDoThat("Bu üye şu an susturulmuş değil.")
    check_can_moderate(interaction, member)
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await member.timeout(None, reason=reason)
    await announce(interaction, mod_embed("🔊 Susturma kaldırıldı", member, interaction.user, reason))


@bot.tree.command(name="temizle", description="Bu kanaldaki son mesajları sil")
@app_commands.rename(amount="miktar")
@app_commands.describe(amount="Kaç mesaj silinsin (1-100)")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)  # deleting can take a few seconds
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 {len(deleted)} mesaj silindi.", ephemeral=True)
    await log_action(interaction.guild, channel_embed("🧹 Mesajlar silindi", interaction.channel,
                                                      interaction.user, f"{len(deleted)} mesaj"))


@bot.tree.command(name="uyar", description="Bir üyeyi uyar (siciline kaydedilir)")
@app_commands.rename(member="üye", reason="sebep")
@app_commands.describe(member="Uyarılacak üye", reason="Neden uyarılıyor?")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    check_can_moderate(interaction, member, bot_acts=False)
    record = guild_data("warnings", interaction.guild_id).setdefault(str(member.id), [])
    record.append({
        "reason": reason,
        "by": str(interaction.user),
        "date": discord.utils.utcnow().strftime("%d.%m.%Y"),
    })
    save_data()
    await announce(interaction, mod_embed(f"⚠️ Uyarı #{len(record)}", member, interaction.user, reason))
    try:
        await member.send(f"⚠️ **{interaction.guild.name}** sunucusunda uyarı aldın: {reason}")
    except discord.HTTPException:
        pass  # their DMs are closed - that's okay


@bot.tree.command(name="uyarılar", description="Bir üyenin uyarılarını gör")
@app_commands.rename(member="üye")
@app_commands.describe(member="Uyarıları gösterilecek üye")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def warnings_command(interaction: discord.Interaction, member: discord.Member):
    record = guild_data("warnings", interaction.guild_id).get(str(member.id), [])
    embed = discord.Embed(title=f"⚠️ Uyarılar: {member.display_name}", color=discord.Color.orange())
    if not record:
        embed.description = "Hiç uyarısı yok. 😇"
    first_number = max(1, len(record) - 9)  # only the 10 most recent fit
    for number, warning in enumerate(record[-10:], start=first_number):
        embed.add_field(name=f"#{number} • {warning['date']}",
                        value=f"{warning['reason']}\n*Uyaran: {warning['by']}*", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="uyarıları-sil", description="Bir üyenin tüm uyarılarını sil")
@app_commands.rename(member="üye")
@app_commands.describe(member="Uyarıları silinecek üye")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    guild_data("warnings", interaction.guild_id).pop(str(member.id), None)
    save_data()
    await announce(interaction, mod_embed("🗑️ Tüm uyarılar silindi", member, interaction.user), ephemeral=True)


@bot.tree.command(name="yavaş-mod", description="Bu kanala yavaş mod ekle (0 = kapat)")
@app_commands.rename(seconds="saniye")
@app_commands.describe(seconds="Her üyenin iki mesajı arasında kaç saniye beklemesi gereksin (0-21600)")
@app_commands.default_permissions(manage_channels=True)
@app_commands.guild_only()
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
    channel = text_channel_only(interaction)
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await channel.edit(slowmode_delay=seconds, reason=f"{interaction.user} tarafından")
    detail = f"{seconds} saniye" if seconds else "Kapatıldı"
    await announce(interaction, channel_embed("🐢 Yavaş mod", channel, interaction.user, detail))


@bot.tree.command(name="kilitle", description="Bu kanalı kilitle, üyeler mesaj yazamasın")
@app_commands.rename(reason="sebep")
@app_commands.describe(reason="Neden kilitleniyor?")
@app_commands.default_permissions(manage_channels=True)
@app_commands.guild_only()
async def lock(interaction: discord.Interaction, reason: str = NO_REASON):
    channel = text_channel_only(interaction)
    everyone = interaction.guild.default_role
    overwrite = channel.overwrites_for(everyone)
    overwrite.send_messages = False
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await channel.set_permissions(everyone, overwrite=overwrite, reason=reason)
    await announce(interaction, channel_embed("🔒 Kanal kilitlendi", channel, interaction.user, reason))


@bot.tree.command(name="kilidi-aç", description="Kilitli kanalın kilidini aç")
@app_commands.default_permissions(manage_channels=True)
@app_commands.guild_only()
async def unlock(interaction: discord.Interaction):
    channel = text_channel_only(interaction)
    everyone = interaction.guild.default_role
    overwrite = channel.overwrites_for(everyone)
    overwrite.send_messages = None  # back to the channel's normal setting
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await channel.set_permissions(everyone, overwrite=None if overwrite.is_empty() else overwrite,
                                  reason=f"{interaction.user} tarafından")
    await announce(interaction, channel_embed("🔓 Kanalın kilidi açıldı", channel, interaction.user))


# ================================================================
# FUN & GAMES
# ================================================================

EIGHT_BALL_ANSWERS = [
    "Kesinlikle öyle. ✅", "Hiç şüphesiz.", "Evet, kesinlikle!", "Buna güvenebilirsin.",
    "Büyük ihtimalle.", "Sonra tekrar sor. 🤔", "Şimdi söylemesem daha iyi.", "Şu an tahmin edemiyorum.",
    "Pek sanmıyorum.", "Kaynaklarım hayır diyor. ❌", "Çok şüpheli.", "Kesinlikle hayır. 😂",
]


@bot.tree.command(name="sihirli-top", description="Sihirli 8 topuna evet/hayır sorusu sor")
@app_commands.rename(question="soru")
@app_commands.describe(question="Sormak istediğin evet/hayır sorusu")
async def eight_ball(interaction: discord.Interaction, question: app_commands.Range[str, 1, 200]):
    embed = discord.Embed(title="🎱 Sihirli 8 Topu", color=discord.Color.dark_purple())
    embed.add_field(name="Soru", value=question, inline=False)
    embed.add_field(name="Sihirli topun cevabı", value=random.choice(EIGHT_BALL_ANSWERS), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="yazı-tura", description="Yazı tura at")
async def coinflip(interaction: discord.Interaction):
    await interaction.response.send_message(f"🪙 **{random.choice(['Yazı', 'Tura'])}** geldi!")


@bot.tree.command(name="zar", description="Zar at")
@app_commands.rename(sides="yüz-sayısı")
@app_commands.describe(sides="Zarın kaç yüzü olsun (varsayılan 6)")
async def roll(interaction: discord.Interaction, sides: app_commands.Range[int, 2, 1000] = 6):
    await interaction.response.send_message(f"🎲 Zar **{random.randint(1, sides)}** geldi! (1-{sides})")


class GameView(discord.ui.View):
    """Game buttons that only the person who started the game can press."""

    def __init__(self, player: discord.Member):
        super().__init__(timeout=30)  # seconds before the game expires
        self.player = player
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Bu senin oyunun değil! Kendi oyununu başlat. 🙂",
                                                    ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏰ Süre doldu!", view=None)
            except discord.HTTPException:
                pass


RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
RPS_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}


class RPSView(GameView):
    async def play(self, interaction: discord.Interaction, choice: str):
        bot_choice = random.choice(list(RPS_BEATS))
        if choice == bot_choice:
            result, color = "Berabere! 🤝", discord.Color.light_grey()
        elif RPS_BEATS[choice] == bot_choice:
            total = add_points(interaction.guild_id, self.player.id, RPS_WIN_POINTS)
            result, color = f"Kazandın! 🎉 +{RPS_WIN_POINTS} puan (toplam: {total})", discord.Color.green()
        else:
            result, color = "Ben kazandım! 😎 Bir dahaki sefere bol şans.", discord.Color.red()

        embed = discord.Embed(
            title="Taş, Kağıt, Makas",
            description=f"Sen: {RPS_EMOJI[choice]}  🆚  Ben: {RPS_EMOJI[bot_choice]}\n\n**{result}**",
            color=color,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label="🪨 Taş", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "rock")

    @discord.ui.button(label="📄 Kağıt", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "paper")

    @discord.ui.button(label="✂️ Makas", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.play(interaction, "scissors")


@bot.tree.command(name="taş-kağıt-makas", description="Benimle taş-kağıt-makas oyna ve puan kazan")
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 10)  # once every 10 seconds per person
async def rps(interaction: discord.Interaction):
    view = RPSView(interaction.user)
    embed = discord.Embed(title="Taş, Kağıt, Makas", description="Hamleni seç! 👇",
                          color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()


TRIVIA_QUESTIONS = [
    # (question, correct answer, [wrong answers]) - add your own!
    # --- Türkiye & tarih ---
    ("Türkiye'nin başkenti neresidir?", "Ankara", ["İstanbul", "İzmir", "Bursa"]),
    ("Türkiye Cumhuriyeti hangi yıl ilan edildi?", "1923", ["1919", "1920", "1938"]),
    ("Türkiye'nin en yüksek dağı hangisidir?", "Ağrı Dağı", ["Erciyes Dağı", "Uludağ", "Kaçkar Dağı"]),
    ("Türkiye'nin en kalabalık şehri hangisidir?", "İstanbul", ["Ankara", "İzmir", "Bursa"]),
    ("Türkiye'nin en büyük gölü hangisidir?", "Van Gölü", ["Tuz Gölü", "Beyşehir Gölü", "Eğirdir Gölü"]),
    ("İstanbul'u fetheden Osmanlı padişahı kimdir?", "Fatih Sultan Mehmet",
     ["Kanuni Sultan Süleyman", "Yavuz Sultan Selim", "Osman Gazi"]),
    ("İstanbul hangi yıl fethedildi?", "1453", ["1071", "1299", "1517"]),
    ("Malazgirt Meydan Muharebesi hangi yıl yapıldı?", "1071", ["1176", "1299", "1453"]),
    ("Osmanlı Devleti'nin kurucusu kimdir?", "Osman Gazi", ["Orhan Gazi", "Ertuğrul Gazi", "I. Murad"]),
    ("TBMM hangi yıl açıldı?", "1920", ["1919", "1923", "1924"]),
    ("Türkiye kaç coğrafi bölgeye ayrılır?", "7", ["5", "6", "8"]),
    ("Kapadokya hangi coğrafi bölgededir?", "İç Anadolu", ["Ege", "Karadeniz", "Doğu Anadolu"]),
    ("Pamukkale travertenleri hangi ildedir?", "Denizli", ["Aydın", "Muğla", "Antalya"]),
    ("Tamamı Türkiye sınırları içinde kalan en uzun nehir hangisidir?", "Kızılırmak",
     ["Sakarya", "Yeşilırmak", "Büyük Menderes"]),
    ("Mustafa Kemal Atatürk hangi şehirde doğdu?", "Selanik", ["İstanbul", "Manastır", "Ankara"]),
    ("Çanakkale Deniz Zaferi hangi yıl kazanıldı?", "1915", ["1912", "1919", "1922"]),
    ("Türk bayrağındaki ay ve yıldız ne renktir?", "Beyaz", ["Sarı", "Kırmızı", "Mavi"]),
    ("İstiklal Marşı'nın şairi kimdir?", "Mehmet Akif Ersoy",
     ["Nazım Hikmet", "Yahya Kemal Beyatlı", "Ziya Gökalp"]),
    ("Plaka kodu 06 olan il hangisidir?", "Ankara", ["İstanbul", "İzmir", "Adana"]),
    ("İstanbul'un plaka kodu kaçtır?", "34", ["06", "35", "16"]),
    ("Truva antik kenti hangi ildedir?", "Çanakkale", ["İzmir", "Balıkesir", "Aydın"]),
    ("Efes antik kenti hangi ildedir?", "İzmir", ["Aydın", "Muğla", "Denizli"]),
    ("Sümela Manastırı hangi ildedir?", "Trabzon", ["Rize", "Artvin", "Giresun"]),
    ("Nemrut Dağı'ndaki dev heykeller hangi ildedir?", "Adıyaman", ["Malatya", "Şanlıurfa", "Diyarbakır"]),
    ("Göbeklitepe hangi ildedir?", "Şanlıurfa", ["Mardin", "Adıyaman", "Diyarbakır"]),
    ("Mevlana Müzesi hangi ildedir?", "Konya", ["Bursa", "Kayseri", "Karaman"]),
    ("Kanuni Sultan Süleyman kaçıncı Osmanlı padişahıdır?", "10", ["8", "9", "12"]),
    ("Mimar Sinan'ın 'ustalık eserim' dediği cami hangisidir?", "Selimiye Camii",
     ["Süleymaniye Camii", "Şehzade Camii", "Sultanahmet Camii"]),
    ("Lale Devri hangi devletin tarihinde yaşanmıştır?", "Osmanlı Devleti",
     ["Selçuklu Devleti", "Bizans İmparatorluğu", "Safevi Devleti"]),
    ("Türkiye'yi çevreleyen denizlerden en tuzlusu hangisidir?", "Akdeniz",
     ["Karadeniz", "Marmara Denizi", "Ege Denizi"]),
    ("Üç tarafı denizlerle çevrili kara parçasına ne denir?", "Yarımada", ["Ada", "Körfez", "Burun"]),
    ("Mantısıyla en ünlü şehir hangisidir?", "Kayseri", ["Konya", "Sivas", "Bursa"]),
    ("İskender kebap hangi şehirle özdeşleşmiştir?", "Bursa", ["Adana", "Konya", "Kayseri"]),
    ("Pişmaniyesiyle ünlü il hangisidir?", "Kocaeli", ["Bolu", "Sakarya", "Düzce"]),
    ("Karagöz ile Hacivat hangi geleneksel sanatın karakterleridir?", "Gölge oyunu",
     ["Opera", "Bale", "Heykel"]),
    ("Uzaya giden ilk Türk astronot kimdir?", "Alper Gezeravcı",
     ["Tuva Cihangir Atasever", "Aziz Sancar", "Cahit Arf"]),
    ("Nobel Kimya Ödülü'nü kazanan Türk bilim insanı kimdir?", "Aziz Sancar",
     ["Gazi Yaşargil", "Cahit Arf", "Oktay Sinanoğlu"]),
    ("Nobel Edebiyat Ödülü'nü kazanan Türk yazar kimdir?", "Orhan Pamuk",
     ["Yaşar Kemal", "Elif Şafak", "Nazım Hikmet"]),
    # --- Dünya coğrafyası ---
    ("Japonya'nın başkenti neresidir?", "Tokyo", ["Kyoto", "Osaka", "Seul"]),
    ("Avustralya'nın başkenti neresidir?", "Kanberra", ["Sidney", "Melbourne", "Perth"]),
    ("Kanada'nın başkenti neresidir?", "Ottava", ["Toronto", "Vancouver", "Montreal"]),
    ("Brezilya'nın başkenti neresidir?", "Brasilia", ["Rio de Janeiro", "São Paulo", "Salvador"]),
    ("İtalya'nın başkenti neresidir?", "Roma", ["Milano", "Venedik", "Napoli"]),
    ("Almanya'nın başkenti neresidir?", "Berlin", ["Münih", "Hamburg", "Frankfurt"]),
    ("Mısır'ın başkenti neresidir?", "Kahire", ["İskenderiye", "Luksor", "Gize"]),
    ("Yüzölçümü en büyük ülke hangisidir?", "Rusya", ["Kanada", "Çin", "ABD"]),
    ("Nüfusu en kalabalık ülke hangisidir?", "Hindistan", ["Çin", "ABD", "Endonezya"]),
    ("Yüzölçümü en büyük kıta hangisidir?", "Asya", ["Afrika", "Avrupa", "Kuzey Amerika"]),
    ("Dünyanın en büyük okyanusu hangisidir?", "Pasifik", ["Atlas", "Hint", "Arktik"]),
    ("Dünyanın en büyük sıcak çölü hangisidir?", "Sahra", ["Gobi", "Kalahari", "Atacama"]),
    ("Deniz seviyesine göre en yüksek dağ hangisidir?", "Everest", ["K2", "Kilimanjaro", "Ağrı Dağı"]),
    ("Eyfel Kulesi hangi şehirdedir?", "Paris", ["Londra", "Roma", "Berlin"]),
    ("Big Ben saat kulesi hangi şehirdedir?", "Londra", ["Paris", "Dublin", "Edinburgh"]),
    ("Akdeniz'i Atlas Okyanusu'na bağlayan boğaz hangisidir?", "Cebelitarık Boğazı",
     ["İstanbul Boğazı", "Çanakkale Boğazı", "Hürmüz Boğazı"]),
    ("İstanbul Boğazı hangi iki denizi birbirine bağlar?", "Karadeniz ve Marmara",
     ["Ege ve Marmara", "Akdeniz ve Ege", "Karadeniz ve Ege"]),
    ("Dünyanın en derin noktasının bulunduğu çukur hangisidir?", "Mariana Çukuru",
     ["Porto Riko Çukuru", "Java Çukuru", "Tonga Çukuru"]),
    ("'Güneşin doğduğu ülke' olarak bilinen ülke hangisidir?", "Japonya",
     ["Çin", "Güney Kore", "Tayland"]),
    ("Amazon Ormanları'nın büyük kısmı hangi ülkededir?", "Brezilya", ["Peru", "Kolombiya", "Arjantin"]),
    ("Dünyanın en yüksek şelalesi hangisidir?", "Angel Şelalesi",
     ["Niagara Şelalesi", "Victoria Şelalesi", "İguazu Şelalesi"]),
    ("Niagara Şelalesi hangi iki ülkenin sınırındadır?", "ABD ve Kanada",
     ["ABD ve Meksika", "Kanada ve Grönland", "Brezilya ve Arjantin"]),
    ("Tac Mahal hangi ülkededir?", "Hindistan", ["Pakistan", "İran", "Bangladeş"]),
    ("Machu Picchu hangi ülkededir?", "Peru", ["Meksika", "Şili", "Bolivya"]),
    ("Gize piramitleri hangi ülkededir?", "Mısır", ["Meksika", "Sudan", "Irak"]),
    ("Venedik hangi ülkededir?", "İtalya", ["Fransa", "Hırvatistan", "İspanya"]),
    ("Dünyanın en küçük ülkesi hangisidir?", "Vatikan", ["Monako", "San Marino", "Lihtenştayn"]),
    ("Lalesi ve yel değirmenleriyle ünlü ülke hangisidir?", "Hollanda", ["Belçika", "Danimarka", "İsviçre"]),
    ("Özgürlük Heykeli'ni ABD'ye hangi ülke hediye etti?", "Fransa", ["İngiltere", "İspanya", "İtalya"]),
    # --- Bilim & doğa ---
    ("Güneş Sistemi'nin en büyük gezegeni hangisidir?", "Jüpiter", ["Satürn", "Neptün", "Dünya"]),
    ("Hangi gezegen 'Kızıl Gezegen' olarak bilinir?", "Mars", ["Venüs", "Merkür", "Jüpiter"]),
    ("Güneş'e en yakın gezegen hangisidir?", "Merkür", ["Venüs", "Mars", "Dünya"]),
    ("Halkalarıyla en çok bilinen gezegen hangisidir?", "Satürn", ["Jüpiter", "Uranüs", "Mars"]),
    ("Halk arasında 'Çoban Yıldızı' denen gök cismi hangisidir?", "Venüs", ["Mars", "Jüpiter", "Merkür"]),
    ("Dünya'nın doğal uydusu hangisidir?", "Ay", ["Güneş", "Mars", "Titan"]),
    ("İnsanlar Ay'a ilk kez hangi yıl ayak bastı?", "1969", ["1959", "1965", "1972"]),
    ("Işık saniyede yaklaşık kaç kilometre yol alır?", "300.000", ["30.000", "150.000", "3.000.000"]),
    ("Suyun kimyasal formülü nedir?", "H2O", ["CO2", "O2", "H2O2"]),
    ("Su, deniz seviyesinde kaç °C'de kaynar?", "100", ["80", "90", "120"]),
    ("Bitkiler besin üretmek için havadan hangi gazı alır?", "Karbondioksit", ["Oksijen", "Azot", "Helyum"]),
    ("Havada en çok bulunan gaz hangisidir?", "Azot", ["Oksijen", "Karbondioksit", "Hidrojen"]),
    ("Periyodik tabloda 'O' sembolü hangi elementtir?", "Oksijen", ["Osmiyum", "Altın", "Ozon"]),
    ("Altının kimyasal sembolü nedir?", "Au", ["Ag", "Al", "Gd"]),
    ("Doğadaki en sert madde hangisidir?", "Elmas", ["Altın", "Demir", "Kuvars"]),
    ("Elektrik akımının birimi nedir?", "Amper", ["Volt", "Watt", "Ohm"]),
    ("Düşen bir elmadan esinlenerek yer çekimini açıklayan bilim insanı kimdir?", "Isaac Newton",
     ["Albert Einstein", "Galileo Galilei", "Nikola Tesla"]),
    ("Görelilik kuramını kim geliştirdi?", "Albert Einstein",
     ["Isaac Newton", "Stephen Hawking", "Marie Curie"]),
    ("Gökkuşağında kaç renk vardır?", "7", ["5", "6", "8"]),
    ("İnsan vücudunun en büyük organı hangisidir?", "Deri", ["Karaciğer", "Akciğer", "Beyin"]),
    ("Yetişkin bir insanın iskeletinde kaç kemik vardır?", "206", ["186", "212", "300"]),
    ("Yetişkin bir insanın, yirmilik dişler dahil, kaç dişi vardır?", "32", ["28", "30", "36"]),
    ("Kanı vücuda pompalayan organ hangisidir?", "Kalp", ["Akciğer", "Böbrek", "Karaciğer"]),
    ("Gözün renkli kısmına ne ad verilir?", "İris", ["Retina", "Kornea", "Göz bebeği"]),
    ("Karadaki en hızlı hayvan hangisidir?", "Çita", ["Aslan", "At", "Tazı"]),
    ("Dünyanın en büyük hayvanı hangisidir?", "Mavi balina", ["Fil", "Balina köpekbalığı", "Zürafa"]),
    ("En uzun boylu kara hayvanı hangisidir?", "Zürafa", ["Fil", "Deve", "At"]),
    ("Aşağıdakilerden hangisi memeli değildir?", "Penguen", ["Yunus", "Yarasa", "Balina"]),
    ("Örümceklerin kaç bacağı vardır?", "8", ["6", "10", "12"]),
    ("Bir ahtapotun kaç kolu vardır?", "8", ["6", "10", "12"]),
    ("Pandaların ana besini nedir?", "Bambu", ["Balık", "Bal", "Okaliptüs"]),
    ("Kutup ayısının derisi ne renktir?", "Siyah", ["Beyaz", "Pembe", "Gri"]),
    ("Yarasaların çoğu karanlıkta yönünü nasıl bulur?", "Ses yankısıyla",
     ["Koku alarak", "Isıyı görerek", "Manyetik alanla"]),
    ("'Çölün gemisi' olarak bilinen hayvan hangisidir?", "Deve", ["At", "Fil", "Eşek"]),
    # --- Matematik & zaman ---
    ("En küçük asal sayı hangisidir?", "2", ["1", "3", "0"]),
    ("Bir altıgenin kaç kenarı vardır?", "6", ["5", "7", "8"]),
    ("Bir üçgenin iç açılarının toplamı kaç derecedir?", "180", ["90", "270", "360"]),
    ("12 x 12 kaçtır?", "144", ["124", "132", "156"]),
    ("Bir günde kaç saniye vardır?", "86.400", ["3.600", "24.000", "60.000"]),
    ("Bir yılda kaç ay 31 gün çeker?", "7", ["5", "6", "8"]),
    ("Yılın en kısa ayı hangisidir?", "Şubat", ["Nisan", "Haziran", "Kasım"]),
    # --- Spor ---
    ("Bir futbol takımı sahaya kaç oyuncuyla çıkar?", "11", ["9", "10", "12"]),
    ("Basketbolda bir takım sahada kaç oyuncuyla oynar?", "5", ["4", "6", "7"]),
    ("Voleybolda bir takım sahada kaç oyuncuyla oynar?", "6", ["5", "7", "8"]),
    ("Normal süresinde bir futbol maçı kaç dakika sürer?", "90", ["60", "80", "100"]),
    ("Türkiye, 2002 Dünya Kupası'nı kaçıncı sırada bitirdi?", "Üçüncü",
     ["İkinci", "Dördüncü", "Çeyrek finalde elendi"]),
    ("Olimpiyat bayrağında kaç halka vardır?", "5", ["4", "6", "7"]),
    ("Yaz Olimpiyatları kaç yılda bir düzenlenir?", "4", ["2", "3", "5"]),
    ("Maraton koşusu yaklaşık kaç kilometredir?", "42", ["21", "35", "50"]),
    ("Satrançta mat edilen taş hangisidir?", "Şah", ["Vezir", "Kale", "At"]),
    ("Satranç tahtasında kaç kare vardır?", "64", ["36", "49", "100"]),
    ("Klasik bir futbol topu hangi şekillerden oluşur?", "Beşgen ve altıgen",
     ["Kare ve altıgen", "Üçgen ve kare", "Sadece altıgen"]),
    # --- Oyunlar & teknoloji ---
    ("Minecraft'ta Nether portalı yapmak için hangi blok gerekir?", "Obsidyen",
     ["Ana kaya", "Netherrack", "Kırıktaş"]),
    ("Minecraft'ta oyuncuya yaklaşınca patlayan yaratık hangisidir?", "Creeper",
     ["Zombi", "İskelet", "Enderman"]),
    ("Minecraft'ta elmas kazmak için en az hangi kazma gerekir?", "Demir kazma",
     ["Taş kazma", "Altın kazma", "Tahta kazma"]),
    ("Roblox'un sanal para birimi nedir?", "Robux", ["V-Bucks", "Coin", "Gem"]),
    ("Super Mario'nun kardeşinin adı nedir?", "Luigi", ["Wario", "Toad", "Yoshi"]),
    ("Pokémon serisinde Ash'in en bilinen Pokémon'u hangisidir?", "Pikachu",
     ["Charmander", "Bulbasaur", "Eevee"]),
    ("Bilgisayarın 'beyni' olarak bilinen parça hangisidir?", "İşlemci (CPU)",
     ["RAM", "Ekran kartı", "Sabit disk"]),
    ("YouTube hangi şirkete aittir?", "Google", ["Microsoft", "Meta", "Apple"]),
    ("Klavyede 'kopyala' kısayolu hangisidir?", "Ctrl + C", ["Ctrl + V", "Ctrl + X", "Ctrl + Z"]),
    ("Discord'da bir role verilebilecek en güçlü izin hangisidir?", "Yönetici",
     ["Sunucuyu Yönet", "Rolleri Yönet", "Üyeleri Yasakla"]),
    ("Bu bot hangi programlama diliyle yazıldı?", "Python", ["JavaScript", "Lua", "C++"]),
    # --- Genel kültür ---
    ("Mona Lisa tablosunu kim yaptı?", "Leonardo da Vinci", ["Michelangelo", "Picasso", "Van Gogh"]),
    ("Romeo ve Juliet'i kim yazdı?", "William Shakespeare", ["Charles Dickens", "Victor Hugo", "Goethe"]),
    ("Hangi müzik aletinde genellikle 88 tuş bulunur?", "Piyano", ["Akordeon", "Org", "Gitar"]),
    ("Pizza hangi ülkenin mutfağından çıkmıştır?", "İtalya", ["Fransa", "ABD", "Yunanistan"]),
    ("Suşi hangi ülkenin mutfağına aittir?", "Japonya", ["Çin", "Kore", "Tayland"]),
    ("Guacamole'nin ana malzemesi nedir?", "Avokado", ["Domates", "Misket limonu", "Bezelye"]),
    ("Harry Potter'ın okuduğu büyücülük okulunun adı nedir?", "Hogwarts",
     ["Durmstrang", "Beauxbatons", "Ilvermorny"]),
    ("Örümcek Adam'ın gerçek adı nedir?", "Peter Parker", ["Bruce Wayne", "Clark Kent", "Tony Stark"]),
]


class TriviaView(GameView):
    def __init__(self, player: discord.Member, correct: str, options: list):
        super().__init__(player)
        self.correct = correct
        for option in options:
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary)
            button.callback = self.make_callback(option)
            self.add_item(button)

    def make_callback(self, picked: str):
        async def callback(interaction: discord.Interaction):
            # Turn the right answer green and a wrong pick red
            for button in self.children:
                button.disabled = True
                if button.label == self.correct:
                    button.style = discord.ButtonStyle.success
                elif button.label == picked:
                    button.style = discord.ButtonStyle.danger
                else:
                    button.style = discord.ButtonStyle.secondary

            if picked == self.correct:
                total = add_points(interaction.guild_id, self.player.id, TRIVIA_POINTS)
                result = f"✅ Doğru! +{TRIVIA_POINTS} puan (toplam: {total})"
            else:
                result = f"❌ Yanlış! Doğru cevap: **{self.correct}**"
            await interaction.response.edit_message(content=result, view=self)
            self.stop()
        return callback


@bot.tree.command(name="bilgi-yarışması", description="Bir bilgi sorusunu cevapla ve puan kazan")
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 15)  # once every 15 seconds per person
async def trivia(interaction: discord.Interaction):
    question, correct, wrong = random.choice(TRIVIA_QUESTIONS)
    options = [correct] + wrong
    random.shuffle(options)
    view = TriviaView(interaction.user, correct, options)
    embed = discord.Embed(title="🧠 Bilgi yarışması!", description=question, color=discord.Color.blurple())
    embed.set_footer(text=f"{TRIVIA_POINTS} puan değerinde • Cevaplamak için 30 saniyen var")
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()


class DuelGameView(discord.ui.View):
    """Both players secretly pick rock, paper or scissors."""

    def __init__(self, challenger: discord.Member, opponent: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.players = {challenger.id: challenger, opponent.id: opponent}
        self.picks = {}
        self.bet = bet
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in self.players:
            await interaction.response.send_message("Bu düello senin değil! 🙂", ephemeral=True)
            return False
        if interaction.user.id in self.picks:
            await interaction.response.send_message("Seçimini zaten yaptın, rakibini bekle.", ephemeral=True)
            return False
        return True

    async def pick(self, interaction: discord.Interaction, choice: str):
        self.picks[interaction.user.id] = choice
        if len(self.picks) < 2:
            await interaction.response.send_message(
                f"Seçimin kaydedildi: {RPS_EMOJI[choice]} Rakibini bekliyoruz...", ephemeral=True)
            return

        self.stop()
        (id_a, pick_a), (id_b, pick_b) = self.picks.items()
        player_a, player_b = self.players[id_a], self.players[id_b]
        if pick_a == pick_b:
            result = "Berabere! 🤝 Kimse puan kaybetmedi." if self.bet else "Berabere! 🤝"
        else:
            winner, loser = (player_a, player_b) if RPS_BEATS[pick_a] == pick_b else (player_b, player_a)
            result = f"🏆 Kazanan: {winner.mention}!"
            if self.bet:
                amount = min(self.bet, get_points(interaction.guild_id, loser.id))
                add_points(interaction.guild_id, loser.id, -amount)
                add_points(interaction.guild_id, winner.id, amount)
                result += f" **{loser.display_name}** adlı üyeden **{amount} puan** kazandı."

        embed = discord.Embed(
            title="⚔️ Düello sonucu",
            description=(f"{player_a.display_name}: {RPS_EMOJI[pick_a]}\n"
                         f"{player_b.display_name}: {RPS_EMOJI[pick_b]}\n\n{result}"),
            color=discord.Color.gold(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="🪨 Taş", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.pick(interaction, "rock")

    @discord.ui.button(label="📄 Kağıt", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.pick(interaction, "paper")

    @discord.ui.button(label="✂️ Makas", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.pick(interaction, "scissors")

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏰ Süre doldu, düello iptal edildi.", embed=None, view=None)
            except discord.HTTPException:
                pass


class DuelInviteView(discord.ui.View):
    """The challenged member accepts or declines."""

    def __init__(self, challenger: discord.Member, opponent: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent
        self.bet = bet
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Bu davet sana değil! 🙂", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Kabul et", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        for player in (self.challenger, self.opponent):
            if get_points(interaction.guild_id, player.id) < self.bet:
                await interaction.response.edit_message(
                    content=f"❌ **{player.display_name}** adlı üyenin artık yeterli puanı yok, düello iptal edildi.",
                    embed=None, view=None)
                return
        game = DuelGameView(self.challenger, self.opponent, self.bet)
        embed = discord.Embed(
            title="⚔️ Düello başladı!",
            description=(f"{self.challenger.mention} 🆚 {self.opponent.mention}\n\n"
                         "İkiniz de aşağıdan gizlice seçiminizi yapın! 60 saniyeniz var."),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=game)
        game.message = interaction.message

    @discord.ui.button(label="❌ Reddet", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content=f"🏳️ **{self.opponent.display_name}** düelloyu reddetti.", embed=None, view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏰ Davet kabul edilmedi, düello iptal edildi.",
                                        embed=None, view=None)
            except discord.HTTPException:
                pass


@bot.tree.command(name="düello", description="Bir üyeyi taş-kağıt-makas düellosuna davet et")
@app_commands.rename(opponent="rakip", bet="bahis")
@app_commands.describe(opponent="Kime meydan okuyorsun?", bet="Ortaya kaç puan konsun? (0 = puansız)")
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 15)  # once every 15 seconds per person
async def duel(interaction: discord.Interaction, opponent: discord.Member,
               bet: app_commands.Range[int, 0, 10000] = 0):
    if opponent.id == interaction.user.id:
        raise CantDoThat("Kendinle düello yapamazsın.")
    if opponent.bot:
        raise CantDoThat("Botlarla düello yapılmaz. Benimle oynamak için /taş-kağıt-makas kullan.")
    for player in (interaction.user, opponent):
        if get_points(interaction.guild_id, player.id) < bet:
            raise CantDoThat(f"**{player.display_name}** adlı üyenin {bet} puanı yok.")

    view = DuelInviteView(interaction.user, opponent, bet)
    bet_text = f"Bahis: **{bet} puan**" if bet else "Bahis yok, sadece onur için! 😄"
    embed = discord.Embed(
        title="⚔️ Düello daveti",
        description=(f"{interaction.user.mention}, {opponent.mention} adlı üyeyi "
                     f"taş-kağıt-makas düellosuna davet ediyor!\n{bet_text}"),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Kabul etmek için 60 saniyen var.")
    await interaction.response.send_message(content=opponent.mention, embed=embed, view=view)
    view.message = await interaction.original_response()


# ================================================================
# IN-GAME 1v1 CHALLENGES - each challenge gets its own private channel
# ================================================================

def challenge_staff_roles(guild: discord.Guild) -> list:
    """The referee, evaluator and jr. evaluator roles picked with /1v1-kurulum."""
    settings = get_setting("challenge_settings", guild.id) or {}
    roles = [guild.get_role(settings.get(key) or 0) for key in ("referee", "evaluator", "jr_evaluator")]
    return [role for role in roles if role]


def is_challenge_staff(member: discord.Member) -> bool:
    return member.guild_permissions.manage_guild or any(
        role in member.roles for role in challenge_staff_roles(member.guild))


def open_challenge_channel(guild: discord.Guild, user_id: int):
    """The 1v1 channel this player is already in, if any. Forgets channels that were deleted by hand."""
    for channel_id, challenge in list(data["challenges"].items()):
        if challenge["guild_id"] != guild.id or user_id not in (challenge["challenger"], challenge["opponent"]):
            continue
        channel = guild.get_channel(int(channel_id))
        if channel:
            return channel
        del data["challenges"][channel_id]
        save_data()
    return None


async def close_challenge(channel: discord.TextChannel, text: str):
    """Says how the 1v1 ended, then deletes its channel after 10 seconds."""
    data["challenges"].pop(str(channel.id), None)
    save_data()
    try:
        await channel.send(f"{text}\nBu kanal 10 saniye içinde silinecek.")
        await asyncio.sleep(10)
        await channel.delete(reason="1v1 bitti")
    except discord.HTTPException:
        pass  # the channel is already gone


async def post_challenge_result(guild: discord.Guild, winner_id: int, loser_id: int,
                                referee: discord.Member, challenge: dict):
    """Shares the result in the results channel picked with /1v1-kurulum (if there is one)."""
    settings = get_setting("challenge_settings", guild.id) or {}
    channel = guild.get_channel(settings.get("results") or 0)
    if channel is None:
        return
    embed = discord.Embed(title="⚔️ 1v1 Sonucu", color=discord.Color.gold())
    embed.add_field(name="🏆 Kazanan", value=f"<@{winner_id}>")
    embed.add_field(name="Kaybeden", value=f"<@{loser_id}>")
    embed.add_field(name="Hakem", value=referee.mention)
    if challenge.get("note"):
        embed.add_field(name="Not", value=challenge["note"], inline=False)
    embed.timestamp = discord.utils.utcnow()
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


class ResultView(discord.ui.View):
    """The winner picker a referee or evaluator sees after pressing 🏁 Maçı bitir."""

    def __init__(self, guild: discord.Guild, challenge: dict):
        super().__init__(timeout=120)
        self.challenge = challenge
        for user_id in (challenge["challenger"], challenge["opponent"]):
            member = guild.get_member(user_id)
            name = member.display_name if member else str(user_id)
            button = discord.ui.Button(label=f"🏆 {name[:60]} kazandı", style=discord.ButtonStyle.success)
            button.callback = self.make_callback(user_id)
            self.add_item(button)
        no_result = discord.ui.Button(label="🔒 Sonuçsuz kapat", style=discord.ButtonStyle.secondary)
        no_result.callback = self.make_callback(None)
        self.add_item(no_result)

    def make_callback(self, winner_id):
        async def callback(interaction: discord.Interaction):
            self.stop()
            if str(interaction.channel_id) not in data["challenges"]:
                await interaction.response.edit_message(content="Bu 1v1 zaten kapatılmış.", view=None)
                return
            await interaction.response.edit_message(content="✅ Kaydedildi.", view=None)
            challenger, opponent = self.challenge["challenger"], self.challenge["opponent"]
            if winner_id is None:
                text = f"🔒 Maç sonuçsuz kapatıldı. ({interaction.user.mention})"
            else:
                loser_id = opponent if winner_id == challenger else challenger
                text = f"🏆 <@{winner_id}>, <@{loser_id}> karşısında kazandı! (Hakem: {interaction.user.mention})"
                await post_challenge_result(interaction.guild, winner_id, loser_id, interaction.user, self.challenge)
            await close_challenge(interaction.channel, text)
        return callback


class ChallengeView(discord.ui.View):
    """The buttons inside a 1v1 channel. Fixed custom_ids keep them working after the bot restarts."""

    def __init__(self, accepted: bool = False):
        super().__init__(timeout=None)
        if accepted:  # once the challenge is accepted, only the finish button is left
            self.remove_item(self.accept)
            self.remove_item(self.decline)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.channel_id) not in data["challenges"]:
            await interaction.response.send_message("Bu 1v1 artık geçerli değil.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Kabul et", style=discord.ButtonStyle.success, custom_id="1v1:accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        challenge = data["challenges"][str(interaction.channel_id)]
        if interaction.user.id != challenge["opponent"]:
            await interaction.response.send_message("Sadece meydan okunan oyuncu kabul edebilir.", ephemeral=True)
            return
        challenge["status"] = "accepted"
        save_data()
        await interaction.response.edit_message(view=ChallengeView(accepted=True))
        await interaction.channel.send(f"✅ <@{challenge['opponent']}> meydan okumayı kabul etti! "
                                       "Hakemler ve değerlendiriciler maçı ayarlayabilir. 🎮")

    @discord.ui.button(label="❌ Reddet / İptal", style=discord.ButtonStyle.danger, custom_id="1v1:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        challenge = data["challenges"][str(interaction.channel_id)]
        if interaction.user.id not in (challenge["challenger"], challenge["opponent"]):
            await interaction.response.send_message("Sadece oyuncular reddedebilir ya da iptal edebilir.",
                                                    ephemeral=True)
            return
        if challenge["status"] != "pending":
            await interaction.response.send_message("Maç kabul edildi. Artık sadece hakemler kapatabilir.",
                                                    ephemeral=True)
            return
        action = "reddetti" if interaction.user.id == challenge["opponent"] else "iptal etti"
        await interaction.response.edit_message(view=None)
        await close_challenge(interaction.channel, f"❌ {interaction.user.mention} meydan okumayı {action}.")

    @discord.ui.button(label="🏁 Maçı bitir", style=discord.ButtonStyle.secondary, custom_id="1v1:finish")
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_challenge_staff(interaction.user):
            await interaction.response.send_message("Maçı sadece hakemler ve değerlendiriciler bitirebilir.",
                                                    ephemeral=True)
            return
        challenge = data["challenges"][str(interaction.channel_id)]
        await interaction.response.send_message("Kim kazandı?", view=ResultView(interaction.guild, challenge),
                                                ephemeral=True)


@bot.event
async def on_guild_channel_delete(channel):
    # If someone deletes a 1v1 channel by hand, forget that challenge
    if data["challenges"].pop(str(channel.id), None) is not None:
        save_data()


@bot.tree.command(name="1v1-kurulum", description="1v1 sistemini kur: hakem ve değerlendirici rolleri, özel kategori")
@app_commands.rename(referee="hakem-rolü", evaluator="değerlendirici-rolü", jr_evaluator="jr-değerlendirici-rolü",
                     category="kategori", results_channel="sonuç-kanalı")
@app_commands.describe(referee="Hakem rolü", evaluator="Değerlendirici rolü",
                       jr_evaluator="Jr. değerlendirici rolü (isteğe bağlı)",
                       category="1v1 kanallarının açılacağı kategori (boş bırakırsan ben oluştururum)",
                       results_channel="Maç sonuçlarının paylaşılacağı kanal (isteğe bağlı)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def challenge_setup(interaction: discord.Interaction, referee: discord.Role, evaluator: discord.Role,
                          jr_evaluator: Optional[discord.Role] = None,
                          category: Optional[discord.CategoryChannel] = None,
                          results_channel: Optional[discord.TextChannel] = None):
    await interaction.response.defer(ephemeral=True)  # making a category takes a moment
    guild = interaction.guild
    staff_roles = [role for role in (referee, evaluator, jr_evaluator) if role]
    old_settings = get_setting("challenge_settings", guild.id) or {}
    if category is None:
        category = guild.get_channel(old_settings.get("category") or 0)  # reuse the one made last time
    if not isinstance(category, discord.CategoryChannel):
        # A new category that only the bot and the staff roles can see
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                      guild.me: discord.PermissionOverwrite(view_channel=True)}
        for role in staff_roles:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True)
        category = await guild.create_category("⚔️ 1v1 Maçları", overwrites=overwrites, reason="1v1 kurulumu")

    set_setting("challenge_settings", guild.id, {
        "referee": referee.id,
        "evaluator": evaluator.id,
        "jr_evaluator": jr_evaluator.id if jr_evaluator else None,
        "category": category.id,
        "results": results_channel.id if results_channel else None,
    })
    roles_text = ", ".join(role.mention for role in staff_roles)
    await interaction.followup.send(
        f"✅ 1v1 sistemi kuruldu!\n"
        f"• Her 1v1 için **{category.name}** kategorisinde özel bir kanal açılacak. "
        f"O kanalı sadece iki oyuncu ve {roles_text} görebilecek.\n"
        f"• Sonuç kanalı: {results_channel.mention if results_channel else 'yok'}\n\n"
        "Oyuncular artık /1v1 ile meydan okuyabilir.", ephemeral=True)


CHALLENGE_WAIT = 120   # seconds a player waits between challenges
last_challenge = {}    # player id -> when their last challenge went through


@bot.tree.command(name="1v1", description="Bir oyuncuya oyun içi 1v1 meydan okuması gönder")
@app_commands.rename(opponent="rakip", note="not")
@app_commands.describe(opponent="Kime meydan okuyorsun?", note="İsteğe bağlı not, örneğin harita ya da kurallar")
@app_commands.guild_only()
async def challenge(interaction: discord.Interaction, opponent: discord.Member,
                    note: Optional[app_commands.Range[str, 1, 300]] = None):
    guild = interaction.guild
    settings = get_setting("challenge_settings", guild.id)
    staff_roles = challenge_staff_roles(guild)
    if not settings or not staff_roles:
        raise CantDoThat("1v1 sistemi henüz kurulmamış. Yetkililer /1v1-kurulum ile kurabilir.")
    if opponent.id == interaction.user.id:
        raise CantDoThat("Kendine meydan okuyamazsın.")
    if opponent.bot:
        raise CantDoThat("Botlara meydan okuyamazsın.")
    for player in (interaction.user, opponent):
        open_channel = open_challenge_channel(guild, player.id)
        if open_channel:
            raise CantDoThat(f"**{player.display_name}** adlı üyenin zaten açık bir 1v1'i var: {open_channel.mention}")
    # Only challenges that actually go through start the wait
    wait = last_challenge.get(interaction.user.id, 0) + CHALLENGE_WAIT - time.time()
    if wait > 0:
        raise CantDoThat(f"Yeni bir meydan okuma için {math.ceil(wait)} saniye bekle.")

    await interaction.response.defer(ephemeral=True)  # making a channel takes a moment
    category = guild.get_channel(settings.get("category") or 0)
    can_talk = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),  # hidden from everyone else
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              read_message_history=True, embed_links=True),
        interaction.user: can_talk,
        opponent: can_talk,
    }
    for role in staff_roles:
        overwrites[role] = can_talk
    try:
        channel = await guild.create_text_channel(
            name=f"1v1-{interaction.user.name}-vs-{opponent.name}"[:100],
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            topic=f"⚔️ {interaction.user} vs {opponent}",
            reason="1v1 meydan okuması",
        )
    except discord.HTTPException:
        raise CantDoThat("1v1 kanalını açamadım. Kanalları Yönet iznim olmayabilir ya da kategori dolu olabilir "
                         "(bir kategoride en fazla 50 kanal olur).")

    data["challenges"][str(channel.id)] = {
        "guild_id": guild.id,
        "challenger": interaction.user.id,
        "opponent": opponent.id,
        "status": "pending",
        "note": note or "",
        "created": int(time.time()),
    }
    save_data()
    last_challenge[interaction.user.id] = time.time()

    embed = discord.Embed(
        title="⚔️ 1v1 Meydan Okuması",
        description=(f"{interaction.user.mention} 🆚 {opponent.mention}\n\n"
                     f"{opponent.mention}, meydan okumayı kabul ediyor musun?"),
        color=discord.Color.orange(),
    )
    if note:
        embed.add_field(name="Not", value=note, inline=False)
    embed.add_field(name="Yetkililer", value=" ".join(role.mention for role in staff_roles), inline=False)
    embed.set_footer(text="Maç bitince bir hakem ya da değerlendirici 🏁 Maçı bitir butonuna basar.")
    pings = " ".join([interaction.user.mention, opponent.mention] + [role.mention for role in staff_roles])
    await channel.send(content=pings, embed=embed, view=ChallengeView(),
                       allowed_mentions=discord.AllowedMentions(users=True, roles=True))
    await interaction.followup.send(f"✅ Meydan okuman gönderildi: {channel.mention}", ephemeral=True)


# ================================================================
# POINTS, DAILY REWARD & ROLE MARKET
# ================================================================

@bot.tree.command(name="puan", description="Birinin kaç puanı olduğuna bak")
@app_commands.rename(member="üye")
@app_commands.describe(member="Puanına bakılacak üye (kendin için boş bırak)")
@app_commands.guild_only()
async def points_command(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    guild_points = guild_data("points", interaction.guild_id)
    total = guild_points.get(str(member.id), 0)
    rank_text = ""
    if total > 0:
        rank = sorted(guild_points.values(), reverse=True).index(total) + 1
        rank_text = f" (Puan sıralaması: #{rank})"
    await interaction.response.send_message(
        f"⭐ **{member.display_name}** adlı üyenin **{total}** puanı var.{rank_text}")


@bot.tree.command(name="puan-sıralaması", description="Sunucuda en çok puanı olanları gör")
@app_commands.guild_only()
async def points_leaderboard(interaction: discord.Interaction):
    guild_points = guild_data("points", interaction.guild_id)
    top_ten = sorted(guild_points.items(), key=lambda item: item[1], reverse=True)[:10]

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for rank, (user_id, score) in enumerate(top_ten, start=1):
        badge = medals.get(rank, f"**{rank}.**")
        lines.append(f"{badge} <@{user_id}> — **{score}** puan")

    embed = discord.Embed(
        title=f"🏆 {interaction.guild.name} Puan Sıralaması",
        description="\n".join(lines) or ("Henüz kimsenin puanı yok! Listeye girmek için "
                                         "/günlük, /taş-kağıt-makas veya /bilgi-yarışması kullan."),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="günlük", description=f"Günlük ödülünü al (+{DAILY_POINTS} puan)")
@app_commands.guild_only()
async def daily(interaction: discord.Interaction):
    claims = guild_data("daily", interaction.guild_id)
    next_claim = claims.get(str(interaction.user.id), 0) + 24 * 60 * 60
    if time.time() < next_claim:
        raise CantDoThat(f"Günlük ödülünü zaten aldın. Tekrar alabileceğin zaman: {timestamp(next_claim, 'R')}")
    claims[str(interaction.user.id)] = time.time()
    total = add_points(interaction.guild_id, interaction.user.id, DAILY_POINTS)  # this also saves
    await interaction.response.send_message(
        f"🎁 Günlük ödülün: **+{DAILY_POINTS} puan**! Toplam puanın: **{total}**")


def shop_items(guild: discord.Guild):
    """The roles for sale in this server as (role, price) pairs, cheapest first."""
    items = []
    for role_id, price in guild_data("shop", guild.id).items():
        role = guild.get_role(int(role_id))
        if role:
            items.append((role, price))
    return sorted(items, key=lambda item: item[1])


@bot.tree.command(name="market", description="Puanlarınla alabileceğin rolleri gör")
@app_commands.guild_only()
async def shop(interaction: discord.Interaction):
    lines = [f"{role.mention} — **{price}** puan" for role, price in shop_items(interaction.guild)]
    embed = discord.Embed(
        title="🛒 Market",
        description="\n".join(lines) or "Markette henüz bir şey yok. Yetkililer /market-ekle ile rol ekleyebilir.",
        color=discord.Color.green(),
    )
    embed.set_footer(text=f"Senin puanın: {get_points(interaction.guild_id, interaction.user.id)} "
                          f"• Satın almak için /satın-al")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="market-ekle", description="Markete puanla satın alınabilecek bir rol ekle")
@app_commands.rename(role="rol", price="fiyat")
@app_commands.describe(role="Satılacak rol", price="Kaç puan?")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def shop_add(interaction: discord.Interaction, role: discord.Role,
                   price: app_commands.Range[int, 1, 1000000]):
    check_role_is_safe(role)
    guild_data("shop", interaction.guild_id)[str(role.id)] = price
    save_data()
    await interaction.response.send_message(
        f"✅ {role.mention} rolü markete **{price} puan** fiyatla eklendi.", ephemeral=True)


@bot.tree.command(name="market-sil", description="Bir rolü marketten kaldır")
@app_commands.rename(role="rol")
@app_commands.describe(role="Marketten kaldırılacak rol")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def shop_remove(interaction: discord.Interaction, role: discord.Role):
    if guild_data("shop", interaction.guild_id).pop(str(role.id), None) is None:
        raise CantDoThat("Bu rol markette yok.")
    save_data()
    await interaction.response.send_message(f"✅ {role.mention} marketten kaldırıldı.", ephemeral=True)


async def shop_autocomplete(interaction: discord.Interaction, current: str):
    """Suggests the market's roles while someone types in /satın-al."""
    choices = []
    for role, price in shop_items(interaction.guild):
        if current.lower() in role.name.lower():
            choices.append(app_commands.Choice(name=f"{role.name[:70]} — {price} puan", value=str(role.id)))
    return choices[:25]


@bot.tree.command(name="satın-al", description="Marketten puanlarınla bir rol satın al")
@app_commands.rename(item="ürün")
@app_commands.describe(item="Satın almak istediğin rol")
@app_commands.autocomplete(item=shop_autocomplete)
@app_commands.guild_only()
async def buy(interaction: discord.Interaction, item: str):
    price = guild_data("shop", interaction.guild_id).get(item)
    role = interaction.guild.get_role(int(item)) if price else None
    if role is None:
        raise CantDoThat("Bu ürün markette yok. Ürünleri /market ile görebilirsin.")
    if role in interaction.user.roles:
        raise CantDoThat("Bu role zaten sahipsin.")
    balance = get_points(interaction.guild_id, interaction.user.id)
    if balance < price:
        raise CantDoThat(f"Yeterli puanın yok. Gereken: **{price}**, sende olan: **{balance}**.")
    await interaction.response.defer()  # answer Discord right away, then do the slow part
    await interaction.user.add_roles(role, reason="Marketten satın alındı")  # if this fails, no points are taken
    total = add_points(interaction.guild_id, interaction.user.id, -price)
    await interaction.followup.send(
        f"🛍️ **{role.name}** rolünü **{price} puana** satın aldın! Kalan puanın: **{total}**")


# ================================================================
# ROBLOX LEADERBOARD - a top 10 that staff fill in by hand
# ================================================================

BOARD_SIZE = 10
AVATAR_STYLES = {  # choice shown in Discord: which Roblox picture to use
    "Kafa": "avatar-headshot",
    "Büst": "avatar-bust",
    "Tam boy": "avatar",
}
BOARD_COLORS = {
    "Altın": discord.Color.gold(),
    "Mavi": discord.Color.blue(),
    "Yeşil": discord.Color.green(),
    "Kırmızı": discord.Color.red(),
    "Mor": discord.Color.purple(),
}
RANK_BADGES = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
MEDAL_COLORS = {1: discord.Color.gold(), 2: discord.Color.light_grey(), 3: discord.Color.dark_orange()}

ROBLOX_PROFILE_LINK = re.compile(r"roblox\.com/(?:[a-z]{2}(?:-[a-z]{2,4})?/)?users/(\d+)", re.IGNORECASE)
ROBLOX_USERNAME_LINK = re.compile(r"[?&]username=([A-Za-z0-9_]{3,20})", re.IGNORECASE)
ROBLOX_USERNAME = re.compile(r"[A-Za-z0-9_]{3,20}")
ROBLOX_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def roblox_request(method: str, url: str, **kwargs):
    """Calls one of Roblox's public web APIs and returns its JSON reply."""
    try:
        async with aiohttp.ClientSession(timeout=ROBLOX_TIMEOUT) as session:
            async with session.request(method, url, **kwargs) as response:
                if response.status == 429:
                    raise CantDoThat("Roblox şu an çok fazla istek alıyor. Biraz sonra tekrar dene.")
                response.raise_for_status()
                return await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise CantDoThat("Roblox'a şu an ulaşamıyorum. Biraz sonra tekrar dene.")


async def find_roblox_user(text: str) -> dict:
    """Turns a Roblox profile link, username or user ID into {"id", "name", "display_name"}."""
    text = text.strip().strip("<>").lstrip("@")
    if "roblox.com/share" in text.lower():
        raise CantDoThat("Paylaşım linkleri (roblox.com/share...) çalışmıyor. Profili tarayıcıda açıp adres "
                         "çubuğundaki linki (roblox.com/users/...) ya da kullanıcı adını yapıştır.")
    profile_link = ROBLOX_PROFILE_LINK.search(text)
    username_link = ROBLOX_USERNAME_LINK.search(text)
    if profile_link or text.isdigit():
        user_id = int(profile_link.group(1) if profile_link else text)
        reply = await roblox_request("POST", "https://users.roblox.com/v1/users",
                                     json={"userIds": [user_id], "excludeBannedUsers": False})
    elif username_link or ROBLOX_USERNAME.fullmatch(text):
        username = username_link.group(1) if username_link else text
        reply = await roblox_request("POST", "https://users.roblox.com/v1/usernames/users",
                                     json={"usernames": [username], "excludeBannedUsers": False})
    else:
        raise CantDoThat("Bunu anlayamadım. Bir Roblox profil linki (roblox.com/users/...) ya da kullanıcı adı yaz.")
    found = reply.get("data") or []
    if not found:
        raise CantDoThat("Bu Roblox kullanıcısı bulunamadı.")
    user = found[0]
    return {"id": user["id"], "name": user["name"], "display_name": user.get("displayName") or user["name"]}


async def fetch_avatars(user_ids: list, style: str) -> dict:
    """Fresh avatar pictures for many players in one request: {user_id: picture link}.
    Roblox's picture links expire after a while, so they're looked up every time."""
    if not user_ids:
        return {}
    endpoint = AVATAR_STYLES.get(style, "avatar-headshot")
    ids = ",".join(str(user_id) for user_id in user_ids)
    try:
        reply = await roblox_request("GET", f"https://thumbnails.roblox.com/v1/users/{endpoint}"
                                            f"?userIds={ids}&size=420x420&format=Png&isCircular=false")
    except CantDoThat:
        return {}  # show the leaderboard without pictures rather than not at all
    return {item["targetId"]: item["imageUrl"] for item in reply.get("data") or []
            if item.get("state") == "Completed" and item.get("imageUrl")}


async def fetch_current_names(user_ids: list) -> dict:
    """People can change their Roblox names, so look them up fresh: {user_id: (name, display name)}."""
    if not user_ids:
        return {}
    try:
        reply = await roblox_request("POST", "https://users.roblox.com/v1/users",
                                     json={"userIds": user_ids, "excludeBannedUsers": False})
    except CantDoThat:
        return {}
    return {user["id"]: (user["name"], user.get("displayName") or user["name"]) for user in reply.get("data") or []}


def get_board(guild_id) -> dict:
    board = guild_data("roblox_boards", guild_id)
    board.setdefault("title", "🏆 En İyi 10")
    board.setdefault("subtitle", "")
    board.setdefault("color", "Altın")
    board.setdefault("avatar_style", "Kafa")
    board.setdefault("entries", [])  # entries[0] is 1st place; None means an empty spot
    return board


def board_rank_of(board: dict, user_id: int):
    for rank, entry in enumerate(board["entries"], start=1):
        if entry and entry["id"] == user_id:
            return rank
    return None


def tidy_entries(entries: list):
    """Keeps the list at 10 places at most and drops empty spots from the end."""
    del entries[BOARD_SIZE:]
    while entries and entries[-1] is None:
        entries.pop()


def player_label(player: dict) -> str:
    if player["display_name"].lower() == player["name"].lower():
        return player["name"]
    return f"{player['display_name']} (@{player['name']})"


async def build_board(guild: discord.Guild):
    """The leaderboard message: a heading, then one card per player with their Roblox avatar."""
    board = get_board(guild.id)
    filled = [(rank, entry) for rank, entry in enumerate(board["entries"], start=1) if entry]
    user_ids = [entry["id"] for _, entry in filled]
    avatars = await fetch_avatars(user_ids, board["avatar_style"])
    names = await fetch_current_names(user_ids)

    text = f"## {board['title']}"
    if board["subtitle"]:
        text += f"\n{board['subtitle']}"
    if not filled:
        return text + "\n\nSıralama henüz boş. Yetkililer /sıralama-düzenle ile kişi ekleyebilir.", []

    embeds = []
    for rank, entry in filled:
        if entry["id"] in names:  # keep names up to date
            entry["name"], entry["display_name"] = names[entry["id"]]
        embed = discord.Embed(
            title=f"{RANK_BADGES[rank]}  {player_label(entry)}",
            url=f"https://www.roblox.com/users/{entry['id']}/profile",  # the name opens their profile
            description=entry.get("note") or None,
            color=MEDAL_COLORS.get(rank, BOARD_COLORS.get(board["color"], discord.Color.gold())),
        )
        if entry["id"] in avatars:
            embed.set_thumbnail(url=avatars[entry["id"]])
        embeds.append(embed)
    embeds[-1].set_footer(text="Son güncelleme")
    embeds[-1].timestamp = discord.utils.utcnow()
    if names:
        save_data()
    return text, embeds


async def update_live_board(guild: discord.Guild) -> str:
    """Edits the leaderboard posted with /sıralama-düzenle kanal. Returns a note if that didn't work."""
    board = get_board(guild.id)
    channel = guild.get_channel(board.get("channel_id") or 0)
    if channel is None or not board.get("message_id"):
        return ""
    text, embeds = await build_board(guild)
    try:
        message = await channel.fetch_message(board["message_id"])
        await message.edit(content=text, embeds=embeds)
        return ""
    except discord.NotFound:
        board.pop("channel_id", None)
        board.pop("message_id", None)
        save_data()
        return "\n(Kanaldaki sıralama mesajı silinmiş. Yeniden göndermek için /sıralama-düzenle kanal kullan.)"
    except discord.HTTPException:
        return "\n(Kanaldaki sıralama mesajını güncelleyemedim.)"


@tasks.loop(hours=12)
async def board_refresher():
    """Twice a day (and when the bot starts), refreshes live leaderboards so avatars never go stale."""
    for guild in bot.guilds:
        if data["roblox_boards"].get(str(guild.id), {}).get("message_id"):
            try:
                await update_live_board(guild)
            except Exception:
                traceback.print_exc()


@board_refresher.before_loop
async def wait_before_refreshing():
    await bot.wait_until_ready()


@bot.tree.command(name="sıralama", description="Sunucunun Roblox sıralamasını gör")
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 10)  # once every 10 seconds per person
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()  # looking up avatars can take a moment
    text, embeds = await build_board(interaction.guild)
    await interaction.followup.send(content=text, embeds=embeds)


board_admin = app_commands.Group(
    name="sıralama-düzenle",
    description="Roblox sıralamasını düzenle",
    guild_only=True,
    default_permissions=discord.Permissions(manage_guild=True),
)


@board_admin.command(name="ayarla", description="Bir sıraya kişi koy (o sıradaki kişinin yerini alır)")
@app_commands.rename(rank="sıra", note="not")
@app_commands.describe(rank="Kaçıncı sıra? (1-10)", roblox="Roblox profil linki, kullanıcı adı ya da ID",
                       note="İsteğe bağlı not, örneğin '1500 galibiyet'")
async def board_set(interaction: discord.Interaction, rank: app_commands.Range[int, 1, 10], roblox: str,
                    note: Optional[app_commands.Range[str, 1, 200]] = None):
    await interaction.response.defer(ephemeral=True)
    user = await find_roblox_user(roblox)
    board = get_board(interaction.guild_id)
    current_rank = board_rank_of(board, user["id"])
    if current_rank and current_rank != rank:
        raise CantDoThat(f"{player_label(user)} zaten #{current_rank} sırasında. "
                         "Yerini değiştirmek için /sıralama-düzenle taşı kullan.")
    entries = board["entries"]
    while len(entries) < rank:
        entries.append(None)
    replaced = entries[rank - 1]
    if note is None and replaced and replaced["id"] == user["id"]:
        note = replaced.get("note", "")  # same person again: keep their note
    entries[rank - 1] = {**user, "note": note or ""}
    tidy_entries(entries)
    save_data()
    text = f"✅ #{rank}: **{player_label(user)}**"
    if replaced and replaced["id"] != user["id"]:
        text += f" ({player_label(replaced)} yerine)"
    await interaction.followup.send(text + await update_live_board(interaction.guild), ephemeral=True)


@board_admin.command(name="ekle", description="Bir sıraya kişi ekle; alttakiler bir sıra aşağı kayar")
@app_commands.rename(rank="sıra", note="not")
@app_commands.describe(rank="Kaçıncı sıraya? (1-10)", roblox="Roblox profil linki, kullanıcı adı ya da ID",
                       note="İsteğe bağlı not, örneğin '1500 galibiyet'")
async def board_insert(interaction: discord.Interaction, rank: app_commands.Range[int, 1, 10], roblox: str,
                       note: Optional[app_commands.Range[str, 1, 200]] = None):
    await interaction.response.defer(ephemeral=True)
    user = await find_roblox_user(roblox)
    board = get_board(interaction.guild_id)
    current_rank = board_rank_of(board, user["id"])
    if current_rank:
        raise CantDoThat(f"{player_label(user)} zaten #{current_rank} sırasında. "
                         "Yerini değiştirmek için /sıralama-düzenle taşı kullan.")
    entries = board["entries"]
    while len(entries) < rank - 1:
        entries.append(None)
    entries.insert(rank - 1, {**user, "note": note or ""})
    dropped = entries[BOARD_SIZE] if len(entries) > BOARD_SIZE else None
    tidy_entries(entries)
    save_data()
    text = f"✅ **{player_label(user)}** #{rank} sırasına eklendi."
    if dropped:
        text += f" **{player_label(dropped)}** ilk 10'dan çıktı."
    await interaction.followup.send(text + await update_live_board(interaction.guild), ephemeral=True)


@board_admin.command(name="sil", description="Bir sıradaki kişiyi çıkar; alttakiler bir sıra yukarı kayar")
@app_commands.rename(rank="sıra")
@app_commands.describe(rank="Kaçıncı sıradaki kişi çıkarılsın? (1-10)")
async def board_remove(interaction: discord.Interaction, rank: app_commands.Range[int, 1, 10]):
    entries = get_board(interaction.guild_id)["entries"]
    if rank > len(entries) or entries[rank - 1] is None:
        raise CantDoThat(f"#{rank} sırası zaten boş.")
    await interaction.response.defer(ephemeral=True)
    removed = entries.pop(rank - 1)
    tidy_entries(entries)
    save_data()
    await interaction.followup.send(f"✅ **{player_label(removed)}** sıralamadan çıkarıldı."
                                    + await update_live_board(interaction.guild), ephemeral=True)


@board_admin.command(name="taşı", description="Bir kişiyi başka bir sıraya taşı; aradakiler kayar")
@app_commands.rename(from_rank="nereden", to_rank="nereye")
@app_commands.describe(from_rank="Şu anki sırası (1-10)", to_rank="Yeni sırası (1-10)")
async def board_move(interaction: discord.Interaction, from_rank: app_commands.Range[int, 1, 10],
                     to_rank: app_commands.Range[int, 1, 10]):
    entries = get_board(interaction.guild_id)["entries"]
    if from_rank > len(entries) or entries[from_rank - 1] is None:
        raise CantDoThat(f"#{from_rank} sırası boş.")
    if from_rank == to_rank:
        raise CantDoThat("Bu kişi zaten o sırada.")
    await interaction.response.defer(ephemeral=True)
    entry = entries.pop(from_rank - 1)
    while len(entries) < to_rank - 1:
        entries.append(None)
    entries.insert(to_rank - 1, entry)
    tidy_entries(entries)
    save_data()
    await interaction.followup.send(f"✅ **{player_label(entry)}** #{from_rank} → #{to_rank} taşındı."
                                    + await update_live_board(interaction.guild), ephemeral=True)


@board_admin.command(name="görünüm", description="Başlığı, açıklamayı, rengi ve avatar stilini değiştir")
@app_commands.rename(heading="başlık", subtitle="açıklama", color="renk", avatar_style="avatar-stili")
@app_commands.describe(heading="Sıralamanın başlığı",
                       subtitle="Başlığın altındaki yazı (yeni satır için \\n, silmek için -)",
                       color="4-10. sıraların rengi (ilk 3 madalya renginde)",
                       avatar_style="Avatar nasıl görünsün?")
async def board_style(interaction: discord.Interaction,
                      heading: Optional[app_commands.Range[str, 1, 200]] = None,
                      subtitle: Optional[app_commands.Range[str, 1, 1000]] = None,
                      color: Optional[Literal["Altın", "Mavi", "Yeşil", "Kırmızı", "Mor"]] = None,
                      avatar_style: Optional[Literal["Kafa", "Büst", "Tam boy"]] = None):
    board = get_board(interaction.guild_id)
    if heading is None and subtitle is None and color is None and avatar_style is None:
        await interaction.response.send_message(
            f"Şu anki görünüm:\n• Başlık: {board['title']}\n• Açıklama: {board['subtitle'] or '(yok)'}\n"
            f"• Renk: {board['color']}\n• Avatar stili: {board['avatar_style']}\n\n"
            "Değiştirmek için bu komutta en az bir seçeneği doldur.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if heading is not None:
        board["title"] = heading
    if subtitle is not None:
        board["subtitle"] = "" if subtitle.strip() == "-" else subtitle.replace("\\n", "\n")
    if color is not None:
        board["color"] = color
    if avatar_style is not None:
        board["avatar_style"] = avatar_style
    save_data()
    await interaction.followup.send("✅ Görünüm güncellendi! Görmek için /sıralama kullan."
                                    + await update_live_board(interaction.guild), ephemeral=True)


@board_admin.command(name="kanal", description="Sıralamayı bir kanala gönder; her değişiklikte kendini günceller")
@app_commands.rename(channel="kanal")
@app_commands.describe(channel="Sıralamanın duracağı kanal (canlı sıralamayı kapatmak için boş bırak)")
async def board_channel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    board = get_board(interaction.guild_id)
    if channel is None:
        board.pop("channel_id", None)
        board.pop("message_id", None)
        save_data()
        await interaction.response.send_message("✅ Canlı sıralama kapatıldı. Kanaldaki mesaj silinmedi.",
                                                ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    text, embeds = await build_board(interaction.guild)
    message = await channel.send(content=text, embeds=embeds)
    board["channel_id"], board["message_id"] = channel.id, message.id
    save_data()
    await interaction.followup.send(f"✅ Sıralama {channel.mention} kanalına gönderildi. "
                                    "Her değişiklikte kendini otomatik güncelleyecek.", ephemeral=True)


class ConfirmView(discord.ui.View):
    """Yes / cancel buttons. `answer` ends up True, False, or None if nobody clicked in time."""

    def __init__(self, yes_label: str):
        super().__init__(timeout=30)
        self.answer = None
        self.yes.label = yes_label

    @discord.ui.button(label="Evet", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.answer = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Vazgeç", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.answer = False
        self.stop()
        await interaction.response.defer()


@board_admin.command(name="sıfırla", description="Sıralamadaki herkesi çıkar (görünüm ayarları kalır)")
async def board_reset(interaction: discord.Interaction):
    view = ConfirmView("Evet, sıfırla")
    await interaction.response.send_message("⚠️ Sıralamadaki herkes çıkarılacak. Emin misin?",
                                            view=view, ephemeral=True)
    await view.wait()
    if view.answer is None:
        await interaction.edit_original_response(content="⏰ Süre doldu, hiçbir şey silinmedi.", view=None)
    elif not view.answer:
        await interaction.edit_original_response(content="İptal edildi, hiçbir şey silinmedi.", view=None)
    else:
        get_board(interaction.guild_id)["entries"] = []
        save_data()
        extra = await update_live_board(interaction.guild)
        await interaction.edit_original_response(content="✅ Sıralama sıfırlandı." + extra, view=None)


bot.tree.add_command(board_admin)


# ================================================================
# GIVEAWAYS
# ================================================================

GIVEAWAY_UNITS = {"dakika": 60, "saat": 60 * 60, "gün": 24 * 60 * 60}


def giveaway_embed(giveaway: dict) -> discord.Embed:
    """The giveaway message, while it's running or after it ends."""
    if giveaway["ended"]:
        winners = ", ".join(f"<@{user_id}>" for user_id in giveaway.get("winner_ids", []))
        return discord.Embed(
            title=f"🎉 ÇEKİLİŞ BİTTİ: {giveaway['prize']}",
            description=(f"Kazanan: {winners or 'Kimse katılmadı 😢'}\n"
                         f"Katılımcı sayısı: {len(giveaway['entrants'])}\n"
                         f"Başlatan: <@{giveaway['host_id']}>"),
            color=discord.Color.dark_grey(),
        )
    return discord.Embed(
        title=f"🎉 ÇEKİLİŞ: {giveaway['prize']}",
        description=("Katılmak için aşağıdaki butona bas!\n\n"
                     f"Bitiş: {timestamp(giveaway['end'], 'R')} ({timestamp(giveaway['end'], 'f')})\n"
                     f"Kazanan sayısı: {giveaway['winner_count']}\n"
                     f"Başlatan: <@{giveaway['host_id']}>"),
        color=discord.Color.gold(),
    )


class GiveawayView(discord.ui.View):
    """The join button. Its fixed custom_id lets it keep working after the bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉 Katıl", style=discord.ButtonStyle.success, custom_id="giveaway:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = data["giveaways"].get(str(interaction.message.id))
        if giveaway is None or giveaway["ended"]:
            await interaction.response.send_message("Bu çekiliş sona erdi.", ephemeral=True)
            return
        entrants = giveaway["entrants"]
        if interaction.user.id in entrants:
            entrants.remove(interaction.user.id)
            text = "Çekilişten ayrıldın."
        else:
            entrants.append(interaction.user.id)
            text = "🎉 Çekilişe katıldın! Ayrılmak istersen butona tekrar bas."
        save_data()
        await interaction.response.send_message(f"{text} (Katılımcı sayısı: {len(entrants)})", ephemeral=True)


async def end_giveaway(message_id: str, giveaway: dict):
    entrants = giveaway["entrants"]
    giveaway["winner_ids"] = random.sample(entrants, min(giveaway["winner_count"], len(entrants)))
    giveaway["ended"] = True
    save_data()

    channel = bot.get_channel(giveaway["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=giveaway_embed(giveaway), view=None)
    except discord.HTTPException:
        pass  # the giveaway message was deleted
    winners = giveaway["winner_ids"]
    if winners:
        mentions = ", ".join(f"<@{user_id}>" for user_id in winners)
        verb = "kazandın" if len(winners) == 1 else "kazandınız"
        await channel.send(f"🎉 Tebrikler {mentions}! **{giveaway['prize']}** ödülünü {verb}!")
    else:
        await channel.send(f"😢 **{giveaway['prize']}** çekilişine kimse katılmadı.")


@tasks.loop(seconds=20)
async def giveaway_checker():
    """Every 20 seconds: ends finished giveaways and forgets ones that ended over a week ago."""
    now = time.time()
    for message_id, giveaway in list(data["giveaways"].items()):
        try:
            if not giveaway["ended"] and giveaway["end"] <= now:
                await end_giveaway(message_id, giveaway)
            elif giveaway["ended"] and giveaway["end"] < now - 7 * 24 * 60 * 60:
                del data["giveaways"][message_id]
                save_data()
        except Exception:
            traceback.print_exc()  # one broken giveaway shouldn't stop the others


@giveaway_checker.before_loop
async def wait_until_logged_in():
    await bot.wait_until_ready()


@bot.tree.command(name="çekiliş", description="Bu kanalda bir çekiliş başlat")
@app_commands.rename(prize="ödül", duration="süre", unit="birim", winner_count="kazanan-sayısı")
@app_commands.describe(prize="Ne kazanılacak?", duration="Ne kadar sürsün?", unit="Sürenin birimi",
                       winner_count="Kaç kişi kazansın? (1-20)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def start_giveaway(interaction: discord.Interaction, prize: app_commands.Range[str, 1, 200],
                         duration: app_commands.Range[int, 1, 1000],
                         unit: Literal["dakika", "saat", "gün"] = "saat",
                         winner_count: app_commands.Range[int, 1, 20] = 1):
    seconds = duration * GIVEAWAY_UNITS[unit]
    if seconds > 30 * 24 * 60 * 60:
        raise CantDoThat("Bir çekiliş en fazla 30 gün sürebilir.")
    giveaway = {
        "guild_id": interaction.guild_id,
        "channel_id": interaction.channel_id,
        "prize": prize,
        "end": int(time.time() + seconds),
        "winner_count": winner_count,
        "host_id": interaction.user.id,
        "entrants": [],
        "ended": False,
    }
    await interaction.response.defer(ephemeral=True)
    message = await interaction.channel.send(embed=giveaway_embed(giveaway), view=GiveawayView())
    data["giveaways"][str(message.id)] = giveaway
    save_data()
    await interaction.followup.send("✅ Çekiliş başladı!", ephemeral=True)


@bot.tree.command(name="çekiliş-yenile", description="Bu kanaldaki son çekiliş için yeni bir kazanan seç")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def reroll_giveaway(interaction: discord.Interaction):
    finished = [giveaway for giveaway in data["giveaways"].values()
                if giveaway["channel_id"] == interaction.channel_id and giveaway["ended"]]
    if not finished:
        raise CantDoThat("Bu kanalda biten bir çekiliş bulamadım.")
    giveaway = max(finished, key=lambda item: item["end"])
    if not giveaway["entrants"]:
        raise CantDoThat("Bu çekilişe kimse katılmamıştı.")
    # Prefer someone who hasn't won yet
    candidates = [user_id for user_id in giveaway["entrants"]
                  if user_id not in giveaway.get("winner_ids", [])] or giveaway["entrants"]
    winner_id = random.choice(candidates)
    await interaction.response.send_message(
        f"🔄 **{giveaway['prize']}** için yeni kazanan: <@{winner_id}>! Tebrikler! 🎉")


# ================================================================
# COMMUNITY: AFK, INFO COMMANDS, SUGGESTIONS
# ================================================================


@bot.tree.command(name="ping", description="Botun ne kadar hızlı cevap verdiğini ölç")
async def ping(interaction: discord.Interaction):
    started = time.perf_counter()
    await interaction.response.send_message("🏓 Ölçülüyor...")
    reply_ms = (time.perf_counter() - started) * 1000      # how long sending a reply took
    gateway_ms = bot.latency * 1000                          # the bot's connection to Discord
    connection = "?" if math.isinf(gateway_ms) else f"{gateway_ms:.0f} ms"
    if not math.isinf(gateway_ms) and gateway_ms < 300 and reply_ms < 1000:
        verdict = "✅ Hızlı, sorun yok."
    else:
        verdict = ("⚠️ Yavaş! Bu kadar gecikmede komutlar bazen \"yanıt vermedi\" hatası verir. "
                   "Sorun büyük ihtimalle botun çalıştığı sunucuda (host).")
    await interaction.edit_original_response(
        content=f"🏓 Pong!\n• Discord bağlantısı: **{connection}**\n• Cevap gönderme: **{reply_ms:.0f} ms**\n"
                f"• Sürüm: **{BOT_VERSION}** • Sistem: **{platform.system()}**\n{verdict}")


@bot.tree.command(name="afk", description="AFK ol; seni etiketleyenlere haber veririm")
@app_commands.rename(reason="sebep")
@app_commands.describe(reason="Neden AFK'sın? (isteğe bağlı)")
@app_commands.guild_only()
async def afk(interaction: discord.Interaction, reason: app_commands.Range[str, 1, 200] = "AFK"):
    guild_data("afk", interaction.guild_id)[str(interaction.user.id)] = {
        "reason": reason, "since": int(time.time())}
    save_data()
    await interaction.response.send_message(
        f"💤 Artık AFK'sın: {reason}\nBir mesaj yazdığında AFK durumun otomatik olarak kalkar.", ephemeral=True)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return
    afk_users = guild_data("afk", message.guild.id)
    try:
        # Writing any message means you're back
        if afk_users.pop(str(message.author.id), None) is not None:
            save_data()
            await message.reply("👋 Tekrar hoş geldin! AFK durumun kaldırıldı.",
                                delete_after=10, mention_author=False)

        # Tell people when someone they pinged is AFK
        notes = []
        for user in message.mentions[:5]:
            info = afk_users.get(str(user.id))
            if info and user.id != message.author.id:
                notes.append(f"💤 **{user.display_name}** şu an AFK: {info['reason']} ({timestamp(info['since'], 'R')})")
        if notes:
            await message.reply("\n".join(notes), mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass  # can't reply in this channel


@bot.tree.command(name="kullanıcı-bilgi", description="Bir üye hakkında bilgi gör")
@app_commands.rename(member="üye")
@app_commands.describe(member="Kimin bilgisi? (kendin için boş bırak)")
@app_commands.guild_only()
async def user_info(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    roles = [role.mention for role in reversed(member.roles) if not role.is_default()]
    role_text = " ".join(roles[:20]) or "Rol yok"
    if len(roles) > 20:
        role_text += f" (+{len(roles) - 20})"

    embed = discord.Embed(title=f"👤 {member.display_name}", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Kullanıcı adı", value=str(member))
    embed.add_field(name="ID", value=str(member.id))
    embed.add_field(name="Puan", value=str(get_points(interaction.guild_id, member.id)))
    embed.add_field(name="Hesap oluşturma",
                    value=f"{timestamp(member.created_at)} ({timestamp(member.created_at, 'R')})")
    if member.joined_at:
        embed.add_field(name="Sunucuya katılma",
                        value=f"{timestamp(member.joined_at)} ({timestamp(member.joined_at, 'R')})")
    embed.add_field(name=f"Roller ({len(roles)})", value=role_text, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sunucu-bilgi", description="Bu sunucu hakkında bilgi gör")
@app_commands.guild_only()
async def server_info(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"🏠 {guild.name}", color=discord.Color.blurple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Sahip", value=f"<@{guild.owner_id}>")
    embed.add_field(name="Üye sayısı", value=str(guild.member_count))
    embed.add_field(name="Kuruluş", value=f"{timestamp(guild.created_at)} ({timestamp(guild.created_at, 'R')})")
    embed.add_field(name="Kanallar",
                    value=f"💬 {len(guild.text_channels)} yazı • 🔊 {len(guild.voice_channels)} ses")
    embed.add_field(name="Roller", value=str(len(guild.roles) - 1))  # minus @everyone
    embed.add_field(name="Takviye",
                    value=f"Seviye {guild.premium_tier} ({guild.premium_subscription_count or 0} takviye)")
    embed.set_footer(text=f"Sunucu ID: {guild.id}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="Bir üyenin profil fotoğrafını büyük göster")
@app_commands.rename(member="üye")
@app_commands.describe(member="Kimin avatarı? (kendin için boş bırak)")
@app_commands.guild_only()
async def avatar(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"🖼️ {member.display_name}", color=member.color)
    embed.set_image(url=member.display_avatar.with_size(1024).url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="öneri-kanalı", description="Önerilerin gönderileceği kanalı seç")
@app_commands.rename(channel="kanal")
@app_commands.describe(channel="Öneri kanalı")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def set_suggestion_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    set_setting("suggestion_channels", interaction.guild_id, channel.id)
    await interaction.response.send_message(f"✅ Öneriler artık {channel.mention} kanalına gönderilecek.",
                                            ephemeral=True)


@bot.tree.command(name="öneri", description="Sunucu için bir öneride bulun, üyeler oylasın")
@app_commands.rename(idea="öneri")
@app_commands.describe(idea="Önerin nedir?")
@app_commands.guild_only()
@app_commands.checks.cooldown(1, 60)  # once a minute per person
async def suggest(interaction: discord.Interaction, idea: app_commands.Range[str, 5, 1000]):
    channel_id = get_setting("suggestion_channels", interaction.guild_id)
    channel = interaction.guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        raise CantDoThat("Henüz bir öneri kanalı yok. Yetkililer /öneri-kanalı ile bir kanal seçebilir.")
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="💡 Yeni öneri", description=idea, color=discord.Color.yellow())
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    message = await channel.send(embed=embed)
    await message.add_reaction("👍")
    await message.add_reaction("👎")
    await interaction.followup.send(f"✅ Önerin {channel.mention} kanalına gönderildi!", ephemeral=True)


# ================================================================
# CUSTOM EMBEDS
# ================================================================

EMBED_COLORS = {
    "Mavi": discord.Color.blue(),
    "Yeşil": discord.Color.green(),
    "Kırmızı": discord.Color.red(),
    "Altın": discord.Color.gold(),
    "Mor": discord.Color.purple(),
}


class EmbedForm(discord.ui.Modal, title="Embed oluştur"):
    embed_title = discord.ui.TextInput(label="Başlık", max_length=256)
    embed_text = discord.ui.TextInput(label="Mesaj", style=discord.TextStyle.paragraph, max_length=4000)

    def __init__(self, color: discord.Color):
        super().__init__()
        self.embed_color = color

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=self.embed_title.value, description=self.embed_text.value,
                              color=self.embed_color)
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bu kanala mesaj gönderemiyorum.", ephemeral=True)
            return
        await interaction.followup.send("✅ Embed gönderildi!", ephemeral=True)


@bot.tree.command(name="embed", description="Bu kanala özel bir embed mesajı gönder")
@app_commands.rename(color="renk")
@app_commands.describe(color="Embed'in kenar şeridinin rengi")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def embed_command(interaction: discord.Interaction,
                        color: Literal["Mavi", "Yeşil", "Kırmızı", "Altın", "Mor"] = "Mavi"):
    await interaction.response.send_modal(EmbedForm(EMBED_COLORS[color]))  # opens a pop-up form


# ================================================================
# HELP
# ================================================================

HELP_SECTIONS = {
    "🎮 Oyunlar": "/1v1 /sihirli-top /yazı-tura /zar /taş-kağıt-makas /bilgi-yarışması /düello",
    "🏆 Sıralama ve puanlar": "/sıralama /puan /puan-sıralaması /günlük /market /satın-al",
    "💬 Topluluk": "/öneri /afk /kullanıcı-bilgi /sunucu-bilgi /avatar /ping",
    "🛡️ Moderasyon": ("/at /yasakla /yasak-kaldır /sustur /susturma-kaldır /temizle /uyar /uyarılar "
                      "/uyarıları-sil /yavaş-mod /kilitle /kilidi-aç"),
    "⚙️ Yönetim": ("/karşılama-kanalı /veda-kanalı /karşılama-mesajı /karşılama-aç-kapat /karşılama-test "
                  "/otomatik-rol /log-kanalı /öneri-kanalı /market-ekle /market-sil /çekiliş "
                  "/çekiliş-yenile /sıralama-düzenle /1v1-kurulum /embed"),
}


@bot.tree.command(name="yardım", description="Botun yapabildiği her şeyi gör")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Yapabildiklerim", color=discord.Color.blurple())
    for section, commands_text in HELP_SECTIONS.items():
        embed.add_field(name=section, value=" ".join(f"`{name}`" for name in commands_text.split()), inline=False)
    embed.set_footer(text="Moderasyon ve yönetim komutlarını sadece yetkililer görür.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ================================================================
# START THE BOT
# ================================================================

TOKEN = load_token()
if not TOKEN or TOKEN == TOKEN_PLACEHOLDER:
    print("NO TOKEN FOUND: make a file called token.txt in the same folder as bot.py, "
          "paste your bot token into it (nothing else), save it, and start the bot again.")
else:
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("DISCORD REJECTED THE TOKEN: go to the Developer Portal -> your app -> Bot -> Reset Token, "
              "paste the new token into token.txt, save, and start the bot again.")
    except discord.PrivilegedIntentsRequired:
        print("INTENT IS OFF: go to the Developer Portal -> your app -> Bot, turn ON "
              "'Server Members Intent', save, and start the bot again.")
    except Exception:
        traceback.print_exc()
        print("\nThe bot stopped because of the error above.")
wait_before_closing()
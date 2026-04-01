import asyncio
import json
import os
import random
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime
from os import listdir
from os.path import isfile, join

import discord
import requests
from colorama import Fore, Style, init

from lib import api
from lib.imageapi import ocr_image, ocr_print_number
from lib.ocr import *
from console import (KarutaConsole,
                     R, C_TEAL, C_PURPLE, C_AMBER, C_MINT, C_CORAL,
                     C_GRAY, C_DIM, C_WHITE, C_GOLD, C_BLUE)

# init colors
init(convert=True)
match = "(is dropping [3-4] cards!)|(I'm dropping [3-4] cards since this server is currently active!)"
path_to_ocr = "temp"
v = "v2.3.3"

# CardCompanion UID
CARDCOMPANION_ID = 1380936713639166082

# load config
with open("config.json") as f:
    config = json.load(f)

if os.name == 'nt':
    title = True
else:
    title = False

# load vars
token = config["token"]
channels = config["channels"]
guilds = config["servers"]
accuracy = float(config["accuracy"])
blaccuracy = float(config["blaccuracy"])
loghits = config["log_hits"]
logcollection = config["log_collection"]
timestamp = config["timestamp"]
autodrop = config["autodrop"]
debug = config["debug"]
cprint = config["check_print"]
autofarm = config["autofarm"]
verbose = config["very_verbose"]

if autofarm:
    resourcechannel = config["resourcechannel"]
min_wishlist = int(config.get("min_wishlist", 50))
wishlist_lookup_enabled = config.get("wishlist_lookup", True)
wishlist_watching_channels = config.get("wishlist_watching_channels", channels)
clear_console_on_start = config.get("clear_console_on_start", True)
lookup_delay = float(config.get("lookup_delay", 1.5))

# output toggles
log_drops    = config.get("log_drops",    True)
log_grabs    = config.get("log_grabs",    True)
log_wishlist = config.get("log_wishlist", True)
log_autodrop = config.get("log_autodrop", True)
log_kcd      = config.get("log_kcd",      True)
log_autofarm = config.get("log_autofarm", True)

if cprint:
    pn = int(config["print_number"])
if autodrop:
    autodropchannel = config["autodropchannel"]
    dropdelay       = config["dropdelay"]
    randmin         = int(config["randmin"])
    randmax         = int(config["randmax"])

# start console
console = KarutaConsole(version=v, use_timestamp=timestamp)

# consonant set for OCR v/u heuristic
_CONSONANTS = frozenset('bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ')


# helpers

def _parse_char_line(line: str):
    """
    Parse a single line from characters.txt.
    Formats:
        "Gojo Satoru"                  -> ('Gojo Satoru', None)
        "Gojo Satoru, Jujutsu Kaisen"  -> ('Gojo Satoru', 'Jujutsu Kaisen')
    """
    line = line.strip()
    if not line:
        return None
    if ',' in line:
        parts = line.split(',', 1)
        return (parts[0].strip(), parts[1].strip())
    return (line, None)


# bot class

class Main(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.charblacklist = None
        self.aniblacklist  = None
        self.animes        = None
        # list of (char_name: str, anime: str | None)
        self.chars: list[tuple[str, str | None]] = []
        self.messageid    = None
        self.current_card = None
        self.ready        = False
        self.grab_timer   = 0
        self.drop_timer   = 0
        self.url          = None
        self.grab_reason  = ""
        self.missed       = 0
        self.collected    = 0
        self.cardnum      = 0
        self.lookup_next_at = 0.0
        self.lookup_lock  = asyncio.Lock()
        self.drop_lock    = asyncio.Lock()
        if autofarm:
            self.button = None

    # on ready event
    async def on_ready(self):
        if clear_console_on_start:
            await asyncio.create_subprocess_shell("cls" if title else "clear")
        await asyncio.sleep(0.5)
        if sys.gettrace() is None:
            console.print_banner()

        # build startup box
        _sections = []
        _user_str = (
            f"{C_MINT}{self.user.name}#{self.user.discriminator}{R}"
            f"  {C_DIM}({self.user.id}){R}"
        )
        _sections.append(("ONLINE", [_user_str]))

        _watch_items = []
        for _cid in channels:
            _ch = self.get_channel(_cid)
            _cn = f"#{_ch.name}" if _ch else f"(unknown: {_cid})"
            _gn = _ch.guild.name if _ch else "?"
            _watch_items.append(
                f"{C_WHITE}{_gn}{R}  {C_DIM}▸{R}  {C_MINT}{_cn}{R}"
            )
        _sections.append(
            (f"WATCHING  {C_GRAY}({len(_watch_items)} channels){R}", _watch_items)
        )

        if wishlist_watching_channels != channels:
            _wl_items = []
            for _cid in wishlist_watching_channels:
                _ch = self.get_channel(_cid)
                _cn = f"#{_ch.name}" if _ch else f"(unknown: {_cid})"
                _gn = _ch.guild.name if _ch else "?"
                _wl_items.append(
                    f"{C_WHITE}{_gn}{R}  {C_DIM}▸{R}  {C_MINT}{_cn}{R}"
                )
            _sections.append((f"WISHLIST  {C_GRAY}({len(_wl_items)} channels){R}", _wl_items))

        if autodrop:
            _ch = self.get_channel(autodropchannel)
            _cn = f"#{_ch.name}" if _ch else f"(unknown: {autodropchannel})"
            _gn = _ch.guild.name if _ch else "?"
            _sections.append(
                ("AUTODROP", [f"{C_WHITE}{_gn}{R}  {C_DIM}▸{R}  {C_PURPLE}{_cn}{R}"])
            )

        console.print_startup_box(_sections)
        dprint(f"discord.py-self {discord.__version__}")

        await self.update_files()

        # subscribe to guilds
        for guild in guilds:
            try:
                await self.get_guild(guild).subscribe(
                    typing=True, activities=False, threads=False, member_updates=False
                )
            except AttributeError:
                tprint(f"{C_CORAL}Error subscribing to a server?{R}")

        # start tasks
        def spawn(coro, name="task"):
            t = asyncio.get_event_loop().create_task(coro)
            def _done(fut, _name=name):
                exc = fut.exception() if not fut.cancelled() else None
                if exc:
                    tprint(f"{C_CORAL}[TASK ERROR]{R} {_name} crashed: {exc!r}")
            t.add_done_callback(_done)
            return t

        spawn(self.cooldown(),                          "cooldown")
        spawn(self.filewatch("keywords\\animes.txt"),  "filewatch:animes")
        spawn(self.filewatch("keywords\\characters.txt"), "filewatch:characters")
        spawn(self.filewatch("keywords\\aniblacklist.txt"), "filewatch:aniblacklist")
        spawn(self.configwatch("config.json"),          "configwatch")
        spawn(self.filewatch("keywords\\charblacklist.txt"), "filewatch:charblacklist")
        spawn(console.animate(),                        "console:animate")
        if autodrop:
            spawn(self.autodrop(), "autodrop")
        if autofarm:
            spawn(self.autofarm(), "autofarm")
        self.ready = True

    # message listener
    async def on_message(self, message):
        cid = message.channel.id

        if (
            not self.ready
            or message.author.id != 646937666251915264
            or cid not in channels
        ):
            return

        buttons_ref = [None]

        def mcheck(before, after):
            if before.id != message.id:
                return False
            try:
                children = after.components[0].children
                if not children:
                    return False
                if children[0].disabled:
                    return False
                buttons_ref[0] = children
                dprint("Message edit found")
                return True
            except (IndexError, AttributeError):
                dprint(f"mcheck component error - {after.components}")
                return False

        if re.search("A wishlisted card is dropping!", message.content):
            dprint("Wishlisted card detected")

        # drop match
        if self.grab_timer == 0 and re.search(match, message.content):
            BUTTON_WINDOW = 25.0
            ocr_start = asyncio.get_running_loop().time()
            if isbutton(cid):
                edit_task = asyncio.get_running_loop().create_task(
                    self.wait_for("message_edit", check=mcheck, timeout=BUTTON_WINDOW)
                )
            else:
                edit_task = None

            console.set_state("SCANNING")

            charlist = []
            anilist  = []
            grabbed  = False

            async with self.drop_lock:
                if self.grab_timer != 0:
                    if edit_task and not edit_task.done():
                        edit_task.cancel()
                    return

                # save image
                with open("temp\\card.webp", "wb") as file:
                    file.write(requests.get(message.attachments[0].url).content)

                # split cards
                if filelength("temp\\card.webp") == 836:
                    cardnum = 3
                    for a in range(3):
                        await get_card(f"{path_to_ocr}\\card{a + 1}.png", "temp\\card.webp", a)
                    for a in range(3):
                        await get_top(f"{path_to_ocr}\\card{a + 1}.png", f"{path_to_ocr}\\char\\top{a + 1}.png")
                        await get_bottom(f"{path_to_ocr}\\card{a + 1}.png", f"{path_to_ocr}\\char\\bottom{a + 1}.png")
                        if cprint:
                            await get_print(f"{path_to_ocr}\\card{a + 1}.png", f"{path_to_ocr}\\char\\print{a + 1}.png")
                else:
                    cardnum = 4
                    for a in range(4):
                        await get_card(f"{path_to_ocr}\\card{a + 1}.png", "temp\\card.webp", a)
                    for a in range(4):
                        await get_top(f"{path_to_ocr}\\card{a + 1}.png", f"{path_to_ocr}\\char\\top{a + 1}.png")
                        await get_bottom(f"{path_to_ocr}\\card{a + 1}.png", f"{path_to_ocr}\\char\\bottom{a + 1}.png")
                        if cprint:
                            await get_print(f"{path_to_ocr}\\card{a + 1}.png", f"{path_to_ocr}\\char\\print{a + 1}.png")

                # run ocr
                onlyfiles = [ff for ff in listdir("temp\\char") if isfile(join("temp\\char", ff))]
                printlist = []
                for img in onlyfiles:
                    if "4" in img and cardnum != 4:
                        continue
                    if "top" in img:
                        img_path = path_to_ocr + "\\char\\top" + re.sub(r"\D", "", img) + ".png"
                        charlist.append(self.normalize_ocr_text(await self.ocr_best(img_path)))
                    elif "bottom" in img:
                        img_path = path_to_ocr + "\\char\\bottom" + re.sub(r"\D", "", img) + ".png"
                        ani_text = self.normalize_ocr_text(await self.ocr_best(img_path))
                        anilist.append(ani_text)
                        if cprint:
                            card_num = re.sub(r"\D", "", img)
                            printlist.append(ocr_print_number(path_to_ocr + f"\\char\\print{card_num}.png"))
                        else:
                            printlist.append("9999999")

                vprint(f"Anilist: {anilist}")
                vprint(f"Charlist: {charlist}")

                for i, number in enumerate(printlist):
                    try:
                        printlist[i] = int(re.sub(r" \d$| ", "", number))
                    except ValueError:
                        dprint(f"ValueError parsing print number: '{number}'")
                        printlist[i] = 9999999
                vprint(f"Printlist: {printlist}")

                def emoji(b):
                    match b:
                        case 0: return "1️⃣"
                        case 1: return "2️⃣"
                        case 2: return "3️⃣"
                        case 3: return "4️⃣"

                grab_idx    = -1
                grab_reason = ""

                # check char matches
                char_matches = []
                for i, character in enumerate(charlist):
                    if (
                        api.isSomethingChar(character, anilist[i], self.chars, accuracy)
                        and not api.isSomething(character, self.charblacklist, accuracy)
                        and not api.isSomething(anilist[i], self.aniblacklist, blaccuracy)
                    ):
                        kw_idx = self.keyword_match_priority_char(character, anilist[i], self.chars, accuracy)
                        char_matches.append((i, kw_idx, character))

                if char_matches:
                    char_matches.sort(key=lambda x: x[1])
                    grab_idx, _, best_char = char_matches[0]
                    grab_reason = (
                        f"Character: {C_MINT}{best_char}{R}  {C_DIM}from{R}  {C_TEAL}{anilist[grab_idx]}{R}"
                    )
                    self.grab_reason = f"Character: {best_char} from {anilist[grab_idx]}"
                    if loghits:
                        with open("log.txt", "a") as ff:
                            ff.write(
                                f"{current_time() + ' - ' if timestamp else ''}"
                                f"Character: {best_char} from {anilist[grab_idx]} - {message.attachments[0].url}\n"
                            )

                # check anime matches
                if grab_idx == -1:
                    anime_matches = []
                    for i, anime in enumerate(anilist):
                        if (
                            api.isSomething(anime, self.animes, accuracy)
                            and not api.isSomething(charlist[i], self.charblacklist, accuracy)
                            and not api.isSomething(anime, self.aniblacklist, blaccuracy)
                        ):
                            kw_idx = self.keyword_match_priority(anime, self.animes, accuracy)
                            anime_matches.append((i, kw_idx, anime))

                    if anime_matches:
                        anime_matches.sort(key=lambda x: x[1])
                        grab_idx, _, best_anime = anime_matches[0]
                        grab_reason = (
                            f"Anime: {C_TEAL}{best_anime}{R}  {C_DIM}│{R}  {C_MINT}{charlist[grab_idx]}{R}"
                        )
                        self.grab_reason = f"Anime: {best_anime} | {charlist[grab_idx]}"
                        if loghits:
                            with open("log.txt", "a") as ff:
                                ff.write(
                                    f"{current_time() + ' - ' if timestamp else ''}"
                                    f"Anime: {best_anime} | {charlist[grab_idx]} - {message.attachments[0].url}\n"
                                )

                # check print matches
                if grab_idx == -1 and cprint:
                    for i, prin in enumerate(printlist):
                        if (
                            prin <= pn
                            and anilist[i] not in self.aniblacklist
                            and charlist[i] not in self.charblacklist
                        ):
                            grab_idx    = i
                            grab_reason = f"Print #{C_GOLD}{prin}{R}"
                            self.grab_reason = f"Print #{prin}: {charlist[i]} from {anilist[i]}"
                            if loghits:
                                with open("log.txt", "a") as ff:
                                    ff.write(
                                        f"{current_time() + ' - ' if timestamp else ''}"
                                        f"Print #{prin}: {charlist[i]} from {anilist[i]} - "
                                        f"{re.sub(chr(63) + '.*', '', message.attachments[0].url)}\n"
                                    )
                            break

                # execute grab
                grabbed = grab_idx != -1
                if grabbed:
                    drop_print(f"{C_TEAL}[{message.channel.name}]{R}  {grab_reason}")
                    self.url = message.attachments[0].url

                    if isbutton(cid):
                        elapsed   = asyncio.get_running_loop().time() - ocr_start
                        remaining = max(BUTTON_WINDOW - elapsed, 1.0)
                        try:
                            if edit_task.done():
                                edit_task.result()
                                dprint("edit_task already resolved before await")
                            else:
                                await asyncio.wait_for(asyncio.shield(edit_task), timeout=remaining)
                        except asyncio.TimeoutError:
                            edit_task.cancel()
                            drop_print(
                                f"{C_TEAL}[{message.channel.name}]{R}  "
                                f"{C_CORAL}Button edit timed out after {elapsed:.1f}s OCR + "
                                f"{remaining:.1f}s wait — card gone{R}"
                            )
                            grabbed = False
                        except Exception as e:
                            drop_print(f"{C_TEAL}[{message.channel.name}]{R}  {C_CORAL}edit_task error: {e}{R}")
                            grabbed = False
                        else:
                            local_buttons = buttons_ref[0]
                            if local_buttons and grab_idx < len(local_buttons):
                                await asyncio.sleep(random.uniform(0.1, 0.35))
                                try:
                                    await local_buttons[grab_idx].click()
                                    await self.afterclick()
                                except discord.errors.InvalidData:
                                    drop_print(
                                        f"{C_TEAL}[{message.channel.name}]{R}  "
                                        f"{C_CORAL}Interaction failed — Discord didn't ACK in time (card likely gone){R}"
                                    )
                                    grabbed = False
                                except Exception as e:
                                    drop_print(
                                        f"{C_TEAL}[{message.channel.name}]{R}  "
                                        f"{C_CORAL}Button click error: {e}{R}"
                                    )
                                    grabbed = False
                            else:
                                drop_print(
                                    f"{C_TEAL}[{message.channel.name}]{R}  "
                                    f"{C_CORAL}Button index {grab_idx} out of range "
                                    f"(only {len(local_buttons) if local_buttons else 0} buttons){R}"
                                )
                                grabbed = False
                    else:
                        if edit_task and not edit_task.done():
                            edit_task.cancel()
                        await self.react_add(message, emoji(grab_idx))
                else:
                    if edit_task and not edit_task.done():
                        edit_task.cancel()

            console.set_state("IDLE")

            # fallback to wishlist
            if grab_idx == -1 and wishlist_lookup_enabled and cid in wishlist_watching_channels:
                await self.do_wishlist_lookup(message, charlist, anilist, cid, mcheck, emoji, buttons_ref)

        # confirm grab
        elif re.search(
            rf"<@{str(self.user.id)}> took the \*\*.*\*\* card `.*`!"
            rf"|<@{str(self.user.id)}> fought off .* and took the \*\*.*\*\* card `.*`!",
            message.content
        ):
            a = re.search(
                rf"<@{str(self.user.id)}>.*took the \*\*(.*)\*\* card `(.*)`!",
                message.content
            )
            self.grab_timer = 600
            self.missed    -= 1
            self.collected += 1
            console.collected = self.collected
            console.missed    = self.missed
            grab_print(f"{C_TEAL}[{message.channel.name}]{R}  Obtained  {C_MINT}{a.group(1)}{R}")
            if logcollection:
                with open("log.txt", "a") as ff:
                    reason_str = f" [{self.grab_reason}]" if self.grab_reason else ""
                    if timestamp:
                        ff.write(f"{current_time()} - Obtained: {a.group(1)}{reason_str} - {self.url}\n")
                    else:
                        ff.write(f"Obtained: {a.group(1)}{reason_str} - {self.url}\n")

        # bless checks
        elif message.content.startswith(f"<@{str(self.user.id)}>, your **Evasion"):
            dprint("Evasion blessing detected — resetting grab cd")
            self.grab_timer = 0
        elif message.content.startswith(f"<@{str(self.user.id)}>, your **Generosity"):
            dprint("Generosity blessing detected — resetting drop cd")
            self.drop_timer = 0

    # wishlist fallback
    async def do_wishlist_lookup(self, message, charlist, anilist, cid, mcheck, emoji, buttons_ref):
        channel = self.get_channel(autodropchannel)
        if channel is None:
            channel = self.get_channel(message.channel.id)
        best_idx = -1
        best_wl  = -1

        wl_print(f"{C_TEAL}[{channel.name}]{R} No keyword match — checking wishlists...")

        for i in range(len(charlist)):
            name   = self.normalize_ocr_text(fix_ocr_spaces(charlist[i].strip()))
            series = self.normalize_ocr_text(fix_ocr_spaces(anilist[i].strip()))
            if not name:
                continue

            if api.isSomething(name, self.charblacklist, blaccuracy):
                wl_print(f"{C_AMBER}Skipping blacklisted character:{R} {name}")
                continue
            if series and api.isSomething(series, self.aniblacklist, blaccuracy):
                wl_print(f"{C_AMBER}Skipping blacklisted anime:{R} {series}")
                continue

            query = f"clu {series} {name}" if series else f"clu {name}"

            async with self.lookup_lock:
                now       = asyncio.get_running_loop().time()
                wait_time = self.lookup_next_at - now
                if wait_time > 0:
                    wl_print(f"{C_AMBER}Rate limit — waiting {wait_time:.1f}s before next lookup{R}")
                    await asyncio.sleep(wait_time)

                async with channel.typing():
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                await channel.send(query)
                self.lookup_next_at = asyncio.get_running_loop().time() + lookup_delay

                try:
                    resp = await self.wait_for(
                        "message",
                        timeout=6.0,
                        check=lambda m: (
                            m.author.id == CARDCOMPANION_ID
                            and m.channel.id == channel.id
                            and (len(m.embeds) > 0 or bool(m.content))
                        )
                    )
                except asyncio.TimeoutError:
                    wl_print(f"{C_AMBER}Timeout waiting for clu response for:{R} {name}")
                    continue

                if not resp.embeds:
                    wl_print(f"{C_AMBER}clu couldn't find{R} '{name}' {C_DIM}(OCR mismatch){R} — skipping")
                    continue

            wl = -1
            try:
                embed = resp.embeds[0]

                vprint(
                    f"clu embed dump — "
                    f"title={embed.title!r}  "
                    f"desc={embed.description!r}  "
                    f"fields={[(f.name, f.value) for f in (embed.fields or [])]}  "
                    f"content={resp.content!r}"
                )

                if embed.description:
                    desc_clean = embed.description.replace("**", "")
                    m = re.search(r"wishlist\s*[:\-]\s*([\d,]+)", desc_clean, re.IGNORECASE)
                    if m:
                        wl = int(re.sub(r"[^0-9]", "", m.group(1)))

                if wl == -1:
                    for field in (embed.fields or []):
                        if field.name.strip().lower() == "wishlist":
                            wl_text = re.sub(r"[^0-9]", "", field.value)
                            if wl_text:
                                wl = int(wl_text)
                            break

                if wl == -1 and resp.content:
                    m = re.search(r"wishlist\s*[:\-]\s*([\d,]+)", resp.content, re.IGNORECASE)
                    if m:
                        wl = int(re.sub(r"[^0-9]", "", m.group(1)))

            except Exception as e:
                dprint(f"WL parse error for {name}: {e}")

            wl_print(
                f"{C_WHITE}{name}{R} {C_DIM}({series}){R}  {C_DIM}▸{R}  "
                f"{C_GOLD}{wl if wl >= 0 else '?'} wishlists{R}"
            )

            if wl > best_wl:
                best_wl  = wl
                best_idx = i

            if i < len(charlist) - 1:
                await asyncio.sleep(random.uniform(0.3, 0.8))

        if best_idx == -1 or best_wl < min_wishlist:
            wl_print(
                f"Best wishlist: {C_CORAL}{best_wl}{R} — "
                f"below threshold of {C_AMBER}{min_wishlist}{R}, skipping"
            )
            return

        wl_print(f"Grabbing {C_MINT}{charlist[best_idx]}{R} with {C_GOLD}{best_wl}{R} wishlists")
        self.url         = message.attachments[0].url
        self.grab_reason = f"Wishlist ({best_wl}): {charlist[best_idx]} from {anilist[best_idx]}"

        if loghits:
            with open("log.txt", "a") as ff:
                ff.write(
                    f"{current_time() + ' - ' if timestamp else ''}"
                    f"Wishlist ({best_wl}): {charlist[best_idx]} from {anilist[best_idx]} - "
                    f"{message.attachments[0].url}\n"
                )

        if isbutton(cid):
            try:
                await self.wait_for("message_edit", check=mcheck, timeout=25.0)
            except asyncio.TimeoutError:
                wl_print(f"{C_CORAL}Button edit timed out — card gone{R}")
                return

            local_buttons = buttons_ref[0]
            if local_buttons and best_idx < len(local_buttons):
                await asyncio.sleep(random.uniform(0.1, 0.35))
                try:
                    await local_buttons[best_idx].click()
                    await self.afterclick()
                except discord.errors.InvalidData:
                    wl_print(f"{C_CORAL}Interaction failed — Discord didn't ACK in time (card likely gone){R}")
                except Exception as e:
                    wl_print(f"{C_CORAL}Button click error: {e}{R}")
            else:
                wl_print(f"{C_CORAL}Button index {best_idx} out of range{R}")
        else:
            await self.react_add(message, emoji(best_idx))

    # add reaction
    async def react_add(self, message, emoji):
        try:
            dprint("Attempting to react")
            await asyncio.sleep(random.uniform(0.1, 0.35))
            await message.add_reaction(emoji)
        except discord.errors.Forbidden as oopsie:
            dprint(f"React failed: {oopsie}")
            return
        self.missed  += 1
        console.missed = self.missed
        dprint(f"Reacted with {emoji} successfully")

    # keyword priority helpers

    @staticmethod
    def keyword_match_priority(text, keyword_list, threshold):
        """Priority index for a flat keyword list (animes, blacklists)."""
        text_l = text.lower().strip()
        for idx, kw in enumerate(keyword_list):
            kw_l = kw.lower().strip()
            if kw_l and SequenceMatcher(None, text_l, kw_l).ratio() >= threshold:
                return idx
        return len(keyword_list)

    @staticmethod
    def keyword_match_priority_char(char_text: str, anime_text: str,
                                    parsed_chars: list, threshold: float) -> int:
        """
        Priority index for a parsed chars list of (name, optional_anime) tuples.
        Lower index = higher priority (appears earlier in the keyword file).
        When an anime qualifier is present it must also match.
        """
        char_l  = char_text.lower().strip()
        anime_l = anime_text.lower().strip()
        for idx, (char_name, char_anime) in enumerate(parsed_chars):
            if not char_name:
                continue
            if SequenceMatcher(None, char_l, char_name.lower()).ratio() >= threshold:
                if char_anime is None:
                    return idx
                if SequenceMatcher(None, anime_l, char_anime.lower()).ratio() >= threshold:
                    return idx
        return len(parsed_chars)

    @staticmethod
    def _fix_vu_confusion(text: str) -> str:
        """
        EasyOCR sometimes reads 'v' as 'u' for the Karuta card font.
        """
        if 'u' not in text and 'U' not in text:
            return text
        chars = list(text)
        for i, ch in enumerate(chars):
            if ch not in ('u', 'U'):
                continue
            prev_ok = i > 0 and chars[i - 1] in _CONSONANTS
            next_ok = i < len(chars) - 1 and chars[i + 1] in _CONSONANTS
            if prev_ok and next_ok:
                chars[i] = 'v' if ch == 'u' else 'V'
        return ''.join(chars)

    # clean up OCR text
    @staticmethod
    def normalize_ocr_text(text):
        text = unicodedata.normalize("NFKC", text or "")
        text = text.replace("\r", " ").replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        tokens = text.split(" ") if text else []
        merged = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if len(token) == 1 and token.isalpha():
                letters = [token]
                j = i + 1
                while j < len(tokens) and len(tokens[j]) == 1 and tokens[j].isalpha():
                    letters.append(tokens[j])
                    j += 1
                if len(letters) >= 2:
                    merged.append("".join(letters))
                    i = j
                    continue
            merged.append(token)
            i += 1
        text = " ".join(merged)
        text = re.sub(r"\s+([:;,\.\?\!\)\]])", r"\1", text)
        text = re.sub(r"([\(\[])\s+", r"\1", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = text.strip()
        text = Main._fix_vu_confusion(text)
        return text

    # run OCR in thread
    async def ocr_best(self, image_path):
        def _run():
            text = ocr_image(image_path)
            dprint(f"ocr_best [{image_path}]: '{text}'")
            return text
        return await asyncio.to_thread(_run)

    # timer loop
    async def cooldown(self):
        while True:
            await asyncio.sleep(1)
            if self.grab_timer > 0:
                self.grab_timer -= 1
            if self.drop_timer > 0:
                self.drop_timer -= 1

            console.grab_timer = self.grab_timer
            console.drop_timer = self.drop_timer
            console.collected  = self.collected
            console.missed     = self.missed

            if console.state in ("WAITING", "IDLE"):
                console.set_state("WAITING" if self.grab_timer > 0 else "IDLE")

            if title:
                grab_str = f"Grab: {self.grab_timer}s" if self.grab_timer > 0 else "Grab: ready"
                drop_str = f"Drop: {self.drop_timer}s" if self.drop_timer > 0 else "Drop: ready"
                await asyncio.create_subprocess_shell(
                    f"title Karuta Sniper {v} - Collected {self.collected} - Missed {self.missed} - "
                    f"{grab_str} - {drop_str}"
                )

    # reload keyword files
    async def update_files(self):
        with open("keywords\\characters.txt", encoding="utf-8") as ff:
            raw_chars = ff.read().splitlines()
        self.chars = []
        for line in raw_chars:
            parsed = _parse_char_line(line)
            if parsed:
                self.chars.append(parsed)

        with open("keywords\\animes.txt", encoding="utf-8") as ff:
            self.animes = ff.read().splitlines()
        with open("keywords\\aniblacklist.txt", encoding="utf-8") as ff:
            self.aniblacklist = ff.read().splitlines()
        with open("keywords\\charblacklist.txt", encoding="utf-8") as ff:
            self.charblacklist = ff.read().splitlines()

        tprint(
            f"Loaded  {C_TEAL}{len(self.animes)}{R} animes  "
            f"{C_DIM}│{R}  {C_CORAL}{len(self.aniblacklist)}{R} blacklisted  "
            f"{C_DIM}│{R}  {C_TEAL}{len(self.chars)}{R} characters  "
            f"{C_DIM}│{R}  {C_CORAL}{len(self.charblacklist)}{R} blacklisted"
        )

    # watch text files
    async def filewatch(self, path):
        bruh = api.FileWatch(path)
        dprint(f"Filewatch activated for {path}")
        while True:
            await asyncio.sleep(2)
            if bruh.watch():
                await self.update_files()

    # watch config.json
    async def configwatch(self, path):
        bruh = api.FileWatch(path)
        while True:
            await asyncio.sleep(1)
            if bruh.watch():
                with open("config.json") as ff:
                    cfg = json.load(ff)
                global accuracy, wishlist_lookup_enabled, wishlist_watching_channels
                accuracy                  = float(cfg["accuracy"])
                wishlist_lookup_enabled   = cfg.get("wishlist_lookup", True)
                wishlist_watching_channels = cfg.get("wishlist_watching_channels", channels)
                dprint("Config reloaded")

    # auto farm
    async def autofarm(self):
        channel = self.get_channel(resourcechannel)
        while True:
            async with channel.typing():
                await asyncio.sleep(random.uniform(0.2, 1))
            await channel.send("kw")
            async for message in channel.history(limit=1):
                dprint(message.content)
                if "you do not have" in message.content:
                    farm_print("Autofarm - You don't have a permit")
                else:
                    match1 = re.search(r"(\d+) hour", message.content)
                    match0 = re.search(r"(\d+) minute", message.content)
                    if match1:
                        hours = int(match1.group(1))
                        farm_print(f"Autofarm - Waiting for {hours} hour(s) to work again")
                        await asyncio.sleep(hours * 3600 + 5)
                    elif match0:
                        minutes = int(match0.group(1))
                        farm_print(f"Autofarm - Waiting for {minutes} minutes to work again")
                        await asyncio.sleep(minutes * 60 + 5)
                    else:
                        farm_print("Autofarm - Processing...")
                if message is not None:
                    reply = await self.wait_for(
                        "message",
                        check=lambda m: m.author.id == 646937666251915264
                    )
                    if reply:
                        await self.autofindresource()
                        await reply.components[0].children[1].click()
                        farm_print("Autofarm - Worked successfully!")
                        await asyncio.sleep(12 * 3600 + 5)

    # find best resource node
    async def autofindresource(self):
        channel = self.get_channel(resourcechannel)
        async with channel.typing():
            await asyncio.sleep(random.uniform(0.2, 1))
        await channel.send("kn")
        reply = await client.wait_for(
            "message",
            check=lambda m: m.author.id == 646937666251915264
        )
        a = re.compile(
            r"`(\w+)` · \*\*(\d+)%\*\* tax · \*\*(\d+)(%\*\* power · \*\*(\d+)|\*)",
            re.MULTILINE
        ).findall(reply.embeds[0].to_dict()["description"].replace(",", ""))
        top      = 0
        material = None
        for interest in a:
            if not interest.count("") == 1:
                if int(interest[4]) > top:
                    top      = int(interest[4])
                    material = interest[0]
            else:
                top      = int(interest[2])
                material = interest[0]
        async with channel.typing():
            await asyncio.sleep(random.uniform(0.9, 1.7))
        await channel.send(f"kjn abcde {material}")

    # run auto drop
    async def autodrop(self):
        channel    = self.get_channel(autodropchannel)
        first_run  = True
        while True:
            try:
                if not first_run:
                    await asyncio.sleep(dropdelay + random.randint(randmin, randmax))
                first_run = False

                grab_wait, drop_wait = await self.check_kcd(channel)
                wait_secs = max(grab_wait, drop_wait)
                if wait_secs > 0:
                    console.set_state("WAITING")
                    self.grab_timer = grab_wait
                    self.drop_timer = drop_wait
                    remaining = wait_secs + random.randint(5, 15)
                    while remaining > 0:
                        chunk     = min(remaining, 30)
                        await asyncio.sleep(chunk)
                        remaining -= chunk

                console.set_state("DROPPING")
                async with channel.typing():
                    await asyncio.sleep(random.uniform(0.2, 1))
                await channel.send("kd")
                self.drop_timer = 1800
                autodrop_print("Cards dropped successfully")
                console.set_state("IDLE")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                tprint(f"{C_CORAL}[Autodrop] Error ({type(e).__name__}: {e}) — retrying in 30s{R}")
                console.set_state("IDLE")
                first_run = True
                await asyncio.sleep(30)

    # get cooldown status
    async def check_kcd(self, channel):
        async with channel.typing():
            await asyncio.sleep(random.uniform(0.2, 0.6))

        listener_task = asyncio.get_event_loop().create_task(
            self.wait_for(
                "message",
                timeout=10.0,
                check=lambda m: (
                    m.author.id == 646937666251915264
                    and m.channel.id == channel.id
                    and len(m.embeds) > 0
                )
            )
        )
        await channel.send("kcd")

        try:
            resp = await listener_task
        except asyncio.TimeoutError:
            kcd_print(f"{C_AMBER}No response from Karuta — assuming both ready{R}")
            return 0, 0

        desc        = resp.embeds[0].description or ""
        fields_text = " ".join(f.value for f in (resp.embeds[0].fields or []))
        full_text   = desc + " " + fields_text
        clean_text  = re.sub(r"[*_`~]", "", full_text)

        def parse_cd(text, label):
            if re.search(rf"{label} is currently available", text, re.IGNORECASE):
                return 0
            mins = re.search(rf"{label}.*?available in (\d+) minute", text, re.IGNORECASE)
            if mins:
                return int(mins.group(1)) * 60
            secs = re.search(rf"{label}.*?available in (\d+) second", text, re.IGNORECASE)
            if secs:
                return int(secs.group(1))
            fallback = re.search(
                rf"{label}.*?(\d+)\s*(?:minute|min|second|sec)", text, re.IGNORECASE
            )
            if fallback:
                val = int(fallback.group(1))
                if re.search(rf"{label}.*?{val}\s*(?:minute|min)", text, re.IGNORECASE):
                    return val * 60
                return val
            return 0

        grab_secs = parse_cd(clean_text, "Grab")
        drop_secs = parse_cd(clean_text, "Drop")
        _grab_s = f"{C_MINT}ready{R}" if grab_secs == 0 else f"{C_AMBER}{grab_secs}s{R}"
        _drop_s = f"{C_MINT}ready{R}" if drop_secs == 0 else f"{C_AMBER}{drop_secs}s{R}"
        kcd_print(f"Grab: {_grab_s}  {C_DIM}│{R}  Drop: {_drop_s}")
        return grab_secs, drop_secs

    # post-click
    async def afterclick(self):
        dprint("Clicked on Button")
        self.missed  += 1
        console.missed = self.missed


# module-level helpers

def fix_ocr_spaces(text):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def current_time():
    return datetime.now().strftime("%H:%M:%S")


def isbutton(data):
    return data in [648044573536550922, 776520559621570621, 858004885809922078, 857978372688445481]


# print wrappers
def tprint(message):        console.log(message)
def dprint(message):
    if debug:   console.log_debug(message)
def vprint(message):
    if verbose: console.log_info(message)
def drop_print(message):
    if log_drops:    console.log_grab(message)
def grab_print(message):
    if log_grabs:    console.log_collect(message)
def wl_print(message):
    if log_wishlist: console.log_wl(message)
def autodrop_print(message):
    if log_autodrop: console.log_drop(message)
def kcd_print(message):
    if log_kcd:      console.log_kcd(message)
def farm_print(message):
    if log_autofarm: console.log_farm(message)


# entry point
if not token:
    tprint(f"{C_CORAL}No token set in config.json — exiting{R}")
    sys.exit(1)

client = Main(guild_subscriptions=False)
tprint(f"{C_MINT}Starting bot...{R}")
try:
    client.run(token)
except KeyboardInterrupt:
    tprint(f"{C_CORAL}Ctrl-C detected — exiting{R}")
    client.close()
    sys.exit(0)
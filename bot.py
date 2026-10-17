import re, base64, asyncio, logging
from datetime import datetime

import aiohttp
import pymongo
import pyromod.listen  # noqa: F401  (adds client.ask)
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.enums import ChatMemberStatus, ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, UserNotParticipant
from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

from config import (TG_BOT_TOKEN, APP_ID, API_HASH, CHANNEL_ID, PORT, DB_URI, DB_NAME, SHORTLINK_URL,
                    SHORTLINK_API, FORCE_SUB_CHANNEL, WORKERS, CUSTOM_CAPTION, PROTECT_CONTENT,
                    START_MSG, FORCE_MSG, ADMINS, LINK_BASE)

log = logging.getLogger("bot")

# ---------------------------------------------------------------- database
db = pymongo.MongoClient(DB_URI)[DB_NAME]
users, settings = db["users"], db["config"]

# ---------------------------------------------------------------- client + state
app = Client("Bot", api_id=APP_ID, api_hash=API_HASH, bot_token=TG_BOT_TOKEN, workers=WORKERS)
state = {"started": datetime.now(), "username": "", "db_channel": None, "invite": ""}


# ---------------------------------------------------------------- helpers
def encode(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().strip("=")


def decode(s: str) -> str:
    s = s.strip("=")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


async def _subscribed(_, client, msg):
    if not FORCE_SUB_CHANNEL or msg.from_user.id in ADMINS:
        return True
    try:
        m = await client.get_chat_member(FORCE_SUB_CHANNEL, msg.from_user.id)
    except UserNotParticipant:
        return False
    return m.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER)


subscribed = filters.create(_subscribed)
admin_pm = filters.private & filters.user(ADMINS)


def fmt(text, u):
    return text.format(first=u.first_name, last=u.last_name, id=u.id, mention=u.mention,
                       username="@" + u.username if u.username else None)


async def get_messages(ids):
    out = []
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        try:
            out += await app.get_messages(state["db_channel"].id, chunk)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            out += await app.get_messages(state["db_channel"].id, chunk)
    return out


def get_message_id(msg) -> int:
    """Message id in the DB channel from a forward or a t.me link (0 if not from it)."""
    ch = state["db_channel"]
    if msg.forward_from_chat:
        return msg.forward_from_message_id if msg.forward_from_chat.id == ch.id else 0
    if msg.text and not msg.forward_sender_name:
        m = re.match(r"https://t.me/(?:c/)?(.*)/(\d+)", msg.text)
        if m:
            chan, mid = m.group(1), int(m.group(2))
            if (chan.isdigit() and f"-100{chan}" == str(ch.id)) or chan == ch.username:
                return mid
    return 0


async def ask_msg_id(uid, prompt) -> int:
    while True:
        try:
            m = await app.ask(uid, prompt, filters=filters.forwarded | filters.text, timeout=60)
        except Exception:
            return 0
        mid = get_message_id(m)
        if mid:
            return mid
        await m.reply("❌ Error\n\nThis post/link is not from my DB Channel", quote=True)


async def get_shortlink(link: str) -> str:
    row = settings.find_one({"_id": "shortener_config"}) or {}
    site = row.get("shortener") or SHORTLINK_URL
    api = row.get("shortener_api") or SHORTLINK_API
    link = link.replace("http://", "https://")
    shareus = site == "api.shareus.in"
    url = f"https://{site}/shortLink" if shareus else f"https://{site}/api"
    params = {"token": api, "format": "json", "link": link} if shareus else {"api": api, "url": link}
    fallback = f"{url}?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, raise_for_status=True, ssl=False) as r:
                data = await r.json(content_type=None)
        if data.get("status") == "success":
            return data["shortlink"] if shareus else data["shortenedUrl"]
        log.warning("shortener error: %s", data.get("message"))
    except Exception as e:
        log.warning("shortener error: %s", e)
    return fallback


async def make_link(payload: str) -> str:
    """Permanent link (survives a banned bot) if a link base is set, else a direct bot link."""
    row = settings.find_one({"_id": "link_base"})
    base = row["value"] if row else LINK_BASE
    if base:
        return f"{base}{'&' if '?' in base else '?'}s={payload}"
    return f"https://telegram.me/{state['username']}?start={payload}"


async def reply_links(msg, link):
    share = "https://telegram.me/share/url?url="
    if re.search(r"/r/?\?s=", link):
        # Link-Worker link: it makes the short link itself when tapped, so don't shorten it here too.
        return await msg.reply_text(
            f"<b>Here is your link (share this one)</b>\n\n{link}", quote=True,
            reply_markup=Markup([[Btn("Share Link", url=share + link)]]))
    slink = await get_shortlink(link)
    await msg.reply_text(
        f"<b>Here are your links\n\nLink: </b>{link} \n\n<b>Slink : </b>{slink}", quote=True,
        reply_markup=Markup([[Btn("Share Link", url=share + link), Btn("Share Slink", url=share + slink)]]))


# ---------------------------------------------------------------- user handlers
@app.on_message(filters.command("start") & filters.private & subscribed)
async def start(client, message):
    uid = message.from_user.id
    if not users.find_one({"_id": uid}):
        users.insert_one({"_id": uid})

    if len(message.command) > 1:
        try:
            parts = decode(message.command[1]).split("-")
            n = abs(state["db_channel"].id)
            if len(parts) == 3:
                a, b = int(parts[1]) // n, int(parts[2]) // n
                ids = list(range(a, b + 1)) if a <= b else list(range(a, b - 1, -1))
            elif len(parts) == 2:
                ids = [int(parts[1]) // n]
            else:
                return
        except Exception:
            return

        wait = await message.reply("Please wait...")
        try:
            msgs = await get_messages(ids)
        except Exception:
            return await message.reply_text("Something went wrong..!")
        await wait.delete()

        for m in msgs:
            caption = m.caption.html if m.caption else ""
            if CUSTOM_CAPTION and m.document:
                caption = CUSTOM_CAPTION.format(previouscaption=caption, filename=m.document.file_name)
            kw = dict(chat_id=uid, caption=caption, parse_mode=ParseMode.HTML,
                      reply_markup=None, protect_content=PROTECT_CONTENT)
            try:
                await m.copy(**kw)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await m.copy(**kw)
            except Exception:
                pass
        return

    await message.reply_text(
        fmt(START_MSG, message.from_user), quote=True, disable_web_page_preview=True,
        reply_markup=Markup([[Btn("😊 About Me", callback_data="about"), Btn("🔒 Close", callback_data="close")]]))


@app.on_message(filters.command("start") & filters.private)
async def not_joined(client, message):
    buttons = [[Btn("Join Channel", url=state["invite"])]]
    if len(message.command) > 1:
        buttons.append([Btn("Try Again", url=f"https://t.me/{state['username']}?start={message.command[1]}")])
    await message.reply(fmt(FORCE_MSG, message.from_user), reply_markup=Markup(buttons),
                        quote=True, disable_web_page_preview=True)


@app.on_callback_query()
async def callbacks(client, query):
    if query.data == "about":
        await query.message.edit_text("<b>○ Creator : @MrKrazyBot</b>", disable_web_page_preview=True,
                                      reply_markup=Markup([[Btn("🔒 Close", callback_data="close")]]))
    elif query.data == "close":
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except Exception:
            pass


# ---------------------------------------------------------------- admin handlers
@app.on_message(admin_pm & filters.command("users"))
async def users_count(client, message):
    await message.reply(f"{users.count_documents({})} users are using this bot")


@app.on_message(admin_pm & filters.command("stats"))
async def stats(client, message):
    s = int((datetime.now() - state["started"]).total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    await message.reply(f"<b>BOT UPTIME</b>\n{d}d {h}h {m}m {s}s")


@app.on_message(admin_pm & filters.command("broadcast"))
async def broadcast(client, message):
    src = message.reply_to_message
    if not src:
        msg = await message.reply("<code>Use this command as a reply to any telegram message.</code>")
        await asyncio.sleep(8)
        return await msg.delete()

    status = await message.reply("<i>Broadcasting Message.. This will Take Some Time</i>")
    total = ok = blocked = deleted = failed = 0
    for doc in users.find():
        uid = doc["_id"]
        try:
            try:
                await src.copy(uid)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await src.copy(uid)
            ok += 1
        except UserIsBlocked:
            users.delete_one({"_id": uid})
            blocked += 1
        except InputUserDeactivated:
            users.delete_one({"_id": uid})
            deleted += 1
        except Exception:
            failed += 1
        total += 1

    await status.edit(f"<b><u>Broadcast Completed</u>\n\nTotal Users: <code>{total}</code>\n"
                      f"Successful: <code>{ok}</code>\nBlocked Users: <code>{blocked}</code>\n"
                      f"Deleted Accounts: <code>{deleted}</code>\nUnsuccessful: <code>{failed}</code></b>")


@app.on_message(admin_pm & filters.command("genlink"))
async def genlink(client, message):
    mid = await ask_msg_id(message.from_user.id, "Forward Message from the DB Channel (with Quotes)..\nor Send the DB Channel Post link")
    if mid:
        n = abs(state["db_channel"].id)
        await reply_links(message, await make_link(encode(f"get-{mid * n}")))


@app.on_message(admin_pm & filters.command("batch"))
async def batch(client, message):
    uid = message.from_user.id
    first = await ask_msg_id(uid, "Forward the First Message from DB Channel (with Quotes)..\nor Send the DB Channel Post Link")
    last = first and await ask_msg_id(uid, "Forward the Last Message from DB Channel (with Quotes)..\nor Send the DB Channel Post link")
    if first and last:
        n = abs(state["db_channel"].id)
        await reply_links(message, await make_link(encode(f"get-{first * n}-{last * n}")))


@app.on_message(admin_pm & filters.command("shortlink"))
async def set_shortlink(client, message):
    if len(message.command) < 3:
        return await message.reply("Usage: `/shortlink site.com api_key`")
    site, api = message.command[1:3]
    settings.update_one({"_id": "shortener_config"}, {"$set": {"shortener": site, "shortener_api": api}}, upsert=True)
    await message.reply(f"Global Shortener Updated!\nSite: `{site}`\nAPI: `{api}`")


@app.on_message(admin_pm & filters.command("shortener"))
async def show_shortener(client, message):
    row = settings.find_one({"_id": "shortener_config"}) or {}
    await message.reply(f"Current Global Shortener:\nSite: `{row.get('shortener') or SHORTLINK_URL}`\n"
                        f"API: `{row.get('shortener_api') or SHORTLINK_API}`")


@app.on_message(admin_pm & filters.command("linkbase"))
async def link_base_cmd(client, message):
    arg = message.command[1] if len(message.command) > 1 else None
    row = settings.find_one({"_id": "link_base"})
    current = row["value"] if row else LINK_BASE
    if arg is None:
        if current:
            return await message.reply(f"Permanent links are <b>ON</b>.\nBase: <code>{current}</code>\n\n"
                                       "Change: /linkbase https://you.github.io/f/\nTurn off: /linkbase off")
        return await message.reply("Permanent links are <b>OFF</b> (links open this bot directly).\n"
                                   "Turn on: /linkbase https://you.github.io/f/")
    if arg.lower() == "off":
        settings.update_one({"_id": "link_base"}, {"$set": {"value": ""}}, upsert=True)
        return await message.reply("Permanent links are now <b>OFF</b>.")
    if not re.fullmatch(r"https://[^\s<>\"']+", arg):
        return await message.reply("Send a full address starting with https://")
    settings.update_one({"_id": "link_base"}, {"$set": {"value": arg}}, upsert=True)
    sep = "&" if "?" in arg else "?"
    await message.reply(f"Saved. New links will look like:\n<code>{arg}{sep}s=CODE</code>")


COMMANDS = ["start", "users", "broadcast", "batch", "genlink", "stats", "shortlink", "shortener", "linkbase"]


@app.on_message(admin_pm & (filters.text | filters.caption) & ~filters.command(COMMANDS))
async def auto_shortener(client, message):
    text = message.text or message.caption
    m = re.search(r"https?://\S+", text)
    if not m:
        return
    link = m.group(0).rstrip(".,!?)]}>\"'")
    link = re.sub(r"^https?://(t\.me|telegram\.me)/", "https://telegram.me/", link)
    link = link.replace("telegram.me/+", "telegram.me/%2B")
    slink = await get_shortlink(link)
    await message.reply_text(
        f"<b>Original:-</b> {text}\n\n<b>Short Link:-</b> {slink}", quote=True,
        reply_markup=Markup([[Btn("Share Short Link", url=f"https://telegram.me/share/url?url={slink}")]]))


# ---------------------------------------------------------------- run
async def main():
    await app.start()
    app.set_parse_mode(ParseMode.HTML)
    state["username"] = (await app.get_me()).username

    if FORCE_SUB_CHANNEL:
        try:
            chat = await app.get_chat(FORCE_SUB_CHANNEL)
            if not chat.invite_link:
                await app.export_chat_invite_link(FORCE_SUB_CHANNEL)
                chat = await app.get_chat(FORCE_SUB_CHANNEL)
            state["invite"] = chat.invite_link
        except Exception as e:
            log.error("Can't get invite link for FORCE_SUB_CHANNEL=%s (is the bot admin there?): %s", FORCE_SUB_CHANNEL, e)
            return
    try:
        state["db_channel"] = await app.get_chat(CHANNEL_ID)
        await (await app.send_message(CHANNEL_ID, "Test Message")).delete()
    except Exception as e:
        log.error("Make sure the bot is admin in the DB channel and CHANNEL_ID=%s is right: %s", CHANNEL_ID, e)
        return

    routes = web.RouteTableDef()

    @routes.get("/", allow_head=True)
    async def health(_):
        return web.json_response("OK")

    web_app = web.Application()
    web_app.add_routes(routes)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    log.info("Bot started successfully.")
    await idle()
    await app.stop()


if __name__ == "__main__":
    app.run(main())

import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated

from bot import Bot
from config import ADMINS, FORCE_MSG, START_MSG, CUSTOM_CAPTION, PROTECT_CONTENT
from helper_func import subscribed, decode, get_messages
from database.database import add_user, del_user, full_userbase, present_user, database, user_data, config_data


REPLY_ERROR = "<code>Reply to a Telegram message to broadcast it.</code>"


@Bot.on_message(filters.command("start") & filters.private & subscribed)
async def start_command(client: Client, message):
    user_id = message.from_user.id

    if not await present_user(user_id):
        try:
            await add_user(user_id)
        except:
            pass

    if len(message.text) > 7:
        try:
            string = await decode(message.text.split(" ", 1)[1])
            args = string.split("-")

            if len(args) == 3:
                start = int(int(args[1]) / abs(client.db_channel.id))
                end = int(int(args[2]) / abs(client.db_channel.id))

                if start <= end:
                    ids = range(start, end + 1)
                else:
                    ids = range(start, end - 1, -1)

            elif len(args) == 2:
                ids = [int(int(args[1]) / abs(client.db_channel.id))]
            else:
                return
        except:
            return

        wait = await message.reply("Please wait...")

        try:
            messages = await get_messages(client, ids)
        except:
            await wait.edit("Something went wrong..!")
            return

        await wait.delete()

        for msg in messages:
            if CUSTOM_CAPTION and msg.document:
                caption = CUSTOM_CAPTION.format(
                    previouscaption="" if not msg.caption else msg.caption.html,
                    filename=msg.document.file_name
                )
            else:
                caption = "" if not msg.caption else msg.caption.html

            try:
                await msg.copy(
                    chat_id=user_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    protect_content=PROTECT_CONTENT
                )
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await msg.copy(
                    chat_id=user_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    protect_content=PROTECT_CONTENT
                )
            except:
                pass

        return

    await message.reply_text(
        START_MSG.format(
            first=message.from_user.first_name,
            last=message.from_user.last_name,
            username=('@' + message.from_user.username)
            if message.from_user.username else None,
            mention=message.from_user.mention,
            id=user_id
        ),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("😊 About Me", callback_data="about"),
            InlineKeyboardButton("🔒 Close", callback_data="close")
        ]]),
        disable_web_page_preview=True,
        quote=True
    )


@Bot.on_message(filters.command("start") & filters.private)
async def not_joined(client: Client, message):
    buttons = [[InlineKeyboardButton("Join Channel", url=client.invitelink)]]

    if len(message.command) > 1:
        buttons.append([
            InlineKeyboardButton(
                "Try Again",
                url=f"https://t.me/{client.username}?start={message.command[1]}"
            )
        ])

    await message.reply(
        FORCE_MSG.format(
            first=message.from_user.first_name,
            last=message.from_user.last_name,
            username=('@' + message.from_user.username)
            if message.from_user.username else None,
            mention=message.from_user.mention,
            id=message.from_user.id
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        quote=True,
        disable_web_page_preview=True
    )


@Bot.on_message(filters.command("broadcast") & filters.private & filters.user(ADMINS))
async def broadcast(client: Bot, message):
    if not message.reply_to_message:
        return await message.reply(REPLY_ERROR)

    users = await full_userbase()
    client.broadcast_cancelled = False

    cancel = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
    ]])

    status = await message.reply(
        f"<b>Broadcasting...</b>\n\n"
        f"Total: <code>{len(users)}</code>\n"
        f"Sent: <code>0</code>",
        reply_markup=cancel
    )

    sent = blocked = deleted = failed = 0

    for user_id in users:
        if client.broadcast_cancelled:
            break

        try:
            await message.reply_to_message.copy(user_id)
            sent += 1

        except FloodWait as e:
            await asyncio.sleep(e.value)

            if client.broadcast_cancelled:
                break

            try:
                await message.reply_to_message.copy(user_id)
                sent += 1
            except:
                failed += 1

        except UserIsBlocked:
            await del_user(user_id)
            blocked += 1

        except InputUserDeactivated:
            await del_user(user_id)
            deleted += 1

        except:
            failed += 1

        if (sent + blocked + deleted + failed) % 25 == 0:
            try:
                await status.edit(
                    f"<b>Broadcasting...</b>\n\n"
                    f"Total: <code>{len(users)}</code>\n"
                    f"Sent: <code>{sent}</code>\n"
                    f"Failed: <code>{failed}</code>",
                    reply_markup=cancel
                )
            except:
                pass

    processed = sent + blocked + deleted + failed

    await status.edit(
        f"<b>{'Broadcast Cancelled' if client.broadcast_cancelled else 'Broadcast Completed'}</b>\n\n"
        f"Total: <code>{len(users)}</code>\n"
        f"Sent: <code>{sent}</code>\n"
        f"Blocked: <code>{blocked}</code>\n"
        f"Deleted: <code>{deleted}</code>\n"
        f"Failed: <code>{failed}</code>\n"
        f"Remaining: <code>{len(users) - processed}</code>"
    )


@Bot.on_callback_query()
async def callbacks(client: Bot, query: CallbackQuery):
    if query.data == "about":
        await query.message.edit_text(
            "<b>○ Creator : @MrKrazyBot</b>",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔒 Close", callback_data="close")
            ]])
        )

    elif query.data == "close":
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except:
            pass

    elif query.data == "cancel_broadcast":
        if query.from_user.id not in ADMINS:
            return await query.answer("Not authorized.", show_alert=True)

        client.broadcast_cancelled = True
        await query.answer("Broadcast cancelled.")


@Bot.on_message(filters.command("stats") & filters.private & filters.user(ADMINS))
async def stats(client: Bot, message):
    users = user_data.count_documents({})

    db_stats = database.command("dbStats")
    total_used = db_stats.get("storageSize", 0) + db_stats.get("indexSize", 0)

    user_stats = database.command("collStats", user_data.name)
    config_stats = database.command("collStats", config_data.name)

    this_bot = (
        user_stats.get("storageSize", 0) +
        user_stats.get("totalIndexSize", 0) +
        config_stats.get("storageSize", 0) +
        config_stats.get("totalIndexSize", 0)
    )

    limit = 512 * 1024 * 1024
    other_bots = max(0, total_used - this_bot)
    remaining = max(0, limit - total_used)

    def size(value):
        if value >= 1024 * 1024:
            return f"{value / 1024 / 1024:.2f} MB"
        return f"{value / 1024:.2f} KB"

    await message.reply(
        f"<b>Bot Stats</b>\n\n"
        f"Users: <code>{users}</code>\n\n"
        f"This bot: <code>{size(this_bot)}</code>\n"
        f"Other bots: <code>{size(other_bots)}</code>\n"
        f"MongoDB used: <code>{size(total_used)} / 512 MB</code>\n"
        f"MongoDB left: <code>{size(remaining)}</code>"
    )

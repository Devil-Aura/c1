import os
import json
import logging
from telegram import Update, MessageEntity
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
)
from telegram.error import TelegramError

BOT_TOKEN = ""  # Replace with your actual bot token
FORCE_SUB_CHANNEL = -1002432405855  # Your force sub channel ID
DATA_FILE = "user_data.json"

# Setup logging - only errors
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot_errors.log")]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Load / Save  (all keys stored as STR to
#  avoid int→str mismatch after JSON reload)
# ─────────────────────────────────────────────
def load_user_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)   # keys are always str after JSON load
    except Exception:
        pass
    return {}

def save_user_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save user data: {e}")

user_data = load_user_data()

# ─────────────────────────────────────────────
#  Helper: always use str(user_id) as key
# ─────────────────────────────────────────────
def uid(user_id: int) -> str:
    """Return string version of user_id for consistent dict key usage."""
    return str(user_id)

def ensure_user(user_id: int):
    """Create default record if not present."""
    key = uid(user_id)
    if key not in user_data:
        user_data[key] = {"thumbnail": None, "state": "idle"}
    return key


# ─────────────────────────────────────────────
#  Force subscription check
# ─────────────────────────────────────────────
async def is_user_joined(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return False

FORCE_SUB_MSG = (
    "🔒 <b>Join Required</b>\n\n"
    "To use this bot, please join our channel first.\n\n"
    "⚡ <b>@World_Fastest_Bots</b>\n\n"
    "Join our channel and try again."
)


# ─────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    ensure_user(user_id)
    save_user_data(user_data)

    welcome_text = (
        "🎬 <b>Video Cover/Thumbnail Bot</b>\n\n"
        "- Add a custom cover/thumbnail to your videos instantly!\n\n"
        "📸 <b>How to use:</b>\n"
        "• Send a photo — it will be saved as thumbnail\n"
        "• Send any video — thumbnail will be added automatically\n"
        "• Works for all your videos\n\n"
        "🛠 <b>Commands:</b>\n"
        "• /mythumb — See your saved thumbnail\n"
        "• /delthumb — Remove your thumbnail\n"
        "• /help — Get help guide\n\n"
        "⚡ <b>Powered by:</b>\n @World_Fastest_Bots\n\n"
        "💬 <b>Need help?</b> Feel free to contact us!"
    )
    await update.message.reply_text(welcome_text, parse_mode='HTML')


# ─────────────────────────────────────────────
#  Handle photo
# ─────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if not await is_user_joined(user_id, context):
        await update.message.reply_text(FORCE_SUB_MSG, parse_mode='HTML')
        return

    photos = update.message.photo
    largest_photo = max(photos, key=lambda p: p.file_size)

    key = ensure_user(user_id)

    if user_data[key].get("state") == "waiting_for_image":
        smallest = min(photos, key=lambda p: p.file_size)

        if smallest.file_size > 200 * 1024 or smallest.width > 320 or smallest.height > 320:
            await update.message.reply_text(
                "❌ Please send a smaller image (under 200KB and 320×320 pixels)."
            )
            return

        user_data[key]["image_file_id"] = largest_photo.file_id
        save_user_data(user_data)

        try:
            entities = [
                MessageEntity(
                    type=e["type"],
                    offset=e["offset"],
                    length=e["length"],
                    user=e.get("user")
                )
                for e in user_data[key].get("caption_entities") or []
            ] or None

            await context.bot.send_video(
                chat_id=update.message.chat_id,
                video=user_data[key]["video_file_id"],
                cover=user_data[key]["image_file_id"],
                caption=user_data[key]["video_caption"],
                caption_entities=entities,
                supports_streaming=True,
                has_spoiler=user_data[key].get("has_spoiler", False),
                reply_to_message_id=update.message.message_id - 1
            )

            # Persist thumbnail for future videos
            user_data[key]["thumbnail"] = largest_photo.file_id

        except TelegramError as e:
            logger.error(f"send_video error: {e}")
            await update.message.reply_text(f"❌ Error sending video: {str(e)}")

        # Reset state, keep thumbnail
        user_data[key].update({
            "state": "idle",
            "video_file_id": None,
            "video_caption": None,
            "caption_entities": None,
            "image_file_id": None,
            "has_spoiler": False
        })

    else:
        # Just saving thumbnail
        user_data[key]["thumbnail"] = largest_photo.file_id
        user_data[key]["state"] = "idle"
        await update.message.reply_text("✅ Thumbnail saved! Now send me a video.")

    save_user_data(user_data)


# ─────────────────────────────────────────────
#  Handle video
# ─────────────────────────────────────────────
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if not await is_user_joined(user_id, context):
        await update.message.reply_text(FORCE_SUB_MSG, parse_mode='HTML')
        return

    video = update.message.video
    if not video:
        return await update.message.reply_text("❌ Please send a valid video.")

    key = ensure_user(user_id)
    saved_thumbnail = user_data[key].get("thumbnail")

    if saved_thumbnail:
        try:
            await context.bot.send_video(
                chat_id=update.message.chat_id,
                video=video.file_id,
                cover=saved_thumbnail,
                caption=update.message.caption,
                caption_entities=update.message.caption_entities,
                supports_streaming=True,
                reply_to_message_id=update.message.message_id
            )
            return
        except TelegramError as e:
            logger.error(f"send_video with saved thumbnail error: {e}")
            await update.message.reply_text(
                "❌ Error using saved thumbnail. Please send a fresh photo first."
            )
            # Clear bad thumbnail
            user_data[key]["thumbnail"] = None
            save_user_data(user_data)
            return

    # No saved thumbnail — ask for one
    caption_entities = [
        {
            "offset": e.offset,
            "length": e.length,
            "type": e.type,
            "user": e.user.to_dict() if e.type == "text_mention" else None
        }
        for e in update.message.caption_entities or []
    ]

    user_data[key].update({
        "state": "waiting_for_image",
        "video_file_id": video.file_id,
        "video_caption": update.message.caption,
        "caption_entities": caption_entities,
        "image_file_id": None,
        "has_spoiler": user_data[key].get("has_spoiler", False)
    })

    save_user_data(user_data)
    await update.message.reply_text("✅ Video received! Now send me a photo for the cover.")


# ─────────────────────────────────────────────
#  Thumbnail management commands
# ─────────────────────────────────────────────
async def my_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    key = uid(user_id)
    thumbnail = user_data.get(key, {}).get("thumbnail")

    if thumbnail:
        try:
            await update.message.reply_photo(
                photo=thumbnail,
                caption=(
                    "🖼️ <b>Your Current Thumbnail</b>\n\n"
                    "This image will be added to all your videos automatically.\n\n"
                    "Use /delthumb to delete this current thumbnail."
                ),
                parse_mode='HTML'
            )
        except Exception:
            await update.message.reply_text("❌ Can't load thumbnail. Please set a new one.")
    else:
        await update.message.reply_text("❌ No thumbnail saved yet. Send me a photo to set one.")


async def delete_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    key = uid(user_id)

    if user_data.get(key, {}).get("thumbnail"):
        user_data[key]["thumbnail"] = None
        save_user_data(user_data)
        await update.message.reply_text("✅ Thumbnail removed successfully!")
    else:
        await update.message.reply_text("❌ No thumbnail found to delete.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🎬 <b>Video Cover/Thumbnail Bot - Help Guide</b>\n\n"
        "📖 <b>How to use this bot:</b>\n"
        "1. <b>Send a photo</b> — It will be saved as your thumbnail\n"
        "2. <b>Send a video</b> — The thumbnail will be added automatically\n"
        "3. <b>Repeat</b> — Same thumbnail works for all future videos\n\n"
        "🛠 <b>Commands:</b>\n"
        "• /start — Start the bot\n"
        "• /mythumb — See your thumbnail\n"
        "• /delthumb — Remove thumbnail\n"
        "• /help — Show this guide\n\n"
        "💡 <b>Tips:</b>\n"
        "• Use clear photos for best results\n"
        "• Thumbnail works for all videos\n"
        "• No need to resend photos\n\n"
        "⚡ <b>Powered by:</b>\n @World_Fastest_Bots\n\n"
        "💬 <b>Need help or feedback?</b> Feel free to reach us!"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')


# ─────────────────────────────────────────────
#  Callback handler
# ─────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    if query.data == "check_join":
        if await is_user_joined(user.id, context):
            await query.edit_message_text(
                "✅ <b>Welcome!</b>\n\n"
                "You can now use the bot.\n\n"
                "Send a photo to set as thumbnail, then send any video!\n\n"
                "⚡ <b>Powered by:</b> @World_Fastest_Bots\n\n"
                "💬 <b>Need help?</b> Contact us anytime!",
                parse_mode='HTML'
            )
        else:
            await query.answer("Please join the channel first!", show_alert=True)


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mythumb", my_thumbnail))
    app.add_handler(CommandHandler("delthumb", delete_thumbnail))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("🎬 Video Cover Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

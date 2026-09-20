import os
import re
import uuid
import asyncio
import logging
import subprocess
from pathlib import Path

import yt_dlp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ---------- تنظیمات ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8080))
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# تنظیم آدرس سرور تولید توکن PO
POT_SERVER_URL = "http://127.0.0.1:4416"
os.environ["YTDLP_POT_SERVER_URL"] = POT_SERVER_URL

MAX_TELEGRAM_SIZE = 50 * 1024 * 1024

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------- کیبورد پایین ----------
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["📥 دانلود یوتیوب"], ["📥 دانلود اینستاگرام"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# ---------- گزینه‌های کیفیت ----------
QUALITIES = {
    "1080": ("🎬 1080p", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best[height<=1080]", "video"),
    "720":  ("🎬 720p",  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]", "video"),
    "480":  ("🎬 480p",  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]", "video"),
    "360":  ("🎬 360p",  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]", "video"),
    "mp3":  ("🎵 فقط صدا (MP3)", "bestaudio/best", "audio"),
}


# ---------- توابع کمکی ----------
def human_size(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


def is_valid_url(text: str) -> bool:
    return bool(re.match(r"https?://\S+", text))


def _download(url: str, format_selector: str, kind: str, out_path: Path):
    """دانلود سینک - داخل thread اجرا می‌شه"""
    ydl_opts = {
        "outtmpl": str(out_path),
        "format": format_selector,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
        "socket_timeout": 60,
    }

    if kind == "audio":
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        ydl_opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        final_path = Path(ydl.prepare_filename(info))

        if kind == "audio":
            mp3 = final_path.with_suffix(".mp3")
            if mp3.exists():
                final_path = mp3

        if not final_path.exists():
            mp4 = final_path.with_suffix(".mp4")
            if mp4.exists():
                final_path = mp4

        return info, final_path


def _compress_video(input_path: Path, output_path: Path):
    """فشرده‌سازی با ffmpeg تا زیر 50MB"""
    for crf in [28, 32, 36, 40]:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-vcodec", "libx264",
            "-crf", str(crf),
            "-preset", "veryfast",
            "-acodec", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if output_path.exists() and output_path.stat().st_size <= MAX_TELEGRAM_SIZE:
            return True
    return output_path.exists() and output_path.stat().st_size <= MAX_TELEGRAM_SIZE


async def _safe_delete(path: Path, delay: int = 3):
    try:
        await asyncio.sleep(delay)
        if path.exists():
            path.unlink()
    except Exception:
        pass


# ---------- هندلرها ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 سلام!\n\n"
        "به ربات دانلودر خوش اومدی 🎉\n"
        "از دکمه‌های پایین انتخاب کن که از کجا می‌خوای دانلود کنی:",
        reply_markup=MAIN_KEYBOARD,
    )


async def youtube_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = "waiting_link"
    context.user_data["platform"] = "youtube"
    await update.message.reply_text(
        "🎬 لطفاً **لینک ویدیوی یوتیوب** رو بفرست:",
        parse_mode="Markdown",
    )


async def instagram_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = "waiting_link"
    context.user_data["platform"] = "instagram"
    await update.message.reply_text(
        "📸 لطفاً **لینک پست اینستاگرام** رو بفرست:",
        parse_mode="Markdown",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state != "waiting_link":
        await update.message.reply_text(
            "برای شروع، از دکمه‌های پایین یکی رو انتخاب کن 👇",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    url = update.message.text.strip()
    if not is_valid_url(url):
        await update.message.reply_text("❌ این یه لینک معتبر نیست. دوباره بفرست.")
        return

    context.user_data["url"] = url
    context.user_data["state"] = "waiting_quality"

    buttons = []
    for key, (label, _, _) in QUALITIES.items():
        buttons.append([InlineKeyboardButton(label, callback_data=f"q|{key}")])

    await update.message.reply_text(
        "✅ لینک دریافت شد.\n\n"
        "کیفیت مورد نظرت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def quality_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("q|"):
        return

    qkey = data.split("|", 1)[1]
    if qkey not in QUALITIES:
        await query.edit_message_text("❌ گزینه نامعتبر.")
        return

    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("❌ لینک پیدا نشد. از اول شروع کن.")
        return

    label, fmt, kind = QUALITIES[qkey]
    await query.edit_message_text(
        f"⏳ در حال دانلود با کیفیت {label}...\nممکنه چند لحظه طول بکشه."
    )

    chat_id = update.effective_chat.id
    job_id = uuid.uuid4().hex[:8]
    out_path = DOWNLOAD_DIR / f"{job_id}.%(ext)s"

    try:
        await context.bot.send_chat_action(
            chat_id,
            ChatAction.UPLOAD_VOICE if kind == "audio" else ChatAction.UPLOAD_VIDEO,
        )

        info, final_path = await asyncio.to_thread(_download, url, fmt, kind, out_path)
        title = info.get("title", "فایل")
        size = final_path.stat().st_size

        if kind == "video" and size > MAX_TELEGRAM_SIZE:
            await query.edit_message_text("🗜 حجم فایل زیاده، در حال فشرده‌سازی...")
            compressed = DOWNLOAD_DIR / f"{job_id}_c.mp4"
            ok = await asyncio.to_thread(_compress_video, final_path, compressed)
            if ok:
                final_path.unlink(missing_ok=True)
                final_path = compressed
                size = final_path.stat().st_size
            else:
                await query.edit_message_text(
                    "❌ فایل بعد از فشرده‌سازی هم بزرگ‌تر از ۵۰ مگابایت شد و تلگرام نمی‌تونه بفرسته."
                )
                final_path.unlink(missing_ok=True)
                context.user_data.clear()
                return

        with open(final_path, "rb") as f:
            if kind == "audio":
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    title=title,
                    caption=f"🎵 {title}",
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=f"🎬 {title}\n📦 {human_size(size)}",
                    supports_streaming=True,
                )

        await query.edit_message_text(f"✅ ارسال شد:\n{title}")
        asyncio.create_task(_safe_delete(final_path))

        context.user_data.clear()
        await context.bot.send_message(
            chat_id=chat_id,
            text="می‌خوای یه دانلود دیگه انجام بدی؟ از دکمه‌های پایین انتخاب کن 👇",
            reply_markup=MAIN_KEYBOARD,
        )

    except yt_dlp.utils.DownloadError as e:
        logger.exception("yt-dlp error")
        await query.edit_message_text(
            f"❌ خطای دانلود:\n`{str(e)[:300]}`",
            parse_mode="Markdown",
        )
        context.user_data.clear()
    except Exception as e:
        logger.exception("general error")
        await query.edit_message_text(f"❌ خطای غیرمنتظره: {str(e)[:200]}")
        context.user_data.clear()


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ OK")


# ---------- اجرا ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(MessageHandler(filters.Regex("^📥 دانلود یوتیوب$"), youtube_btn))
    app.add_handler(MessageHandler(filters.Regex("^📥 دانلود اینستاگرام$"), instagram_btn))
    app.add_handler(CallbackQueryHandler(quality_selected, pattern=r"^q\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    if RENDER_URL:
        logger.info("Starting webhook mode...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{RENDER_URL}/{BOT_TOKEN}",
            drop_pending_updates=True,
        )
    else:
        logger.info("Starting polling mode...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

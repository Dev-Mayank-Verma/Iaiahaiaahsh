"""
main.py — entry point.

Chalane ke liye:
    pip install -r requirements.txt
    cp .env.example .env      # phir .env me BOT_TOKEN daalo
    python main.py

Testing (bina API ke):
    .env me API_MOCK=1 rakho — dummy data se poora bot chal jaayega.
"""
from __future__ import annotations

import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import handlers
from api import ScholarVerseAPI
from branding import BRAND
from config import settings
from downloader import ffmpeg_available
from store import EnrollmentStore

log = logging.getLogger("scholarverse")


# ---------------------------------------------------------------------------
async def post_init(app: Application) -> None:
    api: ScholarVerseAPI = app.bot_data["api"]
    await api.start()

    await app.bot.set_my_commands([
        BotCommand("start", "Main menu"),
        BotCommand("batches", "Batch list"),
        BotCommand("help", "Madad"),
        BotCommand("about", f"{BRAND} ke baare me"),
        BotCommand("cancel", "Chal raha download rok do"),
        BotCommand("id", "Meri Telegram ID"),
    ])

    log.info("✅ %s bot ready", BRAND)
    log.info("   API  : %s", settings.api_root)
    log.info("   Mock : %s", "ON (dummy data)" if settings.api_mock else "OFF")
    log.info("   Lectures: OFF (maintenance) · sirf Notes + DPP")
    if not ffmpeg_available():
        log.info("   ffmpeg nahi mila — PDF download ke liye zaroori nahi hai.")


async def post_shutdown(app: Application) -> None:
    api: ScholarVerseAPI | None = app.bot_data.get("api")
    if api:
        await api.close()
    log.info("Bot band ho gaya.")


# ---------------------------------------------------------------------------
def build_app() -> Application:
    app = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(True)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(600)      # bade file upload ke liye
        .pool_timeout(30)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.bot_data["api"] = ScholarVerseAPI(settings)
    app.bot_data["store"] = EnrollmentStore()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("about", handlers.cmd_about))
    app.add_handler(CommandHandler("id", handlers.cmd_id))
    app.add_handler(CommandHandler("cancel", handlers.cmd_cancel))
    app.add_handler(CommandHandler("batches", handlers.cmd_batches))

    app.add_handler(CallbackQueryHandler(handlers.on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    app.add_error_handler(handlers.on_error)
    return app


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not settings.bot_token:
        sys.exit(
            "❌ BOT_TOKEN set nahi hai.\n"
            "   .env file banao aur usme BOT_TOKEN=<token> daalo.\n"
            "   Token @BotFather se milega."
        )

    settings.ensure_dirs()
    build_app().run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()

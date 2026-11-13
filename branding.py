"""
branding.py — TheScholarVerse.In ki saari branding ek jagah.

Har message, har caption, har button isi file se aata hai. Naam badalna ho to
sirf .env me BRAND_NAME change karo, ya yahan ke defaults.
"""
from __future__ import annotations

from config import Settings

SETTINGS = Settings()

BRAND = SETTINGS.brand_name
WEBSITE = SETTINGS.brand_url
CHANNEL = SETTINGS.brand_channel
SUPPORT = SETTINGS.brand_support
TAGLINE = SETTINGS.brand_tagline

DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━"
THIN = "──────────────────────"

# ---------------------------------------------------------------------------
# Boilerplate
# ---------------------------------------------------------------------------
WELCOME = (
    f"🎓 <b>{BRAND}</b>\n"
    f"<i>{TAGLINE}</i>\n"
    f"{DIVIDER}\n\n"
    "Namaste {name}! 👋\n\n"
    "Main <b>TheScholarVerse</b> ka content bot hoon. Yahan se tum apna "
    "<b>batch</b> chuno, subject → chapter → lecture/notes tak jao, aur seedha "
    "Telegram me hi video ya PDF le lo.\n\n"
    "<b>Kaise use karein?</b>\n"
    "1️⃣ <b>📚 Batch chuno</b> dabao\n"
    "2️⃣ Subject aur chapter select karo\n"
    "3️⃣ Video ya PDF pe click karo — file yahin aa jaayegi ✅\n\n"
    f"{THIN}\n"
    f"🌐 {WEBSITE}\n"
    f"📢 {CHANNEL}\n"
)

WELCOME_SHORT = (
    f"🎓 <b>{BRAND}</b>\n"
    f"<i>{TAGLINE}</i>\n"
    f"{DIVIDER}\n\n"
    "Namaste {name}! 👋\n\n"
    "Batch chuno → subject → chapter → Notes/DPP → PDF seedha yahin.\n\n"
    f"{THIN}\n"
    f"🌐 {WEBSITE}  ·  📢 {CHANNEL}"
)

MAINTENANCE = (
    f"🔧 <b>Lectures — Under Maintenance</b>\n"
    f"{DIVIDER}\n\n"
    "Video lectures abhi temporarily band hain. Team ispe kaam kar rahi hai.\n\n"
    "✅ Tab tak <b>Notes</b> aur <b>DPP</b> poore available hain — wo download kar lo.\n\n"
    f"{THIN}\n"
    f"🎓 <b>{BRAND}</b> • {WEBSITE}"
)

HELP = (
    f"🆘 <b>Help — {BRAND}</b>\n"
    f"{DIVIDER}\n\n"
    "<b>Commands</b>\n"
    "• /start — Main menu\n"
    "• /batches — Batch list\n"
    "• /help — Yeh message\n"
    "• /about — Bot & brand info\n"
    "• /id — Tumhari Telegram ID\n"
    "• /cancel — Chal raha download rok do\n\n"
    "<b>Kya available hai</b>\n"
    "• 📄 Notes — PDF\n"
    "• 📝 DPP — PDF\n"
    "• 🔧 Lectures — abhi maintenance me\n\n"
    f"<b>Size limit:</b> {SETTINGS.max_upload_mb} MB per file. Isse bada "
    "file ho to bot tumhe <b>🔗 Direct link</b> ka option dega.\n\n"
    f"{THIN}\n"
    f"Koi dikkat ho to: {SUPPORT}\n"
)

ABOUT = (
    f"ℹ️ <b>About — {BRAND}</b>\n"
    f"{DIVIDER}\n\n"
    f"<b>{BRAND}</b> ek study platform hai jahan students ko batch-wise "
    "lectures, notes, DPP aur practice material ek jagah milta hai.\n\n"
    "<b>Ye bot kya karta hai</b>\n"
    "• Batch → Subject → Chapter → Notes/DPP — pura navigation\n"
    "• Notes aur DPP seedha PDF me chat me\n"
    "• Live progress bar, speed aur ETA\n"
    "• Bade files ke liye direct-link option\n\n"
    f"🌐 Website: {WEBSITE}\n"
    f"📢 Channel: {CHANNEL}\n"
    f"💬 Support: {SUPPORT}\n\n"
    f"{DIVIDER}\n"
    f"<i>Powered by {BRAND} API</i>\n"
)


# ---------------------------------------------------------------------------
# Chhote builders
# ---------------------------------------------------------------------------
def footer() -> str:
    return f"\n\n{THIN}\n🎓 <b>{BRAND}</b> • {WEBSITE}"


def title_block(emoji: str, heading: str, sub: str = "") -> str:
    text = f"{emoji} <b>{heading}</b>"
    if sub:
        text += f"\n<i>{sub}</i>"
    return f"{text}\n{DIVIDER}\n"


def caption(title: str, meta: str = "") -> str:
    text = f"🎬 <b>{title}</b>"
    if meta:
        text += f"\n{meta}"
    return text + footer()


def error_block(message: str) -> str:
    return (
        f"⚠️ <b>Oops!</b>\n{DIVIDER}\n{message}\n\n"
        f"Try: /start\n💬 {SUPPORT}"
    )


def progress_text(stage: str, bar: str, pct: float, detail: str) -> str:
    return (
        f"⬇️ <b>{stage}</b>\n"
        f"<code>{bar}</code> {pct:5.1f}%\n"
        f"{detail}\n"
        f"{THIN}\n"
        f"🎓 {BRAND}"
    )

"""
handlers.py — pura navigation + download + upload logic.

Callback data scheme (keyboards.py dekho):
  m            main menu
  b:<page>     batch page
  b:s:<pg>:<i> batch select
  sp:<pg>      subject page          s:<pg>:<i> subject select
  tp:<pg>      topic page            t:<pg>:<i> topic select
  ct:<key>     content type filter
  cp:<pg>      content page          c:<pg>:<i> content select
  dl / lnk / cmp / abort / clr / bk:*
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from api import APIError, Batch, Item, ScholarVerseAPI
from branding import (
    ABOUT, BRAND, CHANNEL, DIVIDER, HELP, MAINTENANCE, MY_BATCHES_EMPTY,
    SUPPORT, TESTS_MAINTENANCE, THIN, WEBSITE, WELCOME, WELCOME_SHORT,
    caption as brand_caption, error_block, progress_text, title_block,
)
from config import settings
from downloader import Cancelled, DownloadError, ProgressInfo, download
from keyboards import (
    back_batch_kb, back_menu_kb, batch_home_kb, batch_items_kb, batches_kb,
    big_file_kb, cancel_kb, content_types_kb, item_kb, list_kb, main_menu,
    my_batches_kb,
)
from utils import clip, esc, human_bytes, human_time, page_slice, progress_bar

log = logging.getLogger(__name__)

TYPE_LABEL = {"videos": "🎬 Videos", "notes": "📄 Notes", "dpp": "📝 DPP"}
sem = asyncio.Semaphore(settings.concurrent_downloads)


# ===========================================================================
#  Guards
# ===========================================================================
async def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if settings.allowed_user_ids and user.id not in settings.allowed_user_ids:
        if update.effective_message:
            await update.effective_message.reply_text(
                f"🔒 <b>{BRAND}</b>\n{THIN}\nYe bot private hai.\n"
                f"Access ke liye: {SUPPORT}\n\nTumhari ID: <code>{user.id}</code>",
                parse_mode=ParseMode.HTML,
            )
        return False
    return True


async def _force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    channel = settings.force_join_channel
    if not channel or not update.effective_message:
        return True
    try:
        member = await context.bot.get_chat_member(channel, update.effective_user.id)
        if member.status in {"left", "kicked"}:
            raise ValueError
        return True
    except (TelegramError, ValueError):
        await update.effective_message.reply_text(
            f"📢 <b>Pehle channel join karo</b>\n{DIVIDER}\n"
            f"Bot use karne ke liye {CHANNEL} join karna zaroori hai.\n\n"
            f"Join karke /start dobara bhejo.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return False


def api_of(context: ContextTypes.DEFAULT_TYPE) -> ScholarVerseAPI:
    return context.application.bot_data["api"]


def store_of(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data["store"]


# ===========================================================================
#  /start  /help  /about  /id  /cancel
# ===========================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update, context):
        return
    if not await _force_join(update, context):
        return
    context.user_data.clear()
    name = esc(update.effective_user.first_name or "dost")

    logo = settings.logo_path
    if logo is not None:
        try:
            with open(logo, "rb") as fh:
                await update.message.reply_photo(
                    fh,
                    caption=WELCOME_SHORT.format(name=name)[:1024],
                    parse_mode=ParseMode.HTML,
                    reply_markup=main_menu(),
                )
            return
        except TelegramError as exc:
            log.warning("logo send failed: %s", exc)

    await update.message.reply_text(
        WELCOME.format(name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update, context):
        return
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update, context):
        return
    await update.message.reply_text(ABOUT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🆔 <b>Tumhari Telegram ID</b>\n{THIN}\n<code>{update.effective_user.id}</code>\n\n"
        f"Ise <code>ALLOWED_USER_IDS</code> me daal sakte ho.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ev: asyncio.Event | None = context.user_data.get("cancel")
    if ev:
        ev.set()
        context.user_data.pop("cancel", None)
        await update.message.reply_text("🛑 Download cancel kar diya.")
    else:
        await update.message.reply_text("Kuch chal hi nahi raha tha 🙂")


async def cmd_batches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update, context):
        return
    msg = await update.message.reply_text("⏳ Batches load ho rahe hain…")
    await _show_batches(msg, context, page=0, edit=False)


# ===========================================================================
#  Text handler (search)
# ===========================================================================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allowed(update, context):
        return
    if context.user_data.get("awaiting") != "search":
        await update.message.reply_text(
            "Neeche ke buttons use karo 👇", reply_markup=main_menu()
        )
        return
    context.user_data.pop("awaiting", None)
    query = (update.message.text or "").strip()
    if len(query) < 2:
        await update.message.reply_text("Kam se kam 2 letters likho.")
        return

    msg = await update.message.reply_text(f"🔎 <b>Searching:</b> {esc(query)}", parse_mode=ParseMode.HTML)
    api = api_of(context)
    try:
        batches, pages, _ = await api.search_batches(query, 1)
    except APIError as exc:
        await msg.edit_text(error_block(esc(str(exc))), parse_mode=ParseMode.HTML, reply_markup=main_menu())
        return

    if not batches:
        await msg.edit_text(
            title_block("😕", "Kuch nahi mila", f"“{esc(query)}” ke liye koi batch nahi."),
            parse_mode=ParseMode.HTML, reply_markup=main_menu(),
        )
        return

    context.user_data.update(
        batches=batches, batch_page=0, batch_pages=pages,
        batch_query=query, batch_mode="search",
    )
    text = title_block("🔎", f"“{esc(query)}” ke results", f"{len(batches)} batch mile")
    await _safe_edit(
        msg,
        text + "Neeche se batch chuno 👇",
        _merge(batch_items_kb(batches, 0), batches_kb(0, pages)),
        edit=True,
    )


def _merge(top, bottom):
    from telegram import InlineKeyboardMarkup

    return InlineKeyboardMarkup(list(top.inline_keyboard) + list(bottom.inline_keyboard))


# ===========================================================================
#  Batches
# ===========================================================================
async def _show_batches(msg, context, page: int, edit: bool = True) -> None:
    api = api_of(context)
    try:
        batches, pages, total = await api.batches(page + 1)
    except APIError as exc:
        await _safe_edit(msg, error_block(esc(str(exc))), main_menu(), edit)
        return

    if not batches:
        await _safe_edit(msg, error_block("Is page pe koi batch nahi mila."), main_menu(), edit)
        return

    context.user_data.update(batches=batches, batch_page=page, batch_pages=pages, batch_mode="all")
    text = (
        title_block("📚", "Batch chuno", f"Page {page + 1} / {pages}  ·  {total:,} batches")
        + "Neeche se apna batch select karo 👇"
    )
    kb = _merge(batch_items_kb(batches, page), batches_kb(page, pages))
    await _safe_edit(msg, text, kb, edit)


async def _select_batch(query, context, page: int, idx: int) -> None:
    batches = context.user_data.get("batches") or []
    if idx >= len(batches):
        await query.answer("List purani ho gayi, dobara try karo.", show_alert=True)
        return
    await query.answer(f"{batches[idx].name} ✅")
    await _show_batch_home(query, context, batches[idx])


# ---------------------------------------------------------------------------
#  Batch home — Subjects / Tests / Enroll
# ---------------------------------------------------------------------------
async def _show_batch_home(query, context, batch: Batch | None = None) -> None:
    if batch is not None:
        context.user_data["batch"] = batch
    b: Batch | None = context.user_data.get("batch")
    if b is None:
        await _edit(query, error_block("Pehle koi batch chuno."), main_menu())
        return

    enrolled = await store_of(context).has(query.from_user.id, b.id)
    lines = []
    if b.by:
        lines.append(f"<i>{esc(b.by)}</i>")
    meta = []
    if b.language:
        meta.append(f"🗣 {esc(b.language)}")
    if b.price and b.price not in ("0", ""):
        meta.append(f"💰 ₹{esc(b.price)}")
    if meta:
        lines.append(" · ".join(meta))
    if enrolled:
        lines.append("📌 <b>Enrolled</b> — ⭐ Mere Batches me milega")

    text = (
        f"📚 <b>{esc(b.name)}</b>\n{DIVIDER}\n"
        + ("\n".join(lines) + "\n" if lines else "")
        + "\nKya karna hai?\n\n"
        + f"{THIN}\n🎓 <b>{BRAND}</b> • {WEBSITE}"
    )
    await _edit(query, text, batch_home_kb(enrolled))


async def _open_subjects(query, context) -> None:
    batch: Batch | None = context.user_data.get("batch")
    if batch is None:
        await _edit(query, error_block("Pehle koi batch chuno."), main_menu())
        return
    await _edit(query, title_block("⏳", esc(batch.name), "Subjects load ho rahe hain…"))
    api = api_of(context)
    try:
        subjects = await api.subjects(batch.id)
    except APIError as exc:
        await _edit(query, error_block(esc(str(exc))), back_batch_kb())
        return
    if not subjects:
        await _edit(query, error_block("Is batch me koi subject nahi mila."), back_batch_kb())
        return
    context.user_data.update(subjects=subjects, subject_page=0)
    await _render_subjects(query, context, 0)


async def _toggle_enroll(query, context) -> None:
    b: Batch | None = context.user_data.get("batch")
    if b is None:
        await query.answer("Pehle batch chuno.", show_alert=True)
        return
    now = await store_of(context).toggle(
        query.from_user.id,
        {"id": b.id, "name": b.name, "by": b.by, "language": b.language, "price": b.price},
    )
    await query.answer("⭐ Enroll ho gaya!" if now else "Enroll hata diya")
    await _show_batch_home(query, context)


# ---------------------------------------------------------------------------
#  Mere Batches (enrolled)
# ---------------------------------------------------------------------------
async def _show_my_batches(query, context, page: int = 0) -> None:
    rows = await store_of(context).list_for(query.from_user.id)
    context.user_data["my_batches"] = rows
    if not rows:
        await _edit(query, MY_BATCHES_EMPTY, main_menu())
        return

    per = settings.page_size
    total_pages = max(1, (len(rows) + per - 1) // per)
    page = max(0, min(page, total_pages - 1))
    chunk = page_slice(rows, page, per)
    labels = []
    for r in chunk:
        extra = f"  ·  🗣 {r.get('language')}" if r.get("language") else ""
        labels.append(f"⭐ {clip(r.get('name', 'Batch'), 44)}{extra}")

    text = (
        f"⭐ <b>Mere Batches</b>\n{DIVIDER}\n"
        f"{len(rows)} batch enrolled  ·  page {page + 1}/{total_pages}\n\n"
        "Kholne ke liye tap karo 👇\n\n"
        f"{THIN}\n🎓 <b>{BRAND}</b> • {WEBSITE}"
    )
    await _edit(query, text, my_batches_kb(labels, page, total_pages))


async def _open_enrolled(query, context, page: int, idx: int) -> None:
    rows = context.user_data.get("my_batches") or []
    real = page * settings.page_size + idx
    if real >= len(rows):
        await query.answer("List refresh karo.", show_alert=True)
        return
    d = rows[real]
    await query.answer(d.get("name", "")[:40])
    await _show_batch_home(
        query,
        context,
        Batch(
            id=str(d.get("id", "")),
            name=str(d.get("name", "Batch")),
            by=str(d.get("by", "")),
            language=str(d.get("language", "")),
            price=str(d.get("price", "")),
        ),
    )


async def _render_subjects(query, context, page: int) -> None:
    subjects = context.user_data.get("subjects") or []
    batch = context.user_data.get("batch")
    per = settings.page_size
    total_pages = max(1, (len(subjects) + per - 1) // per)
    chunk = page_slice(subjects, page, per)

    labels = []
    for s in chunk:
        bits = []
        if s.videos:
            bits.append(f"🎬 {s.videos}")
        if s.notes:
            bits.append(f"📄 {s.notes}")
        meta = f"  ·  {' · '.join(bits)}" if bits else ""
        labels.append(f"{s.name}{meta}")

    text = (
        title_block("🧪", f"{esc(batch.name) if batch else 'Batch'} — Subjects",
                    f"{len(subjects)} subjects")
        + "Subject chuno 👇"
    )
    await _edit(query, text, list_kb(labels, "s", page, total_pages, back="bk:home"))


async def _select_subject(query, context, page: int, idx: int) -> None:
    subjects = context.user_data.get("subjects") or []
    real = page * settings.page_size + idx
    if real >= len(subjects):
        await query.answer("List refresh karo.", show_alert=True)
        return
    subject = subjects[real]
    context.user_data.update(subject=subject, topic_page=0)
    await query.answer(subject.name)

    await _edit(query, title_block("⏳", esc(subject.name), "Topics load ho rahe hain…"))
    api = api_of(context)
    batch = context.user_data["batch"]
    try:
        topics, pages = await api.topics(batch.id, subject.id, 1)
    except APIError as exc:
        await _edit(query, error_block(esc(str(exc))), back_menu_kb("bk:subjects"))
        return
    if not topics:
        await _edit(query, error_block("Is subject me koi topic nahi mila."), back_menu_kb("bk:subjects"))
        return
    context.user_data.update(topics=topics, topic_pages=pages, topic_page=0)
    await _render_topics(query, context, 0)


# ===========================================================================
#  Topics
# ===========================================================================
async def _render_topics(query, context, page: int) -> None:
    api = api_of(context)
    batch = context.user_data["batch"]
    subject = context.user_data["subject"]
    pages = context.user_data.get("topic_pages", 1)

    if page != context.user_data.get("topic_page"):
        try:
            topics, pages = await api.topics(batch.id, subject.id, page + 1)
            context.user_data.update(topics=topics, topic_pages=pages, topic_page=page)
        except APIError as exc:
            await _edit(query, error_block(esc(str(exc))), back_menu_kb("bk:subjects"))
            return

    topics = context.user_data.get("topics") or []
    labels = []
    for t in topics:
        bits = []
        if t.videos:
            bits.append(f"🎬 {t.videos}")
        if t.notes:
            bits.append(f"📄 {t.notes}")
        meta = f"  ·  {' · '.join(bits)}" if bits else ""
        labels.append(f"{t.name}{meta}")

    text = (
        title_block("📖", esc(subject.name), f"Page {page + 1} / {pages}")
        + "Chapter / topic chuno 👇"
    )
    await _edit(query, text, list_kb(labels, "t", page, pages, back="bk:subjects"))


async def _select_topic(query, context, page: int, idx: int) -> None:
    topics = context.user_data.get("topics") or []
    if idx >= len(topics):
        await query.answer("Refresh karo.", show_alert=True)
        return
    topic = topics[idx]
    default_type = "notes"
    context.user_data.update(topic=topic, ctype=default_type, item_page=0)
    await query.answer(topic.name)
    await _edit(
        query,
        title_block("📂", esc(topic.name), "Kya dekhna hai?"),
        content_types_kb(default_type),
    )


# ===========================================================================
#  Contents
# ===========================================================================
async def _render_contents(query, context, ctype: str, page: int = 0) -> None:
    if ctype == "videos":
        await _edit(query, MAINTENANCE, content_types_kb(context.user_data.get("ctype", "notes")))
        return

    api = api_of(context)
    batch = context.user_data["batch"]
    subject = context.user_data["subject"]
    topic = context.user_data["topic"]
    context.user_data["ctype"] = ctype

    await _edit(query, title_block("⏳", esc(topic.name), f"{TYPE_LABEL.get(ctype, ctype)} load ho rahe hain…"))
    try:
        items, pages = await api.contents(batch.id, subject.id, topic.id, ctype, page + 1)
    except APIError as exc:
        await _edit(query, error_block(esc(str(exc))), content_types_kb(ctype))
        return

    if not items:
        await _edit(
            query,
            title_block("📭", "Yahan kuch nahi hai", f"{TYPE_LABEL.get(ctype, ctype)} me koi item nahi mila."),
            content_types_kb(ctype),
        )
        return

    context.user_data.update(items=items, item_pages=pages, item_page=page)

    labels = []
    for it in items:
        if it.kind == "video":
            dur = f" · {human_time(it.duration)}" if it.duration else ""
            labels.append(f"🎬 {clip(it.title, 40)}{dur}")
        else:
            labels.append(f"📄 {clip(it.title, 46)}")

    text = (
        title_block("📂", esc(topic.name),
                    f"{TYPE_LABEL.get(ctype, ctype)}  ·  page {page + 1}/{pages}  ·  {len(items)} items")
        + "Ek item chuno 👇"
    )
    await _edit(query, text, list_kb(labels, "c", page, pages, back="bk:topics"))


async def _select_item(query, context, page: int, idx: int) -> None:
    items = context.user_data.get("items") or []
    if idx >= len(items):
        await query.answer("Refresh karo.", show_alert=True)
        return
    item = items[idx]
    context.user_data["item"] = item
    await query.answer("Selected")

    kind = "🎬 Video" if item.kind == "video" else "📄 PDF"
    bits = [f"<b>Type:</b> {kind}"]
    if item.date:
        bits.append(f"<b>Date:</b> {item.date}")
    if item.duration:
        bits.append(f"<b>Duration:</b> {human_time(item.duration)}")

    text = (
        f"🎯 <b>{esc(clip(item.title, 120))}</b>\n"
        f"{DIVIDER}\n" + "\n".join(bits) + "\n\n"
        "⬇️ <b>Download</b> dabao — file seedha yahin aa jaayegi."
        f"\n\n{THIN}\n🎓 <b>{BRAND}</b> • {WEBSITE}"
    )
    await _edit(query, text, item_kb())


# ===========================================================================
#  Download + upload
# ===========================================================================
async def _do_download(query, context) -> None:
    item: Item | None = context.user_data.get("item")
    if item is None:
        await query.answer("Pehle koi item chuno.", show_alert=True)
        return

    api = api_of(context)
    batch = context.user_data["batch"]
    subject = context.user_data["subject"]

    await query.answer("Download shuru…")
    await _edit(query, title_block("🔗", "Link resolve ho raha hai…", esc(clip(item.title, 70))))

    try:
        resolved = await api.resolve(batch.id, subject.id, item)
    except APIError as exc:
        await _edit(query, error_block(esc(str(exc))), item_kb())
        return

    context.user_data["resolved"] = resolved
    cancel = asyncio.Event()
    context.user_data["cancel"] = cancel

    reporter = ProgressReporter(query, clip(item.title, 60))
    dest_dir = settings.work_dir / str(query.from_user.id)

    async with sem:
        try:
            path = await download(resolved, dest_dir, progress=reporter.update, cancel=cancel)
        except Cancelled:
            await _edit(query, title_block("🛑", "Download cancel ho gaya", ""), item_kb())
            return
        except DownloadError as exc:
            await _edit(query, error_block(esc(str(exc))), item_kb())
            return
        finally:
            context.user_data.pop("cancel", None)

    await reporter.finish("Upload ho raha hai…")
    await _deliver(query, context, path, resolved.kind)


async def _deliver(query, context, path: Path, kind: str) -> None:
    item: Item = context.user_data["item"]
    size = path.stat().st_size
    limit = settings.max_upload_mb * 1024 * 1024

    if size > limit:
        context.user_data["file"] = str(path)
        await _edit(
            query,
            f"⚠️ <b>File bada hai</b>\n{DIVIDER}\n"
            f"<b>Size:</b> {human_bytes(size)}\n"
            f"<b>Telegram limit:</b> {settings.max_upload_mb} MB\n\n"
            f"Compress karke bhejun, ya direct link dun?\n\n{THIN}\n🎓 <b>{BRAND}</b>",
            big_file_kb(),
        )
        return

    meta = " · ".join(
        x for x in [
            f"📅 {item.date}" if item.date else "",
            f"⏱ {human_time(item.duration)}" if item.duration else "",
            f"💾 {human_bytes(size)}",
        ] if x
    )
    cap = brand_caption(esc(clip(item.title, 200)), meta)[:1024]

    await query.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    try:
        with open(path, "rb") as fh:
            await query.message.reply_document(
                fh, caption=cap, filename=path.name, parse_mode=ParseMode.HTML,
            )
    except Forbidden:
        await _edit(query, error_block("Bot ko yahan file bhejne ki permission nahi hai."), item_kb())
        return
    except BadRequest as exc:
        await _edit(query, error_block(f"Upload fail hua: {esc(str(exc))}"), item_kb())
        return

    with contextlib.suppress(Exception):
        await query.message.delete()

    if not settings.keep_files:
        with contextlib.suppress(Exception):
            path.unlink(missing_ok=True)


async def _send_link(query, context) -> None:
    resolved = context.user_data.get("resolved")
    if resolved is None:
        item: Item | None = context.user_data.get("item")
        if item is None:
            await query.answer("Pehle download dabao.", show_alert=True)
            return
        await query.answer("Link ban raha hai…")
        api = api_of(context)
        try:
            resolved = await api.resolve(
                context.user_data["batch"].id, context.user_data["subject"].id, item
            )
        except APIError as exc:
            await query.answer(str(exc)[:180], show_alert=True)
            return
        context.user_data["resolved"] = resolved

    await query.answer("Link bhej diya")
    await query.message.reply_text(
        f"🔗 <b>Direct link</b>\n{DIVIDER}\n"
        f"<code>{esc(resolved.url[:3800])}</code>\n\n"
        f"{THIN}\n🎓 <b>{BRAND}</b>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ===========================================================================
#  Progress reporter
# ===========================================================================
class ProgressReporter:
    def __init__(self, query, title: str) -> None:
        self.query = query
        self.title = title
        self._last = 0.0
        self._last_pct = -1.0

    async def update(self, info: ProgressInfo) -> None:
        now = time.time()
        if now - self._last < 2.5 and info.percent < 100:
            return
        self._last = now
        self._last_pct = info.percent

        if info.total and info.total > 1_000_000:  # bytes mode (direct download)
            bar = progress_bar(info.percent)
            detail = (
                f"📦 {human_bytes(info.downloaded)} / {human_bytes(info.total)}\n"
                f"⚡ {human_bytes(info.speed)}/s   ⏳ {human_time(info.eta)}"
            )
        elif info.total:  # seconds mode (ffmpeg)
            bar = progress_bar(info.percent)
            detail = (
                f"⏱ {human_time(info.downloaded)} / {human_time(info.total)}\n"
                f"⏳ {human_time(info.eta)} bacha"
            )
        else:  # duration unknown — indeterminate bar
            bar = progress_bar(50)
            detail = "⏳ Stream process ho raha hai…"
            info = ProgressInfo(**{**info.__dict__, "percent": 50.0})
        await _edit(self.query, progress_text(self.title, bar, info.percent, detail), cancel_kb())

    async def finish(self, text: str) -> None:
        await _edit(self.query, title_block("📤", text, "") + f"🎓 <b>{BRAND}</b>")


# ===========================================================================
#  Edit helpers
# ===========================================================================
async def _edit(query, text: str, kb=None) -> None:
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            log.debug("edit failed: %s", exc)


async def _safe_edit(msg, text: str, kb, edit: bool) -> None:
    try:
        if edit:
            await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                disable_web_page_preview=True)
        else:
            await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                disable_web_page_preview=True)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                 disable_web_page_preview=True)


# ===========================================================================
#  Router
# ===========================================================================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    if not await _allowed(update, context):
        await query.answer()
        return

    data = query.data or ""
    parts = data.split(":")
    head = parts[0]

    try:
        if head == "m":
            await query.answer()
            context.user_data.clear()
            await _edit(query, WELCOME.format(name=esc(query.from_user.first_name or "dost")), main_menu())

        elif head == "b" and len(parts) == 2:          # b:<page>
            await query.answer()
            await _show_batches(query.message, context, int(parts[1]))

        elif head == "b" and parts[1] == "s":          # b:s:<pg>:<i>
            await _select_batch(query, context, int(parts[2]), int(parts[3]))

        elif head == "sp":                             # sp:<page>
            await query.answer()
            await _render_subjects(query, context, int(parts[1]))

        elif head == "s" and len(parts) == 3:          # s:<pg>:<i>
            await _select_subject(query, context, int(parts[1]), int(parts[2]))

        elif head == "tp":                             # tp:<page>
            await query.answer()
            await _render_topics(query, context, int(parts[1]))

        elif head == "t" and len(parts) == 3:          # t:<pg>:<i>
            await _select_topic(query, context, int(parts[1]), int(parts[2]))

        elif head == "ct" and len(parts) > 1 and parts[1] == "locked":
            await query.answer("Lectures under maintenance 🔧", show_alert=True)
            await _edit(query, MAINTENANCE, content_types_kb(context.user_data.get("ctype", "notes")))

        elif head == "ct":
            await query.answer()
            await _render_contents(query, context, parts[1], 0)

        elif head == "cp":
            await query.answer()
            await _render_contents(query, context, context.user_data.get("ctype", "videos"), int(parts[1]))

        elif head == "c" and len(parts) == 3:          # c:<pg>:<i>
            await _select_item(query, context, int(parts[1]), int(parts[2]))

        elif head == "dl":
            await _do_download(query, context)

        elif head == "lnk":
            await _send_link(query, context)

        elif head == "abort":
            ev = context.user_data.get("cancel")
            if ev:
                ev.set()
            await query.answer("Cancel kar diya")

        elif head == "clr":
            await query.answer()
            await _edit(query, title_block("✅", "Theek hai", "Kuch bheja nahi."), item_kb())

        elif head == "my":
            await query.answer()
            await _show_my_batches(query, context, 0)

        elif head == "myp":
            await query.answer()
            await _show_my_batches(query, context, int(parts[1]))

        elif head == "myb":
            await _open_enrolled(query, context, int(parts[1]), int(parts[2]))

        elif head == "subs":
            await query.answer()
            await _open_subjects(query, context)

        elif head == "tests":
            await query.answer("Tests under maintenance 🔧", show_alert=True)
            batch = context.user_data.get("batch")
            enrolled = bool(batch) and await store_of(context).has(query.from_user.id, batch.id)
            await _edit(query, TESTS_MAINTENANCE, batch_home_kb(enrolled))

        elif head == "enr":
            await _toggle_enroll(query, context)

        elif head == "bk":
            await query.answer()
            target = parts[1] if len(parts) > 1 else "topics"
            if target == "home":
                await _show_batch_home(query, context)
            elif target == "subjects":
                await _render_subjects(query, context, context.user_data.get("subject_page", 0))
            elif target == "topics":
                await _render_topics(query, context, context.user_data.get("topic_page", 0))
            elif target == "contents":
                await _render_contents(query, context, context.user_data.get("ctype", "videos"),
                                       context.user_data.get("item_page", 0))

        elif head == "srch":
            await query.answer()
            context.user_data["awaiting"] = "search"
            await _edit(
                query,
                title_block("🔎", "Search", "Batch ka naam type karke bhejo")
                + "Jaise: <i>Arjuna</i>, <i>Udaan</i>, <i>Prayas</i>",
                back_menu_kb(),
            )

        elif head == "about":
            await query.answer()
            await _edit(query, ABOUT, back_menu_kb())

        else:
            await query.answer()

    except Exception:  # pragma: no cover
        log.exception("callback failed: %s", data)
        with contextlib.suppress(Exception):
            await query.answer("Kuch gadbad ho gayi, /start try karo.", show_alert=True)


# ===========================================================================
#  Error handler
# ===========================================================================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        with contextlib.suppress(Exception):
            await update.effective_message.reply_text(
                error_block("Internal error aa gaya. Dobara try karo."),
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )

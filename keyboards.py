from __future__ import annotations

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as KB

from config import settings
from utils import clip


def _grid(rows: list[list[B]]) -> KB:
    return KB(rows)


def main_menu() -> KB:
    return _grid([
        [B("📚 Batch chuno", callback_data="b:0")],
        [B("⭐ Mere Batches", callback_data="my"), B("🔎 Search", callback_data="srch")],
        [B("ℹ️ About", callback_data="about"), B("🌐 Website", url=settings.brand_url)],
        [B("📢 Channel", url=f"https://t.me/{settings.brand_channel.lstrip('@')}")],
    ])


def batch_home_kb(enrolled: bool) -> KB:
    enroll_label = "✅ Enrolled — hatao" if enrolled else "📌 Enroll karo"
    return _grid([
        [B("📖 Subjects", callback_data="subs"), B("🧪 Tests 🔧", callback_data="tests")],
        [B(enroll_label, callback_data="enr")],
        [B("◀️ Back", callback_data="b:0"), B("🏠 Menu", callback_data="m")],
    ])


def batches_kb(page: int, total_pages: int) -> KB:
    rows: list[list[B]] = []
    nav: list[B] = []
    if page > 0:
        nav.append(B("‹ Prev", callback_data=f"b:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(B(f"{page + 1}/{total_pages} ›", callback_data=f"b:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([B("🏠 Main menu", callback_data="m")])
    return _grid(rows)


def batch_items_kb(batches, page: int) -> KB:
    rows = [
        [B(clip(b.name, 48), callback_data=f"b:s:{page}:{i}")]
        for i, b in enumerate(batches)
    ]
    return _grid(rows)


def list_kb(labels, prefix, page, total_pages, back, nav_prefix=None) -> KB:
    nav_prefix = nav_prefix or f"{prefix}p"
    rows: list[list[B]] = []
    for i, label in enumerate(labels):
        rows.append([B(clip(label, 52), callback_data=f"{prefix}:{page}:{i}")])
    nav: list[B] = []
    if page > 0:
        nav.append(B("‹ Prev", callback_data=f"{nav_prefix}:{page - 1}"))
    if page + 1 < total_pages:
        nav.append(B(f"{page + 1}/{total_pages} ›", callback_data=f"{nav_prefix}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([B("◀️ Back", callback_data=back), B("🏠 Menu", callback_data="m")])
    return _grid(rows)


def content_types_kb(active: str) -> KB:
    def mark(key: str, label: str) -> B:
        return B(("✅ " if active == key else "") + label, callback_data=f"ct:{key}")

    return _grid([
        [mark("notes", "📄 Notes"), mark("dpp", "📝 DPP")],
        [B("🔧 Lectures — maintenance", callback_data="ct:locked")],
        [B("◀️ Back", callback_data="bk:topics"), B("🏠 Menu", callback_data="m")],
    ])


def my_batches_kb(labels, page, total_pages) -> KB:
    return list_kb(labels, "myb", page, total_pages, back="m", nav_prefix="myp")


def item_kb(has_link: bool = True) -> KB:
    rows = [[B("⬇️ Download", callback_data="dl")]]
    if has_link:
        rows.append([B("🔗 Direct link", callback_data="lnk")])
    rows.append([B("◀️ Back", callback_data="bk:contents"), B("🏠 Menu", callback_data="m")])
    return _grid(rows)


def back_batch_kb() -> KB:
    return _grid([[B("◀️ Batch", callback_data="bk:home"), B("🏠 Menu", callback_data="m")]])


def big_file_kb() -> KB:
    return _grid([
        [B("🔗 Direct link do", callback_data="lnk")],
        [B("❌ Cancel", callback_data="clr")],
    ])


def cancel_kb() -> KB:
    return _grid([[B("❌ Cancel download", callback_data="abort")]])


def back_menu_kb(back: str = "m") -> KB:
    return _grid([[B("◀️ Back", callback_data=back), B("🏠 Menu", callback_data="m")]])

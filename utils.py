from __future__ import annotations

import html
import re
import time
from pathlib import Path
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WS = re.compile(r"\s+")


def human_bytes(num) -> str:
    if not num or num < 0:
        return "—"
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < step or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} TB"


def human_time(seconds) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def progress_bar(pct: float, width: int = 14) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100.0))
    return "▰" * filled + "▱" * (width - filled)


def esc(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def clip(text: str, limit: int = 60) -> str:
    text = _WS.sub(" ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def safe_filename(name: str, fallback: str = "file", max_len: int = 90) -> str:
    name = _BAD_CHARS.sub("_", str(name or "")).strip().strip(".")
    name = _WS.sub(" ", name)
    if not name:
        name = fallback
    if len(name) > max_len:
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 5:
            name = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            name = name[:max_len]
    return name


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    for i in range(1, 1000):
        candidate = directory / (f"{stem} ({i}).{ext}" if ext else f"{stem} ({i})")
        if not candidate.exists():
            return candidate
    return directory / f"{int(time.time())}-{filename}"


def page_slice(items: Sequence[T], page: int, per_page: int) -> list[T]:
    start = max(0, page) * per_page
    return list(items[start : start + per_page])


def chunked(seq: Iterable[T], size: int) -> Iterable[list[T]]:
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def parse_duration(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    parts = str(value).split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    seconds = 0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds

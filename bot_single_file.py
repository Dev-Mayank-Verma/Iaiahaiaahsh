"""
TheScholarVerse.In — Telegram Bot  (single-file version)
========================================================
Poora bot ek hi file me. GitHub web editor me "Create new file" karke
ye paste kar do — bas.

Chalane ke liye:
    pip install python-telegram-bot httpx python-dotenv
    BOT_TOKEN=xxx API_MOCK=1 python bot_single_file.py

Ya Docker:
    FROM python:3.12-slim
    WORKDIR /app
    COPY bot_single_file.py .
    RUN pip install --no-cache-dir python-telegram-bot httpx python-dotenv
    CMD ["python", "bot_single_file.py"]
"""


# ======================================================================
#  config.py
# ======================================================================

"""
config.py — Bot ki saari settings ek jagah.

⚠️  YAHI FILE EDIT KARNI HAI jab apni API daalni ho.
    Sirf do cheezein badalni hoti hain:
      1. .env me API_BASE_URL  (ya API_BASE_URL yahan default)
      2. Neeche ENDPOINTS dict ke paths
    Baaki kisi bhi file ko chhune ki zaroorat nahi.
"""

import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional — bina python-dotenv ke bhi bot chalega
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------
def _str(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _int(key: str, default: int) -> int:
    try:
        return int(_str(key) or default)
    except ValueError:
        return default


def _bool(key: str, default: bool = False) -> bool:
    raw = _str(key).lower()
    return raw in {"1", "true", "yes", "y", "on"} if raw else default


def _id_set(key: str) -> frozenset[int]:
    raw = _str(key)
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


# ===========================================================================
#  🔴 ENDPOINTS — apne API ke hisaab se yahan path badlo
#     {batch_id} {subject_id} {topic_id} {item_id} auto-fill honge.
#     Query params (page, ContentType etc.) api.py khud add karta hai.
# ===========================================================================
ENDPOINTS: dict[str, str] = {
    "batches":    "/AllBatches",     # ?page=1                -> batch list
    "search":     "/searchBatch",    # ?name=&page=1          -> batch search
    "subjects":   "/BatchInfo",      # ?BatchId=&Type=details -> data.subjects[]
    "topics":     "/SubjectInfo",    # ?BatchId=&SubjectId=&page=1
    "contents":   "/TopicInfo",      # ?BatchId=&SubjectId=&TopicId=&ContentType=&page=1
    "pdf":        "/GetPdf",         # ?BatchId=&SubjectId=&PdfId=&AttachmentId=
}

# ContentType values jo tumhari API accept karti hai
# (lectures is build me nahi hain — sirf notes + DPP)
CONTENT_TYPES: dict[str, str] = {
    "notes": "notes",
    "dpp": "DppNotes",
}


@dataclass(frozen=True)
class Settings:
    # ---- Telegram ----
    bot_token: str = _str("BOT_TOKEN")
    allowed_user_ids: frozenset[int] = _id_set("ALLOWED_USER_IDS")  # khaali = sab allowed
    force_join_channel: str = _str("FORCE_JOIN_CHANNEL")            # e.g. @TheScholarVerse

    # ---- API ----
    api_base_url: str = _str("API_BASE_URL", "https://thescholarverse.in")
    api_prefix: str = _str("API_PREFIX", "/api")
    api_key: str = _str("API_KEY")
    api_key_header: str = _str("API_KEY_HEADER", "X-API-Key")
    api_referer: str = _str("API_REFERER", "https://thescholarverse.in/")
    api_timeout: int = _int("API_TIMEOUT", 40)
    api_cache_ttl: int = _int("API_CACHE_TTL", 300)
    api_mock: bool = _bool("API_MOCK", False)   # 1 = dummy data, API ke bina UI test

    # ---- Branding ----
    brand_name: str = _str("BRAND_NAME", "TheScholarVerse.In")
    brand_url: str = _str("BRAND_URL", "https://thescholarverse.in")
    brand_channel: str = _str("BRAND_CHANNEL", "@TheScholarVerse")
    brand_support: str = _str("BRAND_SUPPORT", "@TheScholarVerseSupport")
    brand_tagline: str = _str("BRAND_TAGLINE", "Padho. Download karo. Aage badho.")
    brand_logo: str = _str("BRAND_LOGO", "assets/logo.png")


    # ---- Download / upload ----
    work_dir: Path = Path(_str("WORK_DIR", "/tmp/scholarverse"))
    max_upload_mb: int = _int("MAX_UPLOAD_MB", 50)    # Telegram Bot API limit
    max_file_mb: int = _int("MAX_FILE_MB", 2000)
    concurrent_downloads: int = _int("CONCURRENT_DOWNLOADS", 3)
    ffmpeg_bin: str = _str("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin: str = _str("FFPROBE_BIN", "ffprobe")
    keep_files: bool = _bool("KEEP_FILES", False)

    # ---- UI ----
    page_size: int = _int("PAGE_SIZE", 8)
    log_level: str = _str("LOG_LEVEL", "INFO")

    # ------------------------------------------------------------------
    @property
    def api_root(self) -> str:
        return f"{self.api_base_url.rstrip('/')}/{self.api_prefix.strip('/')}"

    def url(self, name: str, **kwargs: str) -> str:
        path = ENDPOINTS[name].format(**kwargs)
        return f"{self.api_root}/{path.lstrip('/')}"

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @property
    def logo_path(self) -> Path | None:
        if not self.brand_logo:
            return None
        p = Path(self.brand_logo)
        if not p.is_absolute():
            p = Path(__file__).resolve().parent / p
        return p if p.exists() else None


settings = Settings()

# ======================================================================
#  utils.py
# ======================================================================

"""utils.py — chhote helpers: formatting, progress bar, safe filenames."""

import html
import re
import time
from pathlib import Path
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WS = re.compile(r"\s+")


def human_bytes(num: float | int | None) -> str:
    if not num or num < 0:
        return "—"
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < step or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} TB"


def human_time(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN guard
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
    """HTML parse mode ke liye escape."""
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
    buf: list[T] = []
    for item in seq:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def parse_duration(value: str | int | None) -> int | None:
    """'01:53:18' / '12:30' / 6789  ->  seconds"""
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

# ======================================================================
#  branding.py
# ======================================================================

"""
branding.py — TheScholarVerse.In ki saari branding ek jagah.

Har message, har caption, har button isi file se aata hai. Naam badalna ho to
sirf .env me BRAND_NAME change karo, ya yahan ke defaults.
"""


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
    "Batch chuno → subject → chapter → Notes/DPP → PDF seedha yahin.\n"
    "Pasand ka batch <b>📌 Enroll</b> kar lo, phir <b>⭐ Mere Batches</b> me milega.\n\n"
    f"{THIN}\n"
    f"🌐 {WEBSITE}  ·  📢 {CHANNEL}"
)

TESTS_MAINTENANCE = (
    f"🧪 <b>Tests — Under Maintenance</b>\n"
    f"{DIVIDER}\n\n"
    "Is batch ke test series abhi ban rahe hain. Jald aa rahe hain. 🔧\n\n"
    "✅ Tab tak <b>Notes</b> aur <b>DPP</b> se practice karo.\n\n"
    f"{THIN}\n"
    f"🎓 <b>{BRAND}</b> • {WEBSITE}"
)

MY_BATCHES_EMPTY = (
    f"⭐ <b>Mere Batches</b>\n"
    f"{DIVIDER}\n\n"
    "Abhi koi batch enroll nahi kiya hai.\n\n"
    "Kisi bhi batch ko khol ke <b>📌 Enroll</b> dabao — wo yahan save ho jaayega, "
    "phir har baar dhundna nahi padega.\n\n"
    f"{THIN}\n"
    f"🎓 <b>{BRAND}</b>"
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

# ======================================================================
#  store.py
# ======================================================================

"""
store.py — Enrolled batches.

Database ki zaroorat nahi — ek JSON file me save hota hai (WORK_DIR me).
Bot restart hone pe bhi data bacha rehta hai.

File format:
{
  "123456789": [
    {"id": "...", "name": "...", "by": "...", "language": "...", "price": "..."}
  ]
}
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path


log = logging.getLogger(__name__)

MAX_PER_USER = 60


class EnrollmentStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.work_dir / "enrollments.json")
        self._lock = asyncio.Lock()
        self._data: dict[str, list[dict]] = {}
        self._loaded = False

    # ---------------- internals ----------------
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self.path.read_text("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._data = {
                    str(k): [b for b in v if isinstance(b, dict)]
                    for k, v in data.items()
                    if isinstance(v, list)
                }
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("enrollments.json padha nahi gaya (%s) — khaali se shuru", exc)
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)          # atomic — file kabhi aadhi nahi likhti
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ---------------- public API ----------------
    async def list_for(self, user_id: int) -> list[dict]:
        async with self._lock:
            self._load()
            return list(self._data.get(str(user_id), []))

    async def has(self, user_id: int, batch_id: str) -> bool:
        return any(b.get("id") == batch_id for b in await self.list_for(user_id))

    async def add(self, user_id: int, batch: dict) -> bool:
        """True = naya enroll hua, False = pehle se tha."""
        async with self._lock:
            self._load()
            key = str(user_id)
            rows = self._data.setdefault(key, [])
            if any(b.get("id") == batch.get("id") for b in rows):
                return False
            rows.insert(0, {
                "id": str(batch.get("id", "")),
                "name": str(batch.get("name", "")),
                "by": str(batch.get("by", "")),
                "language": str(batch.get("language", "")),
                "price": str(batch.get("price", "")),
            })
            del rows[MAX_PER_USER:]
            self._save()
            return True

    async def remove(self, user_id: int, batch_id: str) -> bool:
        async with self._lock:
            self._load()
            key = str(user_id)
            rows = self._data.get(key, [])
            new = [b for b in rows if b.get("id") != batch_id]
            if len(new) == len(rows):
                return False
            self._data[key] = new
            self._save()
            return True

    async def toggle(self, user_id: int, batch: dict) -> bool:
        """True = ab enrolled hai, False = hata diya."""
        if await self.has(user_id, str(batch.get("id"))):
            await self.remove(user_id, str(batch.get("id")))
            return False
        await self.add(user_id, batch)
        return True

    async def count(self, user_id: int) -> int:
        return len(await self.list_for(user_id))

# ======================================================================
#  api.py
# ======================================================================

"""
api.py — ScholarVerse API ka async client + response normalizer.

Design rule: API ka response shape thoda bhi badle to sirf isi file me change
karo, handlers ko farak nahi padta. Har field ke multiple alias try hote hain.

Mock mode (API_MOCK=1): bina kisi API ke poora bot test kar sakte ho.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)


class APIError(RuntimeError):
    """API ne galat jawab diya / network fail hua."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# ===========================================================================
#  Data models — UI inhi objects pe chalta hai
# ===========================================================================
@dataclass
class Batch:
    id: str
    name: str
    image: str = ""
    language: str = ""
    by: str = ""
    price: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class Subject:
    id: str          # API jo bhi SubjectId maange (usually slug)
    name: str
    teacher: str = ""
    notes: int = 0
    videos: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class Topic:
    id: str
    name: str
    notes: int = 0
    videos: int = 0
    exercises: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class Item:
    id: str
    title: str
    kind: str = "pdf"                    # is build me sirf pdf
    date: str = ""
    duration: int | None = None
    thumb: str = ""
    url: str = ""                        # agar API seedha URL de de
    attachments: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class Resolved:
    """Download ke liye ready resource."""
    url: str
    kind: str = "pdf"                    # pdf | other
    filename: str = "file"
    headers: dict[str, str] = field(default_factory=dict)


# ===========================================================================
#  Helpers
# ===========================================================================
def _pick(d: dict, *keys: str, default: Any = "") -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _as_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _date_str(v: Any) -> str:
    s = str(v or "")
    return s[:10] if len(s) >= 10 else s


def _kind_from_name(name: str) -> str:
    low = (name or "").lower()
    if low.endswith(".pdf") or "pdf" in low:
        return "pdf"
    if any(low.endswith(x) for x in (".mp4", ".mkv", ".webm", ".m3u8", ".mpd")):
        return "video"
    return "other"


# ===========================================================================
#  Client
# ===========================================================================
class ScholarVerseAPI:
    def __init__(self, cfg=settings) -> None:
        self.cfg = cfg
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[float, Any]] = {}

    # ---------------- lifecycle ----------------
    async def start(self) -> None:
        if self._client is None:
            headers = {
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": self.cfg.api_referer,
                "Origin": self.cfg.api_referer.rstrip("/"),
            }
            if self.cfg.api_key:
                headers[self.cfg.api_key_header] = self.cfg.api_key
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.cfg.api_timeout, connect=15),
                follow_redirects=True,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------------- core request ----------------
    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}

        if self.cfg.api_mock:
            return _mock_response(endpoint, params)

        cache_key = f"{endpoint}?{sorted(params.items())}"
        cached = self._cache.get(cache_key)
        if cached and (time.time() - cached[0]) < self.cfg.api_cache_ttl:
            return cached[1]

        await self.start()
        assert self._client is not None
        url = self.cfg.url(endpoint)

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code == 404:
                    raise APIError("Content not found (404).", 404)
                if resp.status_code >= 500:
                    raise APIError(f"Server error ({resp.status_code}).", resp.status_code)
                if resp.status_code >= 400:
                    raise APIError(f"Request failed ({resp.status_code}).", resp.status_code)
                payload = resp.json()
                if not isinstance(payload, dict):
                    payload = {"data": payload}
                if payload.get("success") is False:
                    raise APIError(str(payload.get("message") or "API ne error diya."))
                self._cache[cache_key] = (time.time(), payload)
                return payload
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                log.warning("API attempt %s failed for %s: %s", attempt + 1, url, exc)
                if attempt < 2:
                    import asyncio

                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
            except ValueError as exc:  # JSON decode
                raise APIError("API ne galat JSON bheja.") from exc

        raise APIError(
            "Server se connect nahi ho paya. Thodi der baad try karo."
        ) from last_error

    # ==================================================================
    #  Batches
    # ==================================================================
    async def batches(self, page: int = 1) -> tuple[list[Batch], int, int]:
        js = await self._get("batches", {"page": page})
        rows = js.get("data") or js.get("batches") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or []
        total_pages = _as_int(_pick(js, "totalPages", "total_pages", default=1)) or 1
        total_items = _as_int(_pick(js, "totalItems", "total", default=len(rows)))
        return [self._batch(r) for r in rows], total_pages, total_items

    async def search_batches(self, query: str, page: int = 1) -> tuple[list[Batch], int, int]:
        js = await self._get("search", {"name": query, "page": page})
        rows = js.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or []
        total_pages = _as_int(_pick(js, "totalPages", default=1)) or 1
        return [self._batch(r) for r in rows], total_pages, _as_int(_pick(js, "totalItems", default=len(rows)))

    @staticmethod
    def _batch(d: dict) -> Batch:
        return Batch(
            id=str(_pick(d, "_id", "batchId", "id")),
            name=str(_pick(d, "batchName", "name", "title", default="Untitled batch")),
            image=str(_pick(d, "batchImage", "image", "thumbnail")),
            language=str(_pick(d, "language", "lang")),
            by=str(_pick(d, "byName", "description", "subtitle")),
            price=str(_pick(d, "batchPrice", "price")),
            raw=d,
        )

    # ==================================================================
    #  Subjects  (BatchInfo -> data.subjects)
    # ==================================================================
    async def subjects(self, batch_id: str) -> list[Subject]:
        js = await self._get("subjects", {"BatchId": batch_id, "Type": "details"})
        data = js.get("data") or js
        rows: list = []
        if isinstance(data, dict):
            rows = data.get("subjects") or data.get("subjectList") or []
        elif isinstance(data, list):
            rows = data
        out: list[Subject] = []
        for r in rows:
            out.append(
                Subject(
                    id=str(_pick(r, "slug", "subjectId", "_id", "id")),
                    name=str(_pick(r, "subject", "name", "subjectName", default="Subject")),
                    teacher=_teacher(r),
                    notes=_as_int(_pick(r, "notes", "totalNotes", default=0)),
                    videos=_as_int(_pick(r, "videos", "totalVideos", "lectureVideos", default=0)),
                    raw=r,
                )
            )
        return out

    # ==================================================================
    #  Topics  (SubjectInfo)
    # ==================================================================
    async def topics(self, batch_id: str, subject_id: str, page: int = 1) -> tuple[list[Topic], int]:
        js = await self._get(
            "topics", {"BatchId": batch_id, "SubjectId": subject_id, "page": page}
        )
        rows = js.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or []
        total_pages = _as_int(_pick(js, "totalPages", default=1)) or 1
        out = [
            Topic(
                id=str(_pick(r, "slug", "_id", "id", "topicId")),
                name=str(_pick(r, "name", "topic", "title", default="Topic")),
                notes=_as_int(_pick(r, "notes", default=0)),
                videos=_as_int(_pick(r, "videos", "lectureVideos", default=0)),
                exercises=_as_int(_pick(r, "exercises", default=0)),
                raw=r,
            )
            for r in rows
        ]
        return out, total_pages

    # ==================================================================
    #  Contents  (TopicInfo?ContentType=...)
    # ==================================================================
    async def contents(
        self,
        batch_id: str,
        subject_id: str,
        topic_id: str,
        ctype: str = "videos",
        page: int = 1,
    ) -> tuple[list[Item], int]:
        js = await self._get(
            "contents",
            {
                "BatchId": batch_id,
                "SubjectId": subject_id,
                "TopicId": topic_id,
                "ContentType": CONTENT_TYPES.get(ctype, ctype),
                "page": page,
            },
        )
        rows = js.get("data") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or []
        total_pages = _as_int(_pick(js, "totalPages", default=1)) or 1

        items: list[Item] = []
        for r in rows:
            items.extend(self._note_items(r))
        return items, total_pages

    @staticmethod
    def _note_items(d: dict) -> list[Item]:
        out: list[Item] = []
        schedule_id = str(_pick(d, "_id", "id"))
        for hw in d.get("homeworkIds") or []:
            note_type = str(_pick(hw, "note", default="Document"))
            for att in hw.get("attachmentIds") or []:
                out.append(
                    Item(
                        id=schedule_id,
                        title=str(_pick(att, "name", "topic", default=f"{note_type}.pdf")),
                        kind="pdf",
                        date=_date_str(_pick(d, "date")),
                        attachments=[att],
                        raw=d,
                    )
                )
        return out

    # ==================================================================
    #  Resolve -> download-ready URL
    # ==================================================================
    async def resolve(self, batch_id: str, subject_id: str, item: Item) -> Resolved:
        return await self._resolve_pdf(batch_id, subject_id, item)

    async def _resolve_pdf(self, batch_id: str, subject_id: str, item: Item) -> Resolved:
        if not item.attachments:
            raise APIError("Is item ke saath koi attachment nahi hai.")
        att = item.attachments[0]
        att_id = str(_pick(att, "_id", "attachmentId", "id"))
        js = await self._get(
            "pdf",
            {
                "BatchId": batch_id,
                "SubjectId": subject_id,
                "PdfId": item.id,
                "AttachmentId": att_id,
            },
        )
        data = js.get("data") or js
        base = str(_pick(data, "baseUrl", "base_url", default=""))
        key = str(_pick(data, "key", "path", default=""))
        name = str(_pick(data, "name", "fileName", default=item.title))
        if base and key:
            url = base.rstrip("/") + "/" + key.lstrip("/")
        else:
            url = str(_pick(data, "url", "link", default=""))
        if not url:
            raise APIError("API ne PDF ka link nahi diya.")
        return Resolved(url=url, kind="pdf", filename=name or item.title)


def _teacher(row: dict) -> str:
    teachers = row.get("teacherIds") or row.get("teachers") or []
    if isinstance(teachers, list) and teachers and isinstance(teachers[0], dict):
        t = teachers[0]
        name = f"{_pick(t, 'firstName', 'name', default='')} {_pick(t, 'lastName', default='')}".strip()
        return name
    return ""


# ===========================================================================
#  MOCK — bina API ke poora bot test karne ke liye (API_MOCK=1)
# ===========================================================================
_MOCK_BATCHES = [
    {"_id": "mock-b1", "batchName": "Next Toppers — Class 12", "language": "Hinglish",
     "byName": "For CBSE Class 12 Aspirants", "batchPrice": 0},
    {"_id": "mock-b2", "batchName": "Mission Jeet — NEET 2027", "language": "Hinglish",
     "byName": "For NEET Aspirants", "batchPrice": 0},
    {"_id": "mock-b3", "batchName": "Selection Way — SSC CGL", "language": "Hindi",
     "byName": "For SSC Aspirants", "batchPrice": 0},
]

_MOCK_SUBJECTS = [
    {"subject": "Physics By Rajwant Sir", "slug": "physics", "notes": 16, "videos": 12},
    {"subject": "Chemistry By Rahul Dudi Sir", "slug": "chemistry", "notes": 22, "videos": 9},
    {"subject": "Mathematics By Ashish Sir", "slug": "maths", "notes": 18, "videos": 14},
    {"subject": "Biology By Shivani Ma'am", "slug": "biology", "notes": 20, "videos": 11},
]

_MOCK_TOPICS = [
    {"name": "Units and Measurement", "slug": "units-and-measurement", "notes": 16, "videos": 6},
    {"name": "Kinematics", "slug": "kinematics", "notes": 12, "videos": 8},
    {"name": "Laws of Motion", "slug": "laws-of-motion", "notes": 14, "videos": 7},
    {"name": "Work Power Energy", "slug": "work-power-energy", "notes": 10, "videos": 5},
]


def _mock_response(endpoint: str, params: dict) -> dict:
    page = _as_int(params.get("page", 1)) or 1
    if endpoint == "batches":
        return {"success": True, "currentPage": page, "totalPages": 1,
                "totalItems": len(_MOCK_BATCHES), "data": _MOCK_BATCHES}
    if endpoint == "search":
        q = str(params.get("name", "")).lower()
        rows = [b for b in _MOCK_BATCHES if q in b["batchName"].lower()] or _MOCK_BATCHES[:1]
        return {"success": True, "totalPages": 1, "data": rows}
    if endpoint == "subjects":
        return {"success": True, "data": {"subjects": _MOCK_SUBJECTS}}
    if endpoint == "topics":
        return {"success": True, "totalPages": 1, "data": _MOCK_TOPICS}
    if endpoint == "contents":
        ctype = str(params.get("ContentType", "notes"))
        label = "DPP" if ctype == "DppNotes" else "Class Notes"
        rows = [
            {"_id": f"mock-n{i}",
             "date": "2026-05-11T00:00:00.000Z",
             "homeworkIds": [{
                 "note": label,
                 "attachmentIds": [{"_id": f"mock-a{i}",
                                    "name": f"Units and Measurement {label} {i}.pdf"}],
             }]}
            for i in range(1, 5)
        ]
        return {"success": True, "totalPages": 1, "data": rows}
    if endpoint == "pdf":
        return {"success": True,
                "data": {"baseUrl": "mock:", "key": "document.pdf", "name": ""}}
    return {"success": True, "data": []}

# ======================================================================
#  downloader.py
# ======================================================================

"""
downloader.py — ek hi jagah se har tarah ka download.

  • direct file (.mp4 .pdf .zip ...)  -> httpx streaming
  • HLS  (.m3u8)                      -> ffmpeg -c copy (remux, koi quality loss nahi)
  • DASH (.mpd)                       -> same ffmpeg path
  • mock: (testing)                   -> ffmpeg testsrc se dummy file

Cancel: asyncio.Event set karo, download turant ruk jaayega.
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx


log = logging.getLogger(__name__)

CHUNK = 1 << 18  # 256 KB


class DownloadError(RuntimeError):
    pass


class Cancelled(DownloadError):
    pass


@dataclass
class ProgressInfo:
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0          # bytes/sec
    eta: int | None = None      # seconds
    percent: float = 0.0


ProgressCB = "callable"  # async def (ProgressInfo) -> None


def is_stream(url: str) -> bool:
    low = url.lower().split("?")[0]
    return low.endswith(".m3u8") or low.endswith(".mpd")


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None


VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v")
DOC_EXT = (".pdf", ".zip", ".docx", ".pptx", ".txt", ".jpg", ".png")


def _with_ext(name: str, resource: Resolved, stream: bool = False) -> str:
    """File ka sahi extension ensure karta hai (Telegram ko chahiye hota hai)."""
    low = name.lower()
    if resource.kind == "video" and not low.endswith(VIDEO_EXT):
        return safe_filename(Path(name).stem + ".mp4")
    if resource.kind == "pdf" and not low.endswith(DOC_EXT):
        return safe_filename(Path(name).stem + ".pdf")
    return name


# ---------------------------------------------------------------------------
#  Public entry point
# ---------------------------------------------------------------------------
async def download(
    resource: Resolved,
    dest_dir: Path,
    progress: "ProgressCB | None" = None,
    cancel: asyncio.Event | None = None,
) -> Path:
    """Download karke local Path return karta hai."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _with_ext(safe_filename(resource.filename or "file"), resource, stream=is_stream(resource.url))

    if resource.url.startswith("mock:"):
        return await _mock_file(resource, dest_dir, name, progress, cancel)

    if is_stream(resource.url):
        return await _ffmpeg_download(resource, dest_dir, name, progress, cancel)

    return await _http_download(resource, dest_dir, name, progress, cancel)


# ---------------------------------------------------------------------------
#  Direct HTTP
# ---------------------------------------------------------------------------
async def _http_download(
    resource: Resolved,
    dest_dir: Path,
    name: str,
    progress: "ProgressCB | None",
    cancel: asyncio.Event | None,
) -> Path:
    dest = unique_path(dest_dir, name)
    headers = {"User-Agent": "Mozilla/5.0", **resource.headers}
    timeout = httpx.Timeout(connect=20, read=120, write=60, pool=20)

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        try:
            async with client.stream("GET", resource.url, headers=headers) as resp:
                if resp.status_code >= 400:
                    raise DownloadError(f"Download failed (HTTP {resp.status_code}).")
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                started = asyncio.get_event_loop().time()
                with open(dest, "wb") as fh:
                    async for chunk in resp.aiter_bytes(CHUNK):
                        if cancel and cancel.is_set():
                            raise Cancelled("Download cancelled.")
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            await progress(_info(done, total, started))
        except httpx.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise DownloadError(f"Network error: {exc}") from exc
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise DownloadError("Khaali file mili (0 bytes).")
    return dest


# ---------------------------------------------------------------------------
#  HLS / DASH via ffmpeg
# ---------------------------------------------------------------------------
async def _ffmpeg_download(
    resource: Resolved,
    dest_dir: Path,
    name: str,
    progress: "ProgressCB | None",
    cancel: asyncio.Event | None,
) -> Path:
    if not ffmpeg_available():
        raise DownloadError(
            "ffmpeg install nahi hai — m3u8/mpd download ke liye zaroori hai.\n"
            "Ubuntu: `sudo apt install ffmpeg`"
        )

    dest = unique_path(dest_dir, name)
    duration = await _probe_duration(resource.url, resource.headers)

    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-progress", "pipe:1", "-nostats",
    ]
    if resource.headers:
        hdr = "".join(f"{k}: {v}\r\n" for k, v in resource.headers.items())
        cmd += ["-headers", hdr]
    cmd += ["-i", resource.url, "-c", "copy", "-movflags", "+faststart", str(dest)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_buf: list[bytes] = []

    async def drain() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_buf.append(line)
            if len(stderr_buf) > 200:
                del stderr_buf[:100]

    drainer = asyncio.create_task(drain())
    started = asyncio.get_event_loop().time()

    try:
        assert proc.stdout is not None
        while True:
            if cancel and cancel.is_set():
                proc.kill()
                raise Cancelled("Download cancelled.")
            line = await proc.stdout.readline()
            if not line:
                break
            key, _, value = line.decode(errors="ignore").strip().partition("=")
            if key in {"out_time_us", "out_time_ms"} and progress:
                try:
                    done = int(value) / 1_000_000  # seconds
                except ValueError:
                    continue
                pct = min(99.0, done / duration * 100) if duration else 0.0
                elapsed = max(0.001, asyncio.get_event_loop().time() - started)
                speed = (done / elapsed) if duration else 0.0
                await progress(
                    ProgressInfo(
                        downloaded=int(done), total=int(duration or 0),
                        speed=speed, eta=int(max(0, duration - done)) if duration else None,
                        percent=pct,
                    )
                )
        await proc.wait()
    finally:
        await drainer

    if proc.returncode != 0:
        dest.unlink(missing_ok=True)
        err = b"".join(stderr_buf[-8:]).decode(errors="ignore").strip()
        if "encrypt" in err.lower() or "drm" in err.lower() or "decryption" in err.lower():
            raise DownloadError(
                "Ye stream encrypted hai, isliye download nahi ho paya."
            )
        raise DownloadError(f"ffmpeg fail hua: {err[:300] or 'unknown error'}")

    if not dest.exists() or dest.stat().st_size == 0:
        raise DownloadError("ffmpeg ne khaali file banayi.")
    return dest


async def _probe_duration(url: str, headers: dict[str, str]) -> float:
    """ffprobe se duration; ffprobe na ho to ffmpeg ke stderr se nikaal lete hain."""
    hdr = "".join(f"{k}: {v}\r\n" for k, v in headers.items()) if headers else ""

    if shutil.which(settings.ffprobe_bin):
        cmd = [settings.ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1"]
        if hdr:
            cmd += ["-headers", hdr]
        cmd.append(url)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
            return float(out.decode().strip() or 0)
        except Exception:
            return 0.0

    if shutil.which(settings.ffmpeg_bin):
        cmd = [settings.ffmpeg_bin, "-hide_banner", "-nostdin"]
        if hdr:
            cmd += ["-headers", hdr]
        cmd += ["-i", url]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=25)
            import re

            m = re.search(rb"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
            if m:
                h, mi, s = m.groups()
                return int(h) * 3600 + int(mi) * 60 + float(s)
        except Exception:
            return 0.0
    return 0.0


# ---------------------------------------------------------------------------
#  Mock (testing)
# ---------------------------------------------------------------------------
async def _mock_file(
    resource: Resolved,
    dest_dir: Path,
    name: str,
    progress: "ProgressCB | None",
    cancel: asyncio.Event | None,
) -> Path:
    dest = unique_path(dest_dir, name)
    steps = 20
    if ffmpeg_available() and dest.suffix.lower() in {".mp4", ".mkv", ".webm"}:
        cmd = [
            settings.ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(dest),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        if dest.exists() and dest.stat().st_size > 0:
            if progress:
                await progress(ProgressInfo(100, 100, 0, 0, 100))
            return dest

    # PDF ya ffmpeg na ho to chhota valid file
    data = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
        if dest.suffix.lower() == ".pdf"
        else b"TheScholarVerse.In - sample file\n"
    )
    with open(dest, "wb") as fh:
        for i in range(steps):
            if cancel and cancel.is_set():
                fh.close()
                dest.unlink(missing_ok=True)
                raise Cancelled("Download cancelled.")
            fh.write(data)
            await asyncio.sleep(0.05)
            if progress:
                await progress(
                    ProgressInfo(
                        downloaded=(i + 1) * len(data), total=steps * len(data),
                        speed=len(data) * 20, eta=(steps - i - 1) // 20,
                        percent=(i + 1) / steps * 100,
                    )
                )
    return dest


def _info(done: int, total: int, started: float) -> ProgressInfo:
    elapsed = max(0.001, asyncio.get_event_loop().time() - started)
    speed = done / elapsed
    eta = int((total - done) / speed) if total and speed > 0 else None
    return ProgressInfo(
        downloaded=done,
        total=total,
        speed=speed,
        eta=eta,
        percent=(done / total * 100) if total else 0.0,
    )

# ======================================================================
#  keyboards.py
# ======================================================================

"""keyboards.py — saare inline keyboards + callback data scheme.

Callback data chhota rakhna zaroori hai (Telegram limit 64 bytes), isliye list
me index bhejte hain, real id nahi — asli object user_data me rehta hai.
"""

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as KB


def _grid(rows: list[list[B]]) -> KB:
    return KB(rows)


# ---------------------------------------------------------------------------
#  Main menu
# ---------------------------------------------------------------------------
def main_menu() -> KB:
    return _grid([
        [B("📚 Batch chuno", callback_data="b:0")],
        [B("⭐ Mere Batches", callback_data="my"), B("🔎 Search", callback_data="srch")],
        [B("ℹ️ About", callback_data="about"), B("🌐 Website", url=settings.brand_url)],
        [B("📢 Channel", url=f"https://t.me/{settings.brand_channel.lstrip('@')}")],
    ])


# ---------------------------------------------------------------------------
#  Batch home (subjects / tests / enroll)
# ---------------------------------------------------------------------------
def batch_home_kb(enrolled: bool) -> KB:
    enroll_label = "✅ Enrolled — hatao" if enrolled else "📌 Enroll karo"
    return _grid([
        [B("📖 Subjects", callback_data="subs"), B("🧪 Tests 🔧", callback_data="tests")],
        [B(enroll_label, callback_data="enr")],
        [B("◀️ Back", callback_data="b:0"), B("🏠 Menu", callback_data="m")],
    ])


# ---------------------------------------------------------------------------
#  Batch list  (server paginated)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
#  Generic list (subjects / topics / items) — client side paging
# ---------------------------------------------------------------------------
def list_kb(
    labels: list[str],
    prefix: str,
    page: int,
    total_pages: int,
    back: str,
    nav_prefix: str | None = None,
) -> KB:
    """prefix = item callback (s / t / c), nav_prefix = pager callback (sp / tp / cp)."""
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


# ---------------------------------------------------------------------------
#  Content type filter
# ---------------------------------------------------------------------------
def content_types_kb(active: str) -> KB:
    def mark(key: str, label: str) -> B:
        return B(("✅ " if active == key else "") + label, callback_data=f"ct:{key}")

    return _grid([
        [mark("notes", "📄 Notes"), mark("dpp", "📝 DPP")],
        [B("🔧 Lectures — maintenance", callback_data="ct:locked")],
        [B("◀️ Back", callback_data="bk:topics"), B("🏠 Menu", callback_data="m")],
    ])


def my_batches_kb(labels: list[str], page: int, total_pages: int) -> KB:
    return list_kb(labels, "myb", page, total_pages, back="m", nav_prefix="myp")


# ---------------------------------------------------------------------------
#  Item card
# ---------------------------------------------------------------------------
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

# alias: handlers me caption ko brand_caption ke naam se use kiya gaya hai
brand_caption = caption


# ======================================================================
#  handlers.py
# ======================================================================

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

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes


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

# ======================================================================
#  main.py
# ======================================================================

"""
main.py — entry point.

Chalane ke liye:
    pip install -r requirements.txt
    cp .env.example .env      # phir .env me BOT_TOKEN daalo
    python main.py

Testing (bina API ke):
    .env me API_MOCK=1 rakho — dummy data se poora bot chal jaayega.
"""

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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("batches", cmd_batches))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
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
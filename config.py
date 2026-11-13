"""
config.py — Bot ki saari settings ek jagah.

⚠️  YAHI FILE EDIT KARNI HAI jab apni API daalni ho.
    Sirf do cheezein badalni hoti hain:
      1. .env me API_BASE_URL  (ya API_BASE_URL yahan default)
      2. Neeche ENDPOINTS dict ke paths
    Baaki kisi bhi file ko chhune ki zaroorat nahi.
"""
from __future__ import annotations

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

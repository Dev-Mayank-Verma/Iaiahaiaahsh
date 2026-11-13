"""
api.py — ScholarVerse API ka async client + response normalizer.

Design rule: API ka response shape thoda bhi badle to sirf isi file me change
karo, handlers ko farak nahi padta. Har field ke multiple alias try hote hain.

Mock mode (API_MOCK=1): bina kisi API ke poora bot test kar sakte ho.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from config import CONTENT_TYPES, settings

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

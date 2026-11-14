from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)

MAX_PER_USER = 60


class EnrollmentStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (settings.work_dir / "enrollments.json")
        self._lock = asyncio.Lock()
        self._data: dict[str, list[dict]] = {}
        self._loaded = False

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
            log.warning("enrollments.json padha nahi gaya (%s)", exc)
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def list_for(self, user_id: int) -> list[dict]:
        async with self._lock:
            self._load()
            return list(self._data.get(str(user_id), []))

    async def has(self, user_id: int, batch_id: str) -> bool:
        return any(b.get("id") == batch_id for b in await self.list_for(user_id))

    async def add(self, user_id: int, batch: dict) -> bool:
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
        if await self.has(user_id, str(batch.get("id"))):
            await self.remove(user_id, str(batch.get("id")))
            return False
        await self.add(user_id, batch)
        return True

    async def count(self, user_id: int) -> int:
        return len(await self.list_for(user_id))

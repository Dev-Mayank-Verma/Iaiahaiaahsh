from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from api import Resolved
from config import settings
from utils import safe_filename, unique_path

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
    speed: float = 0.0
    eta: int | None = None
    percent: float = 0.0


ProgressCB = "callable"


def is_stream(url: str) -> bool:
    low = url.lower().split("?")[0]
    return low.endswith(".m3u8") or low.endswith(".mpd")


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None


VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v")
DOC_EXT = (".pdf", ".zip", ".docx", ".pptx", ".txt", ".jpg", ".png")


def _with_ext(name: str, resource: Resolved, stream: bool = False) -> str:
    low = name.lower()
    if resource.kind == "video" and not low.endswith(VIDEO_EXT):
        return safe_filename(Path(name).stem + ".mp4")
    if resource.kind == "pdf" and not low.endswith(DOC_EXT):
        return safe_filename(Path(name).stem + ".pdf")
    return name


async def download(
    resource: Resolved,
    dest_dir: Path,
    progress: "ProgressCB | None" = None,
    cancel: asyncio.Event | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _with_ext(safe_filename(resource.filename or "file"), resource, stream=is_stream(resource.url))

    if resource.url.startswith("mock:"):
        return await _mock_file(resource, dest_dir, name, progress, cancel)

    if is_stream(resource.url):
        return await _ffmpeg_download(resource, dest_dir, name, progress, cancel)

    return await _http_download(resource, dest_dir, name, progress, cancel)


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
                    done = int(value) / 1_000_000
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
            raise DownloadError("Ye stream encrypted hai, isliye download nahi ho paya.")
        raise DownloadError(f"ffmpeg fail hua: {err[:300] or 'unknown error'}")

    if not dest.exists() or dest.stat().st_size == 0:
        raise DownloadError("ffmpeg ne khaali file banayi.")
    return dest


async def _probe_duration(url: str, headers: dict[str, str]) -> float:
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

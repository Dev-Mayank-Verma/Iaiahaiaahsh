# 🎓 TheScholarVerse.In — Telegram Content Bot

Telegram bot jo tumhari API se **batch → subject → topic → video/PDF** uthata hai,
file download karta hai, aur seedha chat me upload kar deta hai.

Har screen pe **TheScholarVerse.In** branding. Saara UI Hinglish me.

---

## 1. Features

| Feature | Detail |
|---|---|
| Batch browsing | Paginated list, API se (jaise 1425 pages bhi chal jaayega) |
| Search | Batch naam se search |
| Navigation | Subject → Topic → Videos / Notes / DPP |
| Notes + DPP download | API ka `baseUrl + key` join karke, seedha PDF |
| Lectures | `🔧 Under maintenance` — is build me nahi hain |
| Live progress | Bar + speed + ETA, message live edit hota hai |
| Bada file | 50 MB se zyada pe **🔗 Direct link** / **❌ Cancel** |
| Cancel | `/cancel` ya inline button — ffmpeg process turant kill |
| Queue | Max 3 parallel downloads (configurable) |
| Private bot | `ALLOWED_USER_IDS` se access control |
| Force join | `FORCE_JOIN_CHANNEL` se channel membership check |
| Cache | API responses 5 min cache (configurable) |
| Mock mode | `API_MOCK=1` — bina API ke poora bot test |

---

## 2. Install

```bash
# ffmpeg optional hai (is build me sirf PDF hai, iske bina bhi chalega)
# sudo apt update && sudo apt install -y ffmpeg

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # phir .env edit karo
python main.py
```

`.env` me minimum ye 1 line zaroori hai:

```
BOT_TOKEN=123456:AA...        # @BotFather se
```

---

## 3. Pehle bina API ke test karo

```bash
API_MOCK=1
python main.py
```

Bot 3 dummy batches (Next Toppers, Mission Jeet, Selection Way), 4 subjects,
4 topics, 6 videos aur 4 PDFs ke saath chalega. Poora navigation, progress bar,
download aur upload — sab test ho jaayega. Mock ek asli chhota MP4 banata hai
(ffmpeg se) taaki Telegram video player me play ho.

---

## 4. Apni API kaise add karni hai (2 step)

### Step 1 — `.env` me base URL + key

```env
API_BASE_URL=https://tumhari-site.com
API_PREFIX=/api
API_KEY=your_key_here
API_KEY_HEADER=X-API-Key
API_REFERER=https://tumhari-site.com/
API_MOCK=0
```

### Step 2 — `config.py` me ENDPOINTS

```python
ENDPOINTS = {
    "batches":    "/AllBatches",     # ?page=1
    "search":     "/searchBatch",    # ?name=&page=1
    "subjects":   "/BatchInfo",      # ?BatchId=&Type=details
    "topics":     "/SubjectInfo",    # ?BatchId=&SubjectId=&page=1
    "contents":   "/TopicInfo",      # ?BatchId=&SubjectId=&TopicId=&ContentType=&page=1
    "pdf":        "/GetPdf",         # ?BatchId=&SubjectId=&PdfId=&AttachmentId=
    "video":      "/get-video-url",  # ?batchId=&subjectId=&childId=&scheduleId=&Type=&lectureId=
}
```

Bas. Baaki 8 files ko chhune ki zaroorat nahi.

### Agar tumhare API ke response shape alag hain

Sirf `api.py` ke chhote mapper functions badlo — `_batch()`, `_video_item()`,
`_note_items()`, `_resolve_pdf()`, `_resolve_video()`. Handlers ko kuch farak
nahi padega, kyunki wo sirf `Batch` / `Subject` / `Topic` / `Item` objects
dekhte hain.

---

## 4b. Lectures — maintenance mode

Is build me lectures **poori tarah hata diye gaye hain** — na video endpoint, na
HLS/DASH engine, na compress. Content screen pe sirf do tab hain: **📄 Notes** aur
**📝 DPP**, aur unke neeche `🔧 Lectures — maintenance` button jo tap karne pe
saaf message dikhata hai.

Code me lecture wapas laana ho to teen jagah kaam hai: `config.py` ke `ENDPOINTS`
me `video` path, `api.py` me `_resolve_video()`, aur `keyboards.py` me Videos ka
button. Baaki navigation ko kuch chhune ki zaroorat nahi.

## 4c. Logo / branding

`assets/logo.png` me apna logo rakho (square PNG, 512×512 best).
`/start` pe bot wo logo photo ke saath welcome bhejega.

```env
BRAND_LOGO=assets/logo.png
```

Logo hataana ho to `BRAND_LOGO=` khaali chhod do — bot text welcome bhejega.

## 5. Files

```
main.py          entrypoint, commands, startup/shutdown
config.py        ⚙️  settings + ENDPOINTS  ← yahi edit karni hai
branding.py      🎨 naam, welcome, help, captions  ← branding yahi se
api.py           async client, normalizer, cache, mock
downloader.py    download engine (direct file + progress + cancel)
handlers.py      navigation router, progress, upload
keyboards.py     saare inline keyboards
utils.py         size/time format, progress bar, safe filename
requirements.txt
.env.example
```

---

## 6. Deploy (VPS, systemd)

```ini
# /etc/systemd/system/scholarverse-bot.service
[Unit]
Description=TheScholarVerse Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/scholarverse-bot
EnvironmentFile=/home/ubuntu/scholarverse-bot/.env
ExecStart=/home/ubuntu/scholarverse-bot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scholarverse-bot
journalctl -u scholarverse-bot -f
```

### Docker

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t sv-bot . && docker run -d --env-file .env --name sv-bot sv-bot
```

---

## 7. Zaroori baatein

- **50 MB limit** Telegram Bot API ka hai. Isse bada bhejna ho to apna
  [local Bot API server](https://github.com/tdlib/telegram-bot-api) chalao
  (2 GB tak) aur `MAX_UPLOAD_MB` badha do.
- **ffmpeg** is build me zaroori nahi hai — sirf PDF download hota hai.
- **Encrypted / DRM streams** (jinke saath `clearKeys` jaisa kuch aata hai) is
  bot me support nahi hain. `api.py` me aisa response aane pe bot
  "DRM-protected" error deta hai. Jo content tum serve karne ke liye
  authorised ho, wahi source use karo.
- `KEEP_FILES=0` (default) — upload ke baad temp file delete ho jaati hai.

---

## 8. Customise

| Kya badalna hai | Kahan |
|---|---|
| Bot ka naam, tagline, links | `branding.py` (ya `.env` ke `BRAND_*`) |
| Welcome / help / about text | `branding.py` |
| Buttons ke labels | `keyboards.py` |
| Page size, limits, timeouts | `.env` |
| API endpoints | `config.py` |

---

🎓 **TheScholarVerse.In** — https://thescholarverse.in

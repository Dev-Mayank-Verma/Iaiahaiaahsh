FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WORK_DIR=/tmp/scholarverse \
    TZ=Asia/Kolkata

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp/scholarverse

RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app /tmp/scholarverse
USER botuser

CMD ["python", "main.py"]

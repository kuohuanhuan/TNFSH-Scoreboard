# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------- build
FROM python:${PYTHON_VERSION}-slim AS build

# 設為 false 可建置不含 ddddocr（約小 200 MB）的映像檔，使用者需手動輸入驗證碼
ARG WITH_OCR=true

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt requirements-ocr.txt /tmp/
RUN if [ "$WITH_OCR" = "true" ]; then \
        pip install -r /tmp/requirements-ocr.txt; \
    else \
        pip install -r /tmp/requirements.txt; \
    fi

# ---------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim

LABEL org.opencontainers.image.title="TNFSH Scoreboard" \
      org.opencontainers.image.description="台南一中成績查詢系統" \
      org.opencontainers.image.source="https://github.com/tobiichi3227/TNFSH-Scoreboard" \
      org.opencontainers.image.licenses="GPL-2.0-only"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # 執行身分沒有家目錄；/tmp 在 read-only 容器中也是可寫的 tmpfs（onnxruntime 會寫入暫存資料）
    HOME=/tmp \
    # 預設信任前方反向代理的 X-Forwarded-* 標頭
    FORWARDED_ALLOW_IPS="*" \
    WEB_CONCURRENCY=1

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin scoreboard

COPY --from=build /opt/venv /opt/venv
WORKDIR /srv
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY app ./app

USER scoreboard
EXPOSE 5227

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; base = os.environ.get('SCOREBOARD_BASE_URL', '/').rstrip('/'); urllib.request.urlopen(f'http://127.0.0.1:5227{base}/healthz', timeout=4)"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5227", "--proxy-headers"]

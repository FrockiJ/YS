# ---- Stage 1: Builder ----
# 安裝所有建置工具和 Python 套件
FROM python:3.11-slim as builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ---- Stage 2: Final Image ----
# 從乾淨的基礎映像開始，只安裝執行時期必要的函式庫
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# 從 builder 階段複製已安裝好的 Python 套件
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
# 同時也要複製 pip 安裝的可執行檔 (如 uvicorn)
COPY --from=builder /usr/local/bin /usr/local/bin
COPY services/api/src /app/src
COPY cerp /app/cerp
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

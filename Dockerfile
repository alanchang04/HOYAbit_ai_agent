# HOYA BIT 加密市場分析 AI Agent — Web UI 容器
# CLI（main.py）與 Web UI（webapp/app.py）共用同一個 image，
# 差別只在 CMD 執行哪個進入點。

FROM python:3.11-slim

WORKDIR /app

# 先只複製 requirements.txt 以善用 Docker layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# App Runner／健康檢查走 GET /healthz（見 webapp/app.py）
CMD ["uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8000"]

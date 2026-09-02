# --- stage 1: build the frontend ------------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# --- stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY --from=web /web/dist frontend/dist

ENV SATQUERY_DATA_DIR=/srv/data \
    SATQUERY_HOST=0.0.0.0 \
    SATQUERY_PORT=8000
RUN mkdir -p /srv/data
VOLUME ["/srv/data"]
EXPOSE 8000

# Adapt the RS classifier at build time so the image ships ready to demo.
# Remove this line for a smaller image; the app runs without it and says so.
RUN cd backend && python -m app.ml.train_eurosat --limit-per-class 700 || \
    echo "RS classifier training skipped - the tool will report itself unavailable"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health').read()"

WORKDIR /srv/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

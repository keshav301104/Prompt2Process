# Prompt2Process — one container: FastAPI + LangGraph backend serving the built React console.
# Build:  docker build -t prompt2process .
# Run:    docker run -p 8000:8000 -e GEMINI_API_KEY=... prompt2process   →  http://localhost:8000

# ---- 1. Build the console (React + Vite + Tailwind)
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Runtime: Python API, Gemma 4 client, ML models, and the built console
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./backend/
COPY --from=web /app/frontend/dist ./frontend/dist

# data/ (generated demo documents) and state/ (SQLite + checkpoints) are created at runtime under /app
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

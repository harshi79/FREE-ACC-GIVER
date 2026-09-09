# syntax=docker/dockerfile:1
#
# Fʀᴇᴇ Aᴄᴄ Gɪᴠᴇʀ — container image
# Run locally:   docker build -t free-acc-giver .
#                docker run --rm -p 8000:8000 \
#                  -e BOT_TOKEN=... -e BOT_DATABASE_URL=postgres://... \
#                  free-acc-giver
# On Render this Dockerfile is picked up automatically (see render.yaml).

FROM python:3.11-slim

# Logs straight to stdout (Render-friendly), no __pycache__ in the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (layer caching: the heavy step runs once).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source (health server + bot code).
COPY . .

# Run as a non-root user — the app never needs root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser && \
    chown -R appuser:appuser /app
USER appuser

# Render injects PORT; the bot's tiny health server binds 0.0.0.0:$PORT
# and answers 200 so the platform keeps the instance warm.
EXPOSE 8000

CMD ["python", "bot.py"]

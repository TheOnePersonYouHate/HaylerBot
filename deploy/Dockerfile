# Minimal image for the Naval RP bot (xAI brain -- no GPU, no LM Studio).
# Build from the repo root so the context is the whole project:
#   docker build -f deploy/Dockerfile -t naval-rp-bot .
FROM python:3.12-slim

WORKDIR /app

# Install deps first so this layer caches when only the code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app. .dockerignore keeps out .env, .venv, caches, and local state,
# so secrets are never baked into the image (they arrive at runtime via --env-file).
COPY . .

# Persist the ship's state/log on a mounted volume at /app/state (see DEPLOY.md).
CMD ["python", "bot.py"]

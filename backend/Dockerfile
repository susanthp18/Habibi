# Backend app image — parameterized by command (api / worker / bot_worker / voice).
# Build:
#   docker compose build api
#   docker compose build voice   # also installs requirements-voice.txt
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl for healthchecks; ca-certs for Azure/Meta TLS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Application source (see .dockerignore)
COPY . .

# Default = API. Compose overrides command + DB_PROCESS_ROLE per service.
ENV DB_PROCESS_ROLE=api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


# Voice runner needs Pipecat + native audio/WebRTC deps.
FROM base AS voice

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-voice.txt .
RUN pip install -r requirements-voice.txt

ENV DB_PROCESS_ROLE=voice
EXPOSE 7860
# Bind all interfaces so published compose ports reach the runner.
CMD ["python", "-m", "voice.bot", "--host", "0.0.0.0", "--port", "7860"]

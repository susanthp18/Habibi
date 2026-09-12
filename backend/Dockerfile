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

# requirements.lock is a 3.12 linux resolve of this file, with hashes.
# --require-hashes is what makes the 114 previously-unpinned transitives
# (cryptography, urllib3, certifi, …) a recorded artifact rather than a
# fresh PyPI resolve at every image build.
COPY requirements.txt requirements.lock .
RUN pip install --require-hashes -r requirements.lock

# Application source (see .dockerignore). Runs as an unprivileged user: the
# only tree the app writes is /app/.cache (TTS previews, recordings, the
# session-store fallback); everything else is read-only to it.
COPY . .
RUN useradd --system --uid 1000 --create-home --home-dir /home/app app \
    && mkdir -p /app/.cache \
    && chown -R app:app /app
USER app
ENV HOME=/home/app

# Default = API. Compose overrides command + DB_PROCESS_ROLE per service.
ENV DB_PROCESS_ROLE=api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


# Compile voice native wheels. Discarded; the voice stage copies
# /usr/local and does not keep the C toolchain. ffmpeg is here too
# because some wheels probe for it at install time — the runtime
# copy is a separate apt install on the voice stage, since apt
# puts the binary in /usr/bin, outside this COPY.
FROM base AS builder

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Constrain the voice layer to the base pins. Without -c, pipecat's
# transitive graph can upgrade httpx, openai, websockets or ruff inside
# this image only; the api and voice images from one commit then
# disagree, and nothing records what either got. A conflict
# (ruff==0.6.9 vs pipecat's cli extra ruff>=0.12.1, if evals is added)
# must fail the build — do not drop the flag to make the install green.
COPY requirements-voice.txt requirements-voice.lock .
RUN pip install --require-hashes -r requirements-voice.lock -c requirements.txt

# Pipecat's sentence splitter (pipecat.utils.string) calls
# nltk.download("punkt_tab") at import if the data is missing. Bake it
# into the image so a production start does not perform a network
# download — least of all behind a bank egress proxy.
# Path is outside /app so the docker-compose.dev.yml bind-mount of
# .:/app cannot hide it.
ENV NLTK_DATA=/usr/local/share/nltk_data
RUN python -c "import os, nltk; nltk.download('punkt_tab', download_dir=os.environ['NLTK_DATA'], quiet=True, raise_on_error=True); nltk.data.find('tokenizers/punkt_tab')"


# Voice runner. ffmpeg is needed at runtime; a C toolchain is not.
# build-essential used to survive into this stage — the container that
# terminates borrower calls.
FROM base AS voice

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local
USER app

ENV NLTK_DATA=/usr/local/share/nltk_data
ENV DB_PROCESS_ROLE=voice
EXPOSE 7860
# Bind all interfaces so published compose ports reach the runner.
CMD ["python", "-m", "voice.bot", "--host", "0.0.0.0", "--port", "7860"]

# Laptop test image: the voice image plus the test tooling. docker-compose.dev.yml
# builds this target for the `voice` service, which is where the suite runs;
# the shipped images above carry no pytest and no ruff.
FROM voice AS voice-dev
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
USER app

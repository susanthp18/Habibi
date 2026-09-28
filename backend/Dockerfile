# Backend app image — parameterized by command (api / worker / bot_worker).
# Build:
#   docker compose build api
# Pinned by digest: a tag moves under a rebuild; the digest is what CI and the
# laptop both built. Bump deliberately (docker pull python:3.12-slim, then
# docker image inspect --format '{{index .RepoDigests 0}}').
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS base

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


# Laptop test image: the app image plus the test tooling. docker-compose.dev.yml
# builds this target for the `tests` service, which is where the suite runs;
# the shipped images carry no pytest and no ruff.
FROM base AS dev
USER root
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
USER app


# The pinned models for the call-intelligence pass, fetched in a stage of
# their own: only call_intel/models.py (and its two helpers) is copied, so an
# application change does not invalidate ~800 MB of downloads.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS models
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 ML_MODEL_DIR=/opt/models
WORKDIR /fetch
RUN pip install huggingface_hub==1.33.0
COPY env_utils.py env_loader.py ./
COPY call_intel/__init__.py call_intel/models.py call_intel/
RUN python -m call_intel.models fetch
# Noto fonts for the evidence PDFs (Latin, Devanagari, Tamil, Arabic),
# verified by sha256: a changed upstream file fails the build, not an export.
ADD --checksum=sha256:478c558ea716033cd60c03438f628dfa75694dcf6b5f6d505a2f05fd2b4f3823 \
    https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io@main/fonts/NotoSans/hinted/ttf/NotoSans-Regular.ttf /opt/fonts/
ADD --checksum=sha256:4e3c66638958c3e2ab5d37f47a8deb89fffeb7be9985c665a519bbc7ba762313 \
    https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io@main/fonts/NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-Regular.ttf /opt/fonts/
ADD --checksum=sha256:3c0a186feb3c63c7f6d63e1511dcdc144e745ae09b98e217c83f3e317974f6f9 \
    https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io@main/fonts/NotoSansTamil/hinted/ttf/NotoSansTamil-Regular.ttf /opt/fonts/
ADD --checksum=sha256:bdff3e5659d67e67def05b33f749683b9376ae819d65d3dd62ac4640b3aaef48 \
    https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io@main/fonts/NotoSansArabic/hinted/ttf/NotoSansArabic-Regular.ttf /opt/fonts/


# ml_worker: the batch call-intelligence pass (python -m call_intel.worker).
# The base image plus CPU inference runtimes and the models baked in, so the
# worker never downloads at run time -- least of all behind a bank's egress.
FROM base AS ml
USER root
COPY requirements-ml.txt requirements-ml.lock ./
RUN pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu \
      -r requirements-ml.lock -c requirements.txt
COPY --from=models --chown=app:app /opt/models /opt/models
COPY --from=models --chown=app:app /opt/fonts /opt/fonts
USER app
ENV ML_MODEL_DIR=/opt/models \
    ML_FONT_DIR=/opt/fonts \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    ML_THREADS=2 \
    DB_PROCESS_ROLE=ml_worker
CMD ["python", "-m", "call_intel.worker"]

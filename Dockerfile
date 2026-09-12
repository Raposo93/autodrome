# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.14.7-slim-bookworm

FROM node:22-bookworm-slim AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend
COPY frontend ./frontend
RUN npm run build --prefix frontend

FROM ${PYTHON_IMAGE} AS wheel
WORKDIR /src
RUN python -m pip install --no-cache-dir \
    build==1.6.0 setuptools==84.0.0 wheel==0.48.0
COPY pyproject.toml setup.py MANIFEST.in requirements.txt README.md ./
COPY api ./api
COPY autodrome ./autodrome
COPY --from=frontend /src/frontend/dist ./frontend/dist
RUN python -m build --no-isolation --wheel

FROM ghcr.io/denoland/deno:bin-2.9.5 AS deno

FROM ${PYTHON_IMAGE} AS runtime
ARG AUTODROME_COMMIT=""
ENV API_HOST=0.0.0.0 \
    API_PORT=5000 \
    AUTODROME_COMMIT=${AUTODROME_COMMIT} \
    COVER_STORAGE_PATH=/music/.autodrome-covers \
    DENO_DIR=/home/autodrome/.cache/deno \
    HOME=/home/autodrome \
    LIBRARY_PATH=/music \
    PYTHONUNBUFFERED=1 \
    QUEUE_STATE_PATH=/music/.autodrome-queue.json \
    STAGING_PATH=/music/.autodrome-staging \
    YT_DLP_DENO_PATH=/usr/local/bin/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 autodrome \
    && useradd --uid 10001 --gid 10001 --create-home \
        --shell /usr/sbin/nologin autodrome \
    && install -d -o autodrome -g autodrome -m 0750 /music "$DENO_DIR"
COPY --from=deno /deno /usr/local/bin/deno
COPY requirements.lock /tmp/requirements.lock
COPY --from=wheel /src/dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir \
        --constraint /tmp/requirements.lock /tmp/*.whl \
    && rm -f /tmp/*.whl /tmp/requirements.lock \
    && deno --version \
    && ffmpeg -version >/dev/null

USER 10001:10001
WORKDIR /music
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=3).read(1)"]
CMD ["autodrome"]

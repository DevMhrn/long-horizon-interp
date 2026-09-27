FROM python:3.11-slim-trixie@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gettext libffi-dev libjpeg-dev libxml2-dev libxslt1-dev \
        zlib1g-dev libmaxminddb-dev ca-certificates git patch && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.8.22

ENV TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRETIX_CONFIG_FILE=/app/src/tests/ci_sqlite.cfg

COPY requirements.lock /tmp/requirements.lock
RUN uv pip install --system --no-cache -r /tmp/requirements.lock

# Source fetched by exact commit sha (content-addressed, so always identical), history removed.
RUN git init -q /app && cd /app && \
    git fetch -q --depth 1 https://github.com/pretix/pretix.git cdeb1e86bd98d095e742f9b9b9701b634b0f1aa8 && \
    git checkout -q FETCH_HEAD && \
    rm -rf /app/.git

WORKDIR /app
RUN PRETIX_DOCKER_BUILD=1 uv pip install --system --no-cache --no-deps -e .

WORKDIR /app/src
RUN python manage.py compilemessages -v 0

# Hardening: remember what /app/src looks like after the build (root-owned, outside /app, so the
# verifier can remove anything new at top level), then hand /app to an unprivileged agent user.
RUN mkdir -p /opt/verifier && ls -A /app/src > /opt/verifier/src_toplevel.txt && \
    useradd -m -u 1001 agent && chown -R agent:agent /app

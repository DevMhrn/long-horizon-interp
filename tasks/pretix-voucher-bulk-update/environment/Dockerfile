FROM python:3.13-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b

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
    git fetch -q --depth 1 https://github.com/pretix/pretix.git ea2c81e6dcd54633cd104621db7329b7ed3b6e01 && \
    git checkout -q FETCH_HEAD && \
    rm -rf /app/.git

WORKDIR /app
RUN PRETIX_DOCKER_BUILD=1 uv pip install --system --no-cache --no-deps -e .

WORKDIR /app/src
RUN python manage.py compilemessages -v 0

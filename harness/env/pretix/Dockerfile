# pretix frozen at a single commit, ready to run its pytest suite on SQLite.
# Build context is assembled by harness/build_env.py: this file + repo.tar + requirements.lock.

# Digest-pinned Python image, chosen per commit from the version its own CI tests SQLite on
# (see python_images.json). The default is only used for a manual `docker build`.
ARG PYTHON_IMAGE=python:3.13-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
FROM ${PYTHON_IMAGE}

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gettext libffi-dev libjpeg-dev libxml2-dev libxslt1-dev \
        zlib1g-dev libmaxminddb-dev ca-certificates git patch && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.8.22

# Same answer on every machine: fixed timezone, locale and hash seed.
ENV TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PRETIX_CONFIG_FILE=/app/src/tests/ci_sqlite.cfg

# Third-party dependencies first, from the lock captured in a working container.
COPY requirements.lock /tmp/requirements.lock
RUN uv pip install --system --no-cache -r /tmp/requirements.lock

# The frozen commit itself: `git archive` output, so no .git history is present.
WORKDIR /app
ADD repo.tar /app/

# Install the checkout without re-resolving anything. PRETIX_DOCKER_BUILD skips the
# npm/static asset build, which the Python test suite does not need.
RUN PRETIX_DOCKER_BUILD=1 uv pip install --system --no-cache --no-deps -e .

# CI compiles translations before testing (`make localecompile`); tests assert localized text.
WORKDIR /app/src
RUN python manage.py compilemessages -v 0

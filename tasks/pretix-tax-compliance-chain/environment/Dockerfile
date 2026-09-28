FROM python:3.11-slim-trixie@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

# Agent CLIs (Codex, Claude Code) need curl, ripgrep and Node.js. They are installed here so agent setup
# never depends on a package mirror at run time. Node.js comes from the official release, pinned by checksum.

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential gettext libffi-dev libjpeg-dev libxml2-dev libxslt1-dev \
        zlib1g-dev libmaxminddb-dev ca-certificates git patch \
        curl ripgrep xz-utils && \
    rm -rf /var/lib/apt/lists/*

ARG NODE_VERSION=v22.12.0
RUN arch="$(dpkg --print-architecture)" && \
    case "$arch" in \
        amd64) node_arch=x64;   sum=22982235e1b71fa8850f82edd09cdae7e3f32df1764a9ec298c72d25ef2c164f ;; \
        arm64) node_arch=arm64; sum=8cfd5a8b9afae5a2e0bd86b0148ca31d2589c0ea669c2d0b11c132e35d90ed68 ;; \
        *) echo "unsupported architecture $arch" && exit 1 ;; \
    esac && \
    curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-${node_arch}.tar.xz" && \
    echo "$sum  /tmp/node.tar.xz" | sha256sum -c - && \
    tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner && \
    rm /tmp/node.tar.xz && node --version && npm --version

# Agent CLI pinned at build time: Harbor skips its own installer when the CLI is already present, so
# agent setup needs no network and every run uses the same version.
ARG CODEX_VERSION=0.158.0
ARG CLAUDE_CODE_VERSION=2.1.284
RUN npm install -g "@openai/codex@${CODEX_VERSION}" "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && \
    codex --version && claude --version

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
COPY feature_removal.patch /tmp/feature_removal.patch
RUN git init -q /app && cd /app && \
    git fetch -q --depth 1 https://github.com/pretix/pretix.git 3e972eddbf117a17da33e730f9e3fc8bf4f59306 && \
    git checkout -q FETCH_HEAD && \
    git apply --whitespace=nowarn /tmp/feature_removal.patch && \
    rm -rf /app/.git /tmp/feature_removal.patch

WORKDIR /app
RUN PRETIX_DOCKER_BUILD=1 uv pip install --system --no-cache --no-deps -e .

WORKDIR /app/src
RUN python manage.py compilemessages -v 0

# Hardening: remember what /app/src looks like after the build (root-owned, outside /app, so the
# verifier can remove anything new at top level), then hand /app to an unprivileged agent user.
RUN mkdir -p /opt/verifier && ls -A /app/src > /opt/verifier/src_toplevel.txt && \
    useradd -m -u 1001 agent && chown -R agent:agent /app

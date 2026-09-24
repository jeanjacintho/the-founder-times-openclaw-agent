FROM ghcr.io/openclaw/openclaw:2026.9.4@sha256:cc596b846506a5f4cfcee111394a2725f375f01cca2ebb492a161fd1b747f101
ARG PLOW_REVISION
LABEL org.opencontainers.image.revision=$PLOW_REVISION co.plow.probe=/opt/plow/probe
USER root
RUN mkdir -p /opt/plow/skills /var/lib/plow && chown node:node /var/lib/plow

# WeasyPrint's native dependencies (bookworm names). The wheel is pure Python
# but binds Pango/Cairo through cffi at import time, so without these
# `import weasyprint` fails with a cffi error that reads like a Python problem.
# fonts-dejavu-core gives the page a guaranteed font with no fontconfig cache.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz0b \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
      libffi8 \
      shared-mime-info \
      fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

# The newspaper scripts' own Python: 3.13 (the version they are tested on;
# the base ships 3.11) in a root-owned venv the agent cannot rewrite. uv is
# pinned by version and checksum, used only at build time and removed; it
# verifies the CPython download against the hashes it ships with.
#
# pydyf is pinned beside weasyprint on purpose: 62.3 declares only
# pydyf>=0.10.0, and pydyf 0.12 moved its Stream API so every write_pdf() dies
# with "'super' object has no attribute 'transform'".
ARG UV_VERSION=0.11.19
ARG UV_SHA256_AMD64=7035608168e106375b36d0c818d537a889c51a8625fe7f8f7cad5e62b947c368
ARG UV_SHA256_ARM64=83b13ab184a45b7d9a3b0e4b10eaebd50ad41e66cb16dcce8e60aa7be13ae399
ARG PT_PYTHON_VERSION=3.13.13
ARG WEASYPRINT_VERSION=62.3
ARG PYDYF_VERSION=0.10.0
ARG PYYAML_VERSION=6.0.3
ARG TARGETARCH
RUN case "${TARGETARCH:-amd64}" in \
      amd64) triple=x86_64-unknown-linux-gnu; sum="${UV_SHA256_AMD64}" ;; \
      arm64) triple=aarch64-unknown-linux-gnu; sum="${UV_SHA256_ARM64}" ;; \
      *) echo "uv: no pinned build for ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -fsS --max-time 120 -L -o /tmp/uv.tgz \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${triple}.tar.gz" \
 && echo "${sum}  /tmp/uv.tgz" | sha256sum -c - \
 && mkdir /tmp/uv && tar -xzf /tmp/uv.tgz -C /tmp/uv --strip-components=1 \
 && export UV_PYTHON_INSTALL_DIR=/opt/plow/python UV_CACHE_DIR=/tmp/uv-cache UV_NO_CONFIG=1 \
 && /tmp/uv/uv python install "${PT_PYTHON_VERSION}" \
 && /tmp/uv/uv venv --python "${PT_PYTHON_VERSION}" --no-python-downloads /opt/plow/pt-venv \
 && /tmp/uv/uv pip install --python /opt/plow/pt-venv/bin/python3 \
      "weasyprint==${WEASYPRINT_VERSION}" "pydyf==${PYDYF_VERSION}" "PyYAML==${PYYAML_VERSION}" \
 && rm -rf /tmp/uv /tmp/uv.tgz /tmp/uv-cache \
 && chmod -R a+rX,go-w /opt/plow/python /opt/plow/pt-venv

# Exec runs `sh -c` / `bash --noprofile --norc -c` with tools.exec.pathPrepend
# putting the venv first. A login shell (`bash -lc`) resets PATH from
# /etc/profile, so the venv is prepended there too. The gateway's own PATH is
# left alone: the Agent Index reporter keeps running on the system python3.
RUN printf 'PATH="/opt/plow/pt-venv/bin:$PATH"\nexport PATH\n' > /etc/profile.d/pt-venv.sh \
 && chmod 0644 /etc/profile.d/pt-venv.sh

# Build probe: render a PDF through python3 exactly as a skill would, in each
# shell form exec can take, with the PATH exec uses. The build fails if any
# of them resolves a python3 without weasyprint.
RUN probe="import yaml, weasyprint, sys; assert sys.version_info[:2] == (3, 13), sys.version; weasyprint.HTML(string='<p>build probe</p>').write_pdf('/tmp/probe.pdf'); import os; os.remove('/tmp/probe.pdf'); print('weasyprint', weasyprint.__version__, sys.executable)" \
 && export PATH="/opt/plow/pt-venv/bin:$PATH" \
 && sh -c "python3 -c \"$probe\"" \
 && bash -c "python3 -c \"$probe\"" \
 && bash -lc "python3 -c \"$probe\"" \
 && env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin bash -lc "python3 -c \"$probe\""

COPY boot /opt/plow/boot
COPY plugin /opt/plow/plugin
COPY prompt /opt/plow/prompt
COPY skills /opt/plow/skills
# Root-owned and read-only to the agent: a script a turn could rewrite is a
# script a web page could rewrite. Executables keep their bit from git.
RUN chown -R root:root /opt/plow/skills \
 && find /opt/plow/skills -type d -exec chmod 0755 {} + \
 && find /opt/plow/skills -type f ! -perm -u+x -exec chmod 0644 {} + \
 && find /opt/plow/skills -type f -perm -u+x -exec chmod 0755 {} + \
 && install -d -o node -g node -m 0700 /var/lib/plow/pt
COPY build.ts /opt/plow/build.ts
COPY package.json package-lock.json tsconfig.json /opt/plow/

# The Agent Index usage reporter, fetched at build from an immutable commit and
# checked against its hash. Fetched rather than committed because
# plow-pbc/agent-index-client owns that file; a sha rather than a branch because
# this runs inside an agent holding a live credential, and a moving reference
# would substitute unreviewed code under it. The checksum is the second half: a
# sha in a URL is only as good as the host serving it. Bumping either is an edit
# somebody reviews.
#
# Root-owned, outside the state volume the agent writes: a copy the agent could
# write is a copy a turn can replace.
RUN curl -fsS --max-time 60 -o /opt/plow/agent-index-client.py \
      "https://raw.githubusercontent.com/plow-pbc/agent-index-client/edf196031803e204cdbcd81ce574e1f54fd75f65/standalone/agent_index_client.py" \
 && echo "970caf7534cd7d3b71ffee8f1a576f9da4dc494a508e8ab1998ee2ce6f4a2ac4  /opt/plow/agent-index-client.py" | sha256sum -c - \
 && chmod 0644 /opt/plow/agent-index-client.py

# The collector the reporter reads. agentsview covers OpenClaw sessions, so with
# it installed the usage half stops reading zero; without it the client still
# registers and reports empty days. Pinned and checksummed for the same reason
# as the client above: it runs inside an agent holding a live credential.
#
# One build per architecture: a local build on Apple silicon is arm64, and an
# amd64 binary there fails under Rosetta, so the reporter sent nothing. Both
# checksums match the release's provenance files.
ARG AGENTSVIEW_VERSION=0.44.0
ARG AGENTSVIEW_SHA256_AMD64=037ea7a46d52e06b20363b4aa7cd7f28e32f31d8215803d6e9a0c96bac5818e3
ARG AGENTSVIEW_SHA256_ARM64=6f3c76ebe119826a2def1ae226c3573b214d396a3ed7c477ef282b1063345b87
RUN case "${TARGETARCH:-amd64}" in \
      amd64) sum="${AGENTSVIEW_SHA256_AMD64}" ;; \
      arm64) sum="${AGENTSVIEW_SHA256_ARM64}" ;; \
      *) echo "agentsview: no pinned build for ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -fsS --max-time 120 -L -o /tmp/agentsview.tgz \
      "https://github.com/kenn-io/agentsview/releases/download/v${AGENTSVIEW_VERSION}/agentsview_${AGENTSVIEW_VERSION}_linux_${TARGETARCH:-amd64}.tar.gz" \
 && echo "${sum}  /tmp/agentsview.tgz" | sha256sum -c - \
 && tar -xzf /tmp/agentsview.tgz -C /usr/local/bin agentsview \
 && rm /tmp/agentsview.tgz \
 && chmod 0755 /usr/local/bin/agentsview
RUN cd /opt/plow && npm ci --omit=dev --omit=peer --omit=optional --ignore-scripts && node /opt/plow/build.ts && chmod +x /opt/plow/probe
ENV OPENCLAW_STATE_DIR=/var/lib/plow OPENCLAW_CONFIG_PATH=/var/lib/plow/openclaw.json OPENCLAW_NO_RESPAWN=1 NODE_DISABLE_COMPILE_CACHE=1
# Agent Index listing. Compose (and a host that injects env) can override without rebuild.
ENV AGENT_ID=theplowtimes \
    AGENT_NAME="The Founder Times" \
    AGENT_BLURB="Your morning paper, printed. It researches on your Mac and puts a sourced page in the tray, or a PDF in chat."
# The inherited healthcheck loads config and can race the boot state lock.
HEALTHCHECK NONE
USER node
CMD ["node", "/opt/plow/boot/main.js"]

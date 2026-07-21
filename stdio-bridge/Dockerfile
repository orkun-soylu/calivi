# stdio→HTTP bridge for MCP servers that only speak stdio.
#
# Calivi's backend deliberately does not run stdio servers itself: that would mean executing an
# npm/PyPI package named in an admin web form inside the application's own container, next to the
# database and the session key. This image is where that execution is moved to instead — it holds
# the untrusted code and speaks HTTP to Calivi, which needs no new transport to talk to it.
#
# Two rules make this worth having. Break either one and the bridge stops being a boundary:
#
#   1. Servers are INSTALLED HERE, PINNED. Not `npx -y <package>` or `uvx <package>` at runtime.
#      A runtime fetch means the container downloads and executes whatever the registry serves at
#      that moment, which is the supply-chain problem this file exists to contain — and it forces
#      the container to keep egress it would not otherwise need.
#
#   2. Every server gets ITS OWN VIRTUALENV. mcp-proxy and the servers both depend on `mcp`, so
#      installing a server into the proxy's environment can move that dependency underneath it.
#      (Tried it: the proxy came up and every session died with "Connection closed".)
FROM ghcr.io/sparfenyuk/mcp-proxy:v0.12.0

# The user is created BEFORE anything is installed, and nothing is chowned afterwards.
#
# A trailing `chown -R bridge:bridge /opt/mcp` looks free and is not: chown rewrites every
# inode, and on an overlay filesystem that copies the whole tree into a new layer, so the image
# carried two copies of every server. It cost 59 MB here — a quarter of the image — for a
# permission bit. The installs leave world-readable files, the process only ever reads them,
# and the compose service mounts the root filesystem read-only regardless.
RUN adduser -D -u 65532 bridge

# One venv per server. Add your own the same way, always with a pinned version.
#
# `time` is the default because it needs no network at all, so it works under the locked-down
# `mcp-bridge` network the compose service uses (see docker-compose.yml). It is also the gap it
# fills that comes up most: a model has no idea what today's date is.
RUN python3 -m venv /opt/mcp/time \
 && /opt/mcp/time/bin/pip install --no-cache-dir mcp-server-time==2026.7.10

# A server that needs the internet — note this one cannot work until the bridge is given egress,
# which is a decision the compose file makes you take deliberately:
#
#   RUN python3 -m venv /opt/mcp/fetch \
#    && /opt/mcp/fetch/bin/pip install --no-cache-dir mcp-server-fetch==2026.7.10
#
# For npm-delivered servers, add node here and install the package at BUILD time:
#
#   RUN apk add --no-cache nodejs npm \
#    && npm install -g --prefix /opt/mcp/filesystem @modelcontextprotocol/server-filesystem@2025.8.21
#
# then point the config at /opt/mcp/filesystem/bin/mcp-server-filesystem.

# The upstream image runs as root and nothing here needs to. The compose service drops
# capabilities and mounts the root filesystem read-only on top of this.
USER bridge

ENTRYPOINT ["catatonit", "--", "mcp-proxy"]

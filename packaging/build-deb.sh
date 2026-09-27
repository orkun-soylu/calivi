#!/bin/bash
# Builds the calivi .deb for one distribution (#95):
#
#   packaging/build-deb.sh [--distro trixie|noble|resolute]   (default: trixie)
#     → packaging/out/calivi_<version>-<rev>+<tag>_amd64.deb
#
# Needs Docker, and npm or Docker for the frontend. The venv is built inside the distribution's
# own image, at the path it runs from (/opt/calivi/venv). Its compiled wheels are tied to that
# distribution's Python, so the package depends on exactly that minor version — one .deb per
# distribution, each in its own APT suite. The version suffix (+deb13, +ubuntu24.04, …) keeps
# the three apart; "+" rather than "~" so the file name is safe in URLs and release assets.
set -euo pipefail

DISTRO=trixie
while [ $# -gt 0 ]; do
    case $1 in
        --distro) DISTRO=$2; shift 2 ;;
        *) echo "usage: $0 [--distro trixie|noble|resolute]" >&2; exit 2 ;;
    esac
done
case $DISTRO in
    trixie) IMAGE=debian:trixie TAG=deb13 ;;
    noble) IMAGE=ubuntu:24.04 TAG=ubuntu24.04 ;;
    resolute) IMAGE=ubuntu:26.04 TAG=ubuntu26.04 ;;
    *) echo "unsupported distribution: $DISTRO" >&2; exit 2 ;;
esac

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$REPO/packaging/out}
REVISION=${DEB_REVISION:-1}
VERSION=$(sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p' "$REPO/frontend/package.json" | head -1)
DEB_VERSION="$VERSION-$REVISION+$TAG"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/root"

echo "== frontend"
if command -v npm >/dev/null; then
    (cd "$REPO/frontend" && npm ci --silent && npm run build --silent)
else
    docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$REPO/frontend:/src" -w /src \
        node:22-alpine sh -c 'npm ci --silent && npm run build --silent'
fi

echo "== layout"
A="$REPO/appliance"
install -d "$ROOT/opt/calivi/backend" "$ROOT/usr/sbin" "$ROOT/usr/lib/calivi" "$ROOT/usr/lib/systemd/system" \
    "$ROOT/usr/share/calivi" "$ROOT/etc/calivi" "$ROOT/etc/sudoers.d" "$ROOT/etc/cloud/cloud.cfg.d" "$ROOT/etc/needrestart/conf.d" \
    "$ROOT/DEBIAN"
cp -r "$REPO/backend/app" "$REPO/backend/requirements.txt" "$ROOT/opt/calivi/backend/"
find "$ROOT/opt/calivi/backend" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$REPO/frontend/dist" "$ROOT/opt/calivi/frontend"
install -m 0644 "$REPO/frontend/nginx.conf" "$ROOT/opt/calivi/frontend/nginx.conf.source"
install -m 0755 "$A/bootstrap/calivi_bootstrap_user.py" "$ROOT/usr/sbin/calivi-bootstrap-user"
install -m 0755 "$A/files/firstboot" "$A/files/configure" "$ROOT/usr/lib/calivi/"
install -m 0644 "$A/files/calivi.service" "$A/files/calivi-firstboot.service" "$A/files/calivi-firstboot.path" \
    "$ROOT/usr/lib/systemd/system/"
install -m 0644 "$A/files/tools.yml" "$ROOT/usr/share/calivi/tools.yml"
install -m 0644 "$A/files/calivi.env" "$ROOT/etc/calivi/calivi.env"
install -m 0440 "$A/files/sudoers-calivi" "$ROOT/etc/sudoers.d/70-calivi-bootstrap"
install -m 0644 "$A/files/cloud-calivi.cfg" "$ROOT/etc/cloud/cloud.cfg.d/90-calivi.cfg"
install -m 0644 "$A/files/needrestart-calivi.conf" "$ROOT/etc/needrestart/conf.d/calivi.conf"
install -m 0644 "$REPO/packaging/debian/conffiles" "$ROOT/DEBIAN/"
install -m 0755 "$REPO/packaging/debian/preinst" "$REPO/packaging/debian/postinst" \
    "$REPO/packaging/debian/prerm" "$REPO/packaging/debian/postrm" "$ROOT/DEBIAN/"

echo "== venv + package ($IMAGE)"
mkdir -p "$OUT"
docker run --rm -v "$WORK:/work" -v "$OUT:/out" -v "$REPO/packaging/debian/control.in:/control.in:ro" \
    -e DEB_VERSION="$DEB_VERSION" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" "$IMAGE" bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends python3-venv >/dev/null
    # Built at the path it will run from: a venv hard-codes its own location.
    python3 -m venv /opt/calivi/venv
    /opt/calivi/venv/bin/pip install -q --no-cache-dir --only-binary=:all: -r /work/root/opt/calivi/backend/requirements.txt
    /opt/calivi/venv/bin/pip uninstall -q -y pip
    cp -a /opt/calivi/venv /work/root/opt/calivi/venv
    # The service account cannot write __pycache__ under a root-owned tree, so compile here —
    # recorded with the runtime path, for readable tracebacks.
    python3 -m compileall -q -d /opt/calivi/backend/app /work/root/opt/calivi/backend/app
    size=$(du -sk --exclude=DEBIAN /work/root | cut -f1)
    py=$(python3 -c "import sys; print(\"%d.%d\" % sys.version_info[:2])")
    pynext=$(python3 -c "import sys; print(\"%d.%d\" % (sys.version_info[0], sys.version_info[1] + 1))")
    sed -e "s/@VERSION@/$DEB_VERSION/" -e "s/@SIZE@/$size/" -e "s/@PY@/$py/" -e "s/@PYNEXT@/$pynext/" \
        /control.in > /work/root/DEBIAN/control
    dpkg-deb --root-owner-group -Zxz --build /work/root "/out/calivi_${DEB_VERSION}_amd64.deb" >/dev/null
    chown "$HOST_UID:$HOST_GID" "/out/calivi_${DEB_VERSION}_amd64.deb"
    chown -R "$HOST_UID:$HOST_GID" /work  # the pyc files above are root-owned; let the trap clean up
'
DEB="$OUT/calivi_${DEB_VERSION}_amd64.deb"
(cd "$OUT" && sha256sum "$(basename "$DEB")" > "$(basename "$DEB").sha256")
ls -lh "$DEB"

#!/bin/sh
# Installs calivi-vm onto a Debian 13 system: Calivi natively (systemd + nginx on :80), the
# `calivi` service account, and the machine-owner bootstrap. Run as root with the staged tree
# at /opt/calivi (backend/, frontend/, appliance/). build.sh runs it inside the image; it also
# works on an existing Debian 13 VM, and running it again updates Calivi in place.
set -eu

SRC=/opt/calivi
ETC=/etc/calivi
export DEBIAN_FRONTEND=noninteractive

[ "$(id -u)" = 0 ] || { echo "install.sh: run as root" >&2; exit 1; }
if [ ! -d "$SRC/backend/app" ] || [ ! -f "$SRC/frontend/index.html" ]; then
    echo "install.sh: expected the staged tree at $SRC (backend/, frontend/ built)" >&2
    exit 1
fi

apt-get update -q
apt-get install -y -q --no-install-recommends \
    nginx python3-venv sudo qemu-guest-agent ca-certificates curl

# Backend virtualenv. --only-binary for the same reason as the Dockerfile: a missing wheel
# should fail the build loudly, not start a silent source build.
[ -x "$SRC/venv/bin/python" ] || python3 -m venv "$SRC/venv"
"$SRC/venv/bin/pip" install -q --no-cache-dir --only-binary=:all: -r "$SRC/backend/requirements.txt"

# The files the .deb (packaging/) installs, at the same paths, so the package can later take
# over an image's install without leftovers.
install -d -m 0755 "$ETC" /usr/lib/calivi /usr/share/calivi
install -m 0644 "$SRC/appliance/files/calivi.env" "$ETC/calivi.env"
install -m 0755 "$SRC/appliance/bootstrap/calivi_bootstrap_user.py" /usr/sbin/calivi-bootstrap-user
install -m 0440 "$SRC/appliance/files/sudoers-calivi" /etc/sudoers.d/70-calivi-bootstrap
install -m 0755 "$SRC/appliance/files/firstboot" "$SRC/appliance/files/configure" /usr/lib/calivi/
install -m 0644 "$SRC/appliance/files/tools.yml" /usr/share/calivi/tools.yml
install -m 0644 "$SRC/appliance/files/calivi.service" \
    "$SRC/appliance/files/calivi-firstboot.service" \
    "$SRC/appliance/files/calivi-firstboot.path" /usr/lib/systemd/system/
[ -d /etc/cloud/cloud.cfg.d ] && install -m 0644 "$SRC/appliance/files/cloud-calivi.cfg" /etc/cloud/cloud.cfg.d/90-calivi.cfg

# Everything else — account, data dirs, nginx site, units, (re)start — is shared with the .deb.
sh /usr/lib/calivi/configure
echo "install.sh: done"

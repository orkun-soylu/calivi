#!/bin/sh
# Installs calivi-vm onto a Debian 13 system: Calivi natively (systemd + nginx on :80), the
# `calivi` service account, and the machine-owner bootstrap. Run as root with the staged tree
# at /opt/calivi (backend/, frontend/, appliance/). build.sh runs it inside the image; it also
# works on an existing Debian 13 VM, and running it again updates Calivi in place.
set -eu

SRC=/opt/calivi
DATA=/var/lib/calivi
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

# The service account. No shell, no password; its home is the data directory.
id calivi >/dev/null 2>&1 || \
    useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin --user-group calivi

# Backend virtualenv. --only-binary for the same reason as the Dockerfile: a missing wheel
# should fail the build loudly, not start a silent source build.
[ -x "$SRC/venv/bin/python" ] || python3 -m venv "$SRC/venv"
"$SRC/venv/bin/pip" install -q --no-cache-dir --only-binary=:all: -r "$SRC/backend/requirements.txt"

install -d -m 0750 -o calivi -g calivi "$DATA" "$DATA/config"
for f in search.yml vision_models.yml; do
    [ -e "$DATA/config/$f" ] || install -m 0640 -o calivi -g calivi "$SRC/backend/app/defaults/$f" "$DATA/config/$f"
done
[ -e "$DATA/config/system_prompts.yml" ] || \
    install -m 0640 -o calivi -g calivi "$SRC/backend/app/defaults/system_prompts.yml" "$DATA/config/system_prompts.yml"
[ -e "$DATA/config/tools.yml" ] || \
    install -m 0640 -o calivi -g calivi "$SRC/appliance/files/tools.yml" "$DATA/config/tools.yml"

install -d -m 0755 "$ETC"
install -m 0644 "$SRC/appliance/files/calivi.env" "$ETC/calivi.env"

# The bootstrap helper and the one sudoers line that lets the service account run it.
install -m 0755 "$SRC/appliance/bootstrap/calivi_bootstrap_user.py" /usr/local/sbin/calivi-bootstrap-user
install -m 0440 "$SRC/appliance/files/sudoers-calivi" /etc/sudoers.d/70-calivi-bootstrap
visudo -cf /etc/sudoers.d/70-calivi-bootstrap >/dev/null

install -d -m 0755 /usr/local/lib/calivi
install -m 0755 "$SRC/appliance/files/firstboot" /usr/local/lib/calivi/firstboot
install -m 0644 "$SRC/appliance/files/calivi.service" \
    "$SRC/appliance/files/calivi-firstboot.service" \
    "$SRC/appliance/files/calivi-firstboot.path" /etc/systemd/system/
[ -d /etc/cloud/cloud.cfg.d ] && install -m 0644 "$SRC/appliance/files/cloud-calivi.cfg" /etc/cloud/cloud.cfg.d/90-calivi.cfg

# nginx: derived from the Docker frontend's config, so the CSP and the proxy timeouts have a
# single source. Each substitution must hit, or the build stops — silent drift here would ship
# a site that proxies to a hostname that does not exist.
conf=$(cat "$SRC/frontend/nginx.conf.source")
for pat in 'http://calivi-backend:8000' '/usr/share/nginx/html' 'listen 80;'; do
    printf '%s' "$conf" | grep -qF "$pat" || { echo "install.sh: nginx.conf no longer contains '$pat'" >&2; exit 1; }
done
printf '%s\n' "$conf" \
    | sed -e 's#http://calivi-backend:8000#http://127.0.0.1:8000#g' \
          -e 's#/usr/share/nginx/html#/opt/calivi/frontend#g' \
          -e 's#listen 80;#listen 80 default_server;\n    listen [::]:80 default_server;#' \
    > /etc/nginx/sites-available/calivi
ln -sf /etc/nginx/sites-available/calivi /etc/nginx/sites-enabled/calivi
rm -f /etc/nginx/sites-enabled/default
nginx -t -q

systemctl daemon-reload
systemctl enable -q calivi-firstboot.service calivi-firstboot.path calivi.service nginx qemu-guest-agent
# On a live system (not inside the image build) bring it up now.
if [ -d /run/systemd/system ]; then
    systemctl start calivi-firstboot.service calivi-firstboot.path
    systemctl restart calivi.service nginx
fi
echo "install.sh: done"

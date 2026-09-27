#!/bin/bash
# Builds the calivi-vm image: Debian 13 genericcloud + Calivi installed natively.
#
#   appliance/build.sh            → appliance/out/calivi-vm-<version>.qcow2 (+ .sha256)
#
# Needs an x86-64 Debian/Ubuntu host with libguestfs-tools, qemu-utils, curl, and either npm
# or docker (for the frontend build). /dev/kvm makes it minutes instead of tens of minutes.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$REPO/appliance/out}
CACHE=${CACHE:-$REPO/appliance/.cache}
BASE_URL=${BASE_URL:-https://cloud.debian.org/images/cloud/trixie/latest}
BASE=debian-13-genericcloud-amd64.qcow2
DISK_SIZE=${DISK_SIZE:-32G}
VERSION=$(sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p' "$REPO/frontend/package.json" | head -1)
IMAGE="$OUT/calivi-vm-$VERSION.qcow2"

mkdir -p "$OUT" "$CACHE"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== base image"
curl -fsSL -o "$CACHE/SHA512SUMS" "$BASE_URL/SHA512SUMS"
if ! (cd "$CACHE" && grep " $BASE\$" SHA512SUMS | sha512sum -c --status 2>/dev/null); then
    curl -fL -o "$CACHE/$BASE" "$BASE_URL/$BASE"
    (cd "$CACHE" && grep " $BASE\$" SHA512SUMS | sha512sum -c)
fi

echo "== frontend"
if command -v npm >/dev/null; then
    (cd "$REPO/frontend" && npm ci --silent && npm run build --silent)
else
    docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$REPO/frontend:/src" -w /src \
        node:22-alpine sh -c 'npm ci --silent && npm run build --silent'
fi

echo "== stage"
STAGE="$WORK/calivi"
mkdir -p "$STAGE/backend" "$STAGE/appliance"
cp -r "$REPO/backend/app" "$REPO/backend/requirements.txt" "$STAGE/backend/"
find "$STAGE/backend" -name __pycache__ -prune -exec rm -rf {} +
cp -r "$REPO/frontend/dist" "$STAGE/frontend"
cp "$REPO/frontend/nginx.conf" "$STAGE/frontend/nginx.conf.source"
cp -r "$REPO/appliance/bootstrap" "$REPO/appliance/files" "$REPO/appliance/install.sh" "$STAGE/appliance/"

echo "== customize"
cp "$CACHE/$BASE" "$WORK/disk.qcow2"
qemu-img resize -q "$WORK/disk.qcow2" "$DISK_SIZE"
# The genericcloud root is ~3 GB; the first step grows it inside the build so the install has
# room. cloud-init grows it again to whatever size the VM's disk is given.
steps=(
    --run-command 'growpart /dev/sda 1 && resize2fs /dev/sda1'
    --copy-in "$STAGE:/opt"
    --run "$REPO/appliance/install.sh"
    # The cloud kernel leaves out most hardware drivers — including the GPU ones a passed-through
    # card needs. The standard kernel replaces it.
    --run-command 'apt-get install -y -q linux-image-amd64 && apt-get purge -y -q linux-image-cloud-amd64 "linux-image-*-cloud-amd64"'
    --run-command 'apt-get autoremove -y -q && apt-get clean && rm -rf /var/lib/apt/lists/*'
    # Every clone must get its own identity: machine-id and cloud-init's first-boot state. The
    # per-machine secrets are created by calivi-firstboot, never in the image.
    --run-command 'truncate -s 0 /etc/machine-id && rm -f /var/lib/dbus/machine-id && cloud-init clean --logs'
    --run-command 'rm -f /etc/calivi/secret.env /etc/calivi/setup-code /etc/calivi/host-user /etc/calivi/bootstrap.lock'
)
virt-customize -a "$WORK/disk.qcow2" --network --memsize 2048 --smp 2 "${steps[@]}"

echo "== compress"
qemu-img convert -q -O qcow2 -c "$WORK/disk.qcow2" "$IMAGE"
(cd "$OUT" && sha256sum "$(basename "$IMAGE")" > "$(basename "$IMAGE").sha256")
ls -lh "$IMAGE"

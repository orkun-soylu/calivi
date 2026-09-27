#!/bin/bash
# Builds the calivi-vm image: Debian 13 genericcloud + the calivi package.
#
#   appliance/build.sh [--deb calivi_X.Y.Z-N+deb13_amd64.deb]
#     → appliance/out/calivi-vm-<version>.qcow2 (+ .sha256)
#
# The image installs Calivi the one way every other machine does: `apt install` of the Debian
# 13 package, which also brings the apt.calivi.ai source and key, so a VM from the image updates
# with `apt upgrade`. For a release, pass the release's own +deb13 asset — the image then holds
# exactly the bytes that were tested and published. Without --deb, the package is built first
# (packaging/build-deb.sh --distro trixie).
#
# Needs an x86-64 Debian/Ubuntu host with libguestfs-tools, qemu-utils, curl, and Docker (and
# npm or Docker for the frontend) when it builds the package. /dev/kvm makes it minutes instead
# of tens of minutes.
set -euo pipefail

DEB=
while [ $# -gt 0 ]; do
    case $1 in
        --deb) DEB=$(realpath "$2"); shift 2 ;;
        *) echo "usage: $0 [--deb calivi_….deb]" >&2; exit 2 ;;
    esac
done

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-$REPO/appliance/out}
CACHE=${CACHE:-$REPO/appliance/.cache}
BASE_URL=${BASE_URL:-https://cloud.debian.org/images/cloud/trixie/latest}
BASE=debian-13-genericcloud-amd64.qcow2
DISK_SIZE=${DISK_SIZE:-32G}

mkdir -p "$OUT" "$CACHE"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== base image"
curl -fsSL -o "$CACHE/SHA512SUMS" "$BASE_URL/SHA512SUMS"
if ! (cd "$CACHE" && grep " $BASE\$" SHA512SUMS | sha512sum -c --status 2>/dev/null); then
    curl -fL -o "$CACHE/$BASE" "$BASE_URL/$BASE"
    (cd "$CACHE" && grep " $BASE\$" SHA512SUMS | sha512sum -c)
fi

echo "== package"
if [ -z "$DEB" ]; then
    OUT="$WORK/deb" "$REPO/packaging/build-deb.sh" --distro trixie
    DEB=$(ls "$WORK"/deb/calivi_*+deb13_amd64.deb)
fi
case $(dpkg-deb -f "$DEB" Version) in
    *+deb13) ;;
    *) echo "build.sh: $DEB is not the Debian 13 package" >&2; exit 1 ;;
esac
# A VM's first boot runs apt (Proxmox's cloud-init upgrades packages), and apt treats a
# published package with the same version but other bytes as an upgrade: it would silently
# replace the image's Calivi with the published one. Found by booting such an image — the
# published 0.6.1 has no keyring, so it also broke the VM's updates. A build of an already
# published version must be that very package.
version=$(dpkg-deb -f "$DEB" Version)
published=$(curl -fsS --max-time 20 https://apt.calivi.ai/dists/trixie/main/binary-amd64/Packages 2>/dev/null \
    | awk -v v="$version" '/^Version: / {hit = ($2 == v)} hit && /^SHA256: / {print $2; exit}' || true)
if [ -n "$published" ] && [ "$published" != "$(sha256sum < "$DEB" | cut -d' ' -f1)" ]; then
    echo "build.sh: calivi $version is already published with other content." >&2
    echo "  Use the published package (--deb), or build with a new revision: DEB_REVISION=2 $0" >&2
    exit 1
fi
# The image is named after the package it carries, not after the checkout.
VERSION=$(dpkg-deb -f "$DEB" Version | sed 's/-[^-]*$//')
IMAGE="$OUT/calivi-vm-$VERSION.qcow2"
cp "$DEB" "$WORK/calivi.deb"

echo "== customize"
cp "$CACHE/$BASE" "$WORK/disk.qcow2"
qemu-img resize -q "$WORK/disk.qcow2" "$DISK_SIZE"
# The genericcloud root is ~3 GB; the first step grows it inside the build so the install has
# room. cloud-init grows it again to whatever size the VM's disk is given.
steps=(
    --run-command 'growpart /dev/sda 1 && resize2fs /dev/sda1'
    --copy-in "$WORK/calivi.deb:/var/tmp"
    # Recommends brings qemu-guest-agent. curl is what apt.calivi.ai's instructions and most
    # of what the model runs expect to find.
    --run-command 'apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q /var/tmp/calivi.deb curl && rm /var/tmp/calivi.deb'
    # A package from before 0.6.2 brings no APT source: its image would never update itself.
    --run-command 'test -s /etc/apt/sources.list.d/calivi.sources || { echo "build.sh: the package brings no APT source (0.6.2 or later needed)" >&2; exit 1; }'

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

#!/bin/bash
# A throwaway VM from a distribution's official cloud image, for the install tests (#95).
#
#   packaging/test/vm.sh start trixie|noble|resolute <dir>   boot it, wait until SSH and cloud-init are done
#   packaging/test/vm.sh stop <dir>
#
#   IMAGE=<qcow2>          boot this image (the calivi-vm image) instead of the distribution's
#   PACKAGE_UPGRADE=true   upgrade packages on first boot, as Proxmox's cloud-init does
#
# QEMU user networking, so nothing needs root beyond /dev/kvm: the guest's SSH and :80 are
# forwarded to 127.0.0.1:2222 and :8080, and the guest reaches the runner's 127.0.0.1 as
# 10.0.2.2 (the fake model server). The base image is cached in <dir>; the VM writes to an
# overlay on top of it. <dir>/ssh_config is what install_test.py connects with, and
# <dir>/console.log has the serial console when a boot goes wrong.
set -euo pipefail

cmd=${1:?usage: vm.sh start <distro> <dir> | stop <dir>}
case $cmd in
    stop)
        dir=${2:?}
        [ -f "$dir/qemu.pid" ] && kill "$(cat "$dir/qemu.pid")" 2>/dev/null || true
        exit 0 ;;
    start) distro=${2:?} dir=${3:?} ;;
    *) echo "unknown command: $cmd" >&2; exit 2 ;;
esac

case $distro in
    trixie) url=https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2 ;;
    noble|resolute) url=https://cloud-images.ubuntu.com/$distro/current/$distro-server-cloudimg-amd64.img ;;
    *) echo "unsupported distribution: $distro" >&2; exit 2 ;;
esac

mkdir -p "$dir"
if [ -n "${IMAGE:-}" ]; then
    base=$(realpath "$IMAGE")
else
    base="$dir/$distro-base.qcow2"
    [ -s "$base" ] || curl -fsSL --retry 3 -o "$base" "$url"
fi
qemu-img create -q -f qcow2 -F qcow2 -b "$base" "$dir/disk.qcow2" 32G

[ -f "$dir/id_ed25519" ] || ssh-keygen -q -t ed25519 -N "" -C calivi-ci -f "$dir/id_ed25519"
cat > "$dir/user-data" <<EOF
#cloud-config
users:
  - name: ci
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys: ["$(cat "$dir/id_ed25519.pub")"]
package_update: ${PACKAGE_UPGRADE:-false}
package_upgrade: ${PACKAGE_UPGRADE:-false}
EOF
printf 'instance-id: calivi-ci\nlocal-hostname: calivi-ci\n' > "$dir/meta-data"
cloud-localds "$dir/seed.iso" "$dir/user-data" "$dir/meta-data"

cat > "$dir/ssh_config" <<EOF
Host vm
    HostName 127.0.0.1
    Port 2222
    User ci
    IdentityFile $dir/id_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ConnectTimeout 5
EOF

qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp 2 -m 3072 \
    -drive file="$dir/disk.qcow2",if=virtio -drive file="$dir/seed.iso",if=virtio,format=raw \
    -netdev user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:8080-:80 \
    -device virtio-net-pci,netdev=n0 \
    -display none -serial file:"$dir/console.log" -daemonize -pidfile "$dir/qemu.pid"

for _ in $(seq 120); do
    ssh -F "$dir/ssh_config" vm true 2>/dev/null && break
    sleep 5
done
ssh -F "$dir/ssh_config" vm true || { echo "no SSH after 10 minutes"; tail -50 "$dir/console.log"; exit 1; }
# Ubuntu's first boot runs apt on its own (unattended-upgrades): wait for cloud-init, and the
# tests take the dpkg lock with a timeout.
ssh -F "$dir/ssh_config" vm 'sudo cloud-init status --wait >/dev/null || true; . /etc/os-release; echo "booted: $PRETTY_NAME"'

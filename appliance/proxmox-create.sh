#!/bin/bash
# Creates a calivi-vm VM from the image. Run on a Proxmox VE node, as root.
#
#   ./proxmox-create.sh <vmid> <calivi-vm-X.Y.Z.qcow2> [options]
#     --name NAME        (calivi)        --storage STORAGE (local-lvm)
#     --bridge BRIDGE    (vmbr0)         --cores N (4)   --memory MiB (8192)
#     --start
#
# q35 + OVMF without pre-enrolled keys: ready for GPU passthrough, and Secure Boot stays off so
# out-of-tree drivers (NVIDIA's DKMS module) load. Add the GPU afterwards with
# `qm set <vmid> --hostpci0 <mapping or address>,pcie=1`.
set -euo pipefail

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 2 ] || usage
VMID=$1 IMAGE=$(realpath "$2"); shift 2
NAME=calivi STORAGE=local-lvm BRIDGE=vmbr0 CORES=4 MEMORY=8192 START=0
while [ $# -gt 0 ]; do
    case $1 in
        --name) NAME=$2; shift 2 ;;
        --storage) STORAGE=$2; shift 2 ;;
        --bridge) BRIDGE=$2; shift 2 ;;
        --cores) CORES=$2; shift 2 ;;
        --memory) MEMORY=$2; shift 2 ;;
        --start) START=1; shift ;;
        *) usage ;;
    esac
done
[ -f "$IMAGE" ] || { echo "no such image: $IMAGE" >&2; exit 1; }

qm create "$VMID" --name "$NAME" --ostype l26 --machine q35 --bios ovmf \
    --cores "$CORES" --cpu host --memory "$MEMORY" \
    --net0 "virtio,bridge=$BRIDGE" --scsihw virtio-scsi-single --agent enabled=1 \
    --efidisk0 "$STORAGE:1,efitype=4m,pre-enrolled-keys=0" \
    --scsi0 "$STORAGE:0,import-from=$IMAGE,discard=on,ssd=1,iothread=1" \
    --ide2 "$STORAGE:cloudinit" --ipconfig0 ip=dhcp \
    --boot order=scsi0
echo "created VM $VMID ($NAME). Its console shows the address and the setup code."
[ "$START" = 1 ] && qm start "$VMID"
exit 0

# calivi-vm

A Proxmox VM image that boots straight into Calivi on `http://<vm-ip>/`, where the chat model
**operates the machine it runs on**: bash, file reads, writes and edits, the way a terminal
coding agent does, with Calivi's web UI in place of a terminal. Bring any model: Ollama on
the VM itself, a GPU passed through to it, another Ollama or OpenAI-compatible server, or a
cloud model.

Design and security notes: *Host tools* and *First registration on the appliance* in
[`ARCHITECTURE.md`](../ARCHITECTURE.md), and issue #78.

## Create the VM

Download `calivi-vm-X.Y.Z.qcow2` and `proxmox-create.sh` from the
[latest release](https://github.com/orkun-soylu/calivi/releases/latest) onto a Proxmox VE node,
check the image against its `.sha256`, and as root:

```sh
sha256sum -c calivi-vm-X.Y.Z.qcow2.sha256
chmod +x proxmox-create.sh
./proxmox-create.sh 900 calivi-vm-X.Y.Z.qcow2 --storage local-lvm --bridge vmbr0 --start
```

Or build the image yourself (below).

The VM is q35 + OVMF with Secure Boot off, 4 cores, 8 GB RAM and a 32 GB disk, and gets its
address by DHCP. Use the VM's Cloud-Init tab for a static address, and *Resize disk* for more
room (models are large). The partition grows on the next boot.

## Claim it

Open the VM's **console** in Proxmox. Above the login prompt it shows:

```
  Calivi:  http://192.0.2.10/
  Setup code:  ABCD-EFGH-JKLM-NPQR   (asked for when you create the first account)
```

Browse to the address and sign up with the code. That first account:

- becomes Calivi's super admin, **and** a Linux account on the VM with the same name and
  password, in `sudo`, with passwordless sudo;
- is the account the model's commands run as;
- can optionally set the hostname and timezone, and install an SSH public key (under
  *Machine settings*).

Registration then closes. The owner can reopen it in Settings. Other users only get plain chat:
the host tools are the owner's alone.

The code is the only thing that stops someone else on the LAN from claiming the machine first,
so claim it soon after it boots.

## Using it

Add a model server in Settings → Servers, turn on 🔧, and ask. Commands that destroy data, cut
network access or stop services wait for your approval. 🛡 next to 🔧 makes **every** tool call
wait. Commands time out after 120 s. For longer work the model runs the job detached and
checks on it later.

The approval rules catch the model's *mistakes*; they are not a sandbox. The account has
sudo, so the VM itself is the boundary. Snapshot it before large changes.

To install Ollama on the VM, ask the model to. For a GPU, add it to the VM
(`qm set <vmid> --hostpci0 <mapping>,pcie=1`) first, then ask the model to install the driver.

Plain HTTP on port 80 is meant for the LAN. To expose the machine further, put a TLS proxy in
front of it and set `COOKIE_SECURE=true` in `/etc/calivi/calivi.env`.

## Build the image

On an x86-64 Debian/Ubuntu host with `libguestfs-tools`, `qemu-utils`, and `npm` or Docker
(`/dev/kvm` makes it minutes instead of tens of minutes):

```sh
appliance/build.sh        # → appliance/out/calivi-vm-<version>.qcow2 (+ .sha256)
```

It verifies the Debian 13 genericcloud image against Debian's SHA512SUMS, builds the frontend,
runs [`install.sh`](install.sh) inside the image, swaps the cloud kernel for the standard one
(the cloud kernel has no GPU drivers), and resets the machine identity. Secrets are never in the
image: the session key and the setup code are generated on each VM's first boot.

`install.sh` also works on an existing Debian 13 machine. Stage the tree at `/opt/calivi` the
way `build.sh` does, then run it as root. Running it again updates Calivi in place and keeps
`/var/lib/calivi`.

## Updating

Calivi is a Debian package, `calivi`. Each release has `calivi_X.Y.Z-N_amd64.deb` attached. On
the VM:

```sh
curl -fLO https://github.com/orkun-soylu/calivi/releases/download/vX.Y.Z/calivi_X.Y.Z-1_amd64.deb
sudo apt install ./calivi_X.Y.Z-1_amd64.deb
```

That works on an image from before the package too (0.3–0.5): the package takes over its files,
and your chats and settings in `/var/lib/calivi` stay. If a reply is running, the restart waits
for it, up to 30 minutes. A signed APT repository, so that `apt upgrade` picks new versions up
by itself, is planned (#95). To go back, `apt install` the older `.deb`. Removing the package
keeps `/var/lib/calivi`, even on `purge`.

To build the package yourself: `packaging/build-deb.sh` (needs Docker).

## Where things are

| | |
|---|---|
| `/opt/calivi` | Calivi (backend, built frontend, venv) |
| `/var/lib/calivi` | database and editable config (`config/*.yml`) — back this up |
| `/etc/calivi/calivi.env` | settings; `secret.env` holds the per-machine key |
| `calivi.service`, `nginx` | `journalctl -u calivi` |

## If the first registration fails half-way

The helper creates its lock before changing anything and does not remove it on failure, so it
cannot run twice. There is no owner yet to log in as. Either set a user with a password or SSH
key in the VM's **Cloud-Init** tab and reboot, or run each command from the Proxmox host with
`qm guest exec <vmid> -- <command>`:

```sh
getent passwd <name>                     # did the account get created?
ls /etc/sudoers.d/ | grep calivi         # 70-… is the image's; 80-/90- are the owner's
sudo userdel -r <name>; sudo rm -f /etc/sudoers.d/80-calivi-host /etc/sudoers.d/90-calivi-owner
sudo rm -f /etc/calivi/bootstrap.lock    # then register again
```

#!/bin/bash
# Adds packages to the APT repository tree and signs it (#95). Stateless: the tree is the state.
#
#   packaging/apt/publish.sh <repo dir> <signing key fingerprint> <calivi_*.deb>...
#
# Needs the key in the current GNUPGHOME and apt-ftparchive (apt-utils). One suite per
# distribution, named by codename; the package's version suffix says which (+deb13 → trixie).
# Each suite keeps its newest KEEP versions, so a rollback is `apt install calivi=<version>`.
#
# Layout (served as-is by GitHub Pages at https://apt.calivi.ai):
#   index.html                                 how to add the repository, and the fingerprint
#   calivi.gpg, calivi.asc                     the public key (binary for Signed-By, armored)
#   pool/<suite>/calivi_<version>_amd64.deb
#   dists/<suite>/{Release,InRelease,Release.gpg}, dists/<suite>/main/binary-amd64/Packages{,.gz}
#
# Used for real by .github/workflows/apt.yml and, with a throwaway key, by the install tests.
set -euo pipefail
repo=${1:?usage: publish.sh <repo dir> <fingerprint> <deb>...} fpr=${2:?} ; shift 2
KEEP=${KEEP:-5}
here=$(cd "$(dirname "$0")" && pwd)
declare -A SUITE=([deb13]=trixie [ubuntu24.04]=noble [ubuntu26.04]=resolute)

# The fingerprint is pinned by the caller: a wrong key in the secret must stop here, not ship a
# repository signed by something the users' keyring does not trust.
gpg --batch --with-colons --list-secret-keys "$fpr" 2>/dev/null | grep -q "^fpr:::::::::$fpr:$" \
    || { echo "publish.sh: the signing key $fpr is not in the keyring" >&2; exit 1; }

for deb in "$@"; do
    version=$(dpkg-deb -f "$deb" Version)
    suite=${SUITE[${version##*+}]:-}
    [ -n "$suite" ] || { echo "publish.sh: $deb: no suite for version $version" >&2; exit 1; }
    install -D -m 0644 "$deb" "$repo/pool/$suite/calivi_${version}_amd64.deb"
done

cd "$repo"
gpg --batch --yes --export "$fpr" > calivi.gpg
gpg --batch --yes --armor --export "$fpr" > calivi.asc
spaced=$(sed -E 's/(.{4})/\1 /g; s/ $//' <<<"$fpr")
sed "s/@FPR_SPACED@/$spaced/g" "$here/index.html.in" > index.html

for suite in "${SUITE[@]}"; do
    [ -d "pool/$suite" ] || continue
    # Oldest first by version (sort -V is right for X.Y.Z-N+tag); drop all but the newest KEEP.
    mapfile -t debs < <(ls "pool/$suite"/*.deb | sort -V)
    for old in "${debs[@]:0:$(( ${#debs[@]} > KEEP ? ${#debs[@]} - KEEP : 0 ))}"; do
        rm -f "$old"
    done

    dist=dists/$suite
    rm -rf "$dist"
    mkdir -p "$dist/main/binary-amd64"
    apt-ftparchive packages "pool/$suite" > "$dist/main/binary-amd64/Packages"
    gzip -9nk "$dist/main/binary-amd64/Packages"
    apt-ftparchive \
        -o APT::FTPArchive::Release::Origin=Calivi \
        -o APT::FTPArchive::Release::Label=Calivi \
        -o APT::FTPArchive::Release::Suite="$suite" \
        -o APT::FTPArchive::Release::Codename="$suite" \
        -o APT::FTPArchive::Release::Architectures=amd64 \
        -o APT::FTPArchive::Release::Components=main \
        -o APT::FTPArchive::Release::Description="Calivi for $suite" \
        release "$dist" > "$dist/Release.tmp"
    mv "$dist/Release.tmp" "$dist/Release"
    gpg --batch --yes --local-user "$fpr" --digest-algo SHA512 --clearsign -o "$dist/InRelease" "$dist/Release"
    gpg --batch --yes --local-user "$fpr" --digest-algo SHA512 -abs -o "$dist/Release.gpg" "$dist/Release"
    echo "$suite: $(grep -c '^Package:' "$dist/main/binary-amd64/Packages") package(s)"
done

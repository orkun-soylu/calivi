#!/bin/bash
# Downloads the newest earlier release's .deb for one distribution, for the upgrade test (#95).
#
#   packaging/test/previous-release.sh <tag: deb13|ubuntu24.04|ubuntu26.04> <this build's version> <dir>
#
# "Earlier" means a lower package version than this build's, by dpkg's rules: a pull request
# that has not bumped the version yet still upgrades from the release it will follow, and the
# release being tested (whose own assets may already be attached) from the one before.
# Prints the downloaded path, or nothing when no release has a package for this distribution
# (Ubuntu before 0.6.1). Needs `gh` with a token that can read the repository's releases.
set -euo pipefail
tag=${1:?} built=${2:?} dir=${3:?}

for release in $(gh release list --exclude-drafts --exclude-pre-releases -L 30 --json tagName -q '.[].tagName'); do
    names=$(gh release view "$release" --json assets -q '.assets[].name')
    asset=$(printf '%s\n' "$names" | grep -E "^calivi_.*\+${tag//./\\.}_amd64\.deb$" | head -1 || true)
    # 0.6.0 shipped one package, for Debian 13, before the suffixes existed.
    if [ -z "$asset" ] && [ "$tag" = deb13 ]; then
        asset=$(printf '%s\n' "$names" | grep -E '^calivi_[^+]*_amd64\.deb$' | head -1 || true)
    fi
    version=${asset#calivi_}
    version=${version%_amd64.deb}
    if [ -n "$asset" ] && dpkg --compare-versions "$version" lt "$built"; then
        mkdir -p "$dir"
        gh release download "$release" -p "$asset" -D "$dir" --clobber
        echo "$dir/$asset"
        exit 0
    fi
done

#!/usr/bin/env bash
# Deploy a commit of the company repo, pulled on the VM itself.
#
#   ssh azureuser@20.205.178.161 'bash ~/payint-src/deploy/cloudunity/deploy-from-git.sh autonomous-modernization'
#
# The first run needs the checkout (and after that the script updates itself):
#   git clone git@github-payint:BTGit-India/beeonix-payint.git ~/payint-src
# `github-payint` is an ~/.ssh/config alias for the read-only deploy key
# ~/.ssh/payint_deploy (registered under the repo's Settings -> Deploy keys).
#
# It packs the same four trees pack-release.sh packs on the laptop, from
# `git archive <sha>` (never a working tree), and runs the same rollout. The
# marketing site (Site/) is built from the same commit, in a pinned Node
# container, and released with it; a site.tgz passed as the second argument
# is released instead. A commit without Site/ leaves the live site as it is.
set -euo pipefail

REF=${1:?usage: deploy-from-git.sh <branch|tag|sha> [site.tgz]}
SITE=${2:-}
SRC=${PAYINT_SRC:-$HOME/payint-src}
REPO=${PAYINT_REPO:-git@github-payint:BTGit-India/beeonix-payint.git}

[ -d "$SRC/.git" ] || git clone -q "$REPO" "$SRC"
git -C "$SRC" fetch -q --prune origin
SHA=$(git -C "$SRC" rev-parse --verify -q "origin/$REF^{commit}" || git -C "$SRC" rev-parse --verify "$REF^{commit}")
SHORT=$(git -C "$SRC" rev-parse --short=12 "$SHA")
echo "deploying $REF @ $SHORT"

for t in Habibi backend agentstudio; do
  git -C "$SRC" archive --format=tar.gz -o "/tmp/${t,,}.tgz" "$SHA" "$t"
done
tmp=$(mktemp -d)
git -C "$SRC" archive --format=tar "$SHA" deploy | tar -xf - -C "$tmp"
printf '%s %s\n' "$SHORT" "$REF" > "$tmp/deploy/cloudunity/RELEASE_SHA"
tar -czf /tmp/deploy.tgz -C "$tmp" deploy
cp "$tmp/deploy/cloudunity/voice-studio-rollout.sh" /tmp/voice-studio-rollout.sh
rm -rf "$tmp"

# A site.tgz left in /tmp by an earlier laptop deploy is not what this commit
# describes: release the one named, else the one this commit builds, else none.
rm -f /tmp/site.tgz.next
if [ -n "$SITE" ]; then
  [ "$SITE" -ef /tmp/site.tgz ] || cp "$SITE" /tmp/site.tgz
elif git -C "$SRC" cat-file -e "$SHA:Site/package.json" 2>/dev/null; then
  build=$(mktemp -d)
  git -C "$SRC" archive --format=tar "$SHA" Site | tar -xf - -C "$build"
  echo "building the marketing site from $SHORT"
  if docker run --rm --memory=2g --cpus=2 -v "$build/Site:/app" -w /app node:22-bookworm \
       sh -c 'npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null' &&
     tar -czf /tmp/site.tgz.next -C "$build/Site/dist/client" .; then
    mv /tmp/site.tgz.next /tmp/site.tgz
  else
    # The site is independent of the app: a failed build keeps the old site.
    echo "marketing site build FAILED; the live site is left as it is" >&2
    rm -f /tmp/site.tgz /tmp/site.tgz.next
  fi
  # The container wrote as root; clear the build tree the same way.
  docker run --rm -v "$build:/b" node:22-bookworm rm -rf /b/Site >/dev/null 2>&1 || true
  rm -rf "$build"
else
  rm -f /tmp/site.tgz
fi

exec bash /tmp/voice-studio-rollout.sh

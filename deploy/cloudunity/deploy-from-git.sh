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
# marketing site (Site/) is not in git: it is left as it is unless a fresh
# site.tgz is passed as the second argument.
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
# describes; release a site only when one is named.
if [ -z "$SITE" ]; then
  rm -f /tmp/site.tgz
elif ! [ "$SITE" -ef /tmp/site.tgz ]; then
  cp "$SITE" /tmp/site.tgz
fi

exec bash /tmp/voice-studio-rollout.sh

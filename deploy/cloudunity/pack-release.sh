#!/usr/bin/env bash
# Pack the four trees voice-studio-rollout.sh expects, into ./dist/.
#
# Run from the repo root on the laptop. The rollout overlays whole trees, so
# what is packed here is exactly what the server will run: it is packed from a
# clean checkout of HEAD (`git archive`), never from the working tree, so a
# half-finished edit cannot reach the VM by accident.
#
#   bash deploy/cloudunity/pack-release.sh
#   scp -i <key> dist/*.tgz azureuser@20.205.178.161:/tmp/
#   ssh -i <key> azureuser@20.205.178.161 'bash /tmp/deploy-run.sh'
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
OUT=dist
mkdir -p "$OUT"

if ! git diff-index --quiet HEAD --; then
  echo "working tree is dirty; commit or stash before packing a release" >&2
  git status --short | head -20 >&2
  exit 1
fi

SHA=$(git rev-parse --short=12 HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "packing $BRANCH @ $SHA"

# The rollout reads this to stamp DEPLOYED_SHA. It rides inside deploy.tgz, so
# the stamp can never describe a different tree than the one that was shipped.
printf '%s %s\n' "$SHA" "$BRANCH" > "$OUT/RELEASE_SHA"

for tree in Habibi backend agentstudio deploy; do
  # `git archive` excludes everything gitignored — node_modules, .venv, .env,
  # dist/ itself — without needing a second exclude list to keep in sync.
  if [ "$tree" = deploy ]; then
    # RELEASE_SHA is generated, not committed, so it is added on top.
    tmp=$(mktemp -d)
    git archive --format=tar HEAD deploy | tar -xf - -C "$tmp"
    cp "$OUT/RELEASE_SHA" "$tmp/deploy/cloudunity/RELEASE_SHA"
    tar -czf "$OUT/$tree.tgz" -C "$tmp" deploy
    rm -rf "$tmp"
  else
    git archive --format=tar.gz -o "$OUT/$tree.tgz" HEAD "$tree"
  fi
  printf '  %-14s %s\n' "$tree.tgz" "$(du -h "$OUT/$tree.tgz" | cut -f1)"
done

# Lowercase name: the rollout extracts /tmp/habibi.tgz.
mv -f "$OUT/Habibi.tgz" "$OUT/habibi.tgz"

echo
echo "next:"
echo "  scp -i \"<key>\" $OUT/*.tgz deploy/cloudunity/voice-studio-rollout.sh azureuser@20.205.178.161:/tmp/"
echo "  ssh -i \"<key>\" azureuser@20.205.178.161 'bash /tmp/voice-studio-rollout.sh'"

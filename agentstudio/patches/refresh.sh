#!/usr/bin/env bash
# Regenerate agentstudio/patches/{engine,pipecat}.diff: our full delta against
# the pinned upstream (UPSTREAM.md). Run after changing anything under
# agentstudio/engine. Needs git and network access to github.com.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="$HERE/../engine"
TAG="dograh-v1.47.0"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone -q --depth 1 --branch "$TAG" https://github.com/dograh-hq/dograh.git "$WORK/dograh"
PIPECAT_SHA="$(git -C "$WORK/dograh" ls-tree HEAD pipecat | awk '{print $3}')"
git init -q "$WORK/pipecat"
git -C "$WORK/pipecat" fetch -q --depth 1 https://github.com/dograh-hq/pipecat.git "$PIPECAT_SHA"
git -C "$WORK/pipecat" checkout -q FETCH_HEAD
rm -rf "$WORK/dograh/.git" "$WORK/pipecat/.git"
rmdir "$WORK/dograh/pipecat" 2>/dev/null || true

# Line endings differ between checkouts (autocrlf); only content counts.
common=(--strip-trailing-cr --exclude=__pycache__ --exclude=node_modules --exclude=.pytest_cache)
( cd "$WORK" && diff -ruN "${common[@]}" --exclude=pipecat dograh "$ENGINE" ) \
  | sed "s#$ENGINE#engine#g" > "$HERE/engine.diff" || true
( cd "$WORK" && diff -ruN "${common[@]}" pipecat "$ENGINE/pipecat" ) \
  | sed "s#$ENGINE/pipecat#engine/pipecat#g" > "$HERE/pipecat.diff" || true

echo "engine.diff: $(grep -c '^diff -ruN' "$HERE/engine.diff") files; pipecat.diff: $(grep -c '^diff -ruN' "$HERE/pipecat.diff") files (pipecat $PIPECAT_SHA)"

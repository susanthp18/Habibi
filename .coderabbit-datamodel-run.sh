#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd /mnt/d/Hackathon

echo "=== validate ==="
coderabbit config validate .coderabbit-datamodel.yaml

ROOT=ccc807008047a276ddc058a19f5ffcad561615f3
COMMON=(
  review --agent
  --include-untracked
  --base-commit "$ROOT"
  -c .coderabbit-datamodel.yaml
  -c .coderabbit-datamodel-review.md
  -c backend/DATA_MODEL.md
)

echo "=== sql file estimate ==="
git diff --name-only "$ROOT"...HEAD -- backend/sql || true
git ls-files --others --exclude-standard -- backend/sql || true

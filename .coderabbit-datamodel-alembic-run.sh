#!/usr/bin/env bash
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd /mnt/d/Hackathon

echo "START $(date -Iseconds)"
set +e
coderabbit review --agent --include-untracked --base main \
  --dir backend/alembic \
  -c .coderabbit-datamodel.yaml \
  -c .coderabbit-datamodel-review.md \
  -c backend/DATA_MODEL.md \
  > .coderabbit-datamodel-alembic.jsonl 2> .coderabbit-datamodel-alembic.err
rc=$?
echo "EXIT:$rc" | tee -a .coderabbit-datamodel-alembic.err
echo "END $(date -Iseconds)" | tee -a .coderabbit-datamodel-alembic.err
exit $rc

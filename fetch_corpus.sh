#!/usr/bin/env bash
# Fetch the audited corpus at the exact commit the paper's numbers were produced from.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HERE/GRACE_whitepaper_data}"
COMMIT=7d28c4da0fe2850a654eff0b31a5ea02ac150c8a
if [ ! -d "$DEST/.git" ]; then
  git clone https://github.com/just5034/GRACE_whitepaper_data "$DEST"
fi
git -C "$DEST" fetch --quiet origin "$COMMIT" 2>/dev/null || true
git -C "$DEST" checkout --quiet "$COMMIT"
N=$(git -C "$DEST" ls-files | wc -l)
echo "corpus at $COMMIT, $N tracked files (paper: 1248)"
[ "$N" -eq 1248 ] || { echo "file count mismatch"; exit 1; }
echo "export GRACE_CORPUS=$DEST"

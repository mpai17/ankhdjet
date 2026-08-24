#!/usr/bin/env bash
# Cut the public-release history: a single parentless commit carrying the
# current tree, so the published repo starts at the release state while the
# full development history stays in the private record (backed up as a git
# bundle first; nothing is deleted or rewritten locally).
#
#   bash tools/cut_public_release.sh              # dry run: bundle + branch only
#   bash tools/cut_public_release.sh --push       # also force-push to origin master
#
# The visibility flip stays manual on purpose:
#   gh repo edit mpai17/ankhdjet --visibility public --accept-visibility-change-consequences
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

[ -z "$(git status --porcelain)" ] || { echo "ERROR: working tree not clean"; exit 1; }

STAMP=$(date -u +%Y%m%d)
BUNDLE="$REPO/../ankhdjet-private-history-$STAMP.bundle"
echo "== backing up ALL private history -> $BUNDLE =="
git bundle create "$BUNDLE" --all
git bundle verify "$BUNDLE" >/dev/null && echo "   bundle verified"

MSG="Ankhdjet public release: the ternary weights-to-masks compiler with its SKY130 signoff record, two TinyTapeout vehicles, and calibrated GF180MCU/ASAP7 estimators."
NEW=$(git commit-tree "HEAD^{tree}" -m "$MSG")
git branch -f public-release "$NEW"
echo "== release commit $NEW on branch public-release =="
git log --oneline -1 public-release
echo "   tree identical to HEAD: $(git diff --quiet HEAD public-release && echo yes || echo NO)"

if [ "${1:-}" = "--push" ]; then
  echo "== force-pushing public-release -> origin master =="
  git push --force origin public-release:master
  echo "   done; flip visibility manually when ready:"
else
  echo "== dry run complete; to publish =="
  echo "   bash tools/cut_public_release.sh --push"
fi
echo "   gh repo edit mpai17/ankhdjet --visibility public --accept-visibility-change-consequences"

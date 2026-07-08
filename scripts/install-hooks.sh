#!/bin/sh
# Point git at the committed hooks/ directory so the pre-commit hook
# (auto-refreshes generated docs + the I/O-contract snapshot) runs on every
# commit.  Run once per clone.
root=$(git rev-parse --show-toplevel) || exit 1
git -C "$root" config core.hooksPath hooks
chmod +x "$root/hooks/"* 2>/dev/null || true
echo "Installed git hooks (core.hooksPath=hooks). pre-commit now refreshes"
echo "README / docs/reference / registry/io_contracts.json automatically."

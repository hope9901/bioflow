#!/usr/bin/env bash
# Install a monthly cron entry for `bioflow update auto` (Linux / macOS).
#
# Run once; appends a single line to the invoking user's crontab.
# Fires at 02:30 on the 1st of every month.  Why cron and not a
# bioflow daemon?  The bioflow design forbids long-running services
# (Part 5).  cron is the OS-native primitive.
#
# Usage:
#     ./scripts/install-schedule-cron.sh                 # safe default (no auto-approve)
#     ./scripts/install-schedule-cron.sh --auto-approve  # approve passing candidates
#     ./scripts/install-schedule-cron.sh --real          # use the real DockerBackend
#     ./scripts/install-schedule-cron.sh --uninstall

set -euo pipefail

REPO_PATH="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(command -v python || command -v python3)"
MARKER="# bioflow-monthly-update"
AUTO_APPROVE=""
REAL=""
GIT_PUSH=""
GIT_REMOTE="origin"
UNINSTALL=""

for arg in "$@"; do
    case "$arg" in
        --auto-approve) AUTO_APPROVE="--auto-approve" ;;
        --real)         REAL="--real" ;;
        --git-push)     GIT_PUSH="--git-push" ;;
        --git-remote=*) GIT_REMOTE="${arg#*=}" ;;
        --uninstall)    UNINSTALL=1 ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

if [[ -n "$UNINSTALL" ]]; then
    current="$(crontab -l 2>/dev/null | grep -v "$MARKER" || true)"
    echo "$current" | crontab -
    echo "✓ Removed any '$MARKER' entries from crontab."
    exit 0
fi

if [[ ! -f "$REPO_PATH/bioflow/__init__.py" ]]; then
    echo "ERROR: REPO_PATH '$REPO_PATH' doesn't look like a bioflow checkout." >&2
    exit 1
fi

LOG_DIR="$REPO_PATH/update/cron.log"
GIT_FLAGS=""
if [[ -n "$GIT_PUSH" ]]; then
    GIT_FLAGS="$GIT_PUSH --git-remote $GIT_REMOTE"
fi
ARGS="update auto $AUTO_APPROVE $REAL $GIT_FLAGS --report $REPO_PATH/update/last_run.json"

# At 02:30 on the 1st of every month
CRON_LINE="30 2 1 * * cd $REPO_PATH && $PYTHON_BIN -m bioflow.cli $ARGS >> $LOG_DIR 2>&1  $MARKER"

# Replace any existing entry, append the new one
current="$(crontab -l 2>/dev/null | grep -v "$MARKER" || true)"
{ echo "$current"; echo "$CRON_LINE"; } | crontab -

echo "✓ Installed cron entry:"
echo "  $CRON_LINE"
echo ""
echo "Inspect with:  crontab -l"
echo "Log tail:      tail -f $LOG_DIR"
echo "Manual run:    cd $REPO_PATH && $PYTHON_BIN -m bioflow.cli $ARGS"

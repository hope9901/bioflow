#!/usr/bin/env bash
# Install / uninstall the weekly release-watch via user cron.
#
# Schedules:
#   0 8 * * 1  python -m update.release_watch   (Monday 08:00 by default)
#
# Set env var GITHUB_TOKEN for higher rate limit (5000/hr vs 60/hr).
#
# Usage:
#   ./scripts/install-schedule-cron-weekly.sh
#   ./scripts/install-schedule-cron-weekly.sh --time 08 00 --dow 1
#   ./scripts/install-schedule-cron-weekly.sh --uninstall

set -euo pipefail

HOUR=8
MINUTE=0
DOW=1     # Mon=1 … Sun=7 (or 0/7)
UNINSTALL=0
JOB_TAG="# bioflow-weekly-release-watch"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --time)      HOUR="$2"; MINUTE="$3"; shift 3 ;;
        --dow)       DOW="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        *)           echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$(command -v python3 || command -v python)"
CMD="cd ${REPO_ROOT} && ${PYTHON} -m update.release_watch >> update/notifications/release_watch.log 2>&1"
ENTRY="${MINUTE} ${HOUR} * * ${DOW} ${CMD}  ${JOB_TAG}"

current=$(crontab -l 2>/dev/null || true)
stripped=$(printf "%s\n" "$current" | grep -v -F "$JOB_TAG" || true)

if [[ "$UNINSTALL" -eq 1 ]]; then
    printf "%s\n" "$stripped" | crontab -
    echo "✓ Removed bioflow-weekly-release-watch cron entry."
    exit 0
fi

{ printf "%s\n" "$stripped"; echo "$ENTRY"; } | crontab -
echo "✓ Installed weekly release watch on DOW=${DOW} at ${HOUR}:$(printf %02d $MINUTE)."
echo "  Candidates → ${REPO_ROOT}/update/candidates/<YYYY-MM>/"

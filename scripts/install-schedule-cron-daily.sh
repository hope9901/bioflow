#!/usr/bin/env bash
# Install / uninstall the daily registry freshness check via user cron.
#
# Schedules:
#   0 6 * * *  python -m update.freshness_check
#
# Reports land at update/notifications/freshness-<YYYY-MM-DD>.md
#
# Usage:
#   ./scripts/install-schedule-cron-daily.sh                 # install at 06:00
#   ./scripts/install-schedule-cron-daily.sh --time 07 30    # custom HH MM
#   ./scripts/install-schedule-cron-daily.sh --uninstall

set -euo pipefail

HOUR=6
MINUTE=0
UNINSTALL=0
JOB_TAG="# bioflow-daily-freshness"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --time)      HOUR="$2"; MINUTE="$3"; shift 3 ;;
        --uninstall) UNINSTALL=1; shift ;;
        *)           echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$(command -v python3 || command -v python)"
CMD="cd ${REPO_ROOT} && ${PYTHON} -m update.freshness_check >> update/notifications/cron.log 2>&1"
ENTRY="${MINUTE} ${HOUR} * * * ${CMD}  ${JOB_TAG}"

current=$(crontab -l 2>/dev/null || true)
stripped=$(printf "%s\n" "$current" | grep -v -F "$JOB_TAG" || true)

if [[ "$UNINSTALL" -eq 1 ]]; then
    printf "%s\n" "$stripped" | crontab -
    echo "✓ Removed bioflow-daily-freshness cron entry."
    exit 0
fi

{ printf "%s\n" "$stripped"; echo "$ENTRY"; } | crontab -
echo "✓ Installed daily freshness check at ${HOUR}:$(printf %02d $MINUTE)."
echo "  Reports → ${REPO_ROOT}/update/notifications/"

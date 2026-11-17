#!/usr/bin/env bash
# supercronic 스케줄러가 안 떠 있으면 띄워요. 여러 번 실행해도 안전해요. (~/.bashrc, ~/.profile 에서 호출)
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
STATE=${TOKEN_USAGE_CRON_STATE:-/workspace/token-usage-cron}; mkdir -p "$STATE/logs"
exec 8>"$STATE/start.lock"; flock -n 8 || exit 0
pgrep -f "supercronic.* $HERE/crontab" >/dev/null && exit 0
nohup setsid "$HOME/.local/bin/supercronic" -quiet "$HERE/crontab" >>"$STATE/logs/supercronic.log" 2>&1 </dev/null 8>&- &

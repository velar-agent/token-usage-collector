#!/usr/bin/env bash
# supercronic 스케줄러가 안 떠 있으면 띄워요. 여러 번 실행해도 안전해요.
# 운영 수집은 GCE VM 의 시스템 cron 이 해요. 같은 로그인으로 두 곳에서 돌면 OAuth 토큰이 무효화될 수 있어서
# FORCE_START=1 일 때만 띄워요.
if [ "${FORCE_START:-}" != 1 ]; then
  echo "start-cron.sh: 수집은 GCE VM 에서 돌아요(README 참고). 정말 여기서 띄우려면 FORCE_START=1 로 실행하세요." >&2
  exit 1
fi
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
STATE=${TOKEN_USAGE_CRON_STATE:-/workspace/token-usage-cron}; mkdir -p "$STATE/logs"
exec 8>"$STATE/start.lock"; flock -n 8 || exit 0
pgrep -f "supercronic.* $HERE/crontab" >/dev/null && exit 0
nohup setsid "$HOME/.local/bin/supercronic" -quiet "$HERE/crontab" >>"$STATE/logs/supercronic.log" 2>&1 </dev/null 8>&- &

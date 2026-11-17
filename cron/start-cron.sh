#!/usr/bin/env bash
# token-usage-cron 스케줄러(supercronic)를 없으면 띄워요. 여러 번 실행해도 안전해요.
# 사용: start-cron.sh [--status|--stop|--restart]
set -u
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
STATE=${TOKEN_USAGE_CRON_STATE:-/workspace/token-usage-cron}
CRONTAB="$HERE/crontab"; LOGFILE="$STATE/logs/supercronic.log"
SC=$HOME/.local/bin/supercronic; mkdir -p "$STATE/logs"
procs(){ for p in $(pgrep -f -- "supercronic $CRONTAB" 2>/dev/null); do [[ $p != $$ ]] && echo "$p"; done; }
case "${1:-}" in
  --status) p=$(procs | tr '\n' ' '); [[ -n "${p// /}" ]] && { echo "running pid=${p% }"; exit 0; }; echo "not running"; exit 1 ;;
  --stop|--restart) for p in $(procs); do kill "$p"; done
    for _ in 1 2 3 4 5; do [[ -z "$(procs)" ]] && break; sleep 1; done
    for p in $(procs); do kill -9 "$p"; done; sleep 0.5
    [[ $1 == --stop ]] && { echo stopped; exit 0; } ;;
  "") ;;
  *) echo "usage: $0 [--status|--stop|--restart]" >&2; exit 2 ;;
esac
exec 8>"$STATE/start.lock"; flock -w 30 8 || exit 1
[[ -n "$(procs)" ]] && exit 0
"$SC" -test "$CRONTAB" >/dev/null 2>&1 || { echo "crontab 검증 실패" >&2; exit 1; }
nohup setsid "$SC" "$CRONTAB" >>"$LOGFILE" 2>&1 </dev/null 8>&- &
sleep 1; [[ -n "$(procs)" ]] && echo "started pid=$(procs | head -1)" || { echo "시작 실패, $LOGFILE 확인" >&2; exit 1; }

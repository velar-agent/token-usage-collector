#!/usr/bin/env bash
# 30분마다: 토큰 사용량 수집(collect-all.sh) → 대시보드 전송(log_raw.py)
# 겹쳐 실행되지 않게 flock 으로 막고, 결과는 logs/YYYY-MM-DD.log 에 남겨요.
set -u
export TZ=Asia/Seoul PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)   # 코드 위치(저장소 cron/)
REPO=$(dirname "$HERE")
STATE=${TOKEN_USAGE_CRON_STATE:-/workspace/token-usage-cron}   # 로그·알림 상태 등 실행 데이터
LOG="$STATE/logs/$(date +%F).log"; mkdir -p "$STATE/logs"
exec >>"$LOG" 2>&1
exec 9>"$STATE/run.lock"
flock -n 9 || { echo "$(date -Iseconds) SKIP 이전 실행이 아직 진행 중"; exit 0; }
echo "=== $(date -Iseconds) start"
rc=0
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
"$REPO/bin/collect-all.sh" 2>&1 | tee "$TMP/collect"; crc=${PIPESTATUS[0]}; [ $crc -ne 0 ] && rc=$crc
lrc=0; python3 "$REPO/bin/log_raw.py" 2>&1 | tee "$TMP/log"; lrc=${PIPESTATUS[0]}; [ $lrc -ne 0 ] && rc=$lrc
TOKEN_USAGE_CRON_STATE="$STATE" python3 "$HERE/alerts.py" "$TMP/collect" "$lrc" "$TMP/log"
echo "=== $(date -Iseconds) end rc=$rc"
# 14일 지난 로그 정리
find "$STATE/logs" -name '[0-9]*.log' -mtime +14 -delete
exit $rc

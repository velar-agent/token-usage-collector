#!/usr/bin/env bash
# 매 시 15분·45분마다: 토큰 사용량 수집(collect-all.sh) → 대시보드 전송(log_raw.py)
# 겹쳐 실행되지 않게 flock 으로 막고, 결과는 logs/YYYY-MM-DD.log 에 남겨요.
set -u
export TZ=Asia/Seoul PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)   # 코드 위치(저장소 cron/)
REPO=$(dirname "$HERE")
STATE=${TOKEN_USAGE_CRON_STATE:-/workspace/token-usage-cron}   # 로그 등 실행 데이터
LOG="$STATE/logs/$(date +%F).log"; mkdir -p "$STATE/logs"
exec >>"$LOG" 2>&1
exec 9>"$STATE/run.lock"
flock -n 9 || { echo "$(date -Iseconds) SKIP 이전 실행이 아직 진행 중"; exit 0; }
echo "=== $(date -Iseconds) start"
rc=0
"$REPO/bin/collect-all.sh"; crc=$?; [ $crc -ne 0 ] && rc=$crc
python3 "$REPO/bin/log_raw.py"; lrc=$?; [ $lrc -ne 0 ] && rc=$lrc
echo "=== $(date -Iseconds) end rc=$rc"
# 14일 지난 로그 정리
find "$STATE/logs" -name '[0-9]*.log' -mtime +14 -delete
exit $rc

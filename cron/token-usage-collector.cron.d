# token-usage-collector: 5분마다(시스템 시간대 Asia/Seoul) 수집 → 대시보드 전송
SHELL=/bin/bash
CRON_TZ=Asia/Seoul
*/5 * * * * collector /workspace/token-usage-collector/cron/run.sh

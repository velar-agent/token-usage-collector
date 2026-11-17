# token-usage-collector

codex, claude, antigravity, muse, grok-bot 의 구독 한도 사용량을 모아서, 서비스마다 JSONL 파일 하나씩
`/workspace/token-usage/raw/<YYYY-MM-DD_HHMM>_<service>.jsonl` 에 써요.

- `bin/collect-all.sh` — 수집 본체. [velar-agent/agent-scripts](https://github.com/velar-agent/agent-scripts) 의 스크립트를 써요(`/workspace/agent-scripts` 에 있어야 해요).
  서비스마다 `OK <file>` 또는 `FAIL <service>: <error>` 를 출력해요.
  - claude: 실패하면 CLI 토큰을 갱신(`claude -p hi`)하고 한 번 더 시도해요.
  - muse: 사용량을 읽기 전에 muse TUI(`bin/muse-tui-warmup.py`, ember/minimal, 프롬프트 "hi")를 가상 터미널에서 10초간 띄워요. 헤드리스 `muse exec` 만으로는 사용량 창이 안 열릴 수 있어서예요.
- `bin/log_raw.py` — raw 파일을 대시보드 기록으로 바꿔 POST 해요(`docs/FORMAT.md`, `docs/INGEST.md` 참고).
  `/workspace/token-usage/log_raw.py` 는 이 파일을 가리키는 심볼릭 링크예요.
- `docs/FORMAT.md` — 기록 형식. `docs/INGEST.md` — 대시보드 전송 API.

## 스케줄 (`cron/`)
- `cron/crontab` — `supercronic` 이 매시 15분·45분(Asia/Seoul)에 `cron/run.sh` 를 실행해요.
- `cron/run.sh` — `collect-all.sh` 다음 `log_raw.py` 를 실행하고, `/workspace/token-usage-cron/logs/YYYY-MM-DD.log` 에 이어 써요(14일 지난 로그는 지워요).
  이전 실행이 아직 돌고 있으면 건너뛰어요(`flock`). 재시도는 없어요. 실패하면 다음 15분·45분을 기다려요.
- `cron/start-cron.sh` — 이 crontab 으로 `supercronic` 이 안 떠 있으면 띄워요. `~/.bashrc` 와 `~/.profile` 에서 불러요. crontab 을 고친 뒤에는 떠 있는 `supercronic` 을 종료하고 다시 실행하세요.

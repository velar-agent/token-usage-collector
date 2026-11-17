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
- `cron/start-cron.sh` — 이 crontab 으로 `supercronic` 이 안 떠 있으면 띄워요. 운영은 아래 VM 의 시스템 cron 으로 옮겨서, box 에서는 더 이상 자동으로 띄우지 않아요(box 가 잠들면 실행이 빠졌어요). 두 곳에서 동시에 돌리지 마세요.

## 배포 (Google Cloud VM)
2026-11-18 부터 수집은 GCE VM 에서 돌아요. box 의 supercronic 수집기는 꺼 두었어요.
- VM: `token-usage-collector` (프로젝트 `velar-495311`, `us-west1-b`, e2-micro, Ubuntu 24.04, swap 2GB, 시간대 Asia/Seoul), 외부 IP `35.252.213.245`
- 접속: box 에서 `ssh -i ~/.ssh/gce_collector collector@35.252.213.245` (sudo 비밀번호 없음)
- 경로는 box 와 같아요: `/workspace/{token-usage-collector,agent-scripts,token-usage,token-usage-cron}`. `/home/box` 는 `/home/collector` 를 가리키는 심볼릭 링크라 하드코딩된 경로도 그대로 동작해요.
- CLI(claude, codex, agy, muse)는 `~/.local/bin` 에 box 와 같은 버전으로 복사했고, 로그인 정보(`~/.claude*`, `~/.codex`, `~/.gemini`, `~/.config/muse`)도 box 에서 복사했어요.
  grok-bot 은 `~/.config/Grok Bot/sand-secrets.json` 에 활성 계정 액세스 토큰만 넣어 두었어요(리프레시 토큰 없음). 만료되면 box 에서 다시 만들어 복사해야 해요.
- 스케줄: `/etc/cron.d/token-usage-collector` — `15,45 * * * * collector /workspace/token-usage-collector/cron/run.sh` (시스템 cron, 재부팅 후에도 동작). 로그는 `/workspace/token-usage-cron/logs/YYYY-MM-DD.log`.
- 재배포(코드만): box 에서 `tar czf - -C /workspace token-usage-collector agent-scripts | ssh -i ~/.ssh/gce_collector collector@35.252.213.245 'tar xzf - -C /workspace'`. `token-usage/` 의 `.logged`·raw 는 VM 쪽이 최신이니 덮어쓰지 마세요.
- 같은 로그인을 box 와 VM 이 함께 쓰면 OAuth 리프레시 토큰이 돌아가면서 서로를 무효화할 수 있어요. 수집은 VM 한 곳에서만 돌리세요.

# token-usage-collector (5분 간격 수집)

codex, claude, antigravity, muse, grok-bot 의 구독 한도 사용량을 모아서, 서비스마다 JSONL 파일 하나씩
`/workspace/token-usage/raw/<YYYY-MM-DD_HHMM>_<service>.jsonl` 에 써요.

- `bin/collect-all.sh` — 수집 본체. [velar-agent/agent-scripts](https://github.com/velar-agent/agent-scripts) 의 스크립트를 써요(`/workspace/agent-scripts` 에 있어야 해요).
  서비스마다 `OK <file>` 또는 `FAIL <service>: <error>` 를 출력해요.
  - claude: 실패하면 CLI 토큰을 갱신(`claude -p hi`)하고 한 번 더 시도해요.
  - muse: 사용량을 읽기 전에 muse TUI(`bin/muse-tui-warmup.py`, ember/minimal, 프롬프트 "hi")를 가상 터미널에서 10초간 띄워요. 헤드리스 `muse exec` 만으로는 사용량 창이 안 열릴 수 있어서예요.
- `bin/log_raw.py` — raw 파일을 대시보드 기록으로 바꿔 POST 해요(`docs/FORMAT.md`, `docs/INGEST.md` 참고).
  Google VM 안에서 매 배치를 개발(dev, `http://127.0.0.1:8787`)과 운영(prod, `http://127.0.0.1:8788`) 두 대시보드에 보내요. 기본 키 파일은 각각 `/workspace/token-usage/google-ingest-key.txt`와 `/workspace/token-usage/google-ingest-key-prod.txt`예요(`INGEST_URL`/`INGEST_KEY_FILE`, `INGEST_PROD_URL`/`INGEST_PROD_KEY_FILE` 환경 변수로 바꿀 수 있어요). 한쪽만 실패해도 다른 쪽은 끝까지 시도하고, 어느 쪽이든 실패하면 그 파일은 다음 실행에서 다시 보내요(서버 쪽 중복 제거로 안전해요). Cloudflare 대시보드는 운영을 종료했어요.
  `/workspace/token-usage/log_raw.py` 는 이 파일을 가리키는 심볼릭 링크예요.
- `docs/FORMAT.md` — 기록 형식. `docs/INGEST.md` — 대시보드 전송 API.

## 스케줄 (`cron/`)

- `cron/crontab` — `supercronic` 이 Asia/Seoul 기준으로 5분마다 `cron/run.sh` 를 실행해요.
- `cron/run.sh` — `collect-all.sh` 다음 `log_raw.py` 를 실행하고, `/workspace/token-usage-cron/logs/YYYY-MM-DD.log` 에 이어 써요(14일 지난 로그는 지워요).
  이전 실행이 아직 돌고 있으면 `SKIP` 을 남기고 건너뛰어요(`flock -n`). 실패하면 다음 5분 간격 실행을 기다려요.
- cron 로그는 하루 288회분이 남고, 매번 모든 서비스의 수집에 성공하면 raw 파일은 하루 1,440개(서비스 5개 × 288회)가 쌓여요.
- `cron/start-cron.sh` — 이 crontab 으로 `supercronic` 이 안 떠 있으면 띄워요. 운영은 아래 VM 의 시스템 cron 으로 옮겨서, box 에서는 더 이상 자동으로 띄우지 않아요(box 가 잠들면 실행이 빠졌어요). 두 곳에서 동시에 돌리지 마세요. 그래서 `FORCE_START=1` 없이 실행하면 경고를 출력하고 띄우지 않은 채 종료해요(exit 1).

## 배포 (Google Cloud VM)

2026-11-18 부터 수집은 GCE VM 에서 돌아요. box 의 supercronic 수집기는 꺼 두었어요.

- VM: `token-usage-collector` (`us-west1-b`, e2-micro, Ubuntu 24.04, swap 2GB, 시간대 Asia/Seoul)
- 접속: box 에서 `ssh gce-collector`. 주소·계정·키는 box 의 `~/.ssh/config` 에만 적어 둬요. VM 외부 IP 가 바뀌면 거기 `HostName` 만 고치면 돼요.
- 경로는 box 와 같아요: `/workspace/{token-usage-collector,agent-scripts,token-usage,token-usage-cron}`. `/home/box` 는 `/home/collector` 를 가리키는 심볼릭 링크라 하드코딩된 경로도 그대로 동작해요.
- CLI(claude, codex, agy, muse)는 `~/.local/bin` 에 box 와 같은 버전으로 복사했고, 로그인 정보(`~/.claude*`, `~/.codex`, `~/.gemini`, `~/.config/muse`)도 box 에서 복사했어요.
  grok-bot 은 `~/.config/Grok Bot/sand-secrets.json` 에 활성 계정 액세스 토큰만 넣어 두었어요(리프레시 토큰 없음). 만료되면 box 에서 다시 만들어 복사해야 해요.
- VM 의 시스템 cron 은 `*/5 * * * * collector /workspace/token-usage-collector/cron/run.sh` 로 5분마다 수집해요. 재부팅 후에도 동작하고, 로그는 `/workspace/token-usage-cron/logs/YYYY-MM-DD.log` 에 남아요.
- 스케줄을 설치하거나 갱신할 때는 VM 에서 저장소의 `cron/token-usage-collector.cron.d` 를 `/etc/cron.d/token-usage-collector` 로 복사해요.

  ```bash
  sudo install -m 644 /workspace/token-usage-collector/cron/token-usage-collector.cron.d /etc/cron.d/token-usage-collector
  ```

- 재배포(코드만): 먼저 GitHub 에 푸시하고, box 에서 `ssh gce-collector 'git -C /workspace/token-usage-collector pull --ff-only && git -C /workspace/agent-scripts pull --ff-only'`. VM 의 두 저장소는 git 체크아웃이라 커밋된 코드만 받아요. `token-usage/` 의 `.logged`·raw 는 VM 쪽이 최신이니 덮어쓰지 마세요.
- 실패 알림은 없어요. 수집이 도는지는 `ssh gce-collector 'grep -E "FAIL|rc=[1-9]" /workspace/token-usage-cron/logs/$(date +%F).log'` 로 확인해요(grok-bot 토큰 만료도 여기서 `FAIL grok-bot` 으로 보여요).
- 같은 로그인을 box 와 VM 이 함께 쓰면 OAuth 리프레시 토큰이 돌아가면서 서로를 무효화할 수 있어요. 수집은 VM 한 곳에서만 돌리세요.

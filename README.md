# token-usage-collector

Collects subscription-limit usage for codex, claude, antigravity, muse, and grok-bot,
writing one JSONL file per service to `/workspace/token-usage/raw/<YYYY-MM-DD_HHMM>_<service>.jsonl`.

- `bin/collect-all.sh` — main collector. Uses the scripts in
  [velar-agent/agent-scripts](https://github.com/velar-agent/agent-scripts) (expected at `/workspace/agent-scripts`).
  Prints `OK <file>` or `FAIL <service>: <error>` per service.
  - claude: on failure, refreshes the CLI token (`claude -p hi`) and retries.
  - muse: opens the muse TUI (`bin/muse-tui-warmup.py`, ember/minimal, prompt "hi") in a pseudo-terminal for 10 seconds before reading usage, because a headless `muse exec` can leave the usage window unopened.
- `docs/ALERTS.md` — alert rules for collection failures.
- `docs/FORMAT.md` — record format.

- `bin/log_raw.py` — converts raw files into dashboard records and POSTs them (see `docs/FORMAT.md`, `docs/INGEST.md`).
  `/workspace/token-usage/log_raw.py` is a symlink to it.
- `docs/INGEST.md` — dashboard ingest API.

## Schedule (`cron/`)
- `cron/run.sh` — one run: `collect-all.sh` → `log_raw.py` → `alerts.py`. Guarded by `flock`; logs to `<state>/logs/YYYY-MM-DD.log` (14 days kept).
- `cron/alerts.py` — turns a run's result into deduped `[TOKEN-USAGE-ALERT]` events (`open` once per new or worsened
  `(service, problem_key)`, `recovered` once when it clears), appends them to `<state>/alerts-outbox.jsonl`, and POSTs them
  to the URL in `<state>/webhook.conf` (line 1 URL, then `Header: value` lines) when present.
  problem_keys: `collect_fail:<service>` (warning), `multi_service_down` (critical, 3+ services), `log_script_error` (error).
- `cron/crontab` — supercronic schedule, 15 and 45 past every hour (Asia/Seoul).
- `cron/start-cron.sh [--status|--stop|--restart]` — starts the scheduler if not running; called from `~/.bashrc` and `~/.profile`.

`<state>` is `$TOKEN_USAGE_CRON_STATE`, default `/workspace/token-usage-cron` (outside the repo; holds logs, alert state, outbox, webhook.conf).

# token-usage-collector

Collects subscription-limit usage for grok, codex, claude, antigravity, muse, and grok-bot,
writing one JSONL file per service to `/workspace/token-usage/raw/<YYYY-MM-DD_HHMM>_<service>.jsonl`.

- `bin/collect-all.sh` — main collector. Uses the scripts in
  [velar-agent/agent-scripts](https://github.com/velar-agent/agent-scripts) (expected at `/workspace/agent-scripts`).
  Prints `OK <file>` or `FAIL <service>: <error>` per service.
  - grok / claude: on failure, refreshes the CLI token (grok: `grok --single hi --model "Grok 4.5" --reasoning-effort low`; claude: `claude -p hi`) and retries.
  - muse: opens the muse TUI (`bin/muse-tui-warmup.py`, ember/minimal, prompt "hi") in a pseudo-terminal for 10 seconds before reading usage, because a headless `muse exec` can leave the usage window unopened.
- `docs/ALERTS.md` — alert rules for collection failures.
- `docs/FORMAT.md` — record format.

Run on request from the token usage logging bot; no own schedule.

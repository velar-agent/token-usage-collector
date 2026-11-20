#!/usr/bin/env bash
# Collect subscription usage for codex, claude, antigravity, muse, grok-bot into /workspace/token-usage/raw/
export PATH=$HOME/.local/bin:$PATH
S=/workspace/agent-scripts
R=${TOKEN_USAGE_RAW:-/workspace/token-usage/raw}
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
ts=$(date +%Y-%m-%d_%H%M); now=$(date -Iseconds)
mkdir -p "$R"
N='input_tokens:null,output_tokens:null,total_tokens:null,cost_usd:null'
# 실패 시 1을 반환해요. 성공이면 stderr에 남은 안내(예: muse exhausted)도 로그에 남겨요.
run(){
  name=$1; shift
  out=$R/${ts}_$name.jsonl
  if "$@" > $out.tmp 2>$out.err && [ -s $out.tmp ]; then
    mv $out.tmp $out
    echo "OK $out"
    if [ -s $out.err ]; then cat "$out.err"; fi
    rm -f $out.err
    return 0
  else
    rm -f $out.tmp
    echo "FAIL $name: $(head -c 300 $out.err)"
    rm -f $out.err
    return 1
  fi
}
codex(){ timeout 60 python3 $S/codex-account-rateLimits-read.py | jq -c --arg now "$now" ".rateLimits as \$r | \$r.primary.resetsAt as \$e | {collected_at:\$now,service:\"codex\",model:(\"ChatGPT \"+\$r.planType),period_start:((\$e-\$r.primary.windowDurationMins*60)|todate),period_end:(\$e|todate),$N,used_percent:(\$r.primary.usedPercent|floor),limit_type:\"weekly\",reset_at:(\$e|todate),source:\"codex-account-rateLimits-read.py\"}"; }
claude(){ { $S/claude-usage.sh 2>/dev/null || { (cd /tmp && timeout 90 claude -p hi >/dev/null 2>&1); $S/claude-usage.sh; }; } | jq -c --arg now "$now" ".limits[] | {collected_at:\$now,service:\"claude\",model:(.scope.model.display_name // .scope.model.id // (if .kind==\"weekly_scoped\" then \"scoped\" else \"all models\" end)),period_start:null,period_end:.resets_at,$N,used_percent:(.percent|floor),limit_type:.kind,reset_at:.resets_at,source:\"claude-usage.sh\"}"; }
agy(){ timeout 90 $S/agy-print-usage.sh --output-format-json | jq -c --arg now "$now" ".command.data.groups[] as \$g | \$g.buckets[] | {collected_at:\$now,service:\"antigravity\",model:\$g.name,period_start:null,period_end:.reset_time,$N,remaining_percent:(.remaining_fraction*100|floor),limit_type:(.window // \"weekly\"),reset_at:.reset_time,source:\"agy-print-usage.sh\"}"; }
muse(){ python3 "$HERE/muse-collect.py"; }
grokbot(){ local T; T=$($S/grok-bot-cursor-token-from-linux.sh) || return 1; GROK_BOT_ACCESS_TOKEN="$T" timeout 60 $S/grok-bot-cursor-usage.sh | jq -c --arg now "$now" "{collected_at:\$now,service:\"grok-bot\",model:(.grokPlanLabel // .includedUsageSuperGrokPlan),period_start:.currentPeriodStart,period_end:.nextResetTimestampUtc,$N,used_percent:(.usagePercent|floor),limit_type:\"weekly\",reset_at:.nextResetTimestampUtc,source:\"grok-bot-cursor-usage.sh\"}"; }
rc=0
run codex codex; crc=$?; [ $crc -ne 0 ] && rc=$crc
run claude claude; crc=$?; [ $crc -ne 0 ] && rc=$crc
run antigravity agy; crc=$?; [ $crc -ne 0 ] && rc=$crc
run muse muse; crc=$?; [ $crc -ne 0 ] && rc=$crc
run grok-bot grokbot; crc=$?; [ $crc -ne 0 ] && rc=$crc
exit $rc

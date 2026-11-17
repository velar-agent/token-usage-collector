#!/usr/bin/env python3
"""Convert gathering-bot raw jsonl files into processed/YYYY-MM-DD.jsonl (FORMAT.md). Idempotent via .logged list."""
import json, sys, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
KST = timezone(timedelta(hours=9))
BASE = Path("/workspace/token-usage")
DONE = BASE / ".logged"
NOTE_MAP = {"X Premium+ (GrokBuild)": "GrokBuild"}
POST = (BASE / ".post_enabled").exists()
PROD = "https://usage-dashboard.velar-agent.workers.dev/api/ingest"
DEV = "https://usage-dashboard-dev.velar-agent.workers.dev/api/ingest"
def post_dev(recs, name):
    """Best-effort mirror to the dev server; never blocks prod."""
    try:
        post(recs, DEV, "ingest-dev")
    except Exception as e:
        print(f"dev ingest failed ({name}): {type(e).__name__}: {e}")
        with (BASE / ".dev_failed.log").open("a") as fl:
            fl.write(f"{datetime.now(KST).isoformat()} {name} {type(e).__name__}: {e}\n")
def post(recs, url=PROD, label="ingest"):
    key = (BASE / "ingest-key.txt").read_text().strip()
    for i in range(0, len(recs), 40):
        req = urllib.request.Request(url, data=json.dumps(recs[i:i+40]).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "token-usage-logging-bot/1.0"}, method="POST")
        for attempt in range(3):
            try:
                print(f"{label}:", urllib.request.urlopen(req, timeout=30).read().decode()); break
            except urllib.error.HTTPError as e:
                if e.code < 500 or attempt == 2: raise
                import time; time.sleep(3)
            except Exception:
                if attempt == 2: raise
                import time; time.sleep(3)
done = set(DONE.read_text().split()) if DONE.exists() else set()
def kst(s):
    if not s: return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST).replace(microsecond=0).isoformat()
files = [Path(a) for a in sys.argv[1:]] or sorted((BASE/"raw").glob("*.jsonl"))
for f in files:
    if str(f) in done: continue
    n = 0
    filerecs = []
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        r = json.loads(line)
        ts = kst(r.get("collected_at")) or datetime.now(KST).replace(microsecond=0).isoformat()
        base = {"ts": ts, "service": r.get("service")}
        extra = {k: v for k, v in {"reset_at": kst(r.get("reset_at")), "note": NOTE_MAP.get(r.get("model"), r.get("model")), "source": "token-usage-logging-bot", "raw_file": f.name, "raw_source": r.get("source")}.items() if v is not None}
        recs = []
        lt = r.get("limit_type") or "weekly"
        lt = {"weekly_all": "weekly", "5h": "session", "window": "session"}.get(lt, lt)
        pct = r.get("used_percent")
        if pct is None and r.get("remaining_percent") is not None:
            pct = round(100 - float(r["remaining_percent"]), 2)
            if float(pct).is_integer(): pct = int(pct)
        if pct is not None:
            recs.append({**base, "metric": f"{lt}_used_pct", "value": pct, "unit": "%", **extra})
        for k, m, u in [("input_tokens","tokens_in","tokens"),("output_tokens","tokens_out","tokens"),("total_tokens","tokens_total","tokens"),("cost_usd","cost","USD")]:
            if r.get(k) is not None:
                recs.append({**base, "metric": m, "value": r[k], "unit": u, **extra})
        # grok weekly 'GrokBuild' was also removed at the user's request (2026-11-17 17:52 KST); never send it
        recs = [x for x in recs if not (x.get('service') == 'grok' and x.get('metric') == 'weekly_used_pct' and x.get('note') == 'GrokBuild')]
        filerecs += recs
    if POST and filerecs:
        post(filerecs)
        post_dev(filerecs, f.name)
    for x in filerecs:
        out = BASE/"processed"/f"{x['ts'][:10]}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as o:
            o.write(json.dumps(x, ensure_ascii=False)+"\n"); n += 1
    with DONE.open("a") as d: d.write(str(f)+"\n")
    print(f"{f.name}: {n} records")

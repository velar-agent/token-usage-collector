#!/usr/bin/env python3
"""Convert gathering-bot raw jsonl files into processed/YYYY-MM-DD.jsonl (FORMAT.md). Idempotent via .logged list."""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

KST = timezone(timedelta(hours=9))
BASE = Path("/workspace/token-usage")
DONE = BASE / ".logged"
NOTE_MAP = {"X Premium+ (GrokBuild)": "GrokBuild"}
POST = (BASE / ".post_enabled").exists()
INGEST_URL = os.environ.get("INGEST_URL", "http://127.0.0.1:8787/api/ingest")
INGEST_KEY_FILE = Path(os.environ.get("INGEST_KEY_FILE", BASE / "google-ingest-key.txt"))
INGEST_PROD_URL = os.environ.get("INGEST_PROD_URL", "http://127.0.0.1:8788/api/ingest")
INGEST_PROD_KEY_FILE = Path(os.environ.get("INGEST_PROD_KEY_FILE", BASE / "google-ingest-key-prod.txt"))

def _post_to(url, key_file, recs):
    host = unquote(urlsplit(url).hostname or "").lower().rstrip(".")
    if host.split(".")[-2:] == ["workers", "dev"]:
        raise ValueError(f"Ingest URL must point to the Google dashboard: {url}")
    key = Path(key_file).read_text().strip()
    if not key:
        raise ValueError(f"Ingest key file is empty: {key_file}")
    for i in range(0, len(recs), 40):
        req = urllib.request.Request(url, data=json.dumps(recs[i:i+40]).encode(), headers={"Content-Type": "application/json", "User-Agent": "token-usage-logging-bot/1.0"}, method="POST")
        req.add_unredirected_header("Authorization", f"Bearer {key}")
        for attempt in range(3):
            try:
                response = urllib.request.urlopen(req, timeout=30).read().decode()
                print(f"ingest to {url}:", response.replace(key, "[redacted]") if key else response)
                break
            except Exception as e:
                if attempt == 2 or (isinstance(e, urllib.error.HTTPError) and e.code < 500):
                    if key and key in str(e):
                        raise RuntimeError("Ingest request failed (details redacted)") from None
                    raise
                time.sleep(3)

def post(recs):
    # dev와 prod에 독립적으로 보내요. 한쪽 실패가 다른 쪽 시도를 막지 않아요.
    # 둘 다 시도한 뒤 하나라도 실패했으면 예외를 올려 .logged를 남기지 않고 다음 회차에 재시도해요.
    # 서버는 INSERT OR IGNORE(dedupe_key)라 재전송은 idempotent해요.
    errors = []
    for url, key_file in ((INGEST_URL, INGEST_KEY_FILE), (INGEST_PROD_URL, INGEST_PROD_KEY_FILE)):
        try:
            _post_to(url, key_file, recs)
        except Exception as e:
            try:
                k = Path(key_file).read_text().strip()
            except Exception:
                k = ""
            msg = str(e).replace(k, "[redacted]") if k and k in str(e) else str(e)
            print(f"ingest to {url} failed: {msg}", file=sys.stderr)
            errors.append(e)
    if errors:
        raise RuntimeError(f"Ingest failed for {len(errors)} target(s)")

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
    for x in filerecs:
        out = BASE/"processed"/f"{x['ts'][:10]}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as o:
            o.write(json.dumps(x, ensure_ascii=False)+"\n"); n += 1
    with DONE.open("a") as d: d.write(str(f)+"\n")
    print(f"{f.name}: {n} records")

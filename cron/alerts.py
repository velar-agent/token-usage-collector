#!/usr/bin/env python3
"""run.sh 한 회차의 결과를 보고 문제 상태를 판단해, 새로 생기거나 심해진 문제는 open,
사라진 문제는 recovered 알림을 만들어요 (형식: /workspace/token-usage/ALERTS.md).
알림은 alerts-outbox.jsonl 에 쌓고, <state>/webhook.conf(1행 URL, 이후 "Header: value" 줄들)가 있으면 그 주소로도 POST 해요.
사용: alerts.py <collect 출력 파일> <log_raw 종료코드> <log_raw 출력 파일>"""
import json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
KST = timezone(timedelta(hours=9))
HERE = Path(os.environ.get("TOKEN_USAGE_CRON_STATE", "/workspace/token-usage-cron"))  # 실행 데이터 위치
STATE, OUTBOX, HOOK = HERE/"alerts-state.json", HERE/"alerts-outbox.jsonl", HERE/"webhook.conf"
SERVICES = ["codex", "claude", "antigravity", "muse", "grok-bot"]
RANK = {"warning": 1, "error": 2, "critical": 3}
SOURCE, SOURCE_ID = "token-usage-cron (script developer)", "94932b7f-8273-41e0-9c7c-5b3fe21a43b8"
now = datetime.now(KST).replace(microsecond=0).isoformat()

collect_out = Path(sys.argv[1]).read_text(errors="replace") if len(sys.argv) > 1 else ""
log_rc = int(sys.argv[2]) if len(sys.argv) > 2 else 0
log_out = Path(sys.argv[3]).read_text(errors="replace") if len(sys.argv) > 3 else ""

problems = {}  # "service|problem_key" -> dict
ok = {s for s in SERVICES if f"_{s}.jsonl" in collect_out and any(l.startswith("OK ") and l.endswith(f"_{s}.jsonl") for l in collect_out.splitlines())}
for s in SERVICES:
    if s in ok: continue
    err = next((l.split(":", 1)[1].strip() for l in collect_out.splitlines() if l.startswith(f"FAIL {s}:")), "")
    problems[f"{s}|collect_fail:{s}"] = dict(service=s, severity="warning",
        summary=f"{s} 사용량 수집 실패", detail=err or "OK/FAIL 출력 없음 (collect-all.sh 중단 가능성)")
down = len(SERVICES) - len(ok)
if down >= 3:
    problems["pipeline|multi_service_down"] = dict(service="pipeline", severity="critical",
        summary=f"서비스 {down}개 동시 수집 실패", detail=", ".join(s for s in SERVICES if s not in ok))
if log_rc != 0:
    tail = " | ".join(log_out.strip().splitlines()[-5:])[:600]
    problems["pipeline|log_script_error"] = dict(service="pipeline", severity="error",
        summary="log_raw.py 실행 실패 (대시보드 전송 안 됨, 다음 회차에 재시도)", detail=f"rc={log_rc} {tail}")

try:
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not isinstance(state, dict): raise ValueError("not an object")
except Exception as ex:
    print(f"alerts-state.json 읽기 실패, 새로 시작: {ex}"); state = {}
state = {k: v for k, v in state.items() if "|" in k and isinstance(v, dict) and v.get("severity") in RANK}
events = []
for k, p in problems.items():
    old = state.get(k)
    if old is None or RANK[p["severity"]] > RANK[old["severity"]]:
        events.append(dict(p, status="open", problem_key=k.split("|", 1)[1]))
        state[k] = {"severity": p["severity"], "since": old.get("since", now) if old else now}
for k in list(state):
    if k not in problems:
        svc, key = k.split("|", 1)
        events.append(dict(service=svc, problem_key=key, severity=state[k]["severity"], status="recovered",
            summary=f"복구됨 ({state[k].get('since', '?')}부터 이어진 문제)", detail="이번 회차에서 정상 확인"))
        del state[k]
STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))

hook = [l.strip() for l in HOOK.read_text().splitlines() if l.strip()] if HOOK.exists() else []
for e in events:
    text = ("[TOKEN-USAGE-ALERT]\n" f"severity: {e['severity']}\nstatus: {e['status']}\nsource: {SOURCE}\nsource_id: {SOURCE_ID}\n"
            f"time: {now}\nservice: {e['service']}\nproblem_key: {e['problem_key']}\nsummary: {e['summary']}\ndetail: {e['detail']}")
    rec = {"time": now, "delivered": False, "text": text}
    if hook and hook[0].startswith("http"):
        hdrs = {"Content-Type": "application/json", "User-Agent": "token-usage-cron/1.0"}
        for h in hook[1:]:
            if ":" in h: k, v = h.split(":", 1); hdrs[k.strip()] = v.strip()
        try:
            urllib.request.urlopen(urllib.request.Request(hook[0], data=json.dumps({"alert": text}).encode(), headers=hdrs, method="POST"), timeout=20)
            rec["delivered"] = True
        except Exception as ex:
            rec["webhook_error"] = f"{type(ex).__name__}: {ex}"
    with OUTBOX.open("a", encoding="utf-8") as o: o.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"ALERT {e['status']} {e['service']} {e['problem_key']} delivered={rec['delivered']}")

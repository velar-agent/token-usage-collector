# 토큰 사용 기록 보내기 / Posting token usage records

Google VM 안에서 대시보드 주소는 개발(dev) `http://127.0.0.1:8787`과 운영(prod) `http://127.0.0.1:8788`예요. 수집기(`bin/log_raw.py`)는 매 배치를 두 대시보드에 각각 보내요. 한쪽만 실패해도 다른 쪽은 끝까지 시도하고, 어느 쪽이든 실패하면 그 파일은 다음 실행에서 다시 보내요(서버 쪽 중복 제거로 안전해요). 아래 예시는 개발(dev) 기준이에요. Cloudflare 대시보드는 운영을 종료했어요.
On the Google VM, the dashboards listen at `http://127.0.0.1:8787` (dev) and `http://127.0.0.1:8788` (prod). The collector (`bin/log_raw.py`) posts each batch to both. One target's failure still attempts the other, and any failure retries the file next run (re-sending is safe). Examples below target dev. The Cloudflare dashboard has been retired.

- `INGEST_URL` 기본값 / Default POST URL (dev) — `http://127.0.0.1:8787/api/ingest`
- `INGEST_PROD_URL` 기본값 / Default POST URL (prod) — `http://127.0.0.1:8788/api/ingest`
- 인증 / Auth: 헤더 `Authorization: Bearer <INGEST_KEY>`
- `INGEST_KEY_FILE` 기본값 / Default key file (dev) — `/workspace/token-usage/google-ingest-key.txt` (권한 600, 채팅·로그에 키를 찍지 마세요 / never print or log the key)
- `INGEST_PROD_KEY_FILE` 기본값 / Default key file (prod) — `/workspace/token-usage/google-ingest-key-prod.txt` (권한 600)
- 본문 / Body: `Content-Type: application/json` — 기록 객체 하나, 객체 배열, 또는 `{"records":[...]}`. **한 번에 최대 40건 / max 40 records per request**, 본문 256KB 이하.

## 필드 / Fields (FORMAT.md 와 같아요 / same as FORMAT.md)

| 필드 | 필수 | 규칙 / Rule |
| --- | --- | --- |
| `service` | 예/yes | 문자열 1~64자 / string, 1–64 chars |
| `metric` | 예/yes | 문자열 1~64자 (`weekly_used_pct`, `session_used_pct`, …) |
| `value` | 예/yes | **숫자** / number (문자열 `"14"` 은 거부 / strings rejected) |
| `ts` | 아니오/no | ISO 8601. `+09:00` 권장. 없으면 서버 현재 시각(KST). 시간대가 없으면 KST 로 봐요 |
| `unit` | 아니오 | 문자열 ≤20자 |
| `reset_at` | 아니오 | ISO 8601 |
| `note` | 아니오 | 문자열 ≤200자 |
| `source` | 아니오 | 문자열 ≤100자 |
| 그 밖의 필드 | 아니오 | 그대로 보존돼요 (예: `raw_file`, `raw_source`). 밑줄(`_`)로 시작하는 이름은 안 돼요. 기록 하나 4KB 이하 |

중복 / Dedupe: `ts` + `service` + `metric` + `note` 가 같은 기록은 한 번만 저장돼요 (두 번째는 `duplicates` 로 세어지고 무시돼요). 같은 값을 다시 보내도 안전해요.
Records with the same `ts`+`service`+`metric`+`note` are stored once; re-sending is safe.

## 예 1: 한 건 / one record

```bash
curl -sS -X POST http://127.0.0.1:8787/api/ingest \
  -H "Authorization: Bearer $(cat /workspace/token-usage/google-ingest-key.txt)" \
  -H "Content-Type: application/json" \
  -d '{"ts":"2026-11-15T15:20:00+09:00","service":"grok","metric":"weekly_used_pct","value":7,"unit":"%","reset_at":"2026-11-17T15:42:00+09:00","note":"X Premium+","source":"token-usage-logging-bot"}'
```

## 예 2: 여러 건 / several records

```bash
curl -sS -X POST http://127.0.0.1:8787/api/ingest \
  -H "Authorization: Bearer $(cat /workspace/token-usage/google-ingest-key.txt)" \
  -H "Content-Type: application/json" \
  -d '[{"service":"claude","metric":"session_used_pct","value":0,"unit":"%","note":"all models"},
       {"service":"claude","metric":"weekly_used_pct","value":14,"unit":"%","note":"all models","reset_at":"2026-11-17T19:59:59+09:00"}]'
```

## 예 3: Python

```python
import json, urllib.request
from datetime import datetime, timedelta, timezone
KST = timezone(timedelta(hours=9))
key = open("/workspace/token-usage/google-ingest-key.txt").read().strip()
recs = [{"ts": datetime.now(KST).isoformat(timespec="seconds"), "service": "codex",
         "metric": "weekly_used_pct", "value": 36, "unit": "%", "note": "ChatGPT prolite",
         "source": "token-usage-logging-bot"}]
req = urllib.request.Request("http://127.0.0.1:8787/api/ingest", data=json.dumps(recs).encode(),
      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "User-Agent": "token-usage-logging-bot/1.0"}, method="POST")
print(urllib.request.urlopen(req, timeout=30).read().decode())
```

## 응답 / Responses

- `200` `{"ok":true,"received":N,"inserted":X,"duplicates":Y}`
- `400` 잘못된 JSON 또는 필드 — 한 건이라도 잘못되면 **아무것도 저장하지 않고** `{"error":"…","details":[{"index":0,"error":"…"}]}` 로 이유를 알려 줘요 / nothing is stored if any record is invalid
- `401` 키가 없거나 틀림 / missing or wrong key
- `405` POST 가 아님 · `413` 너무 큼 / too large

## 원본(raw) 파일 올리기 (선택) / Uploading a raw dump (optional)

```bash
python3 - <<'PY' | curl -sS -X POST http://127.0.0.1:8787/api/raw/upload \
  -H "Authorization: Bearer $(cat /workspace/token-usage/google-ingest-key.txt)" -H "Content-Type: application/json" --data-binary @-
import json; print(json.dumps({"name":"2026-11-15_1800_grok.jsonl","content":open("/workspace/token-usage/raw/2026-11-15_1800_grok.jsonl").read()}))
PY
```

`name`: 영문·숫자·`.`·`_`·`-` 200자 이하. `content`: 200,000자 이하. 같은 이름이면 덮어써요(`replaced:true`). 선택 `created_at`(ISO 8601). 대시보드에는 최신 8개만 보이고, 열람에는 비밀번호가 필요해요.

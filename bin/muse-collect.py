#!/usr/bin/env python3
"""Collect Muse subscription usage as JSONL on stdout.

Always warms up the Muse TUI and then runs `muse-usage.sh --json`.
When the server returns no usage data (allowance is null / reason
`server_sent_no_usage`), the observation is recorded faithfully with
null used_percent plus reason and hint; that is not a collection
failure. The dashboard evaluates whether that means quota exhausted.

CLI or parse errors are reported on stderr and exit 1.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
HERE = Path(__file__).resolve().parent
USAGE_SCRIPT = Path(os.environ.get("MUSE_USAGE_CMD", "/workspace/agent-scripts/muse-usage.sh"))
WARMUP = HERE / "muse-tui-warmup.py"


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_utc_z(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def allowance_records(payload: dict, collected_at: str) -> list[dict]:
    allowance = payload.get("allowance")
    if not isinstance(allowance, dict):
        return []
    tier = allowance.get("tier") or "muse"
    rows = []
    for key in ("weekly", "window"):
        limit = allowance.get(key)
        if not isinstance(limit, dict) or limit.get("usedPercent") is None:
            continue
        used = limit["usedPercent"]
        if isinstance(used, bool) or not isinstance(used, (int, float)):
            continue
        resets = limit.get("resetsAtMs")
        if isinstance(resets, bool) or not isinstance(resets, (int, float)):
            continue
        stamp = to_utc_z(resets)
        rows.append({
            "collected_at": collected_at,
            "service": "muse",
            "model": tier,
            "period_start": None,
            "period_end": stamp,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
            "used_percent": math.floor(used),
            "limit_type": key,
            "reset_at": stamp,
            "source": "muse-usage.sh",
        })
    return rows


def no_usage_record(payload: dict, collected_at: str) -> dict:
    reason = str(payload.get("reason") or "server_sent_no_usage").strip() or "server_sent_no_usage"
    hint = str(payload.get("hint") or "").strip()
    row = {
        "collected_at": collected_at,
        "service": "muse",
        "model": None,
        "period_start": None,
        "period_end": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
        "used_percent": None,
        "limit_type": None,
        "reset_at": None,
        "reason": reason,
        "source": "muse-usage.sh",
    }
    if hint:
        row["hint"] = hint
    return row


def no_usage_message(payload: dict | None, fallback: str = "") -> str:
    if not isinstance(payload, dict):
        return fallback or "no Muse usage data"
    reason = str(payload.get("reason") or "").strip()
    hint = str(payload.get("hint") or "").strip()
    if reason and hint:
        return f"{reason}; {hint}"
    return reason or hint or fallback or "no Muse usage data"


def emit(rows: list[dict]) -> None:
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, separators=(",", ":")))


def run_warmup() -> None:
    cmd = os.environ.get("MUSE_WARMUP_CMD")
    if cmd:
        argv = cmd.split()
    else:
        argv = [sys.executable, str(WARMUP), "10"]
    try:
        subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def read_usage(usage_json: Path | None) -> tuple[int, dict | None, str]:
    """Return (exit_code, parsed_json_or_None, stderr_text)."""
    if usage_json is not None:
        text = usage_json.read_text(encoding="utf-8")
        try:
            return 0, json.loads(text), ""
        except json.JSONDecodeError as err:
            return 1, None, f"invalid Muse usage JSON: {err}"
    cmd = os.environ.get("MUSE_USAGE_CMD", str(USAGE_SCRIPT))
    argv = cmd.split() if " " in cmd else [cmd]
    if argv[-1] != "--json" and Path(argv[0]).name == "muse-usage.sh":
        argv = argv + ["--json"]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=60)
    except FileNotFoundError:
        return 1, None, f"{argv[0]} was not found in PATH."
    except subprocess.TimeoutExpired:
        return 1, None, "muse usage timed out"
    err = (proc.stderr or "").strip()
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return proc.returncode, None, err or f"Could not get Muse usage (exit {proc.returncode})."
    if not out:
        return 1, None, err or "muse usage returned no output"
    try:
        return 0, json.loads(out), err
    except json.JSONDecodeError as exc:
        return 1, None, err or f"invalid Muse usage JSON: {exc}"


def collect(now: datetime, skip_warmup: bool, usage_json: Path | None) -> int:
    collected_at = now.astimezone(KST).isoformat(timespec="seconds")
    if not skip_warmup:
        run_warmup()
    status, payload, err = read_usage(usage_json)
    if status == 0 and payload is not None:
        rows = allowance_records(payload, collected_at)
        if rows:
            emit(rows)
            return 0
        emit([no_usage_record(payload, collected_at)])
        print(f"muse no usage: {no_usage_message(payload)}", file=sys.stderr)
        return 0
    print(err or "Could not get Muse usage.", file=sys.stderr)
    return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Muse usage as JSONL on stdout.")
    parser.add_argument("--now", help="Collection time (ISO 8601). Default: now in Asia/Seoul")
    parser.add_argument("--skip-warmup", action="store_true",
                        help="Do not open the Muse TUI (tests only)")
    parser.add_argument("--usage-json", type=Path,
                        help="Read muse usage JSON from a file instead of calling muse-usage.sh")
    # --raw-dir is accepted for compatibility with the previous interface; unused.
    parser.add_argument("--raw-dir", type=Path, default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.now:
        now = parse_iso(args.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=KST)
    else:
        now = datetime.now(KST)
    skip = args.skip_warmup or os.environ.get("MUSE_SKIP_WARMUP") == "1"
    return collect(now, skip, args.usage_json)


if __name__ == "__main__":
    sys.exit(main())

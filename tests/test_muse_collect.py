"""Muse exhausted / server_sent_no_usage collection rules."""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
COLLECT = REPO / "bin" / "muse-collect.py"
COLLECT_ALL = REPO / "bin" / "collect-all.sh"
KST = timezone(timedelta(hours=9))

RESET_UTC = "2026-11-23T00:00:00Z"  # 2026-11-23 09:00 KST
BEFORE = "2026-11-21T07:20:00+09:00"
AFTER = "2026-11-23T09:00:00+09:00"
NO_USAGE = {
    "allowance": None,
    "hint": "the server sent no usage data for this subscription; this can happen before your first use in a new window",
    "reason": "server_sent_no_usage",
    "schemaVersion": 1,
}
USAGE_OK = {
    "allowance": {
        "tier": "Muse Code Everyday Usage",
        "weekly": {"usedPercent": 12.9, "resetsAtMs": 1795392000000},
        "window": {"usedPercent": 0, "resetsAtMs": 1795100107000},
    }
}


def weekly_row(used=99, collected="2026-11-19T23:50:01+09:00", model="Muse Code Everyday Usage",
               reset=RESET_UTC, **extra):
    row = {
        "collected_at": collected,
        "service": "muse",
        "model": model,
        "period_start": None,
        "period_end": reset,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
        "used_percent": used,
        "limit_type": "weekly",
        "reset_at": reset,
        "source": "muse-usage.sh",
    }
    row.update(extra)
    return row


def write_raw(directory: Path, name: str, rows: list) -> Path:
    path = directory / name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def write_json(directory: Path, name: str, payload) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_executable(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def run_collect(raw: Path, now: str, usage: Path | None = None, env: dict | None = None,
                skip_warmup: bool = True) -> subprocess.CompletedProcess:
    cmd = [ "python3", str(COLLECT), "--raw-dir", str(raw), "--now", now ]
    if skip_warmup:
        cmd.append("--skip-warmup")
    if usage is not None:
        cmd.extend(["--usage-json", str(usage)])
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})


class MuseCollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "raw"
        self.raw.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_exhausted_skips_warmup_and_usage_and_records_100(self):
        write_raw(self.raw, "2026-11-19_2350_muse.jsonl", [
            weekly_row(99),
            {**weekly_row(99), "limit_type": "window", "used_percent": 65,
             "reset_at": "2026-11-19T14:55:07Z", "period_end": "2026-11-19T14:55:07Z"},
        ])
        warmup_flag = Path(self.tmp.name) / "warmup-ran"
        warmup = write_executable(Path(self.tmp.name), "warmup.sh", f"#!/bin/bash\necho ran > '{warmup_flag}'\n")
        usage = write_json(Path(self.tmp.name), "should-not-read.json", USAGE_OK)
        env = {"MUSE_WARMUP_CMD": str(warmup)}
        proc = run_collect(self.raw, BEFORE, usage=usage, env=env, skip_warmup=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK muse exhausted until 2026-11-23 09:00 KST", proc.stderr)
        self.assertFalse(warmup_flag.exists(), "warmup must be skipped while exhausted")
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["service"], "muse")
        self.assertEqual(row["used_percent"], 100)
        self.assertEqual(row["limit_type"], "weekly")
        self.assertEqual(row["reset_at"], RESET_UTC)
        self.assertEqual(row["period_end"], RESET_UTC)
        self.assertEqual(row["model"], "Muse Code Everyday Usage")
        self.assertEqual(row["source"], "muse-exhausted")
        self.assertEqual(row["status"], "exhausted")
        self.assertEqual(row["collected_at"], "2026-11-21T07:20:00+09:00")

    def test_previous_exhausted_record_still_counts_until_reset(self):
        write_raw(self.raw, "2026-11-21_0710_muse.jsonl", [
            weekly_row(100, collected="2026-11-21T07:10:01+09:00", source="muse-exhausted", status="exhausted"),
        ])
        proc = run_collect(self.raw, BEFORE)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK muse exhausted until 2026-11-23 09:00 KST", proc.stderr)
        row = json.loads(proc.stdout.splitlines()[0])
        self.assertEqual(row["used_percent"], 100)

    def test_after_weekly_reset_resumes_normal_collection(self):
        write_raw(self.raw, "2026-11-19_2350_muse.jsonl", [weekly_row(99)])
        usage = write_json(Path(self.tmp.name), "usage.json", USAGE_OK)
        warmup_flag = Path(self.tmp.name) / "warmup-ran"
        warmup = write_executable(Path(self.tmp.name), "warmup.sh", f"#!/bin/bash\necho ran > '{warmup_flag}'\n")
        env = {"MUSE_WARMUP_CMD": str(warmup)}
        proc = run_collect(self.raw, AFTER, usage=usage, env=env, skip_warmup=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(warmup_flag.exists(), "warmup must resume after reset")
        self.assertNotIn("exhausted", proc.stderr)
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual([r["limit_type"] for r in rows], ["weekly", "window"])
        self.assertEqual(rows[0]["used_percent"], 12)
        self.assertEqual(rows[0]["source"], "muse-usage.sh")
        self.assertEqual(rows[0]["reset_at"], "2026-11-23T00:00:00Z")
        self.assertEqual(rows[1]["used_percent"], 0)

    def test_unexpected_no_usage_is_a_failure_with_reason(self):
        write_raw(self.raw, "2026-11-19_1850_muse.jsonl", [weekly_row(50)])
        usage = write_json(Path(self.tmp.name), "usage.json", NO_USAGE)
        proc = run_collect(self.raw, BEFORE, usage=usage)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("server_sent_no_usage", proc.stderr)
        self.assertIn("the server sent no usage data", proc.stderr)
        self.assertNotIn("OK muse exhausted", proc.stderr)

    def test_no_last_reading_and_no_usage_is_a_failure(self):
        usage = write_json(Path(self.tmp.name), "usage.json", NO_USAGE)
        proc = run_collect(self.raw, BEFORE, usage=usage)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("server_sent_no_usage", proc.stderr)

    def test_threshold_is_99_inclusive(self):
        write_raw(self.raw, "2026-11-19_2350_muse.jsonl", [weekly_row(98)])
        usage = write_json(Path(self.tmp.name), "usage.json", NO_USAGE)
        proc = run_collect(self.raw, BEFORE, usage=usage)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("server_sent_no_usage", proc.stderr)

        write_raw(self.raw, "2026-11-19_2350_muse.jsonl", [weekly_row(99)])
        proc = run_collect(self.raw, BEFORE, usage=usage)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK muse exhausted until 2026-11-23 09:00 KST", proc.stderr)


class CollectAllRunTests(unittest.TestCase):
    """collect-all.sh run() should surface muse exhausted as OK and propagate FAIL."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        write_raw(self.raw, "2026-11-19_2350_muse.jsonl", [weekly_row(99)])

    def tearDown(self):
        self.tmp.cleanup()

    def _run_only_muse(self, extra_env=None):
        # Stub the other four collectors so collect-all.sh only really runs muse.
        stubs = self.root / "stubs"
        stubs.mkdir()
        for name in ("timeout", "python3", "jq"):
            # collect-all still calls python3 for muse-collect; keep a path to real python3.
            pass
        env = {
            **os.environ,
            "TOKEN_USAGE_RAW": str(self.raw),
            "PATH": str(HERE) + ":" + os.environ.get("PATH", ""),
            "HOME": self.root.as_posix(),
        }
        if extra_env:
            env.update(extra_env)
        # Wrap: run only the muse function by invoking a tiny copy? Easier to
        # source run() is messy. Instead invoke muse-collect through the same
        # run() snippet used in collect-all.sh.
        script = r'''
set -u
R="$TOKEN_USAGE_RAW"
ts=$(date +%Y-%m-%d_%H%M)
HERE="''' + str(REPO / "bin") + r'''"
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
muse(){ python3 "$HERE/muse-collect.py" --raw-dir "$R" --now "2026-11-21T07:20:00+09:00" "$@"; }
'''
        return script, env

    def test_run_logs_exhausted_ok_and_exits_zero(self):
        script, env = self._run_only_muse()
        proc = subprocess.run(
            ["bash", "-c", script + "run muse muse; echo rc=$?"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK muse exhausted until 2026-11-23 09:00 KST", proc.stdout)
        self.assertRegex(proc.stdout, r"OK .*/\d{4}-\d{2}-\d{2}_\d{4}_muse\.jsonl")
        files = list(self.raw.glob("*_muse.jsonl"))
        new_files = [p for p in files if p.name != "2026-11-19_2350_muse.jsonl"]
        self.assertEqual(len(new_files), 1)
        written = [json.loads(l) for l in new_files[0].read_text().splitlines()]
        self.assertEqual(written[0]["used_percent"], 100)
        self.assertNotIn("rc=1", proc.stdout)
        self.assertIn("rc=0", proc.stdout)

    def test_run_fail_is_nonzero_and_includes_reason(self):
        write_raw(self.raw, "2026-11-19_2350_muse.jsonl", [weekly_row(40)])
        usage = write_json(self.root, "usage.json", NO_USAGE)
        script, env = self._run_only_muse()
        proc = subprocess.run(
            ["bash", "-c", script + f'run muse muse --usage-json "{usage}"; echo rc=$?'],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0)  # echo keeps the shell at 0
        self.assertIn("FAIL muse: server_sent_no_usage", proc.stdout)
        self.assertIn("rc=1", proc.stdout)
        new_files = [p for p in self.raw.glob("*_muse.jsonl") if p.name != "2026-11-19_2350_muse.jsonl"]
        self.assertEqual(new_files, [])


if __name__ == "__main__":
    unittest.main()

"""Muse collection records no-usage faithfully; failures are unexpected errors only."""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
COLLECT = REPO / "bin" / "muse-collect.py"

RESET_UTC = "2026-11-23T00:00:00Z"
NOW = "2026-11-21T07:20:00+09:00"
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


def write_json(directory: Path, name: str, payload) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_executable(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def run_collect(now: str, usage: Path | None = None, env: dict | None = None,
                skip_warmup: bool = True) -> subprocess.CompletedProcess:
    cmd = ["python3", str(COLLECT), "--now", now]
    if skip_warmup:
        cmd.append("--skip-warmup")
    if usage is not None:
        cmd.extend(["--usage-json", str(usage)])
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})


class MuseCollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_usage_is_recorded_faithfully_and_is_not_a_failure(self):
        usage = write_json(self.root, "usage.json", NO_USAGE)
        warmup_flag = self.root / "warmup-ran"
        warmup = write_executable(self.root, "warmup.sh", f"#!/bin/bash\necho ran > '{warmup_flag}'\n")
        proc = run_collect(NOW, usage=usage, env={"MUSE_WARMUP_CMD": str(warmup)}, skip_warmup=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(warmup_flag.exists(), "warmup must still run when usage is missing")
        self.assertIn("muse no usage: server_sent_no_usage;", proc.stderr)
        self.assertNotIn("FAIL", proc.stderr)
        self.assertNotIn("exhausted", proc.stderr)
        self.assertNotIn("exhausted", proc.stdout)
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["service"], "muse")
        self.assertIsNone(row["used_percent"])
        self.assertEqual(row["reason"], "server_sent_no_usage")
        self.assertIn("the server sent no usage data", row["hint"])
        self.assertEqual(row["collected_at"], NOW)
        self.assertEqual(row["source"], "muse-usage.sh")
        self.assertNotIn("status", row)
        self.assertNotEqual(row.get("used_percent"), 100)

    def test_allowance_is_recorded_and_warmup_runs(self):
        usage = write_json(self.root, "usage.json", USAGE_OK)
        warmup_flag = self.root / "warmup-ran"
        warmup = write_executable(self.root, "warmup.sh", f"#!/bin/bash\necho ran > '{warmup_flag}'\n")
        proc = run_collect(NOW, usage=usage, env={"MUSE_WARMUP_CMD": str(warmup)}, skip_warmup=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(warmup_flag.exists())
        self.assertNotIn("no usage", proc.stderr)
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual([r["limit_type"] for r in rows], ["weekly", "window"])
        self.assertEqual(rows[0]["used_percent"], 12)
        self.assertEqual(rows[0]["reset_at"], RESET_UTC)
        self.assertEqual(rows[0]["source"], "muse-usage.sh")

    def test_cli_error_is_a_failure(self):
        proc = run_collect(NOW, env={"MUSE_USAGE_CMD": "/no/such/muse-usage"}, skip_warmup=True)
        # --usage-json not set, so it tries the command
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertTrue(proc.stderr.strip())

    def test_invalid_usage_json_is_a_failure(self):
        bad = self.root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        proc = run_collect(NOW, usage=bad)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("invalid Muse usage JSON", proc.stderr)


class CollectAllRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _run_script(self):
        return r'''
set -u
R="$TOKEN_USAGE_RAW"
HERE="''' + str(REPO / "bin") + r'''"
ts=$(date +%Y-%m-%d_%H%M)
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
muse(){ python3 "$HERE/muse-collect.py" --now "2026-11-21T07:20:00+09:00" --skip-warmup "$@"; }
'''

    def test_run_logs_no_usage_ok_and_exits_zero(self):
        usage = write_json(self.root, "usage.json", NO_USAGE)
        env = {**os.environ, "TOKEN_USAGE_RAW": str(self.raw)}
        proc = subprocess.run(
            ["bash", "-c", self._run_script() + f'run muse muse --usage-json "{usage}"; echo rc=$?'],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertRegex(proc.stdout, r"OK .*/\d{4}-\d{2}-\d{2}_\d{4}_muse\.jsonl")
        self.assertIn("muse no usage: server_sent_no_usage", proc.stdout)
        self.assertNotIn("FAIL muse", proc.stdout)
        self.assertIn("rc=0", proc.stdout)
        files = list(self.raw.glob("*_muse.jsonl"))
        self.assertEqual(len(files), 1)
        row = json.loads(files[0].read_text().splitlines()[0])
        self.assertIsNone(row["used_percent"])
        self.assertEqual(row["reason"], "server_sent_no_usage")

    def test_run_fail_is_nonzero_and_includes_reason(self):
        bad = self.root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        env = {**os.environ, "TOKEN_USAGE_RAW": str(self.raw)}
        proc = subprocess.run(
            ["bash", "-c", self._run_script() + f'run muse muse --usage-json "{bad}"; echo rc=$?'],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FAIL muse: invalid Muse usage JSON", proc.stdout)
        self.assertIn("rc=1", proc.stdout)
        self.assertEqual(list(self.raw.glob("*_muse.jsonl")), [])


if __name__ == "__main__":
    unittest.main()

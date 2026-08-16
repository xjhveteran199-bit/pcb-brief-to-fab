#!/usr/bin/env python3
"""Run every bundled script's self-test and report the aggregate result.

    python selftest.py            # human summary
    python selftest.py --json     # machine-readable

Exit code 0 only if every self-test passed.

What this proves: the bundled scripts behave as documented on synthetic inputs,
including their refusals. What it does NOT prove: that KiCad is installed, that
kicad-cli flags match your version, or that any real board is correct.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGETS = [
    ("feasibility", ["feasibility.py", "--self-test"]),
    ("manifest_check", ["manifest_check.py", "--self-test"]),
    ("netlist_parity", ["netlist_parity.py", "--self-test"]),
    ("fab_audit", ["fab_audit.py", "--self-test"]),
    ("kicad_gate", ["kicad_gate.py", "self-test"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = []
    for name, argv in TARGETS:
        script = HERE / argv[0]
        if not script.is_file():
            results.append({"name": name, "returncode": 127, "stdout": "",
                            "stderr": f"missing script: {script}"})
            continue
        completed = subprocess.run(
            [sys.executable, str(script), *argv[1:]], capture_output=True, text=True
        )
        results.append(
            {
                "name": name,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )

    ok = all(r["returncode"] == 0 for r in results)
    report = {"tool": "selftest", "status": "PASS" if ok else "FAIL", "results": results}

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = "PASS" if r["returncode"] == 0 else "FAIL"
            lines = r["stdout"].splitlines()
            summary = next(
                (line for line in reversed(lines) if "self-test:" in line),
                lines[-1] if lines else r["stderr"][:200],
            )
            print(f"{mark}  {r['name']:<16} {summary}")
        print(f"\nselftest: {report['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

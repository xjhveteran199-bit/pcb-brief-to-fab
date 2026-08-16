#!/usr/bin/env python3
"""Run the KiCad gate sequence with evidence bound to input hashes.

Why a runner instead of shell commands: a shell string silently mangles paths
with spaces, loses stderr, and lets a project-local binary shadow the real tool.
This runner uses argument arrays, records the SHA-256 of every input and of the
CLI executable itself, refuses to write outside the project root, refuses to
overwrite an existing output directory, and stops before manufacturing export
when a gate fails — leaving the failing evidence in place.

    python kicad_gate.py plan --project-root R --manifest m.json --schematic b.kicad_sch --board b.kicad_pcb --output R/evidence/run1
    python kicad_gate.py run  --project-root R --manifest m.json --schematic b.kicad_sch --board b.kicad_pcb --output R/evidence/run1
    python kicad_gate.py self-test

`plan` executes nothing. Show its output to the user before running.

Exit codes: 0 = PASS, 1 = BLOCKED, 2 = usage/setup error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STANDARD_CLI_LOCATIONS = (
    r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
    r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
)


class SetupError(Exception):
    """The gate cannot be attempted at all. Never degrade this into a PASS."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_cli(explicit: str | None, project_root: Path) -> Path:
    """Find kicad-cli, and refuse anything that lives inside the project.

    A binary named kicad-cli sitting in the project directory would turn "run the
    gate" into arbitrary code execution on behalf of whoever supplied the project.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("KICAD_CLI")
    if env:
        candidates.append(env)
    found = shutil.which("kicad-cli")
    if found:
        candidates.append(found)
    candidates.extend(STANDARD_CLI_LOCATIONS)

    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file():
            continue
        if _inside(path, project_root):
            raise SetupError(
                f"refusing to execute {path}: the KiCad CLI must not come from inside the "
                "project directory"
            )
        return path.resolve()
    raise SetupError(
        "kicad-cli not found. Pass --kicad-cli, set KICAD_CLI, or install KiCad. "
        "This environment cannot verify KiCad output; any files authored here remain "
        "AUTHORED_NOT_VERIFIED."
    )


def build_steps(
    cli: Path,
    schematic: Path,
    board: Path,
    output: Path,
    route: str,
    cpl_units: str = "mm",
) -> list[dict]:
    """The fixed operation set. No user-supplied argument reaches a shell."""
    gerbers = output / "gerbers"
    drill = output / "drill"
    steps = [
        {
            "id": "version",
            "phase": "info",
            "argv": [str(cli), "version"],
            "produces": None,
        },
        {
            "id": "erc",
            "phase": "gate",
            "argv": [
                str(cli), "sch", "erc", str(schematic),
                "--output", str(output / "erc.json"),
                "--format", "json",
                "--severity-error", "--severity-warning",
            ],
            "produces": output / "erc.json",
        },
        {
            "id": "netlist",
            "phase": "gate",
            "argv": [
                str(cli), "sch", "export", "netlist", str(schematic),
                "--output", str(output / "netlist.xml"),
                "--format", "kicadxml",
            ],
            "produces": output / "netlist.xml",
        },
        {
            "id": "bom",
            "phase": "gate",
            "argv": [
                str(cli), "sch", "export", "bom", str(schematic),
                "--output", str(output / "bom.csv"),
            ],
            "produces": output / "bom.csv",
        },
        {
            "id": "drc",
            "phase": "gate",
            "argv": [
                str(cli), "pcb", "drc", str(board),
                "--output", str(output / "drc.json"),
                "--format", "json",
                "--schematic-parity",
                "--severity-error", "--severity-warning",
            ],
            "produces": output / "drc.json",
        },
        {
            "id": "gerbers",
            "phase": "manufacturing",
            "argv": [
                str(cli), "pcb", "export", "gerbers", str(board),
                "--output", str(gerbers),
            ],
            "produces": gerbers,
        },
        {
            "id": "drill",
            "phase": "manufacturing",
            "argv": [
                str(cli), "pcb", "export", "drill", str(board),
                "--output", str(drill),
            ],
            "produces": drill,
        },
    ]
    if route == "pcba":
        steps.append(
            {
                "id": "pos",
                "phase": "manufacturing",
                "argv": [
                    str(cli), "pcb", "export", "pos", str(board),
                    "--output", str(output / "cpl.csv"),
                    "--format", "csv",
                    "--units", cpl_units,
                ],
                "produces": output / "cpl.csv",
            }
        )
    return steps


def _count_violations(node) -> dict[str, int]:
    """Count severities in a KiCad violation list, tolerating both report shapes."""
    counts = {"error": 0, "warning": 0, "other": 0, "total": 0}
    if isinstance(node, list):
        for item in node:
            counts["total"] += 1
            severity = str(item.get("severity", "")).lower() if isinstance(item, dict) else ""
            if severity == "error":
                counts["error"] += 1
            elif severity == "warning":
                counts["warning"] += 1
            else:
                counts["other"] += 1
    return counts


def parse_erc(report: dict) -> dict:
    if not isinstance(report, dict):
        raise SetupError("ERC report is not a JSON object")
    if "sheets" in report and isinstance(report["sheets"], list):
        merged: list = []
        for sheet in report["sheets"]:
            if isinstance(sheet, dict):
                merged.extend(sheet.get("violations", []) or [])
        counts = _count_violations(merged)
    elif "violations" in report:
        counts = _count_violations(report.get("violations"))
    else:
        raise SetupError(
            "ERC report has neither 'sheets' nor 'violations'; refusing to read it as clean"
        )
    counts["kicad_version"] = report.get("kicad_version")
    return counts


def parse_drc(report: dict) -> dict:
    if not isinstance(report, dict):
        raise SetupError("DRC report is not a JSON object")
    for key in ("violations", "unconnected_items", "schematic_parity"):
        if key not in report:
            raise SetupError(
                f"DRC report is missing {key!r}; a report that omits a category must never be "
                "read as zero for that category"
            )
    return {
        "violations": _count_violations(report.get("violations")),
        "unconnected": _count_violations(report.get("unconnected_items")),
        "parity": _count_violations(report.get("schematic_parity")),
        "kicad_version": report.get("kicad_version"),
    }


def evaluate(erc: dict, drc: dict, allowances: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if erc["error"] > 0:
        reasons.append(f"ERC errors: {erc['error']}")
    if drc["violations"]["error"] > allowances.get("allow_drc_violations", 0):
        reasons.append(f"DRC errors: {drc['violations']['error']}")
    if drc["unconnected"]["total"] > allowances.get("allow_unconnected", 0):
        reasons.append(f"unconnected items: {drc['unconnected']['total']}")
    if drc["parity"]["total"] > allowances.get("allow_schematic_parity_issues", 0):
        reasons.append(f"schematic parity differences: {drc['parity']['total']}")
    return (not reasons), reasons


def prepare(args) -> dict:
    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        raise SetupError(f"project root is not a directory: {project_root}")

    inputs = {"manifest": args.manifest, "schematic": args.schematic, "board": args.board}
    for label, path in inputs.items():
        if not path.is_file():
            raise SetupError(f"{label} not found: {path}")
        if not _inside(path, project_root):
            raise SetupError(f"{label} is outside the project root: {path}")

    output = args.output.resolve()
    if not _inside(output, project_root):
        raise SetupError(
            f"output directory is outside the project root: {output}. Evidence stays with "
            "the project."
        )
    if output.exists():
        raise SetupError(
            f"output directory already exists: {output}. Give every attempt a new directory; "
            "never overwrite or rename previous evidence."
        )

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SetupError(f"manifest is not valid JSON: {exc}") from exc

    route = manifest.get("project", {}).get("route", "pcb-only")
    allowances = manifest.get("gates", {}) or {}
    cpl_units = (manifest.get("assembly", {}) or {}).get("cpl_units", "mm")
    cli = resolve_cli(args.kicad_cli, project_root)

    return {
        "project_root": project_root,
        "output": output,
        "manifest": manifest,
        "route": route,
        "allowances": allowances,
        "cli": cli,
        "cli_sha256": sha256(cli),
        "input_hashes": {label: sha256(path) for label, path in inputs.items()},
        "input_paths": {label: str(path) for label, path in inputs.items()},
        "steps": build_steps(cli, args.schematic, args.board, output, route, cpl_units),
    }


def do_plan(args) -> int:
    context = prepare(args)
    plan = {
        "tool": "kicad_gate",
        "mode": "plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(context["project_root"]),
        "output": str(context["output"]),
        "route": context["route"],
        "kicad_cli": str(context["cli"]),
        "kicad_cli_sha256": context["cli_sha256"],
        "input_paths": context["input_paths"],
        "input_hashes": context["input_hashes"],
        "allowances": context["allowances"],
        "steps": [{"id": s["id"], "phase": s["phase"], "argv": s["argv"]} for s in context["steps"]],
        "note": "plan executes nothing. Manufacturing steps run only if every gate passes.",
    }
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


def do_run(args) -> int:
    context = prepare(args)
    output: Path = context["output"]
    output.mkdir(parents=True, exist_ok=False)

    records: list[dict] = []
    erc_counts: dict | None = None
    drc_counts: dict | None = None
    status = "PASS"
    reasons: list[str] = []

    for step in context["steps"]:
        if step["phase"] == "manufacturing" and status != "PASS":
            records.append({"id": step["id"], "skipped": "gates did not pass"})
            continue
        completed = subprocess.run(  # noqa: S603 - fixed argv, never a shell string
            step["argv"], capture_output=True, text=True, cwd=str(context["project_root"])
        )
        record = {
            "id": step["id"],
            "phase": step["phase"],
            "argv": step["argv"],
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
        records.append(record)

        if step["id"] == "version":
            record["kicad_cli_version"] = completed.stdout.strip()
            continue

        # kicad-cli returns nonzero when violations exist; that is data, not a crash.
        produced: Path | None = step["produces"]
        if produced is not None and not produced.exists():
            status = "BLOCKED"
            reasons.append(f"{step['id']} produced no output (rc={completed.returncode})")
            continue

        if step["id"] == "erc":
            try:
                erc_counts = parse_erc(json.loads(produced.read_text(encoding="utf-8")))
            except (SetupError, json.JSONDecodeError) as exc:
                status = "BLOCKED"
                reasons.append(f"ERC report unreadable: {exc}")
        elif step["id"] == "drc":
            try:
                drc_counts = parse_drc(json.loads(produced.read_text(encoding="utf-8")))
            except (SetupError, json.JSONDecodeError) as exc:
                status = "BLOCKED"
                reasons.append(f"DRC report unreadable: {exc}")
            if erc_counts is not None and drc_counts is not None:
                passed, why = evaluate(erc_counts, drc_counts, context["allowances"])
                if not passed:
                    status = "BLOCKED"
                    reasons.extend(why)

    if erc_counts is None or drc_counts is None:
        status = "BLOCKED"
        if "ERC or DRC never produced counts" not in reasons:
            reasons.append("ERC or DRC never produced counts")

    # Re-hash the inputs: if a source changed during the run, the evidence is void.
    after = {
        label: sha256(Path(path)) for label, path in context["input_paths"].items()
    }
    if after != context["input_hashes"]:
        status = "BLOCKED"
        reasons.append("a source file changed while the gate was running; evidence is void")

    report = {
        "tool": "kicad_gate",
        "mode": "run",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "reasons": reasons,
        "project_root": str(context["project_root"]),
        "output": str(output),
        "route": context["route"],
        "kicad_cli": str(context["cli"]),
        "kicad_cli_sha256": context["cli_sha256"],
        "input_paths": context["input_paths"],
        "input_hashes_before": context["input_hashes"],
        "input_hashes_after": after,
        "allowances": context["allowances"],
        "erc": erc_counts,
        "drc": drc_counts,
        "steps": records,
        "limits": [
            "Zero findings means one tool found nothing blocking in these exact files.",
            "It does not prove topology, ratings, thermal or EMC behaviour, safety, or function.",
            "Gerber visual inspection, manufacturer preview and human review are still required.",
        ],
    }
    (output / "gate_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for reason in reasons:
        print(f"[blocking] {reason}")
    print(f"kicad_gate: {status} — evidence in {output}")
    return 0 if status == "PASS" else 1


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def self_test() -> int:
    """Verify everything that does not require a real KiCad installation.

    This self-test does NOT prove that kicad-cli works, that its flags are correct
    for your version, or that a real board passes. It proves argument construction,
    report parsing, gate arithmetic, and the refusals.
    """
    checks: list[tuple[str, bool]] = []

    def expect(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "project"
        (root).mkdir()
        sch = root / "b.kicad_sch"
        pcb = root / "b.kicad_pcb"
        man = root / "m.json"
        sch.write_text("(kicad_sch)", encoding="utf-8")
        pcb.write_text("(kicad_pcb)", encoding="utf-8")
        man.write_text(json.dumps({
            "project": {"route": "pcb-only"},
            "gates": {"allow_drc_violations": 0, "allow_unconnected": 0,
                      "allow_schematic_parity_issues": 0},
        }), encoding="utf-8")

        fake_cli = Path(td) / "kicad-cli"
        fake_cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_cli.chmod(0o755)

        steps = build_steps(fake_cli, sch, pcb, root / "out", "pcb-only")
        ids = [s["id"] for s in steps]
        expect("pcb-only step order", ids == ["version", "erc", "netlist", "bom", "drc",
                                              "gerbers", "drill"])
        pcba_ids = [s["id"] for s in build_steps(fake_cli, sch, pcb, root / "o2", "pcba")]
        expect("pcba adds a position export", pcba_ids[-1] == "pos")
        erc_argv = next(s for s in steps if s["id"] == "erc")["argv"]
        expect("erc asks for json", "--format" in erc_argv and "json" in erc_argv)
        drc_argv = next(s for s in steps if s["id"] == "drc")["argv"]
        expect("drc asks for schematic parity", "--schematic-parity" in drc_argv)
        expect("every argv element is a string",
               all(isinstance(a, str) for s in steps for a in s["argv"]))
        expect("manufacturing steps are labelled",
               {s["phase"] for s in steps if s["id"] in {"gerbers", "drill"}} == {"manufacturing"})

        # --- report parsing -------------------------------------------------
        expect("erc sheets shape parses",
               parse_erc({"sheets": [{"violations": [{"severity": "error"},
                                                     {"severity": "warning"}]}]})["error"] == 1)
        expect("erc flat shape parses",
               parse_erc({"violations": [{"severity": "error"}]})["error"] == 1)
        expect("erc clean is zero", parse_erc({"sheets": []})["error"] == 0)

        raised = False
        try:
            parse_erc({"unexpected": True})
        except SetupError:
            raised = True
        expect("an ERC report with no violation key raises rather than reading as clean", raised)

        drc_ok = {"violations": [], "unconnected_items": [], "schematic_parity": []}
        parsed = parse_drc(drc_ok)
        expect("clean drc parses to zeros",
               parsed["violations"]["total"] == 0 and parsed["unconnected"]["total"] == 0)
        for key in ("violations", "unconnected_items", "schematic_parity"):
            partial = dict(drc_ok)
            partial.pop(key)
            raised = False
            try:
                parse_drc(partial)
            except SetupError:
                raised = True
            expect(f"a DRC report missing {key} raises", raised)

        allow = {"allow_drc_violations": 0, "allow_unconnected": 0,
                 "allow_schematic_parity_issues": 0}
        clean_erc = parse_erc({"sheets": []})
        expect("clean gates pass", evaluate(clean_erc, parse_drc(drc_ok), allow)[0])
        expect("erc errors block",
               not evaluate(parse_erc({"violations": [{"severity": "error"}]}),
                            parse_drc(drc_ok), allow)[0])
        expect("unconnected items block",
               not evaluate(clean_erc,
                            parse_drc({"violations": [], "unconnected_items": [{"a": 1}],
                                       "schematic_parity": []}), allow)[0])
        expect("parity differences block",
               not evaluate(clean_erc,
                            parse_drc({"violations": [], "unconnected_items": [],
                                       "schematic_parity": [{"a": 1}]}), allow)[0])
        expect("drc warnings alone do not block",
               evaluate(clean_erc,
                        parse_drc({"violations": [{"severity": "warning"}],
                                   "unconnected_items": [], "schematic_parity": []}), allow)[0])

        # --- refusals -------------------------------------------------------
        def prep(**over):
            base = dict(project_root=root, manifest=man, schematic=sch, board=pcb,
                        output=root / "evidence" / "run1", kicad_cli=str(fake_cli))
            base.update(over)
            return prepare(_Args(**base))

        expect("a valid setup prepares", prep()["route"] == "pcb-only")

        existing = root / "evidence" / "already"
        existing.mkdir(parents=True)
        raised = False
        try:
            prep(output=existing)
        except SetupError:
            raised = True
        expect("an existing output directory is refused", raised)

        raised = False
        try:
            prep(output=Path(td) / "outside")
        except SetupError:
            raised = True
        expect("an output outside the project root is refused", raised)

        outside_sch = Path(td) / "elsewhere.kicad_sch"
        outside_sch.write_text("(kicad_sch)", encoding="utf-8")
        raised = False
        try:
            prep(schematic=outside_sch)
        except SetupError:
            raised = True
        expect("an input outside the project root is refused", raised)

        shadow = root / "kicad-cli"
        shadow.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shadow.chmod(0o755)
        raised = False
        try:
            resolve_cli(str(shadow), root)
        except SetupError:
            raised = True
        expect("a CLI inside the project directory is refused", raised)

        raised = False
        try:
            resolve_cli(str(Path(td) / "no-such-cli"), Path(td) / "empty-root")
        except SetupError:
            raised = True
        expect("a missing CLI raises instead of degrading to PASS", raised)

        bad_manifest = root / "bad.json"
        bad_manifest.write_text("{nope", encoding="utf-8")
        raised = False
        try:
            prep(manifest=bad_manifest)
        except SetupError:
            raised = True
        expect("an unparsable manifest raises", raised)

        # --- hash binding ---------------------------------------------------
        before = prep()["input_hashes"]["schematic"]
        sch.write_text("(kicad_sch modified)", encoding="utf-8")
        expect("a modified source produces a different hash", prep()["input_hashes"]["schematic"] != before)

    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print(f"FAIL: {name}", file=sys.stderr)
    print(f"kicad_gate self-test: {'PASS' if not failed else 'FAIL'} "
          f"({len(checks) - len(failed)}/{len(checks)})")
    print("note: this self-test does not prove kicad-cli works or that its flags match "
          "your KiCad version. Run `kicad-cli --help` on the host and confirm.")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--project-root", type=Path, required=True)
        p.add_argument("--manifest", type=Path, required=True)
        p.add_argument("--schematic", type=Path, required=True)
        p.add_argument("--board", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--kicad-cli")

    sub.add_parser("self-test")
    args = parser.parse_args()

    if args.command == "self-test":
        return self_test()
    try:
        return do_plan(args) if args.command == "plan" else do_run(args)
    except SetupError as exc:
        print(f"kicad_gate: BLOCKED — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

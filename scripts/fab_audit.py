#!/usr/bin/env python3
"""Structurally audit a PCB fabrication package (directory or ZIP).

This is an independent auditor, deliberately not sharing code with whatever
exported the package. It answers questions about *files*:

  - what is in the package, and what is each file;
  - does the copper layer count match the manifest;
  - is there exactly one board outline, and are drill files present and parsable;
  - does the smallest drill meet the declared minimum;
  - does the .gbrjob metadata agree with the manifest;
  - for PCBA: do BOM and CPL designator sets agree with each other and with the
    fitted set implied by the DNP policy.

It CANNOT prove that the outline is closed, that copper is electrically correct,
or that holes align with pads. Those need an independent Gerber viewer and the
target manufacturer's current upload preview. Say so in every report.

    python fab_audit.py <dir-or-zip> --manifest m.json --json-out audit.json --strict
    python fab_audit.py <dir-or-zip> --expected-copper-layers 4 --expected-board-size-mm 38 90
    python fab_audit.py --self-test

Exit codes: 0 = no blocking findings, 1 = blocking findings, 2 = usage/parse error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

MAX_ZIP_MEMBERS = 5000
MAX_ZIP_UNCOMPRESSED = 512 * 1024 * 1024  # 512 MiB

DESIGNATOR_COLUMNS = (
    "designator",
    "designators",
    "refdes",
    "reference",
    "references",
    "ref",
    "refs",
    "part",
)
SIDE_COLUMNS = ("layer", "side", "assembly side", "mount", "placement")
ROTATION_COLUMNS = ("rotation", "rot", "angle")
X_COLUMNS = ("mid x", "midx", "x", "ref x", "center-x", "posx", "position x")
Y_COLUMNS = ("mid y", "midy", "y", "ref y", "center-y", "posy", "position y")
MPN_COLUMNS = ("mpn", "manufacturer part number", "manufacturer_part_number", "part number",
               "lcsc part #", "lcsc", "supplier part", "jlcpcb part #")

NON_MANUFACTURING_TOKENS = (
    "courtyard", "fab", "margin", "user", "dwgs", "cmts", "comment",
    "eco1", "eco2", "eco", "adhes", "adhesive", "3d", "model",
)
OUTLINE_TOKENS = ("edge_cuts", "edgecuts", "edge cuts", "outline", "profile", "boardoutline")
DOCUMENT_EXTS = {".md", ".pdf", ".rtf", ".doc", ".docx", ".html"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Findings:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, level: str, code: str, message: str, files: Iterable[str] = ()) -> None:
        self.items.append({"level": level, "code": code, "message": message, "files": sorted(files)})

    def block(self, code: str, message: str, files: Iterable[str] = ()) -> None:
        self.add("blocking", code, message, files)

    def warn(self, code: str, message: str, files: Iterable[str] = ()) -> None:
        self.add("warning", code, message, files)

    def info(self, code: str, message: str, files: Iterable[str] = ()) -> None:
        self.add("info", code, message, files)

    @property
    def blocking(self) -> list[dict]:
        return [i for i in self.items if i["level"] == "blocking"]

    @property
    def warnings(self) -> list[dict]:
        return [i for i in self.items if i["level"] == "warning"]


def _suffix_part(stem: str) -> str:
    """The layer-identifying tail of a KiCad-style filename.

    ``myproject-F_Courtyard`` -> ``f_courtyard``.  Splitting on the last hyphen
    keeps a project name such as ``fabrikam`` from being read as the Fab layer.
    """
    tail = stem.rsplit("-", 1)[-1] if "-" in stem else stem
    return tail.lower()


def classify(name: str, head: bytes = b"") -> str:
    """Classify one package file by name, with a small content sniff for drills."""
    path = Path(name)
    ext = path.suffix.lower()
    stem = path.stem
    tail = _suffix_part(stem)

    if ext == ".gbrjob":
        return "job"
    if "drl_map" in tail or "drill_map" in tail or "drillmap" in tail or "drill map" in tail:
        return "drill_map"
    if ext in {".drl", ".xln", ".nc", ".exc"}:
        return "drill"
    if ext == ".txt":
        if "drl" in tail or "drill" in tail or head.lstrip()[:3].upper() == b"M48":
            return "drill"
        return "document"
    if ext in {".csv", ".tsv"}:
        return "table"
    if ext in DOCUMENT_EXTS:
        return "document"

    if any(token in tail for token in OUTLINE_TOKENS) or ext in {".gko", ".gm1", ".gm3"}:
        return "outline"
    if any(token in tail for token in NON_MANUFACTURING_TOKENS):
        return "non_manufacturing"
    if "paste" in tail or ext in {".gtp", ".gbp"}:
        return "paste"
    if "mask" in tail or ext in {".gts", ".gbs"}:
        return "mask"
    if "silk" in tail or ext in {".gto", ".gbo"}:
        return "silkscreen"
    if (
        "_cu" in tail
        or tail in {"f.cu", "b.cu"}
        or ext in {".gtl", ".gbl"}
        or re.fullmatch(r"\.g\d+l?", ext) is not None
    ):
        return "copper"
    return "unknown"


def parse_excellon(text: str) -> dict:
    """Extract tool diameters in millimetres from an Excellon drill file."""
    units = None
    if re.search(r"^\s*METRIC", text, re.M):
        units = "mm"
    elif re.search(r"^\s*INCH", text, re.M):
        units = "in"
    tools: dict[str, float] = {}
    for match in re.finditer(r"^T(\d+)C([0-9]*\.?[0-9]+)", text, re.M):
        tools[match.group(1)] = float(match.group(2))
    scale = 25.4 if units == "in" else 1.0
    return {
        "units": units,
        "tool_count": len(tools),
        "diameters_mm": sorted(round(d * scale, 4) for d in tools.values()),
    }


def _norm_header(row: dict) -> dict:
    return {(k or "").strip().lower(): (v if v is not None else "") for k, v in row.items()}


def _pick(row: dict, candidates: Iterable[str]) -> str | None:
    for key in candidates:
        if key in row and str(row[key]).strip() != "":
            return str(row[key]).strip()
    return None


def _split_designators(cell: str) -> list[str]:
    return [d for d in re.split(r"[,\s;]+", cell.strip()) if d]


def read_table(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [_norm_header(row) for row in reader]


# --------------------------------------------------------------------------- #
# package loading
# --------------------------------------------------------------------------- #

def load_package(source: Path, workdir: Path) -> tuple[Path, list[str]]:
    """Return (root directory, list of extraction problems)."""
    problems: list[str] = []
    if source.is_dir():
        return source, problems
    if not source.exists():
        raise FileNotFoundError(f"package not found: {source}")
    if source.suffix.lower() != ".zip":
        raise ValueError(f"{source}: expected a directory or a .zip archive")

    target = workdir / "extracted"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError(f"{source}: {len(members)} members exceeds the {MAX_ZIP_MEMBERS} limit")
        total = sum(m.file_size for m in members)
        if total > MAX_ZIP_UNCOMPRESSED:
            raise ValueError(f"{source}: uncompressed size {total} exceeds the limit")
        seen: set[str] = set()
        for member in members:
            name = member.filename
            if member.is_dir():
                continue
            pure = Path(name)
            if pure.is_absolute() or ".." in pure.parts or name.startswith("/") or ":" in pure.parts[0]:
                problems.append(f"refused unsafe archive path: {name}")
                continue
            if name in seen:
                problems.append(f"duplicate archive entry: {name}")
                continue
            seen.add(name)
            destination = (target / pure).resolve()
            if not str(destination).startswith(str(target.resolve())):
                problems.append(f"refused escaping archive path: {name}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    # If the archive wrapped everything in a single folder, descend into it.
    entries = [p for p in target.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0], problems
    return target, problems


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #

def audit(
    root: Path,
    *,
    route: str,
    expected_copper_layers: int | None,
    expected_size_mm: tuple[float, float] | None,
    expected_thickness_mm: float | None,
    expected_min_drill_mm: float | None,
    assembly_sides: list[str],
    dnp: set[str],
    excluded: set[str],
    expected_fitted: set[str] | None,
    bom: Path | None,
    cpl: Path | None,
    strict: bool,
    extraction_problems: Iterable[str] = (),
) -> dict:
    f = Findings()
    for problem in extraction_problems:
        f.block("archive_unsafe", problem)

    inventory: list[dict] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        category = classify(rel, data[:64])
        inventory.append(
            {
                "file": rel,
                "category": category,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
            }
        )
        if len(data) == 0:
            f.block("empty_file", f"{rel} is zero bytes", [rel])

    if not inventory:
        f.block("empty_package", "package contains no files")

    def of(category: str) -> list[str]:
        return [i["file"] for i in inventory if i["category"] == category]

    copper = of("copper")
    outline = of("outline")
    drill = of("drill")
    mask = of("mask")
    silk = of("silkscreen")
    paste = of("paste")
    job = of("job")
    non_mfg = of("non_manufacturing")
    unknown = of("unknown")

    # --- copper layers ------------------------------------------------------
    if expected_copper_layers is not None:
        if len(copper) != expected_copper_layers:
            f.block(
                "copper_layer_count",
                f"found {len(copper)} copper layer file(s), manifest declares "
                f"{expected_copper_layers}",
                copper,
            )
    elif not copper:
        f.block("no_copper", "no copper layer files found")

    # --- outline ------------------------------------------------------------
    if len(outline) == 0:
        f.block("no_outline", "no board outline layer found")
    elif len(outline) > 1:
        f.block(
            "multiple_outlines",
            f"{len(outline)} outline layers found; send exactly one so the fab cannot guess",
            outline,
        )

    # --- drill --------------------------------------------------------------
    drill_summary: list[dict] = []
    if not drill:
        f.block("no_drill", "no drill file found")
    for rel in drill:
        parsed = parse_excellon((root / rel).read_text(encoding="utf-8", errors="replace"))
        parsed["file"] = rel
        drill_summary.append(parsed)
        if parsed["tool_count"] == 0:
            f.block("drill_unparsable", f"{rel} declares no tools; it is not a usable drill file", [rel])
        if parsed["units"] is None:
            f.warn("drill_units_unstated", f"{rel} states neither METRIC nor INCH", [rel])
    all_diameters = [d for s in drill_summary for d in s["diameters_mm"]]
    if all_diameters and expected_min_drill_mm is not None:
        smallest = min(all_diameters)
        if smallest + 1e-6 < expected_min_drill_mm:
            f.block(
                "drill_below_minimum",
                f"smallest drill {smallest} mm is below the declared minimum "
                f"{expected_min_drill_mm} mm",
            )

    # --- mask / silk / paste ------------------------------------------------
    if len(mask) < 2:
        f.warn("mask_incomplete", f"expected top and bottom soldermask, found {len(mask)}", mask)
    if not silk:
        f.info("no_silkscreen", "no silkscreen layer in the package")
    if route == "pcb-only" and paste:
        f.block(
            "paste_in_bare_board_package",
            "paste layers are present in a pcb-only package; either you are ordering "
            "assembly or you are not",
            paste,
        )
    if route == "pcba":
        if not paste:
            f.block("no_paste", "route is pcba but the package has no paste layer")
        elif assembly_sides and len(paste) < len(assembly_sides):
            f.block(
                "paste_side_missing",
                f"{len(assembly_sides)} assembly side(s) declared but only {len(paste)} "
                "paste layer(s) present",
                paste,
            )

    # --- stray files --------------------------------------------------------
    if non_mfg:
        level = f.block if strict else f.warn
        level(
            "non_manufacturing_layer",
            f"{len(non_mfg)} non-manufacturing layer(s) in the package (Courtyard/Fab/"
            "Margin/User/Dwgs/Eco/adhesive are not manufacturing data)",
            non_mfg,
        )
    if unknown:
        level = f.block if strict else f.warn
        level(
            "unknown_file",
            f"{len(unknown)} file(s) could not be identified; a fab either ignores them, "
            "asks and delays the order, or guesses",
            unknown,
        )

    # --- job file -----------------------------------------------------------
    job_summary: dict = {}
    for rel in job:
        try:
            data = json.loads((root / rel).read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            f.block("job_unparsable", f"{rel} is not valid JSON ({exc})", [rel])
            continue
        specs = data.get("GeneralSpecs", {}) if isinstance(data, dict) else {}
        size = specs.get("Size", {}) if isinstance(specs, dict) else {}
        job_summary = {
            "file": rel,
            "size_x": size.get("X"),
            "size_y": size.get("Y"),
            "layer_number": specs.get("LayerNumber"),
            "thickness_mm": (specs.get("BoardThickness") if isinstance(specs, dict) else None),
        }
        if expected_size_mm and size.get("X") is not None and size.get("Y") is not None:
            got = (float(size["X"]), float(size["Y"]))
            want = tuple(float(v) for v in expected_size_mm)
            if not (
                (abs(got[0] - want[0]) <= 0.5 and abs(got[1] - want[1]) <= 0.5)
                or (abs(got[0] - want[1]) <= 0.5 and abs(got[1] - want[0]) <= 0.5)
            ):
                f.block(
                    "job_size_mismatch",
                    f"{rel} records {got[0]} x {got[1]} mm but the manifest says "
                    f"{want[0]} x {want[1]} mm. A package whose metadata contradicts its own "
                    "documentation cannot be ordered.",
                    [rel],
                )
        if expected_copper_layers is not None and specs.get("LayerNumber") is not None:
            if int(specs["LayerNumber"]) != expected_copper_layers:
                f.block(
                    "job_layer_mismatch",
                    f"{rel} records {specs['LayerNumber']} layers, manifest declares "
                    f"{expected_copper_layers}",
                    [rel],
                )
        if expected_thickness_mm is not None and job_summary.get("thickness_mm") is not None:
            try:
                if abs(float(job_summary["thickness_mm"]) - expected_thickness_mm) > 0.05:
                    f.block(
                        "job_thickness_mismatch",
                        f"{rel} records thickness {job_summary['thickness_mm']} mm, manifest "
                        f"declares {expected_thickness_mm} mm",
                        [rel],
                    )
            except (TypeError, ValueError):
                f.warn("job_thickness_unreadable", f"{rel} thickness is not a number", [rel])
    if not job:
        f.info("no_job_file", "no .gbrjob present; metadata cross-check was skipped")

    # --- BOM / CPL ----------------------------------------------------------
    assembly_summary: dict = {}
    if route == "pcba":
        if bom is None or cpl is None:
            f.block("bom_cpl_missing", "route is pcba but --bom and/or --cpl was not provided")
        else:
            bom_rows = read_table(bom)
            cpl_rows = read_table(cpl)
            bom_designators: list[str] = []
            missing_mpn: list[str] = []
            for row in bom_rows:
                cell = _pick(row, DESIGNATOR_COLUMNS)
                if cell is None:
                    f.block("bom_no_designator", f"a BOM row has no designator column: {row}")
                    continue
                refs = _split_designators(cell)
                bom_designators.extend(refs)
                if _pick(row, MPN_COLUMNS) is None:
                    missing_mpn.extend(refs)
            cpl_designators: list[str] = []
            for row in cpl_rows:
                ref = _pick(row, DESIGNATOR_COLUMNS)
                if ref is None:
                    f.block("cpl_no_designator", f"a CPL row has no designator column: {row}")
                    continue
                cpl_designators.append(ref)
                rotation = _pick(row, ROTATION_COLUMNS)
                if rotation is None:
                    f.block("cpl_no_rotation", f"CPL row {ref} has no rotation column", [])
                else:
                    try:
                        float(rotation)
                    except ValueError:
                        f.block("cpl_bad_rotation", f"CPL row {ref} rotation {rotation!r} is not a number")
                for axis, cols in (("X", X_COLUMNS), ("Y", Y_COLUMNS)):
                    value = _pick(row, cols)
                    if value is None:
                        f.block("cpl_no_position", f"CPL row {ref} has no {axis} column")
                side = _pick(row, SIDE_COLUMNS)
                if side is None:
                    f.block("cpl_no_side", f"CPL row {ref} has no side/layer column")
                elif assembly_sides and side.strip().capitalize() not in assembly_sides:
                    f.block(
                        "cpl_unexpected_side",
                        f"CPL row {ref} is on side {side!r}, which is not in the declared "
                        f"assembly sides {assembly_sides}",
                    )

            def duplicates(values: list[str]) -> list[str]:
                seen: set[str] = set()
                dupes: set[str] = set()
                for v in values:
                    if v in seen:
                        dupes.add(v)
                    seen.add(v)
                return sorted(dupes)

            if duplicates(bom_designators):
                f.block("bom_duplicate", "duplicate designators in BOM: "
                        + ", ".join(duplicates(bom_designators)))
            if duplicates(cpl_designators):
                f.block("cpl_duplicate", "duplicate designators in CPL: "
                        + ", ".join(duplicates(cpl_designators)))

            bom_set = set(bom_designators)
            cpl_set = set(cpl_designators)
            fitted = bom_set - dnp - excluded

            leaked = sorted(cpl_set & dnp)
            if leaked:
                f.block("dnp_in_cpl", "do-not-fit parts present in the CPL: " + ", ".join(leaked))
            missing_in_cpl = sorted(fitted - cpl_set)
            if missing_in_cpl:
                f.block("fitted_missing_from_cpl",
                        "fitted parts absent from the CPL: " + ", ".join(missing_in_cpl))
            extra_in_cpl = sorted(cpl_set - fitted - dnp - excluded)
            if extra_in_cpl:
                f.block("cpl_extra", "CPL lists parts that are not in the fitted set: "
                        + ", ".join(extra_in_cpl))
            if expected_fitted is not None and fitted != expected_fitted:
                f.block(
                    "fitted_set_mismatch",
                    "fitted set derived from the BOM does not match the expected set; "
                    f"only in BOM: {sorted(fitted - expected_fitted)}; "
                    f"only expected: {sorted(expected_fitted - fitted)}",
                )
            if missing_mpn:
                f.warn(
                    "bom_missing_mpn",
                    "no manufacturer/MPN/supplier field for: " + ", ".join(sorted(set(missing_mpn)))
                    + " — the assembler will substitute",
                )
            assembly_summary = {
                "bom_rows": len(bom_rows),
                "cpl_rows": len(cpl_rows),
                "bom_designators": len(bom_set),
                "cpl_designators": len(cpl_set),
                "fitted": sorted(fitted),
                "dnp": sorted(dnp),
                "excluded": sorted(excluded),
            }

    status = "BLOCKED" if f.blocking else "PASS"
    return {
        "tool": "fab_audit",
        "root": str(root),
        "route": route,
        "strict": strict,
        "status": status,
        "blocking": len(f.blocking),
        "warnings": len(f.warnings),
        "counts": {
            "files": len(inventory),
            "copper": len(copper),
            "outline": len(outline),
            "drill": len(drill),
            "mask": len(mask),
            "silkscreen": len(silk),
            "paste": len(paste),
            "job": len(job),
            "non_manufacturing": len(non_mfg),
            "unknown": len(unknown),
        },
        "drill": drill_summary,
        "job": job_summary,
        "assembly": assembly_summary,
        "inventory": inventory,
        "findings": f.items,
        "limits": [
            "This auditor checks file structure and metadata consistency only.",
            "It does not prove the outline is closed, that copper is electrically correct, "
            "or that holes align with pads.",
            "An independent Gerber viewer inspection and the target manufacturer's current "
            "upload preview are still required before ordering.",
        ],
    }


def audit_source(source: Path, args_like: dict, strict: bool) -> dict:
    with tempfile.TemporaryDirectory() as td:
        root, problems = load_package(source, Path(td))
        return audit(root, strict=strict, extraction_problems=problems, **args_like)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def manifest_options(manifest_path: Path | None) -> dict:
    if manifest_path is None:
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    board = manifest.get("board", {})
    dfm = manifest.get("dfm", {})
    assembly = manifest.get("assembly", {})
    outline = board.get("physical_outline_mm")
    return {
        "route": manifest.get("project", {}).get("route", "pcb-only"),
        "expected_copper_layers": board.get("copper_layers"),
        "expected_size_mm": tuple(outline) if isinstance(outline, list) and len(outline) == 2 else None,
        "expected_thickness_mm": board.get("thickness_mm"),
        "expected_min_drill_mm": dfm.get("min_drill_mm"),
        "assembly_sides": list(assembly.get("sides", []) or []),
        "dnp": set(assembly.get("dnp_designators", []) or []),
        "excluded": set(assembly.get("excluded_designators", []) or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("package", nargs="?", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--route", choices=["pcb-only", "pcba"])
    parser.add_argument("--expected-copper-layers", type=int)
    parser.add_argument("--expected-board-size-mm", nargs=2, type=float, metavar=("X", "Y"))
    parser.add_argument("--expected-board-thickness-mm", type=float)
    parser.add_argument("--expected-minimum-drill-mm", type=float)
    parser.add_argument("--assembly-side", action="append", default=[])
    parser.add_argument("--dnp-designator", action="append", default=[])
    parser.add_argument("--excluded-designator", action="append", default=[])
    parser.add_argument("--expected-fitted-designator", action="append", default=[])
    parser.add_argument("--bom", type=Path)
    parser.add_argument("--cpl", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.package is None:
        parser.error("package path is required unless --self-test is given")

    options = {
        "route": "pcb-only",
        "expected_copper_layers": None,
        "expected_size_mm": None,
        "expected_thickness_mm": None,
        "expected_min_drill_mm": None,
        "assembly_sides": [],
        "dnp": set(),
        "excluded": set(),
        "expected_fitted": None,
        "bom": args.bom,
        "cpl": args.cpl,
    }
    try:
        options.update(manifest_options(args.manifest))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"fab_audit: BLOCKED — manifest unreadable ({exc})", file=sys.stderr)
        return 2

    if args.route:
        options["route"] = args.route
    if args.expected_copper_layers is not None:
        options["expected_copper_layers"] = args.expected_copper_layers
    if args.expected_board_size_mm:
        options["expected_size_mm"] = tuple(args.expected_board_size_mm)
    if args.expected_board_thickness_mm is not None:
        options["expected_thickness_mm"] = args.expected_board_thickness_mm
    if args.expected_minimum_drill_mm is not None:
        options["expected_min_drill_mm"] = args.expected_minimum_drill_mm
    if args.assembly_side:
        options["assembly_sides"] = args.assembly_side
    if args.dnp_designator:
        options["dnp"] = set(args.dnp_designator)
    if args.excluded_designator:
        options["excluded"] = set(args.excluded_designator)
    if args.expected_fitted_designator:
        options["expected_fitted"] = set(args.expected_fitted_designator)
    options["bom"] = args.bom
    options["cpl"] = args.cpl

    try:
        report = audit_source(args.package, options, args.strict)
    except (ValueError, FileNotFoundError, zipfile.BadZipFile) as exc:
        print(f"fab_audit: BLOCKED — {exc}", file=sys.stderr)
        return 2

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for item in report["findings"]:
        if item["level"] == "info":
            continue
        files = f" [{', '.join(item['files'][:6])}]" if item["files"] else ""
        print(f"[{item['level']}] {item['code']}: {item['message']}{files}")
    print(
        f"fab_audit: {report['status']} "
        f"({report['blocking']} blocking, {report['warnings']} warnings, "
        f"{report['counts']['files']} files, {report['counts']['copper']} copper layers)"
    )
    return 1 if report["blocking"] else 0


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

GOOD_DRILL = """M48
METRIC,TZ
T1C0.300
T2C1.000
%
T1
X10.0Y10.0
T2
X20.0Y20.0
M30
"""

SMALL_DRILL = GOOD_DRILL.replace("T1C0.300", "T1C0.150")


def _write_package(root: Path, *, layers: int = 2, paste: bool = False,
                   size=(50.0, 30.0), thickness: float = 1.6,
                   drill_text: str = GOOD_DRILL) -> None:
    root.mkdir(parents=True, exist_ok=True)
    names = ["F_Cu"] + [f"In{i}_Cu" for i in range(1, layers - 1)] + ["B_Cu"]
    for name in names[:layers]:
        (root / f"demo-{name}.gbr").write_text(f"G04 {name}*\nM02*\n", encoding="utf-8")
    for name in ("F_Mask", "B_Mask", "F_Silkscreen", "B_Silkscreen"):
        (root / f"demo-{name}.gbr").write_text("G04 layer*\nM02*\n", encoding="utf-8")
    (root / "demo-Edge_Cuts.gbr").write_text("G04 outline*\nM02*\n", encoding="utf-8")
    (root / "demo-PTH.drl").write_text(drill_text, encoding="utf-8")
    if paste:
        for name in ("F_Paste", "B_Paste"):
            (root / f"demo-{name}.gbr").write_text("G04 paste*\nM02*\n", encoding="utf-8")
    (root / "demo-job.gbrjob").write_text(
        json.dumps(
            {
                "GeneralSpecs": {
                    "Size": {"X": size[0], "Y": size[1]},
                    "LayerNumber": layers,
                    "BoardThickness": thickness,
                }
            }
        ),
        encoding="utf-8",
    )


def _base_options(**overrides) -> dict:
    options = {
        "route": "pcb-only",
        "expected_copper_layers": 2,
        "expected_size_mm": (50.0, 30.0),
        "expected_thickness_mm": 1.6,
        "expected_min_drill_mm": 0.3,
        "assembly_sides": [],
        "dnp": set(),
        "excluded": set(),
        "expected_fitted": None,
        "bom": None,
        "cpl": None,
    }
    options.update(overrides)
    return options


def _codes(report: dict) -> set[str]:
    return {i["code"] for i in report["findings"] if i["level"] == "blocking"}


def self_test() -> int:
    checks: list[tuple[str, bool]] = []

    def expect(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    # classification is a fact about names; assert it explicitly
    expect("F_Cu is copper", classify("demo-F_Cu.gbr") == "copper")
    expect("In1_Cu is copper", classify("demo-In1_Cu.gbr") == "copper")
    expect("GTL is copper", classify("demo.GTL") == "copper")
    expect("G2L is copper", classify("demo.G2L") == "copper")
    expect("Edge_Cuts is outline", classify("demo-Edge_Cuts.gbr") == "outline")
    expect("GKO is outline", classify("demo.GKO") == "outline")
    expect("F_Courtyard is non-manufacturing", classify("demo-F_Courtyard.gbr") == "non_manufacturing")
    expect("F_Fab is non-manufacturing", classify("demo-F_Fab.gbr") == "non_manufacturing")
    expect("User_Drawings is non-manufacturing", classify("demo-User_Drawings.gbr") == "non_manufacturing")
    expect("a project named fabrikam is not a Fab layer",
           classify("fabrikam-F_Cu.gbr") == "copper")
    expect("XLN is drill", classify("demo.XLN") == "drill")
    expect("txt sniffed as Excellon is drill", classify("demo.txt", b"M48\nMETRIC") == "drill")
    expect("plain txt is a document", classify("readme.txt", b"hello") == "document")
    expect("drill map is its own category", classify("demo-drl_map.pdf") == "drill_map")

    expect("inch drill converts to mm",
           parse_excellon("M48\nINCH,TZ\nT1C0.0118\n")["diameters_mm"] == [0.2997])
    expect("metric drill parses", parse_excellon(GOOD_DRILL)["diameters_mm"] == [0.3, 1.0])

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        good = base / "good"
        _write_package(good)
        report = audit(good, strict=True, **_base_options())
        expect("clean pcb-only package passes strict", report["status"] == "PASS")
        expect("copper layers counted", report["counts"]["copper"] == 2)

        four = base / "four"
        _write_package(four, layers=4, size=(38.0, 90.0))
        report = audit(four, strict=True, **_base_options(expected_copper_layers=4,
                                                          expected_size_mm=(38.0, 90.0)))
        expect("clean 4-layer package passes", report["status"] == "PASS")
        report = audit(four, strict=True, **_base_options(expected_copper_layers=2))
        expect("wrong layer count blocks", "copper_layer_count" in _codes(report))

        stray = base / "stray"
        _write_package(stray)
        (stray / "demo-F_Courtyard.gbr").write_text("G04*\nM02*\n", encoding="utf-8")
        report = audit(stray, strict=True, **_base_options())
        expect("non-manufacturing layer blocks in strict",
               "non_manufacturing_layer" in _codes(report))
        report = audit(stray, strict=False, **_base_options())
        expect("non-manufacturing layer only warns without strict",
               report["status"] == "PASS" and report["warnings"] >= 1)

        unknown = base / "unknown"
        _write_package(unknown)
        (unknown / "mystery.xyz").write_text("?", encoding="utf-8")
        expect("unknown file blocks in strict",
               "unknown_file" in _codes(audit(unknown, strict=True, **_base_options())))

        sized = base / "sized"
        _write_package(sized, size=(31.1, 88.1))
        expect("gbrjob size disagreement blocks",
               "job_size_mismatch" in _codes(audit(sized, strict=True, **_base_options())))

        thick = base / "thick"
        _write_package(thick, thickness=1.0)
        expect("gbrjob thickness disagreement blocks",
               "job_thickness_mismatch" in _codes(audit(thick, strict=True, **_base_options())))

        tiny = base / "tiny"
        _write_package(tiny, drill_text=SMALL_DRILL)
        expect("drill below the declared minimum blocks",
               "drill_below_minimum" in _codes(audit(tiny, strict=True, **_base_options())))

        twoout = base / "twoout"
        _write_package(twoout)
        (twoout / "demo-Outline2.gbr").write_text("G04*\nM02*\n", encoding="utf-8")
        expect("two outlines block",
               "multiple_outlines" in _codes(audit(twoout, strict=True, **_base_options())))

        nodrill = base / "nodrill"
        _write_package(nodrill)
        (nodrill / "demo-PTH.drl").rename(nodrill / "removed.bin")
        expect("missing drill blocks",
               "no_drill" in _codes(audit(nodrill, strict=False, **_base_options())))

        pastebare = base / "pastebare"
        _write_package(pastebare, paste=True)
        expect("paste in a bare-board package blocks",
               "paste_in_bare_board_package" in _codes(audit(pastebare, strict=True, **_base_options())))

        empty = base / "empty"
        _write_package(empty)
        (empty / "demo-B_Mask.gbr").write_text("", encoding="utf-8")
        expect("zero-byte file blocks",
               "empty_file" in _codes(audit(empty, strict=True, **_base_options())))

        # --- PCBA ----------------------------------------------------------
        pcba = base / "pcba"
        _write_package(pcba, paste=True)
        bom = base / "bom.csv"
        bom.write_text(
            "Designator,Value,Footprint,Manufacturer,MPN\n"
            '"R1,R2",10k,0402,Yageo,RC0402FR-0710KL\n'
            "C1,100n,0402,Murata,GRM155R71C104KA88D\n"
            "J1,USB-C,USB-C-16P,GCT,USB4105-GF-A\n",
            encoding="utf-8",
        )
        cpl = base / "cpl.csv"
        cpl.write_text(
            "Designator,Mid X,Mid Y,Layer,Rotation\n"
            "R1,10.0,10.0,Top,0\n"
            "R2,12.0,10.0,Top,90\n"
            "C1,14.0,10.0,Top,0\n"
            "J1,20.0,5.0,Top,270\n",
            encoding="utf-8",
        )
        pcba_options = _base_options(route="pcba", assembly_sides=["Top"], bom=bom, cpl=cpl)
        report = audit(pcba, strict=True, **pcba_options)
        expect("clean pcba package passes", report["status"] == "PASS")
        expect("fitted set is reported", report["assembly"]["fitted"] == ["C1", "J1", "R1", "R2"])

        cpl_missing = base / "cpl_missing.csv"
        cpl_missing.write_text(
            "Designator,Mid X,Mid Y,Layer,Rotation\n"
            "R1,10.0,10.0,Top,0\n"
            "C1,14.0,10.0,Top,0\n"
            "J1,20.0,5.0,Top,270\n",
            encoding="utf-8",
        )
        expect("fitted part missing from CPL blocks",
               "fitted_missing_from_cpl" in _codes(
                   audit(pcba, strict=True, **_base_options(
                       route="pcba", assembly_sides=["Top"], bom=bom, cpl=cpl_missing))))

        expect("DNP leaking into CPL blocks",
               "dnp_in_cpl" in _codes(
                   audit(pcba, strict=True, **_base_options(
                       route="pcba", assembly_sides=["Top"], bom=bom, cpl=cpl, dnp={"C1"}))))

        cpl_side = base / "cpl_side.csv"
        cpl_side.write_text(
            "Designator,Mid X,Mid Y,Layer,Rotation\n"
            "R1,10.0,10.0,Bottom,0\n"
            "R2,12.0,10.0,Top,90\n"
            "C1,14.0,10.0,Top,0\n"
            "J1,20.0,5.0,Top,270\n",
            encoding="utf-8",
        )
        expect("unexpected assembly side blocks",
               "cpl_unexpected_side" in _codes(
                   audit(pcba, strict=True, **_base_options(
                       route="pcba", assembly_sides=["Top"], bom=bom, cpl=cpl_side))))

        cpl_rot = base / "cpl_rot.csv"
        cpl_rot.write_text(
            "Designator,Mid X,Mid Y,Layer,Rotation\n"
            "R1,10.0,10.0,Top,zero\n"
            "R2,12.0,10.0,Top,90\n"
            "C1,14.0,10.0,Top,0\n"
            "J1,20.0,5.0,Top,270\n",
            encoding="utf-8",
        )
        expect("non-numeric rotation blocks",
               "cpl_bad_rotation" in _codes(
                   audit(pcba, strict=True, **_base_options(
                       route="pcba", assembly_sides=["Top"], bom=bom, cpl=cpl_rot))))

        expect("expected fitted set mismatch blocks",
               "fitted_set_mismatch" in _codes(
                   audit(pcba, strict=True, **_base_options(
                       route="pcba", assembly_sides=["Top"], bom=bom, cpl=cpl,
                       expected_fitted={"R1", "R2", "C1"}))))

        bom_nompn = base / "bom_nompn.csv"
        bom_nompn.write_text(
            "Designator,Value,Footprint\n"
            '"R1,R2",10k,0402\n'
            "C1,100n,0402\n"
            "J1,USB-C,USB-C-16P\n",
            encoding="utf-8",
        )
        report = audit(pcba, strict=True, **_base_options(
            route="pcba", assembly_sides=["Top"], bom=bom_nompn, cpl=cpl))
        expect("missing MPN warns",
               any(i["code"] == "bom_missing_mpn" for i in report["findings"]))

        # --- ZIP handling ---------------------------------------------------
        zpath = base / "good.zip"
        with zipfile.ZipFile(zpath, "w") as archive:
            for item in sorted(good.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(good).as_posix())
        report = audit_source(zpath, _base_options(), True)
        expect("zip package audits the same as the directory", report["status"] == "PASS")

        evil = base / "evil.zip"
        with zipfile.ZipFile(evil, "w") as archive:
            archive.writestr("../escape.txt", "nope")
            archive.writestr("demo-F_Cu.gbr", "G04*\nM02*\n")
        report = audit_source(evil, _base_options(), True)
        expect("archive path traversal is refused and reported",
               "archive_unsafe" in _codes(report))

        notzip = base / "notzip.zip"
        notzip.write_text("this is not a zip", encoding="utf-8")
        raised = False
        try:
            audit_source(notzip, _base_options(), True)
        except (zipfile.BadZipFile, ValueError):
            raised = True
        expect("a corrupt archive raises rather than passing", raised)

        raised = False
        try:
            audit_source(base / "does_not_exist", _base_options(), True)
        except FileNotFoundError:
            raised = True
        expect("a missing package raises", raised)

    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print(f"FAIL: {name}", file=sys.stderr)
    print(f"fab_audit self-test: {'PASS' if not failed else 'FAIL'} "
          f"({len(checks) - len(failed)}/{len(checks)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

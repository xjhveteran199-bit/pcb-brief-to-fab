#!/usr/bin/env python3
"""Validate a pcb-brief-to-fab constraint manifest.

Fails closed: an unparsable manifest, a missing section, or a contradiction is a
blocking finding, never a silent default.

    python manifest_check.py <manifest.json> --stage design
    python manifest_check.py <manifest.json> --stage release --json-out out.json
    python manifest_check.py --self-test

Exit codes: 0 = no blocking findings, 1 = blocking findings, 2 = usage/parse error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Single source of truth for the tier rubric. If it is missing, fail closed
# rather than skipping the consistency check.
from feasibility import (  # noqa: E402
    ESCALATORS as FEASIBILITY_ESCALATORS,
    HARD_GATES as FEASIBILITY_HARD_GATES,
    TIERS as FEASIBILITY_TIERS,
    answers_from_manifest,
    assess,
)

ENTRIES = {"NEW_DESIGN", "EXISTING_SCHEMATIC", "EXISTING_BOARD", "RELEASE_AUDIT"}
ROUTES = {"pcb-only", "pcba"}
STATES = {
    "DRAFT",
    "AUTHORED_NOT_VERIFIED",
    "TOOL_VERIFIED",
    "ENGINEERING_HANDOFF",
    "RELEASE_CANDIDATE",
    "ORDER_READY",
    "BLOCKED",
}
TIERS = {"LOW", "MODERATE", "HIGH"}
HAZARDS = (
    "human_contact",
    "battery_charging",
    "mains_voltage",
    "high_energy",
    "safety_function",
    "controlled_impedance",
    "hdi_or_bga",
)
VERIFIABLE_TECHNOLOGY = "rigid_fr4"
PLACEHOLDERS = {"", "REPLACE_ME", "TBD", "TODO", "N/A", "?", "UNKNOWN"}

# ISO-8601 date or datetime that carries an explicit timezone offset or Z.
TZ_DATE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})$"
)


class Findings:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, level: str, code: str, message: str) -> None:
        self.items.append({"level": level, "code": code, "message": message})

    def block(self, code: str, message: str) -> None:
        self.add("blocking", code, message)

    def warn(self, code: str, message: str) -> None:
        self.add("warning", code, message)

    @property
    def blocking(self) -> list[dict[str, str]]:
        return [i for i in self.items if i["level"] == "blocking"]

    @property
    def warnings(self) -> list[dict[str, str]]:
        return [i for i in self.items if i["level"] == "warning"]


def _get(node: Any, path: str) -> Any:
    cur = node
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_placeholder(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().upper() in PLACEHOLDERS)


def _positive_number(f: Findings, node: Any, path: str, required: bool = True) -> None:
    value = _get(node, path)
    if value is None:
        if required:
            f.block("missing_field", f"{path} is missing")
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        f.block("bad_type", f"{path} must be a number, got {value!r}")
        return
    if value <= 0:
        f.block("bad_value", f"{path} must be > 0, got {value}")


def _approval_complete(f: Findings, m: Any, key: str, label: str) -> bool:
    rec = _get(m, f"approvals.{key}")
    if not isinstance(rec, dict):
        f.block("approval_missing", f"approvals.{key} is missing ({label})")
        return False
    ok = True
    if rec.get("reviewer_is_human") is not True:
        f.block("approval_not_human", f"approvals.{key}.reviewer_is_human must be true ({label})")
        ok = False
    for field in ("name", "role", "evidence"):
        if _is_placeholder(rec.get(field)):
            f.block("approval_incomplete", f"approvals.{key}.{field} is empty ({label})")
            ok = False
    date = rec.get("date")
    if _is_placeholder(date) or not TZ_DATE.match(str(date)):
        f.block(
            "approval_date",
            f"approvals.{key}.date must be ISO-8601 with a timezone offset, got {date!r}",
        )
        ok = False
    return ok


def validate(manifest: Any, stage: str) -> Findings:
    f = Findings()
    if not isinstance(manifest, dict):
        f.block("not_an_object", "manifest root must be a JSON object")
        return f

    for section in ("project", "board", "dfm", "risk", "feasibility", "approvals", "gates"):
        if not isinstance(manifest.get(section), dict):
            f.block("missing_section", f"section {section!r} is missing or not an object")
    if f.blocking:
        return f

    # ---- project -----------------------------------------------------------
    entry = _get(manifest, "project.entry")
    if entry not in ENTRIES:
        f.block("bad_entry", f"project.entry must be one of {sorted(ENTRIES)}, got {entry!r}")
    route = _get(manifest, "project.route")
    if route not in ROUTES:
        f.block("bad_route", f"project.route must be one of {sorted(ROUTES)}, got {route!r}")
    state = _get(manifest, "project.state")
    if state not in STATES:
        f.block("bad_state", f"project.state must be one of {sorted(STATES)}, got {state!r}")
    for field in ("name", "revision"):
        if _is_placeholder(_get(manifest, f"project.{field}")):
            f.block("placeholder", f"project.{field} still holds a placeholder")

    # ---- board -------------------------------------------------------------
    layers = _get(manifest, "board.copper_layers")
    names = _get(manifest, "board.copper_layer_names")
    roles = _get(manifest, "board.stackup_role")
    if not isinstance(layers, int) or isinstance(layers, bool) or layers < 1:
        f.block("bad_layers", f"board.copper_layers must be a positive integer, got {layers!r}")
    else:
        if not isinstance(names, list) or len(names) != layers:
            f.block(
                "layer_names_mismatch",
                f"board.copper_layer_names must list {layers} names, got "
                f"{len(names) if isinstance(names, list) else names!r}",
            )
        if not isinstance(roles, list) or len(roles) != layers:
            f.block(
                "stackup_role_mismatch",
                f"board.stackup_role must list {layers} roles, got "
                f"{len(roles) if isinstance(roles, list) else roles!r}",
            )
    if isinstance(names, list) and len(set(map(str, names))) != len(names):
        f.block("layer_names_duplicate", "board.copper_layer_names contains duplicates")

    area = _get(manifest, "board.placement_area_mm")
    margin = _get(manifest, "board.edge_margin_mm")
    outline = _get(manifest, "board.physical_outline_mm")
    geom_ok = True
    for label, value in (("placement_area_mm", area), ("physical_outline_mm", outline)):
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in value)
        ):
            f.block("bad_geometry", f"board.{label} must be [width, height] positive numbers")
            geom_ok = False
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or margin < 0:
        f.block("bad_geometry", "board.edge_margin_mm must be a number >= 0")
        geom_ok = False
    if geom_ok:
        derived = [round(area[0] + 2 * margin, 6), round(area[1] + 2 * margin, 6)]
        actual = [round(float(outline[0]), 6), round(float(outline[1]), 6)]
        if derived != actual:
            f.block(
                "outline_not_derived",
                f"board.physical_outline_mm {actual} != placement_area_mm + 2*edge_margin_mm "
                f"{derived}. One controlling number only: fix the document, not the check.",
            )

    _positive_number(f, manifest, "board.thickness_mm")
    _positive_number(f, manifest, "board.outer_copper_oz")
    if _get(manifest, "board.product_outline_separate_from_panel") is not True:
        f.warn(
            "panel_merged",
            "board.product_outline_separate_from_panel is not true; a panel rail merged into "
            "the product outline permanently corrupts the board size",
        )

    # ---- dfm ---------------------------------------------------------------
    for field in (
        "min_track_mm",
        "min_clearance_mm",
        "min_drill_mm",
        "via_drill_mm",
        "via_pad_mm",
        "copper_to_edge_mm",
    ):
        _positive_number(f, manifest, f"dfm.{field}")
    min_drill = _get(manifest, "dfm.min_drill_mm")
    via_drill = _get(manifest, "dfm.via_drill_mm")
    via_pad = _get(manifest, "dfm.via_pad_mm")
    if isinstance(min_drill, (int, float)) and isinstance(via_drill, (int, float)):
        if via_drill < min_drill:
            f.block(
                "via_below_min_drill",
                f"dfm.via_drill_mm {via_drill} is smaller than dfm.min_drill_mm {min_drill}",
            )
    if isinstance(via_pad, (int, float)) and isinstance(via_drill, (int, float)):
        if via_pad <= via_drill:
            f.block(
                "via_pad_not_larger",
                f"dfm.via_pad_mm {via_pad} must exceed dfm.via_drill_mm {via_drill}",
            )

    # ---- risk --------------------------------------------------------------
    tier = _get(manifest, "risk.tier")
    if tier not in TIERS:
        f.block("bad_risk_tier", f"risk.tier must be one of {sorted(TIERS)}, got {tier!r}")
    if _is_placeholder(_get(manifest, "risk.reason")):
        f.block("risk_reason", "risk.reason must state why this tier was chosen")
    tripped = [h for h in HAZARDS if _get(manifest, f"risk.{h}") is True]
    missing_flags = [h for h in HAZARDS if not isinstance(_get(manifest, f"risk.{h}"), bool)]
    if missing_flags:
        f.block(
            "risk_flag_missing",
            "these risk flags must be set explicitly to true or false: " + ", ".join(missing_flags),
        )
    if tripped and tier != "HIGH":
        f.block(
            "risk_tier_understated",
            f"risk.tier is {tier!r} but these hazards are declared: {', '.join(tripped)}. "
            "Any of them forces HIGH.",
        )

    # ---- feasibility tier --------------------------------------------------
    tier_value = _get(manifest, "feasibility.tier")
    if tier_value not in FEASIBILITY_TIERS:
        f.block(
            "bad_feasibility_tier",
            f"feasibility.tier must be one of {list(FEASIBILITY_TIERS)}, got {tier_value!r}. "
            "Run scripts/feasibility.py before filling this in.",
        )
    if _is_placeholder(_get(manifest, "feasibility.reason")):
        f.block(
            "feasibility_reason",
            "feasibility.reason must name the specific fact that drove the tier, in plain "
            "language. 'high risk' is not a reason.",
        )
    factors = _get(manifest, "feasibility.factors")
    if not isinstance(factors, dict):
        f.block("bad_feasibility_factors", "feasibility.factors must be an object")
        factors = {}
    else:
        known = set(FEASIBILITY_HARD_GATES) | set(FEASIBILITY_ESCALATORS) | {
            "peak_current_a", "component_count_estimate"
        }
        unknown_factors = sorted(set(factors) - known)
        if unknown_factors:
            f.warn(
                "unknown_feasibility_factor",
                "these feasibility.factors are not part of the rubric and are ignored: "
                + ", ".join(unknown_factors),
            )
    if tier_value in FEASIBILITY_TIERS:
        try:
            computed = assess(answers_from_manifest(manifest))
        except ValueError as exc:
            f.block("feasibility_unassessable", f"feasibility factors are not usable: {exc}")
        else:
            if computed["tier"] != tier_value:
                drivers = computed["hard_gates"] + computed["escalators"]
                f.block(
                    "feasibility_tier_disagrees",
                    f"feasibility.tier is {tier_value!r} but the facts declared in this manifest "
                    f"give {computed['tier']!r}"
                    + (" because " + "; ".join(drivers) if drivers else "")
                    + ". Fix whichever one is wrong; never leave them disagreeing.",
                )
    if tier == "HIGH" and tier_value != "HUMAN_LED":
        f.block(
            "high_risk_needs_human_led",
            f"risk.tier is HIGH but feasibility.tier is {tier_value!r}. A HIGH-risk board is "
            "HUMAN_LED: an engineer owns the topology and the critical placement.",
        )

    # ---- unknowns / waivers ------------------------------------------------
    unknowns = manifest.get("unknowns", [])
    if not isinstance(unknowns, list):
        f.block("bad_unknowns", "unknowns must be a list")
        unknowns = []
    open_unknowns = [u for u in unknowns if isinstance(u, dict) and not _is_placeholder(u.get("item"))]
    for waiver in manifest.get("waivers", []) or []:
        if not isinstance(waiver, dict):
            f.block("bad_waiver", "each waiver must be an object")
            continue
        for field in ("waives", "does_not_waive", "authority", "date", "consequence"):
            if _is_placeholder(waiver.get(field)):
                f.block("waiver_incomplete", f"waiver is missing {field!r}")

    # ---- stage-specific ----------------------------------------------------
    if stage == "design":
        if open_unknowns:
            f.warn(
                "open_unknowns",
                f"{len(open_unknowns)} unknown(s) still open; they must be closed before release",
            )
        if tier == "HIGH" or tier_value in {"AGENT_LED", "HUMAN_LED"}:
            rec = _get(manifest, "approvals.topology_review") or {}
            if rec.get("reviewer_is_human") is not True:
                f.warn(
                    "topology_review_pending",
                    f"feasibility tier {tier_value!r}: a named human topology review is required "
                    "before the schematic freezes",
                )
    elif stage == "release":
        if state in {"DRAFT", "ENGINEERING_HANDOFF", "BLOCKED"}:
            f.block("state_not_releasable", f"project.state {state!r} cannot start a release")
        if open_unknowns:
            f.block(
                "unknowns_open_at_release",
                "unresolved unknowns: " + "; ".join(str(u.get("item")) for u in open_unknowns),
            )
        if _is_placeholder(_get(manifest, "board.manufacturer")):
            f.block("manufacturer_unknown", "board.manufacturer must be set before release")
        if _is_placeholder(_get(manifest, "dfm.source")) or _is_placeholder(_get(manifest, "dfm.checked_on")):
            f.block(
                "dfm_unverified",
                "dfm.source and dfm.checked_on must record where and when the capability "
                "limits were read; remembered numbers expire",
            )
        if _is_placeholder(_get(manifest, "project.approved_netlist_sha256")):
            f.block("no_baseline", "project.approved_netlist_sha256 must be set before release")
        tech = _get(manifest, "board.technology")
        if tech != VERIFIABLE_TECHNOLOGY:
            f.block(
                "technology_not_generically_verifiable",
                f"board.technology {tech!r}: a generic release path only covers "
                f"{VERIFIABLE_TECHNOLOGY!r}. Continue designing, but label the output "
                "ENGINEERING_HANDOFF and use a specialist review.",
            )
        procs = manifest.get("special_processes") or []
        if procs:
            f.block(
                "special_process_unverifiable",
                "special_processes is non-empty (" + ", ".join(map(str, procs)) + "); the required "
                "extra artifacts cannot be verified generically. Label ENGINEERING_HANDOFF.",
            )
        if _get(manifest, "panel.required") is True:
            f.block(
                "panel_unverifiable",
                "panel.required is true; panel/rail geometry needs a manufacturer-specific "
                "review that this path cannot perform",
            )
        if tier == "HIGH" or tier_value in {"AGENT_LED", "HUMAN_LED"}:
            _approval_complete(
                f, manifest, "topology_review",
                f"risk tier {tier}, feasibility tier {tier_value}",
            )
        if tier_value == "HUMAN_LED" and state in {"RELEASE_CANDIDATE", "ORDER_READY"}:
            f.block(
                "human_led_cannot_self_release",
                "feasibility.tier is HUMAN_LED: a package the agent produced alone is "
                "ENGINEERING_HANDOFF. Only the responsible engineer moves it past that.",
            )
        if route == "pcba":
            sides = _get(manifest, "assembly.sides")
            if not isinstance(sides, list) or not sides:
                f.block("no_assembly_side", "route pcba requires assembly.sides to be non-empty")
            elif any(s not in {"Top", "Bottom"} for s in sides):
                f.block("bad_assembly_side", "assembly.sides entries must be 'Top' or 'Bottom'")
            if _get(manifest, "assembly.cpl_units") not in {"mm", "in"}:
                f.block("bad_cpl_units", "assembly.cpl_units must be 'mm' or 'in'")
            if _is_placeholder(_get(manifest, "assembly.cpl_origin")):
                f.block("no_cpl_origin", "assembly.cpl_origin must describe where coordinates start")
        for field in ("allow_drc_violations", "allow_unconnected", "allow_schematic_parity_issues"):
            value = _get(manifest, f"gates.{field}")
            if value != 0:
                f.block(
                    "gate_relaxed",
                    f"gates.{field} is {value!r}; the final routing gate requires 0. Raising it "
                    "is a recorded decision with a named reviewer, not a manifest edit.",
                )
    else:
        f.block("bad_stage", f"unknown stage {stage!r}")

    return f


def run(path: Path, stage: str, json_out: Path | None) -> int:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"manifest not found: {path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"manifest is not valid JSON: {exc}", file=sys.stderr)
        return 2

    findings = validate(manifest, stage)
    status = "BLOCKED" if findings.blocking else "PASS"
    report = {
        "tool": "manifest_check",
        "manifest": str(path),
        "stage": stage,
        "status": status,
        "blocking": len(findings.blocking),
        "warnings": len(findings.warnings),
        "findings": findings.items,
    }
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for item in findings.items:
        print(f"[{item['level']}] {item['code']}: {item['message']}")
    print(f"manifest_check {stage}: {status} "
          f"({len(findings.blocking)} blocking, {len(findings.warnings)} warnings)")
    return 1 if findings.blocking else 0


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

def _good_manifest() -> dict:
    return {
        "schema_version": 1,
        "project": {
            "name": "demo",
            "revision": "RevA",
            "entry": "NEW_DESIGN",
            "route": "pcb-only",
            "state": "TOOL_VERIFIED",
            "approved_netlist_baseline": "baseline.xml",
            "approved_netlist_sha256": "0" * 64,
            "additional_source_files": [],
        },
        "board": {
            "manufacturer": "ExampleFab",
            "technology": "rigid_fr4",
            "copper_layers": 2,
            "copper_layer_names": ["F.Cu", "B.Cu"],
            "stackup_role": ["signal", "ground_and_signal"],
            "placement_area_mm": [48.0, 28.0],
            "edge_margin_mm": 1.0,
            "physical_outline_mm": [50.0, 30.0],
            "thickness_mm": 1.6,
            "outer_copper_oz": 1,
            "inner_copper_oz": None,
            "surface_finish": "HASL",
            "soldermask_color": "green",
            "silkscreen_color": "white",
            "product_outline_separate_from_panel": True,
        },
        "dfm": {
            "source": "https://example.com/capabilities",
            "checked_on": "2026-08-02",
            "min_track_mm": 0.15,
            "min_clearance_mm": 0.15,
            "min_drill_mm": 0.3,
            "via_drill_mm": 0.3,
            "via_pad_mm": 0.6,
            "copper_to_edge_mm": 0.5,
        },
        "assembly": {
            "quantity": 5,
            "sides": [],
            "dnp_designators": [],
            "excluded_designators": [],
            "cpl_units": "mm",
            "cpl_origin": "",
        },
        "special_processes": [],
        "panel": {"required": False, "notes": ""},
        "risk": {
            "tier": "LOW",
            "reason": "USB powered bench board, no human contact",
            "human_contact": False,
            "battery_charging": False,
            "mains_voltage": False,
            "high_energy": False,
            "safety_function": False,
            "controlled_impedance": False,
            "hdi_or_bga": False,
        },
        "feasibility": {
            "tier": "AGENT_AUTONOMOUS",
            "assessed_on": "2026-08-02",
            "reason": "USB powered, 2 layers, 0.4 A peak, no hazard or escalator declared",
            "factors": {
                "flex_or_rigid_flex": False,
                "rf_antenna_design": False,
                "high_speed_digital": False,
                "rf_module_precertified": False,
                "custom_switching_converter": False,
                "motor_or_inductive_load": False,
                "enclosure_fit_required": False,
                "nonstandard_parts": False,
                "harsh_environment": False,
                "respin_not_acceptable": False,
                "peak_current_a": 0.4,
                "component_count_estimate": 45,
            },
        },
        "approvals": {
            "topology_review": {
                "reviewer_is_human": False,
                "name": None,
                "role": None,
                "date": None,
                "evidence": None,
            },
            "package_release_review": {
                "reviewer_is_human": False,
                "name": None,
                "role": None,
                "date": None,
                "evidence": None,
                "package_sha256": None,
            },
        },
        "waivers": [],
        "unknowns": [],
        "gates": {
            "allow_drc_violations": 0,
            "allow_unconnected": 0,
            "allow_schematic_parity_issues": 0,
        },
    }


def _codes(manifest: dict, stage: str) -> set[str]:
    return {i["code"] for i in validate(manifest, stage).blocking}


def self_test() -> int:
    checks: list[tuple[str, bool]] = []

    def expect(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    m = _good_manifest()
    expect("clean manifest passes design stage", not validate(m, "design").blocking)
    expect("clean manifest passes release stage", not validate(m, "release").blocking)

    m = _good_manifest()
    m["board"]["physical_outline_mm"] = [50.0, 32.0]
    expect("outline not derived is caught", "outline_not_derived" in _codes(m, "design"))

    m = _good_manifest()
    m["board"]["copper_layers"] = 4
    expect("layer name count mismatch is caught", "layer_names_mismatch" in _codes(m, "design"))
    expect("stackup role count mismatch is caught", "stackup_role_mismatch" in _codes(m, "design"))

    m = _good_manifest()
    m["risk"]["battery_charging"] = True
    expect("hazard forces HIGH tier", "risk_tier_understated" in _codes(m, "design"))

    # ---- feasibility tier -------------------------------------------------
    m = _good_manifest()
    m["feasibility"]["tier"] = "AGENT_LED"
    expect("a tier that disagrees with the declared facts blocks",
           "feasibility_tier_disagrees" in _codes(m, "design"))

    m = _good_manifest()
    m["feasibility"]["factors"]["custom_switching_converter"] = True
    expect("an escalator that is not reflected in the tier blocks",
           "feasibility_tier_disagrees" in _codes(m, "design"))
    m["feasibility"]["tier"] = "AGENT_LED"
    expect("matching the escalator clears it", not _codes(m, "design"))
    expect("AGENT_LED warns that a topology review is pending",
           any(i["code"] == "topology_review_pending" for i in validate(m, "design").warnings))
    expect("AGENT_LED without a human review blocks release",
           "approval_not_human" in _codes(m, "release"))

    m = _good_manifest()
    m["board"]["copper_layers"] = 4
    m["board"]["copper_layer_names"] = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    m["board"]["stackup_role"] = ["signal", "ground", "power", "signal"]
    expect("4 layers escalate the tier", "feasibility_tier_disagrees" in _codes(m, "design"))

    m = _good_manifest()
    m["risk"]["tier"] = "HIGH"
    m["risk"]["mains_voltage"] = True
    m["feasibility"]["tier"] = "AGENT_LED"
    codes = _codes(m, "design")
    expect("HIGH risk cannot be AGENT_LED", "high_risk_needs_human_led" in codes)

    m = _good_manifest()
    m["risk"]["tier"] = "HIGH"
    m["risk"]["human_contact"] = True
    m["feasibility"]["tier"] = "HUMAN_LED"
    m["feasibility"]["reason"] = "skin contact"
    m["project"]["state"] = "RELEASE_CANDIDATE"
    expect("HUMAN_LED cannot self-release",
           "human_led_cannot_self_release" in _codes(m, "release"))

    m = _good_manifest()
    m["feasibility"]["tier"] = "MOSTLY_FINE"
    expect("an invented tier is rejected", "bad_feasibility_tier" in _codes(m, "design"))

    m = _good_manifest()
    m["feasibility"]["reason"] = ""
    expect("an empty tier reason blocks", "feasibility_reason" in _codes(m, "design"))

    m = _good_manifest()
    m["feasibility"]["factors"]["make_it_easy"] = True
    expect("an invented factor warns rather than being used",
           any(i["code"] == "unknown_feasibility_factor" for i in validate(m, "design").warnings))

    m = _good_manifest()
    del m["feasibility"]
    expect("a missing feasibility section is rejected",
           "missing_section" in _codes(m, "design"))

    m = _good_manifest()
    m["risk"]["tier"] = "HIGH"
    m["risk"]["human_contact"] = True
    m["feasibility"]["tier"] = "HUMAN_LED"
    m["feasibility"]["reason"] = "the board touches skin"
    expect("HIGH without human review blocks release",
           "approval_not_human" in _codes(m, "release"))
    m["approvals"]["topology_review"] = {
        "reviewer_is_human": True,
        "name": "A. Engineer",
        "role": "EE lead",
        "date": "2026-08-02",  # no timezone
        "evidence": "reviews/topology.md",
    }
    expect("approval date without timezone is rejected", "approval_date" in _codes(m, "release"))
    m["approvals"]["topology_review"]["date"] = "2026-08-02T10:00+08:00"
    expect("complete human approval clears the block", not _codes(m, "release"))

    m = _good_manifest()
    m["unknowns"] = [{"item": "connector orientation", "why": "", "owner": "", "interim": ""}]
    expect("open unknown warns at design",
           any(i["code"] == "open_unknowns" for i in validate(m, "design").warnings))
    expect("open unknown blocks at release", "unknowns_open_at_release" in _codes(m, "release"))

    m = _good_manifest()
    m["special_processes"] = ["controlled impedance"]
    expect("special process blocks release", "special_process_unverifiable" in _codes(m, "release"))

    m = _good_manifest()
    m["board"]["technology"] = "flex"
    expect("non FR-4 blocks release",
           "technology_not_generically_verifiable" in _codes(m, "release"))

    m = _good_manifest()
    m["panel"]["required"] = True
    expect("panel blocks release", "panel_unverifiable" in _codes(m, "release"))

    m = _good_manifest()
    m["project"]["route"] = "pcba"
    codes = _codes(m, "release")
    expect("pcba without side blocks", "no_assembly_side" in codes)
    expect("pcba without cpl origin blocks", "no_cpl_origin" in codes)

    m = _good_manifest()
    m["gates"]["allow_unconnected"] = 5
    expect("relaxed gate blocks release", "gate_relaxed" in _codes(m, "release"))

    m = _good_manifest()
    m["dfm"]["via_drill_mm"] = 0.2
    expect("via smaller than min drill is caught", "via_below_min_drill" in _codes(m, "design"))

    m = _good_manifest()
    m["dfm"]["via_pad_mm"] = 0.3
    expect("via pad not larger than drill is caught", "via_pad_not_larger" in _codes(m, "design"))

    m = _good_manifest()
    del m["risk"]["mains_voltage"]
    expect("missing risk flag is caught", "risk_flag_missing" in _codes(m, "design"))

    m = _good_manifest()
    m["project"]["state"] = "DRAFT"
    expect("DRAFT cannot start a release", "state_not_releasable" in _codes(m, "release"))

    m = _good_manifest()
    m["dfm"]["checked_on"] = None
    expect("unverified dfm blocks release", "dfm_unverified" in _codes(m, "release"))

    expect("non-object manifest is rejected", bool(validate([], "design").blocking))
    expect("missing section is rejected", bool(validate({"project": {}}, "design").blocking))

    # end-to-end file run
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "m.json"
        path.write_text(json.dumps(_good_manifest()), encoding="utf-8")
        expect("file run returns 0 for a clean manifest", run(path, "design", None) == 0)
        bad = Path(td) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        expect("unparsable manifest returns 2", run(bad, "design", None) == 2)

    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print(f"FAIL: {name}", file=sys.stderr)
    print(f"manifest_check self-test: {'PASS' if not failed else 'FAIL'} "
          f"({len(checks) - len(failed)}/{len(checks)})")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", nargs="?", type=Path)
    parser.add_argument("--stage", choices=["design", "release"], default="design")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.manifest is None:
        parser.error("manifest path is required unless --self-test is given")
    return run(args.manifest, args.stage, args.json_out)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assess how much of a PCB project an agent can do alone.

Answers one question, deterministically: where must a qualified human be in the
loop for THIS board?

    AGENT_AUTONOMOUS  agent goes brief -> RELEASE_CANDIDATE package;
                      the human inspects the Gerbers and places the order
    AGENT_LED         agent does the work; a person signs three checkpoints
    HUMAN_LED         an engineer owns topology and critical placement;
                      the agent assists and audits

The rubric and its reasoning live in references/07-feasibility-tiers.md.

    python feasibility.py answers.json --json-out tier.json
    python feasibility.py --manifest m.json            # check a recorded tier
    python feasibility.py --self-test

Exit codes: 0 = assessed (or recorded tier agrees), 1 = recorded tier disagrees
with the facts, 2 = usage/parse error.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

TIERS = ("AGENT_AUTONOMOUS", "AGENT_LED", "HUMAN_LED")
RANK = {name: index for index, name in enumerate(TIERS)}

# Hazards that force HUMAN_LED on their own. The first seven share their names
# with the manifest `risk` block, so the two records cannot drift apart.
HARD_GATES: dict[str, str] = {
    "human_contact": "the board touches a human or animal body",
    "battery_charging": "the board charges a battery",
    "mains_voltage": "the board connects to mains voltage",
    "high_energy": "the board stores or switches enough energy to be a fire risk",
    "safety_function": "the board performs a medical, vehicle, flight or industrial safety function",
    "controlled_impedance": "the design needs controlled impedance",
    "hdi_or_bga": "the design uses HDI, blind/buried vias or fine-pitch BGA",
    "flex_or_rigid_flex": "the board is flex or rigid-flex",
    "rf_antenna_design": "the design includes an antenna rather than a pre-certified module",
    "high_speed_digital": "the design carries high-speed digital beyond USB 2.0 full speed",
}

ESCALATORS: dict[str, str] = {
    "rf_module_precertified": "a pre-certified radio module must be oriented so its antenna and "
                              "keepout reach the board edge",
    "custom_switching_converter": "a switching converter is being designed rather than copied, so "
                                  "its sub-layout must be drawn by hand",
    "motor_or_inductive_load": "a motor, relay or solenoid brings inrush, flyback and ground bounce",
    "enclosure_fit_required": "the board must fit existing mechanics, so connector mating "
                              "directions are measured rather than asserted",
    "nonstandard_parts": "at least one part has no verified library footprint",
    "harsh_environment": "the board runs outdoors or in moisture, chemicals or vibration",
    "respin_not_acceptable": "a respin is not acceptable, so the design cannot be wrong once",
}

# Numeric thresholds, all documented in references/07-feasibility-tiers.md.
LAYERS_HUMAN_LED = 6
LAYERS_AGENT_LED = 4
CURRENT_HUMAN_LED_A = 10.0
CURRENT_AGENT_LED_A = 3.0
COMPONENTS_AGENT_LED = 150

HUMAN_WORK = {
    "AGENT_AUTONOMOUS": [
        "open the Gerber/drill package in a viewer or the manufacturer's upload preview and "
        "inspect it",
        "place the order, and approve the exact package SHA-256 to reach ORDER_READY",
    ],
    "AGENT_LED": [
        "review and sign the topology before the schematic freezes",
        "review and sign the placement before it is locked (mechanical anchors, connector "
        "mating directions, converter sub-layouts, antenna keepout)",
        "review and sign the fabrication package against the manifest before ordering",
    ],
    "HUMAN_LED": [
        "own the topology: power tree, part selection, protection, fault behaviour",
        "own the critical placement and the critical routing constraints",
        "decide every trade-off the hard gate implies (isolation, charging, impedance, "
        "certification)",
        "approve any package before it is called anything other than ENGINEERING_HANDOFF",
    ],
}

AGENT_WORK = {
    "AGENT_AUTONOMOUS": "the whole workflow: intake, manifest, architecture, schematic, "
                        "placement, routing, gates, package, audit",
    "AGENT_LED": "the whole workflow, stopping at each checkpoint until the reviewer has signed",
    "HUMAN_LED": "requirement capture, manifest, datasheet verification, deterministic "
                 "generation, ERC/DRC/netlist parity, package audit, decision log and handoff",
}


def _flag(answers: dict, key: str) -> bool:
    return answers.get(key) is True


def _number(answers: dict, key: str, default: float | None = None) -> float | None:
    value = answers.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number, got {value!r}")
    return float(value)


def assess(answers: dict) -> dict:
    """Return the tier plus every driver that produced it."""
    if not isinstance(answers, dict):
        raise ValueError("answers must be a JSON object")

    # Keys beginning with "_" are comments by convention and are ignored silently.
    unknown = sorted(
        k for k in answers
        if not k.startswith("_")
        and k not in HARD_GATES
        and k not in ESCALATORS
        and k not in {"copper_layers", "peak_current_a", "component_count_estimate", "route",
                      "notes"}
    )

    hard: list[str] = []
    soft: list[str] = []

    for key, why in HARD_GATES.items():
        if _flag(answers, key):
            hard.append(f"{key}: {why}")
    for key, why in ESCALATORS.items():
        if _flag(answers, key):
            soft.append(f"{key}: {why}")

    layers = _number(answers, "copper_layers")
    if layers is not None:
        if layers >= LAYERS_HUMAN_LED:
            hard.append(f"copper_layers={layers:g}: {LAYERS_HUMAN_LED}+ layers make stack-up and "
                        "impedance planning part of the design")
        elif layers >= LAYERS_AGENT_LED:
            soft.append(f"copper_layers={layers:g}: stack-up and return-path choices start to matter")

    current = _number(answers, "peak_current_a")
    if current is not None:
        if current >= CURRENT_HUMAN_LED_A:
            hard.append(f"peak_current_a={current:g}: copper, thermals and connectors become "
                        "the design")
        elif current >= CURRENT_AGENT_LED_A:
            soft.append(f"peak_current_a={current:g}: copper width, thermal relief and connector "
                        "rating all need checking")

    count = _number(answers, "component_count_estimate")
    if count is not None and count > COMPONENTS_AGENT_LED:
        soft.append(f"component_count_estimate={count:g}: review volume, not risk")

    if answers.get("route") == "pcba":
        soft.append("route=pcba: rotation convention, origin and units decide whether parts are "
                    "fitted backwards, and the files cannot prove it")

    if hard:
        tier = "HUMAN_LED"
    elif soft:
        tier = "AGENT_LED"
    else:
        tier = "AGENT_AUTONOMOUS"

    summary = {
        "AGENT_AUTONOMOUS": "No hard gate and no escalator was declared. The agent can run the "
                            "whole workflow; you inspect the package and order it.",
        "AGENT_LED": "The agent does the work, but a person who understands hardware must sign "
                     "three checkpoints.",
        "HUMAN_LED": "A qualified engineer owns the topology and the critical placement. The "
                     "agent assists, generates, checks and audits.",
    }[tier]

    return {
        "tool": "feasibility",
        "tier": tier,
        "summary": summary,
        "hard_gates": hard,
        "escalators": soft,
        "agent_does": AGENT_WORK[tier],
        "human_must": HUMAN_WORK[tier],
        "unrecognised_answers": unknown,
        "caveats": [
            "This is a routing decision about human attention, computed only from the answers "
            "given. Wrong answers give a wrong tier.",
            "The tier is not permission: no gate, datasheet check or Gerber inspection is "
            "skipped at any tier.",
            "The tier may rise as facts emerge. Lowering it needs a written reason, and above "
            "AGENT_AUTONOMOUS a named person.",
            "ORDER_READY always needs a named human approving the exact package hash and a "
            "current manufacturer preview, at every tier.",
        ],
    }


def answers_from_manifest(manifest: dict) -> dict:
    """Derive the answer set implied by a manifest's own risk flags."""
    risk = manifest.get("risk", {}) or {}
    board = manifest.get("board", {}) or {}
    project = manifest.get("project", {}) or {}
    answers: dict[str, Any] = {}
    for key in HARD_GATES:
        if key in risk:
            answers[key] = risk[key] is True
    feas = manifest.get("feasibility", {}) or {}
    for key in list(HARD_GATES) + list(ESCALATORS):
        if key in feas.get("factors", {}):
            answers[key] = feas["factors"][key] is True
    for key in ("copper_layers",):
        if board.get(key) is not None:
            answers[key] = board[key]
    for key in ("peak_current_a", "component_count_estimate"):
        if feas.get("factors", {}).get(key) is not None:
            answers[key] = feas["factors"][key]
    if project.get("route"):
        answers["route"] = project["route"]
    return answers


def render(result: dict) -> str:
    lines = [f"tier: {result['tier']}", result["summary"], ""]
    if result["hard_gates"]:
        lines.append("hard gates (each one forces HUMAN_LED):")
        lines += [f"  - {item}" for item in result["hard_gates"]]
        lines.append("")
    if result["escalators"]:
        lines.append("escalators (each one forces at least AGENT_LED):")
        lines += [f"  - {item}" for item in result["escalators"]]
        lines.append("")
    lines.append(f"the agent does: {result['agent_does']}")
    lines.append("the human must:")
    lines += [f"  - {item}" for item in result["human_must"]]
    if result["unrecognised_answers"]:
        lines.append("")
        lines.append("ignored, not recognised: " + ", ".join(result["unrecognised_answers"]))
    return "\n".join(lines)


def run(answers_path: Path | None, manifest_path: Path | None, json_out: Path | None) -> int:
    try:
        if manifest_path is not None:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            answers = answers_from_manifest(manifest)
            recorded = (manifest.get("feasibility", {}) or {}).get("tier")
        else:
            answers = json.loads(answers_path.read_text(encoding="utf-8"))
            recorded = None
        result = assess(answers)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"feasibility: BLOCKED — {exc}", file=sys.stderr)
        return 2

    result["answers_used"] = answers
    if recorded is not None:
        result["recorded_tier"] = recorded
        result["agrees_with_record"] = recorded == result["tier"]

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(render(result))
    if recorded is not None and recorded != result["tier"]:
        print(
            f"\n[blocking] manifest records feasibility.tier={recorded!r} but the declared facts "
            f"give {result['tier']!r}. Fix whichever one is wrong; do not leave them disagreeing."
        )
        return 1
    return 0


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

def self_test() -> int:
    checks: list[tuple[str, bool]] = []

    def expect(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    simple = {
        "copper_layers": 2,
        "peak_current_a": 0.4,
        "component_count_estimate": 45,
        "route": "pcb-only",
    }
    expect("a simple USB board is autonomous", assess(simple)["tier"] == "AGENT_AUTONOMOUS")
    expect("an empty answer set is autonomous", assess({})["tier"] == "AGENT_AUTONOMOUS")

    # every hard gate on its own
    for key in HARD_GATES:
        result = assess({**simple, key: True})
        expect(f"hard gate {key} forces HUMAN_LED", result["tier"] == "HUMAN_LED")
        expect(f"hard gate {key} is named in the output",
               any(item.startswith(key + ":") for item in result["hard_gates"]))

    # every escalator on its own
    for key in ESCALATORS:
        result = assess({**simple, key: True})
        expect(f"escalator {key} forces AGENT_LED", result["tier"] == "AGENT_LED")
        expect(f"escalator {key} is named in the output",
               any(item.startswith(key + ":") for item in result["escalators"]))

    expect("4 layers escalate", assess({**simple, "copper_layers": 4})["tier"] == "AGENT_LED")
    expect("6 layers are a hard gate", assess({**simple, "copper_layers": 6})["tier"] == "HUMAN_LED")
    expect("3 A escalates", assess({**simple, "peak_current_a": 3.0})["tier"] == "AGENT_LED")
    expect("2.9 A does not escalate",
           assess({**simple, "peak_current_a": 2.9})["tier"] == "AGENT_AUTONOMOUS")
    expect("10 A is a hard gate", assess({**simple, "peak_current_a": 10})["tier"] == "HUMAN_LED")
    expect("151 components escalate",
           assess({**simple, "component_count_estimate": 151})["tier"] == "AGENT_LED")
    expect("150 components do not escalate",
           assess({**simple, "component_count_estimate": 150})["tier"] == "AGENT_AUTONOMOUS")
    expect("pcba escalates", assess({**simple, "route": "pcba"})["tier"] == "AGENT_LED")

    both = assess({**simple, "route": "pcba", "mains_voltage": True})
    expect("a hard gate outranks an escalator", both["tier"] == "HUMAN_LED")
    expect("both drivers are still reported", both["hard_gates"] and both["escalators"])

    expect("false flags do not escalate",
           assess({**simple, "mains_voltage": False, "route": "pcb-only"})["tier"]
           == "AGENT_AUTONOMOUS")
    expect("a truthy non-true value does not count as declared",
           assess({**simple, "mains_voltage": "no"})["tier"] == "AGENT_AUTONOMOUS")

    expect("unrecognised keys are reported, not silently used",
           assess({**simple, "make_it_easy": True})["unrecognised_answers"] == ["make_it_easy"])
    expect("underscore keys are treated as comments",
           assess({**simple, "_note": "hi"})["unrecognised_answers"] == [])
    expect("an unrecognised key never changes the tier",
           assess({**simple, "make_it_easy": True})["tier"] == "AGENT_AUTONOMOUS")

    expect("human work is listed for every tier",
           all(HUMAN_WORK[t] for t in TIERS))
    expect("autonomous still requires human package inspection",
           any("preview" in item or "inspect" in item
               for item in assess(simple)["human_must"]))
    expect("autonomous still requires a human for ORDER_READY",
           any("ORDER_READY" in c for c in assess(simple)["caveats"]))

    raised = False
    try:
        assess({"peak_current_a": "lots"})
    except ValueError:
        raised = True
    expect("a non-numeric current raises", raised)

    raised = False
    try:
        assess([])
    except ValueError:
        raised = True
    expect("a non-object answer set raises", raised)

    expect("tier ranking is ordered", RANK["AGENT_AUTONOMOUS"] < RANK["AGENT_LED"] < RANK["HUMAN_LED"])

    # manifest-derived answers
    manifest = {
        "project": {"route": "pcb-only"},
        "board": {"copper_layers": 2},
        "risk": {k: False for k in HARD_GATES if k in
                 ("human_contact", "battery_charging", "mains_voltage", "high_energy",
                  "safety_function", "controlled_impedance", "hdi_or_bga")},
        "feasibility": {"tier": "AGENT_AUTONOMOUS", "factors": {}},
    }
    expect("manifest-derived answers reproduce the tier",
           assess(answers_from_manifest(manifest))["tier"] == "AGENT_AUTONOMOUS")
    manifest["risk"]["battery_charging"] = True
    expect("a manifest risk flag reaches the assessment",
           assess(answers_from_manifest(manifest))["tier"] == "HUMAN_LED")

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        answers_file = base / "a.json"
        answers_file.write_text(json.dumps(simple), encoding="utf-8")
        out = base / "tier.json"
        expect("file run returns 0", run(answers_file, None, out) == 0)
        expect("json output is written", json.loads(out.read_text())["tier"] == "AGENT_AUTONOMOUS")

        m = base / "m.json"
        m.write_text(json.dumps(manifest), encoding="utf-8")  # battery_charging is True here
        expect("a manifest whose recorded tier disagrees returns 1", run(None, m, None) == 1)
        manifest["feasibility"]["tier"] = "HUMAN_LED"
        m.write_text(json.dumps(manifest), encoding="utf-8")
        expect("a manifest whose recorded tier agrees returns 0", run(None, m, None) == 0)

        bad = base / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        expect("unparsable input returns 2", run(bad, None, None) == 2)

    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print(f"FAIL: {name}", file=sys.stderr)
    print(f"feasibility self-test: {'PASS' if not failed else 'FAIL'} "
          f"({len(checks) - len(failed)}/{len(checks)})")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("answers", nargs="?", type=Path,
                        help="JSON file of intake answers (see examples/feasibility-answers.example.json)")
    parser.add_argument("--manifest", type=Path,
                        help="check the tier recorded in a manifest against its own declared facts")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.answers is None and args.manifest is None:
        parser.error("give an answers file or --manifest, or use --self-test")
    return run(args.answers, args.manifest, args.json_out)


if __name__ == "__main__":
    raise SystemExit(main())

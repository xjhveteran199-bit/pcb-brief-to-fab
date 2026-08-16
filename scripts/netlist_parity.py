#!/usr/bin/env python3
"""Compare two KiCad XML netlists for semantic connectivity equivalence.

Semantic equivalence means: the same set of (reference, pin) nodes, partitioned
into the same groups. Net *names* may differ; membership may not.

Use it every time a schematic is edited for readability, refactored, or
regenerated. A text diff of the schematic and a visual check of the drawing are
not evidence that the circuit is unchanged.

    python netlist_parity.py baseline.xml candidate.xml
    python netlist_parity.py baseline.xml candidate.xml --json-out diff.json --require-same-names
    python netlist_parity.py --self-test

Exit codes: 0 = equivalent, 1 = different, 2 = usage/parse error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

Node = tuple[str, str]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_netlist(path: Path) -> dict[str, set[Node]]:
    """Return {net_name: {(ref, pin), ...}} from a KiCad XML netlist.

    Uses an XML parser, never a regular expression. Raises ValueError with a
    specific message when the file is not a netlist we understand, so the caller
    fails closed instead of silently comparing two empty dictionaries.
    """
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"{path}: not parsable XML ({exc})") from exc

    nets_el = root.find("nets")
    if nets_el is None:
        raise ValueError(f"{path}: no <nets> section; is this a KiCad XML netlist?")

    nets: dict[str, set[Node]] = {}
    for net in nets_el.findall("net"):
        name = net.get("name")
        if name is None:
            raise ValueError(f"{path}: a <net> element has no name attribute")
        members: set[Node] = set()
        for node in net.findall("node"):
            ref = node.get("ref")
            pin = node.get("pin")
            if ref is None or pin is None:
                raise ValueError(f"{path}: a <node> in net {name!r} is missing ref or pin")
            members.add((ref, pin))
        if name in nets:
            raise ValueError(f"{path}: duplicate net name {name!r}")
        nets[name] = members

    if not nets:
        raise ValueError(f"{path}: netlist contains zero nets; refusing to call that a baseline")
    return nets


def _node_index(nets: dict[str, set[Node]]) -> dict[Node, str]:
    index: dict[Node, str] = {}
    for name, members in nets.items():
        for node in members:
            if node in index:
                raise ValueError(
                    f"node {node[0]}.{node[1]} appears in both {index[node]!r} and {name!r}"
                )
            index[node] = name
    return index


def compare(
    baseline: dict[str, set[Node]],
    candidate: dict[str, set[Node]],
    require_same_names: bool = False,
) -> dict:
    base_index = _node_index(baseline)
    cand_index = _node_index(candidate)

    base_nodes = set(base_index)
    cand_nodes = set(cand_index)
    missing = sorted(base_nodes - cand_nodes)
    added = sorted(cand_nodes - base_nodes)
    shared = base_nodes & cand_nodes

    # Partition comparison restricted to the shared nodes: two nodes that shared a
    # net in the baseline must still share one, and vice versa.
    base_groups: dict[str, frozenset[Node]] = {}
    for name, members in baseline.items():
        base_groups[name] = frozenset(members & shared)
    cand_groups: dict[str, frozenset[Node]] = {}
    for name, members in candidate.items():
        cand_groups[name] = frozenset(members & shared)

    base_partition = {g for g in base_groups.values() if g}
    cand_partition = {g for g in cand_groups.values() if g}

    moved: list[dict] = []
    if base_partition != cand_partition:
        for node in sorted(shared):
            b_group = frozenset(baseline[base_index[node]] & shared)
            c_group = frozenset(candidate[cand_index[node]] & shared)
            if b_group != c_group:
                moved.append(
                    {
                        "node": f"{node[0]}.{node[1]}",
                        "baseline_net": base_index[node],
                        "candidate_net": cand_index[node],
                        "lost_neighbours": sorted(
                            f"{r}.{p}" for r, p in (b_group - c_group) if (r, p) != node
                        ),
                        "gained_neighbours": sorted(
                            f"{r}.{p}" for r, p in (c_group - b_group) if (r, p) != node
                        ),
                    }
                )

    renamed: list[dict] = []
    if base_partition == cand_partition:
        cand_by_group = {g: n for n, g in cand_groups.items() if g}
        for name, group in base_groups.items():
            if not group:
                continue
            other = cand_by_group.get(group)
            if other is not None and other != name:
                renamed.append({"baseline_net": name, "candidate_net": other})

    equivalent = not missing and not added and not moved
    if require_same_names and renamed:
        equivalent = False

    return {
        "equivalent": equivalent,
        "baseline_nets": len(baseline),
        "candidate_nets": len(candidate),
        "baseline_nodes": len(base_nodes),
        "candidate_nodes": len(cand_nodes),
        "nodes_missing_in_candidate": [f"{r}.{p}" for r, p in missing],
        "nodes_added_in_candidate": [f"{r}.{p}" for r, p in added],
        "nodes_with_changed_connectivity": moved,
        "renamed_nets": renamed,
        "require_same_names": require_same_names,
    }


def run(baseline_path: Path, candidate_path: Path, json_out: Path | None, same_names: bool) -> int:
    try:
        baseline = parse_netlist(baseline_path)
        candidate = parse_netlist(candidate_path)
        result = compare(baseline, candidate, same_names)
    except (ValueError, FileNotFoundError) as exc:
        print(f"netlist_parity: BLOCKED — {exc}", file=sys.stderr)
        return 2

    result["baseline_file"] = str(baseline_path)
    result["baseline_sha256"] = sha256(baseline_path)
    result["candidate_file"] = str(candidate_path)
    result["candidate_sha256"] = sha256(candidate_path)
    result["status"] = "EQUIVALENT" if result["equivalent"] else "DIFFERENT"

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"nets {result['baseline_nets']} -> {result['candidate_nets']}, "
        f"nodes {result['baseline_nodes']} -> {result['candidate_nodes']}"
    )
    for node in result["nodes_missing_in_candidate"]:
        print(f"  missing in candidate: {node}")
    for node in result["nodes_added_in_candidate"]:
        print(f"  added in candidate:   {node}")
    for change in result["nodes_with_changed_connectivity"]:
        print(
            f"  connectivity changed: {change['node']} "
            f"({change['baseline_net']} -> {change['candidate_net']}) "
            f"lost={change['lost_neighbours']} gained={change['gained_neighbours']}"
        )
    if result["renamed_nets"]:
        print(f"  {len(result['renamed_nets'])} net(s) renamed but membership unchanged")
    print(f"netlist_parity: {result['status']}")
    return 0 if result["equivalent"] else 1


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

def _xml(nets: dict[str, list[tuple[str, str]]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<export version=\"E\">", "  <nets>"]
    for code, (name, nodes) in enumerate(nets.items(), start=1):
        lines.append(f'    <net code="{code}" name="{name}">')
        for ref, pin in nodes:
            lines.append(f'      <node ref="{ref}" pin="{pin}"/>')
        lines.append("    </net>")
    lines += ["  </nets>", "</export>"]
    return "\n".join(lines)


def self_test() -> int:
    checks: list[tuple[str, bool]] = []

    def expect(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))

    base = {
        "GND": [("R1", "2"), ("C1", "2"), ("U1", "4")],
        "VCC": [("U1", "8"), ("C1", "1")],
        "NET1": [("R1", "1"), ("U1", "1")],
    }

    a = parse_netlist_from_string(_xml(base))
    expect("identical netlists are equivalent", compare(a, a)["equivalent"])

    renamed = dict(base)
    renamed["Net-(R1-Pad1)"] = renamed.pop("NET1")
    b = parse_netlist_from_string(_xml(renamed))
    result = compare(a, b)
    expect("pure rename is still equivalent", result["equivalent"])
    expect("rename is reported", len(result["renamed_nets"]) == 1)
    expect("rename fails --require-same-names", not compare(a, b, True)["equivalent"])

    moved = {k: list(v) for k, v in base.items()}
    moved["NET1"].remove(("U1", "1"))
    moved["VCC"].append(("U1", "1"))
    c = parse_netlist_from_string(_xml(moved))
    result = compare(a, c)
    expect("a moved pin is not equivalent", not result["equivalent"])
    expect(
        "the moved pin is named",
        any(x["node"] == "U1.1" for x in result["nodes_with_changed_connectivity"]),
    )

    dropped = {k: list(v) for k, v in base.items()}
    dropped["GND"].remove(("U1", "4"))
    d = parse_netlist_from_string(_xml(dropped))
    result = compare(a, d)
    expect("a dropped node is not equivalent", not result["equivalent"])
    expect("the dropped node is named", result["nodes_missing_in_candidate"] == ["U1.4"])

    extra = {k: list(v) for k, v in base.items()}
    extra["GND"].append(("U2", "1"))
    e = parse_netlist_from_string(_xml(extra))
    result = compare(a, e)
    expect("an added node is not equivalent", not result["equivalent"])
    expect("the added node is named", result["nodes_added_in_candidate"] == ["U2.1"])

    # A split: one net becomes two, node count unchanged. This is the case a
    # naive "same number of nets/nodes" check misses.
    split = {
        "GND": [("R1", "2"), ("C1", "2")],
        "GND2": [("U1", "4")],
        "VCC": [("U1", "8"), ("C1", "1")],
        "NET1": [("R1", "1"), ("U1", "1")],
    }
    g = parse_netlist_from_string(_xml(split))
    expect("a split net is detected", not compare(a, g)["equivalent"])
    expect("node counts are equal in the split case",
           compare(a, g)["baseline_nodes"] == compare(a, g)["candidate_nodes"])

    # Failure modes must raise, not silently return empty.
    for bad, label in (
        ("<export><nets></nets></export>", "empty netlist"),
        ("<export></export>", "missing <nets>"),
        ("<export><nets><net code='1'><node ref='R1' pin='1'/></net></nets></export>", "unnamed net"),
        ("<export><nets><net code='1' name='A'><node ref='R1'/></net></nets></export>", "node without pin"),
        ("not xml at all", "unparsable"),
    ):
        raised = False
        try:
            parse_netlist_from_string(bad)
        except ValueError:
            raised = True
        expect(f"{label} raises", raised)

    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "a.xml"
        p2 = Path(td) / "b.xml"
        p1.write_text(_xml(base), encoding="utf-8")
        p2.write_text(_xml(renamed), encoding="utf-8")
        out = Path(td) / "diff.json"
        expect("file run returns 0 when equivalent", run(p1, p2, out, False) == 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        expect("report records both hashes",
               len(report["baseline_sha256"]) == 64 and len(report["candidate_sha256"]) == 64)
        p3 = Path(td) / "c.xml"
        p3.write_text(_xml(moved), encoding="utf-8")
        expect("file run returns 1 when different", run(p1, p3, None, False) == 1)
        expect("missing file returns 2", run(p1, Path(td) / "nope.xml", None, False) == 2)

    failed = [name for name, ok in checks if not ok]
    for name in failed:
        print(f"FAIL: {name}", file=sys.stderr)
    print(f"netlist_parity self-test: {'PASS' if not failed else 'FAIL'} "
          f"({len(checks) - len(failed)}/{len(checks)})")
    return 0 if not failed else 1


def parse_netlist_from_string(text: str) -> dict[str, set[Node]]:
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as handle:
        handle.write(text)
        temp = Path(handle.name)
    try:
        return parse_netlist(temp)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("baseline", nargs="?", type=Path)
    parser.add_argument("candidate", nargs="?", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument(
        "--require-same-names",
        action="store_true",
        help="also require net names to match, not just connectivity",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.baseline is None or args.candidate is None:
        parser.error("baseline and candidate are required unless --self-test is given")
    return run(args.baseline, args.candidate, args.json_out, args.require_same_names)


if __name__ == "__main__":
    raise SystemExit(main())

# Gate model

A gate is a named checkpoint with an **entry condition**, a **required evidence
set**, and an **exit rule**. Evidence is a file produced by a named tool from a
named input hash. Prose is not evidence. A previous run's report describing a
different file hash is not evidence.

## The gates

### G0 — Intake frozen

Entry: the user has stated what the board is for.

Evidence: filled intake questionnaire; every unknown listed as an unknown; entry
type, release route, and risk tier chosen with written reasons.

Exit: the user has confirmed the requirement list. Do not start architecture work
against a requirement list nobody agreed to.

### G1 — Manifest valid

Evidence: `manifest_check.py --stage design` returns PASS.

Exit: derived geometry is self-consistent (outline = placement area + 2 × edge
margin, layer-name count = layer count, stack-up role count = layer count), DFM
minimums are present, and risk flags are set explicitly rather than defaulted.

Common failure: two documents state different board sizes. Fix the documents, not
the manifest, and never let a generator read a size from prose.

### G2 — Architecture reviewed

Evidence: block diagram, power tree with a current budget, interface table, fault
behaviour table, per-part datasheet verification record (MPN, revision, pin map,
ratings, package).

Exit for `HIGH` risk: a named human with a stated role has approved the topology,
with a timezone-qualified date and an evidence file or URL in the manifest.

### G3 — Schematic tool-verified

Evidence, all from the same schematic hash:

- ERC report — zero blocking findings; every exclusion has a written reason and a reviewer;
- XML netlist — frozen as the approved baseline, path and SHA-256 in the manifest;
- BOM export.

Exit: the state label for the schematic becomes `TOOL_VERIFIED` and is bound to
that hash. Any later edit invalidates it until the gate re-runs.

### G4 — Placement gate

Evidence: DRC run with geometry and schematic-parity checks; the unconnected count
recorded as a baseline; a placement review covering mechanical anchors, connector
mating directions, antenna keepout, switching-converter sub-layouts, pin-bound
decoupling, thermal paths, edge clearance, courtyard overlaps, and test access.

Exit: zero DRC geometry violations, zero schematic parity differences.
Unconnected may be nonzero here — that is the routing work still to do.

### G5 — Routing gate

Evidence: DRC after the final zone refill.

Exit: **zero** blocking DRC violations, **zero** unconnected items, **zero**
schematic parity differences. Plus a critical-net checklist stating, per net, that
its return path, guard, keepout, or impedance requirement is satisfied.

A partially routed board does not pass G5. It can still be a legitimate
`ENGINEERING_HANDOFF` — package it and say so.

### G6 — Manufacturing export

Evidence: Gerber, drill, and (for `pcba`) paste, BOM, CPL — all generated from the
same source hash in one run, with the tool version recorded.

Exit: the export tool exited zero, every declared output exists and is non-empty,
and the source hashes recorded before and after the run are identical.

### G7 — Package audit

Evidence: `fab_audit.py --strict` returns PASS.

Exit: copper layer count matches the manifest; outline, mask, silkscreen and drill
are present; no unknown files; no non-manufacturing layers (Courtyard, Fab,
Margin, User, Dwgs, Eco) leaked in; no paste layers in a `pcb-only` package;
`.gbrjob` metadata agrees with the manifest; minimum drill is at or above the
declared floor; for `pcba`, BOM and CPL designator sets agree with each other and
with the expected fitted set.

Exit state: `RELEASE_CANDIDATE`. Not `ORDER_READY`.

### G8 — Human and manufacturer release

Evidence:

- an independent Gerber/drill viewer inspection, with what was inspected written down:
  outline, layer order, plated and non-plated holes, copper, mask, paste,
  silkscreen, exposed pads, plane fills, antenna and edge features, connector
  orientation;
- the target manufacturer's current upload/DFM preview with no unresolved blocker;
- a named qualified reviewer approving the exact package SHA-256.

Exit state: `ORDER_READY`.

### G9 — Bring-up

Evidence: measured results from real boards against a written bring-up plan.

Nothing before G9 says the board works. G0–G8 only say the files are internally
consistent and manufacturable-looking.

## Rules that apply to every gate

1. **Bind evidence to hashes.** A report names the file hash it describes, the tool
   and version that produced it, and the time. If the file changed, the report is void.
2. **Fail closed.** If the manifest cannot be parsed, a dependency is missing, the
   CLI is not found, or a parser errors — the gate result is `BLOCKED`, never PASS.
3. **A superseded result is struck through, not left standing.** Never leave an old
   "ERC 0 errors" line next to changed files.
4. **Exclusions are decisions.** Every ERC/DRC exclusion carries a reason and a
   named person. Zero-by-exclusion is not zero.
5. **New directory per attempt.** Never overwrite or rename a previous evidence
   directory. Directory names are cheap; a laundered failure is not.
6. **Order of authority when values conflict:** reviewed measurements and signed
   decisions > requirement documents > manifest > EDA files and generated reports >
   current manufacturer capability check > generic references. No metric script
   overrules an ERC/DRC error, a physical violation, a missing measurement, a
   visual defect, or a manufacturer upload error.

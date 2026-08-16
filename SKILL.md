---
name: pcb-brief-to-fab
description: Take a plain-language hardware brief and drive it through requirement intake, a machine-readable constraint manifest, schematic capture, placement, routing, ERC/DRC/netlist-parity gates, and a Gerber/drill/BOM/CPL fabrication package with hash-bound evidence. Use for PCB design, PCB打板, 画板子, 原理图, 布局布线, KiCad projects, editing an existing .kicad_sch/.kicad_pcb, Gerber or drill export, PCB-only or PCBA/SMT handoff, JLCPCB/嘉立创 delivery, DFM review, or auditing whether an existing board package is genuinely order-ready. Never use it to assert safety, compliance, certification, or functional correctness without tool evidence plus a named qualified human review.
---

# PCB: brief to fabrication package

Turn a hardware idea into a traceable engineering candidate, and — only after every
gate passes on the exact file hashes — into a fabrication package.

The value of this skill is not speed. It is that every claim is bound to a named
tool, a named file hash, and a timestamp, and that the run refuses to advance when
the evidence does not exist.

## Two rules that override everything else

1. **A green check is not correctness.** A gate proves that one named tool found
   zero blocking findings in one named file. It does not prove the topology, the
   ratings, the thermals, the EMC behaviour, the safety, or that the board works.
2. **A hardcoded assumption is not a measurement.** Never write a check whose
   answer comes from a literal you typed. If you want to know how a tool behaves,
   build a controlled probe, run the real tool, and read the answer out of its
   output. See `references/06-antipatterns.md` for the cases that produced this rule.

## Load the right reference

Read on demand, not all at once:

| When | Read |
|---|---|
| Always, before the first action | `references/02-gates.md` |
| Turning a brief into requirements | `references/01-intake-and-manifest.md` |
| Deciding who does what on this board | `references/07-feasibility-tiers.md` |
| Touching any KiCad file or CLI | `references/03-kicad-facts.md` |
| Placing parts or routing copper | `references/04-placement-and-routing.md` |
| Exporting or auditing manufacturing files | `references/05-fab-package.md` |
| A gate looks suspiciously green, or automation is failing | `references/06-antipatterns.md` |

## State labels — use these exact words, never a synonym

| Label | Meaning |
|---|---|
| `DRAFT` | Requirements or design are still moving. |
| `AUTHORED_NOT_VERIFIED` | Files exist. The declared tool has **not** run on these hashes. |
| `TOOL_VERIFIED` | The named tool ran on the named hash; blocking findings are zero. |
| `ENGINEERING_HANDOFF` | Deliberately incomplete, packaged for a qualified engineer. Not orderable. |
| `RELEASE_CANDIDATE` | All tool gates and the package audit passed. Human and fab review pending. |
| `ORDER_READY` | A named qualified reviewer approved the exact package SHA-256 **and** the target manufacturer's current upload/DFM preview shows no unresolved blocker. |
| `BLOCKED` | A gate failed, or required physical/human evidence does not exist. |

`ORDER_READY` can never be set by this skill on its own authority. It requires a
human name, a role, a timezone-qualified date, and an evidence file or URL
recorded in the manifest.

## Step 0 — classify the job before doing anything

Pick one **entry**:

- `NEW_DESIGN` — start from the brief and the intake questionnaire.
- `EXISTING_SCHEMATIC` — inventory sources, re-run ERC/netlist/BOM on current hashes, then review.
- `EXISTING_BOARD` — re-run ERC + DRC + schematic parity, inspect placement/mechanics, then decide revise vs audit.
- `RELEASE_AUDIT` — read-only. Do not edit a single file. Audit the exact source and package hashes.

Pick one **route**:

- `pcb-only` — bare board: Gerber, drill, fab notes, visual review evidence.
- `pcba` — everything above plus paste layers, assembly BOM, CPL, DNP policy, polarity/rotation review, supplier part mapping.

Pick one **risk tier** and write the reason down:

- `LOW` — USB or bench supply, no human contact, no battery charging, no mains, no RF, no motor, no safety function.
- `MODERATE` — battery powered, RF module, moderate current, moving parts, outdoor use.
- `HIGH` — human/animal contact, lithium charging, mains, high energy, medical/vehicle/flight/industrial-safety function, controlled impedance, HDI/BGA.

`HIGH` requires a named human topology/safety review recorded in the manifest
**before** the schematic freezes. An agent ticking its own checkbox is not review.

## Before first use — confirm the bundled scripts run here

```text
python <skill-dir>/scripts/selftest.py
```

All five must report PASS. This proves the scripts behave as documented on
synthetic inputs, including their refusals. It does **not** prove KiCad is
installed or that its CLI flags match your version — check that separately with
`kicad-cli version` and `kicad-cli --help`.

`examples/example-manifest.json` is a filled, passing manifest to compare against.

## Step 1 — intake

Copy `assets/intake-questionnaire.md` and fill it with the user. Ask only what
changes behaviour, cost, mechanics, or risk. Explain each question in plain
language — assume the user may not be an electronics engineer.

Every unknown is written down as an unknown. Never silently invent a supply
voltage, a connector orientation, a land pattern, an antenna keepout, an
impedance target, or a manufacturer capability limit.

## Step 1b — assess the feasibility tier, and say it out loud

As soon as intake is answered — before the manifest, before any design work —
decide **where a qualified human must be in the loop for this specific board**.
Read `references/07-feasibility-tiers.md`, then run the rubric rather than
judging by feel:

```text
python <skill-dir>/scripts/feasibility.py <answers.json> --json-out <tier.json>
```

`examples/feasibility-answers.example.json` shows the input shape.

| Tier | Who designs | What the human must still do |
|---|---|---|
| `AGENT_AUTONOMOUS` | The agent, end to end, to a `RELEASE_CANDIDATE` package | Inspect the Gerber package in a viewer or the fab's preview, then order and approve the exact package hash |
| `AGENT_LED` | The agent, stopping at three checkpoints | Sign the topology, sign the placement, sign the package — each recorded with a name, role, timezone-qualified date and evidence |
| `HUMAN_LED` | A qualified engineer owns topology and critical placement | Everything above, plus the design decisions themselves. Any package the agent produces alone is `ENGINEERING_HANDOFF` |

Then, in your first reply after intake, state the tier, the **specific fact that
drove it**, and exactly what you will and will not do. "HUMAN_LED, because the
board charges a lithium cell" is useful. "HUMAN_LED (high risk)" is not.

Three rules about the tier:

- It is **not permission**. No gate, datasheet check, or Gerber inspection is
  skipped at any tier, including `AGENT_AUTONOMOUS`.
- It may **rise** as facts emerge — that is just an honest re-read. Lowering it
  needs a written reason, and above `AGENT_AUTONOMOUS`, a named person.
- Record it in the manifest. `manifest_check.py` recomputes it from the manifest's
  own declared facts and blocks when the recorded tier disagrees.

If the user pushes back on a hard gate, do not argue about the tier. Name the
specific failure mode, offer the design change that removes it (an external
certified charger instead of an on-board one; a pre-certified module instead of a
chip antenna), and let them choose.

## Step 2 — freeze a machine-readable manifest

Copy `assets/constraint-manifest.template.json`, fill it, and validate:

```text
python <skill-dir>/scripts/manifest_check.py <manifest.json> --stage design --json-out <out.json>
```

The manifest is the single controlling record for revision, route, layer stack,
outline, DFM minimums, fitted/DNP policy, manufacturer, risk flags, and human
approvals. When a document and the manifest disagree, the manifest wins and the
document gets fixed.

`assets/constraint-manifest.fields.md` explains every field in plain language.

Re-validate with `--stage release` before any manufacturing export. That stage
additionally requires zero unresolved unknowns, explicit manufacturer and process
parameters, and — for `HIGH` risk — a complete human approval record.

## Step 3 — architecture review, before drawing anything

Produce and record: block diagram, power tree, current and thermal budget,
interface table, fault behaviour (what happens at reset, brownout, unpowered,
firmware update), programming/debug path, and test strategy.

For every critical part, verify against the **primary datasheet**: exact orderable
MPN, revision/date, pin mapping, absolute maximum and recommended ratings with
derating, package drawing, exposed pad, and the vendor reference circuit. Record
the datasheet revision in the decision log. Never infer a footprint from a
marketing name or a part-number prefix.

## Step 4 — schematic

Details in `references/03-kicad-facts.md`. Summary:

- Prefer stable libraries; every symbol-to-footprint mapping is verified, not assumed.
- Make power intent explicit. Add test points and a programming/debug path.
- Label polarity and connector mating direction on the schematic, not only in prose.
- Keep the schematic readable for a human: draw real wires, group by function, and
  put each decoupling capacitor next to the pin it decouples on **both** the
  schematic and the PCB.
- Run ERC in the real EDA. Resolve blockers in the source. An ERC *exclusion* is a
  written decision with a reviewer name, not a way to make a number reach zero.
- Export the XML netlist and BOM from the same source hash, then freeze that
  netlist as the approved baseline and record its path plus SHA-256 in the manifest.

Whenever you edit the schematic for readability or refactoring, prove you did not
change the circuit:

```text
python <skill-dir>/scripts/netlist_parity.py <baseline.xml> <candidate.xml> --json-out <diff.json>
```

Semantic parity means the same partition of (reference, pin) nodes. Net *names*
may change; membership may not. Text diffs and eyeballing the drawing are not
evidence.

## Step 5 — placement

Read `references/04-placement-and-routing.md` first. Order of operations:

1. Lock mechanically-constrained parts by absolute coordinate: connectors whose
   mating face must reach the board edge, antennas and their keepouts, mounting
   holes, sensors, displays, buttons, and the board outline itself.
2. Hand-place every switching converter sub-layout (inductor, input/output bulk
   capacitors, feedback divider). A packing algorithm will not do this correctly.
3. Pin-bind every decoupling and loop-stability capacitor to the pin it serves.
4. Place everything else by signal and current flow.

At the placement gate: DRC geometry and schematic parity must be clean. The
unconnected count is recorded as a **routing baseline**, not required to be zero yet.

## Step 6 — routing

Route by risk, highest first: high current, switch nodes and hot loops, clocks,
differential and controlled-impedance pairs, RF feed, high-impedance and guarded
nodes, feedback, safety-critical control lines. Keep a continuous return path; do
not casually split a reference plane. Refill zones before every final DRC.

Autorouting is an **experiment** until the real EDA proves completion. Record its
result honestly. A routed percentage is never a release claim, and a router that
cannot express your critical-net constraints has not routed your critical nets.

At the final routing gate, all three must be zero: blocking DRC violations,
unconnected items, schematic parity differences.

## Step 7 — run the gates with evidence binding

Never compose ad-hoc shell pipelines around `kicad-cli`. Use the runner, which
hashes every input, records the CLI version, uses an argument array rather than a
shell string, refuses to write outside the project root, refuses to overwrite an
existing output directory, and returns `BLOCKED` with the evidence intact when a
gate fails:

```text
python <skill-dir>/scripts/kicad_gate.py plan --manifest <m.json> --schematic <b.kicad_sch> --board <b.kicad_pcb> --project-root <root> --output <new-dir>
python <skill-dir>/scripts/kicad_gate.py run  --manifest <m.json> --schematic <b.kicad_sch> --board <b.kicad_pcb> --project-root <root> --output <new-dir>
```

`plan` prints the exact commands and input hashes without executing anything. Show
the plan to the user before running it.

If a run reports `BLOCKED`: fix the source, then rerun into a **new** output
directory. Never rename a blocked evidence directory to look like a release.

## Step 8 — audit the fabrication package independently

The exporter and the auditor must not be the same code path:

```text
python <skill-dir>/scripts/fab_audit.py <fab-dir-or-zip> --manifest <m.json> --json-out <audit.json> --strict
```

For `pcba`, also pass `--bom <bom.csv> --cpl <cpl.csv>` and the expected fitted
designator set derived from the candidate netlist plus the DNP policy.

What this auditor **can** prove: file inventory, copper layer cardinality, presence
of outline/mask/paste/drill, `.gbrjob` metadata agreement, parsable Excellon tools,
minimum drill, BOM/CPL designator set agreement, DNP leakage, and unknown or
non-manufacturing layers leaking into the package.

What it **cannot** prove: that the outline is closed, that copper is electrically
correct, that holes align with pads, or that the board is manufacturable. Those
require an independent Gerber viewer and the target manufacturer's current upload
preview. Say so in the report.

## Step 9 — human review, order, bring-up

- A qualified human approves topology and safety before schematic freeze, and
  approves the exact package SHA-256 before ordering.
- Re-check the manufacturer's current capability rules and live part availability
  on the day of upload. Remembered numbers expire.
- Order a small prototype quantity first, with a written bring-up plan: continuity
  and short checks, current-limited power-up, rail measurement, reset and
  programming, interfaces, loads, thermal observation, then function.
  `assets/bringup-checklist.md` is the starting template.
- Feed every measured failure back into the manifest and the next revision.

## Stop conditions — say `BLOCKED` and stop

Stop and report rather than producing more artifacts when:

- pinout, land pattern, or datasheet evidence is missing;
- constraints contradict each other and the user has not chosen;
- a safety question is open, or `HIGH` risk lacks a named human reviewer;
- routing is incomplete, or a report is older than the file it describes;
- a manufacturing layer is missing, or the package disagrees with its documentation;
- the remaining work needs physical measurement that only the operator can produce.

Generating further provisional artifacts while blocked adds review burden and
moves no gate. Stopping is the correct engineering action, not a failure.

## Required final report

Every handoff states, in this order:

1. outcome, the exact state label, and the feasibility tier with its driving fact;
2. source revision and SHA-256 of every file the claim depends on;
3. tool names, versions, and the exact commands run;
4. gate counts, plus every unresolved or excluded finding with its written reason;
5. package contents for the chosen route;
6. visual-inspection and manufacturer-preview status;
7. reviewer name, role, timezone-qualified date, approval status;
8. physical-test status and the single next action.

If any required item is missing, the label is `ENGINEERING_HANDOFF` or `BLOCKED`.
It is never `ORDER_READY`.

## Sandbox honesty

If your execution environment has no KiCad, no EDA, and no manufacturer access,
say so explicitly. Files you author in that state are `AUTHORED_NOT_VERIFIED`
until the operator runs the gate on a machine that has the real tool and the
result is written back. Mark them that way in every message; never let a
plausible-looking artifact imply a verification that did not happen.

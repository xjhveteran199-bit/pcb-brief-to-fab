# Manifest fields, in plain language

The manifest is the one place a controlling number is defined. Every document,
script and report quotes it or derives from it. When something disagrees with the
manifest, fix the something.

Validate with:

```text
python scripts/manifest_check.py <manifest.json> --stage design
python scripts/manifest_check.py <manifest.json> --stage release
```

## `project`

| Field | Meaning |
|---|---|
| `name` | Project name. Used in filenames and reports. |
| `revision` | This board revision, e.g. `RevA`. Bump it whenever you send different copper to a fab. |
| `entry` | `NEW_DESIGN`, `EXISTING_SCHEMATIC`, `EXISTING_BOARD`, or `RELEASE_AUDIT`. |
| `route` | `pcb-only` (bare board) or `pcba` (board with parts soldered). |
| `state` | Current state label. See SKILL.md. Never `ORDER_READY` without a human approval record. |
| `approved_netlist_baseline` | Path to the frozen reviewed XML netlist. Everything later is compared against this. |
| `approved_netlist_sha256` | SHA-256 of that file. If the file changes, the baseline is void. |
| `additional_source_files` | Every non-standard symbol, footprint, 3D model, mechanical drawing or rule file the release depends on. List them individually — a tool will not guess which directories matter. |

## `board`

| Field | Meaning |
|---|---|
| `manufacturer` | Who is making it. `UNKNOWN` is allowed while designing, not at release. |
| `technology` | `rigid_fr4` is the only technology a generic release path can verify. Flex, rigid-flex, metal core, high-frequency laminate → stop at `ENGINEERING_HANDOFF`. |
| `copper_layers` | How many copper layers. |
| `copper_layer_names` | The layer names **in physical order, top first**. Length must equal `copper_layers`. |
| `stackup_role` | What each layer is for, in the same order — e.g. `signal`, `ground_plane`, `power`, `signal`. Length must equal `copper_layers`. |
| `placement_area_mm` | `[width, height]` of the area parts may occupy. |
| `edge_margin_mm` | How far the outline sits outside the placement area, on all four sides. |
| `physical_outline_mm` | **Derived**: `placement_area + 2 × edge_margin`. The checker recomputes it. Two independently typed numbers will eventually disagree; this is how you find out immediately. |
| `thickness_mm` | Finished board thickness. |
| `outer_copper_oz` / `inner_copper_oz` | Copper weight. Inner may be `null` on a 2-layer board. |
| `surface_finish` | e.g. `HASL`, `ENIG`. Affects cost and fine-pitch yield. |
| `soldermask_color` / `silkscreen_color` | Cosmetic, but part of the order form. |
| `product_outline_separate_from_panel` | Keep `true`. A panel rail is removable manufacturing geometry and must never be merged into the product outline. |

## `dfm`

Minimum feature sizes the design must respect. **Do not fill these from memory.**
Open the manufacturer's current capability page, read them, and record where and
when you read them.

| Field | Meaning |
|---|---|
| `source` | URL or document you read the numbers from. |
| `checked_on` | ISO date you read it. Numbers older than a few months should be re-checked. |
| `min_track_mm` / `min_clearance_mm` | Narrowest trace and smallest gap. |
| `min_drill_mm` | Smallest finished hole. The package auditor compares this against the drill file. |
| `via_drill_mm` / `via_pad_mm` | Via geometry your DRC actually enforces — not the value you wish you had used. |
| `copper_to_edge_mm` | Clearance from copper to the board outline. |

## `assembly`

Only meaningful when `route` is `pcba`, but `quantity` always applies.

| Field | Meaning |
|---|---|
| `quantity` | Boards in this order. |
| `sides` | `["Top"]`, `["Bottom"]`, or both. Must be non-empty for `pcba`. |
| `dnp_designators` | Parts on the board that must **not** be fitted. |
| `excluded_designators` | Parts deliberately excluded from contract assembly for a stated reason (fitted later by hand, supplied by you, etc.). Each needs a reason in the decision log. |
| `cpl_units` | `mm` or `in`. State it; do not let the assembler guess. |
| `cpl_origin` | Where the coordinates are measured from, described in words. |

## `special_processes`

A list of strings: controlled impedance, castellated holes, edge plating,
resin-filled vias, gold fingers, blind/buried vias, and so on.

If this list is non-empty, a generic automated release cannot verify the required
extra artifacts. Keep designing, but label the result `ENGINEERING_HANDOFF` and
route it through the manufacturer's specific process review.

## `panel`

`required: true` means there is a panel or process rail. That geometry is separate
from the product outline, always.

## `risk`

`tier` is `LOW`, `MODERATE`, or `HIGH`, with a written `reason`.

Each boolean below it is a specific hazard. **If any is `true`, the tier must be
`HIGH`** — the checker enforces this, because "it's only a small board" is how
lithium chargers end up unreviewed.

## `feasibility`

Who does what on this board. Computed by `scripts/feasibility.py`, not chosen by feel.

| Field | Meaning |
|---|---|
| `tier` | `AGENT_AUTONOMOUS` (agent runs the whole workflow; you inspect the package and order), `AGENT_LED` (agent does the work, a person signs three checkpoints), or `HUMAN_LED` (an engineer owns topology and critical placement; the agent assists and audits). |
| `assessed_on` | Date the assessment was run. Re-run it whenever a fact changes. |
| `reason` | The specific fact that drove the tier, in plain language. "The board charges a lithium cell" is a reason. "High risk" is not, and the checker rejects it. |
| `factors` | The rubric inputs that are not already in `risk`: `flex_or_rigid_flex`, `rf_antenna_design`, `high_speed_digital`, `rf_module_precertified`, `custom_switching_converter`, `motor_or_inductive_load`, `enclosure_fit_required`, `nonstandard_parts`, `harsh_environment`, `respin_not_acceptable`, plus `peak_current_a` and `component_count_estimate`. |

The checker recomputes the tier from the facts declared in this same manifest —
the `risk` flags, `board.copper_layers`, `project.route`, and `factors` — and
**blocks if the recorded tier disagrees**. The two can never drift apart.

Consequences the checker enforces:

- `risk.tier: HIGH` ⟹ `feasibility.tier` must be `HUMAN_LED`.
- `AGENT_LED` or `HUMAN_LED` ⟹ `approvals.topology_review` must be complete before release.
- `HUMAN_LED` ⟹ the state cannot be `RELEASE_CANDIDATE` or `ORDER_READY`; a package the
  agent produced alone is `ENGINEERING_HANDOFF`.

Full rubric and reasoning: `references/07-feasibility-tiers.md`.

## `approvals`

Two records, each needing `reviewer_is_human: true`, a `name`, a `role`, a `date`
including a timezone offset (e.g. `2026-08-02T14:30+08:00`), and `evidence` — a
file path or URL.

- `topology_review` — required before schematic freeze when risk is `HIGH`.
- `package_release_review` — required before ordering, and it records the exact
  `package_sha256` that was approved.

This is traceability, not identity authentication. It exists so that a year later
you can find out who said yes and what they were looking at.

## `waivers`

A list of knowingly accepted risks. Each entry states what is waived, what is
explicitly **not** waived, who authorised it, when, and the accepted consequence.

A waiver is never evidence. It may not be cited as though the waived input existed.

## `unknowns`

Each entry: `item`, `why` it matters, `owner` who can resolve it, `interim` what
the design does meanwhile.

Must be empty at `--stage release`. That is the entire point of writing them down.

## `gates`

Allowed counts at the final routing gate. Leave all three at `0`. Raising one is a
recorded decision with a reviewer, not a convenience.

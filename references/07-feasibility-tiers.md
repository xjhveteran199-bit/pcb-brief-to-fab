# Feasibility tiers: how much of this board can an agent actually do?

Run this immediately after intake, before the manifest and before any design
work. The answer changes who does what for the rest of the project.

The tier is an estimate of **division of labour**, not of difficulty for its own
sake. It answers one question: *where must a qualified human be in the loop for
this specific board?*

## The three tiers

### `AGENT_AUTONOMOUS` — the agent carries it end to end

The agent goes from the brief to a `RELEASE_CANDIDATE` fabrication package with
no engineer making design decisions.

The human still does exactly two things, and they are not optional:

1. open the Gerber/drill package in a viewer or the manufacturer's upload preview
   and look at it;
2. place the order.

`ORDER_READY` still requires a named human approving the exact package hash. An
autonomous tier removes the *engineer from the design loop*; it does not remove
the human from the release. Nothing in this skill can set `ORDER_READY` alone.

Typical: a USB-powered sensor or logger board, 2 layers, under an amp, digital
plus low-speed analog, every part available with a verified library footprint,
and a respin the user is willing to accept.

### `AGENT_LED` — agent does the work, human signs three checkpoints

The agent still does all of the drawing, placement, routing, and packaging. A
person who understands hardware must look at it, and record that they did, at
three points:

1. **before the topology freezes** — power tree, part choices, fault behaviour;
2. **before placement is locked** — mechanical anchors, connector mating
   directions, converter sub-layouts, antenna keepout;
3. **before release** — the package, against the manifest.

The review is recorded in `approvals.topology_review` with a name, a role, a
timezone-qualified date, and an evidence file. An agent ticking its own checkbox
is not a review, and `manifest_check.py --stage release` blocks without it.

Typical: battery-powered without on-board charging; a pre-certified radio module;
a switching converter you are designing rather than copying; 4 layers; PCBA;
a board that must fit an existing enclosure.

### `HUMAN_LED` — engineer designs, agent assists

A qualified engineer owns the topology and the critical placement. The agent is
still doing real work — and often most of the hours — but not the decisions:

- turn the brief into a reviewable requirement set and manifest;
- verify every part against its primary datasheet and record the evidence;
- generate and regenerate files deterministically;
- run ERC/DRC/netlist parity and report honestly;
- prove a readability edit did not change the circuit;
- audit the fabrication package independently;
- write the decision log, the gate reports, and the handoff.

Any package the agent produces alone in this tier is labelled
`ENGINEERING_HANDOFF`, never a release.

Typical: anything touching a person, lithium charging, mains, high energy, a
safety function, controlled impedance, HDI/BGA, flex, RF antenna design, or
high-speed digital.

## The rubric

Deterministic, so two runs on the same answers give the same tier. Implemented in
`scripts/feasibility.py`; this file is the reasoning behind it.

### Hard gates → `HUMAN_LED`

Any one of these, on its own:

| Gate | Why it is a hard gate |
|---|---|
| Human or animal body contact | Leakage current and failure modes reach a person. |
| On-board battery charging | Charging faults are a fire mode, not a bug. |
| Mains voltage | Creepage, clearance, isolation and certification are legal requirements. |
| High stored energy | A capacitor bank or a big cell fails energetically. |
| Safety function (medical, vehicle, flight, industrial) | Somebody's process safety depends on it. |
| Controlled impedance | The number comes from the stack-up the fab actually builds, not from the design file. |
| HDI, blind/buried vias, fine-pitch BGA | Manufacturability is decided by the fab's process window. |
| Flex or rigid-flex | Bend radius, stiffener and coverlay design are their own discipline. |
| RF antenna design (not a pre-certified module) | Needs measurement equipment and, usually, certification. |
| High-speed digital (beyond USB 2.0 full speed) | Drags in controlled impedance and return-path design. |
| Peak current ≥ 10 A | Copper, thermals, and connectors all become the design. |
| ≥ 6 copper layers | Stack-up and impedance planning become the design. |

These are the same hazards that force `risk.tier = HIGH` in the manifest. The two
must agree; `manifest_check.py` blocks if they do not.

### Escalators → at least `AGENT_LED`

| Escalator | Why |
|---|---|
| Pre-certified RF module | The module's antenna end and its keepout must reach the board edge, correctly oriented. Placing one at its library rotation put the antenna facing into the board on a real project. |
| Switching converter designed from scratch | Inductor, both bulk capacitors and the feedback divider are a hand-drawn sub-layout. A packer produced 9–11 mm switch-pin loops on a real project. |
| Motor, relay, solenoid or other inductive load | Inrush, flyback and ground bounce. |
| 4 copper layers | Stack-up and return-path choices start to matter. |
| PCBA route | Rotation convention, origin and unit errors fit parts backwards, and files cannot prove otherwise. |
| Must fit an existing enclosure | Mechanical mating is measured, not asserted. A USB-C mouth facing the board interior scrapped a real board. |
| Parts with no verified footprint | Authoring a land pattern from a drawing is a known scrap source. |
| Peak current ≥ 3 A | Copper width, thermal relief and connector rating all need checking. |
| More than 150 components | Volume of review, not risk. |
| Harsh environment (outdoor, moisture, chemicals, vibration) | Conformal coating, sealing and contamination control. |
| A respin is *not* acceptable | You cannot afford to be wrong once, so a human checks. |

### Everything else → `AGENT_AUTONOMOUS`

No hard gate, no escalator. The agent runs the whole workflow and the human
inspects the package and orders.

## Rules about the tier itself

1. **Re-assess when a fact changes.** Adding a battery charger mid-project moves
   the tier to `HUMAN_LED` and invalidates the plan you had. Say so immediately.
2. **The tier may rise silently; it may not fall silently.** Escalation is just an
   honest re-read of the facts. De-escalation is a decision with a written reason
   and — above `AGENT_AUTONOMOUS` — a named person.
3. **The tier is not permission.** `AGENT_AUTONOMOUS` does not authorise skipping
   a gate, a datasheet check, or the Gerber visual inspection. It says nobody
   *else* has to make design decisions; it does not say the checks go away.
4. **State the tier and its drivers in the first reply after intake**, in plain
   language, with the specific fact that drove it. "HUMAN_LED, because the board
   charges a lithium cell" is useful. "HUMAN_LED (high risk)" is not.
5. **When the user disagrees with a hard gate**, do not argue about the tier —
   explain the specific failure mode, offer the design change that removes it
   (an external certified charger instead of an on-board one; a pre-certified
   module instead of a chip antenna), and let them choose.

## What the tier does not tell you

It does not estimate hours, cost, or the probability that the board works. It is
a routing decision about human attention, computed from what the user told you.
If the intake answers are wrong, so is the tier — which is why the drivers are
printed, not just the verdict.

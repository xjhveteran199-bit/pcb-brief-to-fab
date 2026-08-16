# Placement and routing

## Why placement is not a packing problem

An automatic packer optimises whatever metric you gave it. It does not know that a
connector has a mouth, that an antenna has a direction, or that a capacitor exists
only because it must be close to one specific pin. Four real defects from one
board, all of which routing could not have repaired:

**The radio module was placed at its library rotation.** The antenna end of that
module is the pad-free end carrying an all-copper-layer keepout. At rotation 0 the
antenna pointed *into* the board, while the declared antenna keepout region sat
13 mm away at the opposite end, empty. Inside the module's real keepout were a
through-hole shield tab, the buck-boost feedback divider, and another resistor.

**The USB-C connector's mouth faced the board interior.** Its footprint carries a
"PCB Edge" fiducial on a drawing layer; that fiducial landed 24 mm from any board
edge. No cable could ever be inserted. The battery connector had the same defect.

**The switching converter was packed, not designed.** Inductor 9.0 and 11.6 mm from
the two switch pins, the only output capacitor on the opposite face 7.9 mm away,
and the feedback divider's bottom leg 21.3 mm from the FB pin.

**Bypass capacitors sat 5–20 mm from the pins they bypass**, including capacitors
on internal-regulator outputs, which are loop-stability components, not decoupling.

### The rules that follow

1. **Anchor mechanically-constrained parts by absolute coordinate and rotation,
   before anything else runs.** Connectors with a mating direction, antennas,
   mounting holes, sensors, buttons, displays, board-edge features.
2. **Read the footprint, not the part name.** Find the fiducial, the keepout
   polygon, the courtyard, the fab outline notch that marks a connector's mouth,
   and the exposed pad. Then verify after generation that the placed geometry
   matches the intent — the module keepout must actually abut the region keepout.
3. **A hard pin is hard.** If the placer cannot satisfy an anchor it fails. It never
   "works around" a mechanical constraint.
4. **Hand-design the switching-converter sub-layout.** Input capacitor, inductor,
   output capacitor, feedback divider, and the ground return, as one drawn block.
   Leave deliberate clear space around each device so pin-bound passives can nest
   against their pins instead of queueing for leftovers.
5. **Bind every decoupling capacitor to its pin** as an explicit constraint, and
   check the achieved distance afterwards. Distances are measured and recorded, not
   asserted.
6. **Check corridors.** In one case the corridor between a charger IC's pin column
   and a connector's courtyard was 2.84 mm — 0.06 mm narrower than an 0603
   courtyard — so six programming resistors were pushed 8+ mm away. Moving the IC
   2 mm widened it to 4.8 mm and every resistor landed next to its pin.
7. **Place ESD protection at the inlet.** A TVS placed 21 mm downstream of the
   connector *and behind the series fuse* protects nothing.
8. **Two identical parts doing the same job belong on the same face,** next to the
   thing they serve. Split-face placement of a differential or symmetric pair is a
   defect, not a trade-off.
9. **Where a placement is at its floor and cannot improve, say so and flag it for
   the next revision** rather than describing the floor as a good number.

## Area feasibility — measure before promising a size

Compute required area from **courtyards**, not pad extents. Using pad extents
underestimated the requirement by 76 % in one project and produced a board target
that needed 122–140 % packing density — physically impossible, discovered only
after the layout failed.

If a dimension is fixed by a component (a connector body sets the minimum width),
say which component and what its body and courtyard measure. Then treat the other
dimension as the free variable.

Keep the product outline separate from any panel rail or SMT carrier. A rail is
removable manufacturing geometry; merging it into the product outline permanently
corrupts the board size.

## Routing order

Route by risk, and lock each class as you finish it:

1. high current and switching hot loops;
2. high-impedance and guarded inputs (short, on an outer layer, via-free where the
   design demands it — a generic ground guard is not a substitute for a driven guard);
3. clocks, crystals, RF feed and antenna geometry;
4. differential and controlled-impedance pairs;
5. feedback and reference nets;
6. safety-critical control lines;
7. ordinary digital and low-risk nets.

Keep a continuous return path. A solid ground plane stays solid; do not split it
because a diagram somewhere suggested separate analog and digital grounds. On a
mixed-signal board, an intact reference plane is worth more than a clever split.

Refill zones before every final DRC. Route first, pour last: pouring copper before
routing steals the inner-layer area the router needs.

## Autorouting: what it is actually worth

Measured on one real 4-layer mixed-signal board, 282 connections after plane
restoration:

| | Off-the-shelf autorouter | Purpose-built router with explicit rules |
|---|---|---|
| Completion | ~168/282 at best, **could not save the result** (optimiser crashed/reverted) | 163/282, saved and reproducible |
| Inner-layer use | almost zero — a 4-layer board routed as if 2-layer | inner layer carried ~25 % of segments |
| DRC | never reached a verifiable state | 7 violations, each individually explainable |
| Critical-net constraints | could not express "outer layer only, no vias" | encoded as a hard rule |

Practical notes from that experiment:

- Use a modest number of optimisation passes with multithreading. Very high pass
  counts ground for tens of minutes, repeatedly reverted, and then failed to save.
- Single-threaded mode threw index and null-pointer exceptions in the maze search.
- The main reason an autorouter fails on a multi-layer board is usually that it is
  not using the inner layers, not that space is insufficient.
- A router's own report of success is not evidence. In one round the router
  reported 218 connections routed while the real DRC found 883 violations, because
  the via model only checked the via centre point rather than the whole barrel
  across all layers.
- Reconcile the router's accounting against the EDA's, net by net. In the final
  round: 145 unconnected = 119 genuinely unrouted + 29 legitimate large copper
  islands − 3 accounting differences from the EDA re-pairing its minimum spanning
  tree. Only that reconciliation proves there are no dangling traces.

**Never convert a routed percentage into a release claim.** 58 % routed is a
baseline for an engineer to continue from — a legitimate `ENGINEERING_HANDOFF` —
and nothing more.

## Handing off a partially routed board

Package: the openable EDA project, an explicit list of what is *not* routed, the
DRC report, rendered images per layer, the critical-net constraints that must be
preserved, and a one-page "read this first" stating exactly what is unfinished and
what question you want answered.

Anchor the SHA-256 of the untouched original before running any experiment on a
copy, and re-verify it afterwards. Then you can state — and prove — that the
engineer's board was never modified.

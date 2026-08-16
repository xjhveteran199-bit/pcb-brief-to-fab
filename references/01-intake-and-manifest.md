# Intake: turning a plain-language brief into a manifest

The user may not be an electronics engineer. Your job is to ask the smallest set
of questions whose answers change the board, explain each one in plain language,
and write down everything nobody knows yet.

## What to ask, and why it matters

**Purpose and quantity.** One sentence: what does the board do, and how many do
you need? Quantity drives the assembly route and part choices far more than
people expect.

**Power source.** USB, battery, wall adapter, or an existing rail. Ask for the
voltage and the worst-case current. If the answer is a lithium battery, the risk
tier is at least `HIGH` for the charging path — say so immediately.

**Interfaces and loads.** Every sensor, display, motor, relay, radio, connector,
and cable. For each: voltage, current, and whether it moves, heats, or touches a
person. A motor or a relay makes the board a different design.

**Mechanics.** Maximum length × width × height, mounting holes, which connectors
must reach an edge and which direction the cable comes from, and whether the board
goes in an existing enclosure. Connector mating direction is a top-3 source of
scrap boards — ask for it explicitly, not "there is a USB port".

**Environment.** Indoor or outdoor, temperature range, moisture, vibration,
chemicals, human contact.

**Route.** Bare board only (`pcb-only`) or board with parts soldered (`pcba`).
If they do not know: `pcb-only` is cheaper and slower to bring up; `pcba` costs
more and requires the BOM/CPL work to be correct.

**Manufacturer and budget.** Which fab, and roughly what the board may cost. If
undecided, record `UNKNOWN` and do not silently assume anyone's capability limits.

**Existing material.** Do they already have a schematic, a KiCad project, a
datasheet set, a mechanical drawing, a previous revision, or a Gerber archive?
Hash whatever they give you before touching it.

**Deadline and risk appetite.** A prototype the user is willing to respin is a
different design from a board that must work the first time.

## Unknowns

Write each unknown as a row: what is unknown, why it matters, who can resolve it,
and what the design does in the meantime. An unknown that stays in the manifest at
release stage blocks the release. That is the point.

Never fill an unknown with a plausible number. The three that cause real damage:

- **electrical ratings** taken from memory instead of the datasheet;
- **land patterns / footprints** inferred from a part name;
- **manufacturer capability minimums** remembered from a previous project.

## Manifest discipline

The manifest is the only place a controlling number is defined. Everything else
quotes it.

- **Derive, do not restate.** If the outline equals the placement area grown by the
  edge margin, store the placement area and the margin, and let the checker derive
  the outline. Two independently-typed numbers will eventually disagree.
- **One anchor, no rescaling.** If regions are authored against a reference length,
  make that reference equal the real length so the scale factor is exactly 1.0.
  A floorplan silently stretched from a different reference length is a floorplan
  nobody drew.
- **Hard pins are hard.** A mechanically-fixed part has absolute coordinates and a
  rotation. If a placer cannot satisfy them, it fails — it does not "work around"
  them and quietly move a connector inboard.
- **Every constraint carries a `why`.** A number without a reason cannot be
  reviewed, and will be changed by the next person who finds it inconvenient.
- **Record supersessions in place.** When a value changes, keep the previous value,
  the date, the authority who decided, and the rationale. This is how you avoid
  arguing with your own old documents.
- **Ban silent defaults.** A checker that substitutes a generic default for a
  missing field converts an unknown into a fact. Fail instead.

## Choosing the risk tier honestly

Anything in this list makes the design `HIGH` risk, regardless of how small the
board is: contact with a human or animal body, lithium charging, mains voltage,
stored energy that can start a fire, a medical/vehicle/flight/industrial-safety
function, controlled impedance, HDI or fine-pitch BGA.

`HIGH` risk does not mean stop. It means the topology cannot freeze until a named,
qualified human has reviewed it, and that review is recorded with a name, a role,
a timezone-qualified date, and an evidence file or URL.

## Waivers

A user may knowingly accept a risk — for example, ordering a characterization
board before the measurements that would normally justify its component values
exist. That is legitimate, and it is recorded as a **waiver** in the manifest:
what is waived, what is explicitly not waived, who authorized it, when, and the
accepted consequence (usually "a respin is expected").

A waiver is a risk acceptance. It is never evidence, and it must never be cited as
though the waived input existed.

# Fabrication package and DFM

## Generate everything from one source hash, in one run

Gerber, drill, paste, BOM, and CPL must all come from the same schematic/board
hash, produced in a single run, with the tool version recorded. Hash the sources
before and after the export and confirm they are identical — otherwise you cannot
say which board the package describes.

A package assembled from files exported on different days is not a package. It is
a folder.

## What belongs in the package

**`pcb-only`**

- one copper layer file per copper layer, in a stated order;
- top and bottom soldermask;
- top and bottom silkscreen (as designed — omit deliberately if there is none);
- exactly one board-outline layer;
- drill files (plated and non-plated as your tool separates them) plus a drill map;
- a `.gbrjob` or equivalent job file if your tool emits one;
- fabrication notes: material, layer count, finished thickness, copper weights,
  surface finish, mask and silkscreen colour, minimum track/clearance/hole,
  electrical test, and any special process;
- evidence of a visual inspection.

**`pcba` adds**

- top and/or bottom paste layers for the assembled sides;
- an assembly BOM with quantity, designators, value/description, footprint,
  manufacturer, MPN, and supplier part number;
- a CPL / pick-and-place file with designator, X, Y, rotation, side — with the
  units and origin stated explicitly;
- an explicit DNP / do-not-fit list;
- tooling holes and fiducials if the assembler requires them;
- a polarity and rotation review for every polarised part.

## What must not be in the package

Non-manufacturing layers leak in constantly because EDA tools export everything by
default. Courtyard, Fab, Margin, User, Dwgs, Eco, 3D-model, and adhesive layers are
not manufacturing data. A fab house either ignores them or — worse — asks, delays
the order, or guesses.

Paste layers in a `pcb-only` package are a contradiction: either you are ordering
assembly or you are not.

Multiple outline layers are a real hazard. Send exactly one.

Real audit result from one historical package: 23 files, of which 10 were
unidentified auxiliary/engineering files and 7 were explicitly non-manufacturing
layers, and the `.gbrjob` recorded a 31.1 × 88.1 mm outline while the handoff
document said 38 × 90 mm. That size disagreement alone is a blocking finding: a
package whose metadata contradicts its own documentation cannot be ordered.

## Layer naming

Two common conventions. Accept both; state which one you used.

**KiCad default (Protel-ish extensions):** `.gtl` `.g1`/`.g2`/`.in1.gbr` … `.gbl`
for copper; `.gts`/`.gbs` mask; `.gto`/`.gbo` silkscreen; `.gtp`/`.gbp` paste;
`.gm1` or `Edge_Cuts.gbr` outline; `.drl` drill.

**JLCPCB's recommended naming** (from their current Gerber preparation article):
`.GTL` top copper, `.G2L`/`.G3L`… inner copper, `.GBL` bottom copper,
`.GTS`/`.GBS` soldermask, `.GTO`/`.GBO` silkscreen, `.XLN` drills,
`.GKO` or `GM1` board outline. They ask for exactly one outline layer and for any
extra layer (resin-filled via `sk` layer, stiffener, heatsink pad) to be explained
in the order remarks — otherwise it may be ignored.

Source: <https://jlcpcb.com/help/article/gerber-files-preparation> — re-read it on
the day you order; manufacturer instructions change.

## DFM parameters to fix before export

All of these belong in the manifest, and none of them may be a silent default:

- manufacturer and service (bare board vs assembly, standard vs economic);
- quantity;
- copper layer count **and explicit layer order**;
- finished thickness;
- outer and inner copper weight;
- surface finish;
- soldermask and silkscreen colour;
- minimum track width, minimum clearance, minimum drill, via drill and pad;
- copper-to-board-edge clearance;
- assembled side(s);
- panel/rail requirement — and if there is one, it is separate geometry, never
  merged into the product outline;
- special processes: controlled impedance, castellated holes, edge plating,
  resin-filled vias, gold fingers, flex/rigid-flex.

If your design needs a special process, a generic release path cannot verify it.
Design it, then stop at `ENGINEERING_HANDOFF` and route it through the
manufacturer's specific process review.

## Checking capability

Never quote a capability limit from memory or from a previous project. Open the
manufacturer's current capability page and the DFM tool on the day you order, and
record what you read with the date.

For assembly, also re-check live part availability and the assembler's library
mapping. A part that was in stock last month is a stop-ship this month.

## BOM and CPL correctness

The failure modes are boring and expensive:

- a designator in the BOM but not the CPL, or vice versa;
- DNP parts leaking into the fitted set;
- CPL units in mils while the form says mm;
- an origin that is not the one the assembler expects;
- rotations that follow the EDA's convention rather than the assembler's — this is
  the single most common cause of parts fitted backwards;
- missing manufacturer/MPN/supplier fields, so the assembler substitutes;
- polarised parts with no polarity marking on the silkscreen.

Derive the expected fitted set from the netlist plus the DNP policy, then check the
BOM and CPL against that derived set — not against each other only. Two files can
agree with each other and both be wrong.

## Visual inspection is mandatory

A structural audit proves the files exist, parse, and are internally consistent. It
does not prove the copper is right. Open the package in an independent Gerber
viewer or the manufacturer's upload preview and look at:

outline closure and dimensions; layer order and count; plated vs non-plated holes;
slots; copper on every layer; mask openings, especially on fine-pitch and exposed
pads; paste apertures; silkscreen legibility and no silk on pads; plane fills and
thermal reliefs; antenna and board-edge features; connector orientation relative to
the edge; panel rails and tooling holes if present.

Write down what you inspected. "Looked fine" is not an inspection record.

## Ordering

Order a small prototype quantity first. Choose the option that lets the fab contact
you about production-file questions rather than silently deciding for you. Keep the
package SHA-256 with the order number, so that when the boards arrive you know
exactly which files made them.

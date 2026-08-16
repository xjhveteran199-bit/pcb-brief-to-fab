# KiCad: measured facts, not remembered ones

Everything in this file was established by running the real tool and reading its
output. Where a fact is version-specific it says so. If you need to know how KiCad
behaves in a case not covered here, **build a probe**: author a small project where
each candidate construction is its own net, export the netlist, and read the answer.
Do not guess, and do not let a plausible model stand in for a measurement.

## Connectivity: junctions do not connect

Measured on KiCad 9.0.x by exporting a netlist from a probe sheet where every
construction sat on its own net:

| Construction | Connected? |
|---|---|
| Pin at a wire **endpoint** | **yes** (also when the wire is perpendicular to the pin direction) |
| Pin on the **middle** of a wire, with a junction dot | **no** |
| Two mid-wire taps on one long wire | **neither** connects |
| Wire **split** at the tap point | **yes** (with or without a junction dot) |
| Net label on a wire, mid-segment or endpoint | yes, both |
| Power symbol on a pin, or at the end of a stub | yes, both |

**Consequence for any generator: split the wire at every tap** — do not rely on a
junction to make the connection. Still draw the junction dot, because a human
reader cannot otherwise distinguish a T-connection from a crossing.

This is the single most expensive lesson in this file. A connectivity model that
treated junctions as connections reported PASS in a sandbox while the real KiCad
export was missing 15 nodes.

## Other measured KiCad facts

- **Property text angle is relative to the component.** Rendered angle = parent
  angle + field angle. Writing `angle 0` on a part rotated 270° renders the text
  vertically, and the reference designator stacks on top of the value. Compensate.
- **Power symbols do not appear in the exported netlist.** Replacing a net label
  with a power symbol therefore does not change the node count — no exemption
  switch is needed when comparing netlists.
- **A missing power-symbol definition crashes ERC** (observed return code
  0xC0000005 — a crash, not an error message). Hide the pin name with `(name "~")`
  plus `(pin_numbers (hide yes))` and `(pin_names (offset 0) (hide yes))`.
- **`PWR_FLAG` (`#FLG*`) is not in the netlist.** A generator driven purely by the
  netlist will skip it entirely. Losing its label makes the whole rail report
  `power_pin_not_driven` in ERC.
- **`lib_symbols` embedded in a `.kicad_sch` must match the on-disk library.**
  If they diverge you get `lib_symbol_mismatch`. Generate both in the same pass.

## Parsing `.kicad_sch` and `.kicad_pcb`

**Never parse with regular expressions.** The classic failure:
`re.search(r'\(property\s+"Reference".*?\)\)', text, re.S)` matches "up to the
first adjacent pair of closing parens", but the file is indented across newlines,
so `))` never appears — the match silently returns `None` and the record is
skipped. In one run this silently processed 92 of 180 footprints; it was only
caught because DRC produced 161 silkscreen warnings.

Use a **paren-matching block reader**: scan for the token, then walk forward
counting depth, respecting quoted strings and escapes. Return the exact block.
Write it once, put it in a shared module, and never open-code it again.

Compute pin absolute coordinates properly: symbol position, then rotation, then
mirror, then the pin's local offset. Getting this wrong produces a connectivity
model that disagrees with KiCad and you will trust it because it is your own code.

## `kicad-cli`

The CLI is normally **not on `PATH`**. On Windows it lives at
`C:\Program Files\KiCad\9.0\bin\kicad-cli.exe`, and KiCad ships its own Python at
`C:\Program Files\KiCad\9.0\bin\python.exe` which has `pcbnew` available. Use that
interpreter for any script importing `pcbnew`.

Security: only accept a CLI from a standard installation directory, and record its
SHA-256 in the evidence. A binary named `kicad-cli` found inside the project
directory must be refused — otherwise "run the gate" becomes an arbitrary code
execution primitive.

Useful subcommands (check `--help` on your version; do not assume flags):

```text
kicad-cli version
kicad-cli sch erc      <sch> --output <report.json> --format json --severity-error --severity-warning
kicad-cli sch export netlist <sch> --output <net.xml> --format kicadxml
kicad-cli sch export bom     <sch> --output <bom.csv>
kicad-cli sch export pdf     <sch> --output <sch.pdf>
kicad-cli pcb drc      <pcb> --output <drc.json> --format json --schematic-parity --severity-error --severity-warning
kicad-cli pcb export gerbers <pcb> --output <dir>
kicad-cli pcb export drill   <pcb> --output <dir>
kicad-cli pcb export pos     <pcb> --output <cpl.csv> --format csv --units mm
```

Read the DRC JSON properly. It reports **violations**, **unconnected_items**, and
**schematic_parity** as three separate lists. All three must be zero at the final
routing gate. A script that only counts `violations` will report a clean board that
has 400 unrouted connections.

## Readability review

Two different questions, two different methods:

1. **"Do objects overlap in the source file?"** — compute overlap boxes directly
   from the source geometry (body, pin names, pin numbers, reference, value,
   labels, notes). This is a fact about the file.
2. **"Does it look right?"** — export a real PDF with `kicad-cli`, rasterise it,
   and look at every page. An approximate in-sandbox renderer only catches gross
   errors; its glyph widths are estimates.

**Do not extract text from the KiCad PDF to count overlaps.** KiCad embeds both a
searchable text layer and vector-stroked glyphs, and CJK text is UTF-16 — a naive
extraction produced 1005 phantom overlaps in one run.

## Idempotency

A transformation that reads the *pre-transform* state to reconstruct something
(for example, recovering `PWR_FLAG` connections from the labels that existed
before) is **not idempotent**. Running it twice destroys the thing it recovered.
Mark such scripts loudly, and restore the pre-transform version before re-running.

Prefer writing generators that are idempotent by construction: clear the generated
artifact first, then write it fresh.

## What "the schematic is human-readable" means

An external routing engineer rejected a schematic twice with "I can't read this".
The root cause, in their words: every section had been given its own independent
net labels, so what should have been a direct connection had to be traced through
name matching across seven pages. The file passed ERC perfectly.

Concretely, for a schematic a human will hand off:

- draw wires for local connections; reserve net labels for genuinely global signals;
- give each functional block a box and a text label; split a page that is too dense
  rather than shrinking everything;
- put the decoupling capacitor next to its pin, matching the PCB;
- mark unused pins with an explicit no-connect symbol;
- fill in the title block and revision.

"Passes ERC" and "a human can read it" are independent properties. The success
criterion for a handoff is the engineer understanding it, not the script being green.

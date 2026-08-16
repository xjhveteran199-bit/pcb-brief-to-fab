# pcb-brief-to-fab

A Claude skill that turns a plain-language hardware brief into a traceable engineering
candidate — and, only after every gate passes on the exact file hashes, into a
fabrication package.

The value of this skill is not speed. It is that every claim is bound to a named tool,
a named file hash, and a timestamp, and that the run refuses to advance when the
evidence does not exist.

## Two rules that override everything else

1. **A green check is not correctness.** A gate proves that one named tool found zero
   blocking findings in one named file. It does not prove the topology, the ratings,
   the thermals, the EMC behaviour, the safety, or that the board works.
2. **A hardcoded assumption is not a measurement.** Never write a check whose answer
   comes from a literal you typed. Build a controlled probe, run the real tool, and
   read the answer out of its output.

## What it covers

Requirement intake → machine-readable constraint manifest → schematic capture →
placement → routing → ERC / DRC / netlist-parity gates → Gerber, drill, BOM and CPL
fabrication package, with hash-bound evidence at every step.

Routes: `pcb-only` (bare board) and `pcba` (assembly). Risk tiers `LOW` / `MODERATE` /
`HIGH` drive where a qualified human must sign.

## Layout

```
SKILL.md                      Entry point and workflow
references/                   Load-on-demand reference material
  01-intake-and-manifest.md
  02-gates.md
  03-kicad-facts.md
  04-placement-and-routing.md
  05-fab-package.md
  06-antipatterns.md
  07-feasibility-tiers.md
assets/                       Templates: manifest, intake, decision log, gate report
examples/                     A filled, passing manifest and feasibility answers
scripts/                      Verification tooling (Python 3, stdlib only)
  selftest.py                 Proves the bundled scripts behave as documented
  manifest_check.py           Validates the constraint manifest per stage
  feasibility.py              Computes the feasibility tier from intake answers
  netlist_parity.py           Semantic netlist comparison (not a text diff)
  kicad_gate.py               Hash-binding runner around kicad-cli
  fab_audit.py                Independent audit of a fabrication package
```

## Install

Copy the directory into your skills folder:

```
~/.claude/skills/pcb-brief-to-fab        # macOS / Linux
%USERPROFILE%\.claude\skills\pcb-brief-to-fab   # Windows
```

## Verify the scripts run in your environment

```
python scripts/selftest.py
```

All five checks must report PASS. That proves the scripts behave as documented on
synthetic inputs, including their refusals. It does **not** prove KiCad is installed
or that its CLI flags match your version — check that separately:

```
kicad-cli version
kicad-cli --help
```

## State labels

| Label | Meaning |
|---|---|
| `DRAFT` | Requirements or design are still moving. |
| `AUTHORED_NOT_VERIFIED` | Files exist. The declared tool has not run on these hashes. |
| `TOOL_VERIFIED` | The named tool ran on the named hash; blocking findings are zero. |
| `ENGINEERING_HANDOFF` | Deliberately incomplete, packaged for a qualified engineer. Not orderable. |
| `RELEASE_CANDIDATE` | All tool gates and the package audit passed. Human and fab review pending. |
| `ORDER_READY` | A named qualified reviewer approved the exact package SHA-256, and the manufacturer's current DFM preview shows no unresolved blocker. |
| `BLOCKED` | A gate failed, or required physical/human evidence does not exist. |

`ORDER_READY` is never set by the skill on its own authority.

## Scope and limits

This skill does not assert safety, compliance, certification, or functional
correctness. Those require tool evidence **plus** a named qualified human review, and
for anything involving mains, lithium charging, human contact, or a safety function,
that review happens before the schematic freezes.

Requires Python 3 for the scripts and KiCad (with `kicad-cli`) for the ERC/DRC and
export gates.

## License

MIT — see [LICENSE](LICENSE).

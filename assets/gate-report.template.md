# Gate report — <project> <revision> — <gate id>

## Verdict

- **State label**: `DRAFT` | `AUTHORED_NOT_VERIFIED` | `TOOL_VERIFIED` | `ENGINEERING_HANDOFF` | `RELEASE_CANDIDATE` | `ORDER_READY` | `BLOCKED`
- **Gate**: G0 … G9
- **Run at**: <ISO-8601 with timezone>

## Inputs, bound by hash

| File | SHA-256 |
|---|---|
| <schematic> | |
| <board> | |
| <manifest> | |
| <baseline netlist> | |

If any of these hashes change, this report is void. Do not quote it.

## Tools

| Tool | Version | SHA-256 of executable |
|---|---|---|
| | | |

## Commands actually run

```text
<exact argv, one per line>
```

## Results

| Check | Count | Threshold | Pass? |
|---|---:|---:|---|
| ERC errors | | 0 | |
| ERC warnings | | | |
| DRC violations | | 0 | |
| Unconnected items | | 0 | |
| Schematic parity differences | | 0 | |
| Netlist parity vs baseline | | equivalent | |
| Package audit blocking findings | | 0 | |

## Unresolved and excluded findings

| ID | Description | Why it is excluded / unresolved | Reviewer | Date |
|---|---|---|---|---|
| | | | | |

Zero-by-exclusion is not zero. Every row here is a decision someone owns.

## What this report does NOT prove

- that the topology is correct;
- that component ratings, thermals, or EMC behaviour are adequate;
- that the outline is closed, copper is electrically correct, or holes align;
- that the board is safe or compliant;
- that it will work.

## Human review

- Reviewer name / role:
- Reviewer is a human: yes / no
- Date with timezone:
- Evidence file or URL:
- Approved package SHA-256 (release gate only):

## Manufacturer preview

- Manufacturer and service:
- Preview run on (date):
- Unresolved blockers:

## Next action

<one sentence, one owner>

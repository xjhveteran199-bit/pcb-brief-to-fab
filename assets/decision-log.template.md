# Decision log — <project> <revision>

Append-only. Never edit a past entry; supersede it with a new one that references it.

## How to write an entry

Every entry answers: what was decided, why, what evidence supports it, what it
costs, and who agreed. An entry with no evidence field is an assumption, and must
say `ASSUMPTION` in the evidence field rather than leaving it blank.

---

## D-001 — <short title>

- **Date**: 2026-01-01T10:00+08:00
- **Decided by**: <name / role>, or `agent-proposed, unconfirmed`
- **Type**: requirement | topology | part | mechanical | manufacturing | risk-acceptance
- **Decision**: <what is now true>
- **Alternatives considered**: <what else, and why not>
- **Evidence**: <datasheet + revision / measurement + file / tool report + hash / `ASSUMPTION`>
- **Cost / consequence**: <money, size, schedule, risk, respin likelihood>
- **Supersedes**: <D-xxx or none>
- **Reversible?**: <yes/no, and until which gate>

---

## Part verification records

One row per critical part. A part with an empty datasheet-revision cell has not
been verified.

| Ref | Function | Exact orderable MPN | Datasheet rev / date | Pin map checked | Ratings + derating checked | Package drawing checked | Exposed pad | Reference circuit followed |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

## Assumption register

Assumptions that are still load-bearing. Each must eventually become a measurement
or an explicit accepted risk.

| # | Assumption | Where it is used | How it would be proven | Status |
|---|---|---|---|---|
| 1 | | | | open |

## Supersession record

| Date | Field / decision | Old value | New value | Authority | Rationale |
|---|---|---|---|---|---|
| | | | | | |

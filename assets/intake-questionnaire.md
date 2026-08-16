# Intake questionnaire

Copy this file into the project and fill it with the user. Any field you cannot
answer becomes a row in the Unknowns table — never a guessed value.

## 1. What and why

- One-sentence purpose:
- Who uses it, and where:
- Quantity for this build:
- Is a respin acceptable, or must this work first time:
- Deadline:

## 2. Power

- Source (USB / battery / adapter / existing rail):
- Nominal voltage, and range if it varies:
- Worst-case current draw:
- Battery chemistry and capacity, if any:
- Does it charge on-board? (if yes → risk tier is at least HIGH)
- Must it run while charging:
- Sleep / standby target, if any:

## 3. Interfaces and loads

One row per item. Add rows as needed.

| Item | Type (sensor / display / motor / radio / connector) | Voltage | Peak current | Touches a person? | Moves or heats? |
|---|---|---|---|---|---|
| | | | | | |

- Wired communication needed (USB / UART / I²C / SPI / CAN / Ethernet):
- Wireless needed (BLE / Wi-Fi / LoRa / other), and is it a certified module:
- Any signal that must be a controlled impedance:

## 4. Mechanics

- Maximum length × width × height:
- Does it go into an existing enclosure? Attach the drawing if so:
- Mounting holes: count, diameter, positions:
- For every connector: which board edge, and which direction does the cable come from:
- Anything that must be visible or reachable (LED, button, port, display window):
- Keep-out zones (antenna, magnet, moving part, heat source):

## 5. Environment

- Indoor / outdoor:
- Temperature range:
- Moisture, immersion, sweat, chemicals:
- Vibration or shock:
- Human or animal contact — skin, mouth, implanted:

## 6. Route and manufacturer

- Bare board only (`pcb-only`) or with parts soldered (`pcba`):
- Target manufacturer, or `UNKNOWN`:
- Budget per board, and total:
- Layer count preference, or "let the design decide":
- Any process you already know you need (impedance, flex, castellated, edge plating,
  gold fingers, resin-filled vias, panel/rails):

## 7. Existing material

- Schematic:
- EDA project files:
- Datasheets:
- Mechanical drawing:
- Previous revision, and what was wrong with it:
- Existing Gerber or BOM/CPL archive:

Hash everything the user supplies before touching it, and record the hashes.

## 8. Risk tier

Tick every one that applies:

- [ ] contact with a human or animal body
- [ ] lithium (or other rechargeable) charging on board
- [ ] mains voltage anywhere
- [ ] stored energy that could start a fire
- [ ] medical, vehicle, flight, or industrial-safety function
- [ ] controlled impedance
- [ ] HDI or fine-pitch BGA

Any tick → risk tier `HIGH` → a named qualified human must review the topology
before the schematic freezes.

Chosen tier: `LOW` / `MODERATE` / `HIGH`
Reason:

## 8b. Feasibility tier — who does what

Answer these, then run `scripts/feasibility.py` and record the result. Do not
decide the tier by feel; the script exists so two runs on the same answers agree.

Additional hard gates beyond the risk ticks above:

- [ ] flex or rigid-flex board
- [ ] an antenna you design, rather than a pre-certified module
- [ ] high-speed digital beyond USB 2.0 full speed

Escalators:

- [ ] a pre-certified radio module
- [ ] a switching converter designed rather than copied from a reference design
- [ ] motor, relay, solenoid or other inductive load
- [ ] must fit existing mechanics / an existing enclosure
- [ ] at least one part has no verified library footprint
- [ ] outdoor, moisture, chemicals or vibration
- [ ] a respin is NOT acceptable

Numbers:

- Peak current (A):
- Estimated component count:
- Copper layers (or "let the design decide"):

Resulting tier (from the script): `AGENT_AUTONOMOUS` / `AGENT_LED` / `HUMAN_LED`
Driving fact, in one sentence:

## 9. Unknowns

| # | What is unknown | Why it matters | Who can resolve it | What we do meanwhile |
|---|---|---|---|---|
| 1 | | | | |

## 10. Confirmation

- Requirement list confirmed by: (name)
- Date (with timezone):
- Entry type: `NEW_DESIGN` / `EXISTING_SCHEMATIC` / `EXISTING_BOARD` / `RELEASE_AUDIT`
- Route: `pcb-only` / `pcba`

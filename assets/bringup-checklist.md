# Bring-up checklist

Nothing before this point says the board works. Run these in order and stop at the
first failure — a failure here feeds back into the manifest and the next revision,
never into a patch on the order form.

Use a **current-limited** bench supply for every powered step. Set the limit just
above the expected current, not at the supply's maximum.

## 0. Before power

- [ ] Compare the delivered board against the fabrication drawing: outline,
      thickness, finish, hole positions, silkscreen legends.
- [ ] Photograph both faces at high resolution, for the record.
- [ ] Inspect under magnification: solder bridges, tombstones, missing parts,
      wrong orientation on every polarised part, exposed-pad wetting.
- [ ] Measure resistance from every supply rail to ground. Note the value.
      A near-zero reading means stop.
- [ ] Confirm the input connector's pinout with a meter, against the schematic.
- [ ] For any battery input: confirm polarity before connecting anything.

## 1. First power-up

- [ ] Current-limited supply, limit set, board on the bench with nothing connected.
- [ ] Apply the minimum input voltage first. Record the current drawn.
- [ ] Compare against the predicted quiescent current from the power budget.
      An order-of-magnitude difference means stop and investigate.
- [ ] Touch-test / thermal-camera for hot spots within the first 30 seconds.

## 2. Rails

- [ ] Measure every rail at its test point. Record actual vs expected.
- [ ] Check ripple on each rail with a scope, probe grounded at the local return.
- [ ] Sweep the input across its full range and confirm every rail stays in spec.
- [ ] Verify the power-up sequence order if the design requires one.

## 3. Reset, safety, and default state

- [ ] Confirm the board's defined safe state at reset, at brownout, and unpowered.
      Anything that could drive a load, apply a bias, or energise something must
      be inactive by default, verified with a meter or a scope — not by reading code.
- [ ] Verify watchdog / brownout thresholds if present.

## 4. Programming and debug

- [ ] Connect the programmer. Confirm the target is detected.
- [ ] Erase and flash a minimal blinky. Confirm it runs.
- [ ] Confirm the debug/serial path works before loading real firmware.

## 5. Interfaces

- [ ] One at a time: each bus, each connector, each sensor.
- [ ] For every bus, confirm pull-ups, levels, and idle state on a scope.
- [ ] For every connector, confirm the mating direction physically works with the
      real cable, in the real enclosure.

## 6. Loads and analog

- [ ] Bring up loads at reduced level first where possible.
- [ ] Verify analog paths against a known reference or dummy load before trusting
      a measurement from the real sensor.
- [ ] Check for interference between the radio, the switching converter, the
      charger, and any sensitive analog path — with each enabled and disabled.

## 7. Thermal and endurance

- [ ] Run at worst-case load and record temperatures at the hot components.
- [ ] Run a long soak and check for drift, resets, or disconnects.

## 8. Record and feed back

- [ ] Write down every measured value, not just pass/fail.
- [ ] File every deviation as a decision-log entry with a proposed fix.
- [ ] Update the manifest for the next revision before you forget why.

## Reminder

Design files cannot prove function, safety, battery life, accuracy, or compliance.
Only measurement can, and only for the boards you actually measured.

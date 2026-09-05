# Edukit assembly

The kit ships no written instructions, only 23 short videos listed in Manual Sec. 1. The videos are also the only source for the encoder wiring. No document in the reference pack says which lead goes where. The sequence that follows runs in step order, each step linked to its video. Links resolved 2026-08-23.

[edukit-firmware.md](edukit-firmware.md) covers flashing and running the firmware.

## Pick a path first

The soldered path runs all 23 steps and needs only what's in the box. The solderless path skips steps 13, 14, 16, 17, and 18, replacing that wiring with a four-station terminal block and male-to-male jumper wires. Neither ships with the kit. Steps 12 and 15 are different videos per path.

## Frame and encoder, steps 1 to 10

Unpack and inventory in steps [1](https://youtu.be/0meOVIx7N1M) and [2](https://youtu.be/gUSe4PwD93I), then count fasteners against [the bill of materials](../design-inputs/bom.md) in step [3](https://youtu.be/Mix6ypv3_9k).

| Fastener | Qty | Use |
|---|---|---|
| M3 x 16 mm pan head, with M3 hex nut | 19 each | General frame assembly |
| M3 x 10 mm pan head | 4 | Motor support |
| M3 x 8 mm pan head | 3 | Rotary encoder |
| M2.5 x 6 mm pan head | 4 | L-bracket |
| M3 x 6 mm set screw | 2 | Shaft couplings |

ST BOM v2 items 6 to 9 and 20 to 22, plus three standoffs and four rubber grommets.

Four vertical struts make the tower in step [4](https://youtu.be/MxSs33k4FxM). Attach the Nucleo platform to the baseplate in step [5](https://youtu.be/FV42xqJDJCU), and the motor mount to the tower in step [6](https://youtu.be/Xr47u1rKld8).

**Measure the rotor arm before step 7.** The equations of motion need the radius the pivot sweeps, not the length of the casting. The manual's 0.14 m in Manual Table 2 is the whole part. The pivot axis sits 25.5 mm inboard, making this unit's moment arm **0.1145 m**. Afterwards the datum hides inside the encoder housing. A caliper there under-reads by about 3.5 mm. [Experiment 03](../experiments/03-hardware-bringup/writeup.md) has the measurement, and `config/edukit.yaml` carries the value.

Fit the encoder bracket onto the shaft coupling in step [7](https://youtu.be/wRVLRFOLsKk), the encoder onto the bracket in step [8](https://youtu.be/tDe5ZhxdriQ), the assembled bracket onto the motor shaft in step [9](https://youtu.be/zsis9pTEHMA), then join the tower to the baseplate in step [10](https://youtu.be/dyKNGgI_p1A).

## Electronics and wiring, steps 11 to 18

Step [11](https://youtu.be/bhhw-CBYqBQ) covers boards and cabling, then the IHM01A1 connections follow in step [12 soldered](https://youtu.be/OKV5AgY-Hvo) or [12 solderless](https://youtu.be/SVQJFX1-22g).

On the soldered path: prepare the connections in step [13](https://youtu.be/VGt_CtmH9E8), identify the motor and power supply leads in step [14](https://youtu.be/HTFj7JiTv_M), prepare the motor leads in step [15](https://youtu.be/3rkMq80rC6Q), then the encoder supply in step [16](https://youtu.be/YWng9TZUr5M) and signal leads in step [17](https://youtu.be/9tuv9Hkhrtw), then the motor and power supply connections in step [18](https://youtu.be/MajljgDs1Hg).

On the solderless path, prepare only the motor leads in step [15 solderless](https://youtu.be/VLsVsyIXWbE), which the video itself titles step 16. Everything lands on the terminal block.

### Encoder leads

Four leads and a braided shield, the same on both paths. The narration in steps 16 and 17 gives the mapping.

| Lead | Connects to |
|---|---|
| Red | 5 V |
| Black | GND |
| White | DIR3 |
| Green | DIR2 |
| Braid | shield, not connected |

White and green land on the inner rail, white first with green immediately adjacent.

The step 17 video title reads `DIR2 DIR2`, a typo. Its narration calls white Direction 3 and green Direction 2.

**DIR2 and DIR3 carry no encoder meaning.** The IHM01A1 stacks up to three boards for three motors. Its header carries a direction line and a step clock per slot: `DIR1/PWM1`, `DIR2/PWM2`, `DIR3/PWM3`. The Edukit drives one motor, marked `SINGLE MOTOR` on the board. The firmware reuses the two spare slots as the encoder's quadrature inputs under their leftover names.

## Final assembly, steps 19 to 23

Stack the IHM01A1 onto the Nucleo in step [19](https://youtu.be/hYXkdnByJaE), dress the cabling there in step [20](https://youtu.be/GMteZB7qzlY), and fit the USB cable in step [21](https://youtu.be/VgMReqATafk).

**Weigh both pendulum parts before step 22.** The tube and the counterweight (ST BOM v2 items 19 and 23) separate only until then. Afterwards the pendulum doesn't leave the pivot without further disassembly. `config/edukit.yaml` carries the mass this unit was built with. Separate weights also bound how far the assembly departs from the manual's uniform-rod model.

Attach the pendulum to the encoder in step [22](https://youtu.be/nXJLYx9tR4M) and the rubber grommets to the baseplate in step [23](https://youtu.be/DJ2Se6L7miM).

## Checks after assembly

**Encoder direction, not just counts.** One channel alone still produces counts. A non-zero reading proves nothing. Direction needs both, and the check is a *signed* angle. Flash the board and run mode `t`. It prompts for a rotation each way.

**Baseplate level.** The unit stands on rubber grommets. Any tilt moves where upright sits as the rotor arm turns. This one measures **0.51 degrees** on a full-circle sweep, small enough to compensate in firmware and large enough that assuming zero is wrong. An earlier half-turn sweep read 0.98 degrees, and [Experiment 03](../experiments/03-hardware-bringup/writeup.md) records both. Firmware mode `y` sweeps the arm and logs the resting angle. That sweep produced the number.

**Geometry against the manual.** Rotor arm and pendulum length both differ on this unit, and neither is measurable now. `config/edukit.yaml` carries the values taken before assembly, and [Experiment 03](../experiments/03-hardware-bringup/writeup.md) describes the method.

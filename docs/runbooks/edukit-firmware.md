# Running the Edukit firmware

Operational documentation covering firmware execution, boot mode capabilities, and serial telemetry protocols. Consult [edukit-assembly.md](edukit-assembly.md) for mechanical assembly and encoder wiring details.

## Flashing

Configuration file `config/firmware.yaml` defines every binary image available for flashing via `just hw-flash`. To add custom firmware targets, append the corresponding path and description to `config/firmware.yaml`.

```bash
just hw-targets  # list the declared targets
just hw-flash  # write the default target
just hw-flash bench  # write a named target
just hw-flash bench --force  # write even when the firmware already matches
```

Flashing requires the `st-flash` utility from the open source stlink package: <https://github.com/stlink-org/stlink>.

The flashing pipeline defaults to idempotent execution, programming the microcontroller exclusively when the local binary diverges from resident flash contents. Helper script `scripts/flash_firmware.py` reads back device flash for byte-level comparison alongside initial binary integrity validation. Truncated binaries or images compiled for alternate microcontroller targets trigger validation failures prior to write operations.

## Modes

| Entry | Mode |
|---|---|
| `1` | Inverted pendulum control. Prompts for a rotor tracking reference: chirp, step, modulated sine, or log-spaced comb |
| `2` | Suspended pendulum control, identical reference options |
| `s` | Single PID, prompts for pendulum gains |
| `g` | General mode, dual PID or full state feedback, with motor configuration |
| `t` | Test of rotor actuator and pendulum angle encoder |
| `r` | Direct rotor control |
| `c` | Motor characterization, sinusoidal or square-wave chirp, not present in boot menu |
| `w` | Free-swing logger (`probe-freeswing`). Custom project addition. Streams pendulum angle at 500 Hz with the rotor locked stationary until hardware reset. Serves as the bring-up baseline. Mode `probe-pump` supersedes the baseline for identification, providing driven free-swing data across complete amplitude ranges |
| `y` | Tilt sweep (`probe-sweep`). Custom project addition. Steps the rotor through a full rotation in 30-degree increments, logging gravitational resting angles at each dwell. Full rotation also confirms cable routing avoids travel restrictions |
| `d` | Ring-down (`probe-pump`). Custom project addition. Actuates the pendulum to target amplitudes using the proven swing-up impulse, disengages drive torque, and logs free decay. Amplitudes below 180 degrees generate the dissipation curve. Targets exceeding 180 degrees drive continuous rotation over the apex, providing calibration data for counts per revolution. Sub-vertical targets repeat ten times automatically to establish empirical confidence bounds |
| `a` | Actuator characterization via pendulum deflection (`probe-lean`). Custom project addition. Executes a `MAX_ACCEL/16` pulse across ten repetitions per direction, bracketing each pulse with dwell windows for step-loss evaluation against tilt calibrations. Descends through a minimum-command ladder with `MAX_ACCEL` scaled from 16 to 128 to quantify velocity thresholds, stopping execution if rotor motion exceeds boundary limits. Evaluates the 11.78 rad/s^2 acceleration limit, low-speed creep thresholds, and microstep scaling. Actuation requires active supervision |
| `u` | Golden swing-up trace (`probe-trace`). Custom project addition. Executes standard swing-up and balance routines while logging pendulum and rotor dynamics across swing-up state `D` and balance state `B`. Automatically concludes after ten cycles. The captured trace provides the reference trajectory for simulation validation in [Experiment 04](../experiments/04-model-reconciliation/writeup.md) and represents the target state for the [Milestone 05](../milestones/M5-balance.md) balance policy. Actuation requires active supervision |
| `b` | RL balance (`rl-balance`). Added by this project. Runs the stock swing-up exactly as `u` does, logged the same way, then hands over within 1 degree of upright to the exported balance policy in `board/` instead of the PID loops, holds for up to 30 s, and stops itself once the pendulum has stayed past 30 degrees for 3 s, on a turn of arm travel from the handover, or at the time limit. The hold is logged into RAM and dumped after the stop. Drives the motor, so run it supervised |
| `r` (build) | RL swing-up from rest (`rl-swingup`). Added by this project and selected at build time. The boot menu's `r` keeps its stock meaning, direct rotor control. Runs the exported swing-up policy from the settled, hanging pendulum with no stock swing-up for up to 30 s, swing-up included, returns the arm to its start, and repeats. Drives the arm fast. Run it supervised |
| `q` | Exit control loop and halt rotor motion, not present in boot menu |

Identification modes `d`, `a`, and `u` control hardware execution until manual reset, formatting telemetry according to the specifications in [Identification battery](#identification-battery). Verification of encoder scale and holding torque execute via procedural protocols on top of modes `w` and `d`, rather than requiring unique firmware modes.

**Firmware boot enforces a five-second mode selection window.** Expiring the timer without user input causes the microcontroller to default to inverted pendulum control and initiate motor actuation.

## Entering a mode

Command `just hw-monitor` opens a read-only console on the serial interface for inspecting boot banners or monitoring active telemetry streams. Passing a mode character transmits the selection automatically following hardware reset:

```bash
just hw-monitor t  # then press the physical reset button
```

Standard serial terminals operate equivalently, provided mode selection occurs within the initial five-second window.

## Mode `1`, inverted pendulum control

Selecting mode `1` initiates an interactive prompt sequence. Prompts accept binary input, either 1 or 0, and block execution until input arrives.

Prompts configure rotor tracking references: chirp, step, modulated sinusoidal, or log-spaced frequency combs. The signals serve as excitation sources for system identification alongside mode `c` for motor-only excitation, enabling empirical frequency response analysis without firmware recompilation.

Two configuration prompts turn off default features: platform angle calibration, an auxiliary PID loop compensating rotor drift induced by mechanical tilt and encoder offset described in Manual Appendix G, and automatic swing-up. Turning off swing-up configures the controller exclusively for upright stabilization without initial launching maneuvers, enhancing safety during initial wiring verification.

## Mode `t`: testing rotor actuation and encoder feedback

Mode `t` exercises the stepper motor through sequential angular setpoints to 0, -45, 0, +90, and 0 degrees, prompts for manual 360-degree pendulum sweeps in clockwise and counter-clockwise directions, and cycles continuously until interrupted.

With motor power disconnected, reported rotor coordinates remain locked at `0.00` and velocity profiles report `Min 0 Max 0`. The L6474 driver requires dedicated supply voltage to report position coordinates. Restore motor power before evaluating telemetry readings.

## Modes `w` and `y`, free-swing and sweep loggers

Stock firmware modes generate telemetry exclusively while active control loops drive the stepper motor, preventing unforced baseline measurements.

Mode `w` (`probe-freeswing`) holds the stepper motor energized and stationary. Allowing an unpowered rotor transforms the hardware into a coupled two-degree-of-freedom dynamic system, altering the natural suspended pendulum oscillation documented in Manual Appendix D. Mode `y` (`probe-sweep`) steps the rotor through a full rotation to record gravitational settling positions, mapping baseplate inclination across rotor angles while verifying unimpeded cable coiling.

```bash
just hw-probe-freeswing 300  # mode w, writes to data/freeswing/
just hw-probe-sweep 110  # mode y, writes to data/tilt/
```

Both commands accept capture durations in seconds. Depress the hardware reset button when prompted by the script. Multiple software iterations can reference a single `probe-freeswing` baseline.

## Mode `b`, RL balance

The hardware test for the balance policy. Everything up to the handover is the stock swing-up as mode `u` runs it: the same kicks, the same 1 degree exit, the same `D` lines at 125 Hz. At the exit the stock code hard-stops the rotor, zeroes its velocity and enters the 500 Hz balance loop as before; what changes is the command. Each cycle the mode forms the five observations from the encoder count from hanging and the rotor position counted from issued steps relative to the handover instant (`board/observer.c`), runs the exported policy (`board/policy.c`), scales its action by the bound the checkpoint trained with (`RL_ACCEL_BOUND_RAD_S2`, 60 rad/s^2 for the deployed checkpoint) and then by 509.3 microsteps per radian, and hands the result to the balance path's own acceleration integrator, `apply_acceleration`, in place of the PID output. The bound is a hypothesis under [ADR-0004](../adrs/0004-two-actuator-paths.md): the balance path's physical limit is unmeasured, and the stock PID commands 43 to 58 rad/s^2 on the same path while catching. The boot default's 20 degree rotor step reference is disabled for this mode.

The mode stops, hard-stops the motor and dumps its log when the pendulum has stayed past 30 degrees from upright for 3 s (reason 1, `RL_FALL_PERSIST_CYCLES`; images built before that wait was added on 2026-09-11 stop at once), when the arm passes one turn from where the handover left it (reason 2), or after 15000 cycles, 30 s (reason 3). The travel bound protects the encoder cable rather than the controller: the cable snags somewhere past a turn from centre, watched on 2026-09-06 when a policy with no travel charge in its reward swept the arm 1.6 turns and the attempts that failed were the ones whose cable had wrapped. An earlier bound of pi came from the simulation's own termination angle and was too tight, ending a catch that was holding the pendulum inside 3 degrees. A hard stop leaves the driver energised and holding. The log is 2048 entries, every cycle through the first two seconds and sparser after, written to RAM during the hold because a blocking serial line per cycle starves the loop, and printed after the run ends. That last point matters at the bench: cutting power mid-hold loses the log, so let a run end on its own.

Build the image the way [Modifying the firmware](#modifying-the-firmware) describes, with `IDENT_AUTOSTART_MODE` set to `b` and the board code under `board/` compiled alongside, and stage it at the path `config/firmware.yaml` gives for `rl-balance`. Then flash and capture, with a hand on the motor supply:

```bash
just hw-flash rl-balance
just hw-rl-balance
```

Start every run this way. The image boots straight into the mode with no prompt and no delay, so anything that resets the board starts an attempt, pressing reset and flashing included. An attempt started that way runs and is not recorded, because nothing was listening. Expected on the serial line, in order: the banner with `BUILD rl` and `AUTOSTART mode b`, a settle wait while the pendulum hangs still, the `seq us counts phi state` header and `D` lines through the swing-up, silence for the hold, then `RL STOP after <cycles> cycles (<ms> ms): <why>`, where `<why>` is `the pendulum passed 30 degrees from upright` (reason 1), `the arm passed a turn from where it started, where the cable snags` (reason 2) or `the hold ran its full time` (reason 3), then `<n> logged`, the `R` lines, `RL DONE`, and `TRACE DONE`. A reason 1 stop inside the first 4 s is the policy failing the catch, the fall stop's 3 s wait (`RL_FALL_PERSIST_CYCLES`) included; reason 2 is the arm running out; reason 3 is a 30 s hold. If the swing-up itself never reaches upright the capture ends at its time limit with only `D` lines, which is the stock swing-up's failure rather than the policy's.

The conversion from the policy's rad/s^2 to the drive's command is the one line `rl_cmd_steps = policy_command(rl_obs, RL_ACCEL_BOUND_RAD_S2) * RL_MICROSTEPS_PER_RAD`, and the constants are in `edukit_system.h` beside `IDENT_AUTOSTART_MODE`. The bound in the header and the bound the checkpoint was trained and exported with are one number by construction of the procedure, and no check in the build enforces it: change one, change the other. The policy and observer files themselves are tracked under `board/` and checked against the simulation by the gate in [model-conversion.md](model-conversion.md); only the glue that calls them lives in the firmware tree.

## Mode `r`, RL swing-up from rest

The hardware test for the swing-up policy. It is mode `b` with the stock swing-up taken out. The board settles and takes its hanging datum as mode `b` does, then enters the 500 Hz control loop at once with the pendulum hanging. The policy commands the balance path's acceleration integrator through the observer from the first cycle. The observer's rate estimate starts at zero with the pendulum at rest. Because the swing-up checkpoints trained with `tanh` on the command, `board/policy_weights.h` is exported with `--squash-actions` and `RL_ACCEL_BOUND_RAD_S2` in `edukit_system.h` is 60. The torque setting stays at the swing-up's `MAX_TORQUE_SWING_UP` for the whole run. [Experiment 06's checkpoints](../experiments/06-swing-up/checkpoints/README.md#the-ones-on-the-bench) record which policy ran in which session.

The stops differ from mode `b`'s in one way. The fall stop at 30 degrees from upright arms only once the pendulum has first come within 3 degrees (`RL_ARRIVE_COUNTS`). Once armed, it fires only after the pendulum has stayed past 30 degrees for 3 s (`RL_FALL_PERSIST_CYCLES`), and mode `b` images built from the same source share that wait. A policy that falls can pump the pendulum back up in that time. The arrival check and the fall check both read the pendulum angle wrapped to one revolution. A swing-up that arrives from either side then arms the stop. The travel stop at one turn and the 30 s limit apply from the first cycle. The three stops are independent checks. The log records every cycle for the first 3 s (`RL_LOG_FAST_CYCLES_REST`) and every 25th cycle after that.

The mode repeats after each attempt, and one capture holds a series. Between attempts the board drives the arm back to where the attempt started with the profile move `BSP_MotorControl_GoTo` and waits at most 3 s (`RL_RETURN_TIMEOUT_MS`). It then prints `RL RETURN from <steps> to <steps> done, position <steps>` from the drive's position register, or `still moving` in place of `done` when the wait runs out. After a travel stop it skips the return and halts with `RL RETURN skipped, travel stop; halted, unwind the arm and reset`. Cut the motor supply, unwind the arm, and reset. Setting `RL_RETURN_TO_CENTRE` to 0 in `edukit_system.h` removes the return, its `RL RETURN` line, and the halt after a travel stop.

The return does not always move the arm. In the [Experiment 06](../experiments/06-swing-up/writeup.md) captures, three of nine returns printed `still moving` with the position unchanged, all after a full 30 s run, and each of those captures ends at the next boot banner. The log cannot show a stalled motor. The drive's register counts the steps it issued whether or not the shaft turned. On 2026-09-11 a series of attempts logged full arm strokes while the pendulum barely moved, and the [logbook](../experiments/06-swing-up/logbook.md) gives a cable wound past a turn as the probable cause. Mark the arm's starting position on the base and check the arm against the mark after every attempt.

The committed `board/policy_weights.h` is [Experiment 05](../experiments/05-balance/writeup.md)'s balance policy. Export the swing-up checkpoint over it first, with `just board-export <checkpoint> --squash-actions`. Build the image the way [Modifying the firmware](#modifying-the-firmware) describes, with `IDENT_AUTOSTART_MODE` set to `r` and the board code under `board/` compiled alongside, and stage it at the path `config/firmware.yaml` gives for `rl-swingup`. Then flash and capture, with a hand on the motor supply:

```bash
just hw-flash rl-swingup
just hw-rl-swingup
```

Expected on the serial line, in order: the banner with `BUILD rl` and `AUTOSTART mode r`, the settle wait, `Pendulum Initial Angle`, the `seq us counts phi state` header with no `D` lines after it, `RL FROM REST counts 0 seeded 0 mrad/s from 0 samples, observer 0 mrad/s`, the stock firmware's settings report during the run, one tab-separated row about every 2 s, then `RL STOP after <cycles> cycles (<ms> ms): <why>` with mode `b`'s three reasons, `<n> logged`, the `R` lines, `RL DONE`, and the `RL RETURN` line.

## Modifying the firmware

Supplied reference firmware resides in `docs/reference/STM32CubeIDE_project.zip`. The archive includes GCC makefiles, enabling command-line compilation without IDE dependencies.

Toolchain requirements necessitate an `arm-none-eabi` cross-compiler bundled with the newlib C runtime library. Standard macOS package manager formulas for `arm-none-eabi-gcc` omit newlib headers, causing compilation errors on missing `<stdint.h>`. Install official ARM toolchain distributions directly: <https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads>. Extract the official archive locally and prepend the binary folder to `PATH`:

```bash
export PATH="$HOME/.local/arm-gnu-toolchain/bin:$PATH"
```

The source archive includes stale precompiled `.o` object files. An initial `make all` invocation on a broken toolchain can link existing objects into a functional binary, giving the illusion of successful compilation until source modifications trigger true recompilation. Force explicit compilation by cleaning existing object files before proceeding.

Compilation commands execute within `Projects/Multi/Examples/MotionControl/IHM01A1_ExampleFor1Motor/SW4STM32/STM32F401RE-Nucleo/Debug`.

Generated project makefiles embed hard-coded absolute paths referencing original developer workstations across `makefile` and all seven child `subdir.mk` configuration files. Update path prefixes across all build manifests before invoking make.

Purge precompiled artifacts by deleting `*.o`, `*.d`, and `*.su` files, while **preserving `objects.list`**. Despite file extensions, `objects.list` provides critical linker input. Removing the list stalls link stages.

Execute `make all` with the ARM toolchain positioned first in `PATH`. The `secondary-outputs` target runs `arm-none-eabi-objcopy -O binary` to produce `STM32F401RE-Nucleo.bin` alongside the output binary. Flashing script `just hw-flash` programs this binary image onto the microcontroller.

Compiled image sizes differ from vendor binaries (`Edukit_firmware.bin`) due to differing compiler toolchains and optimization levels, generating binaries around 140 KB compared to the 130 KB stock image. Validate firmware integrity through runtime banner verification and functional mode validation.

**Header-only modifications fail to trigger automated rebuilds.** Generated build manifests classify targets as `.SECONDARY`, while `.d` dependency trees contain stale external absolute paths. Modifying configuration headers such as `IDENT_AUTOSTART_MODE` in `edukit_system.h` leaves the output target newer than recognized source prerequisites, causing `make all` to report successful completion without recompiling source files or refreshing binary images.

Enforce manual compilation sequencing to ensure updated code inclusion. Extract compiler flags from `Example/User/subdir.mk` and execute compilation stages directly from the `Debug` directory:

```bash
export PATH="$HOME/.local/arm-gnu-toolchain/bin:$PATH"
FW=/path/to/Projects/Multi/Examples/MotionControl/IHM01A1_ExampleFor1Motor
D=../../../../../../../../Drivers
# 1. compile main.o explicitly, ensuring updated headers compile into the object
arm-none-eabi-gcc "$FW/Src/main.c" -mcpu=cortex-m4 -std=gnu11 -g3 -DUSE_HAL_DRIVER -DSTM32F401xE \
  -DUSE_STM32F4XX_NUCLEO -DNUCLEO_F401RE -DSTM32F401RETx -DSTM32 -DSTM32F4 -DDEBUG -c \
  -I../../../Inc -I"$D/BSP/STM32F4xx-Nucleo" -I"$D/BSP/X-NUCLEO-IHMxx" -I"$D/BSP/Components/Common" \
  -I"$D/BSP/Components/l6474" -I"$D/CMSIS/Include" -I"$D/CMSIS/Device/ST/STM32F4xx/Include" \
  -I"$D/STM32F4xx_HAL_Driver/Inc" -O0 -ffunction-sections -Wall -fstack-usage \
  -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb -o Example/User/main.o
# 2. delete the ELF binary and relink
rm -f STM32F401RE-Nucleo.elf && make all
# 3. generate the raw binary image via objcopy
arm-none-eabi-objcopy -O binary STM32F401RE-Nucleo.elf STM32F401RE-Nucleo.bin
```

Setting `IDENT_AUTOSTART_MODE` configures dedicated measurement probes at compile time. The build pipeline stages target images in `build/firmware/`, including `edukit-ident-sweep.bin`, `-pump`, `-lean`, and `-trace`, as registered in `config/firmware.yaml`. Validate binary uniqueness using `md5` to confirm changes compiled into discrete binary payloads.

## Identification battery

Target `ident` introduces closed-loop identification routines `d`, `a`, and `u` alongside foundational `bench` enhancements. [Experiment 03](../experiments/03-hardware-bringup/writeup.md) utilizes these identification routines to calibrate simulation physics against hardware observations at swing-up amplitudes. Key modifications enhance the 500 Hz telemetry pipeline:

- Firmware samples timestamps **prior** to the cycle-counter delay loop, ensuring interval telemetry reflects execution jitter rather than delay compensation. A modulo sequence index occupies column one in telemetry streams, allowing host tooling to recognize packet loss directly.
- Telemetry lines respect serial throughput constraints, transmitting 46 bytes per 2 ms across a 230400 baud link. Output formats follow `seq us counts phi_steps [state|acc]` tab-delimited structures, where `counts` represents the optical encoder angle and `phi_steps` provides dead-reckoned rotor positions. The final column indicates drive states, P for pump or H for hold in mode `d`, swing-up phases, D or B in mode `u`, or acceleration commands in mode `a`.

Excitation parameters, probe divisors, and repetition thresholds reside in `edukit_system.h` under the `IDENT_` namespace. Constant `IDENT_CAPTURE_RUNS` designates repetitions per session, with ten as default. Swing-up pump logic adapts baseline excitation impulses from stock firmware assets.

**Automating mode execution via compile-time constants.** Selecting runtime modes via serial boot menus presents reliability challenges due to USB packet segmentation and rigid timing tolerances. Defining `IDENT_AUTOSTART_MODE` in `edukit_system.h` to mode characters `w`, `y`, `d`, `a`, or `u` commands immediate execution upon boot, eliminating menu timeouts, and preventing unintended motor operation. Setting the macro to `0` restores standard interactive menus.

Host acquisition script `scripts/capture_trace.py` detects active telemetry streams automatically without transmitting interactive prompt responses. Telemetry streams route through the virtual COM port on the ST-LINK interface, maintaining persistent connection status across target resets.

Bench characterization follows an ordered sequence where successive calibrations inform downstream identification. Rotor tilt sweeps precede dynamic identification, providing baseline step-loss reference points. Free ring-down passes calibrate damping dissipation curves while verifying encoder counts across 360-degree rotations. Actuator characterization probes low-speed deadbands and acceleration limits under active supervision. Golden trace collection completes the battery, recording benchmark trajectories for simulation matching.

## Identifying the running build

Project firmware builds output version metadata prior to boot prompts. Execute `just hw-monitor` and trigger hardware reset:

```text
BUILD ident (retuned swing-up; modes w y d a u; identification battery)
```

Build identifiers correspond to target declarations in `config/firmware.yaml`, defined via `FIRMWARE_BUILD` and `FIRMWARE_BUILD_NOTE` macros in `edukit_system.h`. Update these constants alongside firmware modifications to preserve build traceability.

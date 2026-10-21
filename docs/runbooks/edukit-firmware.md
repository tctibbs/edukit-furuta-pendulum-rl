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
| `d` | Ring-down (`probe-pump`). Custom project addition. Pumps the pendulum with the kit's swing-up kick to each target in `IDENT_RINGDOWN_AMPLITUDES`, 400, 700, and 1000 counts (60, 105, and 150 degrees), then hard-stops the rotor, holds it, and logs 14 s of free decay. Runs the set three times (`IDENT_RINGDOWN_REPEATS`). No target goes over the top. The fixed kick cannot reach it |
| `a` | Actuator characterization via pendulum deflection (`probe-lean`). Custom project addition. Runs a `MAX_ACCEL/16` pulse three times per direction (`IDENT_LEAN_RUNS`), with dwell windows before and after each pulse to check step loss against the tilt calibrations. Descends through a minimum-command ladder with `MAX_ACCEL` scaled from 16 to 128 to measure velocity thresholds, and stops if rotor motion exceeds the boundary limits. Tests the 11.78 rad/s^2 acceleration limit, low-speed creep thresholds, and microstep scaling. Run it supervised |
| `u` | Golden swing-up trace (`probe-trace`). Custom project addition. Runs one stock swing-up and 5 s of balance (`IDENT_TRACE_RUNS`, `IDENT_TRACE_BALANCE_TICKS`), logs the pendulum and rotor through swing-up state `D` and balance state `B`, then halts. The trace is the reference trajectory for simulation validation in [Experiment 04](../experiments/04-model-reconciliation/writeup.md) and the target state for the [Milestone 05](../milestones/M5-balance.md) balance policy. Run it supervised |
| `b` | RL balance (`rl-balance`). Added by this project. Runs the stock swing-up exactly as `u` does, logged the same way, then hands over within 1 degree of upright to the exported balance policy in `board/` instead of the PID loops, holds for up to 30 s, and stops itself once the pendulum has stayed past 30 degrees for 3 s, on a turn of arm travel from the handover, or at the time limit. The hold is logged into RAM and dumped after the stop. Drives the motor, so run it supervised |
| `r` (build) | RL swing-up from rest (`rl-swingup`). Added by this project and selected at build time. The boot menu's `r` keeps its stock meaning, direct rotor control. Runs the exported swing-up policy from the settled, hanging pendulum with no stock swing-up for up to 30 s, swing-up included, returns the arm to its start, and repeats. Drives the arm fast. Run it supervised |
| `x` | Showcase carousel (`showcase`). Added by this project and selected at build time. Walks the entries of `config/showcase.yaml` with the Nucleo's blue button. Drives the motor once an entry's countdown ends. Run it supervised |
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

Mode `t` drives the stepper motor through the setpoints 0, -45, 0, +90, and 0 degrees, prompts for manual 360-degree pendulum sweeps clockwise and counter-clockwise, then disables the motor and resets the board. It runs the sequence once (`ROTOR_ACTUATOR_TEST_CYCLES`).

With motor power disconnected, reported rotor coordinates remain locked at `0.00` and velocity profiles report `Min 0 Max 0`. The L6474 driver requires dedicated supply voltage to report position coordinates. Restore motor power before evaluating telemetry readings.

## Modes `w` and `y`, free-swing and sweep loggers

Stock firmware modes generate telemetry exclusively while active control loops drive the stepper motor, preventing unforced baseline measurements.

Mode `w` (`probe-freeswing`) holds the stepper motor energized and stationary. Allowing an unpowered rotor transforms the hardware into a coupled two-degree-of-freedom dynamic system, altering the natural suspended pendulum oscillation documented in Manual Appendix D. Mode `y` (`probe-sweep`) steps the rotor through a full rotation to record gravitational settling positions, mapping baseplate inclination across rotor angles while verifying unimpeded cable coiling.

```bash
just hw-probe-freeswing 300  # mode w, writes to data/freeswing/
just hw-probe-sweep 110  # mode y, writes to data/tilt/
```

Both commands take the capture length in seconds, open the serial port, and then reset the board through the debugger (`st-flash reset`). Several software iterations can use one `probe-freeswing` baseline.

## Mode `b`, reinforcement learning balance

The hardware test for the balance policy. Everything up to the handover is the stock swing-up as mode `u` runs it: the same kicks, the same 1 degree exit, the same `D` lines at 125 Hz. At the exit the stock code hard-stops the rotor, zeroes its velocity, and enters the 500 Hz balance loop as before. Each cycle the mode forms the five observations from the encoder count from hanging and the rotor position counted from issued steps relative to the handover instant (`board/observer.c`), runs the exported policy (`board/policy.c`), scales its action by the bound the checkpoint trained with (`RL_ACCEL_BOUND_RAD_S2`, 60 rad/s^2 for the deployed checkpoint) and then by 509.3 microsteps per radian, and hands the result to the balance path's own acceleration integrator, `apply_acceleration`, in place of the PID output. The bound is a hypothesis under [ADR-0004](../adrs/0004-two-actuator-paths.md). The balance path's physical limit is unmeasured, and the supplied PID commands 43 to 58 rad/s^2 on the same path while catching. The boot default's 20 degree rotor step reference is turned off for this mode.

The mode stops, hard-stops the motor, and dumps its log when the pendulum has stayed past 30 degrees from upright for 3 s (reason 1, `RL_FALL_PERSIST_CYCLES`; images built before that wait was added on 2026-09-11 stop at once), when the arm passes one turn from where the handover left it (reason 2), or after 15000 cycles, 30 s (reason 3). The travel bound protects the encoder cable. The cable snags somewhere past a turn from center. On 2026-09-06 a policy with no travel charge in its reward swept the arm 1.6 turns, and the attempts that failed were the ones whose cable had wrapped. An earlier bound of pi came from the simulation's termination angle and was too tight, ending a catch that was holding the pendulum inside 3 degrees. A hard stop leaves the driver energized and holding. The log is 2048 entries, every cycle through the first two seconds and sparser after, written to RAM during the hold because a blocking serial line per cycle starves the loop, and printed after the run ends. Cutting power mid-hold loses the log. Let a run end on its own.

[Modifying the firmware](#modifying-the-firmware) describes the build. Build, flash, and capture, with a hand on the motor supply:

```bash
just fw-build b build/firmware/edukit-rl-balance.bin
just hw-flash rl-balance
just hw-rl-balance
```

Start every run this way. `just hw-rl-balance` opens the serial port and then resets the board itself. The image boots straight into the mode with no prompt and no delay, and any other reset (pressing the button or flashing) starts an attempt that nothing records. Expected on the serial line, in order: the banner with `BUILD rl` and `AUTOSTART mode b`, a settle wait while the pendulum hangs still, the `seq us counts phi state` header and `D` lines through the swing-up, silence for the hold, then `RL STOP after <cycles> cycles (<ms> ms): <why>`, where `<why>` is `the pendulum passed 30 degrees from upright` (reason 1), `the arm passed a turn from where it started, where the cable snags` (reason 2), or `the hold ran its full time` (reason 3), then `<n> logged`, the `R` lines, `RL DONE`, and `TRACE DONE`. A reason 1 stop inside the first 4 s is the policy failing the catch, the fall stop's 3 s wait (`RL_FALL_PERSIST_CYCLES`) included; reason 2 is the arm running out; reason 3 is a 30 s hold. If the swing-up itself never reaches upright, the capture ends at its time limit with only `D` lines and the policy never runs.

The conversion from the policy's rad/s^2 to the drive's command is the one line `rl_cmd_steps = policy_command(rl_obs, RL_ACCEL_BOUND_RAD_S2) * RL_MICROSTEPS_PER_RAD`, and the constants are in `edukit_system.h` beside `IDENT_AUTOSTART_MODE`. The procedure keeps the bound in the header equal to the bound the checkpoint was trained and exported with. No check in the build enforces it. Change both together. The policy and observer files themselves are tracked under `board/` and checked against the simulation by the test suite in [model-conversion.md](model-conversion.md); only the glue that calls them lives in the firmware tree.

## Mode `r`, RL swing-up from rest

The hardware test for the swing-up policy. It is mode `b` with the stock swing-up taken out. The board settles and takes its hanging datum as mode `b` does, then enters the 500 Hz control loop at once with the pendulum hanging. The policy commands the balance path's acceleration integrator through the observer from the first cycle. The observer's rate estimate starts at zero with the pendulum at rest. Because the swing-up checkpoints trained with `tanh` on the command, `board/policy_weights.h` is exported with `--squash-actions` and `RL_ACCEL_BOUND_RAD_S2` in `edukit_system.h` is 60. The torque setting stays at the swing-up's `MAX_TORQUE_SWING_UP` for the whole run. [Experiment 06's checkpoints](../experiments/06-swing-up/checkpoints/README.md#the-ones-on-the-bench) record which policy ran in which session.

The stops differ from mode `b`'s in one way. The fall stop at 30 degrees from upright arms only once the pendulum has first come within 3 degrees (`RL_ARRIVE_COUNTS`). Once armed, it fires only after the pendulum has stayed past 30 degrees for 3 s (`RL_FALL_PERSIST_CYCLES`), and mode `b` images built from the same source share that wait. A policy that falls can pump the pendulum back up in that time. The arrival check and the fall check both read the pendulum angle wrapped to one revolution. A swing-up that arrives from either side then arms the stop. The travel stop at one turn and the 30 s limit apply from the first cycle. The three stops are independent checks. The log records every cycle for the first 3 s (`RL_LOG_FAST_CYCLES_REST`) and every twenty-fifth cycle after that.

The mode repeats after each attempt, and one capture holds a series. Between attempts the board drives the arm back to where the attempt started with the profile move `BSP_MotorControl_GoTo` and waits at most 3 s (`RL_RETURN_TIMEOUT_MS`). It then prints `RL RETURN from <steps> to <steps> done, position <steps>` from the drive's position register, or `still moving` in place of `done` when the wait runs out. After a travel stop it skips the return and halts with `RL RETURN skipped, travel stop; halted, unwind the arm and reset`. Cut the motor supply, unwind the arm, and reset. Setting `RL_RETURN_TO_CENTRE` to 0 in `edukit_system.h` removes the return, its `RL RETURN` line, and the halt after a travel stop.

The return does not always move the arm. In the [Experiment 06](../experiments/06-swing-up/writeup.md) captures, three of nine returns printed `still moving` with the position unchanged, all after a full 30 s run, and each of those captures ends at the next boot banner. The log cannot show a stalled motor. The drive's register counts the steps it issued whether or not the shaft turned. On 2026-09-11 a series of attempts logged full arm strokes while the pendulum barely moved, and the [logbook](../experiments/06-swing-up/logbook.md) gives a cable wound past a turn as the probable cause. Mark the arm's starting position on the base and check the arm against the mark after every attempt.

Follow-on, 2026-09-13: the step clock is the likelier explanation for a return that prints `still moving` with the position unchanged. Such a return issued no steps. The step clock is TIM2, with no auto-reload preload. `L6474_Board_Pwm1SetFreq` in `x_nucleo_ihm01a1_stm32f4xx.c` started it without clearing its count. A move after the arm had stood still could then set a period below the stale count and wait for the 32-bit counter to wrap. After the fix, the driver clears the count when the timer starts and when a new period falls below it. Every mode's profile moves pass through that function. The wound cable the [logbook](../experiments/06-swing-up/logbook.md) gives as the probable cause would then follow from returns that never ran. Images built before the fix, such as the `rl-swingup` image of 2026-09-11, can still stall. Rebuild before flashing.

The committed `board/policy_weights.h` is [Experiment 05](../experiments/05-balance/writeup.md)'s balance policy. Export the swing-up checkpoint over it first, with `just board-export <checkpoint> --squash-actions`. Then build, flash, and capture, with a hand on the motor supply:

```bash
just fw-build r build/firmware/edukit-rl-swingup.bin
just hw-flash rl-swingup
just hw-rl-swingup
```

Expected on the serial line, in order: the banner with `BUILD rl` and `AUTOSTART mode r`, the settle wait, `Pendulum Initial Angle`, the `seq us counts phi state` header with no `D` lines after it, `RL FROM REST counts 0 seeded 0 mrad/s from 0 samples, observer 0 mrad/s`, the stock firmware's settings report during the run, one tab-separated row about every 2 s, then `RL STOP after <cycles> cycles (<ms> ms): <why>` with mode `b`'s three reasons, `<n> logged`, the `R` lines, `RL DONE`, and the `RL RETURN` line.

## Mode `x`, the showcase carousel

The `showcase` image boots straight into a carousel of the entries in `config/showcase.yaml`, with JETHRO selected. [Experiment 07](../experiments/07-showcase/writeup.md#the-carousel) lists the groups. The carousel's code is under `board/` ([board/README.md](../../board/README.md)).

A tap on the Nucleo's blue button moves to the next group. Inside a group, a tap moves to the next entry, and past the last one back to the main entry. A one-second hold on a main entry enters the rest of its group, a hold inside leaves it, and on PID or LQR a hold swaps the two. An entry's first attempt starts after a 4 s countdown. After a result, the entry runs again in 6 s unless a press ended the attempt or the result needs the operator. A hardware test's result stays up until a tap. Any press during an attempt ends it and pauses, and a tap resumes.

SysTick samples the button every millisecond. The button has no interrupt because its line, EXTI13, shares a vector with the L6474's flag line, and the kit's handler clears only the flag line. In the kit's loop, mode `x` checks the button every tenth 2 ms cycle. With 20 ms of debounce, a tap ends an attempt on the kit's controllers within about 40 ms of its release.

A frame is a blocking I2C transfer of about 23 ms, and the display is written only between attempts and at FREE SWING's cue to lift. The buzzer is a 25 kHz TIM5 carrier on PA0, modulated at the note frequency by TIM11. The carrier's duty sets the volume. The duty is 3 percent between attempts and 20 percent during one. The showcase claims TIM5 and TIM11. The display and buzzer are optional, wired as [edukit-assembly.md](edukit-assembly.md#showcase-display-and-buzzer) shows.

Each attempt is one pass of the boot loop. PID runs the kit's swing-up with [Experiment 03](../experiments/03-hardware-bringup/writeup.md)'s retuned kicks, then the kit's two PID loops. LQR runs the same swing-up, then the kit's full-state feedback from the first control cycle after the handover, with the inverted-mode gains of Edukit Manual Sec. 14, page 84 (`SHOWCASE_LQR_*` in `board/showcase.h`). The learned entries run as modes `b` and `r` do, each with its own policy under `board/policies/`. The hardware tests start from the hanging datum in place of the swing-up and run on the identification battery's 2 ms clock:

- RING-DOWN pumps as mode `d` does to 1000 counts (150 degrees), holds the arm, and shows Q_eff and the suspended-mode frequency from the free decay.
- FREE SWING holds the arm and shows the suspended-mode frequency of a hand release. Lift only after its beep. A datum taken with the pendulum held ends as NO RESULT.
- TILT SWEEP steps the arm from -180 to +180 degrees in 30 degree stops and shows the base tilt's amplitude and bearing.

A stock entry keeps the kit's exits and ends as NO CATCH if the swing-up has not caught in 20 s. A learned entry stops on a fall past 30 degrees and on the arm passing a turn from home, and otherwise holds until a press (30 s with auto-advance on). A swing-up entry waits 3 s before its fall stop, stops at 1.5 s if the arm moves while the pendulum does not, and ends as NO CATCH after 30 s without arriving. After every attempt the board drives the arm home and turns the bridges off. The next pass takes the arm's position as home. These results pause until a tap:

- CENTER ARM follows a travel stop or a return cut short. Turn the arm back to its home mark.
- CHECK ARM follows a stall: a move, return, or ring-down pump past its time limit, or the swing-up stall check.
- FAULT follows an undervoltage, thermal, or overcurrent flag. The return is skipped. Center the arm.
- NO MOTOR means the driver has no supply. A supply that comes back leaves the carousel paused until a tap.

Build, flash, and capture, with a hand on the motor supply:

```bash
just fw-showcase
just hw-flash showcase
just hw-showcase 600
```

`just fw-showcase` regenerates the table and policies and builds `build/firmware/edukit-showcase.bin`. `just hw-showcase` resets the board itself. With the motor supply on, any reset, flashing included, starts JETHRO after its countdown. With the supply off, the board waits in NO MOTOR for a tap.

Expected on the serial line: `SHOWCASE oled answered, 13 entries` (or `absent`), then per attempt `SHOWCASE entry <n>/13 <title> attempt <k>`, the banner with `BUILD showcase`, and the lines of the path it runs, ending in `SHOWCASE result <n> <title>:`. For a stock or learned entry the result follows mode `r`'s `RL STOP` and `RL RETURN` lines and reads `<outcome> up <ms> hold <ms> run <ms> tops <passes> peak <steps>`. For a hardware test it reads `Q <q> at <counts> counts, <hz> Hz`, `<hz> Hz`, or `tilt <degrees> deg, bearing <degrees> deg`, then `run <ms>`. The RAM log follows between `SHOWCASE log <count>` and `SHOWCASE log end`. `SHOWCASE select <n> <title>` marks a press between attempts. Between attempts the host can send `n` for a tap, `h` for a hold, or a digit to set auto-advance to that many attempts per entry (`0` turns it off).

What mode `x` changes, on top of the mode `b` and `r` glue in [Modifying the firmware](#modifying-the-firmware):

- `Inc/edukit_system.h` adds `SHOWCASE_ENABLED` (true when `IDENT_AUTOSTART_MODE` is `'x'`), the build name `showcase`, and the `SHOWCASE_` constants.
- `Src/main.c` adds under that flag the selector between attempts, the per-attempt setup, the hardware tests, the button and stop checks, the LQR gains at `i == 1` with the kit's 6 s gain restore skipped, bounded profile-move waits, and the result and log dump. It compiles out the kit's serial command poll inside the control loop.
- `board/showcase_port_stm32.c`, linked in, replaces the HAL's weak `HAL_IncTick` to run the button and buzzer.
- In every mode, the fall persistence is a variable holding the header's value, and the `RL STOP` line's `<ms>` is twice the cycle count. `ident_tick` waits on the signed difference to its deadline and no longer stalls at the cycle counter's wrap every 51 s.

Mode `x` resets the kit's inclination-calibration state and rotor integrator before every attempt. The kit's control loop never clears them. Without the reset, every stock attempt after a hold longer than 14 s (7001 cycles) with calibration off would run with its reference drives held off for its first 18 s (9001 cycles). The reset has no bench check. To check it, run a PID attempt after a hold longer than 14 s.

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

Modes `b`, `r`, and `x` also link code from `board/`, and the three steps cannot build them. `scripts/build_firmware.sh MODE OUT` (`just fw-build MODE OUT`) builds any mode. It expects the archive extracted into `firmware/` at the repository root, a path git ignores, with the glue below applied. On a fresh checkout, extract it with `unzip docs/reference/STM32CubeIDE_project.zip -d firmware`. The toolchain comes from `~/.local/arm-gnu-toolchain/bin` or from `ARM_TOOLCHAIN`. Beyond the three steps, the script:

- writes the mode letter into `IDENT_AUTOSTART_MODE` and leaves it there.
- rewrites the absolute prefix in every `makefile`, `subdir.mk`, and `.d` file to this checkout with `scripts/firmware_prefix.py`, anchored on the firmware tree's own path.
- recompiles the IHM01A1 driver, `x_nucleo_ihm01a1_stm32f4xx.c`, in every mode. That file carries the TIM2 fix in the mode `r` follow-on.
- compiles `board/policy.c` and `board/observer.c` with `-ffp-contract=off`, as the host tests do, and adds them to `objects.list`. The flag keeps GCC from fusing multiply and add instructions. The board's float32 arithmetic then matches the host-tested build bit for bit, libm aside.
- for mode `x` only, compiles the showcase's board sources and the HAL's `stm32f4xx_hal_i2c.c` with `HAL_I2C_MODULE_ENABLED` defined on the command line, and leaves the shared HAL configuration unchanged. For every other mode it removes their objects from `objects.list`.

Expected output: the `arm-none-eabi-size` table, `wrote <out> (<bytes> bytes), mode '<mode>'`, the image's build note, `autostart banner present`, and, for mode `x`, `showcase result line present`.

The firmware tree is never committed. The changes for modes `b` and `r` are below, and mode `x`'s are in [its section](#mode-x-the-showcase-carousel).

Mode `b` (2026-09-06), in `Src/main.c`:

- includes `policy.h` and `observer.h`.
- adds an `rl_enabled` flag, set from `IDENT_AUTOSTART_MODE == 'b'` in the autostart block, that also turns on mode `u`'s trace and swing-up and turns off the 20 degree step reference.
- adds a RAM log of `RL_LOG_ENTRIES` records, dumped after the loop.
- adds a block before the balance loop's `ACCEL_CONTROL` branch that forms the observations, runs the policy, replaces `rotor_control_target_steps`, logs, and checks the stops.
- skips mode `u`'s sparse balance logging and 5 s window under the flag.

`Inc/edukit_system.h` gains the `RL_` constants, `FIRMWARE_BUILD "rl"`, and its note. The stock swing-up is unchanged.

Mode `r` (2026-09-10 and 2026-09-11), on top of mode `b`'s:

- adds an `rl_from_rest` flag, set from `IDENT_AUTOSTART_MODE == 'r'`, that also sets mode `b`'s flags.
- skips the initial 150-microstep move and the swing-up loop under that flag.
- leaves the torque at `MAX_TORQUE_SWING_UP`.
- adds an `rl_arrived` state that arms the fall stop, read from the tilt wrapped to one revolution.
- skips the stock pendulum-excursion exit (a hanging pendulum starts past it).
- adds the fall persistence (shared with mode `b`) and keeps the travel and time stops as independent checks.
- returns the arm to the attempt's start after the dump, with a bounded wait. A drive fault skips the return.
- halts after a travel stop.

The header gains `RL_ARRIVE_COUNTS`, `RL_LOG_FAST_CYCLES_REST`, `RL_FALL_PERSIST_CYCLES`, `RL_RETURN_TO_CENTRE`, `RL_RETURN_TIMEOUT_MS`, and the note's `RL swing-up from rest, return to start after each attempt`.

## Identification battery

Target `ident` introduces closed-loop identification routines `d`, `a`, and `u` alongside foundational `bench` enhancements. [Experiment 03](../experiments/03-hardware-bringup/writeup.md) utilizes these identification routines to calibrate simulation physics against hardware observations at swing-up amplitudes. Key modifications enhance the 500 Hz telemetry pipeline:

- Firmware samples timestamps **prior** to the cycle-counter delay loop, ensuring interval telemetry reflects execution jitter rather than delay compensation. A modulo sequence index occupies column one in telemetry streams, allowing host tooling to recognize packet loss directly.
- Telemetry lines respect serial throughput constraints, transmitting 46 bytes per 2 ms across a 230400 baud link. Output formats follow `seq us counts phi_steps [state|acc]` tab-delimited structures, where `counts` represents the optical encoder angle and `phi_steps` provides dead-reckoned rotor positions. The final column indicates drive states, P for pump or H for hold in mode `d`, swing-up phases, D or B in mode `u`, or acceleration commands in mode `a`.

Excitation parameters, probe divisors, and repetition thresholds are in `edukit_system.h` under the `IDENT_` namespace. `IDENT_CAPTURE_RUNS` sets the repeats per capture to three. The pump logic adapts the supplied firmware's swing-up kicks.

**Automating mode execution via compile-time constants.** Selecting runtime modes via serial boot menus presents reliability challenges due to USB packet segmentation and rigid timing tolerances. Defining `IDENT_AUTOSTART_MODE` in `edukit_system.h` to mode characters `w`, `y`, `d`, `a`, `u`, `b`, `r`, or `x` commands immediate execution upon boot, eliminating menu timeouts, and preventing unintended motor operation. Setting the macro to `0` restores standard interactive menus.

`scripts/capture_trace.py` detects a running telemetry stream on its own and sends no prompt responses. Its `--auto-reset`, which every capture recipe passes, resets the target through `st-flash reset` once the port is open. Telemetry runs over the ST-LINK's virtual COM port, and the port stays connected across target resets.

The battery runs in order, and each calibration informs the identification after it. Tilt sweeps come before dynamic identification and give the baseline step-loss reference points. Free ring-downs calibrate the dissipation curves. Actuator characterization, run supervised, probes low-speed deadbands and acceleration limits. The golden trace comes last and records the reference trajectories for simulation matching.

## Identifying the running build

Project firmware builds output version metadata prior to boot prompts. Execute `just hw-monitor` and trigger hardware reset:

```text
BUILD ident (retuned swing-up; modes w y d a u; identification battery)
```

Build identifiers correspond to target declarations in `config/firmware.yaml`, defined via `FIRMWARE_BUILD` and `FIRMWARE_BUILD_NOTE` macros in `edukit_system.h`. Update these constants alongside firmware modifications to preserve build traceability.

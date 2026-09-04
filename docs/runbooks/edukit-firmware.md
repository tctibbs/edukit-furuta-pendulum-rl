# Running the Edukit firmware

Guidance on how to run the board, what each boot mode does, and how to work with the serial link. [edukit-assembly.md](edukit-assembly.md) covers assembly and the encoder wiring.

## Flashing

`config/firmware.yaml` declares all the images that can be written to the board. To flash a new one, declare it here with a path and a description.

```bash
just hw-targets  # list the declared targets
just hw-flash  # write the default target
just hw-flash bench  # write a named target
just hw-flash bench --force  # write even when the firmware already matches
```

Flashing requires `st-flash` from the stlink package: <https://github.com/stlink-org/stlink>.

By default the board is only flashed when the image differs from what is already on it. `scripts/flash_firmware.py` reads the flash back and compares it byte for byte. It also sanity-checks the image first. A truncated file or one built for a different part fails that check.

## Modes

| Entry | Mode |
|---|---|
| `1` | Inverted pendulum control. Prompts for a rotor tracking reference: chirp, step, modulated sine, or log-spaced comb |
| `2` | Suspended pendulum control, same reference options |
| `s` | Single PID, prompts for pendulum gains |
| `g` | General mode, dual PID or full state feedback, with motor configuration |
| `t` | Test of rotor actuator and pendulum angle encoder |
| `r` | Direct rotor control |
| `c` | Motor characterization, sinusoidal or square-wave chirp. Not in the boot menu |
| `w` | Free-swing logger (`probe-freeswing`). Added by this project. Streams pendulum angle at 500 Hz with the rotor held, until reset. The bring-up baseline; superseded for identification by `probe-pump`, whose ring-down is a driven free-swing across every amplitude |
| `y` | Tilt sweep (`probe-sweep`). Added by this project. Steps the rotor through a full turn in 30 degree increments, repeated a few times, logging the pendulum's resting angle at each dwell. The full turn also confirms the cable does not bound the travel |
| `d` | Ring-down (`probe-pump`). Added by this project. Pumps the pendulum to each of a list of target amplitudes with the proven stock swing-up kick, cuts drive, and logs the free decay. Amplitudes below 180 degrees give the dissipation-versus-amplitude curve; a target above 180 degrees drives it over the top into rotation, whose free spin-down gives counts per revolution. One mode, both results. The sub-vertical targets repeat automatically (10 times by default) so the curve carries error bars |
| `a` | Actuator characterization via the pendulum's lean (`probe-lean`). Added by this project. A `MAX_ACCEL/16` unit probe (one burst each direction, ten times, each with an in-place dwell bracket for step-loss detection against the tilt map), then a descending min-command ladder (`MAX_ACCEL` over 16 to 128, each direction) that tests for a minimum-speed floor. Aborts if the dead-reckoned rotor leaves a bounded arc. For the 11.78 rad/s^2 acceleration bound, the minimum-speed floor that leaves the rotor creeping at a commanded stop (folds the old creep mode `z`), and the microsteps-vs-full-steps reading. Drives the motor, so run it supervised |
| `u` | Golden swing-up trace (`probe-trace`). Added by this project. Runs the real stock swing-up and balance unchanged, adding only logging: the pendulum and rotor through the swing-up (state `D`) and a short balance hold (state `B`). Repeats automatically (10 swing-ups) and stops itself. The trajectory is the reference the simulation must reproduce when driven through the same rotor motion (experiment 04) and the arrival-at-vertical a [Milestone 05](../milestones/M5-balance.md) balance policy must learn to catch. Drives the motor, so run it supervised |
| `q` | Exit control and stop rotor motion. Not in the boot menu |

The identification modes `d`, `a`, and `u` each own the board until reset and log in the extended format described under [Identification battery](#identification-battery) below. The counts-per-revolution check and the hold-stiffness discriminator ride on modes `w` and `d` respectively, as procedures rather than new modes.

**On boot there are five seconds to pick a mode.** Otherwise the board defaults to inverted pendulum control and starts driving the motor.

## Entering a mode

`just hw-monitor` opens a read-only console on the serial link, for reading the boot banner or watching a mode run. Give it a mode and it will also answer the boot prompt after a reset:

```bash
just hw-monitor t  # then press the physical reset button
```

Any serial terminal works too, as long as the mode is typed inside the five-second window.

## Mode `1`, inverted pendulum control

Selecting mode `1` explicitly opens a chain of prompts, each accepting 1 or 0 and each blocking until answered.

Most of them switch on a rotor tracking reference, chirp, step, modulated sine, or a comb of log-spaced sinusoids. These are excitation sources for system identification, as is mode `c`, which drives the motor alone. A frequency response requires no rebuild.

The two exceptions switch off features that default on. Platform angle calibration is an extra PID loop correcting rotor drift from base tilt and encoder offset (Manual App. G). Disabling swing-up gives a controller that holds the pendulum without first launching it, which is safer while the wiring is unconfirmed.

## Mode `t`, actuator and encoder test

Mode `t` runs the rotor through 0, -45, 0, +90, 0 degrees, then prompts for a manual 360 degree pendulum rotation in each direction, and repeats until interrupted.

With the motor supply disconnected, every reported rotor position stays at `0.00` and the speed profile reads `Min 0 Max 0`. The L6474 requires its own supply to report position at all, so connect it before concluding anything from a zero reading.

## Modes `w` and `y`, the free-swing and sweep loggers

The stock modes report only while the control loop drives the rotor, so a free measurement gets nothing out of them.

Mode `w` (`probe-freeswing`) holds the rotor energized and stationary. A free rotor makes the machine a coupled two-degree-of-freedom system, and the frequency measured would not be the suspended mode of Manual App. D. Mode `y` (`probe-sweep`) sweeps the rotor instead and logs where the pendulum settles, so any variation across the sweep is baseplate tilt. The sweep steps the rotor through a full turn. The cable coils through that turn and does not bound the travel.

```bash
just hw-probe-freeswing 300  # mode w, writes to data/freeswing/
just hw-probe-sweep 110  # mode y, writes to data/tilt/
```

Both take a duration in seconds. Press reset when the capture prompts for it. Several releases can share one `probe-freeswing` capture.

## Modifying the firmware

The supplied source is in `docs/reference/STM32CubeIDE_project.zip`, which carries a GCC makefile, so it builds from the command line without the IDE. The obstacles below are all one-time.

Building requires an `arm-none-eabi` toolchain with newlib. Package-manager builds of `arm-none-eabi-gcc` often omit it, and every compile then fails on a missing `stdint.h`. ARM's prebuilt toolchains carry it: <https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads>. On macOS the Homebrew `arm-none-eabi-gcc` formula is the incomplete kind: it has no newlib, and core Homebrew ships no `arm-none-eabi-newlib` formula to add one. Use ARM's prebuilt instead, either the `gcc-arm-embedded` cask (a `.pkg` that needs an admin password) or the tarball from the link above extracted to a user directory and put first on `PATH`. On this Mac that tarball is at `~/.local/arm-gnu-toolchain/bin`; put it ahead of the Homebrew build with `export PATH="$HOME/.local/arm-gnu-toolchain/bin:$PATH"` before any build, or every recompile fails on the missing `stdint.h`.

The archive ships prebuilt `.o` files, so a first `make all` on an incomplete toolchain can still link them into a working `.bin` and look like a successful build. The missing newlib only surfaces on the first real recompile, when a source file actually changes. Force a real compile (touch a source file, or delete the objects as below) to confirm the toolchain before trusting it.

Everything below happens in `Projects/Multi/Examples/MotionControl/IHM01A1_ExampleFor1Motor/SW4STM32/STM32F401RE-Nucleo/Debug`, seven levels into the archive.

The generated makefiles carry an absolute path from the original author's machine, for the linker script and every source file. It is in `makefile` and in all seven `subdir.mk` files beneath it, so rewrite the prefix in every one of them.

The directory ships prebuilt objects. Delete `*.o`, `*.d` and `*.su` first, but **keep `objects.list`**. Despite the extension it is a build input, the linker's object list, and deleting it leaves the link with nothing to do.

Then `make all`, with the toolchain first on `PATH`. Its `secondary-outputs` target runs `arm-none-eabi-objcopy -O binary`, so the build leaves `STM32F401RE-Nucleo.bin` beside the ELF, which is the file `st-flash` writes.

A different compiler built `Edukit_firmware.bin`. The rebuild will not match it byte for byte. Expect around 140 KB against the stock 130 KB. Check behaviour instead, the same banner and the same modes.

**`make` does not rebuild after a header-only change, and it fails silently.** The generated makefile marks every target `.SECONDARY`, and the `.d` dependency files carry absolute paths from the machine that generated them, so `make` never tracks the headers. After editing only a header (for example `IDENT_AUTOSTART_MODE` in `edukit_system.h`), `make all` finds the `.elf` newer than the prerequisites it does track and does nothing. It skips the recompile, the relink and the `objcopy`, then re-wraps the stale `.bin`. It prints `Finished building` and looks successful. Deleting the objects does not help while the `.elf` is present, because `make` treats the missing objects as intermediates it decides it does not need. This is the same class of trap as the prebuilt-`.o` one above.

Force each step by hand instead. From the `Debug` directory, with the toolchain first on `PATH` (the exact compile flags are in `Example/User/subdir.mk`; the `-I` list is relative to `Debug`):

```bash
export PATH="$HOME/.local/arm-gnu-toolchain/bin:$PATH"
FW=/path/to/Projects/Multi/Examples/MotionControl/IHM01A1_ExampleFor1Motor
D=../../../../../../../../Drivers
# 1. compile main.o explicitly, so the current header is definitely read
arm-none-eabi-gcc "$FW/Src/main.c" -mcpu=cortex-m4 -std=gnu11 -g3 -DUSE_HAL_DRIVER -DSTM32F401xE \
  -DUSE_STM32F4XX_NUCLEO -DNUCLEO_F401RE -DSTM32F401RETx -DSTM32 -DSTM32F4 -DDEBUG -c \
  -I../../../Inc -I"$D/BSP/STM32F4xx-Nucleo" -I"$D/BSP/X-NUCLEO-IHMxx" -I"$D/BSP/Components/Common" \
  -I"$D/BSP/Components/l6474" -I"$D/CMSIS/Include" -I"$D/CMSIS/Device/ST/STM32F4xx/Include" \
  -I"$D/STM32F4xx_HAL_Driver/Inc" -O0 -ffunction-sections -Wall -fstack-usage \
  -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb -o Example/User/main.o
# 2. delete the ELF so make must relink, then relink
rm -f STM32F401RE-Nucleo.elf && make all
# 3. objcopy the.bin yourself; make's own.bin step is stale for the same reason
arm-none-eabi-objcopy -O binary STM32F401RE-Nucleo.elf STM32F401RE-Nucleo.bin
```

Selecting a probe is a compile-time choice: set `IDENT_AUTOSTART_MODE` to the mode letter and run those three steps, once per probe. The project stages one image per probe (`edukit-ident-sweep.bin`, `-pump`, `-lean`, `-trace`) in `build/firmware/`, declared as targets in `config/firmware.yaml`. Always confirm two different-mode builds actually differ (`md5`) rather than trusting `make`: an identical hash means it served a stale image.

## Identification battery

The `ident` target adds the closed-loop identification modes `d`, `a`, and `u` on top of the `bench` modifications, for reconciling the simulation against the unit at the amplitudes swing-up uses (experiment 03). The changes are in the 500 Hz logging path:

- The per-line timestamp is taken **before** the loop's cycle-counter wait, not after, so the interval between lines carries the loop jitter instead of the wait absorbing it, the one thing the earlier 500 Hz rate confirmation could not measure. A modulo sequence counter is the first column of every identification line, so the host detects a dropped sample as a sequence gap rather than relying on a fixed interval.
- Lines stay inside the 46-byte-per-2-ms serial budget at 230400 baud. The columns per mode are `seq us counts phi_steps [state|acc]`, tab-separated, where `counts` is the pendulum encoder, `phi_steps` the dead-reckoned rotor position, and the last column the drive state (`P` pump, `H` hold) for `d`, the swing-up or balance state (`D`, `B`) for `u`, or the commanded profile acceleration for `a`.

The parameters (amplitude list, probe divisor, min-command ladder divisors, repeat counts) are `#define`s in `edukit_system.h` under the `IDENT_` prefix; `IDENT_CAPTURE_RUNS` sets how many times each mode repeats its measurement in one capture, ten by default. The pump reuses the stock swing-up's kick, so the battery leans on the third-party swing-up in the supplied firmware. The derived image is git-ignored because that source carries no LICENSE file.

**Mode selection happens at compile time.** Entering a mode through the boot menu was never reliable. The menu arrives in USB fragments, the firmware acts only on exactly two bytes (one character and one carriage return), and the window is five seconds before the board starts a default that drives the motor. Nine attempts were needed to enter the menu once. The identification build sidesteps it entirely with `IDENT_AUTOSTART_MODE` in `edukit_system.h`: set to a mode letter (`w` `y` `d` `a` `u`), the firmware boots straight into that mode, no menu and no window. Selecting a mode is then a flash, and `st-flash` verifies it. A missed capture cannot fall through to the motor, because there is no default to fall through to. Set it to `0` to restore the interactive menu. Each mode costs one flash, and capture then needs only an open port.

The host side pairs with this through `scripts/capture_trace.py`. It recognises a board already streaming samples and starts recording without answering a prompt. The serial port is the ST-LINK's virtual COM port, a separate USB interface from the target, so it survives a reset and the mode's output arrives on a link already open.

The bench sessions run in a fixed order, each measurement feeding the next. The tilt sweep comes first (its map is the step-loss reference the others read against), then the ring-down, whose over-the-top segment also reads the encoder scale so no separate counts-per-revolution turn is needed, then the probe-lean unit probe and min-command ladder (supervised, it drives the motor), then the golden trace (supervised). The sweep's full turn showed the cable coils without binding, which replaces the hand measurement of the travel limit. The reasoning is in experiment 03. The repository git-ignores every image built from that source, so rebuilding is the only route to one. The swing-up retune is two constants in `edukit_system.h`, `STAGE_1_AMP` from 130 to 200 and `STAGE_2_AMP` from 120 to 160, and experiment 03 has the reasoning. The `bench` target carries more than that, adding modes `w` and `y`, per-impulse reporting, and the build banner below.

## Identifying the running build

Builds from this project print their identity before the mode prompt. Run `just hw-monitor` and press reset:

```text
BUILD ident (retuned swing-up; modes w y d a u; identification battery)
```

The build id is a target key in `config/firmware.yaml`, set by `FIRMWARE_BUILD` in `edukit_system.h`, with `FIRMWARE_BUILD_NOTE` supplying the parenthetical. Change both whenever behaviour changes, and record it here. The earlier `bench` build carried only modes `w` and `y`; `ident` adds `d`, `a`, `u` and the pre-wait timestamp. The supplied ST and UCLA image prints no such line. `hw-flash` identifies it by flash read-back.

# ADR-0004: modeling the swing-up kick as a driver position move

**Context:** simulation originally implemented a single actuator model: an acceleration command clamped at $11.78\text{ rad/s}^2$ and integrated into microstep-quantized position targets. That constant derived from firmware parameter `MAX_ACCEL` at $6000\text{ microsteps/s}^2$.

Comparing firmware source code with hardware telemetry on 2026-09-06 revealed two distinct physical actuation paths on the rotor:

1. Swing-up path: executes a blocking 200-microstep position move through the ST L6474 driver speed profile. Step rate starts at $800\text{ microsteps/s}$, or $1.571\text{ rad/s}$, on the first pulse, ramps at $6000\text{ microsteps/s}^2$, or $11.78\text{ rad/s}^2$, to $1348\text{ microsteps/s}$ at midpoint, ramps back down, and halts. Hardware telemetry measured $185.2\text{ ms}$ across 248 bench kicks compared to $185.1\text{ ms}$ calculated from driver arithmetic. The firmware pauses the 500 Hz control loop for the duration of each move.
2. Balance path: firmware bypasses driver speed profiling entirely, integrating discrete acceleration commands under a software clamp of $131{,}071\text{ microsteps/s}^2$, or $257.4\text{ rad/s}^2$. Telemetry from the baseline PID controller shows acceleration commands of 43 to $58\text{ rad/s}^2$ across 50 ms windows during catch transients, settling to $15\text{ rad/s}^2$ at the 99th percentile during steady hold. [Experiment 05](../experiments/05-balance/writeup.md) evaluated clamped energy pumping at 15, 20, and $30\text{ rad/s}^2$ against that profile and retrained at $40\text{ rad/s}^2$.

Neither value reflects an intrinsic physical torque limit of the stepper motor. Telemetry records driver step pulses rather than physical shaft angle from an encoder, so true motor torque authority and the boundary where step loss occurs remain unmeasured on hardware.

## Options

| Option | Assessment |
|---|---|
| Two models, one per path | Swing-up kicks run as blocking position moves on the L6474 profile, balance as continuous acceleration commands. Reproduces the firmware's two paths, and requires the simulation to carry two actuator modes |
| One acceleration model, clamp tuned to the kick duration | [Experiment 05](../experiments/05-balance/writeup.md) swept 15, 20 and $30\text{ rad/s}^2$. Each matched total kick duration at one operating point and distorted the velocity profile through the rest of the move. The driver jumps to $1.571\text{ rad/s}$ on the first pulse, which an acceleration ramp does not reproduce |
| One acceleration model at the $257.4\text{ rad/s}^2$ software clamp | That clamp is the limit the firmware permits in code. The stock PID commands 43 to $58\text{ rad/s}^2$ while catching, well below it. A policy trained to the clamp would command accelerations the motor cannot track |

**Decision:** model the swing-up and balance actuation paths separately.

Swing-up position moves run the driver profile as a blocking displacement of $N$ microsteps with `MIN_SPEED` of $1.571\text{ rad/s}$, an acceleration ramp of $11.78\text{ rad/s}^2$, and `MAX_SPEED` of $3.927\text{ rad/s}$ loaded from [`config/edukit.yaml`](../../config/edukit.yaml). The rotor holds stationary between kicks, while sensor sampling and policy evaluation pause during motion to match firmware execution. A scripted swing-up using this primitive and firmware kick logic validates directly against bench kick timing and half-swing amplitudes.

Balance policies operate on continuous acceleration commands, keeping $11.78\text{ rad/s}^2$ as a provisional nominal baseline. Higher acceleration bounds in simulation represent labeled hypotheses until a bench step-loss ladder measures physical torque authority on hardware. [Experiment 05](../experiments/05-balance/writeup.md) evaluated retraining at $40\text{ rad/s}^2$ on that provisional basis.

**Consequences:** simulated swing-up trajectories match physical firmware execution, ensuring that handover benchmarks evaluate policies against realistic arrival states at the 1.0-degree rate-free exit criterion used by hardware.

Catch metrics derived from the nominal $11.78\text{ rad/s}^2$ limit, including the $1.011\text{ rad/s}$ unstable modal recovery window and the $7.351$ modal coefficient, represent simulation conventions rather than physical plant limits. Baseline balance results from Experiment 05 remain valid under this nominal convention.

A bench step-loss ladder calibration must run before deploying any policy trained past $11.78\text{ rad/s}^2$ to hardware.

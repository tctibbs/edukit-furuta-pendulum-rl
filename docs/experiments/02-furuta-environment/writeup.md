# Experiment 02: The Furuta environment

## Goal

The goal for this experiment was to build the model for the Furuta in Isaac Lab as defined by [Milestone 02](../../milestones/M2-furuta-model.md). [Experiment 01](../01-cartpole-bringup/writeup.md) proved the toolchain on a cartpole. This one replaces the cartpole's torque joint with the Edukit's acceleration-commanded stepper and measures how throughput scales with parallel environment count.

## Setup

Building the training host, an RTX 5080 16 GB on driver 591.86, follows [Training host setup](../../runbooks/training-host-setup.md). Commands that run there assume the working directory is this repository, cloned beside the IsaacLab folder. Not all of the commands run there, though: the unit tests run locally from the repository root, and the figure scripts redraw them from this experiment's folder.

## The work

### The articulation

Isaac Lab builds on Isaac Sim, NVIDIA's robot simulator. Its physics engine is PhysX. The model is an articulation, a tree of rigid bodies connected by joints that PhysX solves as one system. [`src/furuta/articulation.py`](../../../src/furuta/articulation.py) generates it from the parameter file as a USD file, in the Universal Scene Description format Isaac Sim loads. When Isaac Lab loads that file, PhysX builds the articulation within its engine.

PhysX can simulate jointed bodies in maximal or reduced coordinates. In maximal coordinates each body has six degrees of freedom, and the solver pulls the joints back together every step with a small error left over. In reduced coordinates PhysX tracks only the joint angles and the joints can't separate. This model uses reduced coordinates.

The Edukit has three bodies:

- A base, fixed to the world
- An arm, turned by the stepper about the vertical axis `Z`
- A pendulum, hanging from the arm's tip on a passive joint about `X`

The pendulum swings in a plane that turns with the arm.

![The modeled geometry](./figures/model_spec.png)

*The geometry as modeled, generated from the parameter file by [model_spec.py](./figures/model_spec.py). `r` and `L` reach the dynamics. The arm height appears in the model but doesn't affect the dynamics. It only has to keep the pendulum off the floor. The rod radius is cosmetic. The inertia is calculated.*

[config.yaml](./config.yaml) pins the physical constants this experiment ran on. The last two rows are the resolutions the policy reads the rotor and pendulum angles in.

| Symbol | Quantity | Value | Where it comes from |
|---|---|---|---|
| `L` | pendulum length | 0.258 m | Manual App. D, Pendulum Dynamics, page 148 |
| `r` | arm length | 0.140 m | Manual Table 2, page 11 |
| `m` | pendulum mass | 0.050 kg | assumed |
| `g` | gravity | 9.806 m/s^2 | Manual App. D, Pendulum Dynamics, page 148 |
| `2*I_shaft/(m*L^2)` | shaft inertia, normalized | 0.0139 | Manual App. D, Pendulum Dynamics, page 148 |
| `Q` | quality factor of the free swing | 20 | Manual App. D, Pendulum Dynamics, page 150 |
| | microsteps per revolution | 3200 | Manual page 11, as 200 full steps of 16 |
| | encoder counts per revolution | 2400 | Manual Table 2, page 11 |

[`src/furuta/articulation.py`](../../../src/furuta/articulation.py) writes those bodies and the joints between them. It marks the model as an articulation by applying `PhysicsArticulationRootAPI` to the root prim. The environment reads joint angles and sets joint targets through Isaac Lab's `Articulation` class. Without the fixed joint to the world, the whole assembly would be free-floating and fall.

Each revolute joint is one call:

```python
_revolute_joint(
    ..., "/Furuta/base", "/Furuta/arm", "Z", (0.0, 0.0, ARM_HEIGHT_M), driven=True
)
_revolute_joint(..., "/Furuta/arm", "/Furuta/pendulum", "X", (r, 0.0, 0.0))
```

The anchor is a pair of positions, one in each body's frame. If the two disagree, the joint sits in the wrong place.

[`scripts/inspect_articulation.py`](../../../scripts/inspect_articulation.py) loads the asset without the environment and prints the bodies and joints PhysX parsed:

```powershell
..\.venv\Scripts\python.exe scripts\inspect_articulation.py --headless
```

### The derived inertia

[`src/furuta/parameters.py`](../../../src/furuta/parameters.py) turns those constants into the quantities a physics engine needs.

A swinging pendulum trades gravity against rotational inertia. The manual calls the natural frequency of that hanging swing `omega_g`, and the subscript marks the gravity mode. It comes from:

```math
\omega_g^2 = \frac{m \, g \, (L/2)}{I_\mathrm{pivot}}
\qquad\text{where}\qquad
I_\mathrm{pivot} = \tfrac{1}{3} m L^2 + I_\mathrm{shaft}
```

Every term carries one factor of `m`: the numerator and the rod term visibly, the shaft term because the manual publishes it normalized, as `2*I_shaft/(m*L^2)`. Mass cancels exactly, and keeping that normalized form in the parameter file is what preserves the cancellation.

The assumed 0.050 kg is therefore good enough for the swing frequency.

```python
rod = self.pendulum_mass_kg * self.pendulum_length_m**2 / 3.0
return rod + self.shaft_inertia_kg_m2
```

The `1/3` is a uniform rod about its end. The shaft term is the manual's `0.0139`, undone from the normalized form the manual prints. Together they give `omega_g^2 = 55.847 (rad/s)^2`. The manual publishes the same value rounded, as 55.85.

[`tests/test_parameters.py`](../../../tests/test_parameters.py) checks that, and the 57.01 the manual publishes without the shaft term. The tests run locally:

```bash
uv run --with pytest --with pyyaml --with torch --with numpy pytest tests/test_parameters.py -q
```

The manual's `Q` of 20 becomes viscous damping at the pivot. `parameters.py` computes `I_pivot * omega_g / Q`, and the environment applies it to the pendulum joint with zero stiffness, so the joint is undriven rather than frictionless.

Each body carries a mass, a center of mass and an inertia tensor, written explicitly:

```python
api = UsdPhysics.MassAPI.Apply(prim)
api.CreateMassAttr().Set(mass)
api.CreateCenterOfMassAttr().Set(Gf.Vec3f(0.0, 0.0, -length / 2.0))
api.CreateDiagonalInertiaAttr().Set(Gf.Vec3f(inertia_com, inertia_com, axial))
```

The center of mass sits at `-L/2`, halfway down the rod. Physics engines take inertia about the center of mass rather than the pivot, so `parameters.py` converts:

```math
I_\mathrm{com} = I_\mathrm{pivot} - m \left(\frac{L}{2}\right)^2
```

Rotation about `X` is the swing, so `Ixx` carries the derived value and `Iyy` matches it by symmetry. `Izz` is the rod's own long axis, where a 4 mm rod contributes almost nothing.

Isaac Lab's `MassPropertiesCfg` can express mass and density and nothing else, so a shape spawned through it gets its inertia inferred by PhysX from the drawn geometry. For a cylinder that inference gives a uniform rod of `(1/12) m L^2` about the center of mass. The shaft term drops out with nothing to report it. `omega_g^2` then lands on 57.01, which the manual publishes for the rod without its shaft. That's a 2 percent error in the plant.

Nothing here makes contact with anything, so the visual cylinders carry no collision geometry.

Generating the asset checks the written mass properties against the derivation and prints the comparison:

```powershell
..\.venv\Scripts\python.exe scripts\generate_articulation.py --output assets\edukit_pendulum.usda
```

The check reads mass, center of mass, and the two transverse inertias back from the saved file and compares them with the derivation. They match, and the check prints `omega_g^2` beside them from the parameters rather than recomputing it from the file. It reads the file on disk, though, not the articulation PhysX builds from it. Whether the values survive loading into PhysX stays untested here.

### The rotor drive

[`src/furuta/env.py`](../../../src/furuta/env.py) loads the asset and fills in the Direct-workflow callbacks. In that workflow the environment class itself implements observation, reward, termination, and reset. It registers as `Furuta-Balance-Direct-v0`. The template it departs from is `Isaac-Cartpole-Direct-v0` from [Experiment 01](../01-cartpole-bringup/writeup.md). That template writes a torque to its joint:

```python
self.cartpole.set_joint_effort_target(self.actions, joint_ids=self._cart_dof_idx)
```

`env.py` instead scales the action to the acceleration limit, integrates it into a step rate held under the motor's ceiling, integrates that into a position, quantizes it to whole microsteps, and drives the result as a position target. That mirrors the firmware's `apply_acceleration()`, described in Manual App. E, page 160. A microstep is the smallest motion the motor can make, 1/3200 of a revolution here.

```python
self._rotor_target = self._actuator.step(actions.squeeze(-1), PARAMS.control_dt_s)
...
self.robot.set_joint_position_target(
    self._rotor_target.unsqueeze(-1), joint_ids=self._rotor_idx
)
```

The actuator integrates once per control period at 500 Hz, while `_apply_action` runs once per physics substep at 1000 Hz, a decimation of 2 in Isaac Lab's term. The firmware does the same, updating its step rate on the control loop and emitting steps in between.

The environment builds observations from angles alone, passing them through the encoder and microstep lattices before differencing them into velocities, because the hardware has a 2400-count encoder and no velocity sensor. It rounds the pendulum angle to whole encoder counts. The rotor has no position sensor, so its angle is the one the actuator commanded rather than one read back from the simulation.

The reward is the pendulum's height, +1 upright and -1 hanging. Nothing trains against it yet, and `DirectRLEnv` requires one. An episode ends when the rotor passes its travel bound of pi radians, or after 10 s. A reset places the pendulum within 0.1 rad of hanging, so the environments don't all follow one trajectory.

A stepper holds its commanded position until it drops steps. Getting the simulated rotor to do the same took three versions of the joint's drive, each measured by tracking error.

Tracking error is the largest gap across environments between the rotor's angle and the position the actuator commanded. The bench reads it after the last step and converts it to microsteps. The following table reports the error at one environment. The corrected configuration reads 0.20 microsteps at 512 and 4096. Every run used a constant action. No run here has tested lag under a policy that reverses direction quickly.

| Configuration | Tracking error | Verdict |
|---|---|---|
| Generated USD as first written | 119.26 microsteps | The rotor barely moved |
| `DriveAPI` added, damping 1e3 | 15.52 microsteps | Moving, lagging badly |
| Damping corrected to 50 | 0.08 microsteps | Holding position |

The first failure was a missing `UsdPhysics.DriveAPI` on the rotor joint. Isaac Lab's implicit actuator, the PD drive inside PhysX, writes its stiffness and damping into a joint's drive, and a joint without one has nothing to write into. No torque reached the rotor. The environment still loaded, stepped, and produced rewards. 119 microsteps of error is roughly the whole distance the actuator asked the rotor to travel.

The second was self-inflicted, the gains chosen when adding that drive. The implicit actuator applies `K(target - q) - D*q_dot`, so damping appears as a lag proportional to speed. At `D = 1e3` and a rotor speed near 3.5 rad/s the damping term demands about 3500 N m. The stiffness term can only cancel that by sitting `3500 / 1e5 = 0.035` rad behind the target. The measured error was 0.030 rad. Critical damping for this rotor is `2*sqrt(K*I)`, about 21 for an inertia near 1.1e-3 kg m^2, so the value was roughly fifty times too large.

Recorded with the corrected drive:

![Rotor driving the pendulum](./figures/driven_rollout.gif)

*One environment, five seconds. A cosine acceleration drives the rotor at 420 control steps per cycle, the pendulum's 0.841 s natural period. Each cycle pumps the swing higher.*

The clip comes from:

```powershell
..\.venv\Scripts\python.exe -u scripts\record_environment.py --headless --num-envs 1 --steps 2500 --period-steps 420
```

### What a step costs

Throughput and tracking error both come from [`scripts/bench_environment.py`](../../../scripts/bench_environment.py), run on the training host. It's custom because Isaac Lab's training script measures throughput while a policy trains, and there is no policy here yet.

| Setting | |
|---|---|
| Warm-up steps | 20, untimed |
| Timed steps | 200, or 50 at one environment |
| Action | constant 0.25, which is 25 rad/s^2 of the 100 rad/s^2 limit |
| Runs per environment count | 1 |

Full configuration in [config.yaml](./config.yaml).

Throughput is the environment count divided by the time one step takes, so the shorter single-environment run gives the same rate.

Each count runs in its own process, because closing an Isaac Lab environment shuts down the simulator. Running each once means there is no spread behind these numbers.

```powershell
..\.venv\Scripts\python.exe -u scripts\bench_environment.py --headless --num-envs 4096 --steps 200
```

| Environments | Throughput (steps/s) | Step time | Rotor tracking error |
|---|---|---|---|
| 1 | 102 | 9.85 ms | 0.08 microsteps |
| 512 | 50,106 | 10.22 ms | 0.20 microsteps |
| 4096 | 409,876 | 9.99 ms | 0.20 microsteps |

One step is one control step: an action goes in, the actuator integrates it once at the 500 Hz control rate, physics advances the two 1000 Hz substeps a decimation of 2 buys, and the environment returns the next observation. Every environment advances 2 ms of simulated time in that step. Step time is the wall clock spent producing it. At 4096 environments, 9.99 ms of wall clock buys 8.2 s of simulated experience.

Going from 1 to 4096 environments multiplied throughput by 4018, and step time never left the band between 9.85 and 10.22 ms. The per-step cost doesn't depend on how many environments are stepping, the same result [Experiment 01](../01-cartpole-bringup/writeup.md) found on the cartpole.

[Experiment 01](../01-cartpole-bringup/writeup.md)'s cartpole reached 238,190 at the same count, but the two runs don't measure the same thing. That figure comes from Isaac Lab's training script and carries a PPO update this bench doesn't run. This bench didn't separate how much of the gap is the optimizer and how much is the scene. It didn't measure where memory binds either, and no count larger than 4096 ran.

![Throughput and tracking error](./figures/environment_results.png)

*Left: throughput against parallel environment count, log-log. The square is [Experiment 01](../01-cartpole-bringup/writeup.md)'s cartpole, read while a policy trained. Right: rotor tracking error for the three drive configurations, measured at one environment, log scale. Below the dashed line the rotor holds its commanded position.*

[`figures/plot_results.py`](./figures/plot_results.py) reads [`results.csv`](./results.csv) and [`tracking.csv`](./tracking.csv) beside this write-up, transcribed from what the bench runs printed:

```bash
uv run --with matplotlib python figures/plot_results.py
```

### Regenerating from a changed constant

Regenerating the asset from a copy of `config/edukit.yaml` with `pendulum_length_m` changed from 0.258 to 0.300, and no source edit:

```powershell
..\.venv\Scripts\python.exe scripts\generate_articulation.py --config C:\path\to\copy.yaml --output variant.usda
```

| Quantity | Predicted | Measured |
|---|---|---|
| Inertia ratio | 1.35208, from `(0.300/0.258)^2` | 1.35208 |
| omega_g^2 | 48.028, from `55.847 x 0.258/0.300` | 48.029 |
| Center of mass | -0.150 m, from `-L/2` | -0.150 m |

The articulation is therefore generated from the parameter file rather than hardcoded.

## Takeaway

The environment [Milestone 02](../../milestones/M2-furuta-model.md) asks for exists.

- The generator writes the calculated inertia into the asset. The asset's `omega_g^2 = 55.847 (rad/s)^2` matches the manual's 55.85 once rounded.
- The rotor tracks its commanded position to a fifth of a microstep.
- The environment runs at 409,876 steps/s across 4096 parallel environments, with step time flat at about 10 ms.
- The model rebuilds from a parameter-file edit, with no source change.

These rest on one machine and one run per environment count, with no seed set. [Experiment 01](../01-cartpole-bringup/writeup.md) measured its cartpole figure during training. Its step rate isn't directly comparable with this one.

## References

- [Experiment 01](../01-cartpole-bringup/writeup.md), the toolchain bring-up and the cartpole throughput this write-up compares against.
- [Training host runbook](../../runbooks/training-host-setup.md), the install with the seven defects it carries.
- [Milestone 02](../../milestones/M2-furuta-model.md), the acceptance criteria this work serves.
- [The parameter file](../../../config/edukit.yaml), the project's constants. Each value carries its source and its date.
- Edukit Manual, `docs/reference/Edukit_Manual.pdf`, fetched with `scripts/fetch_reference_docs.sh`. App. D, Pendulum Dynamics page 148 for `L`, `g`, and the normalized shaft inertia. Table 2 page 11 for `r`, the rotor gain, and encoder resolution. App. E page 160 for `apply_acceleration()`. The manual is copyright STMicroelectronics and Prof. William J. Kaiser, UCLA.

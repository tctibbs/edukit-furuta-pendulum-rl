# Experiment 02: Furuta environment

## Goal

Per [Milestone 02](../../milestones/M2-furuta-model.md), the objective is building the Furuta pendulum simulation model within Isaac Lab. Preceding work in [Experiment 01](../01-cartpole-bringup/writeup.md) validated the toolchain on a cartpole. Work here replaces the cartpole continuous torque joint with the Edukit acceleration-commanded stepper actuator and measures throughput scaling across parallel environment counts.

## Setup

Training host setup followed [Training host setup](../../runbooks/training-host-setup.md), utilizing an RTX 5080 with 16 GB video memory on driver 591.86. Remote commands run from the repository clone adjacent to the IsaacLab folder. Unit tests execute locally from the repository root, while plotting scripts regenerate figures from the experiment folder.

## The work

### Defining the model

The first step in building the simulation in Isaac Lab is understanding the model. The Furuta pendulum is a multibody system: three rigid bodies joined by two rotating joints.

- Base: the stand. It is fixed in place.
- Rotor arm: a horizontal arm that the stepper motor spins about the vertical axis `Z`.
- Pendulum: a rod hanging from the end of the rotor arm. It swings freely about `X`, the axis along the rotor arm, so its swing plane turns with the rotor arm.

![Model geometry](./figures/model_spec.png)

*The three bodies and their two joint axes, with dimensions from the configuration.*

The model's physical constants are set in [config.yaml](./config.yaml):

| Quantity | Symbol | Value | Source |
|---|---|---|---|
| Arm length | `r` | 0.140 m | Manual page 11 |
| Pendulum length | `L` | 0.258 m | Manual page 148 |
| Pendulum mass | `m` | 0.050 kg | Assumed, cancels out |
| Shaft inertia, normalized | `2*I_shaft/(m*L^2)` | 0.0139 | Manual page 148 |
| Quality factor | `Q` | 20 | Manual page 150 |
| Gravity | `g` | 9.806 m/s^2 | Manual page 148 |

The physical constants above introduce two new terms:

- Shaft inertia, normalized: rotational inertia is resistance to being spun up. It is the rotational equivalent of mass. Most of the pendulum's mass is in the rod. The shaft and other parts that turn with it add a little more inertia. The manual infers it from the measured swing frequency and gives it as a ratio to `m*L^2/2`.
- Quality factor `Q`: how long a free swing lasts before friction in the pivot stops it. At `Q = 20`, each swing is about 15 percent smaller than the last. The model applies this as damping, a friction torque at the pendulum joint.

### Simulating the physics

For the physics engine to simulate the pendulum, the model has to represent its mechanics correctly. Those mechanics split into two types, kinematics and dynamics.

Kinematics describes how things move: where each body is, how fast each one is going, and how quickly that is changing. In this model, two angles describe most of it: the arm angle `φ` and the pendulum angle `θ`. The rotor arm is the one part under direct control. The stepper moves it as commanded, so kinematics controls its motion. [Modeling the actuator and sensors](#modeling-the-actuator-and-sensors) explains how the actuator does it.

Dynamics describes why things move: the forces behind the motion. Nothing in this model drives the pendulum directly, so how it swings comes down to four things:

- **Gravity**: pulls the rod down. A hanging pendulum settles back like a ball in a valley. An upright one is a ball balanced on a hilltop. Any small tilt grows until it falls.
- **Rotational inertia**: how hard the rod is to speed up or slow down. It is the rotational counterpart of mass, and it depends on where the mass sits as well as how much there is. A hammer held by the end of its handle is much harder to swing than one held near its head. The rod pivots at one end, and most of its resistance comes from its far half.
- **Coupling**: how the motor reaches the rod. The motor can only turn the arm, and the arm can only push on the rod at the pivot. When the pivot moves sideways, the free end lags behind and the rod tilts. A hanging broom does the same when the hand holding it jerks. Upright, the same push keeps the rod balanced. Moving the pivot under the lean tips the rod back toward vertical. Balancing a broom on a palm works the same way.
- **Friction**: the pivot bearing takes a little energy out of every swing, and a free swing slowly dies out. A playground swing that nobody pushes does the same. The quality factor `Q` measures how slowly.

PhysX computes all of this on every simulation step, but only from the numbers the model gives it: gravity, each body's inertia, and the pivot damping. Matching those to the real unit is the model's main job. PhysX can keep track of the bodies in one of two ways:

- Maximal coordinates: each body moves on its own, and the solver pulls the joints back into place every step. The joints hold only approximately. Best for loose objects and joints that can break.
- Reduced coordinates: PhysX arranges the bodies as a tree, called an articulation, where each body hangs off its parent through a joint. PhysX tracks only the joint angles, computes each body's position from them, and uses the body masses to work out the motion. The joints hold exactly. Best for robot arms and other jointed chains.

The model uses reduced coordinates. Its joints are rigid hinges, and the joint angles are exactly what the board measures. From here on, the code and documentation call the model an articulation, following the PhysX term.

### Building the articulation

Isaac Sim reads the articulation from a Universal Scene Description (USD) file. The file holds each body's shape and mass and the joints between them. [`src/furuta/articulation.py`](../../../src/furuta/articulation.py) generates this file from the physical constants above, using UsdPhysics, the physics extension to USD. UsdPhysics provides schemas: standard sets of physics properties that attach to entries in the scene. The script uses six:

- `RigidBodyAPI` makes an entry a body that physics moves.
- `MassAPI` sets a body's mass and inertia, covered in [Deriving rotational inertia](#deriving-rotational-inertia).
- `RevoluteJoint` joins two bodies with a rotating joint.
- `DriveAPI` drives the rotor arm's joint, covered in [Modeling the actuator and sensors](#modeling-the-actuator-and-sensors).
- `FixedJoint` pins the base to the world.
- `ArticulationRootAPI`, on the top-level `/Furuta` entry, marks everything below it as one articulation.

The schemas come in two kinds. Joints are entries of their own, created with `Define`. The `API` schemas add properties to an existing entry, attached with `Apply`. The pendulum pivot shows both. The script creates it through a helper, linking the rotor arm to the pendulum about `X` at the arm's tip:

```python
_revolute_joint(
    stage,
    "/Furuta/pendulum_joint",
    "/Furuta/arm",
    "/Furuta/pendulum",
    "X",
    (r, 0.0, 0.0),
)
```

Inside the helper, `Define` creates the joint and `Apply` gives it a drive:

```python
joint = UsdPhysics.RevoluteJoint.Define(stage, path)
...
drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), "angular")
```

Before any training, a separate script checks that PhysX reads the file as intended. [`scripts/inspect_articulation.py`](../../../scripts/inspect_articulation.py) loads the USD file on its own, without the training environment, and prints the bodies and joints PhysX found. `--headless` runs it without a display window:

```powershell
..\.venv\Scripts\python.exe scripts\inspect_articulation.py --headless
```

#### Deriving rotational inertia

Module [`src/furuta/parameters.py`](../../../src/furuta/parameters.py) converts physical constants into rigid body tensors.

A swinging pendulum balances gravity against rotational inertia. Natural frequency `omega_g` for small-amplitude hanging oscillation derives from:

```math
\omega_g^2 = \frac{m \, g \, (L/2)}{I_\mathrm{pivot}}
\qquad\text{where}\qquad
I_\mathrm{pivot} = \tfrac{1}{3} m L^2 + I_\mathrm{shaft}
```

Every term in pivot inertia carries a factor of `m`: the uniform rod term visibly, and the shaft term through normalized manual parameter `2*I_shaft/(m*L^2) = 0.0139`. Mass cancels from numerator and denominator, leaving natural frequency dependent on length and normalized shaft inertia rather than absolute mass:

```python
rod = self.pendulum_mass_kg * self.pendulum_length_m**2 / 3.0
return rod + self.shaft_inertia_kg_m2
```

The uniform rod term plus normalized shaft inertia yields `omega_g^2 = 55.847 rad^2/s^2`, matching the rounded 55.85 published in the manual.

Standard Isaac Lab `MassPropertiesCfg` specifications only configure total mass or density, leaving rotational inertia to PhysX geometric inference. For a cylinder, PhysX infers uniform rod inertia `(1/12) m L^2` about the center of mass, omitting bearing collars alongside shaft hardware. That omission increases predicted `omega_g^2` to 57.01 rad^2/s^2, injecting a 2 percent modeling error.

To capture the true dynamics, `src/furuta/articulation.py` shifts calculated pivot inertia to the center of mass at `-L/2` through the parallel-axis theorem:

```math
I_\mathrm{com} = I_\mathrm{pivot} - m \left(\frac{L}{2}\right)^2
```

The generator then authors explicit diagonal inertia tensors directly onto the USD prim:

```python
api = UsdPhysics.MassAPI.Apply(prim)
api.CreateMassAttr().Set(mass)
api.CreateCenterOfMassAttr().Set(Gf.Vec3f(0.0, 0.0, -length / 2.0))
api.CreateDiagonalInertiaAttr().Set(Gf.Vec3f(inertia_com, inertia_com, axial))
```

Transverse moments `Ixx` and `Iyy` share identical values by symmetry, while axial moment `Izz` along the narrow rod contributes negligible resistance. Pivot damping evaluates to `I_pivot * omega_g / Q` from manual quality factor `Q = 20`, applied to the pendulum joint with zero stiffness to model a passive, lightly damped bearing.

Local unit tests validate parameter calculations against manual benchmarks:

```bash
uv run --with pytest --with pyyaml --with torch --with numpy pytest tests/test_parameters.py -q
```

Running asset generation confirms that authored USD properties match the derivation:

```powershell
..\.venv\Scripts\python.exe scripts\generate_articulation.py --output assets\edukit_pendulum.usda
```

#### Verifying parametric generation

A verification test changed `pendulum_length_m` from 0.258 m to 0.300 m in a copy of `config/edukit.yaml` and reran asset generation without modifying source code:

```powershell
..\.venv\Scripts\python.exe scripts\generate_articulation.py --config C:\path\to\copy.yaml --output variant.usda
```

| Quantity | Predicted | Measured |
|---|---|---|
| Inertia scaling ratio | 1.35208, from `(0.300/0.258)^2` | 1.35208 |
| Natural frequency `omega_g^2` | 48.028 rad^2/s^2, from `55.847 x 0.258/0.300` | 48.029 rad^2/s^2 |
| Center of mass | -0.150 m, from `-L/2` | -0.150 m |

The output confirms that USD assets generate parametrically from configuration files rather than hardcoded geometries.

### Modeling the actuator and sensors

An actuator is whatever turns a control command into motion. On the Edukit, the actuator for the rotor arm is a chain of three parts. The firmware on the STM32 board turns each acceleration command into a stream of microsteps. The L6474 driver on the IHM01A1 shield powers the motor coils for each step. The stepper motor then turns the rotor arm. The environment has to reproduce this chain in simulation.

Environment class [`src/furuta/env.py`](../../../src/furuta/env.py) implements the DirectRLEnv workflow under registration key `Furuta-Balance-Direct-v0`. The cartpole template from [Experiment 01](../01-cartpole-bringup/writeup.md) applies joint effort directly:

```python
self.cartpole.set_joint_effort_target(self.actions, joint_ids=self._cart_dof_idx)
```

The Edukit hardware accepts no direct torque commands. Instead, firmware routine `apply_acceleration()` in Manual Appendix E, page 160, integrates acceleration commands into discrete microstep position targets. The environment replicates that firmware pipeline:

```python
self._rotor_target = self._actuator.step(actions.squeeze(-1), PARAMS.control_dt_s)
...
self.robot.set_joint_position_target(
    self._rotor_target.unsqueeze(-1), joint_ids=self._rotor_idx
)
```

In simulation, [`AccelerationCommandActuator`](../../../src/furuta/actuator.py) stands in for the firmware and the motor. It turns each acceleration command into a position for the rotor arm with the kinematic equations, once per control step of length `Δt`:

```math
\omega_{k+1} = \mathrm{clip}\left(\omega_k + \alpha\,\Delta t,\ \pm\omega_\mathrm{max}\right)
\qquad
\phi_{k+1} = \phi_k + \omega_{k+1}\,\Delta t
```

The policy's action `a`, between -1 and 1, is multiplied by the 100 rad/s^2 limit to give the acceleration `α`. That limit is assumed. The motor's torque bounds it, and nothing has measured it on this unit yet. The arm speed `ω` is capped at the stepper's top rate of 10,000 microsteps per second, 19.6 rad/s. The new arm angle `φ` is rounded to whole microsteps and becomes the target the joint drive holds. No forces enter the calculation.

The actuator updates once every 2 ms, the 500 Hz loop rate of the Edukit firmware (Manual Appendix E, Section 19). The policy sees the same timing it will face on the board. PhysX runs twice as fast, with two 1 ms substeps per command, because a finer physics step keeps the simulated motion accurate between commands. The physics rate has to be a whole multiple of the control rate, so that each command covers whole substeps. Isaac Lab calls that multiple the decimation, here 2.

Two hardware resolutions set the quantization below, both from Manual page 11. The stepper takes 3200 microsteps per revolution, 200 full steps of 16 microsteps each. The encoder reads 2400 counts per revolution.

![Actuator and observation pipeline](./figures/actuator_pipeline.png)

*The actuator and observation loop. Along the bottom, the stepper firmware is emulated once per 2 ms control step, and PhysX holds the resulting target for two 1 ms substeps. Along the top, the sensing is emulated: the pendulum angle is read through the encoder, and the rotor reading is the command itself.*

A sensor does the reverse of an actuator. It turns motion into a reading. The Edukit's only sensor is an optical encoder on the pendulum pivot. The rotor arm has none. The observations the policy receives follow those limits:

- Pendulum angle rounds to discrete increments of the 2400-count optical encoder, differencing positions across steps to compute angular velocity.
- Rotor observations provide commanded microstep angles because the stepper runs open loop without an encoder.

The reward evaluates pendulum height, +1 upright and -1 hanging. Episodes end after 10 seconds or when the rotor exceeds pi radians of travel.

#### Resolving rotor tracking error

Physical stepper motors hold commanded angles rigidly. Matching that holding stiffness required diagnosing drive tracking errors across three iterations:

| Configuration | Tracking error | Behavior |
|---|---|---|
| Initial USD export | 119.26 microsteps | Rotor remained stationary |
| Added `DriveAPI`, damping 1000 | 15.52 microsteps | Severe velocity lag |
| Corrected damping to 50 | 0.08 microsteps | Stiff position holding |

Tracking error represents the largest angular difference between commanded targets and simulated positions.

The initial failure came from omitting schema `UsdPhysics.DriveAPI` on the rotor joint. Isaac Lab also uses the word actuator, for its joint drive models. Its implicit actuators write proportional-derivative PD targets into joint drives, so joints lacking `DriveAPI` receive no torque despite normal simulation execution. Commanded travel was 119 microsteps, meaning the rotor never moved.

Adding `DriveAPI` with damping `D = 1000 N s/rad` introduced severe velocity lag. Implicit actuators apply torque:

$$\tau = K(q_\mathrm{target} - q) - D \dot{q}$$

At rotor speeds near 3.5 rad/s, damping demanded 3500 N m of counter-torque, forcing stiffness `K = 1e5` to sit 0.035 rad behind target. Critical damping `2*sqrt(K*I)` for rotor inertia 1.1e-3 kg m^2 evaluates to roughly 21 N s/rad, making 1000 nearly fifty times overdamped. Reducing damping to 50 brought tracking error down to 0.08 microsteps.

Driven rollout verification demonstrates dynamic coupling under the corrected drive:

![Rotor driving the pendulum](./figures/driven_rollout.gif)

*Rollout over five seconds. A cosine acceleration tuned to the 0.841-second natural period, 420 control steps at 500 Hz, drives the rotor, pumping swing amplitude higher on each cycle.*

```powershell
..\.venv\Scripts\python.exe -u scripts\record_environment.py --headless --num-envs 1 --steps 2500 --period-steps 420
```

### Measuring throughput scaling

Benchmark script [`scripts/bench_environment.py`](../../../scripts/bench_environment.py) measures environment stepping throughput on the training host without policy training overhead:

| Setting | Value |
|---|---|
| Warm-up steps | 20 steps, untimed |
| Timed steps | 200 steps, or 50 at single-environment scale |
| Action | constant 0.25, requesting 25 rad/s^2 acceleration |
| Runs per environment count | 1 execution sweep |

```powershell
..\.venv\Scripts\python.exe -u scripts\bench_environment.py --headless --num-envs 4096 --steps 200
```

| Environments | Throughput in steps/s | Step duration | Rotor tracking error |
|---|---|---|---|
| 1 | 102 | 9.85 ms | 0.08 microsteps |
| 512 | 50,106 | 10.22 ms | 0.20 microsteps |
| 4096 | 409,876 | 9.99 ms | 0.20 microsteps |

One control step advances 2 ms of simulated time. Step duration measures elapsed wall clock spent computing that step. At 4096 environments, 9.99 ms of wall clock computes 8.2 seconds of simulated experience.

Scaling from 1 to 4096 environments multiplied throughput by 4018, while step duration stayed flat between 9.85 ms and 10.22 ms. Per-step cost shows negligible dependence on parallel batch width, matching the scaling behavior observed on the cartpole in [Experiment 01](../01-cartpole-bringup/writeup.md).

Cartpole training reached 238,190 steps/s in Experiment 01, measured during active PPO policy updates. The benchmark here isolates physics stepping, establishing throughput before adding policy optimization.

![Throughput and tracking error](./figures/environment_results.png)

*Left: throughput scaling against environment count on logarithmic axes. The reference square marks the [Experiment 01](../01-cartpole-bringup/writeup.md) cartpole benchmark measured during policy training. Right: rotor tracking error across drive configurations on logarithmic scale. Values below the dashed line confirm stable commanded position tracking.*

Plotting script [`figures/plot_results.py`](./figures/plot_results.py) reads [`results.csv`](./results.csv) and [`tracking.csv`](./tracking.csv):

```bash
uv run --with matplotlib python figures/plot_results.py
```

## Takeaway

The simulation environment fulfills [Milestone 02](../../milestones/M2-furuta-model.md) acceptance criteria:
- Asset generation embeds calculated rotational inertia directly into USD prims, matching manual frequency `omega_g^2 = 55.85 rad^2/s^2`.
- The rotor drive emulates microcontroller acceleration stepping, tracking commanded positions to 0.08 microsteps.
- Stepping throughput scales to 409,876 steps/s across 4096 parallel environments, with step duration flat at 10 ms.
- USD assets rebuild parametrically from configuration edits without source modifications.

## References

- [Milestone 02](../../milestones/M2-furuta-model.md): simulation environment acceptance criteria.
- [Experiment 01](../01-cartpole-bringup/writeup.md): toolchain validation and baseline cartpole throughput comparisons.
- [Training host setup](../../runbooks/training-host-setup.md): remote workstation installation and environment configuration.
- [Edukit system parameters (`config/edukit.yaml`)](../../../config/edukit.yaml): mechanical constants and parameter provenance.
- Edukit manual reference: documentation by STMicroelectronics and Professor William J. Kaiser, UCLA, accessible in `docs/reference/Edukit_Manual.pdf` via `scripts/fetch_reference_docs.sh`. Appendix D, Pendulum Dynamics page 148 for `L` and normalized shaft inertia, and page 150 for `Q`. Table 2 page 11 for `r`, rotor gain, and encoder resolution, and the same page for microsteps per revolution. Appendix E page 160 for `apply_acceleration()`.

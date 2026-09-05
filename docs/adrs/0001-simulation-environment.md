# ADR-0001: NVIDIA Isaac Lab as the simulation environment

**Context:** training happens in simulation before the policy runs on hardware. The Edukit Manual derives a linearized Furuta model in App. D, Pendulum Dynamics, and validates it against a measured frequency response. Two rotational degrees of freedom, so four states and one action. No computer-aided design geometry, nothing collides. A simulator here would implement a known differential equation.

The rotor is a stepper taking acceleration commands, a double integrator with microstep quantization and a step-rate ceiling. The Edukit Manual covers it in App. E. No simulator provides a stepper model, so it needs a custom implementation regardless.

## Options

| Option | Assessment |
|---|---|
| Custom analytical integrator | A hundred lines around a fixed-step integrator. Integrates the App. D model directly with no physics engine in between, and vectorizes trivially. The best technical fit |
| Isaac Lab on Isaac Sim | GPU-parallel by design, config-driven domain randomization, USD asset pipeline. Large install, CUDA required, API churn between releases. Overkill for four states |
| MuJoCo, optionally MJX | Mature and accurate, CPU-only, with GPU-parallel rollouts through MJX. Its Furuta examples all drive a torque actuator, so none of them avoids the custom stepper implementation |
| Brax | GPU-parallel and JAX-native. More tooling than the custom integrator, less than Isaac Lab. No USD pipeline to learn, no event system |
| PyBullet, Gazebo | No advantage over MuJoCo and less current RL use |

**Decision:** use Isaac Lab on Isaac Sim.

For four states the custom integrator is arguably the better choice, and it reproduces the manual's dynamics exactly. That said, a goal of this project is to learn Isaac Lab: the Direct-workflow environment API, building a USD articulation from parameters, GPU-parallel rollouts, and config-driven domain randomization. A hand-written integrator exercises none of those, and this pendulum is small enough to serve as a good introduction.

**Consequences:** Training needs a CUDA GPU, so it happens on a separate training host ([ADR-0002](0002-training-host.md)). The dependency surface is large: Isaac Sim, Omniverse Kit, CUDA, PyTorch, with API churn between releases. [Milestone 01](../milestones/M1-isaac-lab-bringup.md) pins those versions in `pyproject.toml` under `[tool.furuta.simulation-stack]`.

PhysX can disagree with the analytical model, and by how much is unknown until a hardware trace exists. The gate is a free-swing comparison at [Milestone 03](../milestones/M3-hardware-bringup.md). Frequency must match within 2 percent and the decay envelope within 10 percent. Missing it reopens this record, with the custom integrator as the fallback.

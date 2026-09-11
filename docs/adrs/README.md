# Architecture decision records

Each file here holds one accepted decision in Architecture Decision Record (ADR) form. The numbers run in the order the decisions arrived.

A decision belongs here when a reasonable engineer could have chosen otherwise and the choice is expensive to revisit: the simulator, the training host, the learning algorithm, the actuator model.

Reward weights and reset distributions change with the task. They live with the experiment that set them and the code that reads them, not here.

| # | Decision |
|---|---|
| [ADR-0001](0001-simulation-environment.md) | NVIDIA Isaac Lab as the simulation environment |
| [ADR-0002](0002-training-host.md) | Train on the Windows host, driven headless over SSH |
| [ADR-0003](0003-training-algorithm.md) | Training with rsl_rl PPO at [32, 32] |
| [ADR-0004](0004-two-actuator-paths.md) | Modeling the swing-up kick as a driver position move |
| [ADR-0005](0005-observation-space.md) | Observation space: a unit vector and two fitted rates |
| [ADR-0006](0006-walked-rotor-target.md) | Walk the rotor's drive target across the control period |

# ADR-0003: training with rsl_rl PPO at [32, 32]

**Context:** initial balance policy training in [Milestone 05](../milestones/M5-balance.md) is the first time this project trains on its own environment. This milestone requires choosing both a reinforcement learning algorithm and a neural network architecture before training starts.

Streaming observations to a workstation and returning actions over serial introduces 86 ms of round-trip latency, measured in [Experiment 03](../experiments/03-hardware-bringup/writeup.md), far too slow for a 500 Hz, 2 ms balance loop. Policy inference must therefore run locally on the STM32F401RE microcontroller, an 84 MHz ARM Cortex-M4F. Forward inference must finish well inside the 2 ms control step to leave headroom for sensor acquisition and motor stepping.

Milestone 05 also serves to validate the simulation environment itself. If initial training produces a flat learning curve, diagnosing the root cause requires determining whether the fault lies in environment modeling, such as coordinate conventions, observation scaling, or reward formulation, or in algorithmic instability. Using an algorithm already proven on this exact software and hardware stack eliminates the optimizer as an unknown variable during debugging.

## Options: algorithm

| Option | Assessment |
|---|---|
| PPO from `rsl_rl` | Converged on cartpole in [Experiment 01](../experiments/01-cartpole-bringup/writeup.md) on this host and stack. On-policy, so PPO discards rollouts after each update. At 1024 environments sample collection costs little wall-clock time, with Experiment 01 holding 0.27 s per iteration across all swept batch widths |
| Soft actor-critic | Off-policy replay improves sample efficiency, but parallel GPU rollouts are already fast and cheap. An unproven algorithm on this stack would leave flat learning curves confounded between environment defects and optimizer divergence |
| Deep Q-network | Estimates one value per discrete action. The command is a continuous rotor acceleration, so a discrete policy would have to quantize it. The rotor has 7.83 degrees of arrest authority, and quantization consumes part of that. A quantized command also removes the continuous gradient of the action-rate penalty, which is what damps chatter on the real unit |
| A PPO written here | Reimplements an existing optimizer. The project's subject is Isaac Lab and sim-to-real transfer |

## Options: network size

| Option | Assessment |
|---|---|
| `[32, 32]` | 1281 weights. Compiles into microcontroller flash as constant C arrays and runs inside the 2 ms step beside the existing control code |
| `[64, 64]` or wider | More capacity than balancing near upright needs. Longer inference on the Cortex-M4F. A control-step overrun appears after a training run completes, not before it starts |
| A single hidden layer | Fewer weights again. The board has headroom at `[32, 32]`, so the reduction addresses no measured constraint |

**Decision:** train with Proximal Policy Optimization (PPO) using `rsl_rl`, with two-layer multilayer perceptrons sized at `[32, 32]` using exponential linear unit activations for actor and critic networks. Hyperparameters adapt from the Experiment 01 cartpole configuration, recalculating the step-counted rollout and discount horizons for the 500 Hz control frequency in [`src/furuta/agents/rsl_rl_ppo_cfg.py`](../../src/furuta/agents/rsl_rl_ppo_cfg.py).

**Consequences:** early training failures in Milestone 05, recorded as Runs 1, 2, and 4 in the [balance logbook](../experiments/05-balance/logbook.md), quickly traced to environment modeling and reward configuration defects, because Experiment 01 had already verified the identical training pipeline to convergence.

Sample efficiency never limited training performance. In Experiment 01, 1024 parallel environments achieved 57 steps per second per environment with iteration times remaining flat at 0.27 seconds regardless of batch width.

The exported `[32, 32]` network ran at 500 Hz on the board. The control-step overrun found there was the firmware's blocking serial write, recorded as Experiment 05's second hardware defect, rather than network compute. Standalone inference time on the microcontroller remains unmeasured, so exact execution headroom beyond `[32, 32]` is unknown.

No comparative multi-algorithm benchmark ran for this milestone. The decision rests on verified convergence in Experiment 01 and the strict microcontroller execution deadline. Soft Actor-Critic remains a candidate for re-evaluation in [Milestone 06](../milestones/M6-swing-up.md) if extended swing-up rollout trajectories make simulation sample collection a limiting factor.

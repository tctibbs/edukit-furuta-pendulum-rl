# Experiment 01: Isaac Lab bring-up

## Goal

Per [Milestone 01](../../milestones/M1-isaac-lab-bringup.md), the goal is to get Isaac Lab running on a training host and confirm the built-in cartpole simulation trains, before writing any code for the project.

## Setup

Training host setup followed [Training host setup](../../runbooks/training-host-setup.md), executing remote commands from the provisioned IsaacLab folder. The workstation manages SSH tunneling for live monitoring, while local plotting scripts regenerate the learning-curve figure from the experiment folder.

## The work

### Driving the training host over SSH

Initial hardware planning centered on a local Linux server. However, the installed GPU lacked the dedicated hardware ray-tracing cores mandatory for Isaac Sim, disqualifying the machine despite adequate driver versions and system memory. Architecture Decision Record [ADR-0002](../../adrs/0002-training-host.md) documents the architectural context in detail. A Windows machine housing an RTX 5080 served as the primary fallback, accessible exclusively over SSH.

Remote connectivity verification centered on confirming headless initialization of the Direct3D 12 graphics device, GPU memory allocation, and logging of `Using device: cuda:0`:

```powershell
..\.venv\Scripts\python.exe scripts\tutorials\00_sim\create_empty.py --headless
```

Execution confirmed successful Direct3D 12 device initialization and active physics computation on `cuda:0`.

### Training the stock cartpole end to end

End-to-end testing exercised Isaac Lab's built-in Cartpole task (`Isaac-Cartpole-Direct-v0`), the closest baseline to the rotary inverted pendulum and an environment pre-equipped with known-good hyperparameters.

Training executed across 50 iterations with 4096 parallel environments. Full configuration settings reside in [config.yaml](./config.yaml).

```powershell
# command to run the stock cartpole training
..\.venv\Scripts\python.exe scripts\reinforcement_learning\rsl_rl\train.py --task=Isaac-Cartpole-Direct-v0 --headless --max_iterations 50
```

TensorBoard on the local workstation tracked training progress via the SSH tunnel, following the procedure in [Training host setup](../../runbooks/training-host-setup.md#watch-a-run-from-the-workstation).

| Metric | Value |
|---|---|
| Mean reward, iteration 0 | -5.40 |
| Mean reward, iteration 49 | 269.81 |
| Mean episode length, iteration 49 | 275.5 of 300 steps, 92% |
| Throughput at 4096 environments | 238,000 steps/s |
| Wall clock, 50 iterations | about 13 s |
| Seeds | 1, preliminary |
| Total environment steps | 3.28 M |

Mean reward and episode length climb steadily through iteration 49. Execution concluded via the `--max_iterations 50` boundary before performance plateaued, demonstrating active policy improvement. Episode length rises with training as the cartpole learns to balance the pole for longer.

![Learning curve](./figures/learning_curve.png)

*Mean reward at left and mean episode length at right, per training iteration, across 4096 environments, single seed. The dashed line marks the 300-step episode cap.*

| Iteration 0 | Iteration 49 |
|---|---|
| ![untrained](./figures/untrained.gif) | ![trained](./figures/trained.gif) |

*Full 5-second episode rollout across 36 of the 4096 environments. Left illustrates the initial checkpoint at iteration 0. Right demonstrates stabilized balance at iteration 49.*

### Measuring throughput against environment count

Running many simulations at once is the primary reason to use a GPU-based simulator, so the sweep below measures the scaling benefit.

The sweep runs 50 iterations across 64, 512, and 4096 parallel environments, holding all other settings constant between runs. Isaac Lab prints a steps-per-second figure every iteration, and the median of the final ten iterations is the reported number.

| Environments | Throughput in steps/s | Relative to 64 envs | Per environment in steps/s | Iteration time |
|---|---|---|---|---|
| 64 | 3,640 | 1.0x | 56.9 | 0.27 s |
| 512 | 28,924 | 7.9x | 56.5 | 0.27 s |
| 4096 | 238,190 | 65.4x | 58.2 | 0.27 s |

Multiplying the environment count by 64 expanded aggregate sampling throughput by 65x. Per-environment throughput remained stable at approximately 57 to 58 steps per second, while iteration duration remained fixed at 0.27 seconds. Under these conditions, per-iteration runtime cost shows no dependence on environment batch width.

## Takeaway

Isaac Lab operates and trains reliably on the Windows host. The software stack trains a standard cartpole model to 92 percent of the maximum episode length in approximately 13 seconds on an RTX 5080, driven headlessly over SSH from a workstation lacking dedicated GPU hardware. Side-by-side rollout recordings demonstrate rapid behavioral convergence from untrained random exploration to stable upright balance.

Simulation throughput scales linearly through 4096 environments because iteration duration remains pinned at 0.27 seconds regardless of batch width. At the scale required for the Furuta pendulum project, the marginal compute cost of additional parallel environments remains negligible.

## References

- [ADR-0001](../../adrs/0001-simulation-environment.md), architectural evaluation justifying Isaac Lab for simulation.
- [ADR-0002](../../adrs/0002-training-host.md), hardware requirements and architectural justification for headless remote compute over SSH.
- [Training host runbook](../../runbooks/training-host-setup.md), host installation walkthrough and documented resolutions for upstream installation defects.
- [Isaac Sim system requirements](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html), official ray-tracing hardware criteria and baseline GPU specifications.
- [Isaac Lab pip installation](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html), published reference procedure corrected during project provisioning.

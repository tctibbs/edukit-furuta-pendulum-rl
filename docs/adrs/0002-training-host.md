# ADR-0002: Train on the Windows host, driven headless over SSH

**Context:** an earlier Architecture Decision Record (ADR) fixed the simulator. [ADR-0001](0001-simulation-environment.md) chose Isaac Lab and its strict machine requirements.

Isaac Sim's renderer sits on the Kit SDK and needs hardware ray tracing, so NVIDIA lists GPUs without RT cores as unsupported even when training headless. Isaac Sim 5.1.0 also states an RTX 4080 16 GB minimum, 32 GB of system RAM, and Windows 11 or Ubuntu 22.04 to 24.04.

## Options

| Machine | Assessment |
|---|---|
| Windows host | RTX 5080, 16 GB, driver 591.86, 8-core CPU, 32 GB RAM, read from `nvidia-smi`. Clears the published minimum, and Isaac Lab supports Windows as a first-class target |
| Linux server | GTX 1080 Ti, which predates RT cores, so Isaac Sim will not run on it at all |
| macOS workstation | No CUDA GPU. It also holds the serial link to the pendulum, so training here would put the simulator and the hardware on one machine |

**Decision:** training runs on the Windows host, headless, driven over SSH. Metrics come back through an SSH port-forward, and rollouts are recorded to video and copied down.

**Consequences:** training and hardware work live on separate machines, so a run needs network access to the host. They can also proceed at the same time without competing for one machine.

There is no interactive viewport, so debugging happens through logged traces and recorded video. Both `scp` and `sftp` fail against this host, so copying those files down needs the workaround in the [runbook](../runbooks/training-host-setup.md).

Isaac Lab's container workflow is Linux only and unavailable while the host runs Windows.

# Training host setup

Procedures for provisioning the Isaac Lab environment on a Windows 11 host with an RT-core GPU, driven headlessly from a remote workstation over SSH.

End-to-end verification completed on 2026-08-13 against Isaac Sim 5.1.0 and Isaac Lab v2.3.2. Architecture Decision Record [ADR-0002](../adrs/0002-training-host.md) documents host selection rationale.

Follow the instructions below alongside NVIDIA's [pip installation guide](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html). The standard installation workflow encounters several package defects. Documented resolutions appear below.

Remote commands targeting the host designate the machine as `GPU_HOST`. Substitute the corresponding hostname from the local SSH client configuration (`~/.ssh/config`).

## Requirements

GPU architecture requires verification before proceeding. Regardless of driver revision or total video memory, Isaac Sim refuses execution on GPUs lacking hardware RT cores. The underlying Kit renderer requires dedicated ray-tracing hardware even during headless training sessions.

```powershell
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
```

NVIDIA documentation for Isaac Sim 5.1.0 specifies a GeForce RTX 4080 16 GB minimum and lists validation against Windows driver 580.88. Allocate at least 100 GB of storage: while official documentation lists a 50 GB baseline, unpacking the `extscache` dependencies alongside pip cache artifacts exceeds 50 GB. Test hardware verified: RTX 5080 with 16303 MiB on driver 591.86, Ryzen 7 9800X3D, 32 GB RAM, Windows 11 build 26200.

## Install

Establish a working directory on the host for the installation. Execute all subsequent commands from this location. The virtual environment populates `.venv` within the chosen directory, and Isaac Lab resides in `IsaacLab`. All documented paths assume this base directory.

Execution sequence matters: skipping or reordering steps re-triggers known package failures detailed in [the defects](#the-defects).

Create the virtual environment and upgrade pip:

```powershell
uv venv --python 3.11 --seed
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

Pin setuptools prior to subsequent package installations to prevent defect 1:

```powershell
.\.venv\Scripts\python.exe -m pip install "setuptools<81"
```

Install Isaac Sim:

```powershell
.\.venv\Scripts\python.exe -m pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
```

Install `flatdict` without build isolation, forcing utilization of the pinned setuptools version rather than an isolated pip environment to address defect 1:

```powershell
.\.venv\Scripts\python.exe -m pip install flatdict==4.0.1 --no-build-isolation
```

Clone Isaac Lab matching the pinned release tag:

```powershell
git clone --depth 1 --branch v2.3.2 https://github.com/isaac-sim/IsaacLab.git
```

Install Isaac Lab extensions in editable mode by invoking the virtual environment interpreter directly, bypassing launcher defect 2:

```powershell
foreach ($e in @("isaaclab","isaaclab_assets","isaaclab_mimic","isaaclab_rl[rsl-rl]","isaaclab_tasks")) {
    .\.venv\Scripts\python.exe -m pip install -e "IsaacLab\source\$e"
}
```

Re-pin CUDA-enabled PyTorch binaries: installing extension packages inadvertently replaces the CUDA wheel with a CPU build, creating defect 4. Reinstall torch, torchvision, and torchaudio simultaneously to prevent missing binary packages, resolving defect 3:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
```

Pin `tensordict` to maintain binary compatibility and prevent import crashes against PyTorch 2.7, resolving defect 5:

```powershell
.\.venv\Scripts\python.exe -m pip install tensordict==0.8.3
```

Verify GPU acceleration support within PyTorch:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Output must display a version tag containing `+cu128` followed by `True`. Standard version numbers displaying `True` indicate an overwritten CPU package executing physics simulation without GPU acceleration.

## Verify

Execute the stock cartpole task for 50 iterations:

```powershell
$env:OMNI_KIT_ACCEPT_EULA="YES"
cd IsaacLab
..\.venv\Scripts\python.exe scripts\reinforcement_learning\rsl_rl\train.py --task=Isaac-Cartpole-Direct-v0 --headless --max_iterations 50
```

Mean reward climbs from approximately -5 to over 250, and `logs\rsl_rl\cartpole_direct\<timestamp>\` stores `model_49.pt` along with the TensorBoard event file.

Setting `OMNI_KIT_ACCEPT_EULA=YES` satisfies the license agreement non-interactively. Omitting the environment variable causes non-interactive SSH sessions to hang on an invisible license prompt before falsely reporting success.

## Watch a run from the workstation

Start TensorBoard on the host, binding to loopback so access requires the SSH tunnel:

```powershell
.\.venv\Scripts\python.exe -m tensorboard.main --logdir IsaacLab\logs\rsl_rl --host 127.0.0.1 --port 6006
```

Establish the SSH tunnel from the local workstation:

```bash
ssh -N -L 6006:127.0.0.1:6006 GPU_HOST
```

Open <http://localhost:6006> in a browser.

Adding flags `--video --video_length 100 --video_interval 10` to the training script outputs rollout recordings to `logs\rsl_rl\<task>\<timestamp>\videos\train\`. Video capture functions headlessly via the offscreen renderer during non-interactive sessions.

## Copying files off the host

Standard file transfer utilities `scp` and `sftp` fail against the Windows host with error `Received message too long`. Defect 7 details the underlying trigger. Permanent resolution requires guarding the remote PowerShell profile against emitting console text during non-interactive sessions. In the interim, streaming base64 over standard SSH retrieves artifacts reliably:

```bash
ssh GPU_HOST '[Convert]::ToBase64String([IO.File]::ReadAllBytes("<remote path>"))' | grep -v "^WARNING" | tr -d '\r\n ' | base64 -d > <local file>
```

The base64 pipeline handles video captures and model checkpoints effectively, though bulk directory transfers warrant full archive packaging.

## The defects

**1. Build failure in `flatdict`.** The package `setup.py` imports deprecated module `pkg_resources`, absent in setuptools 81, and later releases. Installation produces `ModuleNotFoundError: No module named 'pkg_resources'` inside pip's isolated build container, defaulting to the newest setuptools regardless of local venv packages. Pinning `setuptools<81` and installing `flatdict` via `--no-build-isolation` forces use of the pinned environment setuptools.

**2. Interpreter resolution failure in `isaaclab.bat`.** The script inspects `CONDA_PREFIX`, falls back to a bundled helper `_isaac_sim\python.bat` uncreated by pip installations, and contains dead logic in the third detection branch:

```bat
if not exist "%python_exe%" (
    set "python_exe="
    python -m pip show isaacsim-rl > nul 2>&1
    if %ERRORLEVEL% equ 0 (
```

The Windows command interpreter expands `%ERRORLEVEL%` inside parenthesized conditional blocks at parse time before `pip show` executes, reading a stale exit code. The script ignores `VIRTUAL_ENV`. Directly invoking the virtual environment Python interpreter bypasses the launcher defect entirely, aligning with alternative execution examples in official Isaac Lab guides.

**3. Missing `torchaudio` package.** The `isaacsim-core` metadata requires `torchaudio==2.7.0`. Installing CUDA wheels exclusively for torch and torchvision drops torchaudio from the environment. Installing torch, torchvision, and torchaudio concurrently from the cu128 wheel index resolves dependency parity.

**4. Silent PyTorch CPU fallback via RL extras.** Specifying `isaaclab_rl[all]` pulls `stable-baselines3`, requiring `torch>=2.8`. Pip silently replaces pinned `2.7.0+cu128` with an unaccelerated CPU build of newer PyTorch without raising errors, causing training runs to execute entirely on CPU compute. Installing `isaaclab_rl[rsl-rl]` rather than `[all]` avoids pulling incompatible requirements, while subsequent re-pinning ensures CUDA runtime linkage.

**5. Process crash during `tensordict` import.** As a compiled extension tightly linked against the PyTorch binary interface, `tensordict` fails with `Windows fatal exception: access violation` inside `tensordict/utils.py` when linked against mismatched PyTorch symbols. Resolving dependencies while a CPU PyTorch build is active creates broken binary links. Explicitly pinning `tensordict==0.8.3` restores binary compatibility with PyTorch 2.7.

Defects 4 and 5 stem from shared binary resolution conflicts. Post-installation PyTorch re-pinning requires matching compiled extensions to maintain binary interface alignment.

**6. Black frame strobing in video captures.** Enabling `--video` captures frame buffers on every simulation step, while physics rendering executes only once every `decimation` steps. Unrendered frames capture unpopulated display buffers, producing alternating black frames throughout rollout recordings. Adjusting `env.sim.render_interval=1` leaves the issue unresolved: empirical testing on a 2500-step rollout confirmed 1250 blank frames occupying even-numbered frames. The FFmpeg pipeline below detects dropped render frames:

```bash
ffmpeg -v error -i clip.mp4 -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" -f null -
```

Valid recordings maintain average luminance (YAVG) within tight tolerances. Blank frames register substantially lower luminance values. Filtering even-numbered frames via `select='mod(n,2)'` during video re-encoding restores smooth playback.

**7. Transfer failure with `scp` and `sftp`.** Startup banner text emitted by the host PowerShell profile corrupts binary handshake exchanges in SSH file transfer subsystems, raising `Received message too long`. Consult [Copying files off the host](#copying-files-off-the-host) for structural configuration and temporary streaming workarounds.

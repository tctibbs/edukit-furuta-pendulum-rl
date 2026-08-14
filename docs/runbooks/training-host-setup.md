# Training host setup

How to build the Isaac Lab environment this project trains in, on a Windows 11 host with an RT-core GPU, driven headless from another machine over SSH.

Verified end to end on 2026-08-13 against Isaac Sim 5.1.0 and Isaac Lab v2.3.2. The host decision is documented in [ADR-0002](../adrs/0002-training-host.md).

This guide is meant to be run alongside NVIDIA's [pip installation guide](https://isaac-sim.github.io/IsaacLab/main/source/setup/installation/pip_installation.html). Several issues were encountered during it, all of which are documented here.

Commands that reach the host from the workstation write it as `GPU_HOST`. Substitute the host's entry in your SSH configuration.

## Requirements

Check the GPU first. Isaac Sim will not run without RT cores, whatever the driver or VRAM says, because the Kit renderer requires hardware ray tracing even when training headless.

```powershell
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
```

Isaac Sim 5.1.0 states a GeForce RTX 4080 16 GB minimum and was tested on Windows driver 580.88. Budget 100 GB of disk: the documented minimum is 50 GB, but the `extscache` extras plus the pip cache run past that. Verified on an RTX 5080, 16303 MiB, driver 591.86, Ryzen 7 9800X3D, 32 GB RAM, Windows 11 build 26200.

## Install

Pick a directory on the host to hold the install and run every command below from it. The virtual environment lands in `.venv` inside that directory and the Isaac Lab clone in `IsaacLab`. Every path on this page is relative to it.

Order matters below: skipping or reordering a step reintroduces one of [the defects](#the-defects) at the bottom of this page.

Create the virtual environment and update pip:

```powershell
uv venv --python 3.11 --seed
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

Pin setuptools before anything else installs, for defect 1:

```powershell
.\.venv\Scripts\python.exe -m pip install "setuptools<81"
```

Install Isaac Sim:

```powershell
.\.venv\Scripts\python.exe -m pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com
```

Install `flatdict`, using the setuptools just pinned instead of pip's isolated build environment, also defect 1:

```powershell
.\.venv\Scripts\python.exe -m pip install flatdict==4.0.1 --no-build-isolation
```

Clone Isaac Lab at the pinned tag:

```powershell
git clone --depth 1 --branch v2.3.2 https://github.com/isaac-sim/IsaacLab.git
```

Install the extensions as editable packages, driving the venv interpreter directly since `isaaclab.bat` can't find it on its own, defect 2:

```powershell
foreach ($e in @("isaaclab","isaaclab_assets","isaaclab_mimic","isaaclab_rl[rsl-rl]","isaaclab_tasks")) {
    .\.venv\Scripts\python.exe -m pip install -e "IsaacLab\source\$e"
}
```

Re-pin the GPU build of PyTorch: installing the extensions just swapped it for a CPU build, defect 4. All three of torch, torchvision and torchaudio go back in together, or torchaudio goes missing, defect 3:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
```

Pin `tensordict` to match, or it crashes on import against the new torch, defect 5:

```powershell
.\.venv\Scripts\python.exe -m pip install tensordict==0.8.3
```

Confirm the GPU build took:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

That line must print a `+cu128` version and `True`. A plain version number with `True` means the GPU build was overwritten and training will run on CPU with no warning.

## Verify

Run the stock cartpole task for 50 iterations:

```powershell
$env:OMNI_KIT_ACCEPT_EULA="YES"
cd IsaacLab
..\.venv\Scripts\python.exe scripts\reinforcement_learning\rsl_rl\train.py --task=Isaac-Cartpole-Direct-v0 --headless --max_iterations 50
```

Mean reward should climb from roughly -5 to over 250, and `logs\rsl_rl\cartpole_direct\<timestamp>\` should hold `model_49.pt` and a TensorBoard event file.

The `OMNI_KIT_ACCEPT_EULA=YES` in the command above accepts the agreement; without it, a non-interactive session cannot answer the prompt, so the run stalls and then reports success anyway.

## Watch a run from the workstation

Start TensorBoard on the host, bound to loopback so the tunnel is the only route in:

```powershell
.\.venv\Scripts\python.exe -m tensorboard.main --logdir IsaacLab\logs\rsl_rl --host 127.0.0.1 --port 6006
```

Then tunnel from the workstation:

```bash
ssh -N -L 6006:127.0.0.1:6006 GPU_HOST
```

Open <http://localhost:6006>.

Rollout videos are written to `logs\rsl_rl\<task>\<timestamp>\videos\train\` when the training script is given `--video --video_length 100 --video_interval 10`. Recording works headless: the offscreen renderer produces frames in a non-interactive session.

## Copying files off the host

`scp` and `sftp` both fail against this host with `Received message too long` (defect 7 below). The durable fix is to guard the host's PowerShell profile so it stays silent when the session is not interactive. Until then, this copies a file over plain SSH instead:

```bash
ssh GPU_HOST '[Convert]::ToBase64String([IO.File]::ReadAllBytes("<remote path>"))' | grep -v "^WARNING" | tr -d '\r\n ' | base64 -d > <local file>
```

This is fine for a video or a checkpoint, not for a large directory.

## The defects

**1. `flatdict` fails to build.** Its `setup.py` imports `pkg_resources`, which setuptools 81 removed. The error is `ModuleNotFoundError: No module named 'pkg_resources'` from inside pip's isolated build environment, which builds with the newest setuptools regardless of what the venv holds. Pin `setuptools<81` and install `flatdict` with `--no-build-isolation` so it uses the venv's setuptools.

**2. `isaaclab.bat` cannot find a Python interpreter.** It checks `CONDA_PREFIX`, falls back to a bundled `_isaac_sim\python.bat` that the pip install does not create, and its third branch, meant for exactly this layout, is dead code:

```bat
if not exist "%python_exe%" (
    set "python_exe="
    python -m pip show isaacsim-rl > nul 2>&1
    if %ERRORLEVEL% equ 0 (
```

`%ERRORLEVEL%` inside a parenthesized block is expanded when the block is parsed, before `pip show` has run, so the test reads a stale value. `VIRTUAL_ENV` is never consulted. Call the venv interpreter directly. Isaac Lab's own documentation offers this as the alternative invocation.

**3. `torchaudio` goes missing.** `isaacsim-core` pins `torchaudio==2.7.0`, and installing the CUDA builds of torch and torchvision alone drops it. Install all three from the cu128 index together.

**4. The RL extras silently downgrade the GPU build.** `isaaclab_rl[all]` pulls `stable-baselines3`, which requires `torch>=2.8`, so pip replaces the pinned 2.7.0+cu128 with a CPU build of a newer torch. Nothing errors. Training then runs on the CPU. Install `isaaclab_rl[rsl-rl]` instead of `[all]` unless another framework is needed, and re-pin torch afterwards either way.

**5. `tensordict` crashes the process on import.** It is a compiled extension tightly coupled to the torch ABI, and `rsl-rl-lib` depends on it. If it was resolved while the wrong torch was installed, re-pinning torch afterwards leaves it linked against symbols that no longer exist. The failure is `Windows fatal exception: access violation` inside `tensordict/utils.py`, not an `ImportError`. Install `tensordict==0.8.3` to match torch 2.7.

The general lesson from 4 and 5: re-pinning torch after the fact is not enough. Anything already resolved against the wrong torch that carries compiled code has to be re-resolved too.

**6. Recorded video flashes black every other frame.** `--video` captures once per environment step, but the simulator renders every `decimation` steps, so half the captures grab a buffer that was never drawn. They come out as uniform dark frames, and the result flickers hard. `env.sim.render_interval=1` renders every step and fixes most of it. Frame 0 is still captured before the renderer has anything to give. Checking for it is quick:

```bash
ffmpeg -v error -i clip.mp4 -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" -f null -
```

A clean clip holds YAVG within a couple of units. Blank frames read as a flat value far below the rest, and dropping them is `select='gt(n,0)'` plus a re-encode.

**7. `scp` and `sftp` cannot copy anything off the host.** The shell profile prints text on every session and both transfer protocols read that banner as protocol data, giving `Received message too long`. Details and a workaround are in [Copying files off the host](#copying-files-off-the-host) above.

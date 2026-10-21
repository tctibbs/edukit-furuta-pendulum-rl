# Converting a policy for the board

How to take a trained policy off the simulator and run it on the board (NUCLEO-F401RE). The network is small enough that its weights and forward pass compile to plain C, so it needs no quantization, no model format, and no inference runtime such as TFLite Micro or ONNX Runtime.

## What gets converted

- The actor, `board/policy.c` and `board/policy_weights.h`.
- The observation pipeline, `board/observer.c`.
- The action bound: `tanh` or the actuator's clamp, and the scale. Both must match training ([ADR-0004](../adrs/0004-two-actuator-paths.md)).

See [board/README.md](../../board/README.md) for the code itself.

## Deploy

From the repository root:

```bash
just board-export <checkpoint> --no-squash-actions
```

Example output:

```text
wrote board/policy_weights.h (20700 bytes)
wrote board/policy_vectors.json (64 vectors)
action range over the vectors: -5.690 to 7.670
```

Use `--no-squash-actions` for the Balance tasks and `--squash-actions` for `Furuta-SwingUp-Direct-v0`, which trains with `tanh` on the command. The wrong flag exports without complaint and skews commands by up to 24 percent of the bound at a raw action of magnitude 1. The export records which flag it used, and the verification step below reads it back. Both files are overwritten on every export.

The printed action range is a sanity check. Raw output over 1 is expected. The bound clamps it, or `tanh` maps it inside the bound for a `--squash-actions` export.

## Verifying the C code matches the simulation

This compiles the C, feeds synthetic inputs through it and through the PyTorch model it was exported from, and compares the two:

```bash
just board-test
```

It also runs the checks in [Showcase policies](#showcase-policies) and tests the hardware-test arithmetic and the firmware build's prefix repair. Example output on a pass:

```text
showcase table: current
........................................................................ [ 36%]
........................................................................ [ 72%]
......................................................                   [100%]
```

## Verifying the whole pipeline on real data

The preceding test uses synthetic inputs. This one replays a recorded simulator trace and compares the C output against the command the simulation issued.

```bash
cc -std=c99 -O2 -ffp-contract=off -Wall -Wextra -Werror board/policy.c board/observer.c board/test_board.c -lm -o /tmp/board_test
uv run scripts/check_policy_trace.py /tmp/board_test <trace.csv> --a-max <bound>
```

Example output on a pass:

```text
1242 rows with the policy in command; largest |difference| 0.000006 rad/s^2; 4 rows past the rail
PASS
```

## Showcase policies

The showcase image, firmware [mode `x`](edukit-firmware.md#mode-x-the-showcase-carousel), carries several policies, each under its own name. `config/showcase.yaml` lists every entry. Each learned entry names its checkpoint and gives the acceleration bound and squash it trained with. One command exports every policy and the carousel's table (`just fw-showcase` runs it before building):

```bash
uv run --with numpy scripts/export_showcase.py
```

It prints one `wrote <path>` line per file and overwrites `board/showcase_table.c` and, per policy, `board/policies/<name>.h` and `<name>.json`. A named header prefixes its arrays with the name and carries the bound and squash in a `policy_t` for `policy_command_with`. The vectors record both, with the checkpoint's MD5. Swing-up policies get test vectors across 180 degrees of tilt, balance policies across 20.

Without `--with numpy`, torch warns that it cannot initialize NumPy. The export is unaffected. To export one policy by hand, pass `--name` to `export_policy.py`. `--accel-bound` is required with it, `--out-dir` sets the output directory (default `board/policies/`), and `--tilt-range-deg` sets the vectors' tilt range (default 20):

```bash
uv run --with numpy scripts/export_policy.py <checkpoint> --squash-actions --name <name> --accel-bound 60 --tilt-range-deg 180
```

`just board-test` first runs `export_showcase.py --check`, which regenerates everything in a scratch directory and compares it byte for byte with the committed files without changing anything. The check names each file that differs or that the manifest no longer lists, then prints `showcase table: current` or `showcase table: stale`. `tests/test_showcase.py` then feeds each policy's vectors through the board's forward pass. The output must match PyTorch's within 1e-5, and the command must match the action, bounded and scaled with the policy's own squash and bound, within 1e-3.

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

Use `--no-squash-actions` for the Balance tasks, which is every task here. The wrong flag exports without complaint and skews commands by up to 24 percent of the bound at a raw action of magnitude 1. The export records which flag it used, and the verification step below reads it back. Both files are overwritten on every export.

The printed action range is a sanity check. Raw output above 1 is expected, since the bound clamps it.

## Verifying the C code matches the simulation

This compiles the C, feeds synthetic inputs through it and through the PyTorch model it was exported from, and compares the two:

```bash
just board-test
```

Example output on a pass:

```text
.......                                                                  [100%]
```

## Verifying the whole pipeline on real data

The preceding test uses synthetic inputs. This one replays a recorded simulator trace and compares the C output against the command the simulation issued.

```bash
/usr/bin/clang -std=c99 -O2 -Wall -Wextra -Werror board/policy.c board/observer.c board/test_board.c -lm -o /tmp/board_test
uv run scripts/check_policy_trace.py /tmp/board_test <trace.csv> --a-max <bound>
```

Example output on a pass:

```text
1242 rows with the policy in command; largest |difference| 0.000006 rad/s^2; 4 rows past the rail
PASS
```

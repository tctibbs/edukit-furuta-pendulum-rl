# Checkpoints

The carousel's JETHRO entry runs `tame_i_seed3_model_299.pt`, kept here so the entry can be rebuilt without the training host. Beside it are the two runs that clear every benchmark target, tame-e on seed 1 and tame-k on seed 2, and tame-k's other two seeds. All trained on `Furuta-SwingUp-Direct-v0` at 4 kHz physics and a $60\text{ rad/s}^2$ acceleration bound, with `tanh` on the action. Each file is about 47 KB, an `rsl_rl` state dict holding both actor and critic. A filename is the run id with underscores for hyphens, then its final iteration. Seed 1's run id drops the seed (`tame-e`), and its file keeps it. The [logbook](../logbook.md#the-tame-ladder) explains what each rung changed, and [`config.yaml`](../config.yaml) carries the recipe and benchmark targets.

`scripts/evaluate_swingup.py` scores them the same way as [Experiment 06](../../06-swing-up/checkpoints/README.md)'s checkpoints. Each peak is the maximum over the 256 episodes. Every row matches its record in [`simulation/benchmark.csv`](../simulation/benchmark.csv).

| Checkpoint | Logbook rung | Change | Reached vertical | Held | Travel terminations | Swing-up time (median, 90th percentile) | Peak arm travel | Peak arm speed |
|---|---|---|---|---|---|---|---|---|
| `tame_e_seed1_model_599.pt` | tame-e, seed 1 | the a60d actor with travel -5.0 past 0.5 rad, the arm-speed penalty at -0.1, and command change at -1.0, 600 iterations | 256 | 256 | 0 | 4.46 s, 5.14 s | 1.17 rad | 6.40 rad/s |
| `tame_i_seed3_model_299.pt` | tame-i, seed 3 | tame-f with the arm-speed penalty at -0.4 and the travel termination at 1.5 rad, 300 iterations | 256 | 256 | 0 | 2.97 s, 3.38 s | 1.15 rad | 8.17 rad/s |
| `tame_k_seed1_model_299.pt` | tame-k, seed 1 | tame-f with the arm-speed penalty at -0.4, travel -10.0, and the travel termination at 1.5 rad, 300 iterations | 256 | 256 | 0 | 3.89 s, 5.62 s | 1.88 rad | 7.09 rad/s |
| `tame_k_seed2_model_299.pt` | tame-k, seed 2 | as seed 1 | 256 | 256 | 0 | 4.27 s, 4.95 s | 1.13 rad | 5.26 rad/s |
| `tame_k_seed3_model_299.pt` | tame-k, seed 3 | as seed 1 | 256 | 256 | 0 | 3.52 s, 3.97 s | 1.62 rad | 6.52 rad/s |

tame-i's peak arm speed misses the 8.0 rad/s benchmark target, and the ladder was tuned on seed 3. tame-k's seeds 1 and 3 miss the 1.50 rad travel target. tame-e's seeds 2 and 3 never hold, so their checkpoints stay on the training host.

## Replaying one

Run this on the training host from the project directory to reproduce a row, with `--seed` equal to the seed in the filename:

```powershell
$env:PYTHONPATH = "src"
& $env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe -u scripts\evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 --num-envs 256 --seed 3 --checkpoint docs\experiments\07-showcase\checkpoints\tame_i_seed3_model_299.pt --out results\replay.csv
```

## On the bench

`scripts/export_showcase.py` reads the JETHRO entry in [`config/showcase.yaml`](../../../../config/showcase.yaml) and exports this checkpoint to `board/policies/tame_i_seed3.h`. The header records the checkpoint's MD5, `78d6f9985477b2ca325e5226fbb90371`. `just fw-showcase` builds the image. The checkpoint's first bench session, on 2026-09-13, is in the [logbook](../logbook.md#bench-session-1-2026-09-13).

The carousel's other policies are [Experiment 05](../../05-balance/writeup.md)'s balance checkpoints and [Experiment 06](../../06-swing-up/writeup.md)'s swing-up checkpoints, in those experiments' `checkpoints/` folders.

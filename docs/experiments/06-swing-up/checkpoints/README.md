# Checkpoints

The policies kept from [Experiment 06](../writeup.md), each at its final iteration. Every one trained on `Furuta-SwingUp-Direct-v0` at 4 kHz physics and a $60\text{ rad/s}^2$ acceleration bound, starting from the actor of [Experiment 05](../../05-balance/writeup.md)'s `momentum_a60d_seed1_model_299.pt` with the critic and exploration noise reinitialized. Each file is about 47 KB, an `rsl_rl` state dict holding both actor and critic. The [logbook](../logbook.md) says what each run changed and what it did, and [`config.yaml`](../config.yaml) carries the exact configuration.

Each file name, without `swingup_` and `_model_599.pt`, is its run id in the training log [`simulation/results.csv`](../simulation/results.csv) with hyphens for underscores, and seed 1 drops its `_seed1`. The table gives the logbook's run number beside it. `_smooth` marks the corrected plant, with the drive target walked across the substeps ([ADR-0006](../../../adrs/0006-walked-rotor-target.md)). Each checkpoint is scored by `scripts/evaluate_swingup.py` on 256 starts within 0.4 rad and 1 rad/s of hanging, over 30 s, and [`config.yaml`](../config.yaml) records the scores per run. Reaching vertical means entering $3^\circ$ of upright, holding means staying inside $3^\circ$ for the last 5 s, and a travel termination is the arm passing $\pi$ rad from center. Swing-up time is the time to reach vertical, and its median covers only the episodes that reach it. An episode can reach vertical and later end on the travel limit, and those two columns overlap.

| Checkpoint | Logbook run | Change | Reached vertical | Held | Travel terminations | Swing-up time (median) | Peak arm speed (max of 256) |
|---|---|---|---|---|---|---|---|
| `swingup_r1_warm_seed1_model_599.pt` | 1 | the base run | 255 | 254 | 1 | 5.11 s | 11.2 rad/s |
| `swingup_r1_warm_seed2_model_599.pt` | 3 | run 1 on seed 2 | 141 | 141 | 115 | 2.93 s | 10.6 rad/s |
| `swingup_r1_warm_seed3_model_599.pt` | 4 | run 1 on seed 3 | 256 | 255 | 1 | 1.96 s | 11.2 rad/s |
| `swingup_r3_clock_seed1_model_599.pt` | 5 | episode length jittered 8 to 10 s | 256 | 256 | 0 | 2.10 s | 11.0 rad/s |
| `swingup_r6_armspeed_seed1_model_599.pt` | 8 | as run 5, with the arm-speed penalty ten times heavier, -0.1 per (rad/s)² against -0.01 | 256 | 249 | 1 | 3.48 s | 8.4 rad/s |
| `swingup_r7_smooth_seed1_model_599.pt` | 9 | as run 5, on the corrected plant | 252 | 252 | 4 | 1.25 s | 11.6 rad/s |
| `swingup_r7_smooth_seed2_model_599.pt` | 10 | as run 9, seed 2 | 256 | 256 | 0 | 2.12 s | 11.0 rad/s |
| `swingup_r7_smooth_seed3_model_599.pt` | 11 | as run 9, seed 3 | 250 | 248 | 8 | 1.51 s | 15.1 rad/s |

## Replaying one

Run these on the training host from the project directory. The first reproduces a row of the table. Pass `--seed` equal to the seed in the file name. Checkpoints without `_smooth` in the name trained on the stepped plant and also need `--stepped-rotor`:

```powershell
$env:PYTHONPATH = "src"
& $env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe -u scripts\evaluate_swingup.py --headless --physics-hz 4000 --accel-bound 60 --stepped-rotor --num-envs 256 --seed 1 --checkpoint docs\experiments\06-swing-up\checkpoints\swingup_r1_warm_seed1_model_599.pt --out results\replay.csv
```

One from-rest episode as a per-step trace, with the same flags:

```powershell
$env:PYTHONPATH = "src"
& $env:USERPROFILE\Code\isaac\.venv\Scripts\python.exe -u scripts\record_swingup_trace.py --headless --physics-hz 4000 --accel-bound 60 --stepped-rotor --checkpoint docs\experiments\06-swing-up\checkpoints\swingup_r1_warm_seed1_model_599.pt --out traces\replay.csv
```

`--accel-bound` and `--physics-hz` must match the values the checkpoint trained with. The checkpoint records neither, and a wrong bound scales every command without failing.

## The ones on the bench

`swingup_r3_clock_seed1_model_599.pt` ran in Session 1, on 2026-09-10. It was exported through the [model-conversion runbook](../../../runbooks/model-conversion.md) with `scripts/export_policy.py --squash-actions` to `board/policy_weights.h` (MD5 `69c40f07a75f8deca53365f7bebec088`), compiled into the firmware's mode `r`, which runs the policy from hanging rest, and run at `RL_ACCEL_BOUND_RAD_S2` of 60. It swung up and fell on all three attempts ([capture](../hardware/rl_swingup_20260910.tsv)).

`swingup_r6_armspeed_seed1_model_599.pt` ran in Session 2, on 2026-09-10. Its tenfold arm-speed penalty holds the arm to 8.4 rad/s at most in simulation and 7.7 to 7.9 on the bench, against 11.0 for run 5. Above about 7 rad/s the stepped plant and the bench disagree. It caught the pendulum in all four attempts. The capture records two of them, one holding for 7.8 s and one for the full 30 s ([capture](../hardware/rl_swingup_20260910_session2.tsv)).

Session 3, on 2026-09-11, found and fixed defects in mode `r`'s firmware scaffolding around the policy and is not a policy result ([capture](../hardware/rl_swingup_20260911_control.tsv)).

`swingup_r7_smooth_seed2_model_599.pt` ran in Session 4, on 2026-09-11, exported to `board/policy_weights.h` with MD5 `eb75d9cfa55033b8c7faf1985488fff7`. It was chosen over seeds 1 and 3 of the same configuration because none of its 256 scored starts ended on the travel limit, against 4 and 8 for the other two. The corrected plant has been checked against the bench up to the 10.8 rad/s of Session 1's capture, just under this policy's simulated peak of 11.0. It swung up in 2.25 s and held for the full 30 s at 0.32 degrees RMS with the arm parked ([capture](../hardware/rl_swingup_20260911_session4.tsv)). It is the first swing-up policy with the lighter arm-speed penalty to hold on the bench. The only earlier swing-up policy with it, run 5's, fell on all three attempts.

Each session's header was exported for that session and not committed, and the committed `board/policy_weights.h` still carries [Experiment 05](../../05-balance/writeup.md)'s export. The [firmware runbook](../../../runbooks/edukit-firmware.md#mode-r-rl-swing-up-from-rest) describes the mode `r` build, staged as `rl-swingup` in [`config/firmware.yaml`](../../../../config/firmware.yaml).

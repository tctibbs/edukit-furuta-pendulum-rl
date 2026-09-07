# Checkpoints

Every policy this experiment reports on, one per configuration, at iteration 299. Each is about 47 KB, an `rsl_rl` state dict holding both actor and critic. They are kept so the ladder can be replayed later: each row below changes one thing from the row above it, and the clip and capture columns say what that change did.

| Checkpoint | Task | Bound | Changed from the row above | Clip | Hardware capture |
|---|---|---|---|---|---|
| `balance_seed1` | `Furuta-Balance-Direct-v0` | 11.78 rad/s^2 | the first policy, resets within 2 degrees of upright | `trained.gif`, `handover_first.gif` | |
| `momentum_seed1` | `Furuta-Balance-Momentum-Direct-v0` | 11.78 | resets moved across the recoverable set, arm displaced and moving | `handover_momentum.gif` | |
| `momentum_a40_seed1` | `Furuta-Balance-Momentum-Direct-v0` | 40 | the action scale raised to what the stock controller commands | `firmware_swingup_a40.gif` | `hardware_rl_balance.tsv`, `hardware_rl_balance_series.tsv` |
| `momentum_a60_seed1` | `Furuta-Balance-Momentum-Direct-v0` | 60 | bound raised again, and the charge on arm travel removed | | `hardware_rl_balance_a60.tsv` |
| `momentum_a60b_seed1` | `Furuta-Balance-Momentum-Direct-v0` | 60 | the travel charge restored | | |
| `momentum_a60c_seed1` | `Furuta-Balance-Momentum-Direct-v0` | 60 | plus a charge on how fast the arm turns | `hardware_hold.gif` | `hardware_rl_balance_a60c.tsv` |
| `momentum_a60d_seed1` | `Furuta-Balance-Momentum-Direct-v0` | 60 | plus the action-rate charge raised from 0.01 to 0.5 | `hardware_hold_a60d.gif` | `hardware_rl_balance_a60d.tsv` |

The write-up says what each change was for and what it cost. `config.yaml` carries the exact reward weights under `followups`.

## Replaying one

On the training host, from the project directory with `PYTHONPATH=src`. Through the firmware's own swing-up, which is the comparison the later rows are scored on:

```powershell
& C:\path\to\.venv\Scripts\python.exe -u scripts\scripted_swingup.py --headless --pump firmware --physics-hz 4000 --num-envs 256 --seed 1 --duration-s 30 --checkpoint docs\experiments\05-balance\checkpoints\momentum_a60d_seed1_model_299.pt --policy-task Furuta-Balance-Momentum-Direct-Play-v0 --policy-bound 60 --episodes-out results\replay.csv --trace results\replay_trace.csv
```

`--policy-bound` must match the bound the checkpoint trained with, from the table above. The checkpoint does not record it, and a wrong value scales every command without failing.

To put one on the board instead, [the model-conversion runbook](../../../runbooks/model-conversion.md) has the export and the gate.

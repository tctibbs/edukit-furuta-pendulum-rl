"""Map the arm states from which the swing-up checkpoint's catch holds.

On the bench (experiment 06, 2026-09-10) the swing-up policy had the real pendulum
inside 3 degrees of vertical in 1.7 s, in a state the pendulum's own measure calls
recoverable, then let it drift through zero over 240 ms while commanding -4 to -9
rad/s^2 of the 60 available, and it fell. The board's commands replay exactly from the
observations it logged, so the deployment is cleared and what is left is the policy or
the plant. As the policy saw it at the first 3 degree sample, attempt 1 arrived at a
tilt of +2.85 degrees moving -0.33 rad/s with the arm at +1.42 rad turning at +4.21
rad/s; attempt 2 at +2.85 degrees and -1.50 rad/s with the arm at +1.04 rad and +4.65
rad/s. The arm had been driven to 10.8 rad/s dead-reckoned on the way up, twice
the 5.4 rad/s of any earlier bench capture with the pendulum
caught. A lost step does not show in the log because the arm has no
sensor.

This script separates the two readings. Every environment starts at one pendulum state
and the arm is swept over a grid of angle by rate; the checkpoint's inference policy,
the action mean with no sampling, runs from there, and each cell reports whether the
pendulum was inside `--hold-deg` for the whole of the last `--hold-s`. If the bench
cell holds here, the simulated plant holds where the real one drifted and the gap is
the plant or the stepper. If it does not, the policy cannot catch from the state its
own swing-up produces, and the fix is training-side: arrive with the arm slower. The
upright map (`--tilt-deg 0 --pendulum-rate 0`) says how much arm motion
the hold tolerates with nothing else going on.

Rows are arm angle and columns arm rate, `int(sqrt(num_envs))` of each, so 256
environments give a 16 by 16 map with the same pendulum state in every cell. The cell
nearest the bench arrival is moved onto it, by under half a spacing, so the bench
answer is read from the exact state and not from a neighbour. On the default axes the
lattice point nearest attempt 1 is 0.19 rad/s away, the one nearest attempt 2 is 0.25
rad/s away, and both attempts round to the same 4.40 rad/s column although their arm
rates differ by 0.44 rad/s. Environments past the square are unused and reported as
such.

Run on the training host:

    python scripts/evaluate_catch_map.py --headless --physics-hz 4000 --accel-bound 60 \
        --stepped-rotor --checkpoint logs/rsl_rl/furuta_swingup/r3-clock/model_599.pt \
        --tilt-deg 2.85 --pendulum-rate -0.33 --out results/sw06r_catch_map_a1.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import traceback
from pathlib import Path

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--stepped-rotor",
    action="store_true",
    help="hand the drive one target per control period, the plant every run before"
    " ADR-0006 trained on, instead of walking it across the substeps",
)
parser.add_argument("--task", default="Furuta-SwingUp-Direct-Play-v0")
parser.add_argument("--checkpoint", required=True)
parser.add_argument("--num-envs", type=int, default=256)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument(
    "--tilt-deg",
    type=float,
    default=2.85,
    help="pendulum tilt from upright in every cell, signed as the policy observes it",
)
parser.add_argument(
    "--pendulum-rate",
    type=float,
    default=-0.33,
    help="pendulum rate in every cell, rad/s, with the tilt's sign convention",
)
parser.add_argument(
    "--arm-rad-range",
    type=float,
    nargs=2,
    default=[-2.5, 2.5],
    metavar=("LO", "HI"),
    help="arm angle span of the grid rows, rad",
)
parser.add_argument(
    "--arm-rate-range",
    type=float,
    nargs=2,
    default=[-6.0, 6.0],
    metavar=("LO", "HI"),
    help="arm rate span of the grid columns, rad/s",
)
parser.add_argument(
    "--bench-arm-rad",
    type=float,
    default=1.42,
    help="arm angle of the bench arrival, rad; the nearest grid cell is moved onto it",
)
parser.add_argument(
    "--bench-arm-rate",
    type=float,
    default=4.21,
    help="arm rate of the bench arrival, rad/s; the nearest grid cell is moved onto it",
)
parser.add_argument("--duration-s", type=float, default=10.0)
parser.add_argument("--hold-deg", type=float, default=3.0)
parser.add_argument(
    "--hold-s", type=float, default=5.0, help="trailing window that must stay inside"
)
parser.add_argument("--out", default=None, help="csv path, one row per cell")
parser.add_argument(
    "--accel-bound",
    type=float,
    default=None,
    help="rotor acceleration bound and action scale, rad/s^2, in place of the "
    "configured 11.78. Must match the bound the checkpoint trained with: the "
    "checkpoint does not record it, and a wrong value rescales every command "
    "without failing. See ADR-0004",
)
parser.add_argument(
    "--physics-hz",
    type=float,
    default=None,
    help="simulation rate. The swing-up checkpoints were trained at 4000",
)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

FALL_DEG = 30.0
"""Tilt past which a cell is recorded as fallen.

The swing-up task has no fall-over termination (`FurutaSwingUpEnvCfg` sets
`max_pendulum_angle_rad` to pi), so a fallen pendulum stays in play and the policy may
swing it back up inside the episode. `fell_s` keeps that visible beside `held`, which
only says where the pendulum was at the end. 30 degrees is where the bench log called
the miss."""

AFTER_S = 0.5
"""Start of the window the closest approach is read over, so the initial state does not
report itself as the minimum: every cell begins at `--tilt-deg`, which for the bench
states this script exists for is already inside the hold window."""


def main() -> int:
    """Start every cell from the chosen state, run the policy, write a row per cell."""
    import gymnasium as gym
    import torch
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
    from rsl_rl.runners import OnPolicyRunner

    import furuta.tasks  # noqa: F401  (registration side effect)
    from furuta.env import PARAMS, wrap_to_pi

    spec = gym.spec(args.task)
    cfg = spec.kwargs["env_cfg_entry_point"]()
    cfg.rotor_target_interpolation = not args.stepped_rotor
    agent_cfg = spec.kwargs["rsl_rl_cfg_entry_point"]()
    cfg.scene.num_envs = args.num_envs
    cfg.seed = args.seed
    if args.accel_bound is not None:
        cfg.max_acceleration_rad_s2 = args.accel_bound
        print(f"[cfg  ] max_acceleration_rad_s2={args.accel_bound}", flush=True)
    if args.physics_hz is not None:
        cfg.sim.dt = 1.0 / args.physics_hz
        cfg.decimation = max(1, round(0.002 * args.physics_hz))
        print(
            f"[cfg  ] physics_hz={args.physics_hz} decimation={cfg.decimation}",
            flush=True,
        )

    # The time-out has to fall outside the scored window, as in evaluate_swingup.py:
    # it fires one step before the episode length and resets the environment. A loop
    # running exactly the duration would read a reset cell on its last step.
    # Per-episode jitter is set to zero because it would move that time-out inside the
    # window for some cells.
    duration = args.duration_s
    cfg.episode_length_s = duration + 1.0
    cfg.episode_length_jitter = 0.0

    env = gym.make(args.task, cfg=cfg)
    env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)
    runner = OnPolicyRunner(
        env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device
    )
    runner.load(args.checkpoint)
    policy = runner.get_inference_policy(device=agent_cfg.device)

    inner = env.unwrapped
    device = inner.device
    n = args.num_envs
    side = math.isqrt(n)
    used = side * side
    steps = int(duration / inner.step_dt)
    hold_steps = int(args.hold_s / inner.step_dt)
    after_steps = int(AFTER_S / inner.step_dt)
    tol = math.radians(args.hold_deg)
    fall = math.radians(FALL_DEG)

    # Row-major: environment e is row e // side (arm angle) and column e % side (arm
    # rate). Environments past the square get a centred, still arm and are left out
    # of the map.
    arm_axis = torch.linspace(*args.arm_rad_range, side, device=device)
    rate_axis = torch.linspace(*args.arm_rate_range, side, device=device)
    arm = torch.zeros(n, device=device)
    arm_rate = torch.zeros(n, device=device)
    arm[:used] = arm_axis.repeat_interleave(side)
    arm_rate[:used] = rate_axis.repeat(side)

    # The cell nearest the bench arrival is moved onto it before the state is written,
    # so the run's answer is read from the bench state and not from a lattice point up
    # to half a spacing away. On the default axes attempt 1's 4.21 rad/s and attempt
    # 2's 4.65 rad/s both round to the 4.40 rad/s column. Because the csv takes each
    # cell's arm state from these tensors, the bench cell's row carries the exact
    # bench state.
    bench_row = int(torch.argmin(torch.abs(arm_axis - args.bench_arm_rad)))
    bench_col = int(torch.argmin(torch.abs(rate_axis - args.bench_arm_rate)))
    bench_env = bench_row * side + bench_col
    arm[bench_env] = args.bench_arm_rad
    arm_rate[bench_env] = args.bench_arm_rate
    tilt0 = math.radians(args.tilt_deg)
    print(
        f"[cfg  ] grid {side}x{side}: rows arm {args.arm_rad_range[0]:+.2f} to "
        f"{args.arm_rad_range[1]:+.2f} rad, columns arm rate "
        f"{args.arm_rate_range[0]:+.2f} to {args.arm_rate_range[1]:+.2f} rad/s; "
        f"pendulum tilt {args.tilt_deg:+.2f} deg at {args.pendulum_rate:+.2f} rad/s "
        f"in every cell; {used} of {n} environments used, {n - used} unused",
        flush=True,
    )

    env.reset()

    # Overwrite the reset with the chosen state. This mirrors `FurutaEnv._reset_idx`
    # in src/furuta/env.py item by item, because a joint moved without the
    # rest of that method following it is either a step error the drive closes at
    # full authority or a first observation that lies about the rate:
    #
    # - joint positions and velocities, as `_reset_idx` writes them. The asset hangs
    #   at zero, so the pendulum joint is pi plus the tilt and `wrap_to_pi(pos - pi)`
    #   reads the tilt back; the rotor joint is the arm angle.
    # - the actuator's dead-reckoned position and velocity and the rotor
    #   target it hands the drive.
    # - the previous action, for the action-rate term.
    # - both slope estimators, seeded as the history of a body moving at the written
    #   rate: the pendulum from its encoder-quantized angle and the
    #   rotor from the actuator's quantized position, so the first observation
    #   carries the rate rather than a reading climbing from zero over 32 ms.
    #
    # Left as `env.reset()` set them a moment ago, since no step has run in between:
    # `episode_length_buf` (zeroed by `DirectRLEnv._reset_idx`), `_episode_steps`
    # (jitter is zero here), and the from-hanging diagnostics `_from_hanging`,
    # `_peak_energy_frac`, `_min_tilt`, `_entered_set` and the gate streaks,
    # which feed training logs and nothing the policy sees.
    # `_action` and `_pendulum_vel` are reward-side and are overwritten by the first
    # step and the first observation respectively.
    pendulum_idx = inner._pendulum_idx[0]
    rotor_idx = inner._rotor_idx[0]
    joint_pos = inner.robot.data.default_joint_pos.clone()
    joint_vel = inner.robot.data.default_joint_vel.clone()
    joint_pos[:, pendulum_idx] = math.pi + tilt0
    joint_vel[:, pendulum_idx] = args.pendulum_rate
    joint_pos[:, rotor_idx] = arm
    joint_vel[:, rotor_idx] = arm_rate
    inner.robot.write_joint_state_to_sim(joint_pos, joint_vel)
    inner._actuator.reset(position=arm, velocity=arm_rate)
    inner._rotor_target[:] = inner._actuator.quantized_position()
    inner._prev_action[:] = 0.0
    encoder = PARAMS.rad_per_encoder_count
    inner._pendulum_rate.reset(
        None,
        torch.round(joint_pos[:, pendulum_idx] / encoder) * encoder,
        joint_vel[:, pendulum_idx],
    )
    inner._rotor_rate.reset(None, inner._actuator.quantized_position(), arm_rate)

    # The first observation has to come from the written state, and how it is asked
    # for matters: `_get_observations` pushes one sample into each estimator window,
    # and a sample at the same angle lands as a flat step on the seeded ramp. One call
    # through the wrapper is what a reset inside a training rollout produces
    # (`DirectRLEnv.step` runs `_reset_idx` and then `_get_observations` once), so
    # the policy meets the first rate reading it trained against, 0.978 of the seed
    # at the configured 16-sample window. Stepping first would move the state before
    # the policy has acted; asking twice would flatten the ramp further.
    obs = env.get_observations()

    # Seed and first reading on one line, so the host log checks itself: the angles
    # must match and each rate must read 0.978 of its seed.
    first = obs["policy"][bench_env].tolist()
    print(
        f"[cfg  ] bench cell env {bench_env} seeded arm {float(arm[bench_env]):+.3f} "
        f"rad at {float(arm_rate[bench_env]):+.3f} rad/s, pendulum "
        f"{args.tilt_deg:+.2f} deg at {args.pendulum_rate:+.3f} rad/s; first "
        f"observation tilt {math.degrees(math.atan2(first[1], first[0])):+.2f} deg, "
        f"pendulum rate {first[2]:+.3f} rad/s, arm {first[3]:+.3f} rad at "
        f"{first[4]:+.3f} rad/s; rates read 0.978 of the seed",
        flush=True,
    )

    # Every statistic below is frozen at a cell's first termination, as in
    # evaluate_swingup.py. Isaac Lab resets a terminated environment inside the same
    # `env.step`. From then on its readings belong to a fresh episode.
    arrived = torch.full((n,), -1, dtype=torch.long, device=device)
    left_late = torch.zeros(n, dtype=torch.bool, device=device)
    terminated = torch.zeros(n, dtype=torch.bool, device=device)
    term_step = torch.full((n,), -1, dtype=torch.long, device=device)
    fell_step = torch.full((n,), -1, dtype=torch.long, device=device)
    min_tilt_late = torch.full((n,), math.inf, device=device)
    peak_rotor = torch.zeros(n, device=device)
    peak_rotor_rate = torch.zeros(n, device=device)

    for step in range(steps):
        with torch.inference_mode():
            actions = policy(obs)
        obs, _, _, _ = env.step(actions)

        # The termination is taken before the state is sampled, where
        # evaluate_swingup.py samples first. On the terminating step
        # `_quantized_angles` already returns the reset state. Sampling it would record
        # the cell as falling. `reset_terminated` is the task's own
        # termination, the travel bound for swing-up; the wrapper's `dones` also
        # unions the time-out.
        now = inner.reset_terminated.bool() & ~terminated
        term_step = torch.where(now, torch.full_like(term_step, step), term_step)
        live = ~terminated & ~now
        terminated |= now

        pendulum, rotor = inner._quantized_angles()
        tilt = torch.abs(wrap_to_pi(pendulum - math.pi))
        inside = tilt <= tol

        first_in = inside & (arrived < 0) & live
        arrived = torch.where(first_in, torch.full_like(arrived, step), arrived)
        if step >= steps - hold_steps:
            left_late |= ~inside & live
        first_fall = (tilt > fall) & (fell_step < 0) & live
        fell_step = torch.where(first_fall, torch.full_like(fell_step, step), fell_step)
        if step >= after_steps:
            min_tilt_late = torch.where(
                live, torch.minimum(min_tilt_late, tilt), min_tilt_late
            )
        peak_rotor = torch.maximum(peak_rotor, torch.abs(rotor) * live)
        peak_rotor_rate = torch.maximum(
            peak_rotor_rate, torch.abs(inner._actuator.velocity) * live
        )

    # A cell that never entered the hold window has not held it either.
    held = (~left_late) & (~terminated) & (arrived >= 0)
    fell = fell_step >= 0

    def seconds(step_index: torch.Tensor) -> list[float]:
        """Step indices as seconds for the used cells, nan where the event never came.

        Both `term_step` and `fell_step` hold -1 for a cell the event never reached.
        """
        time_s = torch.where(
            step_index >= 0, step_index.float() * inner.step_dt, torch.nan
        )
        return time_s[:used].tolist()

    held_l = held[:used].tolist()
    term_l = terminated[:used].tolist()
    fell_l = fell[:used].tolist()
    term_s = seconds(term_step)
    fell_s = seconds(fell_step)
    arm_l = arm[:used].tolist()
    rate_l = arm_rate[:used].tolist()
    min_l = min_tilt_late[:used].tolist()
    peak_l = peak_rotor[:used].tolist()
    peak_rate_l = peak_rotor_rate[:used].tolist()

    # Provenance first on every row, as evaluate_swingup.py carries it: the bound and
    # the rate are not in the checkpoint, and a map without them cannot be read later.
    # The travel bound is there because it is what a `T` cell crossed, and the
    # swing-up task's pi is a task setting a later run could override.
    provenance = {
        "task": args.task,
        "checkpoint": args.checkpoint,
        "physics_hz": round(1.0 / cfg.sim.dt),
        "accel_bound_rad_s2": inner._actuator.max_acceleration,
        "max_rotor_angle_rad": round(cfg.max_rotor_angle_rad, 4),
        "seed": args.seed,
        "duration_s": duration,
        "hold_deg": args.hold_deg,
        "hold_s": args.hold_s,
    }
    rows = []
    for e in range(used):
        rows.append(
            {
                **provenance,
                "env": e,
                "arm_rad": round(arm_l[e], 4),
                "arm_rate_rad_s": round(rate_l[e], 4),
                "tilt_deg": args.tilt_deg,
                "pendulum_rate_rad_s": args.pendulum_rate,
                "held": int(held_l[e]),
                "terminated": int(term_l[e]),
                "term_s": round(term_s[e], 3),
                "fell_s": round(fell_s[e], 3),
                "min_tilt_deg_after_0p5s": float("nan")
                if math.isinf(min_l[e])
                else round(math.degrees(min_l[e]), 3),
                "peak_rotor_rad": round(peak_l[e], 4),
                "peak_rotor_rate_rad_s": round(peak_rate_l[e], 3),
            }
        )

    # The map, one character per cell, rows top to bottom in increasing arm angle and
    # columns left to right in increasing arm rate. `H` held, `h` held after falling
    # past 30 degrees and being swung back up, `T` ended on the travel bound, `F` fell
    # and did not recover, `.` left the hold window without falling.
    arm_ticks = arm_axis.tolist()
    rate_ticks = rate_axis.tolist()
    print(
        f"[map  ] rows: arm rad; columns: arm rate {rate_ticks[0]:+.2f} to "
        f"{rate_ticks[-1]:+.2f} rad/s left to right",
        flush=True,
    )
    print(
        f"[map  ] env {bench_env} (row {arm_ticks[bench_row]:+.2f} rad, column "
        f"{rate_ticks[bench_col]:+.2f} rad/s) sits at the bench arrival instead, "
        f"{args.bench_arm_rad - arm_ticks[bench_row]:+.2f} rad and "
        f"{args.bench_arm_rate - rate_ticks[bench_col]:+.2f} rad/s off the lattice",
        flush=True,
    )
    for r in range(side):
        cells = []
        for c in range(side):
            e = r * side + c
            if term_l[e]:
                cells.append("T")
            elif held_l[e]:
                cells.append("h" if fell_l[e] else "H")
            elif fell_l[e]:
                cells.append("F")
            else:
                cells.append(".")
        print(f"[map  ] {arm_ticks[r]:+6.2f}  {''.join(cells)}", flush=True)

    held_grid = held[:used].view(side, side).float()
    print(
        f"[eval ] held {int(held[:used].sum())} of {used} cells, "
        f"{int((held & ~fell)[:used].sum())} of them without a fall; terminated "
        f"{int(terminated[:used].sum())}; fell past {FALL_DEG:.0f} deg "
        f"{int(fell[:used].sum())}",
        flush=True,
    )
    print("[eval ] held fraction by arm rate (columns):", flush=True)
    for c, frac in enumerate(held_grid.mean(dim=0).tolist()):
        print(f"[eval ]   {rate_ticks[c]:+6.2f} rad/s  {frac:.3f}", flush=True)
    print("[eval ] held fraction by arm angle (rows):", flush=True)
    for r, frac in enumerate(held_grid.mean(dim=1).tolist()):
        print(f"[eval ]   {arm_ticks[r]:+6.2f} rad    {frac:.3f}", flush=True)

    e = bench_env
    outcome = "held" if held_l[e] else "not held"
    if term_l[e]:
        outcome += f", terminated at {term_s[e]:.2f} s"
    if fell_l[e]:
        outcome += f", fell at {fell_s[e]:.2f} s"
    print(
        f"[eval ] bench arrival arm {arm_l[e]:+.2f} rad at {rate_l[e]:+.2f} rad/s, "
        f"cell env {e} (row {arm_ticks[bench_row]:+.2f} rad, column "
        f"{rate_ticks[bench_col]:+.2f} rad/s): {outcome}",
        flush=True,
    )
    lo_a, hi_a = sorted(args.arm_rad_range)
    lo_r, hi_r = sorted(args.arm_rate_range)
    if not (lo_a <= args.bench_arm_rad <= hi_a and lo_r <= args.bench_arm_rate <= hi_r):
        print(
            "[warn ] the bench arrival lies outside the grid; its cell is an edge "
            "cell moved beyond the axis range, by more than half a spacing",
            flush=True,
        )

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"[done ] wrote {len(rows)} rows to {path}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    # An exception here has to become a non-zero exit. Left to propagate, Kit's own
    # teardown returns 0 after the traceback, and a driver that trusts the code then
    # runs every later step against a map that was never written.
    try:
        code = main() or 0
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        code = 1
    close_and_exit(simulation_app, code)

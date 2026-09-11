"""Scripted swing-up baseline: a bang-bang pump behind a travel governor, then LQR.

The baseline is a bang-bang pump into LQR gains near vertical. It is also the check on
the reduced pendulum model in `src/furuta/planar.py`, which says a governed pump swings
up inside the travel bound. This script runs the same controller against the
full asset through the same observations a policy gets, quantized angles and
finite-differenced rates, so a feasibility claim survives or dies on the pipeline the
learner actually faces.

The controller is three rules, no learned parameters:

- Pump: `u = a_max * sign(pendulum_rate * cos(tilt))`, which adds energy whenever the
  rotor's push and the pendulum's motion agree.
- Governor: when the arm's stopping distance at full braking would carry it past the
  allowance, brake instead. The governor is the entire difference between 24 rad of
  travel and less than 2.
- Capture: inside the recoverable set implied by the 11.78 rad/s^2 acceleration bound,
  switch to LQR on the four states, the same gains and weights as experiment 03's
  recoverable-set analysis.

Milestone 05's second goal replaces the LQR at the handover with the trained balance
policy. With
`--checkpoint` the capture rule is unchanged and the command inside the set is the
policy's mean action scaled by `a_max`, which is how the environment scaled it in
training. `--catch-mode` narrows the handover set for a policy whose measured catch
capacity is smaller than the theoretical bound. Each episode's state at handover and its
outcome go to `--episodes-out`, which is what says whether a policy trained from near
rest takes a swing-up's arrival.

`--pump firmware` replaces the bang-bang pump (`--pump textbook`) with the board's own
swing-up (ADR-0004, `furuta.kick`): the initial 150-microstep move, the zero-crossing
detector over integer encoder counts, blocking position moves on the L6474 profile with
the loop frozen while one is in flight, and the handover at 1 degree of upright with no
rate condition. The environment runs in position mode so the rotor follows the driver's
profile, and after the handover the LQR or the policy's acceleration is integrated by
the same `AccelerationCommandActuator` the environment uses in acceleration mode, seeded
at rest at the handover angle as the board's own integrator is. `--kicks-out` records
every kick for the logged-trace comparison. Starts still come from the task's reset
spread, where the board starts from a settled pendulum. The textbook path is unchanged.

Run on the training host:

    python -u scripts/scripted_swingup.py --headless --out results/scripted.csv
    python -u scripts/scripted_swingup.py --headless --record --steps 9000
    python -u scripts/scripted_swingup.py --headless --physics-hz 4000 \
        --checkpoint logs/rsl_rl/furuta_balance/seed1/model_299.pt \
        --episodes-out results/handover_seed1.csv --out results/handover.csv
    python -u scripts/scripted_swingup.py --headless --physics-hz 4000 --pump firmware \
        --episodes-out results/handover_firmware_lqr.csv \
        --kicks-out results/handover_firmware_lqr_kicks.csv \
        --out results/handover_firmware.csv
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
parser.add_argument("--num-envs", type=int, default=256)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--allowance", type=float, default=2.0, help="governor bound, rad")
parser.add_argument("--hold-deg", type=float, default=3.0)
parser.add_argument(
    "--hold-s", type=float, default=5.0, help="trailing window that must stay inside"
)
parser.add_argument("--out", default=None, help="csv path for the summary row")
parser.add_argument(
    "--pump",
    choices=["textbook", "energy", "kick", "firmware"],
    default="textbook",
    help="textbook is the governed bang-bang pump above; energy is the same law with "
    "its magnitude scaled by how far the energy still has to go (Astrom and Furuta), "
    "so the push tapers as the separatrix nears and an arrival lands inside a wide "
    "handover set that bang-bang overshoots; kick is the firmware's idea on the "
    "acceleration path, one rest-to-rest pulse of --kick-rad against the swing at "
    "each pass through the bottom and nothing between, so the arm never runs fast; "
    "firmware is the board's own swing-up, kicks on the L6474 position-move profile "
    "timed by its zero-crossing detector over encoder counts, with the environment in "
    "position mode",
)
parser.add_argument(
    "--pump-gain",
    type=float,
    default=4.0,
    help="under --pump energy: the push is full until the energy fraction passes "
    "1 - 1/gain, then tapers linearly to zero at the separatrix",
)
parser.add_argument(
    "--catch-squash",
    action="store_true",
    help="pass the catch policy's action through tanh instead of the clamp it trained "
    "under. The swing-up task squashes its actions, so a balance checkpoint "
    "warm-started into it is driven this way; this replays the checkpoint under the "
    "same bound",
)
parser.add_argument(
    "--kick-rad",
    type=float,
    default=0.393,
    help="under --pump kick: the arc of each rest-to-rest pulse, rad. The default is "
    "the firmware's 200-microstep kick",
)
parser.add_argument(
    "--pump-sign",
    type=float,
    default=1.0,
    choices=[1.0, -1.0],
    help="sign of the pump law, to test the asset's coupling convention",
)
parser.add_argument(
    "--trace", default=None, help="csv path for a per-step trace of environment 0"
)
parser.add_argument(
    "--duration-s",
    type=float,
    default=None,
    help="metrics rollout length; default is the task's episode length",
)
parser.add_argument(
    "--physics-hz",
    type=float,
    default=None,
    help="override the physics rate; the control rate stays at 500 Hz",
)
parser.add_argument(
    "--position-iters",
    type=int,
    default=None,
    help="raise the TGS position iteration floor, the solver's internal substepping",
)
parser.add_argument(
    "--velocity-iters",
    type=int,
    default=None,
    help="raise the PhysX velocity iteration floor",
)
parser.add_argument(
    "--checkpoint",
    default=None,
    help="balance policy to hand over to; omit for the LQR baseline",
)
parser.add_argument(
    "--policy-task",
    default="Furuta-Balance-Direct-Play-v0",
    help="task whose agent config built the checkpoint",
)
parser.add_argument(
    "--catch-mode",
    type=float,
    default=1.011,
    help="hand over inside this bound on the unstable mode, rad/s; "
    "1.011 is the full recoverable set at 11.78 rad/s^2",
)
parser.add_argument(
    "--catch-tilt",
    type=float,
    default=None,
    help="hand over inside this tilt from upright, rad. Default 0.35 under textbook, "
    "the recoverable set's tilt gate and the balance task's termination angle, where "
    "a pump enters the set at the edge of everything a near-upright policy trained "
    "on. Default 0.01745 (1 degree) under firmware, the board's own handover window, "
    "START_ANGLE in the firmware source, applied with no rate condition",
)
parser.add_argument(
    "--policy-bound",
    type=float,
    default=None,
    help="the acceleration bound the checkpoint trained with, rad/s^2, when it is not "
    "the configured one; also the LQR's clamp. Under --pump textbook the "
    "environment's bound is raised to it if lower",
)
parser.add_argument(
    "--accel-bound",
    type=float,
    default=None,
    help="rotor acceleration bound for the pump and the environment, rad/s^2; the "
    "configured 11.78 by default. The LQR and the policy keep the configured bound "
    "either way, so this asks what the swing-up needs, not what the catch is allowed",
)
parser.add_argument(
    "--episodes-out",
    default=None,
    help="csv path for one row per episode: the state at handover and the outcome",
)
parser.add_argument(
    "--kicks-out",
    default=None,
    help="csv path for every kick under --pump firmware: env, kick, t_s, sign, "
    "microsteps. Kick 0 is the initial 150-microstep move; the logged trace's clock "
    "starts when that move completes",
)
parser.add_argument(
    "--start-at-rest",
    action="store_true",
    help="start every episode from a settled pendulum with the arm at zero, as the "
    "board does, instead of the task's reset spread; for the logged-trace comparison",
)
parser.add_argument("--record", action="store_true", help="write a clip instead")
parser.add_argument(
    "--render-per-control-step",
    action="store_true",
    help="render once per control step instead of once per physics substep. At 4 kHz "
    "the per-substep default asks for eight renders per frame and the recorder "
    "then returns blank frames at irregular intervals",
)
parser.add_argument("--steps", type=int, default=9000, help="clip length, 2 ms steps")
parser.add_argument("--output", default="videos/m5/scripted")
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

firmware = args.pump == "firmware"
if args.catch_tilt is None:
    args.catch_tilt = math.radians(1.0) if firmware else 0.35
if firmware and args.accel_bound is not None:
    raise SystemExit(
        "--accel-bound has no meaning under --pump firmware: the kicks are position "
        "moves on the driver's profile, not clamped accelerations"
    )
if args.kicks_out and not firmware:
    raise SystemExit(
        "--kicks-out needs --pump firmware; the textbook pump has no kicks"
    )

if args.record:
    args.enable_cameras = True
app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Roll the scripted controller out; report the gate or write the clip."""
    from dataclasses import replace

    import gymnasium as gym
    import numpy as np
    import torch
    from scipy.linalg import solve_continuous_are

    import furuta.tasks  # noqa: F401  (registration side effect)
    from furuta.actuator import AccelerationCommandActuator
    from furuta.kick import KickLaw
    from furuta.parameters import FurutaParameters

    params = FurutaParameters.from_yaml()
    # Two bounds. `a_catch` is the configured one, which sized the recoverable set and
    # scaled the balance policy's actions in training. `a_max` is what the pump and the
    # environment use, the same unless --accel-bound raises it.
    a_catch = (
        args.policy_bound
        if args.policy_bound is not None
        else params.max_acceleration_rad_s2
    )
    a_max = args.accel_bound if args.accel_bound is not None else a_catch
    if a_max < a_catch and not firmware:
        # Below the configured bound the actuator would clip the catch controllers
        # without the trace saying so; the question this flag asks is only upward.
        raise SystemExit(
            f"--accel-bound {a_max} is below the configured {a_catch} rad/s^2"
        )
    omega_g_sq = params.omega_g_squared
    omega_g = math.sqrt(omega_g_sq)
    factor = 2.0 / 3.0 + params.normalized_shaft_inertia
    coupling = params.rotor_arm_length_m / (params.pendulum_length_m * factor)

    lin_a = np.array(
        [
            [0, 1, 0, 0],
            [omega_g_sq, -omega_g / params.quality_factor, 0, 0],
            [0, 0, 0, 1],
            [0, 0, 0, 0],
        ]
    )
    lin_b = np.array([[0.0], [coupling], [0.0], [1.0]])
    weights = np.diag([100.0, 1.0, 1.0, 0.1])
    riccati = solve_continuous_are(lin_a, lin_b, weights, [[1.0]])
    gains = (lin_b.T @ riccati).ravel()

    spec = gym.spec(args.task)
    cfg = spec.kwargs["env_cfg_entry_point"]()
    cfg.rotor_target_interpolation = not args.stepped_rotor
    cfg.scene.num_envs = args.num_envs
    cfg.seed = args.seed
    # The controller works in rad/s^2 and the actuator clamps to [-1, 1] * a_max, so
    # the tanh bound would distort every saturated command.
    cfg.squash_actions = False
    if firmware:
        # The rotor has to follow the driver's profile, which is a position trajectory,
        # so the action is the rotor angle; `scripts/replay_trace.py` is the precedent.
        cfg.rotor_command_mode = "position"
        print("[cfg  ] rotor_command_mode=position pump=firmware", flush=True)
    if args.start_at_rest:
        cfg.initial_pendulum_angle_range = [0.0, 0.0]
        cfg.initial_pendulum_rate_range = [0.0, 0.0]
        cfg.initial_rotor_angle_range = [0.0, 0.0]
        cfg.initial_rotor_rate_range = [0.0, 0.0]
        cfg.hanging_reset_fraction = 0.0
        cfg.balance_reset_fraction = 0.0
        print("[cfg  ] start at rest", flush=True)
    if args.accel_bound is not None:
        cfg.max_acceleration_rad_s2 = args.accel_bound
        print(f"[cfg  ] max_acceleration_rad_s2={args.accel_bound}", flush=True)
    elif args.policy_bound is not None and not firmware:
        cfg.max_acceleration_rad_s2 = a_catch
        print(f"[cfg  ] max_acceleration_rad_s2={a_catch} (policy bound)", flush=True)
    if args.physics_hz is not None:
        cfg.sim.dt = 1.0 / args.physics_hz
        cfg.decimation = max(1, round(params.control_dt_s * args.physics_hz))
        print(f"[cfg  ] sim.dt={cfg.sim.dt} decimation={cfg.decimation}", flush=True)
    if args.position_iters is not None:
        cfg.sim.physx.min_position_iteration_count = args.position_iters
        print(f"[cfg  ] min_position_iteration_count={args.position_iters}", flush=True)
    if args.velocity_iters is not None:
        cfg.sim.physx.min_velocity_iteration_count = args.velocity_iters
        cfg.sim.physx.enable_external_forces_every_iteration = True
        print(f"[cfg  ] min_velocity_iteration_count={args.velocity_iters}", flush=True)
    duration = args.duration_s if args.duration_s else cfg.episode_length_s
    # The time-out has to fall outside the scored window. It fires one step before the
    # episode length and resets every environment in place to hanging, so a loop that
    # runs exactly the episode length reads a hanging pendulum on its last iteration
    # and scores every survivor as having left the hold window. One second of slack
    # keeps the reset out of the window whatever the duration.
    cfg.episode_length_s = duration + 1.0

    if args.record:
        cfg.scene.num_envs = args.num_envs if args.num_envs != 256 else 9
        cfg.scene.env_spacing = 0.85
        cfg.sim.render_interval = 1
        if args.render_per_control_step:
            cfg.sim.render_interval = cfg.decimation
        if cfg.scene.num_envs == 1:
            # One rig, framed for the whole swing envelope: this camera shows about
            # 0.68 of its standoff in height, and two closer attempts clipped the
            # pendulum at the top of the climb (the making-experiment-gifs notes).
            cfg.viewer.eye = (0.61, -0.86, 0.63)
            cfg.viewer.lookat = (0.0, 0.0, 0.35)
        else:
            cfg.viewer.eye = (0.62, -0.78, 0.50)
            cfg.viewer.lookat = (0.06, 0.0, 0.34)
        cfg.episode_length_s = 1000.0

    env = gym.make(args.task, cfg=cfg, render_mode="rgb_array" if args.record else None)
    policy = None
    if args.checkpoint:
        from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper
        from rsl_rl.runners import OnPolicyRunner

        agent_cfg = gym.spec(args.policy_task).kwargs["rsl_rl_cfg_entry_point"]()
        # The runner sizes its networks off the wrapper. Stepping stays on the bare
        # environment below, so the wrapper is used once here and set aside.
        runner = OnPolicyRunner(
            RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions),
            agent_cfg.to_dict(),
            log_dir=None,
            device=agent_cfg.device,
        )
        runner.load(args.checkpoint)
        policy = runner.get_inference_policy(device=agent_cfg.device)
        print(f"[ckpt ] {args.checkpoint}", flush=True)
    if args.record:
        env = gym.wrappers.RecordVideo(
            env,
            video_folder=args.output,
            step_trigger=lambda step: step == 0,
            video_length=args.steps,
            disable_logger=True,
        )

    inner = env.unwrapped
    device = inner.device
    n = inner.num_envs
    gains_t = torch.tensor(gains, device=device, dtype=torch.float32)

    obs_dict, _ = env.reset(seed=args.seed)
    obs = obs_dict["policy"]

    law = None
    if firmware:
        # One board loop per environment, started with the rotor where the reset put
        # it. The catch integrator is the environment's own actuator model, run here
        # because the environment is in position mode.
        law = KickLaw(params, n, inner.step_dt, device=device)
        law.reset(position=obs[:, 3])
        catch_actuator = AccelerationCommandActuator(
            replace(params, max_acceleration_rad_s2=a_catch), n, device=device
        )
        rad_per_count = params.rad_per_encoder_count

    steps = args.steps if args.record else int(duration / inner.step_dt)
    hold_steps = int(args.hold_s / inner.step_dt)
    tol = math.radians(args.hold_deg)

    trace_rows = []
    # Kick pump state. A pulse is `kick_half` control steps at +a then as many at -a,
    # the rest-to-rest move that covers --kick-rad; the arc it covers is quantised to
    # whole steps and reported.
    kick_half = max(1, round(math.sqrt(args.kick_rad / a_max) / inner.step_dt))
    kick_arc = a_max * (kick_half * inner.step_dt) ** 2
    kick_start = torch.full((n,), -(10**9), dtype=torch.long, device=device)
    kick_dir = torch.zeros(n, device=device)
    kicks = torch.zeros(n, dtype=torch.long, device=device)
    prev_from_hanging = None
    capturing = torch.zeros(n, dtype=torch.bool, device=device)
    terminated = torch.zeros(n, dtype=torch.bool, device=device)
    arrived = torch.full((n,), -1, dtype=torch.long, device=device)
    left_late = torch.zeros(n, dtype=torch.bool, device=device)
    peak_travel = torch.zeros(n, device=device)
    handover = torch.full((n,), -1, dtype=torch.long, device=device)
    handover_state = torch.zeros(n, 4, device=device)
    turns = torch.zeros(n, dtype=torch.long, device=device)
    swing_sign = torch.zeros(n, device=device)
    turn_angle = torch.zeros(n, device=device)

    for step in range(steps):
        cos_t, sin_t, rate, rotor, rotor_rate = obs.unbind(dim=-1)
        tilt = torch.atan2(sin_t, cos_t)
        # Frozen at first termination: Isaac Lab
        # resets a terminated environment in place and the fresh episode must not be
        # credited to the one under test.
        live = ~terminated

        # Half swings, counted as the logged trace's are: the pendulum rate changes
        # sign more than 0.1 rad from hanging, and the pendulum has moved at least
        # 0.1 rad since the last counted reversal. The first gate drops the encoder's
        # dither at rest, the second drops a dither at a peak, where the quantized
        # slope can sit at zero or flicker for several samples. Zero-rate samples carry
        # the previous sign, so a flat window across an extremum does not hide it.
        from_hanging = tilt - torch.sign(tilt) * math.pi
        sign_now = torch.where(rate != 0, torch.sign(rate), swing_sign)
        reversal = (
            (swing_sign * sign_now < 0)
            & (math.pi - tilt.abs() > 0.1)
            & ((from_hanging - turn_angle).abs() > 0.1)
        )
        counted = reversal & ~capturing & live
        turns += counted.long()
        turn_angle = torch.where(counted, from_hanging, turn_angle)
        swing_sign = sign_now

        if firmware:
            t_now = step * inner.step_dt
            # The count the board's loop reads: the encoder lattice from hanging, which
            # is the tilt turned half a revolution. Wrapped, so it runs -1200 to 1200
            # where the board's would run on to 1201; the handover fires first.
            counts = torch.round(torch.atan2(-sin_t, -cos_t) / rad_per_count).long()
            # No acceleration command during the swing-up. The kicks are position
            # moves the law issues below; this column of the trace reads zero.
            u = torch.zeros_like(tilt)
            # The board tests handover at each poll, before any kick, with no rate
            # condition (main.c:1786), and a loop inside a move does not poll.
            capturing |= law.awake(t_now) & (tilt.abs() < args.catch_tilt)
        elif args.pump == "kick":
            # Through the bottom, not mid-pulse and not handed over: one pulse against
            # the swing, the sign the energy law takes there. Consecutive passes have
            # opposite pendulum rates, so the pulses alternate and the arm returns.
            in_pulse = step - kick_start < 2 * kick_half
            if prev_from_hanging is None:
                crossing = torch.zeros_like(in_pulse)
            else:
                crossing = (
                    (prev_from_hanging * from_hanging < 0) & ~in_pulse & ~capturing
                )
            prev_from_hanging = from_hanging
            new_dir = -torch.sign(rate)
            new_dir = torch.where(new_dir == 0, torch.ones_like(new_dir), new_dir)
            kick_dir = torch.where(crossing, new_dir, kick_dir)
            kick_start = torch.where(
                crossing, torch.full_like(kick_start, step), kick_start
            )
            kicks += crossing.long()
            elapsed = step - kick_start
            u = torch.where(
                elapsed < kick_half,
                kick_dir * a_max,
                torch.where(
                    elapsed < 2 * kick_half, -kick_dir * a_max, torch.zeros_like(rate)
                ),
            )
            capturing |= (tilt.abs() < args.catch_tilt) & (
                (rate + 7.351 * tilt).abs() < args.catch_mode
            )
        else:
            u = torch.where(rate * cos_t >= 0, a_max, -a_max) * args.pump_sign
            if args.pump == "energy":
                # Energy from upright per unit inertia, as the reward writes it, as a
                # fraction of the separatrix: 0 hanging at rest, 1 arriving with none.
                fraction = 1.0 + (0.5 * rate.pow(2) + omega_g_sq * (cos_t - 1.0)) / (
                    2.0 * omega_g_sq
                )
                u = u * (args.pump_gain * (1.0 - fraction)).clamp(0.0, 1.0)
            stop = rotor_rate.pow(2) / (2.0 * a_max)
            u = torch.where(
                (rotor_rate > 0) & (rotor + stop >= 0.95 * args.allowance), -a_max, u
            )
            u = torch.where(
                (rotor_rate < 0) & (rotor - stop <= -0.95 * args.allowance), a_max, u
            )

            capturing |= (tilt.abs() < args.catch_tilt) & (
                (rate + 7.351 * tilt).abs() < args.catch_mode
            )
        state = torch.stack([tilt, rate, rotor, rotor_rate], dim=-1)
        first_catch = capturing & (handover < 0) & live
        handover = torch.where(first_catch, torch.full_like(handover, step), handover)
        handover_state = torch.where(first_catch.unsqueeze(-1), state, handover_state)
        if policy is None:
            catch = (-(state * gains_t).sum(dim=-1)).clamp(-a_catch, a_catch)
        else:
            with torch.inference_mode():
                raw = policy(obs_dict).squeeze(-1)
                bounded = torch.tanh(raw) if args.catch_squash else raw.clamp(-1.0, 1.0)
                catch = bounded * a_catch
        u = torch.where(capturing, catch, u)

        if firmware:
            if first_catch.any():
                # The board hands over with the rotor at rest and integrates its own
                # acceleration command from there (main.c:1854); the catch runs on the
                # integrator the environment uses in acceleration mode, seeded there.
                catch_actuator.reset(
                    first_catch, position=rotor[first_catch], velocity=0.0
                )
            held = catch_actuator.step(u / a_catch, inner.step_dt)
            targets, in_flight = law.step(counts, t_now, active=live & ~capturing)
            action = torch.where(capturing, held, targets)
        else:
            action = u / a_max

        if args.trace:
            trace_row = [
                step * inner.step_dt,
                tilt[0].item(),
                rate[0].item(),
                rotor[0].item(),
                rotor_rate[0].item(),
                u[0].item(),
                int(capturing[0].item()),
            ]
            if firmware:
                trace_row += [int(in_flight[0].item()), action[0].item()]
            trace_rows.append(trace_row)
        obs_dict, _, _, _, _ = env.step(action.unsqueeze(-1))
        obs = obs_dict["policy"]

        inside = tilt.abs() < tol
        first = inside & (arrived < 0) & live
        arrived = torch.where(first, torch.full_like(arrived, step), arrived)
        if step >= steps - hold_steps:
            left_late |= ~inside & live
        grown = torch.maximum(peak_travel, rotor.abs())
        peak_travel = torch.where(live, grown, peak_travel)
        now = inner.reset_terminated.bool() & live
        terminated |= now
        if now.any():
            capturing &= ~now

    env.close()

    success = (~left_late) & (~terminated) & (arrived >= 0)
    arrive_s = arrived[arrived >= 0].float() * inner.step_dt
    handed = handover >= 0
    handover_s = handover[handed].float() * inner.step_dt
    mode = handover_state[:, 1] + 7.351 * handover_state[:, 0]

    def median(values: torch.Tensor) -> float:
        return values.median().item() if values.numel() else float("nan")

    def rms(values: torch.Tensor) -> float:
        return values.pow(2).mean().sqrt().item() if values.numel() else float("nan")

    row = {
        "controller": (
            "/".join(Path(args.checkpoint).parts[-3:-1]) if args.checkpoint else "lqr"
        ),
        "physics_hz": round(1.0 / cfg.sim.dt),
        "accel_bound_rad_s2": a_max,
        "policy_bound_rad_s2": a_catch,
        "catch_mode_rad_s": args.catch_mode,
        "catch_tilt_rad": args.catch_tilt,
        "catch_squash": int(args.catch_squash),
        "seed": args.seed,
        "episodes": n,
        "allowance_rad": args.allowance,
        "arrival_rate": (arrived >= 0).float().mean().item(),
        "success_rate": success.float().mean().item(),
        "terminated_rate": terminated.float().mean().item(),
        "arrive_s_median": (
            arrive_s.median().item() if arrive_s.numel() else float("nan")
        ),
        "peak_travel_rad": peak_travel.max().item(),
        "handover_rate": handed.float().mean().item(),
        "handover_s_median": median(handover_s),
        "turns_median": median(turns[handed].float()),
        "catch_rate": (
            (success & handed).sum().item() / handed.sum().item()
            if handed.any()
            else float("nan")
        ),
        "handover_mode_rms": rms(mode[handed]),
        "handover_rotor_rate_rms": rms(handover_state[handed, 3]),
    }
    if firmware:
        # No mode bound under the board's law, so the column reads as unbounded.
        row["catch_mode_rad_s"] = math.inf
        row = {
            "pump": "firmware",
            **row,
            "kicks_median": median(law.kicks[handed].float()),
        }
    elif args.pump == "energy":
        row = {"pump": "energy", "pump_gain": args.pump_gain, **row}
    elif args.pump == "kick":
        row = {
            "pump": "kick",
            "kick_rad": round(kick_arc, 4),
            **row,
            "kicks_median": median(kicks[handed].float()),
        }
    print("[gate ] " + "  ".join(f"{k}={v}" for k, v in row.items()), flush=True)
    if args.episodes_out:
        episodes_path = Path(args.episodes_out)
        episodes_path.parent.mkdir(parents=True, exist_ok=True)
        columns = [
            "env",
            "handover_s",
            "tilt_deg",
            "rate_rad_s",
            "mode_rad_s",
            "rotor_rad",
            "rotor_rate_rad_s",
            "turns",
            "arrive_s",
            "held",
            "terminated",
            "peak_travel_rad",
        ]
        if firmware:
            columns.append("kicks")
        hs = handover_state.cpu()
        with episodes_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for i in range(n):
                handed_i = handover[i].item() >= 0
                writer.writerow(
                    [
                        i,
                        round(handover[i].item() * inner.step_dt, 3)
                        if handed_i
                        else "",
                        round(math.degrees(hs[i, 0].item()), 3) if handed_i else "",
                        round(hs[i, 1].item(), 4) if handed_i else "",
                        round(mode[i].item(), 4) if handed_i else "",
                        round(hs[i, 2].item(), 4) if handed_i else "",
                        round(hs[i, 3].item(), 4) if handed_i else "",
                        turns[i].item(),
                        round(arrived[i].item() * inner.step_dt, 3)
                        if arrived[i].item() >= 0
                        else "",
                        int(success[i].item()),
                        int(terminated[i].item()),
                        round(peak_travel[i].item(), 4),
                    ]
                    + ([law.kicks[i].item()] if firmware else [])
                )
        print(f"[done ] wrote {episodes_path}", flush=True)
    if args.kicks_out:
        kicks_path = Path(args.kicks_out)
        kicks_path.parent.mkdir(parents=True, exist_ok=True)
        with kicks_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["env", "kick", "t_s", "sign", "microsteps"])
            for env_i, index, t_s, sign, microsteps in law.log:
                writer.writerow([env_i, index, round(t_s, 4), sign, microsteps])
        print(f"[done ] wrote {kicks_path}", flush=True)
    if args.trace:
        trace_path = Path(args.trace)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "t_s",
                    "tilt_rad",
                    "rate_rad_s",
                    "rotor_rad",
                    "rotor_rate_rad_s",
                    "u",
                    "catching",
                ]
                + (["in_flight", "rotor_cmd_rad"] if firmware else [])
            )
            writer.writerows(trace_rows)
        print(f"[done ] wrote {trace_path}", flush=True)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        if not new:
            with path.open(newline="") as f:
                header = next(csv.reader(f), [])
            if header != list(row):
                raise SystemExit(
                    f"{path} has columns {header}, this run writes {list(row)}; "
                    "move the old file aside rather than mixing the two"
                )
        with path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row))
            if new:
                writer.writeheader()
            writer.writerow(row)
        print(f"[done ] wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    # An exception here has to become a non-zero exit. Left to propagate, Kit's own
    # teardown returns 0 after the traceback, and a driver that trusts the code then
    # runs every later step as though this one had succeeded.
    try:
        code = main() or 0
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        code = 1
    close_and_exit(simulation_app, code)

"""Replay a logged swing-up through the full PhysX articulation.

Reads a `probe-trace` capture, drives the sim rotor along the rotor angle the real
machine made, leaves the pendulum free, and writes the simulated tilt beside the
measured one.

`furuta.trace.replay` runs the same comparison against the single-angle model in
`furuta.planar`. Driven by this exact rotor motion that model reaches 163 degrees from
upright where the hardware reached 1.4. A Furuta pumps against the rotor's rate, and the
single-angle model carries no term for it. Both results are in
`docs/experiments/04-model-reconciliation/writeup.md`.

The rotor follows the measured angle rather than a measured acceleration. Reconstructing
acceleration from a microstep-quantized angle leaves a small bias that two integrations
turn into a ramp, walking the rotor 640 degrees over a trace whose real span is 22.5
(`FurutaEnvCfg.rotor_command_mode`).

Run on the training host:

    python -u scripts/replay_trace.py --headless --plant after
        --trace docs/experiments/03-hardware-bringup/trace.tsv
        --out results/replay_after.csv
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from isaaclab.app import AppLauncher

from furuta.shutdown import close_and_exit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--plant",
    choices=["before", "after"],
    default="after",
    help="before zeroes Coulomb, drag and tilt; after uses the reconciled config",
)
parser.add_argument("--trace", required=True, help="a probe-trace capture")
parser.add_argument(
    "--run",
    default="0",
    help="which run in the capture, or `all` to join the swing-up to the balance hold",
)
parser.add_argument(
    "--physics-hz",
    type=float,
    default=4000.0,
    help="physics rate; the replay climbs 23 degrees higher at 4000 than at 1000",
)
parser.add_argument(
    "--gap-profile",
    choices=["linear", "bangbang"],
    default="linear",
    help="what to assume for the rotor inside the capture's logging dropouts",
)
parser.add_argument(
    "--playback",
    action="store_true",
    help="drive BOTH joints from the capture, simulating nothing. This is the measured"
    " trace made visible, for showing beside a replay; it is not a result.",
)
parser.add_argument(
    "--stepped-rotor",
    action="store_true",
    help="hand the drive one target per control period instead of walking it across"
    " the substeps (FurutaEnvCfg.rotor_target_interpolation)",
)
parser.add_argument("--out", required=True)
parser.add_argument("--video", default=None, help="also record video to this folder")
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

if args.video:
    # Offscreen rendering needs the camera extensions, same as `--enable_cameras`.
    args.enable_cameras = True
app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Drive the sim rotor along the measured trajectory and log both pendulums."""
    import gymnasium as gym
    import torch
    from isaaclab.utils.math import wrap_to_pi

    import furuta.tasks  # noqa: F401 (registration side effect)
    from furuta.env import PARAMS, FurutaEnvCfg
    from furuta.parameters import gravity_for_tilt
    from furuta.trace import join_runs, read_trace, resample_to_grid

    runs = read_trace(args.trace)
    if args.run == "all":
        # probe-trace restarts its clock at the handover, so one swing-up-then-hold
        # reads as two runs.
        run = join_runs(runs)
    else:
        index = int(args.run)
        if index >= len(runs):
            print(f"[fail ] capture has {len(runs)} runs, asked for {index}")
            return 1
        run = runs[index]

    cfg = FurutaEnvCfg()
    cfg.scene.num_envs = 1
    cfg.scene.env_spacing = 1.2
    cfg.rotor_command_mode = "position"
    cfg.rotor_target_interpolation = not args.stepped_rotor

    if args.plant == "before":
        cfg.pivot_coulomb_deg_per_half_swing = 0.0
        cfg.pivot_drag_coeff = 0.0
        cfg.sim.gravity = gravity_for_tilt(0.0, PARAMS.gravity_m_s2)

    cfg.sim.dt = 1.0 / args.physics_hz
    cfg.decimation = max(1, round(PARAMS.control_dt_s * args.physics_hz))

    grid, rotor_cmd, measured, phase = resample_to_grid(
        run, PARAMS.control_dt_s, gap_profile=args.gap_profile
    )

    # None of the task's guards apply to a replay. The trace starts hanging and the task
    # cuts on exactly that. The travel bound would only truncate the recording.
    cfg.episode_length_s = grid[-1] * 4.0
    cfg.max_pendulum_angle_rad = math.pi
    cfg.max_rotor_angle_rad = 1.0e6
    cfg.reset_upright = False
    cfg.initial_pendulum_angle_range = [0.0, 0.0]
    cfg.initial_pendulum_rate_range = [0.0, 0.0]
    cfg.initial_rotor_angle_range = [0.0, 0.0]
    cfg.initial_rotor_rate_range = [0.0, 0.0]
    cfg.hanging_reset_fraction = 0.0
    cfg.balance_reset_fraction = 0.0

    if args.video:
        cfg.sim.render_interval = 1
        # Framed on the swing envelope, the part that has to stay in shot. The arm
        # pivots at z = 0.35 and the pendulum is 0.265 long. The tip runs from
        # z = 0.085 hanging to 0.615 upright, a 0.53 m band centred on the pivot.
        #
        # Measured off a render rather than assumed: this camera shows about 0.68 times
        # its distance to the target in height. Covering the band with margin needs
        # about 1.1 m of standoff, and the target sits at the pivot rather than below
        # it. Two earlier attempts at 0.62 and 0.81 m both cut the pendulum off at the
        # top at the peak of the climb, the one moment the clip exists for. The empty
        # floor this leaves is cropped out when the GIF is built. Pixels lost off the
        # top of the frame cannot be recovered.
        cfg.viewer.eye = (0.61, -0.86, 0.63)
        cfg.viewer.lookat = (0.0, 0.0, 0.35)

    phases = ", ".join(
        f"{letter}={run.state.count(letter)}" for letter in sorted(set(run.state))
    )
    if args.playback:
        print(
            "[cfg  ] PLAYBACK: both joints from the capture, nothing simulated",
            flush=True,
        )
    print(
        f"[cfg  ] plant={args.plant} physics={args.physics_hz:.0f} Hz "
        f"decimation={cfg.decimation} steps={len(grid)} gap={args.gap_profile} "
        f"run={args.run} samples({phases})",
        flush=True,
    )

    env = gym.make(
        "Furuta-Balance-Direct-v0",
        cfg=cfg,
        render_mode="rgb_array" if args.video else None,
    )
    if args.video:
        env = gym.wrappers.RecordVideo(
            env,
            video_folder=args.video,
            step_trigger=lambda step: step == 0,
            video_length=len(grid),
            disable_logger=True,
        )
    inner = env.unwrapped
    env.reset()

    print(
        f"[cfg  ] coulomb={inner._dissipation.coulomb_rad_s2:.4f} rad/s^2 "
        f"drag={inner._dissipation.drag_coeff:.4f} /rad "
        f"gravity={tuple(round(g, 4) for g in cfg.sim.gravity)}",
        flush=True,
    )

    # Start where the hardware started. The asset hangs at zero and the capture reports
    # tilt from upright, putting the joint angle at the tilt plus half a turn. The
    # initial rate comes off the first few samples, as in the `planar.py` replay.
    span = min(8, len(run.time_s) - 1)
    elapsed = run.time_s[span] - run.time_s[0]
    rate = 0.0
    if span >= 2 and elapsed > 0:
        delta = run.tilt_rad[span] - run.tilt_rad[0]
        rate = math.atan2(math.sin(delta), math.cos(delta)) / elapsed

    joint_pos = inner.robot.data.default_joint_pos.clone()
    joint_vel = torch.zeros_like(joint_pos)
    # Wrapped to start the joint near its own zero rather than at 6.1 rad.
    joint_pos[0, inner._pendulum_idx[0]] = math.atan2(
        math.sin(measured[0] + math.pi), math.cos(measured[0] + math.pi)
    )
    joint_pos[0, inner._rotor_idx[0]] = rotor_cmd[0]
    joint_vel[0, inner._pendulum_idx[0]] = rate
    inner.robot.write_joint_state_to_sim(joint_pos, joint_vel)
    # The rotor follows a stiff position target. The actuator has to agree with the
    # joint it was just placed at or the drive closes the gap at full authority.
    inner._actuator.reset(position=torch.tensor([rotor_cmd[0]], device=inner.device))

    rows = []
    playback_pos = joint_pos.clone()
    playback_vel = torch.zeros_like(joint_vel)
    for step, (time_s, command, truth, letter) in enumerate(
        zip(grid, rotor_cmd, measured, phase, strict=True)
    ):
        action = torch.full((1, 1), command, device=inner.device)
        env.step(action)

        if args.playback:
            # Both joints written from the capture after the step, discarding the
            # physics result.
            playback_pos[0, inner._pendulum_idx[0]] = math.atan2(
                math.sin(truth + math.pi), math.cos(truth + math.pi)
            )
            playback_pos[0, inner._rotor_idx[0]] = command
            inner.robot.write_joint_state_to_sim(playback_pos, playback_vel)
            inner._actuator.reset(position=torch.tensor([command], device=inner.device))

        pendulum = inner.robot.data.joint_pos[0, inner._pendulum_idx[0]]
        tilt = wrap_to_pi(pendulum - math.pi).item()
        rows.append(
            {
                "t_s": round(time_s, 4),
                "measured_tilt_deg": round(math.degrees(truth), 4),
                "sim_tilt_deg": round(math.degrees(tilt), 4),
                "rotor_cmd_deg": round(math.degrees(command), 4),
                "rotor_sim_deg": round(
                    math.degrees(inner.robot.data.joint_pos[0, inner._rotor_idx[0]]), 4
                ),
                "phase": letter,
            }
        )
        if step % 500 == 0:
            print(
                f"[run  ] {time_s:5.2f}s  measured {math.degrees(truth):7.1f}  "
                f"sim {math.degrees(tilt):7.1f}",
                flush=True,
            )

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    reached_sim = min(abs(r["sim_tilt_deg"]) for r in rows)
    reached_hw = min(abs(r["measured_tilt_deg"]) for r in rows)
    print(
        f"[done ] closest approach to upright: hardware {reached_hw:.1f} deg, "
        f"sim {reached_sim:.1f} deg",
        flush=True,
    )

    # If the capture carries a balance hold, say whether the replay held it. Closest
    # approach doesn't answer that. A pendulum swinging straight past vertical posts a
    # small one too.
    hold = [r for r in rows if r["phase"] == "B"]
    if hold:
        held = sum(1 for r in hold if abs(r["sim_tilt_deg"]) < 10.0)
        print(
            f"[done ] balance hold, {len(hold)} steps: hardware within "
            f"{max(abs(r['measured_tilt_deg']) for r in hold):.1f} deg of upright, "
            f"sim within {max(abs(r['sim_tilt_deg']) for r in hold):.1f}; "
            f"sim inside 10 deg for {100.0 * held / len(hold):.0f} percent of it",
            flush=True,
        )
    print(f"[done ] wrote {len(rows)} rows to {path}", flush=True)
    env.close()
    return 0


if __name__ == "__main__":
    code = main()
    close_and_exit(simulation_app, code)

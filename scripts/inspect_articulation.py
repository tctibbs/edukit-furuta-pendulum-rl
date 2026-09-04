"""Load the generated articulation on its own and report the joint layout PhysX parsed.

This does not import `furuta.env`. If the layout is correct here, a fault lies in the
environment.

    python scripts/inspect_articulation.py --headless

Expect 2 degrees of freedom, joints `rotor_joint` and `pendulum_joint`, and bodies
`base`, `arm` and `pendulum`.

It checks topology and joint positions only. No script reads back the mass properties
PhysX loaded.
"""

from __future__ import annotations

import argparse

from isaaclab.app import AppLauncher

# The app launches at import time. The Isaac Lab imports in `main` need it running.
# `add_app_launcher_args` adds `--headless` and `--device`.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--usd", type=str, default="assets/edukit_pendulum.usda")
parser.add_argument("--steps", type=int, default=100)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app


def main() -> int:
    """Spawn the asset, step it, and print its joint layout."""
    # These imports need the app above to be running.
    import isaaclab.sim as sim_utils
    from isaaclab.actuators import ImplicitActuatorCfg
    from isaaclab.assets import Articulation, ArticulationCfg

    from furuta.parameters import FurutaParameters

    params = FurutaParameters.from_yaml()
    print("[step] creating simulation context", flush=True)
    sim = sim_utils.SimulationContext(
        sim_utils.SimulationCfg(dt=params.physics_dt_s, device=args.device)
    )

    print("[step] spawning articulation", flush=True)
    # Only gravity acts on the asset.
    cfg = ArticulationCfg(
        prim_path="/World/Furuta",
        spawn=sim_utils.UsdFileCfg(usd_path=args.usd),
        actuators={
            "all": ImplicitActuatorCfg(
                joint_names_expr=[".*"], stiffness=0.0, damping=0.0
            )
        },
    )
    robot = Articulation(cfg)

    # The reset plays the simulation and builds the articulation. The names and counts
    # below are what PhysX built.
    print("[step] resetting sim", flush=True)
    sim.reset()

    print(f"[ok] joint names   {robot.joint_names}", flush=True)
    print(f"[ok] dof count     {robot.num_joints}", flush=True)
    print(f"[ok] body names    {robot.body_names}", flush=True)

    # An articulation can load and then diverge once the solver runs. The asset starts
    # hanging at equilibrium, undriven. Both positions should stay near zero.
    print("[step] stepping", flush=True)
    for i in range(args.steps):
        robot.write_data_to_sim()
        sim.step()
        robot.update(params.physics_dt_s)
        if i == args.steps - 1:
            pos = robot.data.joint_pos[0]
            print(f"[ok] joint pos after {args.steps}: {pos.tolist()}", flush=True)

    print("[done] articulation loaded and stepped without incident", flush=True)
    return 0


if __name__ == "__main__":
    code = main()
    # Closing the app ends the process and drops any buffered stdout. Every print above
    # flushes for that reason. The exit code is unreliable on this stack. The printed
    # markers show how far a run got.
    simulation_app.close()
    raise SystemExit(code)

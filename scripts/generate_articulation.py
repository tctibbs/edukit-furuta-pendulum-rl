"""Generate the Furuta articulation from the parameter file and check what was written.

`pxr` ships inside Isaac Sim. The script launches Kit only to make that import resolve.
It steps no simulation. Run on the training host:

    python scripts/generate_articulation.py --output assets/edukit_pendulum.usda

The check reads the saved file back and compares its mass properties with
`furuta.parameters`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path("assets/edukit_pendulum.usda"))
# None means `config/edukit.yaml`.
parser.add_argument("--config", type=Path, default=None)
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()

app_launcher = AppLauncher(args)
simulation_app = app_launcher.app

TOLERANCE = 1e-6
"""Relative tolerance. USD stores these values as float32, precise to about 1e-7."""


def verify(usd_path: Path, params) -> bool:
    """Compare the saved file's mass properties with the parameter derivation.

    It opens the saved file from disk, as a loader would.
    """
    from pxr import Usd, UsdPhysics

    stage = Usd.Stage.Open(str(usd_path))
    # USD returns an invalid prim for a missing path instead of raising.
    prim = stage.GetPrimAtPath("/Furuta/pendulum")
    if not prim.IsValid():
        print("[fail] /Furuta/pendulum missing from the stage")
        return False

    api = UsdPhysics.MassAPI(prim)
    mass = api.GetMassAttr().Get()
    com = api.GetCenterOfMassAttr().Get()
    inertia = api.GetDiagonalInertiaAttr().Get()

    expected_inertia = params.pendulum_inertia_about_com_kg_m2
    expected_com_z = -params.pendulum_length_m / 2.0

    # Only these four values have a derivation to check against. The axial inertia and
    # the arm's rest on estimates in `furuta.articulation`, with nothing to check them
    # against.
    checks = [
        ("mass", mass, params.pendulum_mass_kg),
        ("centre of mass z", com[2], expected_com_z),
        ("inertia xx", inertia[0], expected_inertia),
        ("inertia yy", inertia[1], expected_inertia),
    ]

    ok = True
    print(f"\n{'property':<20} {'written':>16} {'expected':>16}")
    print("-" * 54)
    for name, got, want in checks:
        # The floor keeps a zero expected value from demanding exact equality.
        good = abs(got - want) <= TOLERANCE * max(abs(want), 1e-12)
        ok &= good
        print(f"{name:<20} {got:>16.9g} {want:>16.9g} {'' if good else '  MISMATCH'}")

    # Both figures below come from `params`, not from the file.
    print()
    # 3g/(2L), the suspended mode of a uniform rod, where the mass cancels out.
    uniform = params.gravity_m_s2 * 1.5 / params.pendulum_length_m
    print(f"  implied omega_g^2  {params.omega_g_squared:.3f}, manual gives 55.85")
    print(f"  a uniform rod would give {uniform:.3f}")
    return ok


def main() -> int:
    """Generate the asset and verify what was written."""
    from furuta.articulation import build_articulation
    from furuta.parameters import FurutaParameters

    params = FurutaParameters.from_yaml(args.config)
    path = build_articulation(params, args.output)
    print(f"[info] wrote {path}")

    # A failed check still leaves the file on disk.
    passed = verify(path, params)
    print(f"\n  asset check {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    code = main()
    simulation_app.close()
    sys.exit(code)

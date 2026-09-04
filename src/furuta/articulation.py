"""Generate the Furuta pendulum articulation as USD from the parameter file.

Layout, Z up, origin on the rotor axis:

    rotor joint      revolute about Z, base to arm
    arm              extends along +X for r metres
    pendulum joint   revolute about X at the arm tip, arm to pendulum
    pendulum         hangs along -Z for L metres, swinging in the Y-Z plane

Inertia is written explicitly. Isaac Lab's `MassPropertiesCfg` carries only mass and
density. Without explicit inertia, PhysX treats the pendulum as a uniform rod, which
drops the shaft term. That term is worth 1.5 (rad/s)^2 of suspended mode on this unit.
"""

from __future__ import annotations

from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdPhysics

from furuta.parameters import FurutaParameters

ARM_HEIGHT_M = 0.35
"""Height of the rotor arm above the base. It must exceed the pendulum length."""

ROD_RADIUS_M = 0.004
"""Pendulum rod radius. It sizes the drawn rod and its axial inertia. The swing uses
neither."""


ARM_RADIUS_M = 0.008
"""Drawn radius of the arm. The arm's inertia comes from its mass and length."""

ARM_MASS_KG = 0.02
"""Rotor arm mass, an estimate. It sets the rotor's inertia and leaves the pendulum's
free swing alone."""

BASE_RADIUS_M = 0.03
"""Drawn radius of the base column. The base never moves."""

PIVOT_MAX_FORCE = 1.0e2
"""Torque ceiling for the passive pendulum pivot, in N m. Its damping torque stays far
below it."""

ROTOR_MAX_FORCE = 1.0e4
"""Torque ceiling for the rotor drive, in N m, far above the real motor. The actuator
model enforces the acceleration limit."""


def _rigid_body(stage: Usd.Stage, path: str) -> Usd.Prim:
    """Define a rigid body at `path`. Geometry and mass go on afterwards."""
    prim = UsdGeom.Xform.Define(stage, path).GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(prim)
    return prim


def _mass_properties(
    prim: Usd.Prim,
    mass: float,
    com: tuple[float, float, float],
    inertia: tuple[float, float, float],
) -> None:
    """Write mass, centre of mass and diagonal inertia onto a rigid body.

    With all three set, PhysX skips computing its own from the geometry.
    """
    api = UsdPhysics.MassAPI.Apply(prim)
    api.CreateMassAttr().Set(mass)
    api.CreateCenterOfMassAttr().Set(Gf.Vec3f(*com))
    api.CreateDiagonalInertiaAttr().Set(Gf.Vec3f(*inertia))
    # An identity rotation keeps the diagonal above in the body's own frame.
    api.CreatePrincipalAxesAttr().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))


def _cylinder(
    stage: Usd.Stage,
    path: str,
    radius: float,
    height: float,
    axis: str,
    translate: tuple[float, float, float],
) -> None:
    """Draw a visual cylinder. Nothing here applies a collision API."""
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.CreateRadiusAttr().Set(radius)
    cyl.CreateHeightAttr().Set(height)
    cyl.CreateAxisAttr().Set(axis)
    half = height / 2.0
    if axis == "X":
        corner = (half, radius, radius)
    elif axis == "Y":
        corner = (radius, half, radius)
    else:
        corner = (radius, radius, half)
    # A render hint, sized along whichever axis the cylinder runs.
    cyl.CreateExtentAttr().Set([Gf.Vec3f(*(-c for c in corner)), Gf.Vec3f(*corner)])
    UsdGeom.Xformable(cyl.GetPrim()).AddTranslateOp().Set(Gf.Vec3d(*translate))


def _revolute_joint(
    stage: Usd.Stage,
    path: str,
    body0: str,
    body1: str,
    axis: str,
    anchor: tuple[float, float, float],
    driven: bool = False,
) -> None:
    """Define a revolute joint with an angular drive."""
    joint = UsdPhysics.RevoluteJoint.Define(stage, path)
    joint.CreateBody0Rel().SetTargets([body0])
    joint.CreateBody1Rel().SetTargets([body1])
    joint.CreateAxisAttr().Set(axis)
    # One physical point, given once in each body's frame. Every body here starts its
    # own frame at its joint. That makes body1's copy the origin. The identity rotations
    # leave both joint frames aligned with their bodies.
    joint.CreateLocalPos0Attr().Set(Gf.Vec3f(*anchor))
    joint.CreateLocalPos1Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
    joint.CreateLocalRot0Attr().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))
    joint.CreateLocalRot1Attr().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))

    # Every revolute joint needs a drive, including the passive pivot. Isaac Lab's
    # implicit actuator writes stiffness and damping into the drive.
    drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), "angular")
    drive.CreateTypeAttr().Set("force")
    drive.CreateMaxForceAttr().Set(ROTOR_MAX_FORCE if driven else PIVOT_MAX_FORCE)
    # Isaac Lab's actuator config overwrites these gains at load time.
    drive.CreateStiffnessAttr().Set(0.0)
    drive.CreateDampingAttr().Set(0.0)
    drive.CreateTargetPositionAttr().Set(0.0)


def build_articulation(params: FurutaParameters, output_path: str | Path) -> Path:
    """Write the articulation to a USD file and return its path.

    An existing file at that path is replaced.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    stage = Usd.Stage.CreateNew(str(output_path))
    # SI units and Z up on the stage. The parameter file's numbers go in as written.
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)

    root = UsdGeom.Xform.Define(stage, "/Furuta")
    stage.SetDefaultPrim(root.GetPrim())
    # This API is what makes PhysX solve the tree below as one articulation.
    UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim())

    r = params.rotor_arm_length_m
    length = params.pendulum_length_m
    mass = params.pendulum_mass_kg

    # Base. A fixed body's mass and inertia never enter the solve. The values below are
    # placeholders.
    base = _rigid_body(stage, "/Furuta/base")
    _mass_properties(base, 1.0, (0.0, 0.0, 0.0), (1e-3, 1e-3, 1e-3))
    _cylinder(
        stage,
        "/Furuta/base/visual",
        BASE_RADIUS_M,
        ARM_HEIGHT_M,
        "Z",
        (0.0, 0.0, ARM_HEIGHT_M / 2.0),
    )
    # Only body1 is set. An empty body0 means the world. That pins the base.
    fixed = UsdPhysics.FixedJoint.Define(stage, "/Furuta/base_to_world")
    fixed.CreateBody1Rel().SetTargets(["/Furuta/base"])

    # Rotor arm, a cylinder along +X. Its inertia is a slender-rod estimate about its
    # centre, and its axial term is a placeholder.
    arm = _rigid_body(stage, "/Furuta/arm")
    arm_transverse = ARM_MASS_KG * r**2 / 12.0
    _mass_properties(
        arm,
        ARM_MASS_KG,
        (r / 2.0, 0.0, 0.0),
        (1e-5, arm_transverse, arm_transverse),
    )
    _cylinder(stage, "/Furuta/arm/visual", ARM_RADIUS_M, r, "X", (r / 2.0, 0.0, 0.0))

    # Pendulum, hanging along -Z from the arm tip. The transverse inertia is the
    # derived value, shaft term included. The axial term is a thin rod's.
    pendulum = _rigid_body(stage, "/Furuta/pendulum")
    inertia_com = params.pendulum_inertia_about_com_kg_m2
    _mass_properties(
        pendulum,
        mass,
        (0.0, 0.0, -length / 2.0),
        (inertia_com, inertia_com, mass * ROD_RADIUS_M**2 / 2.0),
    )
    _cylinder(
        stage,
        "/Furuta/pendulum/visual",
        ROD_RADIUS_M,
        length,
        "Z",
        (0.0, 0.0, -length / 2.0),
    )

    _revolute_joint(
        stage,
        "/Furuta/rotor_joint",
        "/Furuta/base",
        "/Furuta/arm",
        "Z",
        (0.0, 0.0, ARM_HEIGHT_M),
        driven=True,
    )
    _revolute_joint(
        stage,
        "/Furuta/pendulum_joint",
        "/Furuta/arm",
        "/Furuta/pendulum",
        "X",
        (r, 0.0, 0.0),
    )

    stage.GetRootLayer().Save()
    return output_path

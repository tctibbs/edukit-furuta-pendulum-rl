# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "pyyaml"]
# ///
"""Draw the modeled geometry as a dimensioned elevation.

Lengths and mass come from this experiment's `config.yaml`. Arm height and rod radius
are constants in `src/furuta/articulation.py`. That module imports `pxr` from Isaac Sim
and will not import here. Its constants are read with `ast`.
"""

import ast
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import yaml
from matplotlib.patches import Arc, FancyArrowPatch

plt.switch_backend("Agg")

HERE = Path(__file__).parent
ROOT = HERE.parents[3]


def _module_constant(path: Path, name: str) -> float:
    """Read a literal module-level constant without importing the module."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return float(ast.literal_eval(node.value))
    raise LookupError(f"{name} not found in {path}")


def _load_parameters(root: Path):
    """Read the constants this experiment ran on.

    `config/edukit.yaml` changes as measurements land. This experiment's `config.yaml`
    overrides it with the values this run used. The project is not installed as a
    package. `src` goes on `sys.path` first.
    """
    sys.path.insert(0, str(root / "src"))
    from furuta.parameters import FurutaParameters

    pinned = yaml.safe_load((HERE.parent / "config.yaml").read_text())
    defaults = yaml.safe_load((root / "config" / "edukit.yaml").read_text())
    merged = {
        **defaults["geometry"],
        **defaults["dynamics"],
        **defaults["actuator"],
        **defaults["control"],
        **defaults["sensing"],
        **pinned["physical"],
    }
    return FurutaParameters(
        **{
            k: v
            for k, v in merged.items()
            if k in FurutaParameters.__dataclass_fields__
        }
    )


params = _load_parameters(ROOT)
articulation = ROOT / "src" / "furuta" / "articulation.py"
arm_height = _module_constant(articulation, "ARM_HEIGHT_M")
rod_radius = _module_constant(articulation, "ROD_RADIUS_M")

L = params.pendulum_length_m
r = params.rotor_arm_length_m
m = params.pendulum_mass_kg

# ACCENT marks the pendulum and the two joint axes.
INK = "#222222"
DIM = "#8a8a8a"
BODY = "#1f77b4"
ACCENT = "#d62728"

# Side view. Plot x is world X along the arm, plot y is world Z. The pendulum swings in
# and out of the page. It is drawn hanging.

fig, ax = plt.subplots(figsize=(8.4, 6.4))

# Ground plane.
ax.plot([-0.16, 0.30], [0.0, 0.0], color=INK, linewidth=1.6, zorder=2)
for x in [-0.14 + 0.04 * i for i in range(11)]:
    ax.plot([x, x - 0.022], [0.0, -0.022], color=DIM, linewidth=0.9, zorder=1)

# Base column, arm, and the pendulum hanging from the arm tip.
ax.plot(
    [0.0, 0.0],
    [0.0, arm_height],
    color=BODY,
    linewidth=7,
    solid_capstyle="round",
    zorder=3,
)
ax.plot(
    [0.0, r],
    [arm_height, arm_height],
    color=BODY,
    linewidth=6,
    solid_capstyle="round",
    zorder=3,
)
ax.plot(
    [r, r],
    [arm_height, arm_height - L],
    color=ACCENT,
    linewidth=4,
    solid_capstyle="round",
    zorder=3,
)

# Joints.
ax.plot(
    [0.0],
    [arm_height],
    marker="o",
    markersize=10,
    color="white",
    markeredgecolor=INK,
    markeredgewidth=1.6,
    zorder=5,
)
ax.plot(
    [r],
    [arm_height],
    marker="o",
    markersize=9,
    color="white",
    markeredgecolor=INK,
    markeredgewidth=1.6,
    zorder=5,
)

# Centre of mass, L/2 down the rod.
ax.plot([r], [arm_height - L / 2.0], marker="o", markersize=8, color=INK, zorder=5)
ax.annotate(
    f"centre of mass, L/2 = {L / 2.0:.3f} m\ninertia is calculated about this point",
    xy=(r, arm_height - L / 2.0),
    xytext=(r + 0.082, arm_height - L / 2.0 - 0.072),
    fontsize=8.5,
    color=INK,
    va="center",
    ha="left",
    arrowprops=dict(arrowstyle="-", color=DIM, linewidth=0.9, shrinkA=2, shrinkB=4),
)

# Rotor axis, vertical through the base column.
ax.plot(
    [0.0, 0.0],
    [arm_height, arm_height + 0.125],
    color=DIM,
    linewidth=1.0,
    linestyle=(0, (5, 3)),
    zorder=2,
)
ax.add_patch(
    Arc(
        (0.0, arm_height + 0.098),
        0.090,
        0.032,
        theta1=200,
        theta2=340,
        color=ACCENT,
        linewidth=1.5,
        zorder=4,
    )
)
ax.add_patch(
    FancyArrowPatch(
        (0.0425, arm_height + 0.091),
        (0.047, arm_height + 0.100),
        arrowstyle="-|>",
        mutation_scale=11,
        color=ACCENT,
        linewidth=1.5,
        zorder=4,
    )
)
ax.text(
    0.0,
    arm_height + 0.140,
    "rotor, driven about vertical (Z)",
    fontsize=9,
    color=ACCENT,
    ha="center",
    va="bottom",
)

# Pendulum axis, horizontal along the arm.
ax.plot(
    [r - 0.040, r + 0.022],
    [arm_height, arm_height],
    color=DIM,
    linewidth=1.0,
    linestyle=(0, (5, 3)),
    zorder=2,
)
ax.add_patch(
    Arc(
        (r, arm_height),
        0.130,
        0.130,
        theta1=250,
        theta2=290,
        color=ACCENT,
        linewidth=1.5,
        zorder=4,
    )
)
ax.add_patch(
    FancyArrowPatch(
        (r + 0.020, arm_height - 0.062),
        (r + 0.029, arm_height - 0.057),
        arrowstyle="-|>",
        mutation_scale=11,
        color=ACCENT,
        linewidth=1.5,
        zorder=4,
    )
)
ax.text(
    r + 0.088,
    arm_height + 0.008,
    "pendulum, free\nabout arm axis (X)",
    fontsize=9,
    color=ACCENT,
    ha="left",
    va="bottom",
)


def dim_line(x0, y0, x1, y1, label, offset, ha="center", va="center"):
    """Draw a dimension line between two points, with `label` at its midpoint."""
    ax.annotate(
        "",
        xy=(x0, y0),
        xytext=(x1, y1),
        arrowprops=dict(arrowstyle="<|-|>", color=DIM, linewidth=1.0, mutation_scale=9),
    )
    ax.text(
        (x0 + x1) / 2 + offset[0],
        (y0 + y1) / 2 + offset[1],
        label,
        fontsize=9,
        color=INK,
        ha=ha,
        va=va,
    )


# The two lengths the dynamics use, and the arm height.
dim_line(0.0, arm_height + 0.038, r, arm_height + 0.038, f"r = {r:.3f} m", (0.0, 0.014))
dim_line(
    r + 0.052,
    arm_height,
    r + 0.052,
    arm_height - L,
    f"L = {L:.3f} m",
    (0.010, 0.0),
    ha="left",
)
dim_line(
    -0.080,
    0.0,
    -0.080,
    arm_height,
    f"arm height {arm_height:.2f} m",
    (-0.010, 0.0),
    ha="right",
)

ax.text(
    -0.080,
    arm_height / 2 - 0.028,
    "clearance only,\nnot in the dynamics",
    fontsize=8,
    color=DIM,
    ha="right",
    va="top",
)

# Notes, in a right-hand column.
ax.text(
    r + 0.082,
    arm_height - L + 0.020,
    f"m = {m:.3f} kg, assumed",
    fontsize=8.5,
    color=DIM,
    ha="left",
    va="center",
)
ax.text(
    r + 0.082,
    arm_height - L - 0.030,
    f"rod radius {rod_radius * 1000:.0f} mm, cosmetic",
    fontsize=8,
    color=DIM,
    ha="left",
    va="center",
)

# Equal aspect keeps the drawing to scale. Every offset above is a distance in metres.
ax.set_xlim(-0.23, 0.46)
ax.set_ylim(-0.055, arm_height + 0.215)
ax.set_aspect("equal")
ax.axis("off")

fig.tight_layout()
fig.savefig(HERE / "model_spec.png", dpi=200, bbox_inches="tight")
print("wrote", HERE / "model_spec.png")
print(f"  L={L} r={r} m={m} arm_height={arm_height} rod_radius={rod_radius}")

# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "pyyaml"]
# ///
"""Draw the modeled geometry as a kinematic diagram.

Ground, a driven revolute joint about Z, a link of length r, a free revolute joint about
X (the arm's own axis), and a link of length L. The view is axonometric from the front
right, so the arm comes toward the reader and the pendulum's swing plane opens up. A
side view cannot show that swing, because the pendulum swings in and out of the page.

Colour carries one meaning each, set in `_style.py`. Orange marks the two degrees of
freedom: the joint axes, the angles phi and theta, and the swing plane. Ink marks what
the equations of motion use. Faint grey marks what they do not: the stand and its
height.

Lengths come from this experiment's `config.yaml`, and the arm height from
`src/furuta/articulation.py`, both through `_parameters.py`.
"""

import sys
from pathlib import Path

import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Wedge
from matplotlib.transforms import Bbox

plt.switch_backend("Agg")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from _parameters import ARTICULATION, load_parameters, module_constant  # noqa: E402
from _style import (  # noqa: E402
    DOF,
    DOF_TEXT,
    EX,
    EZ,
    FAINT,
    INK,
    MUTED,
    RIGHT,
    apply_style,
    circle3,
    depth,
    project,
    revolute,
)

params = load_parameters()
arm_height = module_constant(ARTICULATION, "ARM_HEIGHT_M")

L = params.pendulum_length_m
r = params.rotor_arm_length_m

apply_style()
DOF_WASH = "#fdf1e7"

FS_MAIN = 13.5  # lengths and the centre of mass
FS_NOTE = 12.5  # axis letters, joint roles, arm height
FS_ANGLE = 23  # phi, theta
SWING_HALF = np.radians(25.0)  # half-angle of the drawn swing sector, illustrative

HALO = [pe.withStroke(linewidth=4, foreground="white")]


def line3(ax, a, b, **kw):
    """Draw a straight line between two world points."""
    pa, pb = project(a), project(b)
    ax.plot([pa[0], pb[0]], [pa[1], pb[1]], **kw)


def arrow2(ax, a, b, color, lw=1.2, ms=10, z=6, style="-|>"):
    """Draw an arrow between two page points."""
    ax.add_patch(
        FancyArrowPatch(
            tuple(a),
            tuple(b),
            arrowstyle=style,
            mutation_scale=ms,
            color=color,
            linewidth=lw,
            shrinkA=0,
            shrinkB=0,
            zorder=z,
        )
    )


def arrow3(ax, a, b, color, **kw):
    """Draw an arrow between two world points."""
    arrow2(ax, project(a), project(b), color, **kw)


def label(ax, xy, text, dx=0, dy=0, color=INK, fs=FS_MAIN, halo=False, **kw):
    """Place text at a page point, nudged by (dx, dy) in typographic points.

    Offsets are in points so the text keeps its size while the drawing stays to scale.
    """
    kw.setdefault("ha", "center")
    kw.setdefault("va", "center")
    ax.annotate(
        text,
        xy=tuple(xy),
        xytext=(dx, dy),
        textcoords="offset points",
        color=color,
        fontsize=fs,
        zorder=12,
        path_effects=HALO if halo else None,
        **kw,
    )


def rotation(ax, c, u, rho, t0, sweep, z_front=6, z_back=3):
    """Draw a curved arrow about a joint axis, passing behind it on the far side."""
    pts = circle3(c, u, rho, t0, t0 + sweep, 240)
    pp = project(pts)
    behind = depth(pts) < depth(c)
    cuts = np.flatnonzero(np.diff(behind.astype(int))) + 1
    for seg in np.split(np.arange(len(pts)), cuts):
        s = np.r_[seg, seg[-1] + 1] if seg[-1] + 1 < len(pts) else seg
        z = z_back if behind[seg[0]] else z_front
        ax.plot(pp[s, 0], pp[s, 1], color=DOF, lw=1.8, zorder=z)
    arrow2(ax, pp[-8], pp[-1], DOF, lw=1.8, ms=12, z=z_front)


def com_symbol(ax, xy, rad):
    """Draw the quartered disc that marks a centre of mass."""
    ax.add_patch(Circle(xy, rad, fc="white", ec=INK, lw=1.4, zorder=9))
    ax.add_patch(Wedge(xy, rad, 0, 90, fc=INK, ec="none", zorder=9.1))
    ax.add_patch(Wedge(xy, rad, 180, 270, fc=INK, ec="none", zorder=9.1))


def dimension(ax, a, b, ext_dir, off, color=MUTED, gap=0.0, z=3, ext=(True, True)):
    """Draw a dimension between world points a and b, offset along ext_dir.

    `gap` leaves space between the object and each extension line. `ext` turns off an
    extension line where an axis already draws one. Returns the page midpoint.
    """
    a, b, e = (np.asarray(v, dtype=float) for v in (a, b, ext_dir))
    a2, b2 = a + off * e, b + off * e
    for (p, q), on, g in zip(
        ((a, a2), (b, b2)), ext, np.broadcast_to(gap, 2), strict=True
    ):
        if on:
            line3(ax, p + g * e, q + 0.010 * e, color=color, lw=0.8, zorder=z - 1)
    arrow3(ax, a2, b2, color, lw=0.9, ms=9, z=z, style="<|-|>")
    return project((a2 + b2) / 2)


ORIGIN = np.zeros(3)
J1 = arm_height * EZ  # rotor joint, on the Z axis
J2 = J1 + r * EX  # pendulum joint, at the arm tip
TIP = J2 - L * EZ  # the pendulum is drawn hanging, theta = 0
COM = J2 - 0.5 * L * EZ
PHI_C = J1 + 0.070 * EZ  # centre of the phi arrow, up the Z axis
TH_C = J2 + 0.075 * EX  # centre of the theta arrow, out along the X axis


def swing_point(t, radius):
    """Return a point in the swing plane, Y-Z at the arm tip, t from hanging."""
    return J2 + radius * np.array([0.0, np.sin(t), -np.cos(t)])


# The page is in metres, so the drawing is to scale. The limits only need to hold the
# drawing. The saved image is cropped to what is drawn.
SCALE = 16.0  # inches of page per metre of model
extent = project(
    [ORIGIN, J1 + 0.13 * EZ, J2 + 0.15 * EX, TIP, swing_point(-SWING_HALF, L)]
)
xlim = (extent[:, 0].min() - 0.15, extent[:, 0].max() + 0.20)
ylim = (extent[:, 1].min() - 0.05, extent[:, 1].max() + 0.05)
fig = plt.figure(figsize=(SCALE * np.ptp(xlim), SCALE * np.ptp(ylim)))
ax = fig.add_axes((0, 0, 1, 1))

# Ground and stand. Fixed and not in the dynamics, so faint and thin.
g = project(ORIGIN)
ax.plot([g[0] - 0.026, g[0] + 0.026], [g[1], g[1]], color=FAINT, lw=1.3, zorder=2)
for x in np.linspace(g[0] - 0.018, g[0] + 0.026, 5):
    ax.plot([x, x - 0.011], [g[1], g[1] - 0.011], color=FAINT, lw=0.8, zorder=1)
line3(ax, ORIGIN, J1 - 0.02 * EZ, color=FAINT, lw=2.0, zorder=2)

# The swing plane, a sector symmetric about hanging so its chord runs along Y. The rim
# is the path of the tip.
ts = np.linspace(-SWING_HALF, SWING_HALF, 160)
rim = project(np.array([swing_point(t, L) for t in ts]))
apex = project(J2)
ax.add_patch(
    Polygon(np.vstack([apex, rim]), closed=True, fc=DOF_WASH, ec="none", zorder=0)
)
ax.plot(rim[:, 0], rim[:, 1], color=DOF, lw=0.9, ls=(0, (3, 2.5)), alpha=0.75, zorder=1)
for edge in (rim[0], rim[-1]):
    ax.plot(
        [apex[0], edge[0]], [apex[1], edge[1]], color=DOF, lw=0.9, alpha=0.45, zorder=1
    )

# Joint axes as centrelines, with an arrow at the positive end.
CENTRE = (0, (9, 2.5, 2, 2.5))
for joint, axis, length, name, nudge in (
    (J1, EZ, 0.100, "Z", (10, -8)),
    (J2, EX, 0.112, "X", (10, -5)),
):
    end = joint + length * axis
    line3(ax, joint, end, color=DOF, lw=1.3, ls=CENTRE, zorder=4, path_effects=HALO)
    arrow3(ax, end - 0.001 * axis, end + 0.018 * axis, DOF, lw=1.3, ms=11, z=4)
    label(ax, project(end + 0.018 * axis), name, *nudge, color=DOF_TEXT, fs=FS_NOTE)

# Links, then joints. The driven joint is filled and the free joint hollow.
line3(ax, J1, J2, color=INK, lw=3.6, zorder=5)
line3(ax, J2, TIP, color=INK, lw=3.6, zorder=5)
revolute(ax, J1, EZ, 0.0145, 0.014, DOF, z=7)
revolute(ax, J2, EX, 0.0135, 0.015, "white", z=7)

# The two joint angles.
rotation(ax, PHI_C, EZ, 0.034, np.radians(110), np.radians(300))
rotation(ax, TH_C, EX, 0.027, np.radians(60), np.radians(300))
label(
    ax,
    project(PHI_C),
    "φ",
    -47,
    9,
    color=DOF_TEXT,
    fs=FS_ANGLE,
    ha="right",
    style="italic",
)
label(ax, project(PHI_C), "driven", -45, -13, color=MUTED, fs=FS_NOTE, ha="right")

# r runs from the rotor axis to the vertical through the pendulum joint. The Z axis
# serves as its left extension line.
r_mid = dimension(ax, J1, J2, EZ, 0.038, gap=0.020, ext=(False, True))
label(ax, r_mid, rf"$r$ = {r:.3f} m", 8, 22, halo=True)

# L sits on the stand side, with extension lines level on the page.
L_mid = dimension(ax, J2, TIP, -RIGHT, 0.034, gap=(0.024, 0.006))
label(ax, L_mid, rf"$L$ = {L:.3f} m", -10, 6, ha="right", halo=True)

# Arm height is clearance only, so it is faint.
h_mid = dimension(ax, ORIGIN, J1, -RIGHT, 0.055, color=FAINT, gap=0.025)
label(ax, h_mid, f"{arm_height:.2f} m", -6, ha="right", color=FAINT, fs=FS_NOTE)

theta_at = (project(TH_C)[0] + 0.038, project(TH_C)[1])
label(ax, theta_at, "θ", 6, 33, color=DOF_TEXT, fs=FS_ANGLE, ha="left", style="italic")
label(ax, theta_at, "free", 6, 10, color=MUTED, fs=FS_NOTE, ha="left")

# The centre of mass label sits just outside the swing sector's right edge, so its
# leader stays short.
pc = project(COM)
com_symbol(ax, tuple(pc), 0.0105)
edge = max(rim[0], rim[-1], key=lambda p: p[0])
edge_x = apex[0] + (pc[1] - apex[1]) / (edge[1] - apex[1]) * (edge[0] - apex[0])
lead_end = (edge_x + 0.014, pc[1])
ax.plot([pc[0] + 0.012, lead_end[0]], [pc[1], pc[1]], color=MUTED, lw=0.8, zorder=8)
label(ax, lead_end, r"centre of mass, $L/2$", 6, 0, ha="left")

ax.set_aspect("equal")
ax.axis("off")
ax.set_xlim(*xlim)
ax.set_ylim(*ylim)

# Crop to the drawn content. The axes box is larger than the drawing.
renderer = fig.canvas.get_renderer()
drawn = [*ax.patches, *ax.lines, *ax.texts]
crop = (
    Bbox.union([a.get_window_extent(renderer) for a in drawn])
    .transformed(fig.dpi_scale_trans.inverted())
    .padded(0.12)
)
# 150 dpi, the resolution the later experiments' `_style.py` save at.
fig.savefig(HERE / "model_spec.png", dpi=150, bbox_inches=crop, facecolor="white")
print("wrote", HERE / "model_spec.png")
print(f"  L={L} r={r} arm_height={arm_height}")

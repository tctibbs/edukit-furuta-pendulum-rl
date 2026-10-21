"""Shared look for experiment 02's figures: one palette and one camera.

The model geometry and the actuator pipeline sit one above the other in the write-up,
and the pipeline draws the model's kinematic chain in miniature. Both use the same
colours and the same view, so the reader sees one mechanism twice.

Orange marks the two degrees of freedom and the simulated plant. It is the simulation's
colour in the later experiments too. Ink marks what the equations use, and faint grey
marks what they do not.

The module has no top-level plotting import, so it is safe when the figure runner globs
and runs it directly. It borrows matplotlib from whichever script imports it.
"""

from __future__ import annotations

import numpy as np

INK = "#1a2733"
MUTED = "#5a6b7a"
FAINT = "#9aa7b3"
RULE = "#c9d2db"
DOF = "#e8833a"
DOF_TEXT = "#c4651f"  # the orange, darkened to read as text on white


def apply_style(capstyle: str = "round") -> None:
    """Set the shared fonts. Call once at the top of a figure script."""
    import matplotlib as mpl

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "mathtext.fontset": "custom",
            "mathtext.rm": "Helvetica Neue",
            "mathtext.it": "Helvetica Neue:italic",
            "mathtext.cal": "Helvetica Neue",
            "lines.solid_capstyle": capstyle,
        }
    )


# Axonometric camera, azimuth from +X toward +Y and elevation above the floor. From the
# front right the swing plane is drawn at 0.51 of its true area and the arm's vertical
# plane at 0.70. Turning further toward +X opens the swing plane but pushes the L label
# of the model figure into the stand.
AZ = np.radians(-54.0)
EL = np.radians(30.0)
VIEW = np.array([np.cos(EL) * np.cos(AZ), np.cos(EL) * np.sin(AZ), np.sin(EL)])
RIGHT = np.array([-np.sin(AZ), np.cos(AZ), 0.0])
UP = np.cross(VIEW, RIGHT)
EX, EY, EZ = np.eye(3)


def project(p, origin=(0.0, 0.0), scale=1.0):
    """Project world points of shape (..., 3) onto the page.

    `scale` is page units per metre, and `origin` is where the world origin lands.
    """
    p = np.asarray(p, dtype=float)
    return np.asarray(origin) + scale * np.stack([p @ RIGHT, p @ UP], axis=-1)


def depth(p):
    """Distance toward the camera. Larger is nearer."""
    return np.asarray(p, dtype=float) @ VIEW


def circle3(c, u, rho, t0=0.0, t1=2 * np.pi, n=120):
    """Return points on a circle about axis u. t increases by the right-hand rule."""
    u = u / np.linalg.norm(u)
    v = np.cross(u, EZ) if abs(u @ EZ) < 0.9 else EX.copy()
    v /= np.linalg.norm(v)
    w = np.cross(u, v)
    t = np.linspace(t0, t1, n)
    return c + rho * (np.cos(t)[:, None] * v + np.sin(t)[:, None] * w)


def convex_hull(pts):
    """Return the convex hull of page points, by the monotone chain method."""
    pts = sorted(map(tuple, pts))

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def revolute(ax, c, u, rho, half, face, z, lw=1.6, to_page=project):
    """Draw a revolute joint as a short cylinder whose axis is the joint axis.

    The driven joint is filled orange and the free joint white. `to_page` maps world
    points onto the page.
    """
    from matplotlib.patches import Polygon

    u = u / np.linalg.norm(u)
    ring_a = circle3(c - half * u, u, rho)
    ring_b = circle3(c + half * u, u, rho)
    hull = convex_hull(to_page(np.vstack([ring_a, ring_b])))
    ax.add_patch(Polygon(hull, closed=True, fc=face, ec=DOF, lw=lw, zorder=z))
    front = ring_b if depth(c + half * u) > depth(c - half * u) else ring_a
    ax.add_patch(
        Polygon(to_page(front), closed=True, fc=face, ec=DOF, lw=lw, zorder=z + 0.1)
    )

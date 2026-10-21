# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy", "pyyaml"]
# ///
"""Draw the actuator and observation pipeline as the closed loop it is.

One control step runs the outer loop once. The action runs along the bottom through the
stepper emulation: a gain to the acceleration limit, a rate-limited integrator to step
rate, a second integrator to position, and a quantizer to whole microsteps. That chain
re-creates the firmware's `apply_acceleration()` (Edukit Manual, App. E, p. 160). PhysX
then runs the inner loop once per substep on the same held target: the joint drive
pushes torque into the rotor joint and reads the joint back.

The pendulum angle leaves the pendulum joint, is sampled once per control step and
rounded to encoder counts. The rotor has no encoder, so its reading is a tap on the
command itself. Both readings are differenced into rates, the pendulum angle is shifted
to the angle from upright, and the five observations return to the policy.

The plant is the kinematic chain of `model_spec.py` in miniature, seen from the same
camera, so the wires land on the joints they act on and read from. Rates, limits and
resolutions come from this experiment's `config.yaml` through `_parameters.py`. Drive
gains are left to the text.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon
from matplotlib.path import Path as MPath

plt.switch_backend("Agg")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from _parameters import load_parameters  # noqa: E402
from _style import (  # noqa: E402
    DOF,
    DOF_TEXT,
    EX,
    EZ,
    INK,
    MUTED,
    RULE,
    apply_style,
    project,
    revolute,
)

params = load_parameters()

apply_style(capstyle="butt")
REGION_WASH = "#fef8f3"  # lighter than the swing plane so the plane still reads
SWING_WASH = "#fbe5d2"

FS_BLOCK = 13.0  # block names
FS_SYM = 16.0  # signal symbols on wires and in the vector
FS_NOTE = 12.0  # values and notes
FS_GROUP = 12.5  # group names with their rates
LW = 1.6  # every signal wire
LW_BLOCK = 1.4

# The page is in inches.
W, H = 12.4, 4.02
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes((0, 0, 1, 1))
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.set_aspect("equal")
ax.axis("off")


def text(x, y, s, fs=FS_NOTE, color=INK, ha="center", va="center", **kw):
    """Place text at a page point."""
    ax.text(x, y, s, fontsize=fs, color=color, ha=ha, va=va, zorder=10, **kw)


def wire(pts, color=INK, head=True, z=3):
    """Draw an orthogonal wire through page points, with an arrowhead at the end."""
    path = MPath(pts, [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 1))
    ax.add_patch(
        FancyArrowPatch(
            path=path,
            arrowstyle="-|>" if head else "-",
            mutation_scale=13,
            color=color,
            lw=LW,
            joinstyle="miter",
            capstyle="butt",
            shrinkA=0,
            shrinkB=0,
            zorder=z,
        )
    )


def dot(x, y, color=INK, r=0.043):
    """Mark a branch point."""
    ax.add_patch(Circle((x, y), r, fc=color, ec="none", zorder=6))


def block(x0, y0, x1, y1, ec=INK, fc="white", lw=LW_BLOCK, z=4, r=0.05):
    """Draw a rounded block from corner to corner."""
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0),
            x1 - x0,
            y1 - y0,
            boxstyle=f"round,pad=0,rounding_size={r}",
            fc=fc,
            ec=ec,
            lw=lw,
            zorder=z,
        )
    )


def bracket(x0, x1, y, label):
    """Draw a thin bracket over a group of blocks, with the group's name and rate."""
    ax.plot(
        [x0, x0, x1, x1],
        [y - 0.08, y, y, y - 0.08],
        color=RULE,
        lw=1.2,
        zorder=2,
        solid_joinstyle="miter",
    )
    text((x0 + x1) / 2, y + 0.17, label, fs=FS_GROUP, color=MUTED)


S = 0.55  # side of a square operator block
HS = S / 2


def axes_glyph(cx, cy, h=0.19):
    """Draw faint input-output axes inside a nonlinearity block."""
    ax.plot([cx - h, cx + h], [cy, cy], color=RULE, lw=0.8, zorder=5)
    ax.plot([cx, cx], [cy - h, cy + h], color=RULE, lw=0.8, zorder=5)


def quantizer(cx, cy):
    """Draw a quantizer block, a staircase through the origin."""
    block(cx - HS, cy - HS, cx + HS, cy + HS)
    axes_glyph(cx, cy)
    step = 0.085
    xs = [cx - 0.17]
    ys = [cy - 1.5 * step]
    for i in range(4):
        edge = cx - 0.17 + (i + 1) * step
        rise = step if i < 3 else 0.0
        xs += [edge, edge]
        ys += [ys[-1], ys[-1] + rise]
    ax.plot(xs, ys, color=INK, lw=1.6, zorder=6, solid_joinstyle="miter")


def integrator(cx, cy, limited=False):
    """Draw an integrator block. A limited one clamps its own state, drawn as stops."""
    block(cx - HS, cy - HS, cx + HS, cy + HS)
    text(cx, cy - 0.01, r"$\int$", fs=19 if limited else 22)
    if limited:
        for sgn in (1, -1):
            ax.plot(
                [cx - 0.13, cx + 0.13],
                [cy + sgn * 0.19] * 2,
                color=INK,
                lw=1.6,
                zorder=6,
            )


def difference(cx, cy, w=0.62, h=0.3):
    """Draw a rate by finite difference over one control step."""
    block(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, r=0.04)
    text(cx, cy, r"$\Delta/\Delta t$", fs=FS_NOTE)


def summer(cx, cy, r=0.12):
    """Draw a summing junction."""
    ax.add_patch(Circle((cx, cy), r, fc="white", ec=INK, lw=LW_BLOCK, zorder=5))


def gain(x0, cy, w=0.55, h=0.62):
    """Draw a gain triangle pointing along the signal."""
    ax.add_patch(
        Polygon(
            [(x0, cy - h / 2), (x0, cy + h / 2), (x0 + w, cy)],
            closed=True,
            fc="white",
            ec=INK,
            lw=LW_BLOCK,
            zorder=4,
            joinstyle="miter",
        )
    )


Y_B = 0.86  # the forward path
ROWS = [3.24, 2.91, 2.58, 2.25, 1.92]  # observation entries, top to bottom
Y_TH, Y_PH = ROWS[0], ROWS[3]  # the pendulum and rotor return lanes
X_OBS = (0.55, 1.45)
X_MID = (X_OBS[0] + X_OBS[1]) / 2
X_DIFF = 2.02  # the two difference blocks
DW = 0.62
Y_LABEL = Y_B - HS - 0.2  # values under the blocks

# The policy. Named in words, because pi is the half turn in theta_k - pi below.
PI = (0.55, Y_B - 0.4, 1.45, Y_B + 0.4)
block(*PI, lw=1.6)
text(X_MID, Y_B, "policy", fs=FS_BLOCK)

# The forward path, the stepper emulation.
X_GAIN = 2.62
X_I1, X_I2, X_Q = 4.12, 5.42, 6.7
X_TAP = 7.52

wire([(PI[2], Y_B), (X_GAIN, Y_B)])
text((PI[2] + X_GAIN) / 2, Y_B + 0.24, r"$a \in [-1,\,1]$", fs=FS_NOTE + 1)

gain(X_GAIN, Y_B)
text(
    X_GAIN + 0.24,
    Y_LABEL,
    rf"{params.max_acceleration_rad_s2:.0f} rad/s$^2$",
    color=MUTED,
)
wire([(X_GAIN + 0.55, Y_B), (X_I1 - HS, Y_B)])
text((X_GAIN + 0.55 + X_I1 - HS) / 2, Y_B + 0.22, r"$\alpha$", fs=FS_SYM)

integrator(X_I1, Y_B, limited=True)
text(X_I1, Y_LABEL, rf"$\pm${params.max_rotor_rate_rad_s:.1f} rad/s", color=MUTED)
wire([(X_I1 + HS, Y_B), (X_I2 - HS, Y_B)])
text((X_I1 + X_I2) / 2, Y_B + 0.22, r"$\omega$", fs=FS_SYM)

integrator(X_I2, Y_B)
wire([(X_I2 + HS, Y_B), (X_Q - HS, Y_B)])
quantizer(X_Q, Y_B)
text(X_Q, Y_LABEL, f"1/{params.microsteps_per_rev} rev", color=MUTED)
text((X_Q + HS + X_TAP) / 2 - 0.02, Y_B + 0.24, r"$\varphi_k$", fs=FS_SYM)

bracket(X_GAIN, X_Q + HS, Y_B + 0.5, f"stepper emulation, {params.loop_rate_hz:.0f} Hz")

# PhysX, the inner loop around the drive and the articulation.
RG = (7.84, 0.12, 12.25, 2.5)
block(*RG, ec=DOF, fc=REGION_WASH, lw=1.0, z=1, r=0.08)
text(
    RG[0] + 0.2,
    RG[3] - 0.22,
    f"PhysX, {params.physics_rate_hz:.0f} Hz",
    fs=FS_GROUP,
    color=DOF_TEXT,
    ha="left",
)

DRV = (8.4, Y_B - 0.36, 9.5, Y_B + 0.36)
block(*DRV)
text((DRV[0] + DRV[2]) / 2, Y_B + 0.11, "joint drive", fs=FS_BLOCK)
text((DRV[0] + DRV[2]) / 2, Y_B - 0.17, "stiff PD", color=MUTED)

wire([(X_Q + HS, Y_B), (DRV[0], Y_B)])
dot(X_TAP, Y_B)
text((RG[0] + DRV[0]) / 2 + 0.02, Y_B - 0.2, "held", color=MUTED)

# The articulation, the model_spec chain in miniature, drawn hanging.
SC = 5.2  # inches of page per metre of model
J1_PAGE = np.array([10.45, 1.86])  # page position of the rotor joint


def to_page(p):
    """Project world points, in metres from the rotor joint, onto the page."""
    return project(p, origin=J1_PAGE, scale=SC)


J1 = np.zeros(3)
J2 = params.rotor_arm_length_m * EX
L = params.pendulum_length_m
TIP = J2 - L * EZ
SWING_HALF = np.radians(25.0)
ts = np.linspace(-SWING_HALF, SWING_HALF, 60)
rim = to_page(np.array([J2 + L * np.array([0, np.sin(t), -np.cos(t)]) for t in ts]))
ax.add_patch(Polygon(np.vstack([to_page(J2), rim]), fc=SWING_WASH, ec="none", zorder=2))
ax.plot(
    rim[:, 0], rim[:, 1], color=DOF, lw=0.9, ls=(0, (2.5, 2)), alpha=0.8, zorder=2.1
)
for edge in (rim[0], rim[-1]):
    ax.plot(
        *zip(to_page(J2), edge, strict=True), color=DOF, lw=0.8, alpha=0.45, zorder=2.1
    )
for a, b in ((J1, J2), (J2, TIP)):
    ax.plot(*zip(to_page(a), to_page(b), strict=True), color=INK, lw=3.0, zorder=4.6)
revolute(ax, J1, EZ, 0.017, 0.017, DOF, z=7, lw=1.4, to_page=to_page)
revolute(ax, J2, EX, 0.015, 0.018, "white", z=7, lw=1.4, to_page=to_page)
p1, p2, p_tip = to_page(J1), to_page(J2), to_page(TIP)
text(p_tip[0] + 0.16, p_tip[1] - 0.04, "articulation", color=MUTED, ha="left")

# Torque into the rotor joint and the joint state back to the drive, once per substep.
J1_BOTTOM = p1[1] - 0.11
wire([(DRV[2], Y_B), (p1[0], Y_B), (p1[0], J1_BOTTOM)])
text((DRV[2] + p1[0]) / 2, Y_B - 0.2, r"$\tau$", fs=FS_SYM)
X_FB = (DRV[0] + DRV[2]) / 2
wire([(p1[0] - 0.12, p1[1]), (X_FB, p1[1]), (X_FB, DRV[3])], color=DOF)
text(
    (X_FB + p1[0]) / 2 + 0.12,
    p1[1] + 0.2,
    r"$\varphi,\ \dot{\varphi}$",
    fs=FS_NOTE + 2,
    color=DOF_TEXT,
)
X_LOOP = (X_FB + p1[0]) / 2
Y_LOOP = (DRV[3] + p1[1]) / 2
text(X_LOOP, Y_LOOP + 0.1, rf"$\times {params.decimation}$", fs=20, color=DOF_TEXT)
text(X_LOOP, Y_LOOP - 0.15, "per action", color=MUTED)

# The return path, the sensing emulation. The pendulum angle leaves its joint, is
# sampled once per control step, then rounded to encoder counts.
X_UP = 11.95
wire([(p2[0] + 0.12, p2[1]), (X_UP, p2[1]), (X_UP, Y_TH), (11.35, Y_TH)], head=False)
text((p2[0] + X_UP) / 2 + 0.1, p2[1] + 0.24, r"$\theta$", fs=FS_SYM + 2, color=DOF_TEXT)

X_SW_R, X_SW_L = 11.35, 10.98  # the sampler's two terminals
ax.plot(
    [X_SW_R, X_SW_L + 0.02],
    [Y_TH, Y_TH + 0.2],
    color=INK,
    lw=LW,
    zorder=3,
    solid_capstyle="round",
)
dot(X_SW_R, Y_TH, r=0.035)
dot(X_SW_L, Y_TH, r=0.035)

X_ENC = 9.95
wire([(X_SW_L, Y_TH), (X_ENC + HS, Y_TH)])
quantizer(X_ENC, Y_TH)
text(
    X_ENC,
    Y_TH - HS - 0.19,
    f"{params.encoder_counts_per_rev} counts/rev",
    color=MUTED,
)
bracket(
    X_ENC - HS,
    X_SW_R + 0.04,
    Y_TH + 0.38,
    f"sensing emulation, {params.loop_rate_hz:.0f} Hz",
)

# The pendulum lane: the rate, then the angle from upright into cos and sin.
X_THD = 4.0  # the rate branch
X_SUM = 3.28  # psi_k = theta_k - pi
X_SIN = 2.62  # the sin branch
wire([(X_ENC - HS, Y_TH), (X_SUM + 0.12, Y_TH)])
text(X_ENC - HS - 0.42, Y_TH + 0.22, r"$\theta_k$", fs=FS_SYM)
dot(X_THD, Y_TH)
wire([(X_THD, Y_TH), (X_THD, ROWS[2]), (X_DIFF + DW / 2, ROWS[2])])
difference(X_DIFF, ROWS[2])
wire([(X_DIFF - DW / 2, ROWS[2]), (X_OBS[1], ROWS[2])])

summer(X_SUM, Y_TH)
wire([(X_SUM, Y_TH + 0.42), (X_SUM, Y_TH + 0.12)])
text(X_SUM, Y_TH + 0.54, r"$\pi$", fs=FS_SYM, color=MUTED)
text(X_SUM + 0.09, Y_TH + 0.25, r"$-$", fs=FS_SYM, ha="left")
wire([(X_SUM - 0.12, Y_TH), (X_OBS[1], Y_TH)])
text((X_SUM + X_SIN) / 2 - 0.02, Y_TH + 0.22, r"$\psi_k$", fs=FS_SYM)
dot(X_SIN, Y_TH)
wire([(X_SIN, Y_TH), (X_SIN, ROWS[1]), (X_OBS[1], ROWS[1])])

# The rotor lane. There is no rotor encoder, so the reading is the command.
wire([(X_TAP, Y_B), (X_TAP, Y_PH), (X_OBS[1], Y_PH)])
text(X_TAP - 0.14, Y_PH - 0.21, "no rotor encoder", color=MUTED, ha="right")
dot(X_SIN, Y_PH)
wire([(X_SIN, Y_PH), (X_SIN, ROWS[4]), (X_DIFF + DW / 2, ROWS[4])])
difference(X_DIFF, ROWS[4])
wire([(X_DIFF - DW / 2, ROWS[4]), (X_OBS[1], ROWS[4])])

# The observation vector.
OB_TOP, OB_BOT = ROWS[0] + 0.23, ROWS[-1] - 0.23
for xb, sgn in ((X_OBS[0], 1), (X_OBS[1], -1)):
    ax.plot(
        [xb + sgn * 0.09, xb, xb, xb + sgn * 0.09],
        [OB_TOP, OB_TOP, OB_BOT, OB_BOT],
        color=INK,
        lw=1.6,
        zorder=6,
        solid_joinstyle="miter",
    )
entries = [
    r"$\cos\,\psi_k$",
    r"$\sin\,\psi_k$",
    r"$\dot{\theta}_k$",
    r"$\varphi_k$",
    r"$\dot{\varphi}_k$",
]
for y, e in zip(ROWS, entries, strict=True):
    text(X_MID, y, e, fs=FS_SYM - 1)

# Five values on one wire, back to the policy.
wire([(X_MID, OB_BOT), (X_MID, PI[3])])
Y_BUS = (OB_BOT + PI[3]) / 2
ax.plot(
    [X_MID - 0.08, X_MID + 0.08],
    [Y_BUS - 0.08, Y_BUS + 0.08],
    color=INK,
    lw=1.2,
    zorder=6,
)
text(X_MID - 0.15, Y_BUS + 0.02, f"{len(entries)}", ha="right")

out_path = HERE / "actuator_pipeline.png"
fig.savefig(out_path, dpi=180, facecolor="white")
print("wrote", out_path)

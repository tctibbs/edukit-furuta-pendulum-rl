# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "pyyaml"]
# ///
"""Draw the two candidate upright reward terms across the task's tilt envelope.

The inherited `cos(theta)` shaping and the quadratic that replaced it, plotted over the
20 degrees the balance task lives in. Both are scaled the same and both peak at 1.0 at
upright, so the only difference visible here is how much of that range they actually use
before the pendulum is terminated.

    just figures 05
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

sys.path.insert(0, str(HERE.parents[3] / "src"))
from furuta.parameters import FurutaParameters  # noqa: E402

MAX_TILT_RAD = 0.35  # termination, 20 degrees
# The stiction hold angle, half the measured Coulomb loss. Read from the config so the
# line this draws is the deadband the reward actually uses, not a number copied once.
DEADBAND_RAD = FurutaParameters.from_yaml().stiction_hold_angle_rad
# atan(omega_r^2 * a_max / omega_g^2), the tilt the rotor can still arrest
ARREST_DEG = 7.83


def main() -> int:
    """Draw the comparison and write it beside this script."""
    degrees = [i * 0.05 for i in range(0, 401)]
    effective = [max(math.radians(d) - DEADBAND_RAD, 0.0) for d in degrees]
    cosine = [math.cos(e) for e in effective]
    quadratic = [1.0 - (e / MAX_TILT_RAD) ** 2 for e in effective]

    _style.apply_style()

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.plot(
        degrees,
        cosine,
        color="#d62728",
        linewidth=1.8,
        label=f"cos, uses {max(cosine) - min(cosine):.3f} of its range",
    )
    ax.plot(
        degrees,
        quadratic,
        color="#1f77b4",
        linewidth=1.8,
        label=f"quadratic, uses {max(quadratic) - min(quadratic):.3f}",
    )
    ax.axhline(
        1.0,
        color="#444444",
        linestyle=":",
        linewidth=1.0,
        label="alive term, 1.0 every step",
    )
    ax.axvline(
        ARREST_DEG,
        color="#888888",
        linestyle="--",
        linewidth=1.0,
        label=f"rotor arrest limit, {ARREST_DEG} deg",
    )

    ax.set_xlabel("tilt from vertical (degrees)")
    ax.set_ylabel("upright reward term")
    ax.set_xlim(0, 20)
    ax.set_ylim(-0.02, 1.06)
    ax.legend(loc="lower left", frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    _style.titled(
        ax,
        "Upright Reward vs Tilt",
        "The cosine varies by only 0.058 across the 20-degree operating envelope.",
    )
    fig.tight_layout()
    out = HERE / "reward_shaping.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    print(f"  cos range over 0-20 deg:       {max(cosine) - min(cosine):.4f}")
    print(f"  quadratic range over 0-20 deg: {max(quadratic) - min(quadratic):.4f}")
    return 0


if __name__ == "__main__":
    main()

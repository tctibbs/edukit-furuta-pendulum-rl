# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""Fit and plot the baseplate-tilt map from a full-circle sweep capture.

Bins the pendulum's resting angle by arm position and fits a sine wave whose amplitude
is the tilt. The unit has no rotor sensor. The fitted map is the rotor's only absolute
reference.

    just figures 03
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

COUNTS_PER_DEGREE = 6.666667


def read_dwells(path: Path):
    """Shift in resting angle from the rotor-zero datum, in degrees, at each dwell."""
    by_rotor: dict[int, list[int]] = defaultdict(list)
    for line in path.read_text(errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        try:
            count, rotor = int(fields[1]), int(fields[2])
        except ValueError:
            continue
        by_rotor[rotor].append(count)
    rest = {
        r: median(cs[500:]) if len(cs) > 600 else median(cs)
        for r, cs in by_rotor.items()
    }
    datum = rest.get(0, median(rest.values()))
    return {r: (c - datum) / COUNTS_PER_DEGREE for r, c in sorted(rest.items())}


def fit_sinusoid(rotor_deg, rest_deg):
    """Fit the tilt sinusoid A*sin(phi - bearing) + offset to the dwell angles."""
    phi = np.radians(np.array(rotor_deg))
    basis = np.column_stack([np.sin(phi), np.cos(phi), np.ones_like(phi)])
    (a, b, offset), *_ = np.linalg.lstsq(basis, np.array(rest_deg), rcond=None)
    amplitude = float(np.hypot(a, b))
    bearing = float(np.degrees(np.arctan2(-b, a)))
    return amplitude, bearing, float(offset)


def main() -> int:
    """Fit and plot the tilt map."""
    source = EXPERIMENT / "sweep.tsv"
    if not source.exists():
        raise SystemExit(f"no sweep capture at {source}; run just hw-probe-sweep first")

    dwells = read_dwells(source)
    rotor = list(dwells.keys())
    rest = list(dwells.values())
    amplitude, bearing, offset = fit_sinusoid(rotor, rest)

    fine = np.linspace(min(rotor), max(rotor), 400)
    curve = amplitude * np.sin(np.radians(fine) - np.radians(bearing)) + offset

    _style.apply_style()
    fig, ax = plt.subplots(figsize=(7.6, 4.3))
    ax.axhline(0.0, color=_style.GRID, lw=1)
    ax.plot(
        fine, curve, color=_style.MODEL, lw=2.4, label=f"fitted tilt: {amplitude:.2f}°"
    )
    # The resting angle at each stop is the pooled median over the settled samples at
    # that rotor angle, dropping the first 500 of each dwell. The rms residual printed
    # below is the spread against the fit.
    resid = np.array(rest) - (
        amplitude * np.sin(np.radians(rotor) - np.radians(bearing)) + offset
    )
    rms = float(np.sqrt(np.mean(resid**2)))
    ax.scatter(
        rotor,
        rest,
        s=64,
        color=_style.MEASURED,
        zorder=3,
        edgecolor="white",
        linewidth=1.2,
        label="where the pendulum settled",
    )
    ax.set_xlabel("arm angle around the circle (degrees)")
    ax.set_ylabel('shift in "straight down" (degrees)')
    _style.titled(
        ax,
        "Where the pendulum hangs, around a full turn of the arm",
        "The shift traces a sine wave. Its amplitude is the baseplate tilt.",
    )
    ax.set_xticks(range(0, 361, 60))
    ax.legend(loc="upper right", fontsize=9)

    _style.callout(
        ax,
        (max(rotor, key=lambda r: abs(dwells[r])), min(rest)),
        "A level simulator carries none of this shift.",
        (35, min(rest) * 0.55),
        color=_style.INK,
    )

    fig.tight_layout()
    out = HERE / "sweep_map.png"
    fig.savefig(out)
    print(
        f"wrote {out}  (amplitude {amplitude:.3f} deg, bearing {bearing:.1f} deg, "
        f"rms residual {rms:.3f} deg)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

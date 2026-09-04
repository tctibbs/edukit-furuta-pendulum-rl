# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""Effective Q against swing size, from a mode d ring-down capture.

Splits the capture into one decay per target amplitude and plots the Q of each. The
comparison line comes from the free-swing fit, whose constants are `MODEL_VISCOUS_Q`
and `MODEL_COULOMB_DEG` below.

    just figures 03
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EXPERIMENT.parents[2] / "src"))

import _style  # noqa: E402

from furuta.pump import (  # noqa: E402
    model_quality,
    qeff_vs_amplitude,
    read_state_trace,
    split_segments,
)

# Viscous Q and the Coulomb bite per half swing, from the 2026-08-24 free-swing fit.
# config/edukit.yaml carries the Q as quality_factor and has no Coulomb term.
MODEL_VISCOUS_Q = 28.7
MODEL_COULOMB_DEG = 1.07


def binned(pairs, width=12.0, min_count=3):
    """Median Q per amplitude bin, with the 25-75 percentile spread as an error band.

    Bins holding fewer than `min_count` peak pairs are dropped from the curve. One or
    two cycles of a single decay are serially correlated, and a band drawn from them is
    narrower than the sampling supports. Sampling is thinnest near vertical. The raw
    scatter still shows every dropped pair.
    """
    buckets: dict[int, list[float]] = {}
    for amp, q in pairs:
        buckets.setdefault(int(amp // width), []).append(q)
    centres, medians, los, his, counts = [], [], [], [], []
    for b in sorted(buckets):
        values = buckets[b]
        if len(values) < min_count:
            continue
        centres.append((b + 0.5) * width)
        medians.append(float(np.median(values)))
        los.append(float(np.percentile(values, 25)))
        his.append(float(np.percentile(values, 75)))
        counts.append(len(values))
    return centres, medians, los, his, counts


def main() -> int:
    """Plot measured Q against amplitude, against the configured model."""
    source = EXPERIMENT / "pump.tsv"
    if not source.exists():
        raise SystemExit(f"no ring-down capture at {source}; run probe-pump first")

    trace, states = read_state_trace(source, 6.666667)
    segments = split_segments(trace, states)
    if not segments:
        raise SystemExit("no decay segments in the capture")

    raw = [p for seg in segments for p in qeff_vs_amplitude(seg)]
    if not raw:
        raise SystemExit("no usable peak pairs")
    peak_amp = max(a for a, _ in raw)
    # Above ~125 deg the pendulum lingers near the top. Consecutive peaks there differ
    # by almost nothing and the per-swing Q diverges into spikes.
    pairs = [(a, q) for a, q in raw if a <= 125.0 and q < 40.0]
    centres, medians, los, his, _counts = binned(pairs)

    _style.apply_style()
    fig, ax = plt.subplots(figsize=(7.6, 4.6))

    # What a viscous-plus-Coulomb plant gives across amplitude. The Coulomb bite is a
    # fixed loss per half swing, a smaller fraction of a big swing. The model Q rises
    # with amplitude toward the viscous asymptote.
    model_x = np.linspace(6.0, min(125.0, peak_amp), 200)
    model_y = [model_quality(a, MODEL_VISCOUS_Q, MODEL_COULOMB_DEG) for a in model_x]
    ax.plot(
        model_x,
        model_y,
        color=_style.MODEL,
        lw=2.2,
        ls=(0, (5, 2)),
        label="the configured model",
    )
    ax.scatter(
        [a for a, q in raw if q < 40.0],
        [q for a, q in raw if q < 40.0],
        s=9,
        color=_style.MEASURED,
        alpha=0.13,
        label="every swing",
    )
    ax.fill_between(
        centres,
        los,
        his,
        color=_style.MEASURED_FILL,
        linewidth=0,
        label="middle 50% per bin",
    )
    ax.plot(
        centres,
        medians,
        color=_style.MEASURED,
        lw=2.4,
        marker="o",
        markersize=5,
        markerfacecolor="white",
        markeredgewidth=1.6,
        label="measured median",
    )

    ax.set_xlabel("swing size (degrees from hanging)")
    ax.set_ylabel("Q, how slowly energy is lost")
    _style.titled(
        ax,
        "Effective Q at each swing size",
        "Past 60 degrees the unit falls below the model, where swing-up works.",
    )
    ax.set_ylim(0, max(38.0, max(model_y) * 1.45))
    ax.set_xlim(0, max(140, peak_amp * 1.05))
    ax.legend(loc="upper left", fontsize=9, borderaxespad=0.8)

    fig.tight_layout()
    out = HERE / "pump_dissipation.png"
    fig.savefig(out)
    hi = [q for a, q in pairs if a > 90]
    hi_med = float(np.median(hi)) if hi else float("nan")
    print(f"wrote {out}  (peak {peak_amp:.0f} deg, Q above 90 deg ~ {hi_med:.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "pyyaml"]
# ///
"""Fit a captured free-swing trace and draw the experiment's figures.

Reads a trace from `scripts/capture_trace.py`, splits it into releases, fits each, and
reports the suspended-mode natural frequency and the quality factor of that decay.

By default it writes the model-against-measurement figure, the rod-length comparison and
the friction split. The remaining values appear in the printed summary. `--diagnostics`
adds frequency against swing amplitude, which shows the band the quoted frequency is
measured in.

    just freeswing-fit [trace.tsv] [--diagnostics]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _style  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from furuta.freeswing import (  # noqa: E402
    LINEAR_BAND_HIGH_DEG,
    LINEAR_BAND_LOW_DEG,
    analyse,
    read_trace,
    segment_releases,
    split_on_reexcitation,
)

plt.switch_backend("Agg")
_style.apply_style()

ROOT = Path(__file__).resolve().parents[4]
FIGURES = Path(__file__).resolve().parent
EXPERIMENT = FIGURES.parent

# ENCODER_READ_ANGLE_SCALE in the firmware, from 2400 encoder counts per revolution.
COUNTS_PER_DEGREE = 6.666667

# Candidate parameter sets, each predicting a suspended-mode period. Mass cancels out of
# the frequency. Only the lengths appear here. The shaft term is the manual's
# published 2*I_shaft/(m*L^2).
GRAVITY = 9.806
SHAFT_TERM = 0.0139
# (name for the printed summary, label for the figure, rod length in metres).
CANDIDATES = (
    ("manual nominal", "manual's rod length\n0.258 m", 0.258),
    ("measured on this unit", "measured on this unit\n0.265 m", 0.265),
)


def predicted_period(rod_length_m: float) -> float:
    """Suspended-mode period for a rod length, from the manual's linearized model."""
    omega_squared = GRAVITY / (rod_length_m * (2.0 / 3.0 + SHAFT_TERM))
    return 2.0 * math.pi / math.sqrt(omega_squared)


def capture() -> Path:
    """The free-swing capture committed beside this write-up."""
    source = EXPERIMENT / "freeswing.tsv"
    if not source.exists():
        raise SystemExit(f"no free-swing capture at {source}")
    return source


MANUAL_FREQUENCY_HZ = 1.1894
MANUAL_QUALITY = 20.0


def configured_model():
    """The suspended-mode frequency and quality factor from the simulation's config."""
    sys.path.insert(0, str(ROOT / "src"))
    from furuta.parameters import FurutaParameters

    p = FurutaParameters.from_yaml()
    return p.suspended_frequency_hz, p.quality_factor


def draw_model_vs_reality(result, trace, path: Path) -> None:
    """The measured swing against the decay the configured constants predict.

    The model envelope is a pure exponential, which approaches rest without reaching it.
    """
    peaks = result.peaks
    if not peaks:
        return
    start = peaks[0].time_s
    amplitude = peaks[0].amplitude_deg

    times = [t - start for t in trace.time_s if t >= start]
    angles = [
        a for t, a in zip(trace.time_s, trace.angle_deg, strict=True) if t >= start
    ]

    model_f, model_q = configured_model()
    model_tau = model_q / (math.pi * model_f)
    fine = [i * 0.01 for i in range(int(max(times) / 0.01))]
    model_env = [amplitude * math.exp(-t / model_tau) for t in fine]

    figure, axes = plt.subplots(figsize=(9.5, 4.4))
    axes.plot(times, angles, linewidth=0.8, color=_style.MEASURED, label="measured")
    axes.plot(
        fine,
        model_env,
        "--",
        color=_style.MODEL,
        linewidth=1.9,
        label="viscous damping only",
    )
    axes.plot(fine, [-e for e in model_env], "--", color=_style.MODEL, linewidth=1.9)

    # Where the real pendulum stopped.
    # Taken from the trace. `peaks` is filtered well above this level.
    # "Stopped" is the last moment the swing exceeded one degree, about seven encoder
    # counts. Below that the reading is quantization.
    moving = [t for t, a in zip(times, angles, strict=True) if abs(a) > 1.0]
    stopped = max(moving) if moving else None
    if stopped and stopped < max(times):
        still = amplitude * math.exp(-stopped / model_tau)
        axes.axvline(stopped, color=_style.MUTED, linewidth=0.9, linestyle="-.")
        axes.annotate(
            f"model: still swinging {still:.0f} deg",
            xy=(stopped - 0.3, still * 0.60),
            ha="right",
            va="center",
            fontsize=9.5,
            color=_style.MODEL,
        )
        axes.annotate(
            f"this unit: at rest by {stopped:.0f} s",
            xy=(stopped - 0.3, -still * 0.60),
            ha="right",
            va="center",
            fontsize=9.5,
            color=_style.MEASURED,
        )
    axes.set_xlabel("seconds after release")
    axes.set_ylabel("pendulum angle from hanging (deg)")
    _style.titled(
        axes,
        "Free-Swing Decay vs Model",
        "One release. A viscous-only pivot never comes to rest.",
    )
    axes.legend(fontsize=9.5, loc="upper right", framealpha=0.95)
    axes.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def draw_friction(results, path: Path) -> None:
    """Amplitude lost per half swing, against the amplitude it started from.

    The fitted line's slope is the viscous term and its intercept the Coulomb one. Both
    are averaged across releases, matching how the constants were fitted.
    """
    figure, axes = plt.subplots(figsize=(8.0, 4.4))
    xs, ys = [], []
    for result in results:
        peaks = result.peaks
        for first, second in zip(peaks, peaks[1:], strict=False):
            if 0 < first.amplitude_deg <= 30.0:
                xs.append(first.amplitude_deg)
                ys.append(first.amplitude_deg - second.amplitude_deg)
    if not xs:
        return
    top = max(ys) * 1.15
    axes.plot(
        xs, ys, "o", markersize=4, alpha=0.6, color=_style.MEASURED, label="measured"
    )

    fits = [r.mixed for r in results if r.mixed]
    if fits:
        slope = sum(m.viscous_fraction for m in fits) / len(fits)
        constant = sum(m.coulomb_deg for m in fits) / len(fits)
        crossover = sum(m.crossover_deg for m in fits) / len(fits)
        span = [0.0, max(xs) * 1.05]
        axes.plot(
            span,
            [constant + slope * x for x in span],
            "-",
            color=_style.MODEL,
            linewidth=2,
            label="drag and dry friction together",
        )
        axes.plot(
            span,
            [slope * x for x in span],
            "--",
            color=_style.GOOD,
            linewidth=1.5,
            label="drag alone",
        )
        axes.axhline(constant, color=_style.NEUTRAL, linewidth=1, linestyle=":")
        axes.annotate(
            f"{constant:.2f} deg goes every half swing, however small the swing",
            xy=(0.4, constant - top * 0.03),
            ha="left",
            va="top",
            fontsize=9.5,
            color=_style.MUTED,
        )
        axes.axvline(crossover, color=_style.MUTED, linewidth=0.9, linestyle="-.")
        axes.annotate(
            f"below {crossover:.0f} deg,\ndry friction is the bigger loss",
            xy=(crossover - 0.5, top * 0.94),
            ha="right",
            va="top",
            fontsize=9.5,
            color=_style.MUTED,
        )
    axes.set_xlim(0, max(xs) * 1.05)
    axes.set_ylim(0, top)
    axes.set_xlabel("the swing it started from (deg)")
    axes.set_ylabel("swing lost over the next half cycle (deg)")
    _style.titled(
        axes,
        "Swing Lost vs Swing Size",
        "The slope is drag. The lift off zero is a fixed dry-friction bite.",
    )
    axes.legend(fontsize=9.5, loc="lower right")
    axes.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def draw_period_comparison(result, path: Path) -> None:
    """How far each candidate rod length's predicted period sits from the bench.

    Both candidates run through the manual's linearized model; only the rod length
    differs. The shaded band is the 2 percent acceptance limit.
    """
    measured = 1.0 / result.frequency_hz if result.frequency_hz else 0.0
    if not measured:
        return
    labels = [label for _, label, _ in CANDIDATES]
    errors = [
        (predicted_period(length) - measured) / measured * 100.0
        for _, _, length in CANDIDATES
    ]

    figure, axes = plt.subplots(figsize=(8.5, 3.4))
    axes.axvspan(-2.0, 2.0, color=_style.GOOD, alpha=0.10)
    axes.axvline(0.0, color=_style.MEASURED, linewidth=1.4)
    positions = range(len(labels))
    best = min(range(len(errors)), key=lambda i: abs(errors[i]))
    for position, error in zip(positions, errors, strict=True):
        axes.plot(
            [0, error],
            [position, position],
            "-",
            color=_style.NEUTRAL,
            linewidth=1.0,
            zorder=1,
        )
        axes.plot(
            error,
            position,
            "o",
            markersize=11,
            color=_style.GOOD if position == best else _style.NEUTRAL,
            zorder=2,
        )
        axes.annotate(
            f"{error:+.2f}%",
            (error, position),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=9.5,
            color=_style.INK,
        )
    axes.set_yticks(list(positions))
    axes.set_yticklabels(labels)
    axes.set_ylim(-0.6, len(labels) - 0.4)
    limit = max(3.0, max(abs(e) for e in errors) * 1.5)
    axes.set_xlim(-limit, limit)
    axes.set_xlabel("predicted period, percent off the measured one")
    _style.titled(
        axes,
        "Period Error by Rod Length",
        f"Against the bench's {measured:.3f} s. Both clear the gate, the measured one "
        "by more.",
    )
    axes.annotate(
        "within 2 percent, accepted",
        xy=(1.9, len(labels) - 0.55),
        ha="right",
        va="top",
        fontsize=9.5,
        color=_style.MUTED,
    )
    axes.grid(alpha=0.25, axis="x")
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def draw_amplitude_dependence(results, path: Path) -> None:
    """Frequency of each half swing against its amplitude.

    A harmonic oscillator would plot flat. The measured slope is the pendulum's own
    nonlinearity. The quoted frequency comes from a restricted band.
    """
    figure, axes = plt.subplots(figsize=(7.5, 4.2))
    for index, result in enumerate(results, start=1):
        pairs = [(a, f) for a, f in result.amplitude_frequency if a >= 1.0]
        if pairs:
            axes.plot(
                [a for a, _ in pairs],
                [f for _, f in pairs],
                "o",
                markersize=3.5,
                alpha=0.75,
                label=f"release {index}",
            )
    axes.axvspan(
        LINEAR_BAND_LOW_DEG,
        LINEAR_BAND_HIGH_DEG,
        color="#2e7d32",
        alpha=0.12,
        label="swings small enough to trust",
    )
    # The leading large-amplitude term, drawn from the measured zero-amplitude value.
    quoted = sum(r.frequency_hz for r in results) / len(results)
    fine = [0.5 + i * 0.5 for i in range(120)]
    axes.plot(
        fine,
        [quoted / (1 + math.radians(a) ** 2 / 16) for a in fine],
        "--",
        color="#c1440e",
        linewidth=1.3,
        label="theory, f0 / (1 + th^2/16)",
    )
    axes.axhline(quoted, color="#9aa5b1", linewidth=0.9)
    axes.set_xlim(0, 60)
    axes.set_xlabel("swing amplitude (deg)")
    axes.set_ylabel("swing speed (Hz)")
    _style.titled(
        axes,
        "Swing Speed vs Amplitude",
        "A big swing is slower, so the quoted frequency comes from a narrow band.",
    )
    axes.legend(fontsize=8)
    axes.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main() -> int:
    """Fit every release in a capture and write the figures."""
    argv = [a for a in sys.argv[1:] if a]
    diagnostics = "--diagnostics" in argv
    positional = [a for a in argv if not a.startswith("-")]
    path = Path(positional[0]) if positional else capture()
    whole = read_trace(path, COUNTS_PER_DEGREE)
    if not len(whole):
        sys.exit(f"{path} holds no usable samples.")

    print(f"[trace] {path}")
    print(f"  {len(whole)} samples over {whole.duration_s:.1f} s")
    print(
        f"  measured rate {whole.sample_rate_hz:.2f} Hz, "
        f"interval jitter {whole.sample_interval_jitter_s * 1e6:.0f} us"
    )

    releases = split_on_reexcitation(segment_releases(whole))
    print(f"  {len(releases)} release(s) detected")
    if not releases:
        sys.exit("No release exceeded the segmentation threshold.")

    results = [analyse(r) for r in releases]
    usable = [(r, t) for r, t in zip(results, releases, strict=True) if r.cycles >= 5]
    if not usable:
        sys.exit("No release had enough cycles to fit.")

    header = (
        f"{'#':>3}  {'f band':>8}  {'f whole':>8}  {'bias':>7}  {'Q':>6}  {'cyc':>4}"
    )
    print(f"\n{header}  damping")
    for index, (result, _) in enumerate(usable, start=1):
        bias = (
            (result.frequency_whole_hz - result.frequency_hz)
            / result.frequency_hz
            * 100
            if result.frequency_hz
            else 0.0
        )
        print(
            f"{index:>3}  {result.frequency_hz:>8.4f}  "
            f"{result.frequency_whole_hz:>8.4f}  "
            f"{bias:>+6.2f}%  {result.quality_factor:>6.2f}  {result.band_cycles:>4}  "
            f"{result.damping_verdict}"
        )

    frequencies = [r.frequency_hz for r, _ in usable]
    qualities = [r.quality_factor for r, _ in usable]
    mean_f = sum(frequencies) / len(frequencies)
    spread = max(frequencies) - min(frequencies)
    print(f"\n  frequency {mean_f:.4f} Hz, spread {spread:.4f} Hz across releases")
    print(f"  Q {sum(qualities) / len(qualities):.2f}")
    print("  manual nominal is 1.19 Hz, Q 20")
    for name, _, length in CANDIDATES:
        predicted = 1.0 / predicted_period(length)
        error = (mean_f - predicted) / predicted * 100.0
        print(f"  vs {name:<24} {predicted:.4f} Hz, measured is {error:+.2f}%")

    # Figures come from the release with the most cycles to fit.
    best, best_trace = max(usable, key=lambda pair: pair[0].cycles)
    FIGURES.mkdir(parents=True, exist_ok=True)
    draw_model_vs_reality(best, best_trace, FIGURES / "freeswing_model_vs_reality.png")
    draw_period_comparison(best, FIGURES / "freeswing_period.png")
    draw_friction([r for r, _ in usable], FIGURES / "freeswing_friction.png")
    if diagnostics:
        draw_amplitude_dependence(
            [r for r, _ in usable], FIGURES / "freeswing_amplitude.png"
        )
    print(f"\n[figures] {FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

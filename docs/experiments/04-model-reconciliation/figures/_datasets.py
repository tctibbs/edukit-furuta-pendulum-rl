"""Readers for the reconciliation datasets, one loader for every figure script.

Every file read here lives beside the write-up and is a few kilobytes. The raw captures
behind them are multi-megabyte and are not committed. Distilling them once lets these
figures redraw on a clean checkout.

`_reconcile.py` is the other half of this folder. It runs the planar model live; this
module only reads what the host already produced.
"""

from __future__ import annotations

import csv
from pathlib import Path
from statistics import median, quantiles

HERE = Path(__file__).resolve().parent
DATA = HERE.parent


def qeff(name: str) -> list[tuple[float, float]]:
    """Amplitude and effective Q pairs from one ladder CSV."""
    path = DATA / name
    with path.open() as handle:
        return [
            (float(row["amplitude_deg"]), float(row["quality"]))
            for row in csv.DictReader(handle)
        ]


def replay(name: str) -> dict[str, list[float]]:
    """Columns of one replay CSV, keyed by header name."""
    path = DATA / name
    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    return {key: [float(row[key]) for row in rows] for key in rows[0]}


def available(name: str) -> bool:
    """Whether a dataset is present. A figure calls this to name what it cannot draw."""
    return (DATA / name).exists()


def binned_median(
    pairs: list[tuple[float, float]],
    width: float = 15.0,
    lo: float = 10.0,
    hi: float = 175.0,
) -> tuple[list[float], list[float]]:
    """Median Q in fixed amplitude bins. Figures draw it as a line over the scatter."""
    centres, medians, _, _, _ = binned_spread(pairs, width, lo, hi)
    return centres, medians


def binned_spread(
    pairs: list[tuple[float, float]],
    width: float = 15.0,
    lo: float = 10.0,
    hi: float = 175.0,
) -> tuple[list[float], list[float], list[float], list[float], list[int]]:
    """Median, quartiles and sample count per bin, for drawing a band around a line.

    The hardware ladder walks from large swings down, so the wide bins hold two or three
    decays where the narrow ones hold dozens. A bare median line hides that. Bins under
    four samples have no meaningful quartile, so they report their own minimum and
    maximum and the count tells the reader which case a point is.
    """
    centres: list[float] = []
    medians: list[float] = []
    lows: list[float] = []
    highs: list[float] = []
    counts: list[int] = []
    edge = lo
    while edge < hi:
        values = sorted(q for a, q in pairs if edge <= a < edge + width)
        if values:
            cuts = quantiles(values, n=4) if len(values) >= 4 else None
            centres.append(edge + width / 2.0)
            medians.append(median(values))
            lows.append(cuts[0] if cuts else values[0])
            highs.append(cuts[2] if cuts else values[-1])
            counts.append(len(values))
        edge += width
    return centres, medians, lows, highs, counts

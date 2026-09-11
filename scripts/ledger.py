# /// script
# requires-python = ">=3.11"
# ///
"""Build an experiment's results ledger from the raw training and evaluation outputs.

Two files sit beside each training write-up and every figure reads from them. Neither
was produced by anything in the repository until now; both were assembled by hand, which
is why they could not be rebuilt when the plant changed.

- `results.csv`, one row per training iteration, parsed out of the rsl_rl log. The
  training script prints a block per iteration and this reads the five fields the
  learning-curve and saturation figures use.
- `recovery.csv`, one row per (seed, kick magnitude), stacked from the per-seed CSVs
  `scripts/evaluate.py` writes, with the seed column that script does not carry.

    uv run scripts/ledger.py results runlogs/seed1.log <experiment>/results.csv
    uv run scripts/ledger.py recovery results/eval_seed*.csv <experiment>/recovery.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# rsl_rl's per-iteration block, as it prints it. The iteration number is taken as the
# runner prints it; its first block carries no episode statistics yet and is dropped as
# incomplete, so the ledger starts at 1 without any renumbering.
_ITERATION = re.compile(r"Learning iteration\s+(\d+)/\d+")
_FIELDS = {
    "noise_std": re.compile(r"Mean action noise std:\s*([-\d.]+)"),
    "reward": re.compile(r"Mean reward:\s*([-\d.]+)"),
    "episode_length": re.compile(r"Mean episode length:\s*([-\d.]+)"),
    "saturated_fraction": re.compile(r"action/saturated_fraction:\s*([-\d.]+)"),
    "upright_abs_deg": re.compile(r"state/upright_abs_deg:\s*([-\d.]+)"),
}
# Not in every training log; a field a log lacks is left blank.
_OPTIONAL_FIELDS = {
    "hanging_peak_energy_frac": re.compile(r"hanging/peak_energy_frac:\s*([-\d.]+)"),
    "hanging_min_tilt_deg": re.compile(r"hanging/min_tilt_deg:\s*([-\d.]+)"),
    "hanging_reached_gate_frac": re.compile(r"hanging/reached_gate_frac:\s*([-\d.]+)"),
    "hanging_entered_set_frac": re.compile(r"hanging/entered_set_frac:\s*([-\d.]+)"),
    "hanging_held_half_s_frac": re.compile(r"hanging/held_half_s_frac:\s*([-\d.]+)"),
    "value_loss": re.compile(r"Mean value_function loss:\s*([-\d.]+)"),
}
_REQUIRED = ["iteration", *_FIELDS]
_COLUMNS = [
    "iteration",
    "reward",
    "episode_length",
    "upright_abs_deg",
    "saturated_fraction",
    "noise_std",
    *_OPTIONAL_FIELDS,
]


def parse_training_log(text: str) -> list[dict[str, str]]:
    """Return one row per iteration block that carries every required field."""
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in text.splitlines():
        # Strip the terminal colour codes the runner wraps its headers in.
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        hit = _ITERATION.search(line)
        if hit:
            if current is not None and all(k in current for k in _REQUIRED):
                rows.append(current)
            current = {"iteration": hit.group(1)}
            continue
        if current is None:
            continue
        for name, pattern in {**_FIELDS, **_OPTIONAL_FIELDS}.items():
            found = pattern.search(line)
            if found:
                current[name] = str(float(found.group(1)))
    if current is not None and all(k in current for k in _REQUIRED):
        rows.append(current)
    return rows


def write_results(log: Path, out: Path) -> int:
    """Parse one training log into the iteration ledger."""
    rows = parse_training_log(log.read_text(errors="replace"))
    if not rows:
        print(f"[fail ] no complete iteration blocks in {log}")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done ] {len(rows)} iterations from {log.name} -> {out}")
    return 0


def write_recovery(evals: list[Path], out: Path) -> int:
    """Stack the per-seed evaluation CSVs, adding the seed each file is named for."""
    rows: list[dict[str, str]] = []
    for path in sorted(evals):
        hit = re.search(r"seed(\d+)", path.stem)
        if not hit:
            print(f"[fail ] cannot read a seed number from {path.name}")
            return 1
        with path.open() as fh:
            for row in csv.DictReader(fh):
                rows.append({"seed": hit.group(1), **row})
    if not rows:
        print("[fail ] no evaluation rows")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[done ] {len(rows)} rows from {len(evals)} seeds -> {out}")
    return 0


def main() -> int:
    """Dispatch on which ledger is being built."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="which", required=True)
    r = sub.add_parser("results", help="training log -> results.csv")
    r.add_argument("log", type=Path)
    r.add_argument("out", type=Path)
    v = sub.add_parser("recovery", help="eval_seed*.csv -> recovery.csv")
    v.add_argument("evals", type=Path, nargs="+")
    v.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.which == "results":
        return write_results(args.log, args.out)
    return write_recovery(args.evals, args.out)


if __name__ == "__main__":
    sys.exit(main())

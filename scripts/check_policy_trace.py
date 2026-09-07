"""Replay a recorded trajectory through the exported C policy and compare commands.

The unit test in `tests/test_board.py` proves the C forward matches PyTorch on random
observations. This proves it on the observations a real episode produced: every row of
a `scripts/scripted_swingup.py --trace` file where the policy was in command carries the
five observations and the acceleration the simulation actually applied, so the same
rows through the compiled harness must give the same accelerations. A mismatch here
and not in the unit test points at the observation ordering or the scaling, which is
exactly the part the firmware glue can get wrong.

    uv run scripts/check_policy_trace.py <harness> <trace.csv> [--a-max 11.78]

`<harness>` is the host binary built from `board/`; the model-conversion runbook under
`docs/runbooks/` has the build. Exit status is non-zero past the tolerance.
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Run the comparison and print the largest error."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("harness", help="board test binary")
    parser.add_argument("trace", help="csv from scripted_swingup.py --trace")
    parser.add_argument(
        "--a-max",
        type=float,
        default=11.78,
        help="acceleration bound the policy's action was scaled by in the trace",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-3,
        help="largest allowed |difference| in rad/s^2",
    )
    args = parser.parse_args()

    with Path(args.trace).open() as handle:
        rows = [r for r in csv.DictReader(handle) if r["catching"] == "1"]
    if not rows:
        sys.exit(f"{args.trace} has no rows with the policy in command")
    lines = []
    expected = []
    for r in rows:
        tilt = float(r["tilt_rad"])
        obs = (
            math.cos(tilt),
            math.sin(tilt),
            float(r["rate_rad_s"]),
            float(r["rotor_rad"]),
            float(r["rotor_rate_rad_s"]),
        )
        lines.append(" ".join(f"{v:.9g}" for v in obs))
        expected.append(float(r["u"]))

    # `command` mode applies the bound the header was exported with, tanh or clamp,
    # so a checkpoint from a task that set `squash_actions` is checked against the
    # arithmetic it trained under; `policy` mode gives the raw action for the count of
    # rows past the rail.
    def harness(*mode: str) -> list[float]:
        result = subprocess.run(
            [args.harness, *mode],
            input="\n".join(lines) + "\n",
            capture_output=True,
            text=True,
            check=True,
        )
        return [float(v) for v in result.stdout.split()]

    commands = harness("command", str(args.a_max))
    actions = harness("policy")
    if len(commands) != len(expected):
        sys.exit(f"harness returned {len(commands)} values for {len(expected)} rows")
    errors = [abs(c - u) for c, u in zip(commands, expected, strict=True)]
    worst = max(errors)
    saturated = sum(1 for a in actions if abs(a) >= 1.0)
    print(
        f"{len(rows)} rows with the policy in command; largest |difference| "
        f"{worst:.6f} rad/s^2; {saturated} rows past the rail"
    )
    if worst > args.tolerance:
        print(f"FAIL: exceeds {args.tolerance} rad/s^2")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

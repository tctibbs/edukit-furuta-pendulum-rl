# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Plot throughput and rotor tracking error from the bench results.

`results.csv` has one row per environment count. `tracking.csv` has one row per rotor
drive configuration, each measured at one environment. Both are transcribed from what
`scripts/bench_environment.py` printed on the training host.
"""

import csv
from pathlib import Path

import matplotlib.pyplot as plt

plt.switch_backend("Agg")

BLUE = "#1f77b4"
GREY = "#8a8a8a"

HERE = Path(__file__).parent
scale = list(csv.DictReader((HERE.parent / "results.csv").open()))
track = list(csv.DictReader((HERE.parent / "tracking.csv").open()))

envs = [int(r["num_envs"]) for r in scale]
throughput = [float(r["throughput_steps_per_s"]) for r in scale]
step_ms = [float(r["step_time_ms"]) for r in scale]

errors = [float(r["tracking_error_microsteps"]) for r in track]
damping = [r["drive_damping"] for r in track]
labels = [f"DriveAPI\nD = {float(d):g}" if d else "no DriveAPI" for d in damping]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

ax1.loglog(envs, throughput, "o-", color=BLUE, linewidth=2, label="Furuta pendulum")
# Experiment 01's cartpole at 4096 environments, read while PPO trained.
ax1.plot(4096, 238190, "s", color=GREY, label="cartpole, Experiment 01")
ax1.text(
    0.96,
    0.06,
    f"step time {min(step_ms):.2f} to {max(step_ms):.2f} ms at every count",
    transform=ax1.transAxes,
    ha="right",
    va="bottom",
    fontsize=8.5,
    color=GREY,
)
ax1.set_xlabel("parallel environments")
ax1.set_ylabel("throughput (steps/s)")
ax1.set_title("Throughput")
ax1.grid(alpha=0.3)
ax1.set_axisbelow(True)
ax1.margins(0.14)
ax1.legend(fontsize=8.5, loc="upper left")

# The last row is the configuration the environment ships with.
colors = [GREY] * (len(errors) - 1) + [BLUE]
bars = ax2.bar(range(len(errors)), errors, color=colors, width=0.6)
ax2.set_yscale("log")
ax2.set_ylim(0.03, 1000.0)
ax2.bar_label(bars, labels=[f"{e:g}" for e in errors], padding=3, fontsize=8.5)
ax2.axhline(1.0, color=GREY, linestyle="--", linewidth=1)
ax2.text(
    len(errors) - 1,
    1.2,
    "one microstep",
    ha="center",
    va="bottom",
    fontsize=8.5,
    color=GREY,
)
ax2.set_xticks(range(len(errors)), labels, fontsize=9)
ax2.set_ylabel("tracking error (microsteps)")
ax2.set_title("Rotor tracking error, one environment")
ax2.grid(alpha=0.3, axis="y")
ax2.set_axisbelow(True)

fig.tight_layout()
fig.savefig(HERE / "environment_results.png", dpi=150)
print("wrote", HERE / "environment_results.png")

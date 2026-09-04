# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Plot the learning curve for experiment 01 from the exported TensorBoard scalars."""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).parent
rows = list(csv.DictReader((HERE.parent / "results.csv").open()))

it = [int(r["iteration"]) for r in rows]
reward = [float(r["reward"]) for r in rows]
ep_len = [float(r["ep_len"]) for r in rows]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.6))

ax1.plot(it, reward, color="#1f77b4", linewidth=2)
ax1.set_xlabel("iteration")
ax1.set_ylabel("mean reward")
ax1.set_title("Mean reward")
ax1.grid(alpha=0.3)

ax2.plot(it, ep_len, color="#d62728", linewidth=2)
# 300 steps is the episode cap, the task's 5 s limit at its 60 Hz step rate. An episode
# ends early only on termination, so the gap between the curve and this line is how
# often the pole fell.
ax2.axhline(300, color="grey", linestyle="--", linewidth=1)
ax2.text(1, 305, "episode cap, 300 steps", fontsize=8, color="grey")
ax2.set_xlabel("iteration")
ax2.set_ylabel("mean episode length (steps)")
ax2.set_title("Mean episode length")
# A fixed limit. Episode length peaks at 275.5, and the cap line and its label need
# room above that.
ax2.set_ylim(0, 340)
ax2.grid(alpha=0.3)

fig.suptitle("Isaac-Cartpole-Direct-v0, PPO, 4096 envs, seed 42", fontsize=10)
fig.tight_layout()
fig.savefig(HERE / "learning_curve.png", dpi=150)
print("wrote", HERE / "learning_curve.png")

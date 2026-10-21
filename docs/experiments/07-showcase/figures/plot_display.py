# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib", "numpy"]
# ///
"""The showcase display, as the firmware draws it.

Builds `board/test_showcase.c` on the host with the board's own screen code, font and
generated table, takes the screens its `render` mode prints as rows of '#' and '.', and
lays them out as the two-colour panel shows them: the top 16 rows yellow, the rest
blue, each panel framed in the bezel's grey with no labels. The results carry example
values. Needs a C compiler: $CC, or cc, clang or gcc on PATH.

    just figures 07
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
BOARD = HERE.parents[3] / "board"
sys.path.insert(0, str(HERE))
import _style  # noqa: E402

SOURCES = (
    "display.c",
    "font5x7.c",
    "showcase.c",
    "showcase_screens.c",
    "showcase_table.c",
    "policy.c",
    "test_showcase.c",
)

# The SSD1306 module's two colours: the top 16 rows yellow, the rest blue.
YELLOW_ROWS = 16
GLASS = (0.04, 0.05, 0.07)
YELLOW = (0.98, 0.82, 0.27)
BLUE = (0.38, 0.75, 1.0)
BEZEL = "#26303a"

# Figure pixels, at the 150 dpi of _style, so one panel pixel is a 4-pixel cell with a
# 3-pixel dot and the grid shows. GLASS_CELLS of bare glass border each panel, and
# FRAME pixels of bezel separate the panels and edge the figure.
DPI = 150
CELL = 4
DOT = 3
GLASS_CELLS = 4
COLUMNS = 3
FRAME = 16


def compiler() -> list[str]:
    """The host C compiler, found as the board harness tests find it."""
    candidates = [shlex.split(os.environ["CC"])] if os.environ.get("CC") else []
    candidates += [["cc"], ["clang"], ["gcc"]]
    for command in candidates:
        path = shutil.which(command[0])
        if path is not None:
            return [path, *command[1:]]
    raise SystemExit("no C compiler ($CC, cc, clang or gcc) for the screen harness")


def render() -> list[list[str]]:
    """Each screen the harness renders, as its rows."""
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "test_showcase"
        subprocess.run(
            [
                *compiler(),
                "-std=c99",
                "-O2",
                "-ffp-contract=off",
                f"-I{BOARD}",
                *(str(BOARD / name) for name in SOURCES),
                "-lm",
                "-o",
                str(exe),
            ],
            check=True,
        )
        out = subprocess.run(
            [str(exe), "render"], check=True, capture_output=True, text=True
        ).stdout
    screens: list[list[str]] = []
    for line in out.splitlines():
        if line.startswith("=== "):
            screens.append([])
        elif screens and line:
            screens[-1].append(line)
    return screens


def panel(rows: list[str]) -> np.ndarray:
    """The panel as an RGB image: each lit pixel a dot of its band's colour on glass."""
    pad = GLASS_CELLS * CELL
    image = np.empty((len(rows) * CELL + 2 * pad, len(rows[0]) * CELL + 2 * pad, 3))
    image[:] = GLASS
    for y, row in enumerate(rows):
        ink = YELLOW if y < YELLOW_ROWS else BLUE
        for x, pixel in enumerate(row):
            if pixel == "#":
                top, left = pad + y * CELL, pad + x * CELL
                image[top : top + DOT, left : left + DOT] = ink
    return image


def main() -> None:
    """Draw each rendered screen as a panel, three to a row."""
    _style.apply_style()
    screens = render()
    height, width = panel(screens[0]).shape[:2]
    rows = -(-len(screens) // COLUMNS)
    fig_w = COLUMNS * width + (COLUMNS + 1) * FRAME
    fig_h = rows * height + (rows + 1) * FRAME
    fig = plt.figure(figsize=(fig_w / DPI, fig_h / DPI), dpi=DPI, facecolor=BEZEL)
    for k, screen in enumerate(screens):
        row, column = divmod(k, COLUMNS)
        left = FRAME + column * (width + FRAME)
        top = FRAME + row * (height + FRAME)
        ax = fig.add_axes(
            (left / fig_w, 1 - (top + height) / fig_h, width / fig_w, height / fig_h)
        )
        ax.imshow(panel(screen), interpolation="nearest", aspect="equal")
        ax.set_axis_off()
    _style.save(fig, HERE / "display_screens.png", dpi=DPI, bbox_inches=fig.bbox_inches)


if __name__ == "__main__":
    main()

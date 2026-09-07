# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
r"""Build a GIF from recorder mp4s whose drawn frames come at irregular intervals.

The recorder writes one frame per 2 ms control step and, on some runs, draws only some
of them: a strict odd or even half on most, and on a one-rig recording at 4 kHz about
half of the odd frames with blank runs up to a quarter of a second between. A parity
filter that keeps every other frame assumes the strict case. This script
keeps the timeline instead: for each output frame it takes the most recent drawn frame
at or before that instant, which is what a viewer would have seen, so playback speed is
exact and a gap shows as a held frame rather than a jump.

Blank frames are found by size after the crop and scale, as `frame_parity.sh` does: a
flat frame encodes to a tiny PNG. The drawn frames inside a short window before each
output instant are averaged, which removes the path tracer's grain (it differs frame to
frame, so every pixel changes and GIF's frame differencing buys nothing) at the cost of
a few milliseconds of motion blur. Every input is treated the same way and stacked side
by side, so a comparison of two runs is one command.

    uv run scripts/hold_frames_to_gif.py out.gif --fps 12.5 --start 0 --duration 24 \\
        --crop 640:690:320:20 --width 300 left.mp4 right.mp4

The fps must be one GIF stores exactly (100/k centiseconds): 25, 20, 12.5 or 10.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

CONTROL_HZ = 500.0
BLANK_BYTES = 2000


def extract(
    video: Path, crop: str, width: int, denoise: float, into: Path
) -> list[Path]:
    """Write every frame of the clip, cropped and scaled; return the paths in order."""
    into.mkdir(parents=True, exist_ok=True)
    filters = []
    if crop != "none":
        filters.append(f"crop={crop}")
    if denoise > 0:
        # The path tracer's grain differs frame to frame, so every pixel changes and
        # GIF's frame differencing buys nothing. A spatial denoise before scaling
        # removes it; the geometry is hard-edged and survives.
        filters.append(f"hqdn3d={denoise}:{denoise * 0.75:.2f}:0:0")
    filters.append(f"scale={width}:-2:flags=area")
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            ",".join(filters),
            "-vsync",
            "passthrough",
            str(into / "f_%06d.png"),
        ],
        check=True,
    )
    return sorted(into.glob("f_*.png"))


def held_sequence(
    frames: list[Path],
    fps: float,
    start: float,
    duration: float,
    window_s: float,
    into: Path,
):
    """Per output instant, the drawn frames inside the window before it, averaged."""
    drawn = [p.stat().st_size > BLANK_BYTES for p in frames]
    into.mkdir(parents=True, exist_ok=True)
    window = max(1, int(round(window_s * CONTROL_HZ)))
    out: list[Path] = []
    held = 0
    count = int(round(duration * fps))
    cache: dict[int, np.ndarray] = {}

    def load(i: int) -> np.ndarray:
        if i not in cache:
            cache[i] = np.asarray(
                Image.open(frames[i]).convert("RGB"), dtype=np.float32
            )
        return cache[i]

    last_drawn = None
    for k in range(count):
        n = int(round((start + k / fps) * CONTROL_HZ))
        n = min(max(n, 0), len(frames) - 1)
        picks = [i for i in range(max(0, n - window + 1), n + 1) if drawn[i]]
        if not picks:
            # Nothing drawn inside the window: hold the most recent drawn frame.
            last = next((i for i in range(n, -1, -1) if drawn[i]), None)
            if last is None:
                last = next(i for i, ok in enumerate(drawn) if ok)
            picks = [last]
            held += 1
        last_drawn = picks[-1]
        mean = np.mean([load(i) for i in picks], axis=0)
        path = into / f"o_{k:05d}.png"
        Image.fromarray(mean.round().astype(np.uint8)).save(path)
        out.append(path)
        cache.clear()
    del last_drawn
    return out, sum(drawn), len(drawn), held


def main() -> int:
    """Extract, select with hold, stack, and encode with a 64 colour palette."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out")
    parser.add_argument("videos", nargs="+")
    parser.add_argument("--fps", type=float, default=12.5)
    parser.add_argument(
        "--start", type=float, default=0.0, help="seconds of simulated time"
    )
    parser.add_argument(
        "--duration", type=float, required=True, help="seconds of simulated time"
    )
    parser.add_argument("--crop", default="none", help="w:h:x:y before scaling")
    parser.add_argument("--width", type=int, default=300, help="width of each panel")
    parser.add_argument("--colours", type=int, default=64)
    parser.add_argument(
        "--window",
        type=float,
        default=0.016,
        help="seconds of drawn frames averaged into each output frame",
    )
    parser.add_argument(
        "--denoise",
        type=float,
        default=6.0,
        help="spatial denoise strength before scaling; 0 disables it",
    )
    args = parser.parse_args()

    centiseconds = 100.0 / args.fps
    if abs(centiseconds - round(centiseconds)) > 1e-9:
        sys.exit(f"fps {args.fps} is not a whole number of centiseconds per frame")

    work = Path(tempfile.mkdtemp(prefix="holdgif_"))
    try:
        lists = []
        for i, video in enumerate(args.videos):
            frames = extract(
                Path(video), args.crop, args.width, args.denoise, work / f"in{i}"
            )
            seq, n_drawn, n_all, holds = held_sequence(
                frames,
                args.fps,
                args.start,
                args.duration,
                args.window,
                work / f"out{i}",
            )
            print(
                f"{Path(video).name}: {n_drawn} of {n_all} frames drawn; "
                f"{len(seq)} output frames, {holds} with nothing drawn in their window"
            )
            listing = work / f"list{i}.txt"
            listing.write_text(
                "".join(f"file '{p}'\nduration {1 / args.fps}\n" for p in seq)
                + f"file '{seq[-1]}'\n"
            )
            lists.append(listing)
        inputs = []
        for listing in lists:
            inputs += ["-f", "concat", "-safe", "0", "-i", str(listing)]
        stack = (
            "".join(f"[{i}:v]" for i in range(len(lists)))
            + f"hstack=inputs={len(lists)}[s];"
            if len(lists) > 1
            else "[0:v]null[s];"
        )
        graph = (
            f"{stack}[s]fps={args.fps},split[a][b];"
            f"[a]palettegen=max_colors={args.colours}:stats_mode=diff[p];"
            f"[b][p]paletteuse=dither=none"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                graph,
                "-loop",
                "0",
                args.out,
            ],
            check=True,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    report = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=width,height,nb_frames:format=duration",
            "-of",
            "csv=p=0",
            args.out,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    delays = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "frame=duration_time",
            "-of",
            "csv=p=0",
            args.out,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    size_kb = Path(args.out).stat().st_size / 1024
    print(
        f"{args.out}: {size_kb:.0f} KB, {' '.join(report)}, "
        f"frame delays {sorted(set(delays))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

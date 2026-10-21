# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
"""Build the showcase clips from the bench phone videos.

The phone videos (IMG_<n>.MOV, 1080x1920 portrait, 29.97 fps) are not committed. Pass
the folder that holds them:

    uv run docs/experiments/07-showcase/figures/make_clips.py <video-folder> [name ...]

Each clip is locked to its first frame by phase correlation on the wall art, so the
background neither drifts nor jumps at the loop point. Pixels that stay within a few
grey levels of the clip's median frame are set to that median, so sensor noise in the
still background costs nothing; everything that moves keeps its own pixels. Every
source frame is kept, and the result is an animated WebP. Needs ffmpeg and img2webp.
"""

import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))

# name: (video, start s, end s). The crop is the full width and the top 1600 rows,
# which holds the upright rod's tip, the arm's sweep, the base, and the cat.
CLIPS = {
    "swing_up": ("IMG_4008.MOV", 0.9, 6.0),
    "jethro_swing_up": ("IMG_4009.MOV", 0.9, 6.0),
    "cat_boxing": ("IMG_4012.MOV", 54.4, 59.8),
    "lqr": ("IMG_4001.MOV", 8.0, 15.5),
    "pid": ("IMG_3999.MOV", 4.0, 10.4),
    "balance": ("IMG_4003.MOV", 7.0, 14.0),
    "ring_down": ("IMG_4002.MOV", 4.0, 13.0),
}
CROP = (0, 0, 1080, 1600)
WIDTH = 540
QUALITY = 90
FREEZE = 10  # grey levels; the noise in the still background sits below this
SRC_W, SRC_H = 1080, 1920
BAND = (20, 20, 380, 640)  # wall art left of the rig, the stabilization reference


def frames(video, start, end):
    """Yield the full-resolution RGB frames of a video between two times."""
    proc = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(start),
            "-i",
            video,
            "-t",
            str(end - start),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        stdout=subprocess.PIPE,
    )
    size = SRC_W * SRC_H * 3
    while (buf := proc.stdout.read(size)) and len(buf) == size:
        yield np.frombuffer(buf, np.uint8).reshape(SRC_H, SRC_W, 3)
    proc.wait()


def shifts(video, start, end):
    """Return each frame's camera shift against the first, in source pixels."""
    bx, by, bw, bh = BAND
    win = np.hanning(bh // 2)[:, None] * np.hanning(bw // 2)[None, :]
    ref, out = None, []
    for f in frames(video, start, end):
        g = f[by : by + bh : 2, bx : bx + bw : 2].mean(axis=2)
        spec = np.fft.fft2((g - g.mean()) * win)
        ref = spec if ref is None else ref
        r = ref * np.conj(spec)
        c = np.abs(np.fft.ifft2(r / (np.abs(r) + 1e-9)))
        y, x = np.unravel_index(np.argmax(c), c.shape)
        y = y - c.shape[0] if y > c.shape[0] // 2 else y
        x = x - c.shape[1] if x > c.shape[1] // 2 else x
        out.append((2 * x, 2 * y))
    s = np.array(out, float)
    # The rod can cross the band for a frame or two; a running median ignores it.
    return (
        np.array([np.median(s[max(0, i - 4) : i + 5], axis=0) for i in range(len(s))])
        .round()
        .astype(int)
    )


def build(name, video, start, end):
    """Write one clip as an animated WebP beside this script."""
    cx, cy, cw, ch = CROP
    ow, oh = WIDTH, round(WIDTH * ch / cw / 2) * 2
    sh = shifts(video, start, end)
    pad = int(np.abs(sh).max()) + 2
    tiles = []
    for f, (dx, dy) in zip(frames(video, start, end), sh, strict=False):
        fp = np.pad(f, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        x0, y0 = cx - dx + pad, cy - dy + pad
        tiles.append(
            np.asarray(
                Image.fromarray(fp[y0 : y0 + ch, x0 : x0 + cw]).resize(
                    (ow, oh), Image.LANCZOS
                )
            )
        )
    tiles = np.stack(tiles)
    bg = np.median(tiles, axis=0).astype(np.float32)
    tmp = tempfile.mkdtemp()
    args = ["img2webp", "-loop", "0", "-sharp_yuv"]
    period, acc = 1000 * 1001 / 30000, 0.0
    for i, t in enumerate(tiles):
        d = np.abs(t.astype(np.float32) - bg).max(axis=2)
        d = Image.fromarray(np.clip(d, 0, 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(1.5)
        )
        m = Image.fromarray(((np.asarray(d) > FREEZE) * 255).astype(np.uint8))
        m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
        m = m.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
        mm = np.asarray(m, np.float32)[..., None] / 255.0
        frame = (mm * t + (1 - mm) * bg).round().astype(np.uint8)
        path = os.path.join(tmp, f"f{i:04d}.png")
        Image.fromarray(frame).save(path, compress_level=1)
        # 29.97 fps is 33.37 ms a frame and WebP stores whole milliseconds.
        acc += period
        args += [
            "-d",
            str(int(round(acc)) - int(round(acc - period))),
            "-lossy",
            "-q",
            str(QUALITY),
            "-m",
            "6",
            path,
        ]
    out = os.path.join(HERE, f"{name}.webp")
    subprocess.run(args + ["-o", out], check=True, capture_output=True)
    print(
        f"{name}.webp: {len(tiles)} frames, {ow}x{oh},",
        f"{os.path.getsize(out) // 1024} KB",
    )


if __name__ == "__main__":
    # `just figures 07` runs every script here with no arguments, and the videos are
    # not in the repository, so a bare run skips instead of failing the recipe.
    if len(sys.argv) < 2:
        print("make_clips.py: pass the folder holding the phone videos; skipping")
        sys.exit(0)
    src = sys.argv[1]
    for name in sys.argv[2:] or CLIPS:
        video, start, end = CLIPS[name]
        build(name, os.path.join(src, video), start, end)

"""Capture a free-swing trace from the Edukit's mode `w` logger.

Mode `w` streams one line per control period, microseconds and encoder counts separated
by a tab, with the rotor held. A free arm would make it a coupled two-degree-of-freedom
system, whose frequency is not the suspended mode the manual publishes.

Timestamps come from the board. Samples run about 6.5 kB/s against 23 kB/s of link. No
sample is lost to bandwidth.

The capture runs for the duration once the sample header arrives. Take several releases
within one capture; `furuta.freeswing` segments them.

    uv run --with pyserial python scripts/capture_trace.py --seconds 180
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
import time
from pathlib import Path

BAUD = 230400

# The firmware ends its mode prompt with this. Only the trailing colon proves the
# whole prompt arrived. USB CDC delivers the line in fragments, and writing before
# the firmware has armed its read drops the bytes silently.
MODE_PROMPT_TAIL = b"Seconds..:"

DEFAULT_MODE = "w"

# The logger's own header, echoed before the samples start. Each logging mode announces
# its columns this way. Mode w emits two columns, mode y three, and modes d, a and u
# five.
HEADER_MARKER = b"us\tcounts"

# A sample line: integer timestamp, tab, signed integer count. Recognises a board
# already logging after a previous capture left it in mode w. Without this the script
# would wait for a boot prompt that is never coming.
SAMPLE_LINE = re.compile(rb"^\d+\t-?\d+(\t-?\d+)?$")
MIN_SAMPLE_LINES = 5


def find_port(explicit: str | None) -> str:
    """Return the serial device for the board, or exit when none is found."""
    if explicit:
        return explicit
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("No /dev/cu.usbmodem* found. Connect the board and try again.")
    return ports[0]


def main() -> int:
    """Answer the mode prompt, then stream samples to a file until time runs out."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=None)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        help="boot mode to enter: w for free swing, y for the tilt sweep",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output path; defaults to data/freeswing/<timestamp>.tsv",
    )
    args = parser.parse_args()

    import serial

    port = find_port(args.port)
    folder = {"w": "freeswing", "y": "tilt"}.get(args.mode, "capture")
    out = (
        Path(args.out)
        if args.out
        else Path("data") / folder / (time.strftime("%Y%m%d-%H%M%S") + ".tsv")
    )
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        link = serial.Serial(port, BAUD, timeout=0.1)
    except OSError as error:
        # A stale process holding the port reports as a disconnect.
        sys.exit(
            f"Could not open {port}: {error}\n"
            f"If another process holds it: lsof -t {port} | xargs -r kill -9"
        )

    print(f"[port] {port} at {BAUD} 8N1")
    print(f"[out ] {out}")
    print("[action] press the physical reset button now")

    recent = b""
    answered = False
    streaming = False
    samples = 0
    build = None
    deadline = None

    with out.open("wb") as sink:
        while True:
            if deadline is not None and time.time() > deadline:
                break
            try:
                data = link.read(4096)
            except OSError as error:
                print(f"\n[error] lost the port: {error}", flush=True)
                break
            if not data:
                continue

            if streaming:
                sink.write(data)
                samples += data.count(b"\n")
                print(f"\r[rec ] {samples} samples", end="", flush=True)
                continue

            # Check the whole buffer before trimming it. Once the logger starts, one
            # read returns several kilobytes, and trimming first would discard the
            # header off the front and the capture would wait forever for it.
            buffer = recent + data

            if HEADER_MARKER in buffer:
                sink.write(buffer.split(HEADER_MARKER, 1)[1].lstrip(b"\r\n"))
                streaming = True
                deadline = time.time() + args.seconds
                print(f"[rec ] streaming {args.seconds:.0f}s. Release the pendulum")
                continue

            # No header, but the board may already be logging from an earlier run.
            complete = buffer.split(b"\n")[1:-1]
            matched = sum(
                1 for line in complete if SAMPLE_LINE.match(line.strip(b"\r"))
            )
            if matched >= MIN_SAMPLE_LINES:
                sink.write(b"\n".join(complete) + b"\n")
                streaming = True
                deadline = time.time() + args.seconds
                print(f"[rec ] already logging. Streaming {args.seconds:.0f}s")
                continue

            recent = buffer[-400:]

            if not answered and recent.rstrip(b" ").endswith(MODE_PROMPT_TAIL):
                # The firmware acts on a command only when a read returns two bytes
                # carrying a payload of one.
                link.write(args.mode.encode() + b"\r")
                link.flush()
                answered = True
                print(f"\n[sent] mode {args.mode!r}", flush=True)
                continue

            if b"BUILD " in recent and build is None:
                tail = recent.split(b"BUILD ", 1)[1]
                build = tail.split(b" ", 1)[0].decode("ascii", "replace").strip()
                print(f"[build] board reports {build!r}")

    link.close()
    print()
    if not streaming:
        print(
            f"[fail] never reached the sample header. Was mode {args.mode!r} entered?"
        )
        return 1
    print(f"[done] {samples} samples to {out}")
    if build is not None and build != "bench":
        print(f"[warn] board reported build {build!r}, expected 'bench'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

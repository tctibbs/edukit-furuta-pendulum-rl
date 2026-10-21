"""Capture a serial log from one of the board's logging modes.

Every logging mode streams tab-separated lines announced by a header naming its
columns: `us counts` from the free-swing logger (`w`), `us counts phi` from the tilt
sweep (`y`), and five columns from the identification and RL modes (`d`, `a`, `u`, `b`,
`r`). The capture runs from the header for `--seconds`, then closes. The showcase (`x`)
records from boot instead.

A menu build prints a mode prompt after reset, and this script answers it with the mode
letter. An autostart build (`IDENT_AUTOSTART_MODE` set, one image per mode) boots
straight into its mode and prints no prompt. `--auto-reset` resets the board through the
debugger (`st-flash reset`) so the capture begins at boot; without it the script asks
for the reset button.

Timestamps come from the board rather than from arrival, because the link's round trip
is about 86 ms against a 2 ms sample period. At about 6.5 kB/s of samples against
23 kB/s of link, none is lost to bandwidth.

Mode `w` holds the rotor, which is what makes its frequency the suspended mode the
manual publishes; a free arm would make it a coupled two-degree-of-freedom system. Take
several releases within one `w` capture; `furuta.freeswing` segments them. The other
modes drive the arm; run them supervised.

    uv run --with pyserial python scripts/capture_trace.py --mode b --auto-reset
"""

from __future__ import annotations

import argparse
import glob
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BAUD = 230400

# The menu firmware ends its mode prompt with this. Only the trailing colon proves the
# whole prompt arrived. USB CDC delivers the line in fragments, and writing before the
# firmware has armed its read drops the bytes silently.
MODE_PROMPT_TAIL = b"Seconds..:"

DEFAULT_MODE = "w"

# The logger's own header, echoed before the samples start. Each logging mode announces
# its columns this way. Mode w emits two columns, mode y three, and modes d, a, u, b and
# r five.
HEADER_MARKER = b"us\tcounts"

# A sample line: two to five tab-separated integers with an optional trailing state
# letter. Recognizes a board already logging after a previous capture left it in a
# logging mode. Without this the script would wait for a boot prompt that is never
# coming.
SAMPLE_LINE = re.compile(rb"^-?\d+(\t-?\d+){1,4}(\t[A-Za-z])?$")
MIN_SAMPLE_LINES = 5

# Where each mode's captures land under data/, and the build id its image announces.
FOLDERS = {
    "w": "freeswing",
    "y": "tilt",
    "d": "probe-pump",
    "a": "probe-lean",
    "u": "probe-trace",
    "b": "rl-balance",
    "r": "rl-swingup",
    "x": "showcase",
}
EXPECTED_BUILD = {
    "w": "bench",
    "y": "ident",
    "d": "ident",
    "a": "ident",
    "u": "ident",
    "b": "rl",
    "r": "rl",
    "x": "showcase",
}


def find_port(explicit: str | None) -> str:
    """Return the serial device for the board, or exit when none is found."""
    if explicit:
        return explicit
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("No /dev/cu.usbmodem* found. Connect the board and try again.")
    return ports[0]


def reset_board() -> None:
    """Reset the target through the on-board debugger, so an autostart image reboots."""
    if shutil.which("st-flash") is None:
        sys.exit("--auto-reset needs st-flash on PATH (the stlink package)")
    result = subprocess.run(["st-flash", "reset"], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"st-flash reset failed:\n{result.stderr.strip()}")


def main() -> int:
    """Enter the mode, then stream the log to a file until time runs out."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", default=None)
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        help=(
            "boot mode to enter: w free swing, y tilt sweep, d ring-down, "
            "a lean, u the stock swing-up, b the RL balance policy, "
            "r the RL swing-up image (at a boot prompt, r is direct rotor control), "
            "x the showcase carousel"
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output path; defaults to data/<mode folder>/<timestamp>.tsv",
    )
    parser.add_argument(
        "--auto-reset",
        action="store_true",
        help="reset the board through st-flash once the port is open, for autostart "
        "images that print no prompt",
    )
    args = parser.parse_args()

    import serial

    port = find_port(args.port)
    folder = FOLDERS.get(args.mode, "capture")
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
    if args.auto_reset:
        link.reset_input_buffer()
        reset_board()
        print("[reset] board reset through st-flash")
    else:
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
                sink.flush()  # readable while it runs, and intact after a kill
                samples += data.count(b"\n")
                print(f"\r[rec ] {samples} lines", end="", flush=True)
                continue

            # Check the whole buffer before trimming it. Once the logger starts, one
            # read returns several kilobytes, and trimming first would discard the
            # header off the front and the capture would wait forever for it.
            buffer = recent + data

            if b"BUILD " in buffer and build is None:
                tail = buffer.split(b"BUILD ", 1)[1]
                build = tail.split(b" ", 1)[0].decode("ascii", "replace").strip()
                print(f"[build] board reports {build!r}")
                # The showcase's record is its SHOWCASE lines from boot on: the carousel
                # can wait at its selector indefinitely, a sample header follows only a
                # learned attempt, and a stock attempt prints none.
                if args.mode == "x":
                    sink.write(buffer)
                    streaming = True
                    deadline = time.time() + args.seconds
                    print(f"[rec ] streaming {args.seconds:.0f}s from boot")
                    continue
            if b"AUTOSTART mode " in buffer:
                letter = buffer.split(b"AUTOSTART mode ", 1)[1][:1].decode(
                    "ascii", "replace"
                )
                print(f"[boot ] autostart mode {letter!r}")

            if HEADER_MARKER in buffer:
                sink.write(buffer.split(HEADER_MARKER, 1)[1].lstrip(b"\r\n"))
                streaming = True
                deadline = time.time() + args.seconds
                print(f"[rec ] streaming {args.seconds:.0f}s")
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

    link.close()
    print()
    if not streaming:
        print(
            f"[fail] never reached the sample header. Was mode {args.mode!r} entered?"
        )
        return 1
    print(f"[done] {samples} lines to {out}")
    expected = EXPECTED_BUILD.get(args.mode)
    if build is not None and expected is not None and build != expected:
        print(
            f"[warn] board reported build {build!r}, expected {expected!r} "
            f"for mode {args.mode!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

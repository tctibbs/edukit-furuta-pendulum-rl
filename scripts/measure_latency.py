"""Measure the serial command-and-reply round trip.

The question is whether a policy on the workstation could close the balance loop over
this link, against a 2 ms budget.

The stock firmware runs its own 500 Hz loop and takes no per-cycle command from the
host, so "host commands, host observes" cannot be timed directly. The round trip at a
prompt can be. The firmware echoes each character it receives, and the interval between
writing a byte and seeing it return is one full host to board to host traversal.

That interval is USB CDC latency plus the firmware's service interval. At 230400 baud a
byte is about 43 microseconds on the wire, so anything in the millisecond range is
scheduling. Samples come from the boot prompt chain, which offers several prompts per
reset.

    uv run --with pyserial python scripts/measure_latency.py --mode 1
"""

from __future__ import annotations

import argparse
import glob
import statistics
import sys
import time

BAUD = 230400

# The firmware ends every prompt with a colon and a space. Matching that is how the
# script knows a write will be answered.
PROMPT_TAIL = b": "


def find_port(explicit: str | None) -> str:
    """Return the serial device for the board, or exit when none is found."""
    if explicit:
        return explicit
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("No /dev/cu.usbmodem* found. Connect the board and try again.")
    return ports[0]


def summarise(name: str, samples: list[float]) -> None:
    """Print the distribution of a set of millisecond timings."""
    if not samples:
        print(f"  {name}: no samples")
        return
    ordered = sorted(samples)
    percentile95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    print(
        f"  {name}: n={len(ordered)}  "
        f"min={ordered[0]:.2f}  median={statistics.median(ordered):.2f}  "
        f"p95={percentile95:.2f}  max={ordered[-1]:.2f}  (ms)"
    )


def main() -> int:
    """Drive the prompt chain, timing each echo, and report the distribution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=None)
    parser.add_argument(
        "--mode",
        default="1",
        help="mode to enter, whose prompt chain supplies the samples",
    )
    parser.add_argument("--seconds", type=float, default=90.0)
    parser.add_argument("--reply", default="\r", help="what to send at each prompt")
    args = parser.parse_args()

    import serial

    port = find_port(args.port)
    try:
        link = serial.Serial(port, BAUD, timeout=0.02)
    except OSError as error:
        sys.exit(
            f"Could not open {port}: {error}\n"
            f"If a stale process holds it: lsof -t {port} | xargs -r kill -9"
        )

    print(f"[port] {port} at {BAUD} 8N1")
    print("[action] press the physical reset button now")

    echo_ms: list[float] = []
    settle_ms: list[float] = []
    deadline = time.time() + args.seconds
    recent = b""
    entered = False

    while time.time() < deadline:
        try:
            data = link.read(4096)
        except OSError as error:
            # Opening the port can succeed while a stale process still holds it. The
            # failure then surfaces mid-loop and takes the same fix as at open.
            sys.exit(
                f"\nLost the port mid-read: {error}\n"
                f"A stale process is probably still attached. Clear it and rerun:\n"
                f"  lsof -t {port} | xargs -r kill -9"
            )
        if data:
            recent = (recent + data)[-200:]
            continue
        # A quiet link with a prompt at the end means the firmware is waiting for input.
        if not recent.rstrip(b" ").endswith(PROMPT_TAIL.rstrip(b" ")):
            continue

        payload = (args.mode + "\r").encode() if not entered else args.reply.encode()
        entered = True

        link.reset_input_buffer()
        sent_at = time.perf_counter()
        link.write(payload)
        link.flush()

        # The first byte back is the echo.
        first = None
        while time.perf_counter() - sent_at < 1.0:
            chunk = link.read(1)
            if chunk:
                first = time.perf_counter()
                break
        if first is None:
            recent = b""
            continue
        echo_ms.append((first - sent_at) * 1000.0)

        # The full exchange runs until the firmware has been quiet for 250 ms.
        last_seen = time.perf_counter()
        tail = b""
        while time.perf_counter() - last_seen < 0.25:
            chunk = link.read(4096)
            if chunk:
                tail += chunk
                last_seen = time.perf_counter()
        settle_ms.append((last_seen - sent_at) * 1000.0)
        recent = tail[-200:]

    link.close()

    print()
    summarise("echo round trip   ", echo_ms)
    summarise("full exchange     ", settle_ms)
    if echo_ms:
        budget = 2.0
        median = statistics.median(echo_ms)
        verdict = "within" if median <= budget else "over"
        print(
            f"\n  The budget is {budget:.0f} ms per control period at 500 Hz. "
            f"The median echo is {verdict} it."
        )
        print("  A single byte at 230400 baud is 0.043 ms on the wire. The rest is")
        print("  USB scheduling and the firmware's service interval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

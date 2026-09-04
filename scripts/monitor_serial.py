"""Watch the Edukit's serial output, optionally answering the boot mode prompt.

The mode-selection window is five seconds and closes silently, after which the firmware
starts pendulum control and drives the motor. Resetting over SWD re-enumerates the USB
serial device and reopening the port takes longer than the window, so a mode cannot be
chosen that way. This script holds the port open across a reset and answers after the
physical reset button is pressed.

An entry is exactly two bytes, one character and one carriage return. The firmware acts
on a command only when it reads two bytes carrying a payload of one. A bare character is
a byte short, a carriage return with a newline a byte over. Both are ignored in silence
and the prompt times out into the default mode.

    uv run --with pyserial python scripts/monitor_serial.py --mode t --seconds 120
"""

from __future__ import annotations

import argparse
import glob
import sys
import time

# The firmware's own prompt text. The countdown is not announced on the wire. This
# prompt is the only cue that the window is open. USB CDC delivers the prompt in
# fragments. A substring can arrive before the firmware has finished printing the line
# and before it reaches its input read, and bytes written then are dropped. The trailing
# colon is the end of the prompt.
MODE_PROMPT_TAIL = b"Seconds..:"

BAUD = 230400


def find_port(explicit: str | None) -> str:
    """Return the serial device for the board, or exit when none is found."""
    if explicit:
        return explicit
    # The ST-LINK's virtual COM port appears under this pattern on macOS.
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit(
            "No /dev/cu.usbmodem* found. Check the USB cable carries data rather "
            "than only power, and that it is plugged straight in rather than via a hub."
        )
    return ports[0]


def main() -> int:
    """Stream the port, answering the mode prompt when asked to."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=None, help="override the detected port")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument(
        "--mode",
        default=None,
        help="answer the boot prompt with this mode, for example t, r, 1 or g",
    )
    args = parser.parse_args()

    import serial

    port = find_port(args.port)
    try:
        link = serial.Serial(port, BAUD, timeout=0.1)
    except OSError as error:
        # A stale process holding the port reports as a disconnect.
        sys.exit(
            f"Could not open {port}: {error}\n"
            f"If another process holds it: lsof -t {port} | xargs -r kill -9"
        )

    print(f"[port] {port} at {BAUD} 8N1")
    if args.mode:
        print(f"[mode] answering {args.mode!r} at the prompt. Press reset now")

    deadline = time.time() + args.seconds
    recent = b""
    answered = False
    last_heartbeat = time.time()
    while time.time() < deadline:
        try:
            data = link.read(4096)
        except OSError as error:
            print(f"[error] {error}", flush=True)
            break
        if not data:
            # Silence on the wire looks identical to a hang, and the board can sit quiet
            # for a while inside a boot sequence.
            if time.time() - last_heartbeat > 10:
                remaining = int(deadline - time.time())
                print(f"[waiting] no data yet, {remaining}s left", flush=True)
                last_heartbeat = time.time()
            continue
        last_heartbeat = time.time()
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()
        if args.mode and not answered:
            # The 400-byte window excludes a prompt printed by an earlier boot.
            recent = (recent + data)[-400:]
            if recent.rstrip(b" ").endswith(MODE_PROMPT_TAIL):
                # `main.c` acts on a command only when `readBytes == 2 && Msg.Len == 1`.
                link.write(args.mode.encode() + b"\r")
                link.flush()
                answered = True
                print(f"\n[sent] {args.mode!r}", flush=True)
    link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

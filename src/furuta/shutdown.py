"""Guarantee an Isaac Sim process exits, so it stops holding the GPU.

`SimulationApp.close()` does not reliably return. When it hangs the script never reaches
its own exit, the process stays alive holding a CUDA context, and every later run shares
the GPU with it. The run prints its results and only hangs on the way out, so it looks
finished.

Four such processes, left from two earlier sessions, were alive when a training run
started. That run collected at 755 ms per control step against the 40 ms the same
environment benchmarks at on a clear GPU: eleven hours for 400 iterations instead of
forty minutes.

Stdlib only, so a script can import it before launching Kit.
"""

from __future__ import annotations

import os
import sys
import threading

CLOSE_TIMEOUT_S = 30.0
"""How long to let Kit shut down cleanly before the process is ended anyway."""


def close_and_exit(
    simulation_app, code: int = 0, timeout: float = CLOSE_TIMEOUT_S
) -> None:
    """Close Kit and exit with `code`, whether or not the close returns.

    The watchdog is armed before the close, because the hang is inside `close()` and
    anything written after that call would never run. The exit is `os._exit` rather than
    `sys.exit`: interpreter teardown is the part that is stuck.

    Nothing may be printed after this is called. Kit discards buffered stdout on close,
    so a caller that wants its last line seen has to flush it before calling.
    """

    def give_up() -> None:
        print(
            f"[warn ] Kit did not shut down within {timeout:.0f}s, ending the process "
            "so it stops holding the GPU",
            file=sys.stderr,
            flush=True,
        )
        os._exit(code)

    watchdog = threading.Timer(timeout, give_up)
    watchdog.daemon = True
    watchdog.start()
    try:
        simulation_app.close()
    finally:
        watchdog.cancel()
        os._exit(code)

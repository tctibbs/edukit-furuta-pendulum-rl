"""Shared fixtures: the host C compiler the board harnesses are built with."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

# The board code's own warning flags, and -ffp-contract=off, which keeps a * b + c as
# two rounded float operations rather than one fused multiply-add. The firmware build
# passes it too (scripts/build_firmware.sh). With it, the arithmetic the harnesses test
# is the arithmetic that is flashed, libm aside.
HARNESS_FLAGS = (
    "-std=c99",
    "-O2",
    "-ffp-contract=off",
    "-Wall",
    "-Wextra",
    "-Werror",
)


@pytest.fixture(scope="session")
def c_compiler() -> list[str]:
    """The host C compiler: $CC when set, else cc, clang or gcc from PATH.

    With none present the board harness tests skip, or fail when CI is set. A machine
    without a compiler then cannot report them passed.
    """
    candidates = [shlex.split(os.environ["CC"])] if os.environ.get("CC") else []
    candidates += [["cc"], ["clang"], ["gcc"]]
    for command in candidates:
        path = shutil.which(command[0])
        if path is not None:
            return [path, *command[1:]]
    message = "no C compiler ($CC, cc, clang or gcc), and the board harnesses need one"
    if os.environ.get("CI"):
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="session")
def build_harness(
    c_compiler: list[str], tmp_path_factory: pytest.TempPathFactory
) -> Callable[[str, Sequence[Path], Sequence[str]], Path]:
    """Compiles board sources into a host executable named `name`; any warning fails."""

    def build(name: str, sources: Sequence[Path], extra: Sequence[str] = ()) -> Path:
        exe = tmp_path_factory.mktemp(name) / name
        result = subprocess.run(
            [
                *c_compiler,
                *HARNESS_FLAGS,
                *extra,
                *(str(source) for source in sources),
                "-lm",
                "-o",
                str(exe),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.fail(f"the {name} harness did not compile:\n{result.stderr}")
        return exe

    return build

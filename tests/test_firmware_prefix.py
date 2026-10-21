"""Tests for the firmware makefile prefix rewrite.

Each test builds a small stand-in of the firmware tree under a temporary repository,
with makefile text in the shapes the generated project uses, and checks that the rewrite
points every absolute path at that repository exactly once.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "firmware_prefix", ROOT / "scripts" / "firmware_prefix.py"
)
firmware_prefix = importlib.util.module_from_spec(SPEC)
# Registered before it runs: a dataclass looks its module up in sys.modules.
sys.modules[SPEC.name] = firmware_prefix
SPEC.loader.exec_module(firmware_prefix)

ANCHOR = firmware_prefix.ANCHOR
PROJECT = "Projects/Multi/Examples/MotionControl/IHM01A1_ExampleFor1Motor"


def make_repo(root: Path, name: str) -> tuple[Path, Path]:
    """A repository folder with the firmware tree's shape.

    It holds a source file and a Debug dir.
    """
    repo = root / name
    tree = repo / ANCHOR.strip("/")
    (tree / PROJECT / "Src").mkdir(parents=True)
    (tree / PROJECT / "Inc").mkdir(parents=True)
    (tree / PROJECT / "Src" / "main.c").write_text("int main(void) { return 0; }\n")
    (tree / "Drivers" / "BSP" / "Components" / "l6474").mkdir(parents=True)
    (tree / "Drivers" / "BSP" / "Components" / "l6474" / "l6474.c").write_text("\n")
    (tree / PROJECT / "LinkerScript.ld").write_text("\n")
    debug = tree / PROJECT / "SW4STM32" / "STM32F401RE-Nucleo" / "Debug"
    (debug / "Drivers" / "BSP" / "Components" / "l6474").mkdir(parents=True)
    return repo.resolve(), debug


def subdir_mk(prefix: str) -> str:
    """A `subdir.mk` rule in the generated project's shape."""
    return (
        f"C_SRCS += \\\n{prefix}{ANCHOR}Drivers/BSP/Components/l6474/l6474.c\n\n"
        "Drivers/BSP/Components/l6474/l6474.o: "
        f"{prefix}{ANCHOR}Drivers/BSP/Components/l6474/l6474.c\n"
        f'\tarm-none-eabi-gcc -I"{prefix}{ANCHOR}{PROJECT}/Inc" -c "$<"\n'
    )


def makefile(prefix: str) -> str:
    """The top makefile's link line, with the quoted `-T"..."` linker script."""
    return (
        '\tarm-none-eabi-gcc -o "out.elf" '
        f'-T"{prefix}{ANCHOR}{PROJECT}/LinkerScript.ld" -lc\n'
    )


def test_rewrites_a_foreign_prefix_to_the_repository(tmp_path: Path) -> None:
    """The main checkout's prefix in a worktree becomes the worktree's."""
    repo, debug = make_repo(tmp_path, "furuta-worktree")
    (debug / "makefile").write_text(makefile("/build-machine/Code/furuta"))
    report = firmware_prefix.rewrite(debug, repo)
    text = (debug / "makefile").read_text()
    assert f'-T"{repo}{ANCHOR}{PROJECT}/LinkerScript.ld"' in text
    assert report.prefixes == frozenset({str(repo)})
    assert report.files_rewritten == 1


def test_is_idempotent(tmp_path: Path) -> None:
    """A second run changes nothing: the prefix never grows."""
    repo, debug = make_repo(tmp_path, "furuta")
    (debug / "makefile").write_text(makefile("/elsewhere/furuta"))
    firmware_prefix.rewrite(debug, repo)
    first = (debug / "makefile").read_text()
    report = firmware_prefix.rewrite(debug, repo)
    assert (debug / "makefile").read_text() == first
    assert report.files_rewritten == 0


def test_a_folder_name_extending_the_old_one_is_not_doubled(tmp_path: Path) -> None:
    """A folder name that extends another is not doubled.

    `x-worktree` must not become `x-worktree-worktree`.
    """
    repo, debug = make_repo(tmp_path, "isaac-lab-furuta-pendulum-worktree")
    (debug / "makefile").write_text(makefile(str(repo)))
    firmware_prefix.rewrite(debug, repo)
    firmware_prefix.rewrite(debug, repo)
    assert "-worktree-worktree" not in (debug / "makefile").read_text()


def test_reaches_nested_subdir_mk_and_dependency_files(tmp_path: Path) -> None:
    """The l6474 `subdir.mk`, three levels down, and its `.d` file.

    Both carry the dead prefix.
    """
    repo, debug = make_repo(tmp_path, "furuta")
    nested = debug / "Drivers" / "BSP" / "Components" / "l6474"
    (nested / "subdir.mk").write_text(
        subdir_mk("/build-machine/Code/RL/isaac-lab-furuta-pendulum")
    )
    (nested / "l6474.d").write_text(
        f"Drivers/BSP/Components/l6474/l6474.o: \\\n"
        " /build-machine/Code/RL/isaac-lab-furuta-pendulum"
        f"{ANCHOR}Drivers/BSP/Components/l6474/l6474.c\n"
    )
    report = firmware_prefix.rewrite(debug, repo)
    assert report.files_rewritten == 2
    for path in (nested / "subdir.mk", nested / "l6474.d"):
        assert "Code/RL" not in path.read_text()
        assert firmware_prefix.prefixes_in(path.read_text()) == {str(repo)}


def test_two_prefixes_in_one_file_both_move(tmp_path: Path) -> None:
    """A file carrying the old and the current prefix.

    It ends with only this repository's.
    """
    repo, debug = make_repo(tmp_path, "furuta")
    (debug / "subdir.mk").write_text(
        subdir_mk("/a/furuta") + subdir_mk("/b/other/place")
    )
    firmware_prefix.rewrite(debug, repo)
    assert firmware_prefix.prefixes_in((debug / "subdir.mk").read_text()) == {str(repo)}


def test_refuses_a_symlinked_firmware_tree(tmp_path: Path) -> None:
    """Rewriting through a link would edit the checkout it points at."""
    real, _ = make_repo(tmp_path, "real")
    repo = tmp_path / "linked"
    repo.mkdir()
    (repo / "firmware").symlink_to(real / "firmware")
    debug = (
        repo / ANCHOR.strip("/") / PROJECT / "SW4STM32" / "STM32F401RE-Nucleo" / "Debug"
    )
    with pytest.raises(firmware_prefix.PrefixError, match="symlink"):
        firmware_prefix.rewrite(debug, repo)


def test_reports_a_referenced_path_that_does_not_exist(tmp_path: Path) -> None:
    """A rewrite that lands on a missing source fails loudly.

    It does not build stale.
    """
    repo, debug = make_repo(tmp_path, "furuta")
    (debug / "subdir.mk").write_text(f"x.o: /old{ANCHOR}Drivers/not_there.c\n")
    with pytest.raises(firmware_prefix.PrefixError, match="do not exist"):
        firmware_prefix.rewrite(debug, repo)

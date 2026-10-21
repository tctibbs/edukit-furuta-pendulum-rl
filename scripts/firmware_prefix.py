"""Point the generated firmware makefiles at this checkout's firmware tree.

The STM32 project's makefiles and dependency files carry absolute paths from whichever
machine or folder generated them, and not all of them the same one: the l6474 driver's
`subdir.mk` and `.d` files, four levels down, can carry a prefix the rest do not. A
build from a worktree, or from any folder whose name extends another checkout's, needs
every one of them rewritten, and rewritten exactly once.

The rewrite is anchored on the firmware tree's own location inside the repository, not
on the repository's folder name: whatever absolute prefix precedes
`/firmware/Edukit_Rotary_Inverted_Pendulum_Project/Edukit_Rotary_Inverted_Pendulum_Project/`
becomes this repository's resolved path. That is idempotent, works under any folder name
and at any depth, and repairs a foreign prefix as readily as a stale one.

    python3 scripts/firmware_prefix.py <Debug directory> <repository root>
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ANCHOR = (
    "/firmware/Edukit_Rotary_Inverted_Pendulum_Project/"
    "Edukit_Rotary_Inverted_Pendulum_Project/"
)

# An absolute path up to the anchor, stopping at anything that ends a make token: space,
# a quote, or the colon of a dependency rule.
PREFIX = re.compile(r"/[^\s\"':]*?" + re.escape(ANCHOR))

# The whole absolute path the anchor sits in, for the existence check.
FULL_PATH = re.compile(r"/[^\s\"':]*?" + re.escape(ANCHOR) + r"[^\s\"':\\]*")


class PrefixError(Exception):
    """The tree cannot be rewritten safely, or the rewrite did not converge."""


@dataclass(frozen=True)
class RewriteReport:
    """What a rewrite changed and what it found afterwards."""

    files_rewritten: int
    references: int
    prefixes: frozenset[str]


def build_files(debug: Path) -> list[Path]:
    """Every file make reads under the Debug directory: makefiles, `subdir.mk`, `.d`."""
    names = {"makefile", "subdir.mk"}
    return sorted(
        path
        for path in debug.rglob("*")
        if path.is_file() and (path.name in names or path.suffix == ".d")
    )


def rewrite_text(text: str, repo: Path) -> str:
    """The text with every firmware prefix replaced by `repo`."""
    target = str(repo) + ANCHOR
    return PREFIX.sub(lambda _: target, text)


def prefixes_in(text: str) -> set[str]:
    """The distinct absolute prefixes in front of the firmware anchor."""
    return {match.group(0)[: -len(ANCHOR)] for match in PREFIX.finditer(text)}


def check_tree(debug: Path, repo: Path) -> None:
    """Refuse a firmware tree that is a link, or a Debug directory outside the repo."""
    firmware = repo / "firmware"
    if firmware.is_symlink():
        raise PrefixError(
            f"{firmware} is a symlink; rewriting through it would edit another checkout"
        )
    try:
        debug.resolve().relative_to(repo.resolve())
    except ValueError as error:
        raise PrefixError(f"{debug} is not inside {repo}") from error


def rewrite(debug: Path, repo: Path) -> RewriteReport:
    """Rewrite every build file in place and verify the result.

    Afterwards exactly one prefix remains, this repository's, and every absolute path
    that carries it names a file that exists.
    """
    repo = repo.resolve()
    check_tree(debug, repo)
    changed = 0
    references = 0
    prefixes: set[str] = set()
    missing: set[str] = set()
    for path in build_files(debug):
        text = path.read_text()
        new = rewrite_text(text, repo)
        if new != text:
            path.write_text(new)
            changed += 1
        references += sum(1 for _ in PREFIX.finditer(new))
        prefixes |= prefixes_in(new)
        missing |= {
            full.group(0)
            for full in FULL_PATH.finditer(new)
            if not Path(full.group(0)).exists()
        }
    if prefixes - {str(repo)}:
        raise PrefixError(f"prefixes left after the rewrite: {sorted(prefixes)}")
    if missing:
        listed = "\n  ".join(sorted(missing)[:10])
        raise PrefixError(
            f"{len(missing)} referenced path(s) do not exist:\n  {listed}"
        )
    return RewriteReport(changed, references, frozenset(prefixes))


def main() -> int:
    """Rewrite the tree named on the command line and print what changed."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("debug", type=Path, help="the STM32 project's Debug directory")
    parser.add_argument(
        "repo", type=Path, help="the repository root the build runs from"
    )
    args = parser.parse_args()
    try:
        report = rewrite(args.debug, args.repo)
    except PrefixError as error:
        print(f"makefile prefix: {error}", file=sys.stderr)
        return 1
    print(
        f"makefile prefix: {report.files_rewritten} file(s) rewritten, "
        f"{report.references} references, all under this checkout"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# /// script
# requires-python = ">=3.11"
# dependencies = ["torch", "pyyaml"]
# ///
"""Generate the showcase carousel's table and its policies from config/showcase.yaml.

    uv run scripts/export_showcase.py
        write board/showcase_table.c and board/policies/
    uv run scripts/export_showcase.py --check
        regenerate elsewhere and compare, changing nothing

Every policy is exported through `export_policy.export_named`, so the header, the bound,
the squash and the test vectors come from the checkpoint the manifest names. `--check`
fails when a generated file differs from the committed one or when `board/policies/`
holds a policy the manifest no longer names.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_policy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "showcase.yaml"
TABLE = Path("board") / "showcase_table.c"
POLICIES = Path("board") / "policies"

KINDS = {
    "stock": "SHOWCASE_STOCK",
    "rl_balance": "SHOWCASE_RL_BALANCE",
    "rl_from_rest": "SHOWCASE_RL_FROM_REST",
    "probe": "SHOWCASE_PROBE",
    "stock_lqr": "SHOWCASE_STOCK_LQR",
}
PROBES = {
    "ringdown": "SHOWCASE_PROBE_RINGDOWN",
    "freeswing": "SHOWCASE_PROBE_FREESWING",
    "tilt": "SHOWCASE_PROBE_TILT",
}
LEARNED = {"rl_balance", "rl_from_rest"}
TITLE_MAX = 10  # drawn at scale 2 on a 128-pixel panel
LINE_MAX = 21  # characters on one line at scale 1
# The firmware keeps this many entries and drops any past them without a word.
MAX_ENTRIES = int(
    re.search(
        r"#define SHOWCASE_MAX_ENTRIES (\d+)",
        (ROOT / "board" / "showcase.h").read_text(),
    ).group(1)
)
# A swap pair's armed screen ends in "tap next" and "hold <partner>", one space apart
# on a 21-character line.
SWAP_TITLE_MAX = LINE_MAX - len("tap next") - len(" ") - len("hold ")


class ManifestError(Exception):
    """The manifest describes a table the firmware cannot carry."""


# Each field's YAML type. A number is an int or a float; YAML's true and false are not
# numbers here, though Python counts bool as an int.
FIELD_TYPES: dict[str, tuple[type, ...]] = {
    "title": (str,),
    "group": (int,),
    "kind": (str,),
    "main": (bool,),
    "variant": (bool,),
    "probe": (str,),
    "policy": (str,),
    "checkpoint": (str,),
    "accel_bound": (int, float),
    "squash_actions": (bool,),
    "fall_persist_cycles": (int,),
}
REQUIRED = ("title", "group", "kind")


@dataclass(frozen=True)
class Entry:
    """One carousel entry, as the manifest gives it."""

    title: str
    group: int
    kind: str
    main: bool = False
    variant: bool = False
    probe: str | None = None
    policy: str | None = None
    checkpoint: str | None = None
    accel_bound: float | None = None
    squash_actions: bool | None = None
    fall_persist_cycles: int = 0


def c_string(text: str) -> str:
    """A C string literal."""
    if any(ch in text for ch in '"\\') or not text.isascii():
        raise ManifestError(f"{text!r} needs escaping; keep titles to plain ASCII")
    return f'"{text}"'


def check_fields(item: dict) -> None:
    """One raw entry's field names and types."""
    known = {field.name for field in fields(Entry)}
    unknown = sorted(set(item) - known)
    if unknown:
        raise ManifestError(f"{item.get('title')}: unknown field {', '.join(unknown)}")
    missing = [name for name in REQUIRED if name not in item]
    if missing:
        raise ManifestError(f"{item.get('title')}: missing {', '.join(missing)}")
    for name, value in item.items():
        wanted = FIELD_TYPES[name]
        if not isinstance(value, wanted) or (
            isinstance(value, bool) and bool not in wanted
        ):
            kinds = " or ".join(kind.__name__ for kind in wanted)
            raise ManifestError(f"{item.get('title')}: {name} must be {kinds}")


def printable(text: str) -> bool:
    """Only characters the panel's font draws as themselves, 0x20 to 0x7E."""
    return all(0x20 <= ord(ch) <= 0x7E for ch in text)


def load(path: Path = MANIFEST) -> list[Entry]:
    """The manifest's entries, checked against what the firmware and the panel allow."""
    raw = yaml.safe_load(path.read_text())["entries"]
    if len(raw) > MAX_ENTRIES:
        raise ManifestError(
            f"{len(raw)} entries, over SHOWCASE_MAX_ENTRIES, {MAX_ENTRIES}"
        )
    for item in raw:
        check_fields(item)
    entries = [Entry(**item) for item in raw]
    titles = [e.title for e in entries]
    if len(titles) != len(set(titles)):
        raise ManifestError(f"a title is used twice: {titles}")
    groups = [e.group for e in entries]
    if sorted(set(groups)) != list(range(1, max(groups) + 1)):
        raise ManifestError(f"groups must be numbered from 1 without gaps: {groups}")
    if groups != sorted(groups):
        raise ManifestError(f"a group's entries must sit together, in order: {groups}")
    for group in set(groups):
        check_group(group, [e for e in entries if e.group == group])
    for item, e in zip(raw, entries, strict=True):
        if not e.title or not printable(e.title):
            raise ManifestError(f"title {e.title!r} must be printable ASCII")
        if len(e.title) > TITLE_MAX:
            raise ManifestError(f"title {e.title!r} is over {TITLE_MAX} characters")
        if e.kind not in KINDS:
            raise ManifestError(f"{e.title}: unknown kind {e.kind!r}")
        if "fall_persist_cycles" in item and e.kind not in LEARNED:
            raise ManifestError(
                f"{e.title}: only a learned entry carries fall_persist_cycles"
            )
        if e.fall_persist_cycles < 0:
            raise ManifestError(f"{e.title}: fall_persist_cycles must not be negative")
        learned_fields = (e.policy, e.checkpoint, e.accel_bound, e.squash_actions)
        if e.kind in LEARNED and None in learned_fields:
            raise ManifestError(
                f"{e.title}: a learned entry needs policy, checkpoint, accel_bound"
                " and squash_actions"
            )
        if e.kind not in LEARNED and any(v is not None for v in learned_fields):
            raise ManifestError(f"{e.title}: only a learned entry carries a policy")
        if e.kind == "probe" and e.probe not in PROBES:
            raise ManifestError(
                f"{e.title}: a probe entry needs probe: one of {', '.join(PROBES)}"
            )
        if e.kind != "probe" and e.probe is not None:
            raise ManifestError(f"{e.title}: only a probe entry names a probe")
    names = [e.policy for e in entries if e.policy]
    if len(names) != len(set(names)):
        raise ManifestError(f"a policy name is used twice: {names}")
    return entries


def check_group(group: int, members: list[Entry]) -> None:
    """One group's shape: its main entry first, then one variant or its history.

    The group's rows sit together in table order, so a variant, the only row after its
    main entry, is the row right after it. Hardware tests share a group only with each
    other, and the armed screens call the rest of a test's group tests.
    """
    if sum(e.main for e in members) != 1:
        raise ManifestError(f"group {group} needs exactly one main entry")
    if not members[0].main:
        raise ManifestError(f"group {group}'s main entry must come first")
    tests = [e.kind == "probe" for e in members]
    if any(tests) and not all(tests):
        raise ManifestError(f"group {group} mixes hardware tests and controllers")
    variants = [e for e in members if e.variant]
    history = [e for e in members if not e.main and not e.variant]
    if any(e.main and e.variant for e in members):
        raise ManifestError(f"group {group}: a variant is not a main entry")
    if not variants:
        return
    if len(variants) > 1:
        raise ManifestError(f"group {group} has more than one variant")
    if history:
        raise ManifestError(f"group {group} has a variant and history; pick one")
    for e in (members[0], variants[0]):
        if len(e.title) > SWAP_TITLE_MAX:
            raise ManifestError(
                f"title {e.title!r} is over {SWAP_TITLE_MAX} characters, the limit"
                " for a main entry and its variant"
            )


def table_source(entries: list[Entry]) -> str:
    """`board/showcase_table.c` for these entries."""
    includes = [f'#include "policies/{e.policy}.h"' for e in entries if e.policy]
    rows = []
    for e in entries:
        policy = f"&policy_{e.policy}" if e.policy else "NULL"
        probe = PROBES[e.probe] if e.probe else "SHOWCASE_PROBE_NONE"
        rows.append(
            f"    {{{c_string(e.title)}, {e.group}, {int(e.main)}, {int(e.variant)}, "
            f"{KINDS[e.kind]}, {probe}, {policy}, {e.fall_persist_cycles}}},"
        )
    lines = [
        (
            "/* Generated by scripts/export_showcase.py from config/showcase.yaml;"
            " do not edit. */"
        ),
        '#include "showcase_table.h"',
        "",
        "#include <stddef.h>",
        "",
        *includes,
        "",
        "const showcase_entry_t showcase_entries[] = {",
        *rows,
        "};",
        "",
        "const uint8_t showcase_entry_count =",
        "    (uint8_t)(sizeof showcase_entries / sizeof showcase_entries[0]);",
        "",
    ]
    return "\n".join(lines)


def generate(root: Path, entries: list[Entry]) -> list[Path]:
    """Write the table and every policy under `root`; return the paths written."""
    written = []
    for e in entries:
        if e.policy is None:
            continue
        header, vectors = export_policy.export_named(
            ROOT / e.checkpoint,
            e.policy,
            float(e.accel_bound),
            bool(e.squash_actions),
            root / POLICIES,
            tilt_range_deg=180.0 if e.kind == "rl_from_rest" else 20.0,
        )
        written += [header, vectors]
    table = root / TABLE
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(table_source(entries))
    written.append(table)
    return written


def check(entries: list[Entry]) -> list[str]:
    """What differs between a fresh generation and the committed files."""
    problems = []
    with tempfile.TemporaryDirectory() as scratch:
        fresh_root = Path(scratch)
        for fresh in generate(fresh_root, entries):
            relative = fresh.relative_to(fresh_root)
            committed = ROOT / relative
            if not committed.exists():
                problems.append(f"{relative} is missing")
            elif committed.read_bytes() != fresh.read_bytes():
                problems.append(f"{relative} is stale")
    wanted = {
        f"{e.policy}{suffix}" for e in entries if e.policy for suffix in (".h", ".json")
    }
    for path in sorted((ROOT / POLICIES).glob("*")):
        if path.name not in wanted:
            problems.append(f"{POLICIES / path.name} is not in the manifest")
    return problems


def main() -> int:
    """Generate, or check what is committed."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="compare only; write nothing"
    )
    args = parser.parse_args()
    try:
        entries = load()
    except ManifestError as error:
        print(f"config/showcase.yaml: {error}", file=sys.stderr)
        return 1
    if args.check:
        problems = check(entries)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"showcase table: {'stale' if problems else 'current'}")
        return 1 if problems else 0
    for path in generate(ROOT, entries):
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Flash a firmware image, skipping the write when the board already carries it.

Targets are declared in `config/firmware.yaml`.

This board arrived running a third-party stepper console. The script reads the flash and
saves the dump before overwriting, because no other copy of that image is known.

Detecting "already flashed" means reading the flash back and comparing bytes. Nothing
reports the running image over ST-LINK: images built here print a `BUILD` identifier at
startup, but reading it needs the serial link this script does not open, and the ST-LINK
mass-storage volume exposes only its own scratch area.

    uv run --with pyyaml python scripts/flash_firmware.py --list
    uv run --with pyyaml python scripts/flash_firmware.py --target edukit
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFIG = Path("config/firmware.yaml")
BACKUP_DIR = Path("docs/reference/firmware-backup")

# A valid image opens with an initial stack pointer into SRAM and a reset vector into
# flash. Checking them catches a truncated or wrong-part file before it reaches the
# board.
SRAM_BASE = 0x20000000
SRAM_TOP = 0x20018000


@dataclass(frozen=True)
class Target:
    """One flashable image, as declared in the config file."""

    name: str
    path: Path
    description: str
    flash_base: int
    flash_size: int
    banner: str | None


def load_targets() -> tuple[dict[str, Target], str]:
    """Return every declared target and the name of the default one."""
    import yaml

    if not CONFIG.exists():
        sys.exit(f"{CONFIG} is missing.")
    raw: dict[str, Any] = yaml.safe_load(CONFIG.read_text())
    defaults = raw.get("defaults", {})
    targets = {}
    for name, spec in (raw.get("targets") or {}).items():
        targets[name] = Target(
            name=name,
            path=Path(spec["path"]),
            description=spec.get("description", ""),
            flash_base=int(spec.get("flash_base", defaults["flash_base"])),
            flash_size=int(spec.get("flash_size", defaults["flash_size"])),
            banner=spec.get("banner"),
        )
    if not targets:
        sys.exit(f"{CONFIG} declares no targets.")
    return targets, raw.get("default") or next(iter(targets))


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command and hand back its output for the failure message."""
    return subprocess.run(args, capture_output=True, text=True, check=False)


def probe() -> None:
    """Exit unless an ST-LINK and a target are both present."""
    result = _run(["st-info", "--probe"])
    if result.returncode != 0 or "Found 1 stlink" not in result.stdout:
        sys.exit(
            "No ST-LINK target found. Check the USB cable carries data rather than "
            "only power, and that it is plugged straight in rather than via a hub.\n"
            f"{result.stdout}{result.stderr}"
        )


def check_image(target: Target, image: bytes) -> None:
    """Reject a file whose vector table does not match the target's memory map."""
    if len(image) < 8:
        sys.exit(f"{target.path} is too small to be a firmware image.")
    stack_pointer = int.from_bytes(image[0:4], "little")
    reset_vector = int.from_bytes(image[4:8], "little")
    top = target.flash_base + target.flash_size
    if not (
        SRAM_BASE <= stack_pointer <= SRAM_TOP
        and target.flash_base <= reset_vector <= top
    ):
        sys.exit(
            f"{target.path} does not look like an image for this part: "
            f"stack pointer 0x{stack_pointer:08X}, reset 0x{reset_vector:08X}."
        )


def read_flash(target: Target, destination: Path, size: int) -> bytes:
    """Read the board's flash from its base, leaving a copy at `destination`."""
    result = _run(
        ["st-flash", "read", str(destination), hex(target.flash_base), hex(size)]
    )
    if result.returncode != 0:
        sys.exit(f"Could not read the board's flash.\n{result.stdout}{result.stderr}")
    return destination.read_bytes()


def back_up(target: Target) -> Path:
    """Dump the whole of flash to a timestamped file and return its path.

    The backup covers the full flash because whatever is on the board may be larger
    than the image about to be written.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUP_DIR / f"flash-{stamp}.bin"
    read_flash(target, destination, target.flash_size)
    return destination


def main() -> int:
    """Flash the selected target if needed, and report what was decided."""
    targets, default_name = load_targets()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=default_name, choices=sorted(targets))
    parser.add_argument("--list", action="store_true", help="show declared targets")
    parser.add_argument(
        "--force",
        action="store_true",
        help="write even when the board already carries this image",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="skip dumping the existing image first",
    )
    args = parser.parse_args()

    if args.list:
        width = max(len(n) for n in targets)
        for name, target in sorted(targets.items()):
            mark = "*" if name == default_name else " "
            present = "" if target.path.exists() else "   [file missing]"
            print(f" {mark} {name:<{width}}  {target.description}{present}")
        print("\n * is the default")
        return 0

    target = targets[args.target]
    if not target.path.exists():
        sys.exit(
            f"{target.path} is missing. Reference images are git-ignored; "
            "repopulate them with `just docs-fetch`."
        )

    image = target.path.read_bytes()
    check_image(target, image)
    probe()
    print(f"[target] {target.name}: {target.path}, {len(image)} bytes")

    # Anything past the image is left over from whatever ran before.
    with tempfile.TemporaryDirectory() as tmp:
        current = read_flash(target, Path(tmp) / "current.bin", len(image))

    if current == image and not args.force:
        print("[skip] the board already carries this image, nothing written")
        return 0

    if current == image:
        print("[force] image matches but --force was given")

    if not args.no_backup:
        destination = back_up(target)
        print(f"[backup] existing flash saved to {destination}")

    result = _run(
        ["st-flash", "--reset", "write", str(target.path), hex(target.flash_base)]
    )
    print(result.stdout.strip() or result.stderr.strip())
    if result.returncode != 0:
        return 1

    # st-flash verifies its own write.
    print("[done] flashed and reset")
    if target.banner:
        print(f"[expect] the board should now print: {target.banner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

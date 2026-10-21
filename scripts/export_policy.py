# /// script
# requires-python = ">=3.11"
# dependencies = ["torch"]
# ///
r"""Export a trained balance policy's actor as a C header, with test vectors.

The board runs the actor and nothing else: a 5-32-32-1 multilayer perceptron with ELU
activations, reading the five observations the environment builds and emitting one
normalized action. This writes the weights as `static const float` arrays in the
row-major layout the board code expects (`board/policy.c`), and beside them a JSON file
of observation vectors with the outputs PyTorch computes for them, so the C forward can
be checked bit for bit within float tolerance before anything is flashed.

    uv run scripts/export_policy.py <run>/model_299.pt --no-squash-actions

with `--header` and `--vectors` naming the outputs, default `board/policy_weights.h` and
`board/policy_vectors.json`.

`--squash-actions` or `--no-squash-actions` is required, and it has to be whatever
`squash_actions` was in the task config the checkpoint was trained under: the
environment maps the action through `tanh` before the actuator when it is set
(`FurutaEnv._pre_physics_step`, src/furuta/env.py) and lets the actuator clamp it
otherwise, and the two differ by up to 24 percent of the bound, at a raw action of
magnitude 1. The checkpoint does not record it, so the caller has to. The balance tasks
leave it off, and the swing-up task (`FurutaSwingUpEnvCfg` in src/furuta/tasks.py)
turns it on. The header carries the answer as `POLICY_SQUASH_ACTIONS`, and
`policy_command` in board/policy.c follows it.

The showcase build carries several policies at once. `--name` exports one under its own
name instead, into `board/policies/<name>.h` and `<name>.json` (or `--out-dir`): arrays
prefixed with the name, a `policy_t` carrying the bound and the squash for
`policy_command_with`, and vectors that record both with the checkpoint's MD5.
`--accel-bound` is required with it. `scripts/export_showcase.py` calls `export_named`
for every policy in config/showcase.yaml. Without `--name` the output is the single
default policy, `board/policy_weights.h` and `board/policy_vectors.json`.

The checkpoint is rsl_rl's `model_state_dict`; only the `actor.*` tensors are read. The
exploration `std` is not exported: the board runs the mean action, as evaluation does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import torch

LAYERS = ("actor.0", "actor.2", "actor.4")
NUM_OBS = 5
HIDDEN = 32  # POLICY_HIDDEN in board/policy.h, which every named policy must match
POLICY_DIR = Path("board/policies")
NAME = re.compile(r"[a-z][a-z0-9_]*")


def elu(x: torch.Tensor) -> torch.Tensor:
    """ELU with alpha 1, the activation rsl_rl's ActorCritic was built with."""
    return torch.where(x > 0, x, torch.expm1(x))


def forward(state: dict[str, torch.Tensor], obs: torch.Tensor) -> torch.Tensor:
    """The actor's mean action, as float32, layer by layer."""
    x = obs.to(torch.float32)
    for i, name in enumerate(LAYERS):
        x = x @ state[f"{name}.weight"].T + state[f"{name}.bias"]
        if i < len(LAYERS) - 1:
            x = elu(x)
    return x.squeeze(-1)


def c_literal(value: float) -> str:
    """A float constant with nine significant digits, always a valid C token.

    `%.9g` drops the point from an integer-valued number, and `1f` is not a floating
    constant in C: clang reads it as a decimal integer with a stray suffix. A point is
    put back whenever the text has neither a point nor an exponent.
    """
    if not math.isfinite(value):
        raise ValueError(
            f"non-finite weight {value!r} cannot be written as a C constant"
        )
    text = f"{value:.9g}"
    if "." not in text and "e" not in text:
        text += ".0"
    return text + "f"


def c_array(name: str, values: torch.Tensor, per_line: int = 8) -> str:
    """One `static const float` array, row-major, nine significant digits."""
    flat = [c_literal(v) for v in values.flatten().tolist()]
    rows = [", ".join(flat[i : i + per_line]) for i in range(0, len(flat), per_line)]
    body = ",\n    ".join(rows)
    return f"static const float {name}[{values.numel()}] = {{\n    {body}\n}};\n"


def load_actor(path: str | Path) -> tuple[dict, dict[str, torch.Tensor], list[int]]:
    """The checkpoint, its actor tensors as float32, and the actor's layer widths."""
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    state = {
        k: v.to(torch.float32)
        for k, v in checkpoint["model_state_dict"].items()
        if k.startswith("actor.")
    }
    widths = [state[f"{n}.weight"].shape[0] for n in LAYERS]
    if state["actor.0.weight"].shape[1] != NUM_OBS or widths[-1] != 1:
        raise SystemExit(
            f"unexpected actor shape: {widths} from {NUM_OBS} observations"
        )
    return checkpoint, state, widths


def observations(count: int, seed: int, tilt_range_deg: float = 20.0) -> torch.Tensor:
    """Test vectors across the observation ranges the policy meets.

    Tilt within `tilt_range_deg` of upright, pendulum rate within 4 rad/s, arm within
    pi, arm rate within 8 rad/s.
    """
    generator = torch.Generator().manual_seed(seed)
    tilt = (torch.rand(count, generator=generator) * 2 - 1) * math.radians(
        tilt_range_deg
    )
    return torch.stack(
        [
            torch.cos(tilt),
            torch.sin(tilt),
            (torch.rand(count, generator=generator) * 2 - 1) * 4.0,
            (torch.rand(count, generator=generator) * 2 - 1) * math.pi,
            (torch.rand(count, generator=generator) * 2 - 1) * 8.0,
        ],
        dim=-1,
    )


def source_name(path: str | Path) -> str:
    """The checkpoint's last three path parts, the form headers and vectors record."""
    return "/".join(Path(path).parts[-3:])


def named_header(
    name: str,
    checkpoint: dict,
    state: dict[str, torch.Tensor],
    source: str,
    md5: str,
    accel_bound: float,
    squash_actions: bool,
) -> str:
    """The header for one named policy: its arrays and its `policy_t`."""
    guard = f"POLICY_{name.upper()}_H"
    arrays = [
        c_array(f"{name}_{suffix}", state[f"{layer}.{kind}"])
        for layer, pair in zip(
            LAYERS, (("w1", "b1"), ("w2", "b2"), ("w3", "b3")), strict=True
        )
        for kind, suffix in zip(("weight", "bias"), pair, strict=True)
    ]
    lines = [
        "/* Generated by scripts/export_policy.py; do not edit.",
        f" * Policy: {name}",
        f" * Source checkpoint: {source} (MD5 {md5})",
        f" * Iteration: {checkpoint.get('iter', 'unknown')}",
        (
            " * Layout: row-major, W[out][in]; ELU (alpha 1) after the first two"
            " layers; the"
        ),
        (
            " * last layer's single output is the normalized action, bounded to [-1, 1]"
            " by tanh"
        ),
        " * when `squash` is 1 and by a clamp when it is 0, then scaled by `a_max` in",
        " * rad/s^2. The exploration std is not exported. */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        '#include "policy.h"',
        "",
        *arrays,
        f"static const policy_t policy_{name} = {{",
        (
            f'    "{name}", {name}_w1, {name}_b1, {name}_w2, {name}_b2,'
            f" {name}_w3, {name}_b3,"
        ),
        f"    {c_literal(accel_bound)}, {int(squash_actions)},",
        "};",
        "",
        f"#endif /* {guard} */",
        "",
    ]
    return "\n".join(lines)


def export_named(
    checkpoint_path: str | Path,
    name: str,
    accel_bound: float,
    squash_actions: bool,
    out_dir: Path = POLICY_DIR,
    count: int = 64,
    seed: int = 0,
    tilt_range_deg: float = 20.0,
) -> tuple[Path, Path]:
    """Write `<name>.h` and `<name>.json` into `out_dir` and return their paths."""
    if not NAME.fullmatch(name):
        raise SystemExit(f"policy name {name!r} is not a lower-case C identifier")
    checkpoint, state, widths = load_actor(checkpoint_path)
    if widths != [HIDDEN, HIDDEN, 1]:
        raise SystemExit(
            f"{name}: layer widths {widths}, the board expects {HIDDEN}, {HIDDEN}, 1"
        )
    md5 = hashlib.md5(Path(checkpoint_path).read_bytes()).hexdigest()
    source = source_name(checkpoint_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    header = out_dir / f"{name}.h"
    header.write_text(
        named_header(name, checkpoint, state, source, md5, accel_bound, squash_actions)
    )
    obs = observations(count, seed, tilt_range_deg)
    vectors = out_dir / f"{name}.json"
    vectors.write_text(
        json.dumps(
            {
                "name": name,
                "checkpoint": source,
                "checkpoint_md5": md5,
                "accel_bound": accel_bound,
                "squash_actions": bool(squash_actions),
                "tilt_range_deg": tilt_range_deg,
                "observations": obs.tolist(),
                "actions": forward(state, obs).tolist(),
            },
            indent=1,
        )
        + "\n"
    )
    return header, vectors


def export_default(args: argparse.Namespace) -> None:
    """The single default policy, `policy_weights.h` and its vectors."""
    checkpoint, state, widths = load_actor(args.checkpoint)
    source = source_name(args.checkpoint)
    lines = [
        "/* Generated by scripts/export_policy.py; do not edit.",
        f" * Source checkpoint: {source}",
        f" * Iteration: {checkpoint.get('iter', 'unknown')}",
        " * Layout: row-major, W[out][in]; ELU (alpha 1) after the first two layers;",
        " * the last layer's single output is the normalized action, bounded to",
        " * [-1, 1] by tanh when POLICY_SQUASH_ACTIONS is 1 and by a clamp when it is",
        " * 0, as the training task's `squash_actions` had it. The exploration std is",
        " * not exported. */",
        "#ifndef POLICY_WEIGHTS_H",
        "#define POLICY_WEIGHTS_H",
        "",
        f"#define POLICY_WEIGHTS_NUM_OBS {NUM_OBS}",
        f"#define POLICY_HIDDEN_1 {widths[0]}",
        f"#define POLICY_HIDDEN_2 {widths[1]}",
        f"#define POLICY_SQUASH_ACTIONS {int(args.squash_actions)}",
        "",
        c_array("POLICY_W1", state["actor.0.weight"]),
        c_array("POLICY_B1", state["actor.0.bias"]),
        c_array("POLICY_W2", state["actor.2.weight"]),
        c_array("POLICY_B2", state["actor.2.bias"]),
        c_array("POLICY_W3", state["actor.4.weight"]),
        c_array("POLICY_B3", state["actor.4.bias"]),
        "#endif /* POLICY_WEIGHTS_H */",
        "",
    ]
    header = Path(args.header)
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text("\n".join(lines))

    obs = observations(args.count, args.seed)
    out = forward(state, obs)
    vectors = Path(args.vectors)
    vectors.write_text(
        json.dumps(
            {
                "checkpoint": source,
                "squash_actions": bool(args.squash_actions),
                "observations": obs.tolist(),
                "actions": out.tolist(),
            },
            indent=1,
        )
        + "\n"
    )
    print(f"wrote {header} ({header.stat().st_size} bytes)")
    print(f"wrote {vectors} ({args.count} vectors)")
    lo, hi = out.min().item(), out.max().item()
    print(f"action range over the vectors: {lo:.3f} to {hi:.3f}")


def main() -> int:
    """Write the header and the test vectors."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkpoint")
    parser.add_argument("--header", default="board/policy_weights.h")
    parser.add_argument("--vectors", default="board/policy_vectors.json")
    parser.add_argument("--count", type=int, default=64, help="test vectors to write")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--squash-actions",
        action=argparse.BooleanOptionalAction,
        required=True,
        help=(
            "whether the training task set `squash_actions`, so the board maps the "
            "action through tanh (on) or clamps it to [-1, 1] (off) before scaling"
        ),
    )
    parser.add_argument(
        "--name", help="export as a named policy for the showcase table"
    )
    parser.add_argument(
        "--accel-bound", type=float, help="rad/s^2; required with --name"
    )
    parser.add_argument("--out-dir", type=Path, default=POLICY_DIR)
    parser.add_argument(
        "--tilt-range-deg",
        type=float,
        default=20.0,
        help="test vector tilt range from upright; 180 for a swing-up",
    )
    args = parser.parse_args()

    if args.name is None:
        export_default(args)
        return 0
    if args.accel_bound is None:
        parser.error("--accel-bound is required with --name")
    header, vectors = export_named(
        args.checkpoint,
        args.name,
        args.accel_bound,
        args.squash_actions,
        args.out_dir,
        args.count,
        args.seed,
        args.tilt_range_deg,
    )
    print(f"wrote {header} ({header.stat().st_size} bytes)")
    print(f"wrote {vectors} ({args.count} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

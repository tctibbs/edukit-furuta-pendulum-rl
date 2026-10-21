"""The constants experiment 02 ran on.

`config/edukit.yaml` changes as measurements land. Since this experiment its lengths
have been measured and its acceleration limit set to the firmware's. This experiment's
`config.yaml` pins the values it ran on, and they override the live file here.

`src/furuta/articulation.py` imports `pxr` from Isaac Sim and will not import here, so
its constants are read with `ast`.

The module draws nothing, so it is safe when the figure runner globs and runs it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

EXPERIMENT = Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[2]
ARTICULATION = ROOT / "src" / "furuta" / "articulation.py"


def module_constant(path: Path, name: str) -> float:
    """Read a literal module-level constant without importing the module."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return float(ast.literal_eval(node.value))
    raise LookupError(f"{name} not found in {path}")


def load_parameters():
    """Return the physical and interface constants as this experiment pinned them.

    The project is not installed as a package, so `src` goes on `sys.path` first. The
    pinned file keeps the rates under `environment`, with the loop rate named
    `control_rate_hz`.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from furuta.parameters import FurutaParameters

    pinned = yaml.safe_load((EXPERIMENT / "config.yaml").read_text())
    defaults = yaml.safe_load((ROOT / "config" / "edukit.yaml").read_text())
    environment = pinned["environment"]
    merged = {
        **defaults["geometry"],
        **defaults["dynamics"],
        **defaults["actuator"],
        **defaults["control"],
        **defaults["sensing"],
        **pinned["physical"],
        **pinned["actuator"],
        "physics_rate_hz": environment["physics_rate_hz"],
        "loop_rate_hz": environment["control_rate_hz"],
    }
    fields = FurutaParameters.__dataclass_fields__
    return FurutaParameters(**{k: v for k, v in merged.items() if k in fields})

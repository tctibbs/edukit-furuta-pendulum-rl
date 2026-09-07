"""Tests for the board-side policy and observer against the simulation's arithmetic.

The board reimplements two things the simulation also runs: the actor's forward pass,
and the observation pipeline that turns encoder counts and rotor microsteps into the
five numbers the actor reads. A policy transfers only if both reimplementations produce
what the simulation produced in training. These tests compile the C under `board/` into
a host harness and drive it against the Python references: the exporter's own float32
forward for the policy, and `furuta.estimator.VelocitySlopeEstimator` plus the
arithmetic of `FurutaEnv._get_observations` for the observer, with the constants read
from `config/edukit.yaml` as the simulation reads them.

The compiler is the system clang. Nothing here touches the firmware toolchain.
"""

from __future__ import annotations

import ast
import json
import math
import subprocess
from pathlib import Path

import pytest
import torch

from furuta.estimator import VelocitySlopeEstimator
from furuta.parameters import FurutaParameters

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "board"
CLANG = Path("/usr/bin/clang")
SOURCES = [BOARD / name for name in ("policy.c", "observer.c", "test_board.c")]

# The simulation's constants, from the file the simulation reads them from, so the
# reference below and the check on the harness's `constants` mode both move when
# `config/edukit.yaml` does and the board's copies in `observer.h` do not. The window
# is the one value not in that file.
PARAMS = FurutaParameters.from_yaml()
LOOP_RATE_HZ = PARAMS.loop_rate_hz
DT = PARAMS.control_dt_s
COUNTS_PER_REV = PARAMS.encoder_counts_per_rev
MICROSTEPS_PER_REV = PARAMS.microsteps_per_rev
RAD_PER_COUNT = PARAMS.rad_per_encoder_count
RAD_PER_MICROSTEP = PARAMS.rad_per_microstep


def velocity_window_from_source() -> int:
    """`FurutaEnvCfg.velocity_window`, parsed out of env.py rather than imported.

    The module imports Isaac Lab at the top, which is not installed where this test
    runs, so the class attribute is taken from the parsed source instead of a literal
    repeated here that nothing would keep in step.
    """
    tree = ast.parse((ROOT / "src" / "furuta" / "env.py").read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "FurutaEnvCfg"):
            continue
        for statement in node.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "velocity_window"
                for target in statement.targets
            ):
                return int(ast.literal_eval(statement.value))
    raise LookupError("FurutaEnvCfg.velocity_window not found in src/furuta/env.py")


WINDOW = velocity_window_from_source()

# The acceleration bound is a pure scale on the bounded action, so any value tests the
# bound; this is the one the simulation trains against.
A_MAX = PARAMS.max_acceleration_rad_s2

OBS_NAMES = ("cos_tilt", "sin_tilt", "pendulum_rate", "rotor_angle", "rotor_rate")

# The angles and their cosine and sine are computed the same way on both sides and
# differ by libm ulps, far inside 1e-5. The rates carry a difference that grows with
# the estimator's unwrapped angle: each side rounds its float32 accumulator to one ulp,
# 4.8e-7 rad near 2 pi, and the slope weights sum to 94 (rad/s)/rad in magnitude, so
# two independently rounded windows can differ by about 9e-5 rad/s where the fixture
# carries the count through a full turn (measured: 8.4e-5). 2e-4 leaves a factor of
# two over that and sits two orders under the defects the test exists to catch: a
# squared-offset sum off by one scales every rate by 0.3 percent, 0.05 rad/s at the
# fixture's 18 rad/s peak.
OBS_TOLERANCES = (1e-5, 1e-5, 2e-4, 1e-5, 2e-4)


@pytest.fixture(scope="module")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The host harness, built with the flags `board/README.md` quotes."""
    if not CLANG.exists():
        pytest.skip(f"{CLANG} is not present, and the board harness needs a C compiler")
    exe = tmp_path_factory.mktemp("board") / "test_board"
    build = subprocess.run(
        [
            str(CLANG),
            "-std=c99",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(str(source) for source in SOURCES),
            "-lm",
            "-o",
            str(exe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        pytest.fail(f"the board harness did not compile:\n{build.stderr}")
    return exe


@pytest.fixture(scope="module")
def vectors() -> dict:
    """The exporter's test vectors: observations and PyTorch's float32 actions."""
    return json.loads((BOARD / "policy_vectors.json").read_text())


@pytest.fixture(scope="module")
def constants(harness: Path) -> dict[str, int]:
    """The constants the harness was compiled with, from its `constants` mode."""
    result = subprocess.run(
        [str(harness), "constants"], capture_output=True, text=True, check=True
    )
    return {
        name: int(value)
        for name, value in (line.split() for line in result.stdout.splitlines())
    }


def run(harness: Path, mode: str, lines: list[str], *args: str) -> list[list[float]]:
    """Feed `lines` to one harness mode and parse each output line as floats."""
    result = subprocess.run(
        [str(harness), mode, *args],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return [[float(v) for v in line.split()] for line in result.stdout.splitlines()]


def observation_lines(vectors: dict) -> list[str]:
    """One line of five floats per vector. `repr` round-trips the float32 values."""
    return [" ".join(repr(v) for v in obs) for obs in vectors["observations"]]


# Constants.


def test_constants_match_the_simulation(
    constants: dict[str, int], vectors: dict
) -> None:
    """The board's compile-time constants are the simulation's.

    The observer carries its own copies of what `config/edukit.yaml` and
    `FurutaEnvCfg.velocity_window` hold. The equivalence test below reads the reference
    from those sources too, so a drift would fail it as well, but as a mismatch at some
    step; this names the constant that moved. The action bound is cross-checked between
    the header the harness compiled and the vectors file, so the two generated files
    are from the same export.
    """
    assert constants["OBSERVER_ENCODER_COUNTS_PER_REV"] == COUNTS_PER_REV
    assert constants["OBSERVER_MICROSTEPS_PER_REV"] == MICROSTEPS_PER_REV
    assert constants["OBSERVER_LOOP_RATE_HZ"] == LOOP_RATE_HZ
    assert constants["OBSERVER_WINDOW"] == WINDOW
    assert constants["OBSERVER_NUM_OBS"] == constants["POLICY_NUM_OBS"] == 5
    assert constants["POLICY_SQUASH_ACTIONS"] == int(vectors["squash_actions"])


# Policy.


def test_policy_forward_matches_the_exporter(harness: Path, vectors: dict) -> None:
    """The C forward reproduces PyTorch's float32 forward on the exported vectors.

    The exporter computes the actions layer by layer in float32, so the only slack is
    summation order and the libm's `expm1f`, which is what the tolerance covers.
    """
    got = run(harness, "policy", observation_lines(vectors))

    assert len(got) == len(vectors["actions"])
    for (action,), expected in zip(got, vectors["actions"], strict=True):
        assert action == pytest.approx(expected, abs=1e-5)


def test_policy_command_bounds_then_scales(
    harness: Path, vectors: dict, constants: dict[str, int]
) -> None:
    """`policy_command` is the simulation's action bound times `a_max`, nothing else.

    Which bound is fixed by `POLICY_SQUASH_ACTIONS` in the exported header: the
    actuator's `clamp(action, -1, 1)` for the balance tasks, `tanh(action)` for a task
    that set `squash_actions`. The expectation is built from the bound the harness
    reports it compiled with, so a swing-up export is checked against `tanh` and not
    against a clamp it never trained under. The exported vectors reach past 1 on some
    inputs and stay inside it on others, so both sides of the clamp, and both the
    linear and the compressed regions of `tanh`, are covered; the assertion on the
    split guards the fixture against a re-export that no longer does.
    """
    actions = vectors["actions"]
    saturated = sum(abs(a) > 1.0 for a in actions)
    assert 0 < saturated < len(actions), "vectors must reach past 1 and stay inside it"

    got = run(harness, "command", observation_lines(vectors), str(A_MAX))

    squash = constants["POLICY_SQUASH_ACTIONS"] == 1
    for (command,), action in zip(got, actions, strict=True):
        bounded = math.tanh(action) if squash else max(-1.0, min(1.0, action))
        assert command == pytest.approx(bounded * A_MAX, abs=A_MAX * 1e-5)


# Observer.


def smoothstep(x: float) -> float:
    """Cubic ease from 0 to 1 over [0, 1], flat at both ends."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def pose(t: float) -> tuple[float, float]:
    """Pendulum angle from hanging and rotor angle, radians, at time `t`.

    0 to 1 s: the pendulum swings from 169 degrees on one side through hanging to 169
    degrees on the other, so the tilt from upright crosses the +/-pi seam, while the
    rotor makes a small correcting move. 1 to 2 s: a damped wobble about upright, which
    carries the count past 1200 and back, while the rotor sweeps to 4.2 rad, past pi in
    microsteps. 2 to 3 s: the catch fails and the pendulum falls over the top, through
    hanging on the far side and into a ring-down there, which carries the continuous
    count past one full revolution. After 3 s: at rest, so the windows flush.
    """
    t = min(t, 3.0)
    if t < 1.0:
        pendulum = -2.95 * math.cos(math.pi * t)
        rotor = 0.4 * smoothstep(t)
    elif t < 2.0:
        s = t - 1.0
        wobble = (math.pi - 2.95) * math.cos(3.0 * math.pi * s) * (1.0 - smoothstep(s))
        pendulum = math.pi + wobble
        rotor = 0.4 + 3.8 * smoothstep(s)
    else:
        s = t - 2.0
        envelope = math.exp(-6.0 * s * s)
        pendulum = 2.0 * math.pi - math.pi * math.cos(2.0 * math.pi * s) * envelope
        rotor = 4.2
    return pendulum, rotor


def synthetic_trajectory(seconds: float = 4.0) -> list[tuple[int, int]]:
    """`(counts, microsteps)` at the loop rate, as the firmware's sources report."""
    samples = []
    for k in range(int(seconds * LOOP_RATE_HZ)):
        pendulum, rotor = pose(k * DT)
        samples.append(
            (round(pendulum / RAD_PER_COUNT), round(rotor / RAD_PER_MICROSTEP))
        )
    return samples


def modulo_one_revolution(samples: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The same motion from a count source that wraps at one revolution."""
    half = COUNTS_PER_REV // 2
    return [((c + half) % COUNTS_PER_REV - half, m) for c, m in samples]


def wrap_to_pi(angle: torch.Tensor) -> torch.Tensor:
    """Wrap into [-pi, pi]. A no-op under the cosine and sine, kept for fidelity."""
    return torch.remainder(angle + math.pi, 2.0 * math.pi) - math.pi


def reference_observations(samples: list[tuple[int, int]]) -> list[list[float]]:
    """What the simulation's pipeline computes for the count stream in `samples`.

    Mirrors `FurutaEnv._quantized_angles`, `_reset_idx`, and `_get_observations` in
    `src/furuta/env.py`: the count as float32 times the quantum, the estimators seeded
    flat at the first sample, then one update per sample and the stack
    `[cos(tilt), sin(tilt), pendulum_rate, rotor_angle, rotor_rate]`.
    """
    pendulum = VelocitySlopeEstimator(WINDOW, DT, num_envs=1, device="cpu")
    rotor = VelocitySlopeEstimator(WINDOW, DT, num_envs=1, device="cpu", wrap=False)

    def angles(counts: int, microsteps: int) -> tuple[torch.Tensor, torch.Tensor]:
        pendulum = torch.tensor([counts], dtype=torch.float32) * RAD_PER_COUNT
        rotor = torch.tensor([microsteps], dtype=torch.float32) * RAD_PER_MICROSTEP
        return pendulum, rotor

    first_pendulum, first_rotor = angles(*samples[0])
    pendulum.reset(None, first_pendulum)
    rotor.reset(None, first_rotor)

    observations = []
    for counts, microsteps in samples[1:]:
        pendulum_angle, rotor_angle = angles(counts, microsteps)
        pendulum_rate = pendulum.update(pendulum_angle)
        rotor_rate = rotor.update(rotor_angle)
        tilt = wrap_to_pi(pendulum_angle - math.pi)
        obs = torch.stack(
            [torch.cos(tilt), torch.sin(tilt), pendulum_rate, rotor_angle, rotor_rate],
            dim=-1,
        )
        observations.append(obs.squeeze(0).tolist())
    return observations


def test_synthetic_trajectory_covers_what_it_claims() -> None:
    """The fixture crosses the seam, over-rotates, passes pi on the rotor, and rests.

    Asserted rather than trusted, so a later edit to `pose` cannot quietly turn the
    equivalence test into one that never leaves the easy region.
    """
    samples = synthetic_trajectory()
    counts = [c for c, _ in samples]
    microsteps = [m for _, m in samples]

    assert min(counts) < 0 < max(counts), "the pendulum passes through hanging"
    assert max(counts) > COUNTS_PER_REV, "the count carries past a full revolution"
    assert max(microsteps) > MICROSTEPS_PER_REV // 2, "the rotor sweeps past pi"
    assert len(set(samples[-100:])) == 1, "the last 0.2 s is at rest"

    reference = reference_observations(samples)
    assert max(abs(obs[2]) for obs in reference) > 5.0, "a real pendulum rate"
    assert max(abs(obs[4]) for obs in reference) > 3.0, "a real rotor rate"
    assert reference[-1][2] == pytest.approx(0.0, abs=1e-3)
    assert reference[-1][4] == pytest.approx(0.0, abs=1e-3)


@pytest.mark.parametrize("convention", ["continuous", "modulo"])
def test_observer_matches_the_simulation_pipeline(
    harness: Path, convention: str
) -> None:
    """The C observer produces the simulation's observations from the same motion.

    The reference is always the simulation's pipeline fed the continuous count. The C
    side is fed either that count or the same motion from a source that wraps at one
    revolution, which is the other convention the firmware glue might supply; the
    observer has to be indifferent to it, and this is where that is shown. The
    continuous count passes 2400, where the observer's own reduction to one revolution
    has its seam, and the wrapping count passes 1200, where the source has its own.
    """
    continuous = synthetic_trajectory()
    expected = reference_observations(continuous)
    fed = (
        continuous if convention == "continuous" else modulo_one_revolution(continuous)
    )

    got = run(harness, "observer", [f"{c} {m}" for c, m in fed])

    assert len(got) == len(expected) == len(continuous) - 1
    for step, (obs, ref) in enumerate(zip(got, expected, strict=True)):
        for name, value, target, tol in zip(
            OBS_NAMES, obs, ref, OBS_TOLERANCES, strict=True
        ):
            assert value == pytest.approx(target, abs=tol), f"{name} at step {step}"


def test_observer_ramp_reads_the_quantum_rate(harness: Path) -> None:
    """One count per period reads 1.309 rad/s, one microstep 0.982 rad/s.

    A check on the scale constants that does not go through torch: a ramp of one count
    and two microsteps per period reads `quantum / dt` once the 16-sample window has
    filled, and the rotor angle is the unwrapped lattice position.
    """
    steps = 40
    got = run(harness, "observer", [f"{k} {2 * k}" for k in range(steps)])

    final = got[-1]
    assert final[2] == pytest.approx(RAD_PER_COUNT / DT, rel=1e-4)
    assert final[4] == pytest.approx(2.0 * RAD_PER_MICROSTEP / DT, rel=1e-4)
    assert final[3] == pytest.approx(2.0 * (steps - 1) * RAD_PER_MICROSTEP, abs=1e-6)
    # The first estimate after a flat reset differences one count against a flat
    # window and reads a fraction of the full rate, not the full quantum step.
    assert 0.0 < got[0][2] < RAD_PER_COUNT / DT

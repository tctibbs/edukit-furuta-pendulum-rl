"""Gymnasium registration for the Edukit pendulum tasks.

Importing this module registers the environment ids, which is what lets Isaac Lab's
training scripts find them by name.

Both an environment config and an agent config are registered. Isaac Lab's rsl_rl
training entry point resolves the agent through `rsl_rl_cfg_entry_point` and fails
before Kit starts if it is missing, so registering only the environment leaves a task
that exists but cannot be trained.
"""

from __future__ import annotations

import math

import gymnasium as gym

from furuta.agents import (
    FurutaBalanceMomentumPlayPPORunnerCfg,
    FurutaBalanceMomentumPPORunnerCfg,
    FurutaBalancePlayPPORunnerCfg,
    FurutaBalancePPORunnerCfg,
    FurutaSwingUpPlayPPORunnerCfg,
    FurutaSwingUpPPORunnerCfg,
)
from furuta.env import FurutaEnv, FurutaEnvCfg


class FurutaBalancePlayEnvCfg(FurutaEnvCfg):
    """Evaluation variant: the 30 second episode the Milestone 05 gate is scored over.

    Training runs 10 second episodes. The gate is an evaluation result, and drift modes
    only appear in the last 20 seconds of an episode that training never saw.
    """

    def __post_init__(self) -> None:
        """Widen the episode and narrow the scene for evaluation."""
        if hasattr(super(), "__post_init__"):
            super().__post_init__()
        self.episode_length_s = 30.0
        self.scene.num_envs = 256


class FurutaBalanceMomentumEnvCfg(FurutaEnvCfg):
    """Balance from the states a swing-up hands over, not from rest.

    Experiment 05's policy trained from a 2 degree, 0.25 rad/s spread about upright and
    recovers kicks through 0.6 rad/s of a 1.011 rad/s recoverable set. A scripted pump
    arrives anywhere in that set with the arm displaced and moving. The only change
    from the balance task is where episodes start, so a difference in the catch rate
    is the reset distribution and nothing else. Experiment 05 records why.
    """

    def __post_init__(self) -> None:
        """Widen the resets to the recoverable set and the pump's arm motion."""
        if hasattr(super(), "__post_init__"):
            super().__post_init__()
        # Tilt across most of the 20 degree termination envelope, and the unstable
        # mode across most of the recoverable set; the rate follows from the two.
        self.reset_in_recoverable_set = True
        self.initial_pendulum_angle_range = [-0.3, 0.3]
        self.reset_mode_range = [-0.9, 0.9]
        # The arm as the pump leaves it: up to 2 rad off centre inside the governor's
        # allowance, moving at up to 6 rad/s. Both from the handover traces.
        self.initial_rotor_angle_range = [-2.0, 2.0]
        self.initial_rotor_rate_range = [-6.0, 6.0]
        # The swing-up task's travel bound, since that is the task the handover runs
        # in. Balance's pi/2 would end an episode the pump handed over at 1.9 rad.
        self.max_rotor_angle_rad = math.pi


class FurutaBalanceMomentumPlayEnvCfg(FurutaBalanceMomentumEnvCfg):
    """Evaluation variant: 30 second episodes from the same momentum starts."""

    def __post_init__(self) -> None:
        """Widen the episode and narrow the scene for evaluation."""
        super().__post_init__()
        self.episode_length_s = 30.0
        self.scene.num_envs = 256


class FurutaSwingUpEnvCfg(FurutaEnvCfg):
    """Swing-up: start hanging, reach vertical, stay there.

    The rotor cannot lift the pendulum. Its push peaks at 7.43 rad/s^2 of pendulum
    acceleration where gravity's term vanishes, and vanishes at horizontal where
    gravity's pull peaks at 54.04, so vertical is reached by pumping energy in over
    roughly a dozen half swings of the 0.855 s natural period. Every difference from
    the balance configuration follows from that.
    """

    def __post_init__(self) -> None:
        """Turn the balance task into a swing-up."""
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

        # Long enough for the swing-up and the full 5 s hold afterwards. Pumping to
        # vertical takes a dozen or so half swings of the 0.855 s period, so a 10 s
        # episode could end while the pendulum is still on its way up and the policy
        # would never be paid. 20 s was enough on paper and knife-edge in practice:
        # under the corrected dissipation the scripted governed pump
        # arrives through the observation pipeline in the mid teens of seconds, which
        # leaves the hold window straddling the timeout.
        self.episode_length_s = 30.0

        # Start anywhere on the circle. The task is swing-up from hanging, and the
        # evaluation variant below resets there. Training only from hanging leaves the
        # top unvisited: a policy cannot learn to hold a state it has never entered,
        # and the value function cannot report that the top is worth reaching.
        # Resetting across the full circle puts some episodes near vertical from the
        # first iteration.
        self.reset_upright = False
        self.initial_pendulum_angle_range = [-math.pi, math.pi]
        # Wide, because the spread has to cover energies and not only angles. Reaching
        # vertical needs 14.7 rad/s through the bottom, and at plus or minus 1 rad/s
        # every wide-spread reset is a nearly motionless pendulum somewhere on the
        # circle. Stalling short of the top is a state a narrow spread teaches;
        # carrying on from a fast swing is not.
        self.initial_pendulum_rate_range = [-10.0, 10.0]

        # `cos(tilt)` is proportional to the height the rotor pumps the pendulum
        # through, and it spans its full range over the half turn this task covers.
        # Inside balance's 20 degree envelope it is nearly flat, and balance keeps the
        # quadratic.
        self.upright_reward = "cosine"

        # No fall-over termination. Hanging is where every episode starts, so the
        # Milestone 05 cut at 20 degrees would end the episode on the first step.
        # `pi` is unreachable by a wrapped angle, which disables the check.
        self.max_pendulum_angle_rad = math.pi

        # Separatrix energy shaping pays 0 at hanging rest and 2.0 per step on the
        # separatrix. It is the dominant gradient near hanging rest.
        self.rew_scale_energy = 2.0

        # Resets initialized near hanging rest to evaluate the target swing-up task.
        self.hanging_reset_fraction = 0.4

        # Resets drawn near upright to preserve and train recovery/hold skills.
        self.balance_reset_fraction = 0.25

        # Sample near-vertical resets with high rates and arm displacement.
        self.balance_reset_in_recoverable_set = True
        self.balance_reset_angle_range = [-0.3, 0.3]
        self.balance_reset_mode_range = [-0.9, 0.9]
        self.balance_reset_rotor_angle_range = [-2.0, 2.0]
        self.balance_reset_rotor_rate_range = [-6.0, 6.0]

        # Bound commands at limits rather than quadratically penalizing effort.
        self.squash_actions = True

        # Penalize rotor displacement outside deadband, 0.5 per radian per step, to
        # prevent limit drift.
        self.rew_scale_rotor_travel = -0.5

        # The capture well pays up to 2.0 per step at vertical and makes upright
        # balance more profitable than swinging.
        self.rew_scale_capture = 2.0

        # Restrict the rate penalty to the capture window so pumping is not charged.
        self.pendulum_rate_gate_rad = 0.35

        # Penalize angular velocity near upright, 0.25 per (rad/s)^2 per step, to
        # prevent over-the-top rotation.
        self.rew_scale_pendulum_rate = -0.25

        # Match the evaluation gate's travel limit, pi either side
        # of center.
        self.max_rotor_angle_rad = math.pi


class FurutaSwingUpPlayEnvCfg(FurutaSwingUpEnvCfg):
    """Evaluation variant: 30 s to swing up and hold, scored over a fixed seed set."""

    def __post_init__(self) -> None:
        """Reset hanging, which is the task, and narrow the scene."""
        super().__post_init__()
        # Reset near hanging rest to evaluate swing-up from near-zero kinetic energy.
        self.initial_pendulum_angle_range = [-0.4, 0.4]
        self.initial_pendulum_rate_range = [-1.0, 1.0]
        # Clear both reset shares. They are training aids, and the near-vertical
        # share left inherited hands a quarter of the scored episodes a pendulum that
        # is already up.
        self.hanging_reset_fraction = 0.0
        self.balance_reset_fraction = 0.0
        self.scene.num_envs = 256


gym.register(
    id="Furuta-Balance-Direct-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": FurutaEnvCfg,
        "rsl_rl_cfg_entry_point": FurutaBalancePPORunnerCfg,
    },
)

gym.register(
    id="Furuta-Balance-Direct-Play-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": FurutaBalancePlayEnvCfg,
        "rsl_rl_cfg_entry_point": FurutaBalancePlayPPORunnerCfg,
    },
)

gym.register(
    id="Furuta-Balance-Momentum-Direct-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": FurutaBalanceMomentumEnvCfg,
        "rsl_rl_cfg_entry_point": FurutaBalanceMomentumPPORunnerCfg,
    },
)

gym.register(
    id="Furuta-Balance-Momentum-Direct-Play-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": FurutaBalanceMomentumPlayEnvCfg,
        "rsl_rl_cfg_entry_point": FurutaBalanceMomentumPlayPPORunnerCfg,
    },
)


gym.register(
    id="Furuta-SwingUp-Direct-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": FurutaSwingUpEnvCfg,
        "rsl_rl_cfg_entry_point": FurutaSwingUpPPORunnerCfg,
    },
)

gym.register(
    id="Furuta-SwingUp-Direct-Play-v0",
    entry_point="furuta.env:FurutaEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": FurutaSwingUpPlayEnvCfg,
        "rsl_rl_cfg_entry_point": FurutaSwingUpPlayPPORunnerCfg,
    },
)

__all__ = [
    "FurutaBalanceMomentumEnvCfg",
    "FurutaBalanceMomentumPlayEnvCfg",
    "FurutaBalancePlayEnvCfg",
    "FurutaEnv",
    "FurutaEnvCfg",
    "FurutaSwingUpEnvCfg",
    "FurutaSwingUpPlayEnvCfg",
]

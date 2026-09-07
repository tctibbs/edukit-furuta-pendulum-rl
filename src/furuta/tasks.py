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

        # No fall-over termination. Hanging is where every episode starts, so the
        # Milestone 05 cut at 20 degrees would end the episode on the first step.
        # `pi` is unreachable by a wrapped angle, which disables the check.
        self.max_pendulum_angle_rad = math.pi

        # Pumping needs the rotor to swing back and forth, and the requirement is only
        # that total travel stay bounded by the pendulum encoder's cable. A full turn is
        # the bound; balance used half of it because balance never needed the room.
        self.max_rotor_angle_rad = math.pi


class FurutaSwingUpPlayEnvCfg(FurutaSwingUpEnvCfg):
    """Evaluation variant: 30 s to swing up and hold, scored over a fixed seed set."""

    def __post_init__(self) -> None:
        """Reset hanging, which is the task, and narrow the scene."""
        super().__post_init__()
        # Training resets across the whole circle so the policy meets the top. The
        # gate is swing-up, so scoring has to start at the bottom, and a policy scored
        # on the training spread would be credited for episodes handed to it upright.
        self.initial_pendulum_angle_range = [-0.4, 0.4]
        # Near rest, matching the hanging share's spread. The training rate spread of
        # plus or minus 10 rad/s exists to cover energies, and inherited here it hands
        # a scored episode up to 46 percent of the energy to vertical before the
        # policy has acted. At 1 rad/s the handout is 0.5 percent.
        self.initial_pendulum_rate_range = [-1.0, 1.0]
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

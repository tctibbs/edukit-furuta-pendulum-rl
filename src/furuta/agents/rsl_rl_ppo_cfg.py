"""PPO configuration for the balance task.

Started from experiment 01's cartpole settings, which are known good on this exact
stack, but three of them are horizons measured in steps and the cartpole ran at 60 Hz
while this task runs at 500 Hz. Copying them across would have shortened every horizon
by a factor of eight against a plant whose unstable time constant is 136 ms.

The three that moved, and what they are placed against:

- `gamma`. At 500 Hz the cartpole's 0.99 is a `1/(1-gamma)` horizon of 100 steps, 0.2 s.
 That is barely longer than the pendulum's 136 ms time constant, so a policy optimising
 it can let the pendulum fall and never see the cost. 0.999 gives 2 s.
- `lam`. The GAE horizon is `1/(1 - gamma*lam)`. Holding lam at 0.95 while gamma rises
 leaves it at 20 steps, 39 ms, a quarter of a time constant. 0.99 gives 91 steps.
- `num_steps_per_env`. 16 steps is 32 ms of experience per environment per iteration,
 shorter than the GAE window it feeds. 128 is 256 ms, so the window fits the rollout.

`init_noise_std` stays at the cartpole's 1.0, which was tested here. At 1.0 the
learned std rises to 1.23 and clips 55 percent of commanded accelerations at a rail,
which looks like a defect. Cutting it to 0.3 to remove the clipping made learning
worse: 248 to 280 steps over 55 iterations, against 529 by iteration 55 at 1.0. With
only 7.83 degrees of tilt the rotor can arrest, the wide noise is the exploration the
task needs, and the clipping is a symptom of it. Runs 3 and 4 in
`docs/experiments/05-balance/logbook.md` have both.

The network stays at [32, 32]. Five observations and one action do not need width, and
keeping it small keeps on-board inference plausible inside the 2 ms control period on an
84 MHz Cortex-M4F, which Milestone 03 established is where inference has to run.
"""

from __future__ import annotations

from isaaclab.utils import configclass
from isaaclab_rl.rsl_rl import (
    RslRlOnPolicyRunnerCfg,
    RslRlPpoActorCriticCfg,
    RslRlPpoAlgorithmCfg,
)


@configclass
class FurutaBalancePPORunnerCfg(RslRlOnPolicyRunnerCfg):
    """On-policy runner settings for `Furuta-Balance-Direct-v0`."""

    num_steps_per_env = 128
    max_iterations = 300
    save_interval = 50
    experiment_name = "furuta_balance"
    empirical_normalization = False

    # The environment publishes a single observation group, so both heads read it.
    obs_groups = {"policy": ["policy"], "critic": ["policy"]}

    policy: RslRlPpoActorCriticCfg = RslRlPpoActorCriticCfg(
        class_name="ActorCritic",
        init_noise_std=1.0,
        actor_hidden_dims=[32, 32],
        critic_hidden_dims=[32, 32],
        activation="elu",
    )

    algorithm: RslRlPpoAlgorithmCfg = RslRlPpoAlgorithmCfg(
        class_name="PPO",
        value_loss_coef=1.0,
        use_clipped_value_loss=True,
        clip_param=0.2,
        entropy_coef=0.005,
        num_learning_epochs=5,
        num_mini_batches=4,
        learning_rate=1.0e-3,
        schedule="adaptive",
        gamma=0.999,
        lam=0.99,
        desired_kl=0.01,
        max_grad_norm=1.0,
    )


@configclass
class FurutaBalancePlayPPORunnerCfg(FurutaBalancePPORunnerCfg):
    """Evaluation variant. Same policy, no training."""

    max_iterations = 1


@configclass
class FurutaBalanceMomentumPPORunnerCfg(FurutaBalancePPORunnerCfg):
    """Same trainer as balance; only the log directory differs."""

    experiment_name = "furuta_balance_momentum"


@configclass
class FurutaBalanceMomentumPlayPPORunnerCfg(FurutaBalanceMomentumPPORunnerCfg):
    """Evaluation variant. Same policy, no training."""

    max_iterations = 1


@configclass
class FurutaSwingUpPPORunnerCfg(FurutaBalancePPORunnerCfg):
    """On-policy runner settings for `Furuta-SwingUp-Direct-v0`.

    At the configured 11.78 rad/s^2 bound a swing-up pumps over about a dozen half
    swings, and the default `gamma` of 0.9998 is a 10 s horizon. The Experiment 06
    runs trained at 60 rad/s^2 and set `--gamma 0.999`, `--no-value-clip`, and
    `--max-iterations 600` on the command line.
    """

    max_iterations = 900
    save_interval = 100
    experiment_name = "furuta_swingup"

    algorithm: RslRlPpoAlgorithmCfg = RslRlPpoAlgorithmCfg(
        class_name="PPO",
        value_loss_coef=1.0,
        use_clipped_value_loss=True,
        clip_param=0.2,
        entropy_coef=0.005,
        num_learning_epochs=5,
        num_mini_batches=4,
        learning_rate=1.0e-3,
        schedule="adaptive",
        gamma=0.9998,
        lam=0.99,
        desired_kl=0.01,
        max_grad_norm=1.0,
    )


@configclass
class FurutaSwingUpPlayPPORunnerCfg(FurutaSwingUpPPORunnerCfg):
    """Evaluation variant. Same policy, no training."""

    max_iterations = 1

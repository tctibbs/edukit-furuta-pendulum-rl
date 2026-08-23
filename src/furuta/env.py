"""Direct-workflow RL environment for the Edukit rotary inverted pendulum.

- Action: rotor angular acceleration. `AccelerationCommandActuator` integrates it into
  a microstep-quantized position target for the rotor joint.
- Observation: the pendulum angle from upright as cos and sin, the rotor angle, and a
  rate for each. Angles are quantized the way the hardware reads them. The hardware has
  no velocity sensor. Each rate is the change in angle since the last control step.
- Reward: the pendulum's height, +1 upright and -1 hanging. Nothing trains against it
  yet; it is here because `DirectRLEnv` requires one.
- Episode end: the rotor passing its travel bound, or a timeout.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import isaaclab.sim as sim_utils
import torch
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import Articulation, ArticulationCfg
from isaaclab.envs import DirectRLEnv, DirectRLEnvCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sim import SimulationCfg
from isaaclab.sim.spawners.from_files import GroundPlaneCfg, spawn_ground_plane
from isaaclab.utils import configclass
from isaaclab.utils.math import sample_uniform, wrap_to_pi

from furuta.actuator import AccelerationCommandActuator
from furuta.parameters import FurutaParameters

PARAMS = FurutaParameters.from_yaml()
"""Loaded once at import from `config/edukit.yaml`."""

DEFAULT_USD = Path(__file__).resolve().parents[2] / "assets" / "edukit_pendulum.usda"

ROTOR_JOINT = "rotor_joint"
PENDULUM_JOINT = "pendulum_joint"

ROTOR_DRIVE_STIFFNESS = 1.0e5
ROTOR_DRIVE_DAMPING = 50.0
"""Rotor position-drive gains. A stepper holds position until it drops steps.

The implicit actuator applies `K(target - q) - D*q_dot`. The damping term makes a
moving rotor lag its target. At D = 1e3 and 3.5 rad/s the lag is 0.03 rad, about 15
microsteps. Critical damping is 2*sqrt(K*I), about 21 for the rotor's inertia of
1.1e-3 kg m^2 with the pendulum hanging. D = 50 is about twice critical. At D = 50
the rotor tracks within one microstep."""


@configclass
class FurutaEnvCfg(DirectRLEnvCfg):
    """Configuration for the Edukit pendulum environment."""

    decimation = PARAMS.decimation
    episode_length_s = 10.0

    action_space = 1
    observation_space = 5
    state_space = 0

    sim: SimulationCfg = SimulationCfg(
        dt=PARAMS.physics_dt_s, render_interval=PARAMS.decimation
    )

    robot_cfg: ArticulationCfg = ArticulationCfg(
        prim_path="/World/envs/env_.*/Furuta",
        spawn=sim_utils.UsdFileCfg(usd_path=str(DEFAULT_USD)),
        actuators={
            "rotor": ImplicitActuatorCfg(
                joint_names_expr=[ROTOR_JOINT],
                stiffness=ROTOR_DRIVE_STIFFNESS,
                damping=ROTOR_DRIVE_DAMPING,
            ),
            # The pendulum pivot is passive. Damping comes from the manual's Q.
            "pendulum": ImplicitActuatorCfg(
                joint_names_expr=[PENDULUM_JOINT],
                stiffness=0.0,
                damping=PARAMS.pivot_damping_n_m_s,
            ),
        },
    )

    scene: InteractiveSceneCfg = InteractiveSceneCfg(
        num_envs=4096, env_spacing=1.5, replicate_physics=True, clone_in_fabric=False
    )
    """Cloning in Fabric, Isaac Sim's runtime scene store, fails for an articulation
    fixed to the world. Environments are cloned in USD instead."""

    max_rotor_angle_rad = math.pi
    """Rotor travel bound, in radians. Passing it ends the episode.

    The encoder cable limits how far the real arm can turn. That travel is unmeasured.
    The bound stops an integrating acceleration command winding the arm up without
    limit."""

    initial_pendulum_angle_range = [-0.1, 0.1]
    """Reset spread about hanging, in radians. The asset hangs at zero.

    Without it, every environment resets to the same state and follows the same
    trajectory."""


class FurutaEnv(DirectRLEnv):
    """Rotary inverted pendulum with an acceleration-commanded rotor."""

    cfg: FurutaEnvCfg

    def __init__(self, cfg: FurutaEnvCfg, render_mode: str | None = None, **kwargs):
        """Set up joint indices, the actuator model and the differencing state."""
        super().__init__(cfg, render_mode, **kwargs)

        self._rotor_idx, _ = self.robot.find_joints(ROTOR_JOINT)
        self._pendulum_idx, _ = self.robot.find_joints(PENDULUM_JOINT)

        self._actuator = AccelerationCommandActuator(
            PARAMS, num_envs=self.num_envs, device=self.device
        )
        self._rotor_target = torch.zeros(self.num_envs, device=self.device)

        # Last observed angles, for estimating rates by differencing.
        self._prev_pendulum = torch.zeros(self.num_envs, device=self.device)
        self._prev_rotor = torch.zeros(self.num_envs, device=self.device)

    # Scene.

    def _setup_scene(self) -> None:
        self.robot = Articulation(self.cfg.robot_cfg)
        spawn_ground_plane(prim_path="/World/ground", cfg=GroundPlaneCfg())
        self.scene.clone_environments(copy_from_source=False)
        if self.device == "cpu":
            self.scene.filter_collisions(global_prim_paths=[])
        self.scene.articulations["furuta"] = self.robot
        light_cfg = sim_utils.DomeLightCfg(intensity=2000.0, color=(0.75, 0.75, 0.75))
        light_cfg.func("/World/Light", light_cfg)

    # Action pipeline.

    def _pre_physics_step(self, actions: torch.Tensor) -> None:
        """Integrate the acceleration command once per control period.

        Isaac Lab calls this once per control step and `_apply_action` once per physics
        substep. The firmware also updates its step rate once per control step.
        """
        self._rotor_target = self._actuator.step(
            actions.squeeze(-1), PARAMS.control_dt_s
        )

    def _apply_action(self) -> None:
        self.robot.set_joint_position_target(
            self._rotor_target.unsqueeze(-1), joint_ids=self._rotor_idx
        )

    # Observation, reward, termination.

    def _quantized_angles(self) -> tuple[torch.Tensor, torch.Tensor]:
        """Pendulum and rotor angles as the hardware reports them.

        The pendulum angle is rounded to whole encoder counts. The rotor has no
        position sensor. Its angle is the commanded position the actuator tracks.
        """
        pendulum = self.robot.data.joint_pos[:, self._pendulum_idx[0]]
        encoder = PARAMS.rad_per_encoder_count
        return torch.round(
            pendulum / encoder
        ) * encoder, self._actuator.quantized_position()

    def _get_observations(self) -> dict:
        pendulum, rotor = self._quantized_angles()

        # Rates are the change in angle since the last control step. The pendulum rate
        # resolves to 1.309 rad/s, one encoder count per step.
        # Only the pendulum difference wraps. The rotor angle is a running total.
        pendulum_vel = wrap_to_pi(pendulum - self._prev_pendulum) / PARAMS.control_dt_s
        rotor_vel = (rotor - self._prev_rotor) / PARAMS.control_dt_s
        self._prev_pendulum = pendulum
        self._prev_rotor = rotor

        # Angle from upright. In the asset, hanging is zero and upright is pi.
        upright = wrap_to_pi(pendulum - math.pi)

        obs = torch.stack(
            [torch.cos(upright), torch.sin(upright), pendulum_vel, rotor, rotor_vel],
            dim=-1,
        )
        return {"policy": obs}

    def _get_rewards(self) -> torch.Tensor:
        """Pendulum height: 1.0 upright, -1.0 hanging."""
        pendulum, _ = self._quantized_angles()
        return torch.cos(wrap_to_pi(pendulum - math.pi))

    def _get_dones(self) -> tuple[torch.Tensor, torch.Tensor]:
        _, rotor = self._quantized_angles()
        time_out = self.episode_length_buf >= self.max_episode_length - 1
        out_of_bounds = torch.abs(rotor) > self.cfg.max_rotor_angle_rad
        return out_of_bounds, time_out

    def _reset_idx(self, env_ids: Sequence[int] | None) -> None:
        if env_ids is None:
            env_ids = self.robot._ALL_INDICES
        super()._reset_idx(env_ids)

        joint_pos = self.robot.data.default_joint_pos[env_ids].clone()
        joint_vel = self.robot.data.default_joint_vel[env_ids].clone()

        # Start the pendulum near hanging, at rest. The asset hangs at zero.
        joint_pos[:, self._pendulum_idx] = sample_uniform(
            self.cfg.initial_pendulum_angle_range[0],
            self.cfg.initial_pendulum_angle_range[1],
            joint_pos[:, self._pendulum_idx].shape,
            joint_pos.device,
        )
        joint_pos[:, self._rotor_idx] = 0.0
        joint_vel[:, self._rotor_idx] = 0.0
        self.robot.write_joint_state_to_sim(joint_pos, joint_vel, None, env_ids)

        # Reset the actuator with the joint. If the two disagree, the stiff drive snaps
        # the rotor to the actuator's position on the next substep.
        self._actuator.reset(env_ids)
        self._rotor_target[env_ids] = self._actuator.quantized_position()[env_ids]

        # Seed the rate estimate from the quantized starting angles. An unquantized
        # seed adds up to 0.65 rad/s of false rate to each episode's first step.
        encoder = PARAMS.rad_per_encoder_count
        pendulum = joint_pos[:, self._pendulum_idx[0]]
        self._prev_pendulum[env_ids] = torch.round(pendulum / encoder) * encoder
        self._prev_rotor[env_ids] = self._actuator.quantized_position()[env_ids]

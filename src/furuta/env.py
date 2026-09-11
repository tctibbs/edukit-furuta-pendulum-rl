"""Direct-workflow RL environment for the Edukit rotary inverted pendulum.

This environment differs from the cartpole template it is modelled on in its actuator
model and its observation pipeline.

The rotor is not a torque joint. Actions are rotor angular acceleration, which
`AccelerationCommandActuator` integrates into a microstep-quantized position, driven
onto the joint through a stiff position target. Writing the joint state
directly each substep is closer to how a stepper behaves, but it bypasses the
articulation solver and the reaction torque on the arm goes with it.

Observations are estimated from encoder-quantized angles instead of read from
`joint_vel`. The hardware has a 2400-count incremental encoder and no velocity sensor,
so true velocities from the simulator would hand the policy information the real system
cannot supply. Rate comes from `VelocitySlopeEstimator`: plain
differencing resolves 1.309 rad/s of pendulum rate against a recoverable window of
1.011 rad/s, so it is coarser than the quantity it measures.

The balance task is sized by two numbers derived from the measured constants. The rotor
can arrest a pendulum tilted 7.83 degrees, from `tan(theta) = omega_r^2 * a_max /
omega_g^2`, and the recoverable set at any tilt is `|theta_dot + 7.351 * theta| < 1.011`
rad/s. Reset spreads, termination bounds and reward deadbands are all placed against
those rather than chosen by habit.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
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
from furuta.dissipation import PivotDissipation
from furuta.estimator import VelocitySlopeEstimator
from furuta.parameters import FurutaParameters

PARAMS = FurutaParameters.from_yaml()
"""Loaded once at import. Rates and limits below come from it, so a refit is a change to
`config/edukit.yaml` and a regeneration, with no source edit."""

DEFAULT_USD = Path(__file__).resolve().parents[2] / "assets" / "edukit_pendulum.usda"

ROTOR_JOINT = "rotor_joint"
PENDULUM_JOINT = "pendulum_joint"

RECOVERABLE_MODE_RAD_S = 1.011
"""Recoverable-set bound on |theta_dot + omega_g * theta| at 11.78 rad/s^2."""

ROTOR_DRIVE_STIFFNESS = 1.0e5
ROTOR_DRIVE_DAMPING = 50.0
"""Position-drive gains for the rotor, which a stepper holds until it drops steps.

The implicit actuator applies `K(target - q) - D*q_dot`, so damping shows up as a lag
proportional to rotor speed: at D = 1e3 and 3.5 rad/s the drive gives up 0.03 rad, about
15 microsteps of standing error. Critical damping for this rotor is 2*sqrt(K*I), roughly
22 for an inertia near 1.2e-3 kg m^2, so 50 is slightly over-damped and tracks to well
under one microstep. Tracking error is checked in the scale benchmark."""


@configclass
class FurutaEnvCfg(DirectRLEnvCfg):
    """Configuration for the Edukit pendulum environment."""

    decimation = PARAMS.decimation
    episode_length_s = 10.0

    action_space = 1
    observation_space = 5
    state_space = 0

    sim: SimulationCfg = SimulationCfg(
        dt=PARAMS.physics_dt_s,
        render_interval=PARAMS.decimation,
        gravity=PARAMS.gravity_vector,
    )
    """Gravity with the measured baseplate tilt, at the configured magnitude.

    Because rolling the base and tilting gravity are the same dynamics, the tilt is a
    scene setting and the asset stays level. `furuta.parameters.gravity_for_tilt`
    derives the vector. A level plant, for a before and after comparison, is
    `gravity_for_tilt(0.0, PARAMS.gravity_m_s2)`.

    Setting it explicitly also pins the magnitude to the config's 9.806. Isaac Lab's
    `SimulationCfg` defaults to 9.81. A scene that leaves gravity unset integrates
    against a different constant from the one behind `omega_g_squared` and every gate
    derived from it."""

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
    """Fabric cloning is off. This articulation is anchored to the world by a fixed
    joint, and cloning it through Fabric fails where the free-floating cartpole
    succeeds."""

    rotor_command_mode = "acceleration"
    """How to read the action: `acceleration` for the task, `position` for a replay.

    The task's action is a normalized rotor angular acceleration, which is what the
    firmware takes. Replaying a measured trace needs the other thing: the rotor has to
    follow the trajectory the hardware's rotor actually took, so the pendulum's response
    is the only free variable. Feeding the measured acceleration instead does not work
    and is not a tuning question. Reconstructing it from a microstep-quantized angle
    leaves a small bias, and two integrations turn that into a ramp: over the 8 s logged
    trace it walks the rotor 640 degrees against a measured span of 22.5.

    In `position` the action is an absolute rotor angle in radians. It still passes
    through the microstep lattice, because the real rotor could not stand between
    microsteps either. Diagnostic only; no task sets it.
    """

    rotor_target_interpolation = True
    """Linearly interpolate position targets across substeps with velocity feedforward.

    Eliminates discrete jump-and-hold velocity spikes within each 2 ms control period.
    The spikes inject unphysical centrifugal energy (see ADR-0006). Set False to
    reproduce legacy stepping.
    """

    pivot_coulomb_deg_per_half_swing = PARAMS.coulomb_loss_deg_per_half_swing
    pivot_drag_coeff = PARAMS.quadratic_drag_coeff
    """The two pivot loss terms the drive cannot carry, applied as a substep torque.

    `ImplicitActuatorCfg` expresses `K(target - q) - D*qdot`, so the viscous term goes
    through the drive and these two do not. Defaults are the reconciled values from
    `config/edukit.yaml`; setting both to zero gives the purely viscous environment the
    environment had before experiment 04, which is how a before/after comparison is run
    without reverting code.
    """

    max_acceleration_rad_s2: float | None = None
    """Override the rotor's acceleration bound; None reads `config/edukit.yaml`.

    The configured 11.78 rad/s^2 is the conservative reading of the firmware's
    MAX_ACCEL, and the logged trace's rotor moves faster than that reading allows.
    Experiment 05's handover runs sweep this to ask what bound the real swing-up needs,
    which is a question about the constant rather than a new value for it. The
    recoverable set and the balance policy's action scale follow the configured bound,
    so a policy trained at 11.78 keeps its 11.78 through this override."""
    max_rotor_angle_rad = math.pi / 2
    """Rotor travel bound. Cable and frame constrain total rotation.

    Half a turn is what the unit has actually demonstrated. The Milestone 03 tilt sweep
    stopped at +/- 90 degrees because the pendulum encoder is cabled to the arm. No
    wider travel has been measured, so a wider bound would be an assumption."""

    reset_upright = True
    """Reset near vertical rather than hanging. The swing-up task sets this
    False."""

    initial_pendulum_angle_range = [-0.035, 0.035]
    """Reset spread in radians, about upright or hanging per `reset_upright`.

    Plus or minus 2 degrees. With the rate spread below, the worst corner puts the
    unstable mode at `7.351 * 0.035 + 0.25 = 0.507` rad/s, half the 1.011 rad/s bound,
    so every reset is recoverable. Sampling angle and rate independently over wider
    ranges makes some fraction of episodes unwinnable at reset, which caps the hold rate
    at something the policy cannot influence."""

    initial_pendulum_rate_range = [-0.25, 0.25]
    """Reset rate spread in rad/s. Zero every time trains a policy that has never seen
    motion at reset."""

    initial_rotor_angle_range = [-0.5, 0.5]
    initial_rotor_rate_range = [-0.5, 0.5]
    """Rotor reset spread. Starting always at exactly zero teaches the travel term that
    the origin is free."""

    reset_in_recoverable_set = False
    """Draw the pendulum rate from the unstable-mode coordinate instead of a box.

    A swing-up hands the pendulum over moving, and a policy that only ever started at
    rest has never seen that. The linearised upright dynamics split into a stable and
    an unstable mode, and the unstable one, `rate + omega_g * tilt`, is the quantity the
    rotor has to arrest: the recoverable set is a bound on it (1.011 rad/s at the
    configured 11.78 rad/s^2). With this set, the tilt is drawn from
    `initial_pendulum_angle_range`, the mode from `reset_mode_range`, and the rate is
    whatever puts the pair there. Drawing tilt and rate from independent boxes instead
    fills most of the batch with states outside the set, which teach that they are lost.
    Experiment 05 records why."""

    reset_mode_range = [-0.9, 0.9]
    """Unstable-mode coordinate at reset, rad/s, used when `reset_in_recoverable_set`.
    Inside the 1.011 rad/s bound with a margin for the discretisation."""
    max_pendulum_angle_rad = 0.35
    """Fall-over termination, 20 degrees from upright.

    Two and a half times the 7.83 degree arrest angle, so a transient already heading
    back is never cut off, while anything past it is unrecoverable by construction and
    only collects alive reward."""

    upright_reward = "quadratic"
    """Shape of the upright term, `quadratic` or `cosine`.

    The quadratic spans the balance envelope, where `cos` is nearly flat.
    Swing-up inverts that: the pendulum travels a half turn, `cos` is proportional to
    height and therefore to the potential energy the rotor has to pump in, and the
    quadratic's normalisation by a 20 degree termination angle is meaningless."""

    velocity_window = 16
    """Samples in the velocity slope estimator. 32 ms at 500 Hz, against a 136 ms
    unstable time constant. Set to 2 for plain adjacent-sample differencing."""

    episode_length_jitter = 0.0
    """Fractional randomization of episode timeout per environment on reset.

    Randomizes episode duration to prevent batch environments from synchronizing
    rollout phases following early terminations.
    """
    upright_deadband_rad = PARAMS.stiction_hold_angle_rad
    """The tilt at which pivot stiction alone holds the pendulum, derived from the
    measured Coulomb loss (`FurutaParameters.stiction_hold_angle_rad`).

    Inside it the real pendulum returns no feedback, so a reward that keeps pushing for
    smaller angles is asking for something the hardware cannot report. This was a fixed
    0.535 degrees from the free-swing Coulomb of 1.07; the reconciled 0.65 puts it at
    0.325, and deriving it is what stops it going stale a second time."""

    rotor_travel_deadband_rad = 0.35
    """Free rotor travel before the travel term charges.

    Set when the manual's App. E listing was believed to clamp step rate up to a
    `MIN_POSSIBLE_SPEED`, so that a commanded stop would creep about 6.75 degrees over a
    30 s episode. The shipped `main.c` has no such floor (read 2026-09-06), so that
    rationale is gone and the deadband stands on a different one: it is the margin
    inside which experiment 05's seed 2 drifted to the travel bound unpenalised, the
    open weakness that write-up records. Re-deriving it is reward design and belongs
    with the next balance retrain, not a quiet edit here."""

    travel_governor_margin_rad = 2.2
    """Allowance for the stopping-point projection the governor term prices.

    Inside the pi travel bound with 0.94 rad to spare, and above the 1.92 rad the
    scripted governed pump uses (`scripts/scripted_swingup.py`), so the behaviour being
    paid for fits the bound and suffices for the task."""

    rew_scale_travel_governor = 0.0
    """Weight on the squared projected overrun past the governor margin. Zero disables
    the term. The travel bound as termination is one sparse signal at the end of an
    episode; this prices the same limit densely, every step, in the quantity a braking
    controller actually controls."""

    rew_scale_pump_power = 0.0
    """Weight on the instantaneous energy input, `action * pendulum_rate * cos(tilt)`,
    normalised by the actuator's full-scale input. Zero disables the term.

    An energy level term is blind to phase: a pump whose command agrees with the ideal
    `sign(rate * cos(tilt))` only part of the time still collects it, and can settle at
    an equilibrium short of the separatrix. This term pays the input itself, every
    step, so better reversal timing and a wider stroke both carry a dense gradient
    instead of waiting on an exploration accident."""

    rew_scale_swing_rate = 0.0
    """Ungated pendulum-rate cost, everywhere on the circle. Zero disables the term.

    The gated cost (`rew_scale_pendulum_rate`) prices fast arrivals inside the capture
    window and says nothing outside it, so a sustained swing that rides the energy
    term's plateau just under the separatrix collects alive plus energy forever and
    never has a reason to cross. This term makes perpetual motion pay for itself: at
    -0.005 a swing passing the bottom at 11 rad/s pays about 0.6 per step against the
    roughly 2.5 the swing collects, while a policy that arrives and holds stops paying
    it almost entirely. The pump's transient pays it for seconds; the hold repays it
    for the rest of the episode."""

    rew_scale_alive = 1.0
    rew_scale_upright = 1.0
    rew_scale_terminated = -2.0
    rew_scale_rotor_rate = 0.0
    """Charge for how fast the arm is turning, per (rad/s)^2 per step. Zero by default.

    The travel term charges for where the arm is; this charges for how fast it gets
    there. On the hardware the policy caught the pendulum and then held it by swinging
    the arm back and forth through whole turns, which the travel term prices only at its
    extremes and which a rate term prices continuously. Read from the actuator's own
    velocity rather than the estimator, since that is the quantity the drive holds."""

    rew_scale_rotor_travel = -0.05
    """Linear charge on arm excursion past `rotor_travel_deadband_rad`.

    Charged on excursion beyond a deadband rather than on absolute angle: an absolute
    charge prices off-centre parking forever with no way to discharge it, and what the
    hardware needs is bounded travel, not origin tracking."""

    rew_scale_action = -0.01
    squash_actions = False
    """Map the policy's output through `tanh` before the actuator sees it.

    The actuator clamps to `[-1, 1]`, and a clamp has no gradient outside itself: a mean
    of 10 and a mean of 1 drive the simulation the same, so nothing returns a drifting
    policy to the usable range, and a mean far off centre is a constant one-way push on
    the arm.

    `tanh` removes the region instead of charging for it. Balance keeps the clamp, so
    Experiment 05's results and its checkpoints stay valid."""

    rew_scale_action_excess = 0.0
    """Cost on the part of a command that runs past the actuator's rail.

    The actuator clamps to `[-1, 1]`, so a policy whose mean sits at 10 behaves exactly
    like one whose mean sits at 1, and nothing in the simulation objects. Balance never
    drifts far enough for that to matter, and a mean far off centre is a constant
    one-way push on the arm however it is clipped. The quadratic action cost is the
    wrong tool, because it also charges for the saturated bang-bang this task genuinely
    wants; this one is zero inside the rail."""
    rew_scale_action_rate = -0.01
    action_rate_gate_rad = math.pi
    """Tilt threshold inside which action-rate penalty applies (pi is everywhere).

    Restricts action smoothness penalties to the near-vertical hold region to
    suppress chatter without penalizing deliberate swing-up reversals.
    """
    rew_scale_pendulum_rate = -0.005
    rew_scale_energy = 0.0
    """Weight on the energy-shaping term. Zero for balance, which never needs it."""

    energy_excess_gain = 1.0
    """Penalty multiplier for energy exceeding the separatrix.

    Above 1, penalizes excess kinetic energy more steeply than energy deficits to
    discourage policies from becoming trapped in continuous over-the-top rotation.
    """

    balance_reset_fraction = 0.0
    """Fraction of resets drawn near vertical instead of from the wide spread.

    Swing-up only. Resetting uniformly around the circle sounds like it presents the
    top, and it does not present a *holdable* top: with the rate spread applied, 4.3
    percent of those resets are inside the recoverable set `|theta_dot + 7.351*theta| <
    1.011`, against 100 percent of the balance spread below. A policy given
    only unrecoverable starts at vertical learns that vertical is where episodes are
    lost. These resets use experiment 05's values, which are recoverable by
    construction."""

    balance_reset_angle_range = [-0.035, 0.035]
    balance_reset_rate_range = [-0.25, 0.25]

    balance_reset_in_recoverable_set = False
    """Sample near-vertical resets across the recoverable set.

    Samples tilt, unstable mode, and moving rotor states to prepare the policy for
    high-velocity swing-up handovers rather than stationary upright balance.
    """

    balance_reset_mode_range = [-0.9, 0.9]
    """Unstable-mode range for near-vertical resets (rad/s at 11.78 rad/s^2 bound)."""

    balance_reset_rotor_angle_range = [-0.5, 0.5]
    balance_reset_rotor_rate_range = [-0.5, 0.5]
    """Rotor angle and rate ranges for recoverable near-vertical resets."""

    hanging_reset_fraction = 0.0
    """Fraction of resets drawn near hanging, which is the task being scored.

    Swing-up only. Sampling the pendulum uniformly around the circle leaves only a
    sliver of episodes starting at the bottom, and a policy trained that way is fitted
    to the states it saw: an opening stroke that suits a pendulum already part way up
    runs the arm out of travel from rest."""

    hanging_reset_angle_range = [-0.4, 0.4]
    hanging_reset_rate_range = [-1.0, 1.0]
    """Rate spread for the hanging share, kept slow so those starts are starts.

    The wide share's rate range is set high on purpose, to cover the energies a swing
    passes through. Letting that reach the hanging share would mean the episodes
    standing in for the task began with most of the swing's energy already in them."""

    rew_scale_capture = 0.0
    """Weight on the capture well, a second upright term inside the rate gate.

    Only swing-up sets this. Balance already uses the quadratic as its upright term, so
    a second copy would double one weight and nothing else."""

    pendulum_rate_gate_rad = math.pi
    """Tilt inside which the pendulum-rate cost applies.

    Balance can charge for pendulum speed everywhere, because every speed it sees is
    speed it wants gone. Swing-up cannot: reaching vertical from hanging requires about
    14.7 rad/s through the bottom, and at the balance scale that costs 1.08 per step,
    which is more than the upright term pays at vertical. Charging it everywhere prices
    the only route to the target above the target.

    Default `pi` covers every reachable tilt, so balance keeps the Milestone 05
    behaviour."""


class FurutaEnv(DirectRLEnv):
    """Rotary inverted pendulum with an acceleration-commanded rotor."""

    cfg: FurutaEnvCfg

    def __init__(self, cfg: FurutaEnvCfg, render_mode: str | None = None, **kwargs):
        """Set up joint indices, the actuator model and the rate estimators."""
        super().__init__(cfg, render_mode, **kwargs)

        self._rotor_idx, _ = self.robot.find_joints(ROTOR_JOINT)
        self._pendulum_idx, _ = self.robot.find_joints(PENDULUM_JOINT)

        actuator_params = PARAMS
        if self.cfg.max_acceleration_rad_s2 is not None:
            actuator_params = replace(
                PARAMS, max_acceleration_rad_s2=self.cfg.max_acceleration_rad_s2
            )
        self._actuator = AccelerationCommandActuator(
            actuator_params, num_envs=self.num_envs, device=self.device
        )
        self._rotor_target = torch.zeros(self.num_envs, device=self.device)
        self._rotor_target_prev = torch.zeros(self.num_envs, device=self.device)
        self._substep = 0

        # Pivot losses the drive cannot express. Inactive when both constants are zero,
        # and then `_apply_action` never writes an effort target at all.
        self._dissipation = PivotDissipation(
            PARAMS,
            coulomb_deg_per_half_swing=self.cfg.pivot_coulomb_deg_per_half_swing,
            drag_coeff=self.cfg.pivot_drag_coeff,
        )
        self._pivot_torque = torch.zeros(self.num_envs, 1, device=self.device)

        # Rate estimators over the quantized angles. `step_dt` rather than the config's
        # control period: they are equal only while decimation happens to be 2.
        self._pendulum_rate = VelocitySlopeEstimator(
            self.cfg.velocity_window, self.step_dt, self.num_envs, self.device
        )
        self._rotor_rate = VelocitySlopeEstimator(
            self.cfg.velocity_window,
            self.step_dt,
            self.num_envs,
            self.device,
            wrap=False,
        )

        # Last action, for the action-rate penalty. `_action` is written every
        # `_pre_physics_step` and `_pendulum_vel` every `_get_observations`; both are
        # seeded here because the first reward is computed before either has run.
        self._prev_action = torch.zeros(self.num_envs, device=self.device)
        self._action = torch.zeros(self.num_envs, device=self.device)
        self._pendulum_vel = torch.zeros(self.num_envs, device=self.device)

        # Per-environment episode duration in steps, randomized by jitter.
        self._episode_steps = torch.full(
            (self.num_envs,), int(self.max_episode_length), device=self.device
        )

        # From-hanging evaluation diagnostics: tracking peak energy fraction relative
        # to separatrix, minimum upright approach, and recoverable set entries.
        self._from_hanging = torch.zeros(
            self.num_envs, dtype=torch.bool, device=self.device
        )
        self._peak_energy_frac = torch.zeros(self.num_envs, device=self.device)
        self._min_tilt = torch.full((self.num_envs,), math.pi, device=self.device)
        self._entered_set = torch.zeros(
            self.num_envs, dtype=torch.bool, device=self.device
        )
        # Consecutive steps within the capture gate (hold duration tracking).
        self._gate_streak = torch.zeros(self.num_envs, device=self.device)
        self._gate_streak_max = torch.zeros(self.num_envs, device=self.device)
        self._hanging_peak_frac = torch.zeros((), device=self.device)
        self._hanging_min_tilt_deg = torch.full((), 180.0, device=self.device)
        self._hanging_gate_frac = torch.zeros((), device=self.device)
        self._hanging_set_frac = torch.zeros((), device=self.device)
        self._hanging_held_frac = torch.zeros((), device=self.device)

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

        The firmware updates its step rate at 500 Hz and emits steps between updates, so
        the actuator integrates at the control rate while `_apply_action` runs per
        substep.
        """
        # Cloned, not kept. An evaluation loop runs the policy under
        # `torch.inference_mode()`, and holding its output tensor makes the reset's
        # in-place write to `_prev_action` illegal once an episode ends mid-rollout.
        action = actions.squeeze(-1).clone()
        self._rotor_target_prev = self._rotor_target.clone()
        self._substep = 0

        if self.cfg.rotor_command_mode == "position":
            # Replay: the action is where the rotor should be, not how hard to push.
            # The velocity is kept consistent so the integrator is in step if a caller
            # switches back, and so the rate estimator sees a sane rotor.
            velocity = (action - self._actuator.position) / self.step_dt
            self._actuator.reset(position=action, velocity=velocity)
            self._rotor_target = self._actuator.quantized_position()
            self._action = action
            return

        if self.cfg.squash_actions:
            action = torch.tanh(action)
        self._rotor_target = self._actuator.step(action, self.step_dt)
        self._action = action

    def _apply_action(self) -> None:
        """Drive the rotor, and add the pivot losses PhysX cannot carry in the drive.

        Runs once per physics substep, which is what the Coulomb term needs: its cap is
        sized against the substep, and `joint_vel` here is the value the solver is about
        to integrate from.
        """
        target = self._rotor_target
        if self.cfg.rotor_target_interpolation:
            # Walk position target across substeps with velocity feedforward (ADR-0006).
            self._substep = min(self._substep + 1, self.cfg.decimation)
            fraction = self._substep / self.cfg.decimation
            target = (
                self._rotor_target_prev
                + (self._rotor_target - self._rotor_target_prev) * fraction
            )
            self.robot.set_joint_velocity_target(
                self._actuator.velocity.unsqueeze(-1), joint_ids=self._rotor_idx
            )
        self.robot.set_joint_position_target(
            target.unsqueeze(-1), joint_ids=self._rotor_idx
        )
        if self._dissipation.active:
            pivot_vel = self.robot.data.joint_vel[:, self._pendulum_idx[0]]
            self._pivot_torque[:, 0] = self._dissipation.torque(
                pivot_vel, self.physics_dt
            )
            self.robot.set_joint_effort_target(
                self._pivot_torque, joint_ids=self._pendulum_idx
            )

    # Observation, reward, termination.

    def _quantized_angles(self) -> tuple[torch.Tensor, torch.Tensor]:
        """Pendulum and rotor angles as the hardware would report them.

        The pendulum passes through the encoder lattice. The rotor has no
        position sensor at all, so what the firmware knows is the commanded
        position it dead-reckoned, which is what the actuator holds.
        """
        pendulum = self.robot.data.joint_pos[:, self._pendulum_idx[0]]
        encoder = PARAMS.rad_per_encoder_count
        return torch.round(
            pendulum / encoder
        ) * encoder, self._actuator.quantized_position()

    def _get_observations(self) -> dict:
        pendulum, rotor = self._quantized_angles()

        # The estimators hold a window and must advance exactly once per control step.
        # Isaac Lab calls dones and rewards before this hook, so this is the only place
        # they are updated, and the reward reads the rate this leaves behind.
        pendulum_vel = self._pendulum_rate.update(pendulum)
        rotor_vel = self._rotor_rate.update(rotor)
        self._pendulum_vel = pendulum_vel

        # Angle measured from upright. The asset hangs at zero, so upright is pi.
        upright = wrap_to_pi(pendulum - math.pi)

        obs = torch.stack(
            [torch.cos(upright), torch.sin(upright), pendulum_vel, rotor, rotor_vel],
            dim=-1,
        )
        return {"policy": obs}

    def _get_rewards(self) -> torch.Tensor:
        pendulum, rotor = self._quantized_angles()
        upright = wrap_to_pi(pendulum - math.pi)

        # Quadratic in tilt, normalized so the term runs 1.0 at upright to 0.0 at the
        # termination angle. The cartpole template this environment started from uses
        # cos(theta), which suits a pole swinging through large angles. Confined to the
        # 20 degrees this task lives in, cos varies by 0.058 in total against an alive
        # term of 1.0 per step, so it carries almost no gradient. Measured: 33
        # iterations with cos held episode length flat at 216 steps of 5000.
        #
        # The deadband stops the term chasing tilt reduction the hardware cannot report.
        # Below it the real pendulum gets no feedback, so the gradient points nowhere.
        effective = torch.clamp(
            torch.abs(upright) - self.cfg.upright_deadband_rad, min=0.0
        )

        # Excursion past a deadband, not absolute angle. Penalizing absolute angle
        # leaves a policy parked off-origin paying forever with no way to discharge the
        # debt, while the requirement is only that rotor travel stay bounded.
        excursion = torch.clamp(
            torch.abs(rotor) - self.cfg.rotor_travel_deadband_rad, min=0.0
        )

        action_rate = self._action - self._prev_action
        self._prev_action = self._action

        # Total mechanical energy relative to the upright equilibrium, per unit of the
        # pendulum's moment of inertia, so it is written entirely in `omega_g^2`, the
        # measured gravitational stiffness. Zero at upright and at rest,
        # and -2*omega_g^2 hanging at rest, so dividing by 2*omega_g^2 puts it on
        # [-1, 0] and makes the scale comparable to the other terms.
        omega_g_sq = PARAMS.omega_g_squared
        energy = 0.5 * self._pendulum_vel.pow(2) + omega_g_sq * (
            torch.cos(upright) - 1.0
        )
        energy_error = energy / (2.0 * omega_g_sq)
        # Peak separatrix energy fraction and closest upright approach for diagnostics.
        self._peak_energy_frac = torch.maximum(
            self._peak_energy_frac, 1.0 + energy_error
        )
        self._min_tilt = torch.minimum(self._min_tilt, torch.abs(upright))
        # Recoverable set envelope scaled to current actuator acceleration bound.
        window = (
            RECOVERABLE_MODE_RAD_S
            * self._actuator.max_acceleration
            / PARAMS.max_acceleration_rad_s2
        )
        mode = self._pendulum_vel + math.sqrt(omega_g_sq) * upright
        in_gate = torch.abs(upright) < self.cfg.pendulum_rate_gate_rad
        self._entered_set |= in_gate & (torch.abs(mode) < window)
        self._gate_streak = torch.where(
            in_gate, self._gate_streak + 1.0, torch.zeros_like(self._gate_streak)
        )
        self._gate_streak_max = torch.maximum(self._gate_streak_max, self._gate_streak)

        # Where the arm ends up if it brakes now, signed: the stopping distance at the
        # actuator's full deceleration, added to the current angle. The scripted probe
        # (`scripts/scripted_swingup.py`) swings up inside a 2 rad allowance by refusing
        # to let this projection cross it, and the trained policies only ever met the
        # travel limit as a termination, one sparse signal at the end of an episode.
        # Pricing the projection makes braking pay every step. The rate is the
        # actuator integrator's own, which the rotor tracks to 0.2 microsteps.
        rotor_rate = self._actuator.velocity
        stopping_point = rotor + rotor_rate * torch.abs(rotor_rate) / (
            2.0 * self._actuator.max_acceleration
        )
        governor_overrun = torch.clamp(
            torch.abs(stopping_point) - self.cfg.travel_governor_margin_rad, min=0.0
        )

        terms = {
            "alive": self.cfg.rew_scale_alive * (1.0 - self.reset_terminated.float()),
            "terminated": self.cfg.rew_scale_terminated * self.reset_terminated.float(),
            "upright": self.cfg.rew_scale_upright
            * (
                torch.cos(effective)
                if self.cfg.upright_reward == "cosine"
                else 1.0 - (effective / self.cfg.max_pendulum_angle_rad).pow(2)
            ),
            "rotor_travel": self.cfg.rew_scale_rotor_travel * excursion,
            "rotor_rate": self.cfg.rew_scale_rotor_rate
            * self._actuator.velocity.pow(2),
            "travel_governor": self.cfg.rew_scale_travel_governor
            * governor_overrun.pow(2),
            "swing_rate": self.cfg.rew_scale_swing_rate * self._pendulum_vel.pow(2),
            "pump_power": self.cfg.rew_scale_pump_power
            * self._action
            * self._pendulum_vel
            * torch.cos(upright),
            "action": self.cfg.rew_scale_action * self._action.pow(2),
            "action_excess": self.cfg.rew_scale_action_excess
            * (self._action.abs() - 1.0).clamp(min=0.0).pow(2),
            "action_rate": self.cfg.rew_scale_action_rate
            * action_rate.pow(2)
            * (torch.abs(upright) < self.cfg.action_rate_gate_rad).float(),
            # Distance from the energy of the upright equilibrium, normalised to run
            # -1 when hanging at rest and 0 on the separatrix, the trajectory that
            # arrives at vertical with no speed left. A height reward alone is happy
            # with a sustained swing that never captures. This term is maximised only
            # at the energy that reaches the top, so a limit cycle below it is
            # penalised however high its average height.
            #
            # Offset to pay 0 hanging and 1 on the separatrix rather than -1 and 0.
            # The gradient is identical and the level is not: charging for hanging
            # makes a hanging episode cost more the longer it lasts, and running the
            # arm into its travel bound becomes a way out.
            "energy": self.cfg.rew_scale_energy
            * (
                1.0
                - torch.where(
                    energy_error > 0,
                    self.cfg.energy_excess_gain * energy_error,
                    -energy_error,
                )
            ),
            # A quadratic well over the balance envelope, on top of the cosine.
            # Experiment 05 measured `cos` moving 0.058 across 20 degrees, which is why
            # balance does not use it; that flatness does not go away because the
            # task around it got bigger. The cosine spans the half turn and gets the
            # pendulum to the top, and inside the last 20 degrees it stops saying
            # anything, so a policy that arrives has no reason to settle. This term
            # supplies the gradient there and is zero everywhere else.
            "capture": self.cfg.rew_scale_capture
            * (
                1.0
                - (effective / self.cfg.pendulum_rate_gate_rad).clamp(max=1.0).pow(2)
            )
            * (torch.abs(upright) < self.cfg.pendulum_rate_gate_rad).float(),
            # Gated, so swing-up is not charged for the speed it needs. Inside the
            # gate the cost still discourages coasting through vertical instead of
            # stopping there, which is the failure a bare height reward invites.
            "pendulum_rate": self.cfg.rew_scale_pendulum_rate
            * self._pendulum_vel.pow(2)
            * (torch.abs(upright) < self.cfg.pendulum_rate_gate_rad).float(),
        }

        # Per-term means, so a run that stalls can be read rather than guessed at. The
        # saturation fraction is the direct evidence on whether the conservative
        # 11.78 rad/s^2 acceleration bound is costing performance.
        log = {f"reward/{name}": value.mean() for name, value in terms.items()}
        log["action/saturated_fraction"] = (self._action.abs() >= 1.0).float().mean()
        log["state/upright_abs_deg"] = torch.rad2deg(torch.abs(upright)).mean()
        log["state/rotor_abs_rad"] = torch.abs(rotor).mean()
        log["hanging/peak_energy_frac"] = self._hanging_peak_frac
        log["hanging/min_tilt_deg"] = self._hanging_min_tilt_deg
        log["hanging/reached_gate_frac"] = self._hanging_gate_frac
        log["hanging/entered_set_frac"] = self._hanging_set_frac
        log["hanging/held_half_s_frac"] = self._hanging_held_frac
        self.extras["log"] = log

        return torch.stack(list(terms.values()), dim=0).sum(dim=0)

    def _get_dones(self) -> tuple[torch.Tensor, torch.Tensor]:
        pendulum, rotor = self._quantized_angles()
        upright = wrap_to_pi(pendulum - math.pi)
        time_out = self.episode_length_buf >= self._episode_steps - 1
        out_of_bounds = torch.abs(rotor) > self.cfg.max_rotor_angle_rad
        fallen = torch.abs(upright) > self.cfg.max_pendulum_angle_rad
        return out_of_bounds | fallen, time_out

    def _reset_idx(self, env_ids: Sequence[int] | None) -> None:
        if env_ids is None:
            env_ids = self.robot._ALL_INDICES
        super()._reset_idx(env_ids)

        # Compute diagnostics for finished episodes that started hanging.
        ending = self._from_hanging[env_ids]
        if bool(ending.any()):
            peaks = self._peak_energy_frac[env_ids][ending]
            closest = self._min_tilt[env_ids][ending]
            self._hanging_peak_frac = peaks.mean()
            self._hanging_min_tilt_deg = torch.rad2deg(closest.mean())
            self._hanging_gate_frac = (
                (closest < self.cfg.pendulum_rate_gate_rad).float().mean()
            )
            self._hanging_set_frac = self._entered_set[env_ids][ending].float().mean()
            held = self._gate_streak_max[env_ids][ending] >= 0.5 / self.step_dt
            self._hanging_held_frac = held.float().mean()
        self._peak_energy_frac[env_ids] = 0.0
        self._min_tilt[env_ids] = math.pi
        self._entered_set[env_ids] = False
        self._gate_streak[env_ids] = 0.0
        self._gate_streak_max[env_ids] = 0.0
        self._from_hanging[env_ids] = False

        if self.cfg.episode_length_jitter > 0.0:
            full = int(self.max_episode_length)
            shortest = int(round(full * (1.0 - self.cfg.episode_length_jitter)))
            self._episode_steps[env_ids] = torch.randint(
                shortest, full + 1, (len(env_ids),), device=self.device
            )

        joint_pos = self.robot.data.default_joint_pos[env_ids].clone()
        joint_vel = self.robot.data.default_joint_vel[env_ids].clone()
        shape = joint_pos[:, self._pendulum_idx].shape
        device = joint_pos.device

        # The asset hangs at zero, so upright is pi. The swing-up task resets hanging.
        datum = math.pi if self.cfg.reset_upright else 0.0
        joint_pos[:, self._pendulum_idx] = datum + sample_uniform(
            self.cfg.initial_pendulum_angle_range[0],
            self.cfg.initial_pendulum_angle_range[1],
            shape,
            device,
        )
        joint_vel[:, self._pendulum_idx] = sample_uniform(
            self.cfg.initial_pendulum_rate_range[0],
            self.cfg.initial_pendulum_rate_range[1],
            shape,
            device,
        )
        if self.cfg.reset_in_recoverable_set:
            # rate = mode - omega_g * tilt, with tilt measured from upright. The joint
            # angle above is `datum + tilt`, so subtracting the datum recovers the tilt.
            omega_g = math.sqrt(PARAMS.omega_g_squared)
            tilt = joint_pos[:, self._pendulum_idx] - datum
            mode = sample_uniform(
                self.cfg.reset_mode_range[0],
                self.cfg.reset_mode_range[1],
                shape,
                device,
            )
            joint_vel[:, self._pendulum_idx] = mode - omega_g * tilt

        # Split the batch three ways off one draw, so the shares cannot overlap: the
        # bottom slice starts near hanging, which is the task the gate scores, the top
        # slice starts where the pendulum can actually be held, and what is left keeps
        # the wide spread that teaches the states in between.
        #
        # Both extremes are needed and for different reasons. Without the hanging
        # share the batch barely contains the state being measured. Without the
        # near-vertical share the policy never sees a holdable top at all,
        # since only 4.3 percent of the wide spread is inside the recoverable set.
        draw = torch.rand(shape, device=device)

        if self.cfg.hanging_reset_fraction > 0.0:
            down = draw < self.cfg.hanging_reset_fraction
            self._from_hanging[env_ids] = down.squeeze(-1)
            joint_pos[:, self._pendulum_idx] = torch.where(
                down,
                sample_uniform(
                    self.cfg.hanging_reset_angle_range[0],
                    self.cfg.hanging_reset_angle_range[1],
                    shape,
                    device,
                ),
                joint_pos[:, self._pendulum_idx],
            )
            joint_vel[:, self._pendulum_idx] = torch.where(
                down,
                sample_uniform(
                    self.cfg.hanging_reset_rate_range[0],
                    self.cfg.hanging_reset_rate_range[1],
                    shape,
                    device,
                ),
                joint_vel[:, self._pendulum_idx],
            )

        near = torch.zeros_like(draw, dtype=torch.bool)
        if self.cfg.balance_reset_fraction > 0.0:
            near = draw >= (1.0 - self.cfg.balance_reset_fraction)
            near_tilt = sample_uniform(
                self.cfg.balance_reset_angle_range[0],
                self.cfg.balance_reset_angle_range[1],
                shape,
                device,
            )
            if self.cfg.balance_reset_in_recoverable_set:
                # Unstable mode sampled directly; rate derives from mode and tilt.
                omega_g = math.sqrt(PARAMS.omega_g_squared)
                mode = sample_uniform(
                    self.cfg.balance_reset_mode_range[0],
                    self.cfg.balance_reset_mode_range[1],
                    shape,
                    device,
                )
                near_rate = mode - omega_g * near_tilt
            else:
                near_rate = sample_uniform(
                    self.cfg.balance_reset_rate_range[0],
                    self.cfg.balance_reset_rate_range[1],
                    shape,
                    device,
                )
            joint_pos[:, self._pendulum_idx] = torch.where(
                near, math.pi + near_tilt, joint_pos[:, self._pendulum_idx]
            )
            joint_vel[:, self._pendulum_idx] = torch.where(
                near, near_rate, joint_vel[:, self._pendulum_idx]
            )

        rotor_angle = sample_uniform(
            self.cfg.initial_rotor_angle_range[0],
            self.cfg.initial_rotor_angle_range[1],
            shape,
            device,
        )
        rotor_rate = sample_uniform(
            self.cfg.initial_rotor_rate_range[0],
            self.cfg.initial_rotor_rate_range[1],
            shape,
            device,
        )
        if self.cfg.balance_reset_in_recoverable_set and bool(near.any()):
            # Displace and move rotor to emulate post-swing-up handover states.
            rotor_angle = torch.where(
                near,
                sample_uniform(
                    self.cfg.balance_reset_rotor_angle_range[0],
                    self.cfg.balance_reset_rotor_angle_range[1],
                    shape,
                    device,
                ),
                rotor_angle,
            )
            rotor_rate = torch.where(
                near,
                sample_uniform(
                    self.cfg.balance_reset_rotor_rate_range[0],
                    self.cfg.balance_reset_rotor_rate_range[1],
                    shape,
                    device,
                ),
                rotor_rate,
            )
        joint_pos[:, self._rotor_idx] = rotor_angle
        joint_vel[:, self._rotor_idx] = rotor_rate

        self.robot.write_joint_state_to_sim(joint_pos, joint_vel, None, env_ids)

        # The rotor joint follows a stiff position target, so the actuator's
        # dead-reckoned state has to move with the joint. Setting one without the other
        # is a step error the drive closes at full authority on the first substep.
        self._actuator.reset(env_ids, rotor_angle.squeeze(-1), rotor_rate.squeeze(-1))
        self._rotor_target[env_ids] = self._actuator.quantized_position()[env_ids]
        self._rotor_target_prev[env_ids] = self._rotor_target[env_ids]
        self._prev_action[env_ids] = 0.0

        # Seed estimator buffers from quantized state to eliminate reset transients.
        encoder = PARAMS.rad_per_encoder_count
        pendulum = joint_pos[:, self._pendulum_idx[0]]
        self._pendulum_rate.reset(
            env_ids,
            torch.round(pendulum / encoder) * encoder,
            joint_vel[:, self._pendulum_idx[0]],
        )
        self._rotor_rate.reset(
            env_ids,
            self._actuator.quantized_position()[env_ids],
            rotor_rate.squeeze(-1),
        )

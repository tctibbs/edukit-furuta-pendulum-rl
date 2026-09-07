"""The stock firmware's swing-up, batched: the L6474 position move and the kick law.

The Edukit firmware does not pump the pendulum with an acceleration command. It fires
blocking position moves through the L6474 driver's speed profile and times them off the
encoder count with a zero-crossing detector, and its 500 Hz loop does not run while a
move is in flight (ADR-0004). A scripted swing-up that claims to reproduce the board's
arrival has to run that law, over integer counts, with the same frozen loop.

Two pieces, both free of any simulator import so they run under pytest anywhere:

- `profile_displacement`, `profile_velocity` and `profile_duration` are the driver's
  move profile for `N` microsteps. The step rate starts at MIN_SPEED at the first pulse,
  ramps at MAX_ACCEL to the midpoint, ramps back to MIN_SPEED at the last pulse and
  stops; above 560 microsteps the ramp reaches MAX_SPEED and the move cruises. The
  constants come from `config/edukit.yaml` through `FurutaParameters`.
- `KickLaw` is the swing-up loop itself, one state per environment. It reads integer
  encoder counts from hanging, never the true angle, and returns the rotor angle the
  driver would be at by the end of the control step.

The profile is written as continuous piecewise-constant acceleration rather than a
pulse-by-pulse emulation of the driver's integer arithmetic. Emulating the pulses gives
185.06 ms for a 200-microstep move when a step is taken at the start of each timer
period and 186.31 ms when it is taken at the end; the continuous form gives 185.49 and
the bench measured 185.2 over 248 kicks. All three agree to under a millisecond on a
move the pendulum integrates over 185 ms, and the continuous form is the one that
differentiates cleanly for the planar model.

Every rule below cites the firmware source under `firmware/`, which is third-party and
not committed: `Src/main.c` for the loop and the detector, `Inc/edukit_system.h` for the
constants, `Drivers/BSP/Components/l6474/l6474.c` for the profile.
"""

from __future__ import annotations

import math

import torch

from furuta.parameters import FurutaParameters

FORWARD = 1
"""The driver's FORWARD direction, which the logged trace shows as increasing rotor
angle: the first kick took the dead-reckoned position from 150 to 350 microsteps."""

BACKWARD = -1

INITIAL_MOVE_MICROSTEPS = 150
"""The blocking move the firmware makes before its loop starts, `main.c:1750`. Its
deflection is what the first poll sees; on the logged trace that poll fired kick 1."""

STAGE_BANDS_COUNTS = (600, 1000)
"""Peak counts dividing the three kick amplitudes, `main.c:1804-1810`."""

STAGE_GATE_KICKS = 4
"""The schedule is consulted only once more than this many kicks have fired,
`main.c:1803`."""


def _move_terms(
    params: FurutaParameters, steps: torch.Tensor
) -> tuple[torch.Tensor, ...]:
    """Per-move constants of the profile, elementwise over `steps`.

    Returns `(t_ramp, t_cruise, total, v_peak, s_ramp, s_total)` in seconds, rad/s and
    radians. A move short enough that the ramp never reaches MAX_SPEED is triangular:
    the peak is where `v^2 = v0^2 + a * s_total`, half the distance each way. A longer
    one cruises at MAX_SPEED between two fixed ramps, which is the driver's own split
    (`L6474_ComputeSpeedProfile`, `l6474.c:1375`).
    """
    v0 = params.profile_min_speed_rad_s
    a = params.max_acceleration_rad_s2
    v_max = params.profile_max_speed_rad_s
    s_total = steps * params.rad_per_microstep
    v_peak = torch.sqrt(v0 * v0 + a * s_total).clamp(max=v_max)
    t_ramp = (v_peak - v0) / a
    s_ramp = (v_peak * v_peak - v0 * v0) / (2.0 * a)
    t_cruise = ((s_total - 2.0 * s_ramp) / v_peak).clamp(min=0.0)
    total = 2.0 * t_ramp + t_cruise
    return t_ramp, t_cruise, total, v_peak, s_ramp, s_total


def _as_tensor(steps: torch.Tensor | int, like: torch.Tensor) -> torch.Tensor:
    if isinstance(steps, torch.Tensor):
        return steps.to(device=like.device, dtype=like.dtype)
    return torch.tensor(float(steps), device=like.device, dtype=like.dtype)


def profile_displacement(
    t: torch.Tensor, steps: torch.Tensor | int, params: FurutaParameters
) -> torch.Tensor:
    """Rotor displacement in radians `t` seconds into a move of `steps` microsteps.

    Zero before the move, `steps * rad_per_microstep` at and after its end, and in
    between the integral of a speed that starts at MIN_SPEED, ramps up, holds (only
    above 560 microsteps) and ramps back down. Broadcasts over `t` and `steps`.
    """
    steps_t = _as_tensor(steps, t)
    t_ramp, t_cruise, total, v_peak, s_ramp, s_total = _move_terms(params, steps_t)
    v0 = params.profile_min_speed_rad_s
    a = params.max_acceleration_rad_s2
    tau = torch.clamp(t, min=torch.zeros_like(t)).minimum(total)
    back = total - tau
    up = v0 * tau + 0.5 * a * tau * tau
    down = s_total - (v0 * back + 0.5 * a * back * back)
    cruise = s_ramp + v_peak * (tau - t_ramp)
    d = torch.where(tau < t_ramp, up, torch.where(back < t_ramp, down, cruise))
    return torch.where(t >= total, s_total, d)


def profile_velocity(
    t: torch.Tensor, steps: torch.Tensor | int, params: FurutaParameters
) -> torch.Tensor:
    """Rotor speed in rad/s `t` seconds into a move; zero outside `[0, duration)`.

    Right-continuous at both ends: the speed is MIN_SPEED at `t = 0` and zero at the
    end, which is the step the driver applies at its first pulse and the dead stop it
    makes at its last (`L6474_StartMovement`, `l6474.c:1784`; `L6474_HardStop` from the
    step clock handler at `l6474.c:1892`).
    """
    steps_t = _as_tensor(steps, t)
    t_ramp, _, total, v_peak, _, _ = _move_terms(params, steps_t)
    v0 = params.profile_min_speed_rad_s
    a = params.max_acceleration_rad_s2
    back = total - t
    v = torch.where(
        t < t_ramp, v0 + a * t, torch.where(back < t_ramp, v0 + a * back, v_peak)
    )
    inside = (t >= 0.0) & (t < total)
    return torch.where(inside, v, torch.zeros_like(v))


def profile_duration(steps: int, params: FurutaParameters) -> float:
    """Seconds from the first pulse to the last for a move of `steps` microsteps."""
    total = _move_terms(params, torch.tensor(float(steps), dtype=torch.float64))[2]
    return float(total)


class KickLaw:
    """The firmware's swing-up loop over integer encoder counts, one state per env.

    `step` is called once per control period with the count each environment's loop
    would read at that instant. Environments inside a move are frozen exactly as the
    board is inside `BSP_MotorControl_WaitWhileActive`: the detector does not see their
    counts, no command is issued, and the first count after the move ends is the
    re-read the firmware makes on return (`main.c:1816`).

    The detector (`encoder_position_read`, `main.c:3162`):

    - A zero crossing is `(count ^ previous) < 0`, `oppositeSigns` at `main.c:3229`.
      That is true when the count goes from zero to negative and false from zero to
      positive, so a crossing through an exact zero sample is seen one sample late in
      one direction and on the zero in the other. It re-arms the peak flag and requests
      a kick.
    - Until a peak is seen, each poll updates two running maxima of `|count|`: one for
      the current half swing and one carried to the amplitude schedule. The first poll
      whose magnitude falls short of the half-swing maximum is the peak; it sets
      `peaked` and clears `handled_peak`.

    The loop (`main.c:1763-1830`): after the poll, a pending crossing fires a blocking
    move of `amplitude` microsteps in `direction`, then, once more than four kicks have
    fired, picks the next amplitude from the previous half swing's peak against the 600
    and 1000 count bands. An unhandled peak flips the direction and clears the
    half-swing maximum. The handover test that breaks the loop is the caller's: it
    depends on the tilt from upright, which this class deliberately never sees.

    Time zero here is the start of the initial 150-microstep move. The logged trace's
    clock starts when that move completes, `profile_duration(150)` later.
    """

    def __init__(
        self,
        params: FurutaParameters,
        num_envs: int,
        dt: float,
        device: str | torch.device = "cpu",
        initial_microsteps: int = INITIAL_MOVE_MICROSTEPS,
    ) -> None:
        """Create swing-up state for `num_envs` loops polled every `dt` seconds."""
        self._p = params
        self.dt = float(dt)
        self.num_envs = num_envs
        self.device = torch.device(device)
        self._initial = int(initial_microsteps)
        self._amplitudes = torch.tensor(
            params.kick_microsteps, dtype=torch.long, device=self.device
        )
        self.log: list[tuple[int, int, float, int, int]] = []
        """Every move begun, as `(env, index, t_s, sign, microsteps)`. Index 0 is the
        initial move; in-loop kicks count from 1, matching the logged trace."""
        self.reset()

    def _long(self, value: int = 0) -> torch.Tensor:
        return torch.full((self.num_envs,), value, dtype=torch.long, device=self.device)

    def _bool(self) -> torch.Tensor:
        return torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)

    def _float(self, value: float = 0.0, dtype=torch.float32) -> torch.Tensor:
        return torch.full((self.num_envs,), value, dtype=dtype, device=self.device)

    def reset(self, position: torch.Tensor | float = 0.0) -> None:
        """Put every loop at its start, with the rotor at rest at `position` radians.

        Mirrors the initialisation block at `main.c:1730-1739`: maxima zero, no peak,
        no crossing, no kicks, stage 0 amplitude, direction FORWARD. The previous count
        is zero, which is what the pre-loop reads leave behind after the encoder is
        zeroed at the settled hanging position (`main.c:1425`).
        """
        self.previous = self._long()
        self.peaked = self._bool()
        self.handled_peak = self._bool()
        self.zero_crossed = self._bool()
        self.max_since_crossing = self._long()
        self.global_max = self._long()
        self.previous_global_max = self._long()

        self.direction = self._long(FORWARD)
        self.amplitude = self._long(int(self._p.kick_microsteps[0]))
        self.stage_count = self._long()
        self.kicks = self._long()

        self.position = self._float() + position
        self.move_origin = self._float()
        self.move_sign = self._float()
        self.move_steps = self._long()
        self.move_start = self._float(math.inf, torch.float64)
        self.move_end = self._float(math.inf, torch.float64)
        self._started = False
        self.log.clear()

    # Queries.

    def awake(self, t: float) -> torch.Tensor:
        """Environments whose loop polls at time `t`, that is, not inside a move.

        The caller runs the firmware's handover test on exactly these, before `step`,
        because the board tests it after the poll and before any kick (`main.c:1786`).
        """
        if not self._started:
            return self._bool()
        return t >= self.move_end

    # The loop.

    def step(
        self, counts: torch.Tensor, t: float, active: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Advance every loop to time `t` given the counts read there.

        Returns the rotor angle each environment should reach by `t + dt`, in radians,
        and the mask of environments whose rotor is moving during that interval. An
        environment outside `active` is frozen: no poll, no kick, rotor held. The
        caller passes the ones it has handed over or that have terminated.
        """
        counts = counts.to(device=self.device, dtype=torch.long)
        if active is None:
            active = ~self._bool()

        if not self._started:
            # The board moves before it ever polls (`main.c:1749-1751`), so the first
            # call starts the initial move for everyone and reads nothing.
            self._started = True
            everyone = ~self._bool()
            self._begin(
                everyone,
                self._long(FORWARD),
                self._long(self._initial),
                t,
                self._long(),
            )
            return self._targets(t)

        awake = active & (t >= self.move_end)
        self._poll(counts, awake)
        fire = awake & self.zero_crossed
        self.zero_crossed = self.zero_crossed & ~fire
        self._begin(fire, self.direction, self.amplitude, t, self.kicks + 1)
        self._schedule(fire)
        self._handle_peak(awake)
        return self._targets(t)

    def _poll(self, counts: torch.Tensor, awake: torch.Tensor) -> None:
        """`encoder_position_read` for the environments that are polling."""
        crossing = awake & (torch.bitwise_xor(counts, self.previous) < 0)
        self.peaked = self.peaked & ~crossing
        self.zero_crossed = self.zero_crossed | crossing

        track = awake & ~self.peaked
        magnitude = counts.abs()
        bigger_global = track & (magnitude >= self.global_max.abs())
        self.global_max = torch.where(bigger_global, counts, self.global_max)
        bigger = track & (magnitude >= self.max_since_crossing.abs())
        self.max_since_crossing = torch.where(bigger, counts, self.max_since_crossing)
        new_peak = track & ~bigger
        self.peaked = self.peaked | new_peak
        self.handled_peak = self.handled_peak & ~new_peak

        self.previous = torch.where(awake, counts, self.previous)

    def _schedule(self, fire: torch.Tensor) -> None:
        """The amplitude selection that follows a kick, `main.c:1801-1815`."""
        fired = fire.long()
        self.stage_count = self.stage_count + fired
        self.kicks = self.kicks + fired
        choose = (
            fire
            & (self.previous_global_max != self.global_max)
            & (self.stage_count > STAGE_GATE_KICKS)
        )
        magnitude = self.global_max.abs()
        stage = (magnitude >= STAGE_BANDS_COUNTS[0]).long() + (
            magnitude >= STAGE_BANDS_COUNTS[1]
        ).long()
        self.amplitude = torch.where(choose, self._amplitudes[stage], self.amplitude)
        self.previous_global_max = torch.where(
            fire, self.global_max, self.previous_global_max
        )
        self.global_max = torch.where(
            fire, torch.zeros_like(self.global_max), self.global_max
        )

    def _handle_peak(self, awake: torch.Tensor) -> None:
        """The direction flip at an unhandled peak, `main.c:1820-1829`."""
        handle = awake & self.peaked & ~self.handled_peak
        self.handled_peak = self.handled_peak | handle
        self.max_since_crossing = torch.where(
            handle, torch.zeros_like(self.max_since_crossing), self.max_since_crossing
        )
        self.direction = torch.where(handle, -self.direction, self.direction)

    def _begin(
        self,
        mask: torch.Tensor,
        sign: torch.Tensor,
        steps: torch.Tensor,
        t: float,
        index: torch.Tensor,
    ) -> None:
        """Start a move of `steps` microsteps in `sign` for the masked environments.

        `index` is the per-environment kick number written to `log`: zero for the
        initial move, the in-loop count from one otherwise.
        """
        if not bool(mask.any()):
            return
        duration = _move_terms(self._p, steps.to(torch.float64))[2]
        start = torch.full_like(self.move_start, t)
        self.move_origin = torch.where(mask, self.position, self.move_origin)
        self.move_sign = torch.where(
            mask, sign.to(self.move_sign.dtype), self.move_sign
        )
        self.move_steps = torch.where(mask, steps, self.move_steps)
        self.move_start = torch.where(mask, start, self.move_start)
        self.move_end = torch.where(mask, start + duration, self.move_end)
        # The rest position after the move. Targets inside the move come from the
        # profile; once it ends the rotor holds here until the next kick.
        travel = sign.to(self.position.dtype) * steps.to(self.position.dtype)
        self.position = torch.where(
            mask, self.position + travel * self._p.rad_per_microstep, self.position
        )
        envs = mask.nonzero().squeeze(-1)
        rows = torch.stack([envs, index[envs], sign[envs], steps[envs]], dim=-1)
        for env, kick, direction, microsteps in rows.tolist():
            self.log.append((env, kick, float(t), direction, microsteps))

    def _targets(self, t: float) -> tuple[torch.Tensor, torch.Tensor]:
        has_move = self.move_steps > 0
        end_of_step = t + self.dt
        elapsed = (end_of_step - self.move_start).clamp(min=0.0)
        elapsed = torch.where(has_move, elapsed, torch.zeros_like(elapsed))
        travelled = profile_displacement(
            elapsed, self.move_steps.to(elapsed.dtype), self._p
        )
        moving_target = self.move_origin + self.move_sign * travelled.to(
            self.position.dtype
        )
        in_step = has_move & (end_of_step < self.move_end)
        targets = torch.where(in_step, moving_target, self.position)
        in_flight = has_move & (t < self.move_end)
        return targets, in_flight

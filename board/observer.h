/* The observation pipeline, on the board.
 *
 * Builds the five observations the balance policy reads from the two integer position
 * sources the firmware has, with the arithmetic of the simulation's
 * `FurutaEnv._get_observations` (src/furuta/env.py) and `VelocitySlopeEstimator`
 * (src/furuta/estimator.py). A policy trained against that pipeline sees the same
 * numbers here; tests/test_board.py is the proof.
 *
 * C99, single precision, no heap, no I/O. All state lives in the caller's observer_t.
 */
#ifndef OBSERVER_H
#define OBSERVER_H

#include <stdint.h>

#define OBSERVER_NUM_OBS 5

/* Control period. The estimators are time-indexed: `observer_update` must run exactly
 * once per period, at the loop rate, or every rate comes out scaled by the ratio. */
#define OBSERVER_LOOP_RATE_HZ 500
#define OBSERVER_DT_S (1.0f / OBSERVER_LOOP_RATE_HZ)

/* Slope window, `FurutaEnvCfg.velocity_window` in the simulation. A least-squares slope
 * over OBSERVER_WINDOW samples lags the true rate by (OBSERVER_WINDOW - 1) / 2 samples
 * of group delay: 7.5 samples, 15 ms at 500 Hz. The policy was trained against that
 * lag, so the window is not a tuning knob here. */
#define OBSERVER_WINDOW 16

/* Position sources. Encoder counts per pendulum revolution and microsteps per rotor
 * revolution, as in config/edukit.yaml (Manual Sec. 4, Table 2, page 11). tests/test_board.py
 * checks these two, the loop rate and the window against the simulation's values. */
#define OBSERVER_ENCODER_COUNTS_PER_REV 2400
#define OBSERVER_MICROSTEPS_PER_REV 3200

/* One least-squares slope estimator: a running unwrapped angle, and the last
 * OBSERVER_WINDOW values of it in a ring buffer. The running angle is re-based by whole
 * turns once it passes two, together with the buffer, so it is not the angle travelled
 * since reset; only the differences within the window are read. */
typedef struct {
    float previous;                /* last angle fed in, radians */
    float unwrapped;               /* running sum of increments, radians, re-based */
    float buffer[OBSERVER_WINDOW]; /* history of `unwrapped` */
    int oldest;                    /* ring index of the oldest sample */
} observer_slope_t;

typedef struct {
    float coeff[OBSERVER_WINDOW]; /* slope weights, oldest sample first */
    observer_slope_t pendulum;
    observer_slope_t rotor;
} observer_t;

/* Seed both windows flat at the current position, so the first rate is zero. Call it at
 * every handover to the policy, from the sample the first update will difference
 * against: seeding from anything else injects a rate that was never there into the
 * first observation, and skipping it hands the policy a window of whatever the
 * estimator last saw. The simulation seeds flat at every episode start, so this is
 * also how the policy met its first observations in training. */
void observer_reset(observer_t *observer, int32_t counts, int32_t microsteps);

/* Push one sample and fill `obs` with [cos(tilt), sin(tilt), pendulum_rate,
 * rotor_angle, rotor_rate]. Tilt is from upright; angles in radians, rates in rad/s;
 * the rotor angle is unwrapped and may exceed pi in magnitude.
 *
 * `counts` is the pendulum encoder count from hanging, either continuous or wrapping
 * at one revolution: both give the same observations, including where a continuous
 * count passes a whole revolution. A 16-bit timer value rolling over at 65536 is
 * neither, since 65536 is not a whole number of revolutions, and the caller has to
 * resolve that before calling in. `microsteps` is the rotor's dead-reckoned position,
 * continuous.
 *
 * The estimator may be left running between handovers, through pendulum revolutions
 * (a failed catch sends the pendulum over the top): the running angle is re-based by
 * whole turns, so the rate does not lose resolution with distance travelled. That is
 * a property of this implementation and not of the simulation's, whose accumulator
 * grows for the length of an episode. */
void observer_update(observer_t *observer, int32_t counts, int32_t microsteps,
                     float obs[OBSERVER_NUM_OBS]);

/* Prime the estimator so that the next `observer_update` with these same angles
 * reports these rates, instead of the zero a flat window gives. `observer_reset` is
 * this call with both rates zero.
 *
 * This exists because the caller may know the rate already from samples this estimator
 * never saw. On the board the swing-up polls its encoder at its own period, not the
 * control loop's, so those samples cannot be pushed through an estimator whose window
 * is fixed at OBSERVER_DT_S; the caller fits a rate over the true timestamps and seeds
 * it here. Without a seed the policy reads zero rate for the first OBSERVER_WINDOW
 * steps after a handover, 32 ms, which is a quarter of the pendulum's 136 ms unstable
 * time constant and long enough to lose the catch. */
void observer_seed(observer_t *observer, int32_t counts, int32_t microsteps,
                   float pendulum_rate, float rotor_rate);

#endif /* OBSERVER_H */

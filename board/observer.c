#include "observer.h"

#include <math.h>

/* M_PI is not C99, and the ARM toolchain hides it under -std=c99. */
#define OBSERVER_PI 3.14159265358979323846
#define OBSERVER_TWO_PI_F ((float)(2.0 * OBSERVER_PI))

/* Radians per count and per microstep, computed in double at compile time and rounded
 * once to float: the rounding torch applies to the Python-float quantum in
 * `FurutaEnv._quantized_angles`, so the lattice is the same to the last bit. */
#define RAD_PER_COUNT ((float)(2.0 * OBSERVER_PI / OBSERVER_ENCODER_COUNTS_PER_REV))
#define RAD_PER_MICROSTEP ((float)(2.0 * OBSERVER_PI / OBSERVER_MICROSTEPS_PER_REV))

/* Pendulum angle from hanging, reduced to one revolution in the integer domain before
 * the conversion to float. The simulation converts the continuous angle instead; under
 * the cosine and sine, and under the wrapped increment in `slope_update`, the two are
 * the same function. Reducing first keeps the float exact however far the count has
 * travelled, where a large count would spend its precision on whole turns that the
 * trig functions then discard. C99 `%` keeps the sign of the dividend, so the result
 * lies in (-2400, 2400) counts. */
static float pendulum_angle(int32_t counts)
{
    return (float)(counts % OBSERVER_ENCODER_COUNTS_PER_REV) * RAD_PER_COUNT;
}

/* Rotor angle, unwrapped. The policy reads the absolute arm angle, so no reduction. */
static float rotor_angle(int32_t microsteps)
{
    return (float)microsteps * RAD_PER_MICROSTEP;
}

/* Fill the window as a straight line of the given slope, ending one step before
 * `angle`, so that the caller's next push of `angle` completes a W-sample ramp and the
 * dot product returns exactly `rate`. Seeding the ramp to end at `angle` instead would
 * leave the newest sample duplicated after that push and read about 2 percent low.
 * `rate` zero fills the window flat, which is what `observer_reset` wants. */
static void slope_seed(observer_slope_t *slope, float angle, float rate)
{
    const float step = OBSERVER_DT_S * rate;
    const float previous = angle - step;
    slope->previous = previous;
    slope->unwrapped = previous;
    for (int i = 0; i < OBSERVER_WINDOW; ++i) {
        const float back = (float)(OBSERVER_WINDOW - i);
        slope->buffer[i] = angle - back * step;
    }
    slope->oldest = 0;
}

static void slope_reset(observer_slope_t *slope, float angle)
{
    slope_seed(slope, angle, 0.0f);
}

/* Push one angle and return the least-squares slope over the window.
 *
 * With `wrap` set, the increment goes through atan2(sin d, cos d), which maps a step
 * across +/-pi back to the short way round, so the window never straddles the seam.
 * The rotor is continuous by construction and skips it. The three transcendental
 * calls per step are the price of reproducing the simulation's arithmetic; a
 * comparison against pi would wrap just as well and cheaper, but this is the form the
 * policy was trained against. */
static float slope_update(observer_slope_t *slope, const float *coeff, float angle,
                          int wrap)
{
    float delta = angle - slope->previous;
    if (wrap) {
        delta = atan2f(sinf(delta), cosf(delta));
    }
    slope->previous = angle;
    slope->unwrapped += delta;

    /* Overwrite the oldest sample; the slot after it is now the oldest. */
    slope->buffer[slope->oldest] = slope->unwrapped;
    slope->oldest = (slope->oldest + 1) % OBSERVER_WINDOW;

    /* Keep the accumulator within two turns of zero. Nothing reads it as an angle: the
     * rate only depends on the differences between the window's samples, and the
     * simulation's accumulator is left to grow because an episode never runs long
     * enough to matter. Here the estimator may run through failed catches that send
     * the pendulum over the top, and a float near 1500 rad has a resolution of
     * 1.2e-4 rad, which is 0.03 rad/s of rate noise. Subtracting a whole number of
     * turns from the accumulator and every sample at once is exact in float, since the
     * shift is within a factor of two of each value, so the differences and hence the
     * rate are unchanged to the last bit, and later samples are stored at full
     * resolution again. Two turns as the trigger, rather than one, so the shift does
     * not fire on every step of a pendulum sitting near the boundary. */
    if (fabsf(slope->unwrapped) > 2.0f * OBSERVER_TWO_PI_F) {
        const float turns = roundf(slope->unwrapped / OBSERVER_TWO_PI_F);
        const float shift = turns * OBSERVER_TWO_PI_F;
        slope->unwrapped -= shift;
        for (int i = 0; i < OBSERVER_WINDOW; ++i) {
            slope->buffer[i] -= shift;
        }
    }

    /* Dot product over the window, oldest first, with the newest sample subtracted
     * from every term. The coefficients sum to zero, so in exact arithmetic the
     * subtraction changes nothing; in float it removes the common term that is large
     * whenever the angle is, and keeps every partial sum on the scale of the window's
     * own travel. The simulation sums the raw samples, and this form was measured
     * closer to its numbers than summing them raw, not further: torch's reduction order
     * is not a scalar loop's in either case, and the raw sum loses the low bits that
     * carry the rate once the angle passes a turn. Cost: sixteen subtractions. */
    float rate = 0.0f;
    for (int i = 0; i < OBSERVER_WINDOW; ++i) {
        const float sample = slope->buffer[(slope->oldest + i) % OBSERVER_WINDOW];
        rate += coeff[i] * (sample - slope->unwrapped);
    }
    return rate;
}

void observer_reset(observer_t *observer, int32_t counts, int32_t microsteps)
{
    /* Least-squares slope weights for OBSERVER_WINDOW samples OBSERVER_DT_S apart:
     * offsets / (dt * sum(offsets^2)), offsets = i - (W - 1) / 2. This is
     * `slope_coefficients` in src/furuta/estimator.py. The offsets and their squared sum
     * (340 for 16 samples) are exact in float; the one rounding that differs from the
     * double-precision reference is in `dt * sum`, a common factor of 5e-8 on every
     * weight, so on the rate. Antisymmetric about the window centre, so a constant angle
     * reads zero rate. */
    const float centre = (OBSERVER_WINDOW - 1) * 0.5f;
    float sum_sq = 0.0f;
    for (int i = 0; i < OBSERVER_WINDOW; ++i) {
        const float offset = (float)i - centre;
        sum_sq += offset * offset;
    }
    for (int i = 0; i < OBSERVER_WINDOW; ++i) {
        observer->coeff[i] = ((float)i - centre) / (OBSERVER_DT_S * sum_sq);
    }

    slope_reset(&observer->pendulum, pendulum_angle(counts));
    slope_reset(&observer->rotor, rotor_angle(microsteps));
}

void observer_seed(observer_t *observer, int32_t counts, int32_t microsteps,
                   float pendulum_rate, float rotor_rate)
{
    /* The coefficients come from observer_reset, which seeds flat first. */
    observer_reset(observer, counts, microsteps);
    slope_seed(&observer->pendulum, pendulum_angle(counts), pendulum_rate);
    slope_seed(&observer->rotor, rotor_angle(microsteps), rotor_rate);
}

void observer_update(observer_t *observer, int32_t counts, int32_t microsteps,
                     float obs[OBSERVER_NUM_OBS])
{
    const float pendulum = pendulum_angle(counts);
    const float rotor = rotor_angle(microsteps);
    const float pendulum_rate = slope_update(&observer->pendulum, observer->coeff,
                                             pendulum, 1);
    const float rotor_rate = slope_update(&observer->rotor, observer->coeff, rotor, 0);

    /* Tilt from upright. The simulation wraps this into [-pi, pi] before the cosine and
     * sine; both are periodic, so the wrap changes nothing and is left out. The angle
     * is already within one turn, so the argument stays small for the libm. */
    const float tilt = pendulum - (float)OBSERVER_PI;

    obs[0] = cosf(tilt);
    obs[1] = sinf(tilt);
    obs[2] = pendulum_rate;
    obs[3] = rotor;
    obs[4] = rotor_rate;
}

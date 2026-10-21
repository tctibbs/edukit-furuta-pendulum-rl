#include "showcase_probe.h"

#include <math.h>
#include <string.h>

/* M_PI is not C99, and the ARM toolchain hides it under -std=c99. */
#define PROBE_PI 3.14159265358979323846f

enum { BAND_WAITING = 0, BAND_OPEN = 1, BAND_CLOSED = 2 };

/* The centered normal equations of the tilt fit have determinant n^2 / 4 for stops spread
 * evenly round the circle. A set under this share of that cannot separate the sine
 * from the offset: fewer than three distinct arm angles, or stops bunched into a few
 * degrees. Float round-off in the determinant is near 1e-7 n^2. */
#define TILT_MIN_DETERMINANT 1e-4f

void swing_meter_init(swing_meter_t *m)
{
    memset(m, 0, sizeof *m);
}

/* Inside the band: over 3 degrees, up to and including 15. A half swing inside it opens
 * the band, and one of 3 degrees or less closes it (complete_half_swing). freeswing.py
 * converts with the firmware's rounded 6.666667 counts per degree. It reads a peak of
 * exactly 100 counts as a hair under 15, inside, and one of exactly 20 as a hair under 3,
 * the band's end. Both edges sit in the same place here, and the two time the same
 * crossings. */
static int in_band(int32_t amplitude)
{
    return amplitude > SHOWCASE_PROBE_BAND_LOW_COUNTS &&
           amplitude <= SHOWCASE_PROBE_BAND_HIGH_COUNTS;
}

/* Where the straight line between two samples passes zero, as an elapsed time. The
 * caller has checked that the samples differ and lie either side of zero, or on it. */
static uint32_t zero_time(uint32_t t1, uint32_t t2, int32_t c1, int32_t c2)
{
    int64_t num = -(int64_t)c1;
    int64_t den = (int64_t)c2 - (int64_t)c1;
    const int64_t dt = (int64_t)(uint32_t)(t2 - t1);
    if (den < 0) {
        num = -num;
        den = -den;
    }
    return t1 + (uint32_t)((dt * num + den / 2) / den);
}

/* A half swing on `m->side` ended with a crossing at `crossing_us`. */
static void complete_half_swing(swing_meter_t *m, uint32_t crossing_us)
{
    /* A half swing already falling when the meter started has no peak in view. */
    const int32_t peak = m->run_turned ? m->run_peak : 0;
    const int32_t older = m->peaks[1];
    const int8_t into = (int8_t)-m->side;

    m->half_swings++;
    m->amplitude = peak;

    /* Same-side pair: this peak and the one two half swings back. A datum error adds to
     * both alike, so it divides out of their ratio. */
    if (older > peak && peak > 0 && older >= SHOWCASE_PROBE_QEFF_MIN_COUNTS &&
        older > m->q_high) {
        m->q_high = older;
        m->q_low = peak;
    }

    switch (m->band) {
    case BAND_WAITING:
        if (in_band(peak)) {
            m->band = BAND_OPEN;
            m->band_crossings = 1;
            m->first_us = m->last_us = crossing_us;
            m->first_into = m->last_into = into;
            m->first_before = m->last_before = peak;
            m->first_after = m->last_after = 0;
            m->datum_sum = 0;
            m->datum_terms = 0;
        }
        break;
    case BAND_OPEN:
        /* This half swing followed the band's latest crossing. */
        m->last_after = peak;
        if (m->band_crossings == 1) {
            m->first_after = peak;
        }
        if (peak > SHOWCASE_PROBE_BAND_HIGH_COUNTS) {
            /* The swing grew back out of the band: energy went in, so this is a new
             * release and the timing starts over. */
            m->band = BAND_WAITING;
            m->band_crossings = 0;
        } else if (peak <= SHOWCASE_PROBE_BAND_LOW_COUNTS) {
            m->band = BAND_CLOSED;
        } else {
            m->band_crossings++;
            m->last_us = crossing_us;
            m->last_into = into;
            m->last_before = peak;
            m->last_after = 0;
        }
        break;
    default:
        break;
    }

    /* Three consecutive peaks, p0 and p2 on this half swing's side, p1 opposite. With the
     * swing's center d counts on the positive side of the datum, positive peaks read d
     * further out and negative ones d nearer in, so side * (p0 - 2 p1 + p2) / 4 = d
     * exactly for the linear decay of dry friction, and to within a fraction of a count
     * for the viscous part inside the band. Above the band the decay curves too fast
     * between peaks to use. */
    if (m->band == BAND_OPEN && in_band(older) && in_band(m->peaks[0]) && in_band(peak)) {
        m->datum_sum += m->side * (older - 2 * m->peaks[0] + peak);
        m->datum_terms++;
    }

    m->peaks[1] = m->peaks[0];
    m->peaks[0] = peak;
}

/* The signal is past the hysteresis on `side`. Crossing into the other side completes a
 * half swing, timed where the signal last passed through zero. */
static void confirm_side(swing_meter_t *m, int8_t side, int32_t counts)
{
    if (m->side != 0 && m->has_pending) {
        complete_half_swing(m, m->pending_us);
    }
    m->side = side;
    m->has_pending = 0;
    m->run_peak = counts * side;
    m->run_turned = 0;
}

void swing_meter_step(swing_meter_t *m, uint32_t t_us, int32_t counts)
{
    uint32_t t;
    int32_t previous;

    if (!m->started) {
        m->started = 1;
        m->t0_us = t_us;
        m->prev_us = 0;
        m->prev_counts = counts;
        return;
    }
    t = t_us - m->t0_us;
    previous = m->prev_counts;

    /* Remember where the signal last passed through zero; a later pass overwrites an
     * earlier one, so dither about zero resolves to the final departure. */
    if (counts != previous &&
        ((previous <= 0 && counts >= 0) || (previous >= 0 && counts <= 0))) {
        m->pending_us = zero_time(m->prev_us, t, previous, counts);
        m->has_pending = 1;
    }

    if (m->side <= 0 && counts > SHOWCASE_PROBE_HYSTERESIS_COUNTS) {
        confirm_side(m, 1, counts);
    } else if (m->side >= 0 && counts < -SHOWCASE_PROBE_HYSTERESIS_COUNTS) {
        confirm_side(m, -1, counts);
    } else if (m->side != 0 && counts * m->side > m->run_peak) {
        m->run_peak = counts * m->side;
        m->run_turned = 1;
    }

    m->prev_us = t;
    m->prev_counts = counts;
}

/* Frequency in hertz from the band's crossings, consecutive ones half a period apart,
 * with `correction_us` added to the span between the first and the last. */
static int band_frequency(const swing_meter_t *m, float correction_us, float *hz)
{
    float span_us;
    if (m->band_crossings < 3) {
        return 0;
    }
    span_us = (float)(uint32_t)(m->last_us - m->first_us) + correction_us;
    if (!(span_us > 0.0f)) {
        return 0;
    }
    *hz = (float)(m->band_crossings - 1) * 5e5f / span_us;
    return 1;
}

int swing_meter_crossing_frequency_mhz(const swing_meter_t *m, int32_t *mhz)
{
    float hz;
    if (!band_frequency(m, 0.0f, &hz)) {
        return 0;
    }
    *mhz = (int32_t)(hz * 1000.0f + 0.5f);
    return 1;
}

static float local_amplitude(int32_t before, int32_t after)
{
    /* The two half swings either side of a crossing read d long and d short, so their
     * mean is the swing about its true center. */
    return after > 0 ? 0.5f * (float)(before + after) : (float)before;
}

/* How much later the crossing would have been timed against the swing's center, which
 * sits `datum` counts from the caller's zero. The signal passes through zero at slope
 * A omega, into `into`, so it reaches the center datum / slope later. */
static float crossing_shift_us(int8_t into, float datum, float omega, float amplitude)
{
    return (float)into * datum / (omega * amplitude) * 1e6f;
}

int swing_meter_frequency_mhz(const swing_meter_t *m, int32_t *mhz)
{
    float hz;
    if (!band_frequency(m, 0.0f, &hz)) {
        return 0;
    }
    if (m->datum_terms > 0) {
        const float datum = (float)m->datum_sum / (4.0f * (float)m->datum_terms);
        const float omega = 2.0f * PROBE_PI * hz;
        const float first_amplitude = local_amplitude(m->first_before, m->first_after);
        const float last_amplitude = local_amplitude(m->last_before, m->last_after);
        const float first = crossing_shift_us(m->first_into, datum, omega, first_amplitude);
        const float last = crossing_shift_us(m->last_into, datum, omega, last_amplitude);
        if (!band_frequency(m, last - first, &hz)) {
            return 0;
        }
    }
    *mhz = (int32_t)(hz * 1000.0f + 0.5f);
    return 1;
}

int swing_meter_datum_offset_milli(const swing_meter_t *m, int32_t *milli_counts)
{
    float datum;
    if (m->datum_terms == 0) {
        return 0;
    }
    datum = 250.0f * (float)m->datum_sum / (float)m->datum_terms;
    *milli_counts = (int32_t)(datum < 0.0f ? datum - 0.5f : datum + 0.5f);
    return 1;
}

int swing_meter_qeff_milli(const swing_meter_t *m, int32_t *q_milli)
{
    int64_t q_micro;
    if (m->q_high == 0) {
        return 0;
    }
    /* pi / ((high - low) / high), with pi to a millionth. */
    q_micro = (int64_t)m->q_high * 3141593 / (int64_t)(m->q_high - m->q_low);
    *q_milli = (int32_t)((q_micro + 500) / 1000);
    return 1;
}

int32_t swing_meter_qeff_amplitude_counts(const swing_meter_t *m)
{
    return m->q_high;
}

int32_t swing_meter_amplitude_counts(const swing_meter_t *m)
{
    return m->amplitude;
}

uint32_t swing_meter_half_swings(const swing_meter_t *m)
{
    return m->half_swings;
}

int swing_meter_done(const swing_meter_t *m)
{
    return m->band == BAND_CLOSED;
}

void tilt_fit_init(tilt_fit_t *f)
{
    memset(f, 0, sizeof *f);
}

void tilt_fit_add(tilt_fit_t *f, float arm_rad, float rest_rad)
{
    const float s = sinf(arm_rad);
    const float c = cosf(arm_rad);
    f->n++;
    f->s += s;
    f->c += c;
    f->ss += s * s;
    f->sc += s * c;
    f->cc += c * c;
    f->y += rest_rad;
    f->ys += rest_rad * s;
    f->yc += rest_rad * c;
}

/* rest = a sin(arm) + b cos(arm) + offset is linear in (a, b, offset). Centering on the
 * means eliminates the offset and leaves two equations in a and b. A sin(arm - bearing)
 * expands to A cos(bearing) sin(arm) - A sin(bearing) cos(arm), which gives the
 * amplitude and bearing from a and b. */
int tilt_fit_solve(const tilt_fit_t *f, float *amplitude_rad, float *bearing_rad,
                   float *offset_rad)
{
    float n, ss, sc, cc, ys, yc, det, a, b;
    if (f->n < 3) {
        return 0;
    }
    n = (float)f->n;
    ss = f->ss - f->s * f->s / n;
    sc = f->sc - f->s * f->c / n;
    cc = f->cc - f->c * f->c / n;
    ys = f->ys - f->y * f->s / n;
    yc = f->yc - f->y * f->c / n;
    det = ss * cc - sc * sc;
    if (!(det > TILT_MIN_DETERMINANT * n * n)) {
        return 0;
    }
    a = (ys * cc - yc * sc) / det;
    b = (yc * ss - ys * sc) / det;
    if (amplitude_rad != NULL) {
        *amplitude_rad = hypotf(a, b);
    }
    if (bearing_rad != NULL) {
        *bearing_rad = atan2f(-b, a);
    }
    if (offset_rad != NULL) {
        *offset_rad = (f->y - a * f->s - b * f->c) / n;
    }
    return 1;
}

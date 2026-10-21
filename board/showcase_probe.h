/* Measurement math for the showcase's hardware tests.
 *
 * Two estimators the firmware feeds one sample at a time. The swing meter times a free
 * ring-down of the pendulum for its suspended-mode frequency, and reads the effective
 * quality factor at the amplitude it was released from. The tilt fit fits the
 * baseplate-tilt sinusoid to the pendulum's resting angle at a series of arm angles.
 * Both reproduce the offline analyses of Experiment 03 (src/furuta/freeswing.py,
 * src/furuta/pump.py, docs/experiments/03-hardware-bringup/figures/plot_sweep.py);
 * tests/test_probe.py replays the committed captures through both.
 *
 * C99, single precision, no heap, no I/O. All state is running sums in the caller's
 * struct; nothing keeps a sample buffer.
 */
#ifndef SHOWCASE_PROBE_H
#define SHOWCASE_PROBE_H

#include <stdint.h>

/* Encoder counts per pendulum revolution, as in config/edukit.yaml (Manual Sec. 4,
 * Table 2, page 11). The firmware's ENCODER_READ_ANGLE_SCALE is this over 360. */
#define SHOWCASE_PROBE_COUNTS_PER_REV 2400

/* A zero crossing counts once the signal is more than this many counts past zero on
 * the far side. Without it, the encoder's one-count dither as the pendulum passes
 * slowly through hanging registers every pass. freeswing.py's `deadband_counts`. */
#define SHOWCASE_PROBE_HYSTERESIS_COUNTS 2

/* The amplitude band the frequency is timed in, 3 to 15 degrees, in counts. Above it the
 * swing is not harmonic: the period is 0.43 percent long at 15 degrees and grows with
 * the square of the amplitude. Below it one count is too large a share of the swing to
 * time. freeswing.py's LINEAR_BAND_LOW_DEG and LINEAR_BAND_HIGH_DEG. */
#define SHOWCASE_PROBE_BAND_LOW_COUNTS (3 * SHOWCASE_PROBE_COUNTS_PER_REV / 360)
#define SHOWCASE_PROBE_BAND_HIGH_COUNTS (15 * SHOWCASE_PROBE_COUNTS_PER_REV / 360)

/* The smallest peak a Q_eff pair may start from: more than one degree, as in
 * pump.py's `qeff_vs_amplitude`. */
#define SHOWCASE_PROBE_QEFF_MIN_COUNTS 7

/* Swing meter.
 *
 * A half swing runs from one confirmed zero crossing to the next, and its amplitude is
 * the largest sample on its side of zero. The frequency comes from the crossings that
 * end half swings inside the band, from the first half swing at or under 15 degrees to
 * the last before one under 3 degrees, as freeswing.py's `linear_band` and
 * `frequency_from_crossings` take it. Q_eff is pi over the fraction of amplitude lost
 * between a peak and the next on the same side, as pump.py's `qeff_vs_amplitude`,
 * reported for the pair that starts from the largest peak.
 *
 * Every field is private to showcase_probe.c. */
typedef struct {
    uint8_t started;      /* a first sample has been seen */
    int8_t side;          /* side of zero last confirmed: -1, 0 before the first, +1 */
    uint8_t has_pending;  /* the signal has passed through zero since `side` was set */
    uint8_t run_turned;   /* the current half swing rose after it was confirmed */
    uint8_t band;         /* waiting for the band, timing inside it, or past it */
    uint32_t t0_us;       /* first sample's timestamp; later times are elapsed from it */
    uint32_t prev_us;     /* previous sample, elapsed microseconds */
    int32_t prev_counts;  /* previous sample, counts */
    uint32_t pending_us;  /* where the signal last passed through zero */
    int32_t run_peak;     /* largest distance from zero in the current half swing */
    uint32_t half_swings; /* half swings completed */
    int32_t peaks[2];     /* the two half swings before the latest: [0] newer */
    int32_t amplitude;    /* the latest half swing's amplitude */
    int32_t q_high;       /* the Q_eff pair with the largest starting peak */
    int32_t q_low;
    uint32_t band_crossings; /* crossings timed inside the band */
    uint32_t first_us;       /* the band's first and last crossings */
    uint32_t last_us;
    int8_t first_into;       /* side each of those crossings went into */
    int8_t last_into;
    int32_t first_before;    /* amplitude of the half swings either side of them; */
    int32_t first_after;     /* zero while the half swing after has not finished */
    int32_t last_before;
    int32_t last_after;
    int32_t datum_sum;       /* four times the center's offset, summed over triples */
    uint32_t datum_terms;
} swing_meter_t;

void swing_meter_init(swing_meter_t *m);

/* One sample: a timestamp in microseconds from any free-running clock (it may wrap, as
 * long as one ring-down lasts under 71 minutes), and the pendulum's encoder count from
 * its hanging datum. Every sample of the decay, at the 2 ms control period or faster;
 * the timing interpolates between samples, so the period need not be exact. The sign
 * convention does not matter. The datum need not be exact either: see
 * `swing_meter_frequency_mhz`. */
void swing_meter_step(swing_meter_t *m, uint32_t t_us, int32_t counts);

/* The suspended-mode frequency in millihertz, from the crossings inside the band.
 * Returns 0 until the band holds three crossings, one full cycle; the value can still
 * change until `swing_meter_done`.
 *
 * The crossings are timed against the caller's datum, and the first and last are then
 * moved to where the swing's own center would put them. The caller's datum is where
 * the pendulum last came to rest, which dry friction leaves a few counts off its true
 * equilibrium, and in a band only three cycles long one count of datum error moves the
 * estimate by about 0.2 percent, and by up to 0.7 where it moves a half swing across a
 * band edge (measured on Experiment 03's releases). The center comes from the band's
 * own peaks; `swing_meter_datum_offset_milli` reports it. */
int swing_meter_frequency_mhz(const swing_meter_t *m, int32_t *mhz);

/* The same frequency without the datum correction: freeswing.py's own estimate, given
 * the same datum. For comparing against the offline analysis. */
int swing_meter_crossing_frequency_mhz(const swing_meter_t *m, int32_t *mhz);

/* Where the swing's center sits relative to the caller's datum, in thousandths of a
 * count, from the peaks inside the band. Returns 0 until three consecutive half swings
 * have peaked inside it. */
int swing_meter_datum_offset_milli(const swing_meter_t *m, int32_t *milli_counts);

/* Q_eff times 1000, at the largest amplitude a same-side pair of peaks started from:
 * the release amplitude, for a decay the meter saw from its start. Returns 0 until a
 * peak has been followed by a smaller one on its own side, a cycle after release. */
int swing_meter_qeff_milli(const swing_meter_t *m, int32_t *q_milli);

/* The amplitude that Q_eff was read at, in counts. 0 while there is none. */
int32_t swing_meter_qeff_amplitude_counts(const swing_meter_t *m);

/* The latest completed half swing's amplitude, in counts. 0 before the first, and for
 * a half swing already falling when the meter started. */
int32_t swing_meter_amplitude_counts(const swing_meter_t *m);

/* Half swings completed. The first ends at the first crossing after a release. */
uint32_t swing_meter_half_swings(const swing_meter_t *m);

/* 1 once a half swing has peaked under the band after the band's crossings began, when
 * neither result can change any more. */
int swing_meter_done(const swing_meter_t *m);

/* Tilt fit.
 *
 * Least squares for rest = A sin(arm - bearing) + offset, over one resting angle per
 * arm stop, in closed form from running sums: plot_sweep.py's `fit_sinusoid`. The
 * rest angle may be from any fixed datum, which the offset absorbs. Every field is
 * private to showcase_probe.c. */
typedef struct {
    uint32_t n;
    float s, c, ss, sc, cc; /* sums of sin(arm), cos(arm) and their products */
    float y, ys, yc;        /* sums of rest, rest sin(arm), rest cos(arm) */
} tilt_fit_t;

void tilt_fit_init(tilt_fit_t *f);

/* One stop: the arm angle and the pendulum's resting angle there, in radians. */
void tilt_fit_add(tilt_fit_t *f, float arm_rad, float rest_rad);

/* Solve for the amplitude (radians, not negative), the bearing (radians, in [-pi, pi])
 * and the offset. Returns 0, leaving the outputs untouched, with fewer than three stops
 * or with stops too bunched in arm angle to separate the sine from the offset. Any
 * output pointer may be NULL. */
int tilt_fit_solve(const tilt_fit_t *f, float *amplitude_rad, float *bearing_rad,
                   float *offset_rad);

#endif /* SHOWCASE_PROBE_H */

/* Host harness for the showcase's probe math. Not part of the firmware image.
 *
 *   test_probe constants   prints `NAME VALUE` per line: the compile-time constants and
 *                          the size of each struct
 *   test_probe swing       lines of `t_us counts` on stdin, one per sample; prints
 *                          `half N AMPLITUDE` as each half swing completes, then at the
 *                          end `frequency MHZ`, `crossing MHZ`, `datum MILLI`,
 *                          `qeff Q_MILLI AMPLITUDE` (each `none` when there is none),
 *                          `amplitude COUNTS`, `half_swings N` and `done 0|1`
 *   test_probe tilt        lines of `arm_rad rest_rad`, one per stop; prints
 *                          `AMPLITUDE BEARING OFFSET` in radians, or `none`
 *
 * Floats are printed with %.9g, which round-trips a float exactly. Blank lines are
 * skipped; anything else that does not parse is an error. Build:
 *
 *   cc -std=c99 -O2 -ffp-contract=off -Wall -Wextra -Werror \
 *       board/showcase_probe.c board/test_probe.c -lm
 *
 * tests/test_probe.py builds and drives it.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "showcase_probe.h"

static int is_blank(const char *line)
{
    return line[strspn(line, " \t\r\n")] == '\0';
}

static int run_constants(void)
{
    printf("SHOWCASE_PROBE_COUNTS_PER_REV %d\n", SHOWCASE_PROBE_COUNTS_PER_REV);
    printf("SHOWCASE_PROBE_HYSTERESIS_COUNTS %d\n", SHOWCASE_PROBE_HYSTERESIS_COUNTS);
    printf("SHOWCASE_PROBE_BAND_LOW_COUNTS %d\n", SHOWCASE_PROBE_BAND_LOW_COUNTS);
    printf("SHOWCASE_PROBE_BAND_HIGH_COUNTS %d\n", SHOWCASE_PROBE_BAND_HIGH_COUNTS);
    printf("SHOWCASE_PROBE_QEFF_MIN_COUNTS %d\n", SHOWCASE_PROBE_QEFF_MIN_COUNTS);
    printf("sizeof_swing_meter_t %u\n", (unsigned)sizeof(swing_meter_t));
    printf("sizeof_tilt_fit_t %u\n", (unsigned)sizeof(tilt_fit_t));
    return 0;
}

static int run_swing(void)
{
    char line[256];
    swing_meter_t meter;
    uint32_t t_us;
    int32_t counts;
    int32_t value;
    uint32_t reported = 0;

    swing_meter_init(&meter);
    while (fgets(line, sizeof line, stdin) != NULL) {
        if (is_blank(line)) {
            continue;
        }
        if (sscanf(line, "%" SCNu32 " %" SCNd32, &t_us, &counts) != 2) {
            fprintf(stderr, "expected `t_us counts`, got: %s", line);
            return 1;
        }
        swing_meter_step(&meter, t_us, counts);
        if (swing_meter_half_swings(&meter) != reported) {
            reported = swing_meter_half_swings(&meter);
            printf("half %" PRIu32 " %" PRId32 "\n", reported,
                   swing_meter_amplitude_counts(&meter));
        }
    }

    if (swing_meter_frequency_mhz(&meter, &value)) {
        printf("frequency %" PRId32 "\n", value);
    } else {
        printf("frequency none\n");
    }
    if (swing_meter_crossing_frequency_mhz(&meter, &value)) {
        printf("crossing %" PRId32 "\n", value);
    } else {
        printf("crossing none\n");
    }
    if (swing_meter_datum_offset_milli(&meter, &value)) {
        printf("datum %" PRId32 "\n", value);
    } else {
        printf("datum none\n");
    }
    if (swing_meter_qeff_milli(&meter, &value)) {
        printf("qeff %" PRId32 " %" PRId32 "\n", value,
               swing_meter_qeff_amplitude_counts(&meter));
    } else {
        printf("qeff none\n");
    }
    printf("amplitude %" PRId32 "\n", swing_meter_amplitude_counts(&meter));
    printf("half_swings %" PRIu32 "\n", swing_meter_half_swings(&meter));
    printf("done %d\n", swing_meter_done(&meter));
    return 0;
}

static int run_tilt(void)
{
    char line[256];
    tilt_fit_t fit;
    float arm;
    float rest;
    float amplitude;
    float bearing;
    float offset;

    tilt_fit_init(&fit);
    while (fgets(line, sizeof line, stdin) != NULL) {
        if (is_blank(line)) {
            continue;
        }
        if (sscanf(line, "%f %f", &arm, &rest) != 2) {
            fprintf(stderr, "expected `arm_rad rest_rad`, got: %s", line);
            return 1;
        }
        tilt_fit_add(&fit, arm, rest);
    }
    if (tilt_fit_solve(&fit, &amplitude, &bearing, &offset)) {
        printf("%.9g %.9g %.9g\n", amplitude, bearing, offset);
    } else {
        printf("none\n");
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "constants") == 0) {
        return run_constants();
    }
    if (argc == 2 && strcmp(argv[1], "swing") == 0) {
        return run_swing();
    }
    if (argc == 2 && strcmp(argv[1], "tilt") == 0) {
        return run_tilt();
    }
    fprintf(stderr, "usage: %s constants | swing | tilt\n", argv[0]);
    return 2;
}

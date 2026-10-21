/* Host harness for the board code. Not part of the firmware image.
 *
 *   test_board policy          lines of 5 floats on stdin; prints policy_forward per line
 *   test_board command A_MAX   lines of 5 floats; prints policy_command(obs, A_MAX)
 *   test_board observer        lines of `counts microsteps`; the first line resets the
 *                              observer, every later line prints its 5 observations
 *   test_board constants       prints `NAME VALUE` per line: the compile-time constants
 *                              the other modes ran under, for the test to check against
 *                              the simulation's parameter file
 *
 * Every number is printed with %.9g, which round-trips a float exactly. Blank lines are
 * skipped; anything else that does not parse is an error. Build:
 *
 *   cc -std=c99 -O2 -ffp-contract=off -Wall -Wextra -Werror \
 *       board/policy.c board/observer.c board/test_board.c -lm
 *
 * tests/test_board.py builds and drives it.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "observer.h"
#include "policy.h"

#if POLICY_NUM_OBS != 5 || OBSERVER_NUM_OBS != 5
#error "the scanf and printf formats below are written for five observations"
#endif

static int is_blank(const char *line)
{
    return line[strspn(line, " \t\r\n")] == '\0';
}

/* `command` selects policy_command over policy_forward. */
static int run_policy(int command, float a_max)
{
    char line[256];
    float obs[POLICY_NUM_OBS];

    while (fgets(line, sizeof line, stdin) != NULL) {
        if (is_blank(line)) {
            continue;
        }
        if (sscanf(line, "%f %f %f %f %f", &obs[0], &obs[1], &obs[2], &obs[3],
                   &obs[4]) != POLICY_NUM_OBS) {
            fprintf(stderr, "expected five floats, got: %s", line);
            return 1;
        }
        printf("%.9g\n", command ? policy_command(obs, a_max) : policy_forward(obs));
    }
    return 0;
}

static int run_observer(void)
{
    char line[256];
    observer_t observer;
    float obs[OBSERVER_NUM_OBS];
    int32_t counts;
    int32_t microsteps;
    int have_reset = 0;

    while (fgets(line, sizeof line, stdin) != NULL) {
        if (is_blank(line)) {
            continue;
        }
        if (sscanf(line, "%" SCNd32 " %" SCNd32, &counts, &microsteps) != 2) {
            fprintf(stderr, "expected `counts microsteps`, got: %s", line);
            return 1;
        }
        if (!have_reset) {
            observer_reset(&observer, counts, microsteps);
            have_reset = 1;
            continue;
        }
        observer_update(&observer, counts, microsteps, obs);
        printf("%.9g %.9g %.9g %.9g %.9g\n", obs[0], obs[1], obs[2], obs[3], obs[4]);
    }
    return 0;
}

/* The constants as the compiler saw them, not as the headers read: the observer's
 * come through the macros, the policy's through the compiled object, so a header
 * edited after the build cannot make this lie. */
static int run_constants(void)
{
    printf("POLICY_NUM_OBS %d\n", POLICY_NUM_OBS);
    printf("POLICY_SQUASH_ACTIONS %d\n", policy_squash_actions());
    printf("OBSERVER_NUM_OBS %d\n", OBSERVER_NUM_OBS);
    printf("OBSERVER_LOOP_RATE_HZ %d\n", OBSERVER_LOOP_RATE_HZ);
    printf("OBSERVER_WINDOW %d\n", OBSERVER_WINDOW);
    printf("OBSERVER_ENCODER_COUNTS_PER_REV %d\n", OBSERVER_ENCODER_COUNTS_PER_REV);
    printf("OBSERVER_MICROSTEPS_PER_REV %d\n", OBSERVER_MICROSTEPS_PER_REV);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && strcmp(argv[1], "policy") == 0 && argc == 2) {
        return run_policy(0, 0.0f);
    }
    if (argc >= 2 && strcmp(argv[1], "command") == 0 && argc == 3) {
        char *end = NULL;
        const float a_max = strtof(argv[2], &end);
        if (end == argv[2] || *end != '\0') {
            fprintf(stderr, "A_MAX must be a number, got: %s\n", argv[2]);
            return 2;
        }
        return run_policy(1, a_max);
    }
    if (argc >= 2 && strcmp(argv[1], "seed") == 0 && argc == 4) {
        /* Seed with the given rates, then report the observations the next update
         * gives for the same sample: the rates must come back unchanged. */
        observer_t observer;
        float obs[OBSERVER_NUM_OBS];
        long counts = 0, microsteps = 0;
        const float pendulum_rate = (float)atof(argv[2]);
        const float rotor_rate = (float)atof(argv[3]);
        while (scanf("%ld %ld", &counts, &microsteps) == 2) {
            observer_seed(&observer, (int32_t)counts, (int32_t)microsteps,
                          pendulum_rate, rotor_rate);
            observer_update(&observer, (int32_t)counts, (int32_t)microsteps, obs);
            printf("%.9g %.9g %.9g %.9g %.9g\n", obs[0], obs[1], obs[2], obs[3],
                   obs[4]);
        }
        return 0;
    }

    if (argc >= 2 && strcmp(argv[1], "observer") == 0 && argc == 2) {
        return run_observer();
    }
    if (argc >= 2 && strcmp(argv[1], "constants") == 0 && argc == 2) {
        return run_constants();
    }
    fprintf(stderr, "usage: %s policy | command A_MAX | observer | constants\n", argv[0]);
    return 2;
}

/* Host harness for the showcase board code. Not part of the firmware image.
 *
 *   test_showcase pixel X Y          the data byte and bit one pixel lands in
 *   test_showcase init               the panel's init packet, as hex
 *   test_showcase flush              each packet a flush sends: length and first bytes
 *   test_showcase text SCALE STRING  characters clipped at (0, 0), then lit pixels
 *   test_showcase button             lines of 0 or 1, one per ms; prints `ms EVENT`
 *   test_showcase buzzer SOUND       `ms hz` at every change until the tune is silent
 *   test_showcase beeps N HISTORY    `ms hz` at every change of a beeped number
 *   test_showcase attempt OUTCOME    lines of `counts steps cmd`, one per control cycle;
 *                                    prints the result's fields and its two text lines
 *   test_showcase format PROBE OUTCOME VALUE DETAIL ATTEMPTS
 *                                    a hardware test's two result lines, `big|detail`,
 *                                    from its numbers in thousandths; DETAIL `-` for a
 *                                    result without a second number
 *   test_showcase carousel           a script over the planned table, one command per
 *                                    line (`none`, `at MS`, `tap`, `hold`, `auto N`,
 *                                    `end OUTCOME HOLD_MS [tap|hold]`,
 *                                    `measured VALUE DETAIL|-`, `running [lift]`);
 *                                    prints the state after each
 *   test_showcase sounds             the same script; prints `EVENT SOUND` after each
 *   test_showcase screen             the same script; prints the selector screen as text
 *                                    after each, or after `running` the running screen:
 *                                    `layout|top left|top right|title|big|detail|hint left|
 *                                    hint right|pips`, pips as `filled/count`
 *   test_showcase nav                `title|main title|history count|position|partner`
 *                                    per entry
 *   test_showcase screens            every screen for every entry and state, over the
 *                                    planned table, the firmware's, one with every title
 *                                    at its limit, and one whose hints overlap; prints
 *                                    `screen clipped`
 *   test_showcase render             the screens of Experiment 07's display figure, each
 *                                    as `=== caption` and 64 rows of '#' and '.'
 *   test_showcase table              the firmware's generated table, one entry a line
 *   test_showcase policies           lines of `name o0 o1 o2 o3 o4`; prints the named
 *                                    table policy's forward pass and command
 *
 * tests/test_showcase.py builds and drives it. Build:
 *
 *   cc -std=c99 -O2 -ffp-contract=off -Wall -Wextra -Werror -Iboard board/display.c \
 *       board/font5x7.c board/showcase.c board/showcase_screens.c board/showcase_table.c \
 *       board/policy.c board/test_showcase.c -lm
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "display.h"
#include "policy.h"
#include "showcase.h"
#include "showcase_screens.h"
#include "showcase_table.h"

#define COUNT_OF(a) (sizeof(a) / sizeof((a)[0]))

static const char *outcome_names[SHOWCASE_OUTCOMES] = {
    "HELD",  "FELL", "TRAVEL",   "NO_CATCH",   "STOPPED",   "STALL",
    "FAULT", "LAG",  "MEASURED", "NO_RELEASE", "NO_RESULT",
};

static const char *sound_names[SOUND_COUNT] = {
    "NONE",  "MODE",  "NEWER", "DIVE",  "CLIMB", "SWAP",   "SWAP_BACK",
    "TICK",  "READY", "CATCH", "FALL",  "ALARM", "WELCOME",
};

static const char *probe_names[] = {"NONE", "RINGDOWN", "FREESWING", "TILT"};

static int probe_from_name(const char *name)
{
    for (int k = 0; k < (int)COUNT_OF(probe_names); ++k) {
        if (strcmp(name, probe_names[k]) == 0) {
            return k;
        }
    }
    return -1;
}

static int outcome_from_name(const char *name)
{
    for (int k = 0; k < SHOWCASE_OUTCOMES; ++k) {
        if (strcmp(name, outcome_names[k]) == 0) {
            return k;
        }
    }
    return -1;
}

/* Stand-in policies: the screens and the carousel only read the bound and the squash. */
static const float zeros[POLICY_HIDDEN * POLICY_HIDDEN] = {0};
static const policy_t tanh60 = {"tanh60", zeros, zeros, zeros, zeros, zeros, zeros, 60.0f, 1};
static const policy_t clamp60 = {"clamp60", zeros, zeros, zeros, zeros, zeros, zeros, 60.0f, 0};

/* The carousel as planned: five main modes, each main entry followed by its variant or
 * its history. */
static const showcase_entry_t real_table[] = {
    {"PID", 1, 1, 0, SHOWCASE_STOCK, SHOWCASE_PROBE_NONE, NULL, 0},
    {"LQR", 1, 0, 1, SHOWCASE_STOCK_LQR, SHOWCASE_PROBE_NONE, NULL, 0},
    {"RING-DOWN", 2, 1, 0, SHOWCASE_PROBE, SHOWCASE_PROBE_RINGDOWN, NULL, 0},
    {"FREE SWING", 2, 0, 0, SHOWCASE_PROBE, SHOWCASE_PROBE_FREESWING, NULL, 0},
    {"TILT SWEEP", 2, 0, 0, SHOWCASE_PROBE, SHOWCASE_PROBE_TILT, NULL, 0},
    {"BALANCE", 3, 1, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {"1ST CATCH", 3, 0, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {"WANDERING", 3, 0, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {"SHAKY HOLD", 3, 0, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {"SWING-UP", 4, 1, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
    {"NEAR MISS", 4, 0, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
    {"FIRST HOLD", 4, 0, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
    {"JETHRO", 5, 1, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
};

/* The same shape with every title at its limit: 10 characters, or 7 for a main entry
 * with a variant and the variant, whose hint names the other. */
#define W10 "WWWWWWWWWW"
#define W7 "WWWWWWW"
static const showcase_entry_t wide_table[] = {
    {W7, 1, 1, 0, SHOWCASE_STOCK, SHOWCASE_PROBE_NONE, NULL, 0},
    {W7, 1, 0, 1, SHOWCASE_STOCK_LQR, SHOWCASE_PROBE_NONE, NULL, 0},
    {W10, 2, 1, 0, SHOWCASE_PROBE, SHOWCASE_PROBE_RINGDOWN, NULL, 0},
    {W10, 2, 0, 0, SHOWCASE_PROBE, SHOWCASE_PROBE_FREESWING, NULL, 0},
    {W10, 2, 0, 0, SHOWCASE_PROBE, SHOWCASE_PROBE_TILT, NULL, 0},
    {W10, 3, 1, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {W10, 3, 0, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {W10, 3, 0, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {W10, 3, 0, 0, SHOWCASE_RL_BALANCE, SHOWCASE_PROBE_NONE, &clamp60, 0},
    {W10, 4, 1, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
    {W10, 4, 0, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
    {W10, 4, 0, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
    {W10, 5, 1, 0, SHOWCASE_RL_FROM_REST, SHOWCASE_PROBE_NONE, &tanh60, 1500},
};

/* A main entry and its variant one character past that limit: "tap next" and
 * "hold WWWWWWWW" need 22 columns, so each armed screen's hints overlap by one. */
#define W8 "WWWWWWWW"
static const showcase_entry_t over_table[] = {
    {W8, 1, 1, 0, SHOWCASE_STOCK, SHOWCASE_PROBE_NONE, NULL, 0},
    {W8, 1, 0, 1, SHOWCASE_STOCK_LQR, SHOWCASE_PROBE_NONE, NULL, 0},
};

/* The index of the table entry with this title; the harness stops if there is none. */
static uint8_t entry_named(const showcase_entry_t *table, uint8_t count, const char *title)
{
    for (uint8_t k = 0; k < count; ++k) {
        if (strcmp(table[k].title, title) == 0) {
            return k;
        }
    }
    fprintf(stderr, "no entry %s\n", title);
    exit(2);
}

/* ---- Display ------------------------------------------------------------------------ */

static int count_lit(const display_t *d)
{
    int lit = 0;
    for (int k = 1; k <= DISPLAY_BYTES; ++k) {
        for (int bit = 0; bit < 8; ++bit) {
            lit += (d->buf[k] >> bit) & 1;
        }
    }
    return lit;
}

static int run_pixel(int x, int y)
{
    static display_t d;
    display_clear(&d);
    display_pixel(&d, x, y, 1);
    for (int k = 0; k < DISPLAY_BYTES; ++k) {
        for (int bit = 0; bit < 8; ++bit) {
            if (d.buf[1 + k] & (1u << bit)) {
                printf("%d %d\n", k, bit);
            }
        }
    }
    return 0;
}

static int run_init(void)
{
    size_t len = 0;
    const uint8_t *packet = display_init_packet(&len);
    for (size_t k = 0; k < len; ++k) {
        printf("%02X%s", packet[k], k + 1 < len ? " " : "\n");
    }
    return 0;
}

static int capture_write(void *ctx, const uint8_t *bytes, size_t len)
{
    (void)ctx;
    printf("%zu", len);
    for (size_t k = 0; k < len && k < 8; ++k) {
        printf(" %02X", bytes[k]);
    }
    printf("\n");
    return 0;
}

static int run_flush(void)
{
    static display_t d;
    display_clear(&d);
    display_pixel(&d, 0, 0, 1);
    return display_flush(&d, capture_write, NULL);
}

static int run_text(int scale, const char *s)
{
    static display_t d;
    display_clear(&d);
    const int clipped = display_text(&d, 0, 0, s, scale);
    printf("%d %d\n", clipped, count_lit(&d));
    return 0;
}

/* ---- Button and buzzer ---------------------------------------------------------------- */

static int run_button(void)
{
    button_t b;
    button_init(&b);
    char line[32];
    long ms = 0;
    while (fgets(line, sizeof line, stdin) != NULL) {
        if (line[0] != '0' && line[0] != '1') {
            continue;
        }
        const button_event_t event = button_sample_1ms(&b, line[0] == '1');
        if (event == BUTTON_SHORT) {
            printf("%ld SHORT\n", ms);
        } else if (event == BUTTON_LONG) {
            printf("%ld LONG\n", ms);
        }
        ms++;
    }
    return 0;
}

static void print_changes(buzzer_t *b, int stop_when_silent)
{
    for (long ms = 0; ms < 5000; ++ms) {
        uint16_t hz = 0;
        uint8_t level = 0;
        if (buzzer_tick_1ms(b, &hz, &level)) {
            printf("%ld %u\n", ms, hz);
            if (stop_when_silent && hz == 0 && b->notes == NULL) {
                break;
            }
        }
    }
}

static int run_buzzer(const char *name)
{
    for (int k = 1; k < SOUND_COUNT; ++k) {
        if (strcmp(name, sound_names[k]) == 0) {
            buzzer_t b;
            buzzer_init(&b);
            buzzer_play(&b, (sound_t)k);
            print_changes(&b, 1);
            return 0;
        }
    }
    fprintf(stderr, "unknown sound %s\n", name);
    return 2;
}

static int run_beeps(int count, int history)
{
    buzzer_t b;
    buzzer_init(&b);
    buzzer_play_count(&b, (uint8_t)count, history);
    print_changes(&b, 0);
    return 0;
}

/* ---- One attempt ---------------------------------------------------------------------- */

static int run_attempt(const char *outcome_name)
{
    const int outcome = outcome_from_name(outcome_name);
    if (outcome < 0) {
        fprintf(stderr, "unknown outcome %s\n", outcome_name);
        return 2;
    }
    showcase_attempt_t a;
    showcase_attempt_reset(&a, 0);
    char line[96];
    long counts = 0, steps = 0;
    float cmd = 0.0f;
    while (fgets(line, sizeof line, stdin) != NULL) {
        if (sscanf(line, "%ld %ld %f", &counts, &steps, &cmd) == 3) {
            showcase_attempt_step(&a, (int32_t)counts, (int32_t)steps, cmd);
        }
    }
    showcase_result_t r;
    showcase_attempt_result(&a, (showcase_outcome_t)outcome, &r);
    char big[SHOWCASE_TEXT], detail[SHOWCASE_TEXT];
    showcase_format_outcome(&r, big, sizeof big);
    showcase_format_detail(&r, 0, 1, detail, sizeof detail);
    printf("arrived %u\nup_ms %lu\nhold_ms %lu\nrun_ms %lu\ntops %u\nflips %u\npeak_steps %ld\n",
           r.arrived, (unsigned long)r.up_ms, (unsigned long)r.hold_ms, (unsigned long)r.run_ms,
           r.tops, r.flips, (long)r.peak_steps);
    printf("text %s|%s\n", big, detail);
    return 0;
}

static int run_format(const char *probe_name, const char *outcome_name, long value,
                      const char *detail, int attempts)
{
    const int probe = probe_from_name(probe_name);
    const int outcome = outcome_from_name(outcome_name);
    if (probe < 0 || outcome < 0) {
        fprintf(stderr, "unknown probe %s or outcome %s\n", probe_name, outcome_name);
        return 2;
    }
    showcase_result_t r = {0};
    r.outcome = (showcase_outcome_t)outcome;
    r.probe = (showcase_probe_t)probe;
    r.value_milli = (int32_t)value;
    r.has_detail = strcmp(detail, "-") != 0;
    r.detail_milli = r.has_detail ? (int32_t)strtol(detail, NULL, 10) : 0;
    char big[SHOWCASE_TEXT], line[SHOWCASE_TEXT];
    showcase_format_outcome(&r, big, sizeof big);
    showcase_format_detail(&r, 0, (uint16_t)attempts, line, sizeof line);
    printf("%s|%s\n", big, line);
    return 0;
}

/* ---- The carousel ------------------------------------------------------------------- */

static const char *event_names[] = {"NONE",  "START", "MODE",       "NEWER", "DIVE",
                                    "CLIMB", "SWAP",  "NO_HISTORY", "RESUME"};

typedef enum { REPORT_STATE, REPORT_SOUND, REPORT_SCREEN } report_t;

static void print_state(const showcase_t *s, showcase_event_t event)
{
    static const char *phases[] = {"ARMING", "RUNNING", "PAUSED"};
    static const char *pauses[] = {"NONE",  "BUTTON",   "TRAVEL", "STALL",
                                   "FAULT", "NO_MOTOR", "RESULT"};
    printf("%s entry=%s pause=%s in_row=%u attempts=%u held=%u event=%s\n",
           phases[s->phase], s->entries[s->entry].title, pauses[s->pause], s->in_row,
           s->attempts[s->entry], s->held[s->entry], event_names[event]);
}

static void print_screen(const showcase_screen_t *screen)
{
    static const char *layouts[] = {"ARMED",  "RESULT",  "RESULT_PAUSED",
                                    "PAUSED", "STOPPED", "RUNNING"};
    char pips[8] = "";
    if (screen->dots != 0u) {
        snprintf(pips, sizeof pips, "%u/%u", (unsigned)screen->dot + 1u, (unsigned)screen->dots);
    }
    printf("%s|%s|%s|%s|%s|%s|%s|%s|%s\n", layouts[screen->layout], screen->top_left,
           screen->top_right, screen->title, screen->big, screen->detail, screen->hint_left,
           screen->hint_right, pips);
}

static void report(report_t mode, const showcase_t *s, showcase_event_t event, uint32_t now_ms,
                   int running_cue)
{
    showcase_screen_t screen;
    switch (mode) {
    case REPORT_SOUND:
        printf("%s %s\n", event_names[event], sound_names[showcase_event_sound(s, event)]);
        break;
    case REPORT_SCREEN:
        if (running_cue >= 0) {
            showcase_running_screen(s, (showcase_cue_t)running_cue, &screen);
        } else {
            showcase_selector_screen(s, now_ms, &screen);
        }
        print_screen(&screen);
        break;
    case REPORT_STATE:
    default:
        print_state(s, event);
        break;
    }
}

static int run_script(report_t mode)
{
    showcase_t s;
    showcase_init(&s, real_table, (uint8_t)COUNT_OF(real_table), 0);
    char line[96];
    uint32_t now = 0;
    while (fgets(line, sizeof line, stdin) != NULL) {
        char word[16] = {0};
        char arg[16] = {0};
        char second[16] = {0};
        char extra[16] = {0};
        if (sscanf(line, "%15s %15s %15s %15s", word, arg, second, extra) < 1) {
            continue;
        }
        showcase_event_t event = SHOWCASE_EVENT_NONE;
        int running_cue = -1;
        if (strcmp(word, "at") == 0) {
            now = (uint32_t)strtoul(arg, NULL, 10);
            event = showcase_select_step(&s, SHOWCASE_INPUT_NONE, now);
        } else if (strcmp(word, "none") == 0) {
            event = showcase_select_step(&s, SHOWCASE_INPUT_NONE, now);
        } else if (strcmp(word, "tap") == 0) {
            event = showcase_select_step(&s, SHOWCASE_INPUT_TAP, now);
        } else if (strcmp(word, "hold") == 0) {
            event = showcase_select_step(&s, SHOWCASE_INPUT_HOLD, now);
        } else if (strcmp(word, "auto") == 0) {
            showcase_set_auto(&s, (uint8_t)strtoul(arg, NULL, 10));
        } else if (strcmp(word, "running") == 0) {
            running_cue = strcmp(arg, "lift") == 0 ? SHOWCASE_CUE_LIFT : SHOWCASE_CUE_NONE;
        } else if (strcmp(word, "end") == 0 || strcmp(word, "measured") == 0) {
            showcase_result_t r = {0};
            showcase_input_t input = SHOWCASE_INPUT_NONE;
            r.probe = s.entries[s.entry].probe;
            if (strcmp(word, "measured") == 0) {
                r.outcome = SHOWCASE_MEASURED;
                r.value_milli = (int32_t)strtol(arg, NULL, 10);
                r.has_detail = strcmp(second, "-") != 0;
                r.detail_milli = r.has_detail ? (int32_t)strtol(second, NULL, 10) : 0;
            } else {
                const int outcome = outcome_from_name(arg);
                if (outcome < 0) {
                    fprintf(stderr, "unknown outcome %s\n", arg);
                    return 2;
                }
                r.outcome = (showcase_outcome_t)outcome;
                r.hold_ms = (uint32_t)strtoul(second, NULL, 10);
                input = strcmp(extra, "tap") == 0    ? SHOWCASE_INPUT_TAP
                        : strcmp(extra, "hold") == 0 ? SHOWCASE_INPUT_HOLD
                                                     : SHOWCASE_INPUT_NONE;
            }
            showcase_attempt_end(&s, &r, input, now);
        } else {
            fprintf(stderr, "unknown command %s\n", word);
            return 2;
        }
        report(mode, &s, event, now, running_cue);
    }
    return 0;
}

static int run_nav(void)
{
    showcase_t s;
    showcase_init(&s, real_table, (uint8_t)COUNT_OF(real_table), 0);
    for (uint8_t e = 0; e < s.count; ++e) {
        const uint8_t partner = showcase_partner_of(&s, e);
        printf("%s|%s|%u|%u|%s\n", s.entries[e].title, s.entries[showcase_main_of(&s, e)].title,
               showcase_history_count(&s, e), showcase_history_position(&s, e),
               partner != e ? s.entries[partner].title : "");
    }
    return 0;
}

/* ---- Screens ---------------------------------------------------------------------- */

static void screens_for(const showcase_entry_t *table, uint8_t count, const char *label)
{
    static display_t d;
    showcase_t s;
    for (uint8_t e = 0; e < count; ++e) {
        showcase_init(&s, table, count, 0);
        s.entry = e;
        printf("%s-%u-armed %d\n", label, e, showcase_draw_selector(&d, &s, 0));
        printf("%s-%u-running %d\n", label, e,
               showcase_draw_running(&d, &s, SHOWCASE_CUE_NONE));
        printf("%s-%u-running-lift %d\n", label, e,
               showcase_draw_running(&d, &s, SHOWCASE_CUE_LIFT));
        for (int o = 0; o < SHOWCASE_OUTCOMES; ++o) {
            showcase_result_t r = {0};
            r.outcome = (showcase_outcome_t)o;
            r.arrived = 1;
            r.up_ms = 99900u;
            r.hold_ms = 999900u;
            r.run_ms = 1u;
            r.tops = (o % 2) ? 65535u : 0u;
            r.probe = table[e].probe;
            r.value_milli = (o % 2) ? INT32_MAX : INT32_MIN;
            r.detail_milli = (o % 2) ? INT32_MIN : 359400; /* a three-digit bearing */
            r.has_detail = 1;
            s.phase = SHOWCASE_ARMING;
            s.have_result = 1;
            s.result_entry = e;
            s.last = r;
            s.attempts[e] = 999;
            s.held[e] = 999;
            printf("%s-%u-result-%s %d\n", label, e, outcome_names[o],
                   showcase_draw_selector(&d, &s, 0));
            showcase_pause(&s, SHOWCASE_PAUSE_RESULT);
            printf("%s-%u-kept-%s %d\n", label, e, outcome_names[o],
                   showcase_draw_selector(&d, &s, 0));
        }
        s.have_result = 0;
        for (int p = SHOWCASE_PAUSE_BUTTON; p <= SHOWCASE_PAUSE_NO_MOTOR; ++p) {
            showcase_pause(&s, (showcase_pause_t)p);
            printf("%s-%u-paused-%d %d\n", label, e, p, showcase_draw_selector(&d, &s, 0));
        }
    }
}

static int run_screens(void)
{
    static display_t d;
    screens_for(real_table, (uint8_t)COUNT_OF(real_table), "real");
    screens_for(showcase_entries, showcase_entry_count, "firmware");
    screens_for(wide_table, (uint8_t)COUNT_OF(wide_table), "wide");
    showcase_t s;
    for (uint8_t e = 0; e < COUNT_OF(over_table); ++e) {
        showcase_init(&s, over_table, (uint8_t)COUNT_OF(over_table), 0);
        s.entry = e;
        printf("over-%u-armed %d\n", e, showcase_draw_selector(&d, &s, 0));
    }
    printf("boot %d\n", showcase_draw_boot(&d, "welcome to", "JETHRO'S", "WORLD", 600));
    return 0;
}

/* Caption rows then panel rows, for the review sheet builder. */
static void dump(const char *caption, const display_t *d)
{
    printf("=== %s\n", caption);
    for (int y = 0; y < DISPLAY_HEIGHT; ++y) {
        for (int x = 0; x < DISPLAY_WIDTH; ++x) {
            const uint8_t byte = d->buf[1 + (y / 8) * DISPLAY_WIDTH + x];
            putchar((byte >> (y % 8)) & 1 ? '#' : '.');
        }
        putchar('\n');
    }
}

/* The selector after an attempt on `entry`, 1.2 s into the next countdown, or with the
 * result kept up by its pause as a hardware test's is. */
static void after(showcase_t *s, uint8_t entry, const showcase_result_t *r, uint16_t attempts,
                  uint16_t held, int kept, display_t *d)
{
    s->entry = entry;
    s->attempts[entry] = attempts;
    s->held[entry] = held;
    s->last = *r;
    s->have_result = 1;
    s->result_entry = entry;
    s->phase = kept ? SHOWCASE_PAUSED : SHOWCASE_ARMING;
    s->pause = kept ? SHOWCASE_PAUSE_RESULT : SHOWCASE_PAUSE_NONE;
    s->deadline_ms = 6000u;
    s->armed_ms = 6000u;
    showcase_draw_selector(d, s, 1200);
}

/* The screens of Experiment 07's display figure, drawn from the firmware's table. The
 * results carry example values. */
static int run_render(void)
{
    static display_t d;
    const uint8_t count = showcase_entry_count;
    showcase_t s;

    showcase_draw_boot(&d, "welcome to", "JETHRO'S", "WORLD", 600);
    dump("Boot", &d);

    showcase_init(&s, showcase_entries, count, 0);
    showcase_select_step(&s, SHOWCASE_INPUT_TAP, 0);
    showcase_draw_selector(&d, &s, 600);
    dump("PID armed, hints up", &d);

    s.entry = entry_named(showcase_entries, count, "SWING-UP");
    showcase_select_step(&s, SHOWCASE_INPUT_HOLD, 0);
    showcase_draw_selector(&d, &s, 600);
    dump("NEAR MISS, in SWING-UP's history", &d);

    const uint8_t jethro = entry_named(showcase_entries, count, "JETHRO");
    s.entry = jethro;
    s.phase = SHOWCASE_RUNNING;
    showcase_draw_running(&d, &s, SHOWCASE_CUE_NONE);
    dump("JETHRO running", &d);

    s.entry = entry_named(showcase_entries, count, "FREE SWING");
    showcase_draw_running(&d, &s, SHOWCASE_CUE_LIFT);
    dump("FREE SWING asking for the lift", &d);

    showcase_result_t held = {0};
    held.outcome = SHOWCASE_HELD;
    held.arrived = 1;
    held.up_ms = 2622u;
    held.hold_ms = 336318u;
    held.run_ms = 338940u;
    after(&s, jethro, &held, 9, 7, 0, &d);
    dump("JETHRO's result", &d);

    showcase_result_t measured = {0};
    measured.outcome = SHOWCASE_MEASURED;
    measured.probe = SHOWCASE_PROBE_RINGDOWN;
    measured.value_milli = 16234;
    measured.detail_milli = 1170;
    measured.has_detail = 1;
    after(&s, entry_named(showcase_entries, count, "RING-DOWN"), &measured, 3, 0, 1, &d);
    dump("RING-DOWN's result, kept up", &d);

    showcase_init(&s, showcase_entries, count, 0);
    s.entry = entry_named(showcase_entries, count, "BALANCE");
    showcase_pause(&s, SHOWCASE_PAUSE_BUTTON);
    showcase_draw_selector(&d, &s, 0);
    dump("Paused by a press", &d);

    showcase_pause(&s, SHOWCASE_PAUSE_TRAVEL);
    showcase_draw_selector(&d, &s, 0);
    dump("Stopped at the travel limit", &d);
    return 0;
}

/* ---- The firmware's table ---------------------------------------------------------- */

static int run_table(void)
{
    static const char *kinds[] = {"stock", "rl_balance", "rl_from_rest", "probe", "stock_lqr"};
    static const char *probes[] = {"", "ringdown", "freeswing", "tilt"};
    for (uint8_t k = 0; k < showcase_entry_count; ++k) {
        const showcase_entry_t *e = &showcase_entries[k];
        printf("%s|%u|%u|%u|%s|%s|%lu", e->title, e->group, e->is_main, e->is_variant,
               kinds[e->kind], probes[e->probe], (unsigned long)e->fall_persist_cycles);
        if (e->policy != NULL) {
            printf("|%s|%.9g|%d", e->policy->name, (double)e->policy->a_max, e->policy->squash);
        }
        printf("\n");
    }
    return 0;
}

/* Lines of `name o0 o1 o2 o3 o4`; prints the named table policy's forward and command. */
static int run_policies(void)
{
    char line[512];
    char name[64];
    float obs[POLICY_NUM_OBS];
    while (fgets(line, sizeof line, stdin) != NULL) {
        if (sscanf(line, "%63s %f %f %f %f %f", name, &obs[0], &obs[1], &obs[2], &obs[3],
                   &obs[4]) != 6) {
            continue;
        }
        const policy_t *p = NULL;
        for (uint8_t k = 0; k < showcase_entry_count; ++k) {
            if (showcase_entries[k].policy != NULL
                && strcmp(showcase_entries[k].policy->name, name) == 0) {
                p = showcase_entries[k].policy;
            }
        }
        if (p == NULL) {
            printf("missing\n");
            continue;
        }
        printf("%.9g %.9g\n", (double)policy_forward_with(p, obs),
               (double)policy_command_with(p, obs));
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "table") == 0) {
        return run_table();
    }
    if (argc == 2 && strcmp(argv[1], "policies") == 0) {
        return run_policies();
    }
    if (argc == 4 && strcmp(argv[1], "pixel") == 0) {
        return run_pixel(atoi(argv[2]), atoi(argv[3]));
    }
    if (argc == 2 && strcmp(argv[1], "init") == 0) {
        return run_init();
    }
    if (argc == 2 && strcmp(argv[1], "flush") == 0) {
        return run_flush();
    }
    if (argc == 4 && strcmp(argv[1], "text") == 0) {
        return run_text(atoi(argv[2]), argv[3]);
    }
    if (argc == 2 && strcmp(argv[1], "button") == 0) {
        return run_button();
    }
    if (argc == 3 && strcmp(argv[1], "buzzer") == 0) {
        return run_buzzer(argv[2]);
    }
    if (argc == 4 && strcmp(argv[1], "beeps") == 0) {
        return run_beeps(atoi(argv[2]), atoi(argv[3]));
    }
    if (argc == 3 && strcmp(argv[1], "attempt") == 0) {
        return run_attempt(argv[2]);
    }
    if (argc == 7 && strcmp(argv[1], "format") == 0) {
        return run_format(argv[2], argv[3], strtol(argv[4], NULL, 10), argv[5], atoi(argv[6]));
    }
    if (argc == 2 && strcmp(argv[1], "carousel") == 0) {
        return run_script(REPORT_STATE);
    }
    if (argc == 2 && strcmp(argv[1], "sounds") == 0) {
        return run_script(REPORT_SOUND);
    }
    if (argc == 2 && strcmp(argv[1], "screen") == 0) {
        return run_script(REPORT_SCREEN);
    }
    if (argc == 2 && strcmp(argv[1], "nav") == 0) {
        return run_nav();
    }
    if (argc == 2 && strcmp(argv[1], "screens") == 0) {
        return run_screens();
    }
    if (argc == 2 && strcmp(argv[1], "render") == 0) {
        return run_render();
    }
    fprintf(stderr, "usage: see the comment at the top of test_showcase.c\n");
    return 2;
}

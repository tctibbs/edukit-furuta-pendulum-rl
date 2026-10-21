#include "showcase.h"

#include <stdio.h>
#include <string.h>

#define COUNT_OF(a) (sizeof(a) / sizeof((a)[0]))

/* ---- Button ---------------------------------------------------------------------- */

void button_init(button_t *b)
{
    memset(b, 0, sizeof *b);
}

button_event_t button_sample_1ms(button_t *b, int pressed)
{
    button_event_t event = BUTTON_NONE;
    const uint8_t sample = pressed ? 1u : 0u;

    if (sample != b->raw) {
        b->raw = sample;
        b->raw_ms = 0;
    } else if (b->raw_ms < UINT16_MAX) {
        b->raw_ms++;
    }

    if (b->raw != b->level && b->raw_ms >= SHOWCASE_DEBOUNCE_MS) {
        b->level = b->raw;
        if (b->level) {
            b->held_ms = 0;
            b->long_sent = 0;
        } else if (!b->long_sent && b->armed) {
            event = BUTTON_SHORT;
        }
    }
    if (!b->level && b->raw == 0 && b->raw_ms >= SHOWCASE_DEBOUNCE_MS) {
        b->armed = 1;
    }

    if (b->level) {
        if (b->held_ms < UINT16_MAX) {
            b->held_ms++;
        }
        if (!b->long_sent && b->held_ms >= SHOWCASE_LONG_PRESS_MS) {
            b->long_sent = 1;
            if (b->armed) {
                event = BUTTON_LONG;
            }
        }
    }
    return event;
}

/* ---- Buzzer ---------------------------------------------------------------------- */

/* Chosen by ear at the bench on 2026-09-13, at the quiet setting. The mode and history
 * sounds are a rising and falling pair, the catch a double chirp, and the welcome an
 * arpeggio. The two swap tunes were not auditioned. Each goes there and back between two
 * pitches and neither rises nor falls, unlike a move along a level or between levels.
 * The one into the variant goes up and back, the one out of it down and back, and the
 * difference tells which entry is armed without a display. */
static const note_t mode_notes[] = {NOTE(1319, 25, 70), NOTE(1760, 45, 70)};
static const note_t newer_notes[] = {NOTE(1760, 25, 70), NOTE(1319, 45, 70)};
static const note_t dive_notes[] = {NOTE(1568, 35, 70), NOTE(1319, 35, 70), NOTE(1047, 70, 60)};
static const note_t climb_notes[] = {NOTE(1047, 35, 70), NOTE(1319, 35, 70), NOTE(1568, 70, 60)};
static const note_t swap_notes[] = {NOTE(1568, 25, 70), NOTE(2093, 25, 70), NOTE(1568, 40, 60)};
static const note_t swap_back_notes[] = {NOTE(2093, 25, 70), NOTE(1568, 25, 70),
                                         NOTE(2093, 40, 60)};
static const note_t tick_notes[] = {NOTE(2093, 6, 60)};
static const note_t ready_notes[] = {NOTE(1319, 40, 40)};
static const note_t catch_notes[] = {GLIDE(1600, 2400, 50, 60), REST(40),
                                     GLIDE(1800, 3000, 70, 70), NOTE(3000, 50, 20)};
static const note_t fall_notes[] = {GLIDE(1100, 500, 300, 50), NOTE(500, 60, 15)};
static const note_t alarm_notes[] = {NOTE(880, 90, 60), REST(70), NOTE(880, 90, 60), REST(70),
                                     NOTE(880, 90, 60)};
static const note_t welcome_notes[] = {NOTE(1047, 45, 60), NOTE(1319, 45, 60),
                                       NOTE(1568, 45, 60), NOTE(2093, 60, 55),
                                       NOTE(2093, 60, 25), NOTE(2093, 80, 10)};

typedef struct {
    const note_t *notes;
    uint8_t count;
} tune_t;

static const tune_t tunes[SOUND_COUNT] = {
    [SOUND_NONE] = {NULL, 0},
    [SOUND_MODE] = {mode_notes, COUNT_OF(mode_notes)},
    [SOUND_NEWER] = {newer_notes, COUNT_OF(newer_notes)},
    [SOUND_DIVE] = {dive_notes, COUNT_OF(dive_notes)},
    [SOUND_CLIMB] = {climb_notes, COUNT_OF(climb_notes)},
    [SOUND_SWAP] = {swap_notes, COUNT_OF(swap_notes)},
    [SOUND_SWAP_BACK] = {swap_back_notes, COUNT_OF(swap_back_notes)},
    [SOUND_TICK] = {tick_notes, COUNT_OF(tick_notes)},
    [SOUND_READY] = {ready_notes, COUNT_OF(ready_notes)},
    [SOUND_CATCH] = {catch_notes, COUNT_OF(catch_notes)},
    [SOUND_FALL] = {fall_notes, COUNT_OF(fall_notes)},
    [SOUND_ALARM] = {alarm_notes, COUNT_OF(alarm_notes)},
    [SOUND_WELCOME] = {welcome_notes, COUNT_OF(welcome_notes)},
};

void buzzer_init(buzzer_t *b)
{
    memset(b, 0, sizeof *b);
}

/* Starts any note table, replacing whatever was playing. The table must outlive it. */
static void buzzer_play_notes(buzzer_t *b, const note_t *notes, uint8_t count)
{
    if (notes == NULL || count == 0u) {
        b->notes = NULL;
        return;
    }
    b->notes = notes;
    b->count = count;
    b->index = 0;
    b->elapsed_ms = 0;
    b->left_ms = notes[0].ms ? notes[0].ms : 1u;
}

void buzzer_play(buzzer_t *b, sound_t sound)
{
    if (sound <= SOUND_NONE || sound >= SOUND_COUNT) {
        b->notes = NULL;
        return;
    }
    buzzer_play_notes(b, tunes[sound].notes, tunes[sound].count);
}

void buzzer_play_count(buzzer_t *b, uint8_t count, int history)
{
    if (count < 1u) {
        count = 1u;
    }
    if (count > BUZZER_MAX_BEEPS) {
        count = BUZZER_MAX_BEEPS;
    }
    uint8_t n = 0;
    for (uint8_t k = 0; k < count; ++k) {
        b->custom[n++] = (note_t)NOTE(1760, 60, 100); /* A6 */
        b->custom[n++] = (note_t)REST(120);
    }
    if (history) {
        b->custom[n++] = (note_t)NOTE(880, 200, 100); /* A5 */
    }
    buzzer_play_notes(b, b->custom, n);
}

int buzzer_tick_1ms(buzzer_t *b, uint16_t *hz, uint8_t *level)
{
    uint16_t want = 0;
    uint8_t want_level = 0;
    if (b->notes != NULL && b->index < b->count) {
        const note_t *note = &b->notes[b->index];
        want = note->hz;
        if (note->hz != 0u && note->end_hz != 0u && note->ms > 1u) {
            const int32_t span = (int32_t)note->end_hz - (int32_t)note->hz;
            want = (uint16_t)((int32_t)note->hz
                              + span * (int32_t)b->elapsed_ms / (int32_t)(note->ms - 1u));
        }
        if (want != 0u) {
            want_level = note->level ? note->level : 100u;
        }
        b->elapsed_ms++;
        if (--b->left_ms == 0) {
            b->elapsed_ms = 0;
            if (++b->index < b->count) {
                b->left_ms = b->notes[b->index].ms ? b->notes[b->index].ms : 1u;
            } else {
                b->notes = NULL;
            }
        }
    }
    if (want != b->hz || want_level != b->level) {
        b->hz = want;
        b->level = want_level;
        *hz = want;
        *level = want_level;
        return 1;
    }
    return 0;
}

/* ---- One attempt ----------------------------------------------------------------- */

#define COUNTS_PER_REV 2400
#define HALF_REV 1200
#define ARRIVE_COUNTS 20   /* 3 degrees, the firmware's RL_ARRIVE_COUNTS */
#define INSIDE_COUNTS 200  /* 30 degrees, the firmware's RL_STOP_TILT_COUNTS */
#define SETTLED_COUNTS 600 /* 90 degrees from hanging: a side the pendulum has fallen to */
#define FLIP_MIN_RAD_S2 5.0f
#define CYCLE_MS 2u

static int32_t floor_div(int32_t a, int32_t b)
{
    int32_t q = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) {
        --q;
    }
    return q;
}

static int32_t abs32(int32_t v)
{
    return v < 0 ? -v : v;
}

void showcase_attempt_reset(showcase_attempt_t *a, uint32_t prelude_ms)
{
    memset(a, 0, sizeof *a);
    a->prelude_ms = prelude_ms;
}

void showcase_attempt_step(showcase_attempt_t *a, int32_t counts, int32_t steps, float cmd)
{
    const int32_t wrapped = ((counts % COUNTS_PER_REV) + COUNTS_PER_REV) % COUNTS_PER_REV;
    const int32_t tilt = abs32(wrapped - HALF_REV);
    if (!a->arrived && tilt < ARRIVE_COUNTS) {
        a->arrived = 1;
        a->arrive_cycle = a->cycles;
    }
    if (a->arrived && tilt <= INSIDE_COUNTS) {
        if (!a->inside) {
            a->inside = 1;
            a->inside_since = a->cycles;
        }
        if (a->cycles - a->inside_since > a->best_hold_cycles) {
            a->best_hold_cycles = a->cycles - a->inside_since;
        }
    } else {
        a->inside = 0;
    }

    /* A pass over the top moves the pendulum from one hanging position to the next. It
     * counts once the pendulum is within 90 degrees of the new one, so a wobble about
     * upright, which never gets that far down, counts nothing. */
    const int32_t side = floor_div(counts + HALF_REV, COUNTS_PER_REV);
    if (abs32(counts - side * COUNTS_PER_REV) < SETTLED_COUNTS) {
        if (a->side_known && side != a->side) {
            const int32_t passes = abs32(side - a->side);
            a->tops = (uint16_t)((a->tops + passes > UINT16_MAX) ? UINT16_MAX : a->tops + passes);
        }
        a->side = side;
        a->side_known = 1;
    }

    if (abs32(steps) > a->peak_steps) {
        a->peak_steps = abs32(steps);
    }

    const int8_t sign = (cmd > FLIP_MIN_RAD_S2) ? 1 : ((cmd < -FLIP_MIN_RAD_S2) ? -1 : 0);
    if (sign != 0) {
        if (a->last_sign != 0 && sign != a->last_sign && a->flips < UINT16_MAX) {
            a->flips++;
        }
        a->last_sign = sign;
    }
    a->cycles++;
}

void showcase_attempt_result(const showcase_attempt_t *a, showcase_outcome_t outcome,
                             showcase_result_t *r)
{
    memset(r, 0, sizeof *r);
    r->outcome = outcome;
    r->run_ms = a->cycles * CYCLE_MS;
    r->arrived = a->arrived;
    if (a->arrived) {
        r->up_ms = a->prelude_ms + a->arrive_cycle * CYCLE_MS;
        r->hold_ms = a->best_hold_cycles * CYCLE_MS;
    }
    r->tops = a->tops;
    r->flips = a->flips;
    r->peak_steps = a->peak_steps;
}

/* ---- The carousel ---------------------------------------------------------------- */

/* Wrap-safe: true once `now` has reached `deadline`, across the 49-day tick wrap. */
static int reached(uint32_t now_ms, uint32_t deadline_ms)
{
    return (int32_t)(now_ms - deadline_ms) >= 0;
}

static void arm(showcase_t *s, uint32_t now_ms, uint32_t wait_ms)
{
    s->phase = SHOWCASE_ARMING;
    s->pause = SHOWCASE_PAUSE_NONE;
    s->deadline_ms = now_ms + wait_ms;
    s->armed_ms = wait_ms;
}

uint8_t showcase_groups(const showcase_t *s)
{
    uint8_t groups = 0;
    for (uint8_t k = 0; k < s->count; ++k) {
        if (s->entries[k].group > groups) {
            groups = s->entries[k].group;
        }
    }
    return groups;
}

static uint8_t main_of_group(const showcase_t *s, uint8_t group)
{
    for (uint8_t k = 0; k < s->count; ++k) {
        if (s->entries[k].group == group && s->entries[k].is_main) {
            return k;
        }
    }
    return 0;
}

uint8_t showcase_main_of(const showcase_t *s, uint8_t entry)
{
    return main_of_group(s, s->entries[entry].group);
}

static int is_history(const showcase_entry_t *e)
{
    return !e->is_main && !e->is_variant;
}

uint8_t showcase_history_count(const showcase_t *s, uint8_t entry)
{
    const uint8_t group = s->entries[entry].group;
    uint8_t n = 0;
    for (uint8_t k = 0; k < s->count; ++k) {
        if (s->entries[k].group == group && is_history(&s->entries[k])) {
            ++n;
        }
    }
    return n;
}

uint8_t showcase_history_position(const showcase_t *s, uint8_t entry)
{
    if (!is_history(&s->entries[entry])) {
        return 0;
    }
    const uint8_t group = s->entries[entry].group;
    uint8_t position = 0;
    for (uint8_t k = 0; k <= entry; ++k) {
        if (s->entries[k].group == group && is_history(&s->entries[k])) {
            ++position;
        }
    }
    return position;
}

uint8_t showcase_partner_of(const showcase_t *s, uint8_t entry)
{
    const showcase_entry_t *e = &s->entries[entry];
    if (e->is_variant) {
        return showcase_main_of(s, entry);
    }
    if (e->is_main) {
        for (uint8_t k = 0; k < s->count; ++k) {
            if (s->entries[k].group == e->group && s->entries[k].is_variant) {
                return k;
            }
        }
    }
    return entry;
}

static void select_entry(showcase_t *s, uint8_t entry, uint32_t now_ms)
{
    s->entry = entry;
    s->in_row = 0;
    arm(s, now_ms, SHOWCASE_ARM_MS);
}

/* A tap moves along the level: to the next main mode, wrapping from the last to the
 * first, or to the next newer version, and past the newest back to the main mode. A
 * variant is on the main modes' level. */
static showcase_event_t tap(showcase_t *s, uint32_t now_ms)
{
    const showcase_entry_t *e = &s->entries[s->entry];
    if (!is_history(e)) {
        const uint8_t next_group = (e->group >= showcase_groups(s)) ? 1u : (uint8_t)(e->group + 1u);
        select_entry(s, main_of_group(s, next_group), now_ms);
        return SHOWCASE_EVENT_MODE;
    }
    const uint8_t next = (uint8_t)(s->entry + 1u);
    if (next < s->count && s->entries[next].group == e->group && is_history(&s->entries[next])) {
        select_entry(s, next, now_ms);
        return SHOWCASE_EVENT_NEWER;
    }
    select_entry(s, showcase_main_of(s, s->entry), now_ms);
    return SHOWCASE_EVENT_CLIMB;
}

/* A hold swaps a main mode and its variant in place. Otherwise it changes level: into
 * the oldest version of a main mode's history, or back out to the main mode. A main
 * mode with neither restarts its countdown. */
static showcase_event_t hold(showcase_t *s, uint32_t now_ms)
{
    const showcase_entry_t *e = &s->entries[s->entry];
    const uint8_t partner = showcase_partner_of(s, s->entry);
    if (partner != s->entry) {
        select_entry(s, partner, now_ms);
        return SHOWCASE_EVENT_SWAP;
    }
    if (!e->is_main) {
        select_entry(s, showcase_main_of(s, s->entry), now_ms);
        return SHOWCASE_EVENT_CLIMB;
    }
    for (uint8_t k = 0; k < s->count; ++k) {
        if (s->entries[k].group == e->group && is_history(&s->entries[k])) {
            select_entry(s, k, now_ms);
            return SHOWCASE_EVENT_DIVE;
        }
    }
    arm(s, now_ms, SHOWCASE_ARM_MS);
    return SHOWCASE_EVENT_NO_HISTORY;
}

void showcase_init(showcase_t *s, const showcase_entry_t *entries, uint8_t count,
                   uint32_t now_ms)
{
    memset(s, 0, sizeof *s);
    s->entries = entries;
    s->count = (count > SHOWCASE_MAX_ENTRIES) ? SHOWCASE_MAX_ENTRIES : count;
    s->entry = main_of_group(s, showcase_groups(s));
    arm(s, now_ms, SHOWCASE_ARM_MS);
}

void showcase_set_auto(showcase_t *s, uint8_t attempts)
{
    s->auto_attempts = attempts;
}

showcase_event_t showcase_select_step(showcase_t *s, showcase_input_t input, uint32_t now_ms)
{
    switch (s->phase) {
    case SHOWCASE_RUNNING:
        return SHOWCASE_EVENT_NONE;
    case SHOWCASE_PAUSED:
        if (input == SHOWCASE_INPUT_TAP) {
            arm(s, now_ms, SHOWCASE_ARM_MS);
            return SHOWCASE_EVENT_RESUME;
        }
        if (input == SHOWCASE_INPUT_HOLD) {
            return hold(s, now_ms);
        }
        return SHOWCASE_EVENT_NONE;
    case SHOWCASE_ARMING:
    default:
        if (input == SHOWCASE_INPUT_TAP) {
            return tap(s, now_ms);
        }
        if (input == SHOWCASE_INPUT_HOLD) {
            return hold(s, now_ms);
        }
        if (reached(now_ms, s->deadline_ms)) {
            s->phase = SHOWCASE_RUNNING;
            return SHOWCASE_EVENT_START;
        }
        return SHOWCASE_EVENT_NONE;
    }
}

void showcase_pause(showcase_t *s, showcase_pause_t reason)
{
    s->phase = SHOWCASE_PAUSED;
    s->pause = reason;
}

void showcase_attempt_end(showcase_t *s, const showcase_result_t *r, showcase_input_t input,
                          uint32_t now_ms)
{
    s->last = *r;
    s->have_result = 1;
    s->result_entry = s->entry;
    if (s->attempts[s->entry] < UINT16_MAX) {
        s->attempts[s->entry]++;
    }
    if (r->probe == SHOWCASE_PROBE_NONE && r->hold_ms >= SHOWCASE_HELD_MS
        && s->held[s->entry] < UINT16_MAX) {
        s->held[s->entry]++;
    }
    if (s->in_row < UINT8_MAX) {
        s->in_row++;
    }

    switch (r->outcome) {
    case SHOWCASE_TRAVEL:
        showcase_pause(s, SHOWCASE_PAUSE_TRAVEL);
        return;
    case SHOWCASE_STALL:
        showcase_pause(s, SHOWCASE_PAUSE_STALL);
        return;
    case SHOWCASE_FAULT:
        showcase_pause(s, SHOWCASE_PAUSE_FAULT);
        return;
    default:
        break;
    }
    if (input != SHOWCASE_INPUT_NONE) {
        showcase_pause(s, SHOWCASE_PAUSE_BUTTON);
        return;
    }
    if (r->probe != SHOWCASE_PROBE_NONE && s->auto_attempts == 0) {
        showcase_pause(s, SHOWCASE_PAUSE_RESULT);
        return;
    }
    if (s->auto_attempts != 0 && s->in_row >= s->auto_attempts) {
        s->entry = (uint8_t)((s->entry + 1u) % s->count);
        s->in_row = 0;
    }
    arm(s, now_ms, SHOWCASE_RESULT_MS);
}

sound_t showcase_event_sound(const showcase_t *s, showcase_event_t event)
{
    switch (event) {
    case SHOWCASE_EVENT_START:
    case SHOWCASE_EVENT_RESUME:
        return SOUND_READY;
    case SHOWCASE_EVENT_MODE:
        return SOUND_MODE;
    case SHOWCASE_EVENT_NEWER:
        return SOUND_NEWER;
    case SHOWCASE_EVENT_DIVE:
        return SOUND_DIVE;
    case SHOWCASE_EVENT_CLIMB:
        return SOUND_CLIMB;
    case SHOWCASE_EVENT_SWAP:
        return s->entries[s->entry].is_variant ? SOUND_SWAP : SOUND_SWAP_BACK;
    case SHOWCASE_EVENT_NO_HISTORY:
        return SOUND_TICK;
    case SHOWCASE_EVENT_NONE:
    default:
        return SOUND_NONE;
    }
}

uint32_t showcase_seconds_left(const showcase_t *s, uint32_t now_ms)
{
    if (s->phase != SHOWCASE_ARMING || reached(now_ms, s->deadline_ms)) {
        return 0;
    }
    return (s->deadline_ms - now_ms + 999u) / 1000u;
}

uint16_t showcase_countdown_permille(const showcase_t *s, uint32_t now_ms)
{
    if (s->phase != SHOWCASE_ARMING || s->armed_ms == 0u || reached(now_ms, s->deadline_ms)) {
        return 1000u;
    }
    const uint32_t left = s->deadline_ms - now_ms;
    if (left >= s->armed_ms) {
        return 0u;
    }
    return (uint16_t)((s->armed_ms - left) * 1000u / s->armed_ms);
}

/* ---- Text ------------------------------------------------------------------------ */

/* Under 10 s to a tenth, "0.6s"; from there in whole seconds, "30s", up to 999. */
static void seconds_text(uint32_t ms, char *out, size_t n)
{
    if (ms < 9950u) {
        const uint32_t tenths = (ms + 50u) / 100u;
        snprintf(out, n, "%lu.%lus", (unsigned long)(tenths / 10u), (unsigned long)(tenths % 10u));
    } else {
        uint32_t whole = (ms + 500u) / 1000u;
        if (whole > 999u) {
            whole = 999u;
        }
        snprintf(out, n, "%lus", (unsigned long)whole);
    }
}

/* `milli` thousandths to `decimals` places, 1 to 3, rounded half away from zero. At most
 * `limit` units of the last place, so a wild number cannot overrun its line. */
static void fixed_text(int32_t milli, unsigned decimals, uint32_t limit, char *out, size_t n)
{
    static const uint32_t step_of[] = {1000u, 100u, 10u, 1u}; /* thousandths per last place */
    const uint32_t step = step_of[decimals];
    const uint32_t size = milli < 0 ? (uint32_t)(-(int64_t)milli) : (uint32_t)milli;
    uint32_t places = size / step + ((size % step) * 2u >= step ? 1u : 0u);
    if (places > limit) {
        places = limit;
    }
    const uint32_t per_unit = 1000u / step;
    snprintf(out, n, "%s%lu.%0*lu", (milli < 0 && places > 0u) ? "-" : "",
             (unsigned long)(places / per_unit), (int)decimals, (unsigned long)(places % per_unit));
}

/* A bearing in millidegrees as whole degrees from 0 to 359. */
static uint32_t bearing_degrees(int32_t milli)
{
    int64_t whole = ((int64_t)milli + (milli < 0 ? -500 : 500)) / 1000;
    whole %= 360;
    if (whole < 0) {
        whole += 360;
    }
    return (uint32_t)whole;
}

/* A MEASURED hardware test's number, at most 10 characters. */
static void probe_value_text(const showcase_result_t *r, char *out, size_t n)
{
    char number[24];
    switch (r->probe) {
    case SHOWCASE_PROBE_RINGDOWN:
        fixed_text(r->value_milli, 1u, 99999u, number, sizeof number);
        snprintf(out, n, "Q %s", number);
        break;
    case SHOWCASE_PROBE_FREESWING:
        fixed_text(r->value_milli, 3u, 99999u, number, sizeof number);
        snprintf(out, n, "%s Hz", number);
        break;
    case SHOWCASE_PROBE_TILT:
        /* Four characters between "TILT " and the sign: "0.51", "12.3", or "-0.5". */
        if (r->value_milli < 0) {
            fixed_text(r->value_milli, 1u, 99u, number, sizeof number);
        } else if (r->value_milli < 9995) {
            fixed_text(r->value_milli, 2u, 999u, number, sizeof number);
        } else {
            fixed_text(r->value_milli, 1u, 999u, number, sizeof number);
        }
        snprintf(out, n, "TILT %s\x7f", number); /* 0x7F is font5x7's degree sign */
        break;
    case SHOWCASE_PROBE_NONE:
    default:
        snprintf(out, n, "?");
        break;
    }
}

void showcase_format_outcome(const showcase_result_t *r, char *out, size_t n)
{
    char time[24];
    seconds_text(r->hold_ms, time, sizeof time);
    switch (r->outcome) {
    case SHOWCASE_HELD:
        snprintf(out, n, "HELD %s", time);
        break;
    case SHOWCASE_FELL:
        snprintf(out, n, "FELL %s", time);
        break;
    case SHOWCASE_TRAVEL:
        snprintf(out, n, "CENTER ARM");
        break;
    case SHOWCASE_NO_CATCH:
        snprintf(out, n, "NO CATCH");
        break;
    case SHOWCASE_STOPPED:
        snprintf(out, n, "STOPPED");
        break;
    case SHOWCASE_STALL:
        snprintf(out, n, "CHECK ARM");
        break;
    case SHOWCASE_FAULT:
        snprintf(out, n, "FAULT");
        break;
    case SHOWCASE_LAG:
        snprintf(out, n, "LOOP LAG");
        break;
    case SHOWCASE_MEASURED:
        probe_value_text(r, out, n);
        break;
    case SHOWCASE_NO_RELEASE:
        snprintf(out, n, "NO RELEASE");
        break;
    case SHOWCASE_NO_RESULT:
        snprintf(out, n, "NO RESULT");
        break;
    default:
        snprintf(out, n, "?");
        break;
    }
}

/* A hardware test's small line: its second number when it measured one, and the run. */
static void probe_detail_text(const showcase_result_t *r, uint16_t attempts, char *out, size_t n)
{
    char left[32] = "";
    if (r->outcome == SHOWCASE_MEASURED && r->has_detail) {
        char number[24];
        if (r->probe == SHOWCASE_PROBE_RINGDOWN) {
            fixed_text(r->detail_milli, 3u, 99999u, number, sizeof number);
            snprintf(left, sizeof left, "%s Hz", number);
        } else if (r->probe == SHOWCASE_PROBE_TILT) {
            snprintf(left, sizeof left, "bearing %lu\x7f",
                     (unsigned long)bearing_degrees(r->detail_milli));
        }
    }
    const unsigned a = attempts > 99u ? 99u : attempts;
    if (left[0] != '\0') {
        snprintf(out, n, "%s   run %u", left, a);
    } else {
        snprintf(out, n, "run %u", a);
    }
}

void showcase_format_detail(const showcase_result_t *r, uint16_t held, uint16_t attempts,
                            char *out, size_t n)
{
    if (r->probe != SHOWCASE_PROBE_NONE) {
        probe_detail_text(r, attempts, out, n);
        return;
    }
    char left[32] = "";
    if (r->tops > 0u) {
        snprintf(left, sizeof left, "spun %ux", (unsigned)(r->tops > 99u ? 99u : r->tops));
    } else if (r->arrived) {
        char time[24];
        seconds_text(r->up_ms, time, sizeof time);
        snprintf(left, sizeof left, "up %s", time);
    }
    const unsigned h = held > 99u ? 99u : held;
    const unsigned a = attempts > 99u ? 99u : attempts;
    if (left[0] != '\0') {
        snprintf(out, n, "%s   held %u/%u", left, h, a);
    } else {
        snprintf(out, n, "held %u/%u", h, a);
    }
}

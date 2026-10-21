/* The showcase carousel's logic: the button, the buzzer's tunes, one attempt's
 * statistics, and the carousel that steps through the project's history.
 *
 * Pure C99 with no I/O and no clock of its own: every function takes the time or the
 * sample it needs, so the host harness can script a press, a tune or a whole session and
 * check the result. `showcase_port_stm32.c` feeds it from the board, the button and the
 * buzzer from SysTick and the rest from the main loop between attempts.
 *
 * The carousel is a table of entries grouped under main modes. Each group has one main
 * entry, its end product, and either any number of history entries, the versions that
 * led to it, oldest first, or one variant, a sibling that runs in its place. In a group
 * of hardware tests, the history entries are the other tests. A tap moves
 * along the level you are on; a hold dives into a main mode's history or climbs back
 * out, or swaps a main mode and its variant. The carousel boots on the last group's main
 * entry.
 */
#ifndef SHOWCASE_H
#define SHOWCASE_H

#include <stddef.h>
#include <stdint.h>

struct policy; /* policy.h; an entry only points at one */

#define SHOWCASE_MAX_ENTRIES 16
#define SHOWCASE_TEXT 32 /* formatter buffers; the text itself is at most 21 characters */

#define SHOWCASE_DEBOUNCE_MS 20
#define SHOWCASE_LONG_PRESS_MS 1000
#define SHOWCASE_ARM_MS 4000    /* the countdown before an entry's first attempt */
#define SHOWCASE_RESULT_MS 6000 /* the result stays up this long before the next attempt */
#define SHOWCASE_HELD_MS 5000   /* an attempt counts as held from this long inside 30 degrees */

/* The kit's inverted-mode full state feedback with integral action, which the LQR entry
 * runs in the kit's own control loop. The five gains are the Edukit Manual's Sec. 14
 * design, page 84. Theta is the pendulum angle and phi the rotor angle; the gains are
 * positive, as the kit applies them. */
#define SHOWCASE_LQR_K_THETA 191.92f
#define SHOWCASE_LQR_K_THETA_DOT 25.07f
#define SHOWCASE_LQR_K_PHI 2.69f
#define SHOWCASE_LQR_K_PHI_DOT 3.12f
#define SHOWCASE_LQR_K_I 1.00f
/* Unity, the kit's default feedforward gain (firmware source: main sets it at boot, and
 * the 'g' mode takes a zero entry as 1). The Manual's page gives none. */
#define SHOWCASE_LQR_FEEDFORWARD 1.0f

/* ---- Button ---------------------------------------------------------------------- */

typedef enum {
    BUTTON_NONE = 0,
    BUTTON_SHORT, /* on release, when the press was shorter than the long threshold */
    BUTTON_LONG,  /* while still held, once, at the long threshold */
} button_event_t;

typedef struct {
    uint8_t level;     /* debounced state, 1 pressed */
    uint8_t raw;       /* last sample */
    uint16_t raw_ms;   /* how long `raw` has been unchanged */
    uint16_t held_ms;  /* how long `level` has been pressed */
    uint8_t long_sent; /* this press already reported LONG */
    uint8_t armed;     /* has read released since init; no events before that */
} button_t;

void button_init(button_t *b);

/* One sample per millisecond, `pressed` already active-high. A button held from boot,
 * or a pin stuck at its pressed level, reports nothing until it has read released for
 * the debounce time, so it cannot act by itself. */
button_event_t button_sample_1ms(button_t *b, int pressed);

/* ---- Buzzer ---------------------------------------------------------------------- */

typedef enum {
    SOUND_NONE = 0,
    SOUND_MODE,      /* the next main mode */
    SOUND_NEWER,     /* the next version inside a history */
    SOUND_DIVE,      /* into a history */
    SOUND_CLIMB,     /* out of a history, or past its newest version */
    SOUND_SWAP,      /* from a main mode to its variant */
    SOUND_SWAP_BACK, /* from a variant back to its main mode */
    SOUND_TICK,      /* a hold on a mode with no history */
    SOUND_READY,     /* the countdown ran out, a resume, or a test asking for a hand */
    SOUND_CATCH,     /* the pendulum arrived upright, or a hardware test measured its number */
    SOUND_FALL,      /* an attempt ended without a hold, or a hardware test without its number */
    SOUND_ALARM,     /* a stop that needs the operator */
    SOUND_WELCOME,   /* boot */
    SOUND_COUNT,
} sound_t;

typedef struct {
    uint16_t hz;     /* start frequency; 0 is a rest */
    uint16_t end_hz; /* 0 holds `hz`; otherwise a linear glide from `hz` to this */
    uint16_t ms;
    uint8_t level;   /* loudness as a percent of the port's volume; 0 means 100 */
} note_t;

/* A held note, a glide, and a rest, for tune tables. */
#define NOTE(hz, ms, level) {(hz), 0, (ms), (level)}
#define GLIDE(from_hz, to_hz, ms, level) {(from_hz), (to_hz), (ms), (level)}
#define REST(ms) {0, 0, (ms), 0}

#define BUZZER_MAX_BEEPS 9

typedef struct {
    const note_t *notes;
    uint8_t count;
    uint8_t index;
    uint16_t left_ms;
    uint16_t elapsed_ms; /* into the current note, for a glide */
    uint16_t hz;         /* what the output is set to now */
    uint8_t level;
    note_t custom[2 * BUZZER_MAX_BEEPS + 1]; /* the notes `buzzer_play_count` builds */
} buzzer_t;

void buzzer_init(buzzer_t *b);

/* Starts a tune, replacing whatever was playing. */
void buzzer_play(buzzer_t *b, sound_t sound);

/* Beeps a number: `count` short high beeps, clamped to 1 to BUZZER_MAX_BEEPS, then one
 * low tone when `history` is set. How the carousel says which mode it has armed when no
 * display answered. */
void buzzer_play_count(buzzer_t *b, uint8_t count, int history);

/* Advances one millisecond. Returns 1 when the tone changes, with the new frequency in
 * `*hz` (0 means silent) and its loudness in `*level` (percent of the port's volume),
 * and 0 when the output should stay as it is. A glide changes the frequency every
 * millisecond. */
int buzzer_tick_1ms(buzzer_t *b, uint16_t *hz, uint8_t *level);

/* ---- One attempt ----------------------------------------------------------------- */

typedef enum {
    SHOWCASE_HELD = 0, /* ran its full time */
    SHOWCASE_FELL,
    SHOWCASE_TRAVEL,
    SHOWCASE_NO_CATCH, /* ran its full time without arriving */
    SHOWCASE_STOPPED,  /* the button ended it */
    SHOWCASE_STALL,
    SHOWCASE_FAULT,
    SHOWCASE_LAG,
    SHOWCASE_MEASURED,   /* a hardware test ran to its number */
    SHOWCASE_NO_RELEASE, /* a free swing that was never let go */
    SHOWCASE_NO_RESULT,  /* a hardware test that ran without the data for its number */
    SHOWCASE_OUTCOMES,
} showcase_outcome_t;

/* The hardware tests an entry can run. */
typedef enum {
    SHOWCASE_PROBE_NONE = 0,
    SHOWCASE_PROBE_RINGDOWN,  /* pumped up, released, and left to decay: Q_eff and frequency */
    SHOWCASE_PROBE_FREESWING, /* let go by hand with the rotor held: the suspended frequency */
    SHOWCASE_PROBE_TILT,      /* the rest angle around a turn of the arm: the base tilt */
} showcase_probe_t;

typedef struct {
    uint32_t cycles;
    uint32_t prelude_ms; /* time before the first cycle, the stock swing-up's */
    uint32_t arrive_cycle;
    uint32_t inside_since;     /* the cycle the current stretch inside 30 degrees began */
    uint32_t best_hold_cycles; /* the longest such stretch since arrival */
    uint8_t inside;            /* inside 30 degrees on the last cycle, after arrival */
    uint8_t arrived;
    uint8_t side_known;
    int32_t side; /* the hanging position the pendulum last settled near, in revolutions */
    uint16_t tops;
    uint16_t flips;
    int8_t last_sign;
    int32_t peak_steps;
} showcase_attempt_t;

typedef struct {
    showcase_outcome_t outcome;
    uint8_t arrived;
    uint32_t up_ms;   /* start to arrival, the stock swing-up included */
    uint32_t hold_ms; /* the longest unbroken stretch inside 30 degrees after arrival */
    uint32_t run_ms;
    uint16_t tops;    /* passes over the top from one side to the other */
    uint16_t flips;   /* reversals of a command stronger than 5 rad/s^2 */
    int32_t peak_steps;
    /* A hardware test's, which `showcase_attempt_result` leaves zero. `probe` is set on
     * every run of a test, measured or not: it picks the test's text and keeps the run
     * out of the held tally. With a MEASURED outcome the numbers are in thousandths.
     * Ring-down: Q_eff at the release amplitude, and the frequency in mHz when the decay
     * held a full cycle inside the band. Free swing: the frequency in mHz, and no second
     * number. Tilt: the amplitude, and the bearing, both in millidegrees. `has_detail`
     * is 1 when `detail_milli` holds a measured number. */
    showcase_probe_t probe;
    int32_t value_milli;
    int32_t detail_milli;
    uint8_t has_detail;
} showcase_result_t;

void showcase_attempt_reset(showcase_attempt_t *a, uint32_t prelude_ms);

/* One 2 ms control cycle: the pendulum in counts from hanging (continuous, 2400 a
 * revolution), the arm in microsteps from the attempt's start, the command in rad/s^2. */
void showcase_attempt_step(showcase_attempt_t *a, int32_t counts, int32_t steps, float cmd);

void showcase_attempt_result(const showcase_attempt_t *a, showcase_outcome_t outcome,
                             showcase_result_t *r);

/* ---- The carousel ---------------------------------------------------------------- */

typedef enum {
    SHOWCASE_STOCK = 0,    /* the kit's swing-up and controller */
    SHOWCASE_RL_BALANCE,   /* the kit's swing-up, a learned balance policy */
    SHOWCASE_RL_FROM_REST, /* a learned swing-up and balance from a hanging pendulum */
    SHOWCASE_PROBE,        /* a hardware test, the one `probe` names */
    SHOWCASE_STOCK_LQR,    /* the kit's swing-up, then its state feedback, SHOWCASE_LQR_* */
} showcase_kind_t;

/* An entry with neither is_main nor is_variant set is a history entry. */
typedef struct {
    const char *title;      /* at most 10 characters, drawn large */
    uint8_t group;          /* its main mode, numbered from 1 in table order */
    uint8_t is_main;        /* 1 for the entry a tap lands on, first in its group */
    uint8_t is_variant;     /* 1 for the sibling a hold on the main entry swaps to */
    showcase_kind_t kind;
    showcase_probe_t probe; /* SHOWCASE_PROBE_NONE unless the kind is SHOWCASE_PROBE */
    const struct policy *policy; /* NULL unless a learned policy runs */
    uint32_t fall_persist_cycles;
} showcase_entry_t;

typedef enum {
    SHOWCASE_ARMING = 0,
    SHOWCASE_RUNNING,
    SHOWCASE_PAUSED,
} showcase_phase_t;

typedef enum {
    SHOWCASE_PAUSE_NONE = 0,
    SHOWCASE_PAUSE_BUTTON,
    SHOWCASE_PAUSE_TRAVEL,
    SHOWCASE_PAUSE_STALL,
    SHOWCASE_PAUSE_FAULT,
    SHOWCASE_PAUSE_NO_MOTOR,
    SHOWCASE_PAUSE_RESULT, /* a hardware test's result, kept up until a press */
} showcase_pause_t;

typedef enum {
    SHOWCASE_INPUT_NONE = 0,
    SHOWCASE_INPUT_TAP,  /* a short press, or `n` from the host */
    SHOWCASE_INPUT_HOLD, /* a long press, or `h` from the host */
} showcase_input_t;

/* What a selector step did, so the port can play the matching sound. */
typedef enum {
    SHOWCASE_EVENT_NONE = 0,
    SHOWCASE_EVENT_START,
    SHOWCASE_EVENT_MODE,
    SHOWCASE_EVENT_NEWER,
    SHOWCASE_EVENT_DIVE,
    SHOWCASE_EVENT_CLIMB,
    SHOWCASE_EVENT_SWAP,
    SHOWCASE_EVENT_NO_HISTORY,
    SHOWCASE_EVENT_RESUME,
} showcase_event_t;

typedef struct {
    const showcase_entry_t *entries;
    uint8_t count;
    uint8_t entry;
    showcase_phase_t phase;
    showcase_pause_t pause;
    uint32_t deadline_ms;
    uint32_t armed_ms;      /* the countdown the deadline was set with, for the bar */
    uint8_t in_row;         /* attempts on this entry since it was selected */
    uint8_t auto_attempts;  /* 0 waits for a press; N moves on after N attempts */
    uint16_t attempts[SHOWCASE_MAX_ENTRIES];
    uint16_t held[SHOWCASE_MAX_ENTRIES];
    uint8_t have_result;
    uint8_t result_entry;
    showcase_result_t last;
} showcase_t;

/* Starts armed on the last group's main entry. */
void showcase_init(showcase_t *s, const showcase_entry_t *entries, uint8_t count,
                   uint32_t now_ms);

/* Moves on through the table after `attempts` attempts per entry without a press; 0
 * turns it off. For demos and unattended captures. */
void showcase_set_auto(showcase_t *s, uint8_t attempts);

/* One step of the selector between attempts. Returns START when the attempt on the
 * current entry should start now, and the phase is then RUNNING. */
showcase_event_t showcase_select_step(showcase_t *s, showcase_input_t input, uint32_t now_ms);

/* The attempt is over. A travel stop, a stall or a fault pauses for its reason, which the
 * operator has to see; otherwise a press that ended it pauses on the same entry. A
 * hardware test's run counts as an attempt and never as held. Its result stays up,
 * paused, until a press, because a test is a measurement to read once. Repeated with
 * nobody there, a free swing would hold the rotor waiting for a hand. With auto-advance
 * on, a test moves on as every other entry does. */
void showcase_attempt_end(showcase_t *s, const showcase_result_t *r, showcase_input_t input,
                          uint32_t now_ms);

/* Pauses for a reason found outside an attempt, such as the motor supply being off. */
void showcase_pause(showcase_t *s, showcase_pause_t reason);

/* The sound a selector event plays, on the entry the event left selected: a swap sounds
 * one way into the variant and the other way back out. */
sound_t showcase_event_sound(const showcase_t *s, showcase_event_t event);

/* Whole seconds until the armed attempt starts, rounded up. */
uint32_t showcase_seconds_left(const showcase_t *s, uint32_t now_ms);

/* How much of the countdown has run, 0 to 1000. */
uint16_t showcase_countdown_permille(const showcase_t *s, uint32_t now_ms);

/* Where an entry sits: the number of groups, the index of its group's main entry, how
 * many history entries its group has, and its position among them from 1 (0 for a main
 * entry or a variant, so nonzero means a history entry). */
uint8_t showcase_groups(const showcase_t *s);
uint8_t showcase_main_of(const showcase_t *s, uint8_t entry);
uint8_t showcase_history_count(const showcase_t *s, uint8_t entry);
uint8_t showcase_history_position(const showcase_t *s, uint8_t entry);

/* The entry a hold swaps with: a main entry's variant, or a variant's main entry. The
 * entry itself when it has none. */
uint8_t showcase_partner_of(const showcase_t *s, uint8_t entry);

/* ---- Text, at most 21 characters each --------------------------------------------- */

/* The large result line: "HELD 30s", "FELL 0.6s", "NO CATCH"; for a hardware test its
 * number, "Q 16.2", "1.168 Hz", "TILT 0.51" and a degree sign, or why it has none. */
void showcase_format_outcome(const showcase_result_t *r, char *out, size_t n);

/* The small result line: "up 2.3s   held 2/3", "spun 3x   held 0/2", "held 0/2"; for a
 * hardware test its second number when it measured one, and the run count,
 * "1.170 Hz   run 3", "bearing 212" and a degree sign then "   run 3", or "run 3". `held`
 * is not shown for a hardware test. */
void showcase_format_detail(const showcase_result_t *r, uint16_t held, uint16_t attempts,
                            char *out, size_t n);

#endif /* SHOWCASE_H */

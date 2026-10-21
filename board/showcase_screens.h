/* The showcase's OLED screens, drawn into a framebuffer.
 *
 * A screen carries where you are (the mode, and pips for its members), one large thing,
 * the countdown, measured data from an attempt, and the button hints for the first moment
 * after a selection; never a line narrating what an entry does. Each screen
 * is first worked out as text, `showcase_screen_t`, and then drawn from it, so the host
 * tests can read every word a screen says as well as count what does not fit. Every draw
 * returns how many characters did not fit on the panel, which the host tests require to
 * be zero for every entry and state. The board draws these only with the motor stopped
 * or not yet started: a flush is a blocking I2C transfer of tens of milliseconds, and
 * the control loop has 2.
 */
#ifndef SHOWCASE_SCREENS_H
#define SHOWCASE_SCREENS_H

#include <stdint.h>

#include "display.h"
#include "showcase.h"

/* Where a screen's lines go. */
typedef enum {
    SHOWCASE_LAYOUT_ARMED = 0,     /* header, the title large, the countdown, fresh hints */
    SHOWCASE_LAYOUT_RESULT,        /* header, the title small, the outcome large, the detail,
                                    * the countdown */
    SHOWCASE_LAYOUT_RESULT_PAUSED, /* header, the title small, the outcome large, the detail,
                                    * one hint */
    SHOWCASE_LAYOUT_PAUSED,        /* header, the big line, one hint */
    SHOWCASE_LAYOUT_STOPPED,       /* two words on top, the big line in a lit band, one hint */
    SHOWCASE_LAYOUT_RUNNING,       /* header, the title large, "running" or the cue */
} showcase_layout_t;

/* What a running attempt asks of the operator, drawn under its band. */
typedef enum {
    SHOWCASE_CUE_NONE = 0,
    SHOWCASE_CUE_LIFT, /* the free swing, once its datum is taken: lift the pendulum, let go */
} showcase_cue_t;

/* A screen as text. An empty string is a line the screen does not have. */
typedef struct {
    showcase_layout_t layout;
    char top_left[SHOWCASE_TEXT];  /* the mode, "1/5", or a stop's "STOPPED" */
    char top_right[SHOWCASE_TEXT]; /* a stop's "motor off" */
    char title[SHOWCASE_TEXT];     /* a result's entry, small above the outcome */
    char big[SHOWCASE_TEXT];       /* drawn large */
    char detail[SHOWCASE_TEXT];    /* a result's small line, or a run's state or cue */
    char hint_left[SHOWCASE_TEXT];
    char hint_right[SHOWCASE_TEXT];
    uint8_t dots;                  /* the mode's members, as pips; 0 for a mode of one */
    uint8_t dot;                   /* the shown member */
    uint16_t bar;                  /* the countdown, permille, on ARMED and RESULT */
} showcase_screen_t;

/* How long the button hints stay up after a selection. */
#define SHOWCASE_HINT_MS 1500u

/* The screen for the carousel between attempts: the current entry armed, its last
 * result, or the reason it is paused. */
void showcase_selector_screen(const showcase_t *s, uint32_t now_ms, showcase_screen_t *out);

/* The screen left up while an attempt runs. */
void showcase_running_screen(const showcase_t *s, showcase_cue_t cue, showcase_screen_t *out);

/* Draws a screen worked out above. */
int showcase_draw_screen(display_t *d, const showcase_screen_t *screen);

/* Each works its screen out and draws it. */
int showcase_draw_selector(display_t *d, const showcase_t *s, uint32_t now_ms);
int showcase_draw_running(display_t *d, const showcase_t *s, showcase_cue_t cue);

/* The boot screen: a small line, two large lines, and a bar `permille` full. */
int showcase_draw_boot(display_t *d, const char *small, const char *big1, const char *big2,
                       uint16_t permille);

#endif /* SHOWCASE_SCREENS_H */

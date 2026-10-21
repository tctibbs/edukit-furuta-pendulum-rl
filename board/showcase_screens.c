#include "showcase_screens.h"

#include <stdio.h>
#include <string.h>

/* Rows. The header, the mode on the left and its member pips on the right, sits in a
 * two-color module's yellow band (rows 0 to 15), everything else in the blue. */
#define ROW_PIPS 1
#define ROW_LARGE_3 28 /* a title at three times size, centered in the blue */
#define ROW_LARGE_2 31 /* a title that only fits at twice */
#define ROW_RUN_3 26
#define ROW_RUN_2 29
#define ROW_STATE 52 /* "running", or a test's cue */
#define ROW_HINT_FRESH 52
#define ROW_RESULT_TITLE 19
#define ROW_BIG_RESULT 29
#define ROW_DETAIL 46
#define ROW_HINT 56
#define EDGE_H 3 /* the countdown, a line along the bottom edge */
#define BAND_H 22
#define STOP_BAND_Y 18
#define LARGE_MARGIN 8 /* each side, for a title at three times size */

/* ---- Working a screen out ------------------------------------------------------- */

static void put(char *line, const char *text)
{
    snprintf(line, SHOWCASE_TEXT, "%s", text != NULL ? text : "");
}

static void blank(showcase_screen_t *out, showcase_layout_t layout)
{
    memset(out, 0, sizeof *out);
    out->layout = layout;
}

/* The mode, "4/5", and one pip per member of it: the main entry first, then its variant
 * or its history oldest first, the shown one filled. A mode of one member has no pips. */
static void header(const showcase_t *s, showcase_screen_t *out)
{
    const showcase_entry_t *e = &s->entries[s->entry];
    snprintf(out->top_left, SHOWCASE_TEXT, "%u/%u", (unsigned)e->group,
             (unsigned)showcase_groups(s));
    const uint8_t main = showcase_main_of(s, s->entry);
    const uint8_t variants = showcase_partner_of(s, main) != main ? 1u : 0u;
    const uint8_t members = (uint8_t)(1u + variants + showcase_history_count(s, main));
    if (members > 1u) {
        out->dots = members;
        out->dot = e->is_variant ? 1u : showcase_history_position(s, s->entry);
    }
}

/* The first SHOWCASE_HINT_MS of a countdown, while the button hints stay up. */
static int fresh(const showcase_t *s, uint32_t now_ms)
{
    if (showcase_countdown_permille(s, now_ms) >= 1000u) {
        return 0;
    }
    const uint32_t left = s->deadline_ms - now_ms;
    const uint32_t elapsed = left >= s->armed_ms ? 0u : s->armed_ms - left;
    return elapsed < SHOWCASE_HINT_MS;
}

static void armed(const showcase_t *s, uint32_t now_ms, showcase_screen_t *out)
{
    const showcase_entry_t *e = &s->entries[s->entry];
    blank(out, SHOWCASE_LAYOUT_ARMED);
    header(s, out);
    put(out->big, e->title);
    out->bar = showcase_countdown_permille(s, now_ms);
    if (!fresh(s, now_ms)) {
        return;
    }
    const uint8_t partner = showcase_partner_of(s, s->entry);
    if (partner != s->entry) {
        put(out->hint_left, "tap next");
        snprintf(out->hint_right, SHOWCASE_TEXT, "hold %s", s->entries[partner].title);
    } else if (e->is_main) {
        /* A hardware test's group holds more tests; any other group's, older versions. */
        const char *more = e->kind == SHOWCASE_PROBE ? "hold tests" : "hold history";
        put(out->hint_left, "tap next");
        put(out->hint_right, showcase_history_count(s, s->entry) ? more : NULL);
    } else {
        put(out->hint_left, e->kind == SHOWCASE_PROBE ? "tap next" : "tap newer");
        put(out->hint_right, "hold exit");
    }
}

static void result(const showcase_t *s, uint32_t now_ms, showcase_layout_t layout,
                   showcase_screen_t *out)
{
    blank(out, layout);
    header(s, out);
    put(out->title, s->entries[s->entry].title);
    showcase_format_outcome(&s->last, out->big, sizeof out->big);
    showcase_format_detail(&s->last, s->held[s->entry], s->attempts[s->entry], out->detail,
                           sizeof out->detail);
    if (layout == SHOWCASE_LAYOUT_RESULT) {
        out->bar = showcase_countdown_permille(s, now_ms);
    } else {
        put(out->hint_left, "tap to run again");
    }
}

static void stopped(showcase_screen_t *out, const char *left, const char *right,
                    const char *big, const char *hint)
{
    blank(out, SHOWCASE_LAYOUT_STOPPED);
    put(out->top_left, left);
    put(out->top_right, right);
    put(out->big, big);
    put(out->hint_left, hint);
}

/* A stop for the operator names what to do before the tap. The arm stays where the stop
 * left it, with the bridges off, and the next attempt takes wherever it is as home.
 * Because a fault skips the return home, its screen asks for the arm to be centered. */
static void paused(const showcase_t *s, uint32_t now_ms, showcase_screen_t *out)
{
    switch (s->pause) {
    case SHOWCASE_PAUSE_TRAVEL:
        stopped(out, "STOPPED", "motor off", "CENTER ARM", "then tap");
        break;
    case SHOWCASE_PAUSE_STALL:
        stopped(out, "STOPPED", "motor off", "CHECK ARM", "then tap");
        break;
    case SHOWCASE_PAUSE_FAULT:
        stopped(out, "STOPPED", "motor off", "FAULT", "center arm, then tap");
        break;
    case SHOWCASE_PAUSE_NO_MOTOR:
        stopped(out, "CHECK", NULL, "NO MOTOR", "tap to retry");
        break;
    case SHOWCASE_PAUSE_RESULT:
        result(s, now_ms, SHOWCASE_LAYOUT_RESULT_PAUSED, out);
        break;
    case SHOWCASE_PAUSE_BUTTON:
    case SHOWCASE_PAUSE_NONE:
    default:
        blank(out, SHOWCASE_LAYOUT_PAUSED);
        header(s, out);
        put(out->big, "PAUSED");
        put(out->hint_left, "tap to resume");
        break;
    }
}

void showcase_selector_screen(const showcase_t *s, uint32_t now_ms, showcase_screen_t *out)
{
    if (s->phase == SHOWCASE_PAUSED) {
        paused(s, now_ms, out);
    } else if (s->have_result && s->result_entry == s->entry) {
        result(s, now_ms, SHOWCASE_LAYOUT_RESULT, out);
    } else {
        armed(s, now_ms, out);
    }
}

void showcase_running_screen(const showcase_t *s, showcase_cue_t cue, showcase_screen_t *out)
{
    blank(out, SHOWCASE_LAYOUT_RUNNING);
    header(s, out);
    put(out->big, s->entries[s->entry].title);
    put(out->detail, cue == SHOWCASE_CUE_LIFT ? "lift, then let go" : "running");
}

/* ---- Drawing it ---------------------------------------------------------------- */

/* Lit pixels with the text cut out of them, across the panel. */
static int band(display_t *d, int y, int h, const char *text, int scale)
{
    display_fill(d, 0, y, DISPLAY_WIDTH, h, 0);
    const int clipped =
        display_text_center(d, y + (h - DISPLAY_GLYPH_HEIGHT * scale) / 2, text, scale);
    display_invert(d, 0, y, DISPLAY_WIDTH, h);
    return clipped;
}

/* One hint at each end of a line. Two that would not keep a space between them count
 * the characters they overlap by as clipped. */
static int hints(display_t *d, int row, const char *left, const char *right)
{
    int clipped = 0;
    if (left[0] != '\0') {
        clipped += display_text(d, 0, row, left, 1);
    }
    if (right[0] != '\0') {
        clipped += display_text_right(d, row, right, 1);
    }
    if (left[0] != '\0' && right[0] != '\0') {
        const int columns = (int)strlen(left) + 1 + (int)strlen(right);
        if (columns > DISPLAY_COLUMNS) {
            clipped += columns - DISPLAY_COLUMNS;
        }
    }
    return clipped;
}

static int top(display_t *d, const showcase_screen_t *screen)
{
    int clipped = display_text(d, 0, 0, screen->top_left, 1);
    if (screen->top_right[0] != '\0') {
        clipped += display_text_right(d, 0, screen->top_right, 1);
    }
    if (screen->dots != 0u) {
        const int width = screen->dots * 8 - 3;
        display_dots(d, DISPLAY_WIDTH - width, ROW_PIPS, screen->dots, screen->dot);
    }
    return clipped;
}

/* A title at three times size when it fits with a margin each side, else at twice. */
static int large(display_t *d, const char *text, int row_3, int row_2)
{
    if (display_text_width(text, 3) <= DISPLAY_WIDTH - 2 * LARGE_MARGIN) {
        return display_text_center(d, row_3, text, 3);
    }
    return display_text_center(d, row_2, text, 2);
}

/* The countdown, filling along the bottom edge. */
static void edge(display_t *d, uint16_t permille)
{
    if (permille > 1000u) {
        permille = 1000u;
    }
    display_fill(d, 0, DISPLAY_HEIGHT - EDGE_H, DISPLAY_WIDTH * permille / 1000, EDGE_H, 1);
}

int showcase_draw_screen(display_t *d, const showcase_screen_t *screen)
{
    display_clear(d);
    int clipped = top(d, screen);
    int hint_row = ROW_HINT;
    switch (screen->layout) {
    case SHOWCASE_LAYOUT_ARMED:
        clipped += large(d, screen->big, ROW_LARGE_3, ROW_LARGE_2);
        edge(d, screen->bar);
        hint_row = ROW_HINT_FRESH;
        break;
    case SHOWCASE_LAYOUT_RESULT:
    case SHOWCASE_LAYOUT_RESULT_PAUSED:
        clipped += display_text_center(d, ROW_RESULT_TITLE, screen->title, 1);
        clipped += display_text_center(d, ROW_BIG_RESULT, screen->big, 2);
        clipped += display_text_center(d, ROW_DETAIL, screen->detail, 1);
        if (screen->layout == SHOWCASE_LAYOUT_RESULT) {
            edge(d, screen->bar);
        }
        break;
    case SHOWCASE_LAYOUT_PAUSED:
        clipped += large(d, screen->big, ROW_LARGE_3, ROW_LARGE_2);
        break;
    case SHOWCASE_LAYOUT_STOPPED:
        clipped += band(d, STOP_BAND_Y, BAND_H, screen->big, 2);
        break;
    case SHOWCASE_LAYOUT_RUNNING:
    default:
        clipped += large(d, screen->big, ROW_RUN_3, ROW_RUN_2);
        clipped += display_text_center(d, ROW_STATE, screen->detail, 1);
        break;
    }
    clipped += hints(d, hint_row, screen->hint_left, screen->hint_right);
    return clipped;
}

int showcase_draw_selector(display_t *d, const showcase_t *s, uint32_t now_ms)
{
    showcase_screen_t screen;
    showcase_selector_screen(s, now_ms, &screen);
    return showcase_draw_screen(d, &screen);
}

int showcase_draw_running(display_t *d, const showcase_t *s, showcase_cue_t cue)
{
    showcase_screen_t screen;
    showcase_running_screen(s, cue, &screen);
    return showcase_draw_screen(d, &screen);
}

int showcase_draw_boot(display_t *d, const char *small, const char *big1, const char *big2,
                       uint16_t permille)
{
    display_clear(d);
    int clipped = display_text_center(d, 4, small, 1);
    clipped += display_text_center(d, 18, big1, 2);
    clipped += display_text_center(d, 34, big2, 2);
    display_bar(d, 54, permille);
    return clipped;
}

/* A framebuffer and text renderer for the SSD1306 128x64 OLED on the showcase build.
 *
 * The drawing is pure C99 with no I/O, so the host harness can render every screen and
 * check it. Getting the bytes to the panel is the caller's: `display_flush` hands them to
 * a write callback, which on the board is an I2C transmit and in the tests is a buffer.
 *
 * The panel's memory is 8 pages of 128 columns. In horizontal addressing mode a data
 * byte is one column of one page, bit 0 the page's top row, and the bytes run along
 * page 0 then page 1. The framebuffer is kept in exactly that order behind a one-byte
 * I2C control prefix, so a flush sends it without a copy.
 *
 * The two-color modules print rows 0 to 15 in yellow and the rest in blue; the screens
 * put their header line there.
 */
#ifndef DISPLAY_H
#define DISPLAY_H

#include <stddef.h>
#include <stdint.h>

#define DISPLAY_WIDTH 128
#define DISPLAY_HEIGHT 64
#define DISPLAY_BYTES (DISPLAY_WIDTH * DISPLAY_HEIGHT / 8)

/* I2C control bytes: every byte after 0x00 in a transmission is a command, every byte
 * after 0x40 is display data. */
#define DISPLAY_COMMAND_PREFIX 0x00
#define DISPLAY_DATA_PREFIX 0x40

#define DISPLAY_GLYPH_WIDTH 5
#define DISPLAY_GLYPH_HEIGHT 7
#define DISPLAY_ADVANCE 6    /* glyph plus one column of space */
#define DISPLAY_LINE 8       /* glyph plus one row of space */
#define DISPLAY_COLUMNS 21   /* characters per line at scale 1 */
#define DISPLAY_LINES 8

#define DISPLAY_YELLOW_ROWS 16

typedef struct {
    uint8_t buf[1 + DISPLAY_BYTES]; /* buf[0] is DISPLAY_DATA_PREFIX */
} display_t;

/* Sends `len` bytes as one I2C transmission. Returns 0 on success. */
typedef int (*display_write_fn)(void *ctx, const uint8_t *bytes, size_t len);

/* All pixels off. Also sets the data prefix, so call it before the first draw. */
void display_clear(display_t *d);

/* One pixel. Coordinates outside the panel are ignored. */
void display_pixel(display_t *d, int x, int y, int on);

/* A filled rectangle, clipped to the panel. */
void display_fill(display_t *d, int x, int y, int w, int h, int on);

/* A string at (x, y), its top-left corner, each glyph `scale` pixels per font pixel.
 * Characters outside 0x20 to 0x7F draw as '?', and 0x7F draws font5x7's degree sign.
 * Returns how many characters did not fit on the panel, so a test can prove every
 * screen's text is whole. */
int display_text(display_t *d, int x, int y, const char *s, int scale);

/* The pixel width `display_text` takes for `s` at `scale`, without the trailing space. */
int display_text_width(const char *s, int scale);

/* A string centered across the panel, or ending at its right edge. Return as display_text. */
int display_text_center(display_t *d, int y, const char *s, int scale);
int display_text_right(display_t *d, int y, const char *s, int scale);

/* Flips every pixel in a rectangle, clipped to the panel: text drawn first comes out
 * dark on a lit band. */
void display_invert(display_t *d, int x, int y, int w, int h);

/* A 4-pixel-tall bar across the panel, outlined, `permille` of it filled: the countdown. */
void display_bar(display_t *d, int y, uint16_t permille);

/* Page dots: `count` 5-pixel circles 8 pixels apart from (x, y), `current` filled. */
void display_dots(display_t *d, int x, int y, int count, int current);

/* The command packet that configures and switches on a 128x64 panel with its internal
 * charge pump, prefix included. */
const uint8_t *display_init_packet(size_t *len);

/* Sends the whole framebuffer: a command packet setting the column and page window to
 * the full panel, then the data packet. Returns 0 on success, -1 if either write
 * failed. */
int display_flush(const display_t *d, display_write_fn write, void *ctx);

#endif /* DISPLAY_H */

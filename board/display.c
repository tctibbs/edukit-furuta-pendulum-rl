#include "display.h"

#include <string.h>

#include "font5x7.h"

/* AE display off; D5 80 clock divide; A8 3F 64 rows; D3 00 no offset; 40 start line 0;
 * 8D 14 charge pump on, since the module has no external panel supply; 20 00
 * horizontal addressing; A1 and C8 flip the segments and rows so text reads upright
 * with the header on the connector side; DA 12 alternate row wiring for 64-row panels;
 * 81 CF contrast; D9 F1 precharge for the charge pump; DB 40 VCOMH; A4 show RAM; A6 not
 * inverted; 2E scrolling off; AF display on. */
static const uint8_t init_packet[] = {
    DISPLAY_COMMAND_PREFIX,
    0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
    0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6,
    0x2E, 0xAF,
};

/* 21 columns 0 to 127, 22 pages 0 to 7. */
static const uint8_t window_packet[] = {
    DISPLAY_COMMAND_PREFIX, 0x21, 0x00, 0x7F, 0x22, 0x00, 0x07,
};

void display_clear(display_t *d)
{
    d->buf[0] = DISPLAY_DATA_PREFIX;
    memset(d->buf + 1, 0, DISPLAY_BYTES);
}

void display_pixel(display_t *d, int x, int y, int on)
{
    if (x < 0 || y < 0 || x >= DISPLAY_WIDTH || y >= DISPLAY_HEIGHT) {
        return;
    }
    uint8_t *byte = &d->buf[1 + (y / 8) * DISPLAY_WIDTH + x];
    const uint8_t bit = (uint8_t)(1u << (y % 8));
    if (on) {
        *byte |= bit;
    } else {
        *byte &= (uint8_t)~bit;
    }
}

void display_fill(display_t *d, int x, int y, int w, int h, int on)
{
    for (int row = y; row < y + h; ++row) {
        for (int col = x; col < x + w; ++col) {
            display_pixel(d, col, row, on);
        }
    }
}

static void draw_glyph(display_t *d, int x, int y, char c, int scale)
{
    unsigned index = (unsigned char)c;
    if (index < FONT5X7_FIRST || index > FONT5X7_LAST) {
        index = '?';
    }
    const uint8_t *rows = font5x7_rows[index - FONT5X7_FIRST];
    /* The eighth row is the descenders' (font5x7.h). It falls in the line gap, and off
     * the panel on the bottom line, where display_pixel drops it. */
    for (int row = 0; row < FONT5X7_ROWS; ++row) {
        for (int col = 0; col < DISPLAY_GLYPH_WIDTH; ++col) {
            if (rows[row] & (0x10u >> col)) {
                display_fill(d, x + col * scale, y + row * scale, scale, scale, 1);
            }
        }
    }
}

int display_text(display_t *d, int x, int y, const char *s, int scale)
{
    int clipped = 0;
    if (scale < 1) {
        scale = 1;
    }
    for (; *s != '\0'; ++s) {
        const int fits = x >= 0 && y >= 0
            && x + DISPLAY_GLYPH_WIDTH * scale <= DISPLAY_WIDTH
            && y + DISPLAY_GLYPH_HEIGHT * scale <= DISPLAY_HEIGHT;
        if (fits) {
            draw_glyph(d, x, y, *s, scale);
        } else {
            ++clipped;
        }
        x += DISPLAY_ADVANCE * scale;
    }
    return clipped;
}

int display_text_width(const char *s, int scale)
{
    const int n = (int)strlen(s);
    if (n == 0) {
        return 0;
    }
    return (n * DISPLAY_ADVANCE - 1) * scale;
}

int display_text_center(display_t *d, int y, const char *s, int scale)
{
    return display_text(d, (DISPLAY_WIDTH - display_text_width(s, scale)) / 2, y, s, scale);
}

int display_text_right(display_t *d, int y, const char *s, int scale)
{
    return display_text(d, DISPLAY_WIDTH - display_text_width(s, scale), y, s, scale);
}

void display_invert(display_t *d, int x, int y, int w, int h)
{
    for (int row = y; row < y + h; ++row) {
        if (row < 0 || row >= DISPLAY_HEIGHT) {
            continue;
        }
        for (int col = x; col < x + w; ++col) {
            if (col < 0 || col >= DISPLAY_WIDTH) {
                continue;
            }
            d->buf[1 + (row / 8) * DISPLAY_WIDTH + col] ^= (uint8_t)(1u << (row % 8));
        }
    }
}

void display_bar(display_t *d, int y, uint16_t permille)
{
    if (permille > 1000u) {
        permille = 1000u;
    }
    display_fill(d, 0, y, DISPLAY_WIDTH, 1, 1);
    display_fill(d, 0, y + 3, DISPLAY_WIDTH, 1, 1);
    display_fill(d, 0, y, 1, 4, 1);
    display_fill(d, DISPLAY_WIDTH - 1, y, 1, 4, 1);
    display_fill(d, 1, y + 1, (DISPLAY_WIDTH - 2) * permille / 1000, 2, 1);
}

void display_dots(display_t *d, int x, int y, int count, int current)
{
    static const uint8_t ring[5] = {0x0E, 0x11, 0x11, 0x11, 0x0E};
    static const uint8_t disc[5] = {0x0E, 0x1F, 0x1F, 0x1F, 0x0E};
    for (int k = 0; k < count; ++k) {
        const uint8_t *rows = (k == current) ? disc : ring;
        for (int r = 0; r < 5; ++r) {
            for (int c = 0; c < 5; ++c) {
                if (rows[r] & (0x10u >> c)) {
                    display_pixel(d, x + k * 8 + c, y + r, 1);
                }
            }
        }
    }
}

const uint8_t *display_init_packet(size_t *len)
{
    *len = sizeof init_packet;
    return init_packet;
}

int display_flush(const display_t *d, display_write_fn write, void *ctx)
{
    if (write(ctx, window_packet, sizeof window_packet) != 0) {
        return -1;
    }
    if (write(ctx, d->buf, sizeof d->buf) != 0) {
        return -1;
    }
    return 0;
}

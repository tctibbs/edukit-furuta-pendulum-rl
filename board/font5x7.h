/* A 5x7 bitmap font for printable ASCII, drawn for this project.
 *
 * One glyph is eight row bytes, top row first. Capitals, digits and most lowercase sit on
 * rows 0 to 6 with the baseline on row 6; row 7 carries only the descenders of g, j, p,
 * q, y and the comma and semicolon, so a 7-row cell can still read `swing` rather than
 * `swin9`. Within a row the five low bits are the columns, 0x10 the leftmost. Row bytes
 * rather than the more common column bytes because a glyph can then be read and checked
 * by eye against its hex: 0x0E is ".###.".
 *
 * 0x7F, DEL in ASCII, is a degree sign here.
 */
#ifndef FONT5X7_H
#define FONT5X7_H

#include <stdint.h>

#define FONT5X7_FIRST 0x20
#define FONT5X7_LAST 0x7F
#define FONT5X7_GLYPHS (FONT5X7_LAST - FONT5X7_FIRST + 1)
#define FONT5X7_ROWS 8
#define FONT5X7_DEGREE "\x7f"

extern const uint8_t font5x7_rows[FONT5X7_GLYPHS][FONT5X7_ROWS];

#endif /* FONT5X7_H */

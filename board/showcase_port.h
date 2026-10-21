/* The showcase's board glue: the Nucleo's blue button, the SSD1306 on I2C1 and the
 * buzzer, for the NUCLEO-F401RE under the IHM01A1 shield. It claims TIM5, the buzzer's
 * carrier on PA0, and TIM11 with its interrupt, modulating the audible notes; no other
 * mode or driver may use either.
 *
 * The button and the buzzer run from SysTick, at the lowest interrupt priority, with
 * register writes only; nothing here blocks or touches I2C from an interrupt. Presses
 * reach the main loop as counters only SysTick writes, so none is lost. A sound request
 * goes the other way as an id and a sequence number only the main loop writes, and the
 * latest request wins: one made before SysTick has taken the one before replaces it, and
 * starts twice when a tick falls between its two writes.
 *
 * Wiring: OLED SCL on PB8 (D15), SDA on PB9 (D14), both powered from 3.3 V; buzzer
 * signal on PA0 (A0), powered from 3.3 V. Both are optional.
 */
#ifndef SHOWCASE_PORT_H
#define SHOWCASE_PORT_H

#include <stdint.h>

#include "display.h"
#include "showcase.h"

#define SHOWCASE_OLED_ADDR7 0x3C
#define SHOWCASE_I2C_HZ 400000u
#define SHOWCASE_I2C_TIMEOUT_MS 50u
#define SHOWCASE_I2C_MAX_ERRORS 3u

/* Configures the button, the I2C bus and panel, and the tone timer, then starts the
 * SysTick side. Returns 1 when the panel answered at SHOWCASE_OLED_ADDR7. */
int showcase_port_init(void);

/* 1 while the panel is present and has not failed SHOWCASE_I2C_MAX_ERRORS writes. */
int showcase_port_display_ok(void);

/* Sends a frame: a blocking transfer of about 1034 bytes, about 23 ms at SHOWCASE_I2C_HZ,
 * so only between attempts. Returns 0 on success, -1 when the panel is absent or the
 * write failed. */
int showcase_port_flush(const display_t *d);

/* Asks SysTick to start a tune. Two byte writes; safe inside the control loop. The latest
 * request wins, as above. */
void showcase_port_sound(sound_t sound);

/* Loudness, 1 to 50 percent: the duty of the 25 kHz carrier that TIM11 switches at the
 * note frequency. */
void showcase_port_set_volume(uint8_t percent);

/* Asks SysTick to beep a mode's number, with a low tone after it for a history entry.
 * For the main loop to call when an entry arms and no display answered. A sound request,
 * so the latest wins. */
void showcase_port_announce(uint8_t number, int history);

/* With no display present, probes for one at most every SHOWCASE_REPROBE_MS, freeing a
 * bus held low first, and sets it up again if it answers. Returns 1 when a display has
 * just come back, so the caller redraws. Only for the selector, with the motor stopped:
 * a probe of an empty bus takes a few milliseconds and a stuck one up to the timeout. */
int showcase_port_poll_display(uint32_t now_ms);

#define SHOWCASE_REPROBE_MS 2000u
#define SHOWCASE_PROBE_TIMEOUT_MS 10u

/* A press arrived since the last `showcase_port_take_input`. Does not consume it. */
int showcase_port_event_pending(void);

/* Consumes the presses so far: HOLD if any was long, else TAP if any was short. */
showcase_input_t showcase_port_take_input(void);

#endif /* SHOWCASE_PORT_H */

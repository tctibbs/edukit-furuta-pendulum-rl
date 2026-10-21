#include "showcase_port.h"

#include "stm32f4xx_hal.h"

/* The HAL's tick, defined in stm32f4xx_hal.c without a header declaration. */
extern __IO uint32_t uwTick;
extern HAL_TickFreqTypeDef uwTickFreq;

static I2C_HandleTypeDef showcase_i2c;
static int display_ok;
static uint32_t i2c_errors;
static uint32_t next_probe_ms;

static button_t button;
static buzzer_t buzzer;
static volatile uint8_t port_active;

/* SysTick writes these, the main loop reads them. Counters, so no press is lost. */
static volatile uint16_t short_count;
static volatile uint16_t long_count;
static uint16_t short_seen;
static uint16_t long_seen;

/* The main loop writes these, SysTick reads them. A request is a sound_t, or with the
 * top bit set a number to beep, bit 6 marking a history entry. The main loop writes the
 * id and then bumps the sequence number, and SysTick plays whatever id it finds when the
 * number has moved: the latest request wins. One made before SysTick has taken the one
 * before replaces it, and when a tick falls between its two writes SysTick plays it on
 * that tick and again, from the start, on the next. */
static volatile uint8_t sound_id;
static volatile uint8_t sound_seq;
static uint8_t sound_seen;

#define REQUEST_COUNT 0x80u
#define REQUEST_HISTORY 0x40u
#define REQUEST_NUMBER_MASK 0x3Fu

/* ---- Tone ------------------------------------------------------------------------ */

/* TIM5 runs a 25 kHz PWM carrier on PA0, far above anything the transducer can follow,
 * and TIM11 gates it on and off at the note's frequency. The transducer responds to the
 * carrier's average, so the carrier's duty is the volume. The gate interrupt runs at
 * twice the note frequency, at most 6 kHz, and only while a note sounds.
 *
 * The obvious drive, TIM5 making the note itself as a square wave, has no volume: the
 * module on the bench was equally loud at 3, 8 and 20 percent duty that way (2026-09-13).
 *
 * Silence is PA0 in analog mode, high impedance: silent whether the module's driver
 * turns on with a high or a low input, and nothing at all with no buzzer plugged in. */

#define PA0_MODER_MASK (3u << (0 * 2))
#define PA0_MODER_ANALOG (3u << (0 * 2))
#define PA0_MODER_AF (2u << (0 * 2))
#define CARRIER_HZ 25000u
#define GATE_TIMER_HZ 1000000u
#define GATE_IRQ_PRIORITY 14u /* above SysTick's 15, below the step clock's 4 */

static volatile uint8_t volume_percent = 3; /* carrier duty, 1 to 50; the bench pick, 2026-09-13 */
static uint32_t carrier_arr;
static volatile uint32_t carrier_ccr;
static volatile uint8_t gate_on;
static uint16_t tone_now_hz; /* SysTick only */

void TIM1_TRG_COM_TIM11_IRQHandler(void)
{
    if (TIM11->SR & TIM_SR_UIF) {
        TIM11->SR = (uint32_t)~TIM_SR_UIF;
        gate_on ^= 1u;
        TIM5->CCR1 = gate_on ? carrier_ccr : 0u;
    }
}

static void tone_silence(void)
{
    TIM11->CR1 &= ~TIM_CR1_CEN;
    GPIOA->MODER |= PA0_MODER_ANALOG;
    TIM5->CCR1 = 0;
    tone_now_hz = 0;
}

/* `level` scales the volume, so a tune can fade. */
static void tone_set(uint16_t hz, uint8_t level)
{
    if (hz == 0) {
        tone_silence();
        return;
    }
    uint32_t ccr = (carrier_arr + 1u) * volume_percent * level / 10000u;
    carrier_ccr = ccr ? ccr : 1u;
    TIM11->ARR = GATE_TIMER_HZ / (2u * hz) - 1u;
    if (tone_now_hz == 0u) {
        TIM11->CNT = 0;
        TIM11->EGR = TIM_EGR_UG;
        TIM11->SR = 0;
        gate_on = 1;
        TIM5->CCR1 = carrier_ccr;
        GPIOA->MODER = (GPIOA->MODER & ~PA0_MODER_MASK) | PA0_MODER_AF;
        TIM11->CR1 |= TIM_CR1_CEN;
    }
    tone_now_hz = hz;
}

static void tone_init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_TIM5_CLK_ENABLE();
    __HAL_RCC_TIM11_CLK_ENABLE();

    GPIO_InitTypeDef pin = {0};
    pin.Pin = GPIO_PIN_0;
    pin.Mode = GPIO_MODE_ANALOG;
    pin.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &pin);
    /* The alternate function is chosen now, so switching MODER to AF selects TIM5. */
    GPIOA->AFR[0] = (GPIOA->AFR[0] & ~0xFu) | GPIO_AF2_TIM5;

    /* Timers run at twice their bus clock whenever the bus is divided. */
    uint32_t apb1_timer_hz = HAL_RCC_GetPCLK1Freq();
    if ((RCC->CFGR & RCC_CFGR_PPRE1) != RCC_CFGR_PPRE1_DIV1) {
        apb1_timer_hz *= 2u;
    }
    uint32_t apb2_timer_hz = HAL_RCC_GetPCLK2Freq();
    if ((RCC->CFGR & RCC_CFGR_PPRE2) != RCC_CFGR_PPRE2_DIV1) {
        apb2_timer_hz *= 2u;
    }

    /* The carrier: PWM mode 1 on channel 1, counting at the timer clock, silent until a
     * note sets its compare value. */
    TIM5->CR1 = 0;
    TIM5->CCMR1 = (TIM5->CCMR1 & ~(TIM_CCMR1_OC1M | TIM_CCMR1_CC1S))
        | TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2 | TIM_CCMR1_OC1PE;
    TIM5->CCER |= TIM_CCER_CC1E;
    TIM5->CR1 |= TIM_CR1_ARPE;
    TIM5->CCR1 = 0;
    TIM5->PSC = 0;
    carrier_arr = apb1_timer_hz / CARRIER_HZ - 1u;
    TIM5->ARR = carrier_arr;
    TIM5->EGR = TIM_EGR_UG;
    TIM5->CR1 |= TIM_CR1_CEN;

    /* The gate: counts at 1 MHz, interrupts on overflow only (URS), so the update event
     * a note start forces does not toggle it. */
    TIM11->CR1 = TIM_CR1_ARPE | TIM_CR1_URS;
    TIM11->PSC = apb2_timer_hz / GATE_TIMER_HZ - 1u;
    TIM11->ARR = 999u;
    TIM11->EGR = TIM_EGR_UG;
    TIM11->SR = 0;
    TIM11->DIER = TIM_DIER_UIE;
    HAL_NVIC_SetPriority(TIM1_TRG_COM_TIM11_IRQn, GATE_IRQ_PRIORITY, 0);
    HAL_NVIC_EnableIRQ(TIM1_TRG_COM_TIM11_IRQn);
}

void showcase_port_set_volume(uint8_t percent)
{
    volume_percent = (percent > 50u) ? 50u : ((percent < 1u) ? 1u : percent);
}

/* ---- Button ---------------------------------------------------------------------- */

static void button_pin_init(void)
{
    __HAL_RCC_GPIOC_CLK_ENABLE();
    GPIO_InitTypeDef pin = {0};
    pin.Pin = GPIO_PIN_13;
    pin.Mode = GPIO_MODE_INPUT;
    pin.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(GPIOC, &pin);
    /* Line 13 shares EXTI15_10 with the L6474's fault pin, and that handler clears only
     * line 10. Masked, the button can never enter it. */
    EXTI->IMR &= ~EXTI_IMR_MR13;
    EXTI->PR = EXTI_PR_PR13;
    button_init(&button);
}

/* ---- SysTick --------------------------------------------------------------------- */

static void port_tick_1ms(void)
{
    const int pressed = (GPIOC->IDR & GPIO_PIN_13) == 0u; /* active low */
    /* No click of its own: what a press does, a mode change or a pause, has its sound. */
    const button_event_t event = button_sample_1ms(&button, pressed);
    if (event == BUTTON_SHORT) {
        short_count++;
    } else if (event == BUTTON_LONG) {
        long_count++;
    }
    if (sound_seq != sound_seen) {
        sound_seen = sound_seq;
        const uint8_t request = sound_id;
        if (request & REQUEST_COUNT) {
            buzzer_play_count(&buzzer, (uint8_t)(request & REQUEST_NUMBER_MASK),
                              (request & REQUEST_HISTORY) != 0u);
        } else {
            buzzer_play(&buzzer, (sound_t)request);
        }
    }
    uint16_t hz = 0;
    uint8_t level = 0;
    if (buzzer_tick_1ms(&buzzer, &hz, &level)) {
        tone_set(hz, level);
    }
}

/* The HAL's weak tick, replaced so the showcase needs no edit to stm32f4xx_it.c. The
 * first line matches HAL_IncTick's weak body in stm32f4xx_hal.c (HAL V1.7.4).
 *
 * This strong definition shadows the weak one with no warning and no build error, so a
 * HAL update that changes the weak body is silently ignored in the mode x image: after
 * any HAL update, compare the first line here with HAL_IncTick in stm32f4xx_hal.c. */
void HAL_IncTick(void)
{
    uwTick += uwTickFreq;
    if (port_active) {
        port_tick_1ms();
    }
}

/* ---- I2C and the panel ----------------------------------------------------------- */

void HAL_I2C_MspInit(I2C_HandleTypeDef *h)
{
    if (h->Instance != I2C1) {
        return;
    }
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_I2C1_CLK_ENABLE();
    GPIO_InitTypeDef pins = {0};
    pins.Pin = GPIO_PIN_8 | GPIO_PIN_9;
    pins.Mode = GPIO_MODE_AF_OD;
    pins.Pull = GPIO_PULLUP;
    pins.Speed = GPIO_SPEED_FREQ_HIGH;
    pins.Alternate = GPIO_AF4_I2C1;
    HAL_GPIO_Init(GPIOB, &pins);
}

/* A panel reset mid-transfer, or a module wired but unpowered, can hold SDA low, and the
 * peripheral then never gets the bus. Nine clocks let any byte in progress finish and
 * release it; if the line is still low after that, the probe below fails and the
 * showcase carries on without a display. */
static void i2c_bus_recover(void)
{
    __HAL_RCC_GPIOB_CLK_ENABLE();
    GPIO_InitTypeDef pin = {0};
    pin.Pin = GPIO_PIN_9;
    pin.Mode = GPIO_MODE_INPUT;
    pin.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(GPIOB, &pin);
    pin.Pin = GPIO_PIN_8;
    pin.Mode = GPIO_MODE_OUTPUT_OD;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &pin);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);
    HAL_Delay(1);
    for (int k = 0; k < 9 && HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_9) == GPIO_PIN_RESET; ++k) {
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_RESET);
        HAL_Delay(1);
        HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, GPIO_PIN_SET);
        HAL_Delay(1);
    }
}

static int i2c_write(void *ctx, const uint8_t *bytes, size_t len)
{
    (void)ctx;
    if (HAL_I2C_Master_Transmit(&showcase_i2c, (uint16_t)(SHOWCASE_OLED_ADDR7 << 1),
                                (uint8_t *)bytes, (uint16_t)len,
                                SHOWCASE_I2C_TIMEOUT_MS) != HAL_OK) {
        if (++i2c_errors >= SHOWCASE_I2C_MAX_ERRORS) {
            display_ok = 0;
        }
        return -1;
    }
    return 0;
}

/* Sends the panel's init packet. Its one caller is bring-up, once the panel answers its
 * address: at boot, and when the selector's re-probe finds a panel that was absent. A
 * panel is counted absent only after SHOWCASE_I2C_MAX_ERRORS failed writes since its
 * bring-up, so one that browns out or is replugged and then acknowledges its writes is
 * never set up again. */
static int display_init(void)
{
    size_t len = 0;
    const uint8_t *packet = display_init_packet(&len);
    return i2c_write(NULL, packet, len);
}

/* Frees the bus, starts the peripheral from reset, and probes for the panel. The HAL
 * only calls HAL_I2C_MspInit from its reset state, so a second attempt de-initializes
 * first, or the pins would stay in the plain GPIO modes the bus recovery left them in. */
static int display_bring_up(uint32_t probe_timeout_ms, uint32_t trials)
{
    if (showcase_i2c.State != HAL_I2C_STATE_RESET) {
        HAL_I2C_DeInit(&showcase_i2c);
    }
    i2c_bus_recover();
    showcase_i2c.Instance = I2C1;
    showcase_i2c.Init.ClockSpeed = SHOWCASE_I2C_HZ;
    showcase_i2c.Init.DutyCycle = I2C_DUTYCYCLE_2;
    showcase_i2c.Init.OwnAddress1 = 0;
    showcase_i2c.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
    showcase_i2c.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
    showcase_i2c.Init.OwnAddress2 = 0;
    showcase_i2c.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
    showcase_i2c.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
    if (HAL_I2C_Init(&showcase_i2c) != HAL_OK) {
        return 0;
    }
    if (HAL_I2C_IsDeviceReady(&showcase_i2c, (uint16_t)(SHOWCASE_OLED_ADDR7 << 1), trials,
                              probe_timeout_ms) != HAL_OK) {
        return 0;
    }
    i2c_errors = 0;
    display_ok = 1;
    if (display_init() != 0) {
        display_ok = 0;
    }
    return display_ok;
}

/* ---- Public ---------------------------------------------------------------------- */

int showcase_port_init(void)
{
    button_pin_init();
    tone_init();
    buzzer_init(&buzzer);
    display_bring_up(SHOWCASE_I2C_TIMEOUT_MS, 3);
    next_probe_ms = HAL_GetTick() + SHOWCASE_REPROBE_MS;
    port_active = 1;
    return display_ok;
}

int showcase_port_display_ok(void)
{
    return display_ok;
}

int showcase_port_poll_display(uint32_t now_ms)
{
    if (display_ok || (int32_t)(now_ms - next_probe_ms) < 0) {
        return 0;
    }
    next_probe_ms = now_ms + SHOWCASE_REPROBE_MS;
    return display_bring_up(SHOWCASE_PROBE_TIMEOUT_MS, 1);
}

int showcase_port_flush(const display_t *d)
{
    if (!display_ok) {
        return -1;
    }
    return display_flush(d, i2c_write, NULL);
}

void showcase_port_sound(sound_t sound)
{
    sound_id = (uint8_t)sound;
    sound_seq++;
}

void showcase_port_announce(uint8_t number, int history)
{
    sound_id = (uint8_t)(REQUEST_COUNT | (history ? REQUEST_HISTORY : 0u)
                         | (number & REQUEST_NUMBER_MASK));
    sound_seq++;
}

int showcase_port_event_pending(void)
{
    return short_count != short_seen || long_count != long_seen;
}

showcase_input_t showcase_port_take_input(void)
{
    const uint16_t shorts = short_count;
    const uint16_t longs = long_count;
    showcase_input_t input = SHOWCASE_INPUT_NONE;
    if (longs != long_seen) {
        input = SHOWCASE_INPUT_HOLD;
    } else if (shorts != short_seen) {
        input = SHOWCASE_INPUT_TAP;
    }
    short_seen = shorts;
    long_seen = longs;
    return input;
}

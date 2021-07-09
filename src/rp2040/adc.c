// ADC functions on rp2040
//
// Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "board/misc.h" // timer_from_us
#include "command.h" // shutdown
#include "gpio.h" // gpio_adc_setup
#include "hardware/structs/adc.h" // adc_hw
#include "hardware/structs/padsbank0.h" // padsbank0_hw
#include "hardware/structs/resets.h" // RESETS_RESET_ADC_BITS
#include "internal.h" // enable_pclock
#include "sched.h" // sched_shutdown

DECL_CONSTANT("ADC_MAX", 4095);

#define ADC_TEMPERATURE_PIN 0xfe
DECL_ENUMERATION("pin", "ADC_TEMPERATURE", ADC_TEMPERATURE_PIN);

struct gpio_adc
gpio_adc_setup(uint32_t pin)
{
    if ((pin < 26 || pin > 29) && pin != ADC_TEMPERATURE_PIN)
        shutdown("Not a valid ADC pin");

    // Enable the ADC
    if (!is_enabled_pclock(RESETS_RESET_ADC_BITS)) {
        enable_pclock(RESETS_RESET_ADC_BITS);
        adc_hw->cs = ADC_CS_EN_BITS;
    }

    uint8_t chan;
    if (pin == ADC_TEMPERATURE_PIN) {
        chan = 4;
        adc_hw->cs |= ADC_CS_TS_EN_BITS;
    } else {
        chan = pin - 26;
        padsbank0_hw->io[pin] = PADS_BANK0_GPIO0_OD_BITS;
    }

    return (struct gpio_adc){ .chan = chan };
}

enum { ADC_DUMMY=0xff };
static uint8_t last_analog_read = ADC_DUMMY;

// Try to sample a value. Returns zero if sample ready, otherwise
// returns the number of clock ticks the caller should wait before
// retrying this function.
uint32_t
gpio_adc_sample(struct gpio_adc g)
{
    uint32_t cs = adc_hw->cs;
    if (!(cs & ADC_CS_READY_BITS))
        // ADC is busy
        goto need_delay;
    if (last_analog_read == g.chan)
        // Sample now ready
        return 0;
    if (last_analog_read != ADC_DUMMY)
        // Sample on another channel in progress
        goto need_delay;

    // Begin sample
    last_analog_read = g.chan;
    adc_hw->cs = ((cs & ADC_CS_TS_EN_BITS) | ADC_CS_START_ONCE_BITS
                  | ADC_CS_EN_BITS | (g.chan << ADC_CS_AINSEL_LSB));

need_delay:
    return timer_from_us(5); // Sample takes 2us but provide extra time
}

// Read a value; use only after gpio_adc_sample() returns zero
uint16_t
gpio_adc_read(struct gpio_adc g)
{
    last_analog_read = ADC_DUMMY;
    return adc_hw->result;
}

// Cancel a sample that may have been started with gpio_adc_sample()
void
gpio_adc_cancel_sample(struct gpio_adc g)
{
    if (last_analog_read == g.chan)
        last_analog_read = ADC_DUMMY;
}

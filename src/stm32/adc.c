// ADC functions on STM32
//
// Copyright (C) 2019-2020  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "board/irq.h" // irq_save
#include "board/misc.h" // timer_from_us
#include "command.h" // shutdown
#include "compiler.h" // ARRAY_SIZE
#include "generic/armcm_timer.h" // udelay
#include "gpio.h" // gpio_adc_setup
#include "internal.h" // GPIO
#include "sched.h" // sched_shutdown

DECL_CONSTANT("ADC_MAX", 4095);

#define ADC_TEMPERATURE_PIN 0xfe
DECL_ENUMERATION("pin", "ADC_TEMPERATURE", ADC_TEMPERATURE_PIN);

static const uint8_t adc_pins[] = {
    GPIO('A', 0), GPIO('A', 1), GPIO('A', 2), GPIO('A', 3),
    GPIO('A', 4), GPIO('A', 5), GPIO('A', 6), GPIO('A', 7),
    GPIO('B', 0), GPIO('B', 1), GPIO('C', 0), GPIO('C', 1),
    GPIO('C', 2), GPIO('C', 3), GPIO('C', 4), GPIO('C', 5),

#if CONFIG_MACH_STM32F1
    ADC_TEMPERATURE_PIN,
#elif CONFIG_MACH_STM32F2 || CONFIG_MACH_STM32F405 || CONFIG_MACH_STM32F407
    ADC_TEMPERATURE_PIN, 0x00, 0x00,
#elif CONFIG_MACH_STM32F446
    0x00, 0x00, ADC_TEMPERATURE_PIN,
#endif

#if CONFIG_MACH_STM32F405 || CONFIG_MACH_STM32F407 || CONFIG_MACH_STM32F446
    0x00, 0x00, 0x00, 0x00,
    GPIO('F', 6), GPIO('F', 7), GPIO('F', 8), GPIO('F', 9),
    GPIO('F', 10), GPIO('F', 3), 0x00, 0x00,
    0x00, 0x00, GPIO('F', 4), GPIO('F', 5),
#endif
};

#if CONFIG_MACH_STM32F1
#define CR2_FLAGS (ADC_CR2_ADON | (7 << ADC_CR2_EXTSEL_Pos) | ADC_CR2_EXTTRIG \
                   | ADC_CR2_TSVREFE)
#else
#define CR2_FLAGS ADC_CR2_ADON
#endif

// ADC timing:
// stm32f103: ADC clock=4.5Mhz, Tconv=12.5, Tsamp=41.5, total=12.000us
// stm32f407: ADC clock=21Mhz, Tconv=12, Tsamp=84, total=4.571us
// stm32f446: ADC clock=22.5Mhz, Tconv=12, Tsamp=84, total=4.267us

// Perform calibration on stm32f103
static void
adc_calibrate(ADC_TypeDef *adc)
{
#if CONFIG_MACH_STM32F1
    adc->CR2 = ADC_CR2_ADON;
    udelay(10);
    adc->CR2 = ADC_CR2_ADON | ADC_CR2_RSTCAL;
    while (adc->CR2 & ADC_CR2_RSTCAL)
        ;
    adc->CR2 = ADC_CR2_ADON | ADC_CR2_CAL;
    while (adc->CR2 & ADC_CR2_CAL)
        ;
#endif
}

struct gpio_adc
gpio_adc_setup(uint32_t pin)
{
    // Find pin in adc_pins table
    int chan;
    for (chan=0; ; chan++) {
        if (chan >= ARRAY_SIZE(adc_pins))
            shutdown("Not a valid ADC pin");
        if (adc_pins[chan] == pin)
            break;
    }

    // Determine which ADC block to use
    ADC_TypeDef *adc = ADC1;
    uint32_t adc_base = ADC1_BASE;
#if CONFIG_MACH_STM32F405 || CONFIG_MACH_STM32F407 || CONFIG_MACH_STM32F446
    if (chan >= 19) {
        // On the STM32F4, some ADC channels are only available from ADC3
        adc = ADC3;
        adc_base += 0x800;
        chan -= 19;
    }
#endif

    // Enable the ADC
    if (!is_enabled_pclock(adc_base)) {
        enable_pclock(adc_base);

#if CONFIG_MACH_STM32F401
        //ADC max clock frequency is 36MHz
        // CLEAR ADC PRESCALAR
        ADC_Common_TypeDef *adc_common = ADC;
        adc_common -> CCR &= ~(ADC_CCR_ADCPRE) ;
        // SET ADC PRESCALAR TO 4
        adc_common -> CCR |= (uint32_t)(0x1UL << ADC_CCR_ADCPRE_Pos) ;
#endif
        adc_calibrate(adc);
        uint32_t aticks = 4; // 4-12us sample time (depending on stm32 chip)
        adc->SMPR1 = (aticks | (aticks << 3) | (aticks << 6) | (aticks << 9)
                      | (aticks << 12) | (aticks << 15) | (aticks << 18)
                      | (aticks << 21)
                      | (CONFIG_MACH_STM32F4 ? aticks << 24 : 0));
        adc->SMPR2 = (aticks | (aticks << 3) | (aticks << 6) | (aticks << 9)
                      | (aticks << 12) | (aticks << 15) | (aticks << 18)
                      | (aticks << 21) | (aticks << 24) | (aticks << 27));
        adc->CR2 = CR2_FLAGS;
    }

    if (pin == ADC_TEMPERATURE_PIN) {
#if !(CONFIG_MACH_STM32F1 || CONFIG_MACH_STM32F401)
        ADC123_COMMON->CCR = ADC_CCR_TSVREFE;
#endif
    } else {
        gpio_peripheral(pin, GPIO_ANALOG, 0);
    }

    return (struct gpio_adc){ .adc = adc, .chan = chan };
}

// Try to sample a value. Returns zero if sample ready, otherwise
// returns the number of clock ticks the caller should wait before
// retrying this function.
uint32_t
gpio_adc_sample(struct gpio_adc g)
{
    ADC_TypeDef *adc = g.adc;
    uint32_t sr = adc->SR;
    if (sr & ADC_SR_STRT) {
        if (!(sr & ADC_SR_EOC) || adc->SQR3 != g.chan)
            // Conversion still in progress or busy on another channel
            goto need_delay;
        // Conversion ready
        return 0;
    }
    // Start sample
    adc->SQR3 = g.chan;
    adc->CR2 = ADC_CR2_SWSTART | CR2_FLAGS;

need_delay:
    return timer_from_us(20);
}

// Read a value; use only after gpio_adc_sample() returns zero
uint16_t
gpio_adc_read(struct gpio_adc g)
{
    ADC_TypeDef *adc = g.adc;
    adc->SR = ~ADC_SR_STRT;
    return adc->DR;
}

// Cancel a sample that may have been started with gpio_adc_sample()
void
gpio_adc_cancel_sample(struct gpio_adc g)
{
    ADC_TypeDef *adc = g.adc;
    irqstatus_t flag = irq_save();
    if (adc->SR & ADC_SR_STRT && adc->SQR3 == g.chan)
        gpio_adc_read(g);
    irq_restore(flag);
}

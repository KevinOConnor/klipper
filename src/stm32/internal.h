#ifndef __STM32_INTERNAL_H
#define __STM32_INTERNAL_H
// Local definitions for STM32 code

#include "autoconf.h" // CONFIG_MACH_STM32F1

#if CONFIG_MACH_STM32F0
#include "stm32f0xx.h"
#elif CONFIG_MACH_STM32F1
#include "stm32f1xx.h"
#elif CONFIG_MACH_STM32F2
#include "stm32f2xx.h"
#elif CONFIG_MACH_STM32F4
#include "stm32f4xx.h"
#elif CONFIG_MACH_STM32H7
#include "stm32h7xx.h"
#endif

extern GPIO_TypeDef * const digital_regs[];

#define GPIO(PORT, NUM) (((PORT)-'A') * 16 + (NUM))
#define GPIO2PORT(PIN) ((PIN) / 16)
#define GPIO2BIT(PIN) (1<<((PIN) % 16))

#define GPIO_INPUT 0
#define GPIO_OUTPUT 1
#define GPIO_OPEN_DRAIN 0x100
#define GPIO_FUNCTION(fn) (2 | ((fn) << 4))
#define GPIO_ANALOG 3

void enable_pclock(uint32_t periph_base);
int is_enabled_pclock(uint32_t periph_base);
uint32_t get_pclock_frequency(uint32_t periph_base);
void gpio_clock_enable(GPIO_TypeDef *regs);
void gpio_peripheral(uint32_t gpio, uint32_t mode, int pullup);

#endif // internal.h

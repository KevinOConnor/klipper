#ifndef __RP2040_INTERNAL_H
#define __RP2040_INTERNAL_H
// Local definitions for rp2040

#include "RP2040.h"

void enable_pclock(uint32_t reset_bit);
int is_enabled_pclock(uint32_t reset_bit);
uint32_t get_pclock_frequency(uint32_t reset_bit);
void gpio_peripheral(uint32_t gpio, int func, int pull_up);
void reset_to_usb_boot(uint32_t gpio_activity_pin_mask
                       , uint32_t disable_interface_mask);
void connect_internal_flash(void);
void flash_exit_xip(void);
void flash_flush_cache(void);

// Force a function to run from ram
#define UNIQSEC __FILE__ "." __stringify(__LINE__)
#define _ramfunc noinline __section(".ramfunc." UNIQSEC)

#endif // internal.h

// rp2040 timer support
//
// Copyright (C) 2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "board/armcm_boot.h" // armcm_enable_irq
#include "board/irq.h" // irq_disable
#include "board/misc.h" // timer_read_time
#include "board/timer_irq.h" // timer_dispatch_many
#include "command.h" // DECL_SHUTDOWN
#include "hardware/structs/resets.h" // RESETS_RESET_UART0_BITS
#include "hardware/structs/timer.h" // RESETS_RESET_UART0_BITS
#include "internal.h" // enable_pclock
#include "sched.h" // DECL_INIT


/****************************************************************
 * Low level timer code
 ****************************************************************/

// Return the current time (in absolute clock ticks).
uint32_t
timer_read_time(void)
{
    return timer_hw->timerawl;
}

static inline void
timer_set(uint32_t next)
{
    timer_hw->alarm[0] = next;
}

// Activate timer dispatch as soon as possible
void
timer_kick(void)
{
    timer_set(timer_read_time() + 50);
}


/****************************************************************
 * Setup and irqs
 ****************************************************************/

// Hardware timer IRQ handler - dispatch software timers
void __aligned(16)
TIMER0_IRQHandler(void)
{
    irq_disable();
    timer_hw->intr = 1;
    uint32_t next = timer_dispatch_many();
    timer_set(next);
    irq_enable();
}

void
timer_init(void)
{
    irq_disable();
    enable_pclock(RESETS_RESET_TIMER_BITS);
    timer_hw->timelw = 0;
    timer_hw->timehw = 0;
    armcm_enable_irq(TIMER0_IRQHandler, TIMER_IRQ_0_IRQn, 2);
    timer_hw->inte = 1;
    timer_kick();
    irq_enable();
}
DECL_INIT(timer_init);

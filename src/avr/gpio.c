// GPIO functions on AVR.
//
// Copyright (C) 2016-2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "autoconf.h" // CONFIG_MACH_atmega644p
#include "command.h" // shutdown
#include "gpio.h" // gpio_out_write
#include "internal.h" // GPIO2REGS
#include "irq.h" // irq_save
#include "pgm.h" // PROGMEM
#include "sched.h" // sched_shutdown

#include "bed_timer.c"

#ifdef PINA
DECL_ENUMERATION_RANGE("pin", "PA0", GPIO('A', 0), 8);
#endif
DECL_ENUMERATION_RANGE("pin", "PB0", GPIO('B', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PC0", GPIO('C', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PD0", GPIO('D', 0), 8);
#ifdef PINE
DECL_ENUMERATION_RANGE("pin", "PE0", GPIO('E', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PF0", GPIO('F', 0), 8);
#endif
#ifdef PING
DECL_ENUMERATION_RANGE("pin", "PG0", GPIO('G', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PH0", GPIO('H', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PJ0", GPIO('J', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PK0", GPIO('K', 0), 8);
DECL_ENUMERATION_RANGE("pin", "PL0", GPIO('L', 0), 8);
#endif

volatile uint8_t * const digital_regs[] PROGMEM = {
#ifdef PINA
    &PINA,
#else
    NULL,
#endif
    &PINB, &PINC, &PIND,
#ifdef PINE
    &PINE, &PINF,
#endif
#ifdef PING
    &PING, &PINH, NULL, &PINJ, &PINK, &PINL
#endif
};

struct gpio_out
gpio_out_setup(uint8_t pin, uint8_t val)
{
    if (GPIO2PORT(pin) >= ARRAY_SIZE(digital_regs))
        goto fail;
    struct gpio_digital_regs *regs = GPIO2REGS(pin);
    if (! regs)
        goto fail;
    struct gpio_out g = { .regs=regs, .bit=GPIO2BIT(pin) };
    gpio_out_reset(g, val);
    return g;
fail:
    shutdown("Not an output pin");
}

void
gpio_out_reset(struct gpio_out g, uint8_t val)
{
    irqstatus_t flag = irq_save();
    if (g.regs == &PING && g.bit == (1<<PG5)) {
        timer0_stop(val);
    }

    g.regs->out = val ? (g.regs->out | g.bit) : (g.regs->out & ~g.bit);
    g.regs->mode |= g.bit;
    irq_restore(flag);
}

void
gpio_out_toggle_noirq(struct gpio_out g)
{
    g.regs->in = g.bit;
}

void
gpio_out_toggle(struct gpio_out g)
{
    gpio_out_toggle_noirq(g);
}

void
gpio_out_write(struct gpio_out g, uint8_t val)
{
    irqstatus_t flag = irq_save();

    if (g.regs == &PING && g.bit == (1<<PG5)) {
        timer0_restart(val);
    } else {
        g.regs->out = val ? (g.regs->out | g.bit) : (g.regs->out & ~g.bit);
    }

    irq_restore(flag);
}

struct gpio_in
gpio_in_setup(uint8_t pin, int8_t pull_up)
{
    if (GPIO2PORT(pin) >= ARRAY_SIZE(digital_regs) || pull_up < 0)
        goto fail;
    struct gpio_digital_regs *regs = GPIO2REGS(pin);
    if (! regs)
        goto fail;
    struct gpio_in g = { .regs=regs, .bit=GPIO2BIT(pin) };
    gpio_in_reset(g, pull_up);
    return g;
fail:
    shutdown("Not a valid input pin");
}

void
gpio_in_reset(struct gpio_in g, int8_t pull_up)
{
    irqstatus_t flag = irq_save();
    g.regs->out = pull_up > 0 ? (g.regs->out | g.bit) : (g.regs->out & ~g.bit);
    g.regs->mode &= ~g.bit;
    irq_restore(flag);
}

uint8_t
gpio_in_read(struct gpio_in g)
{
    return !!(g.regs->in & g.bit);
}

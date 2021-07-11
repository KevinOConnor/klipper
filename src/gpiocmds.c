// Commands for controlling GPIO output pins
//
// Copyright (C) 2016-2020  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "basecmd.h" // oid_alloc
#include "board/gpio.h" // struct gpio_out
#include "board/irq.h" // irq_disable
#include "board/misc.h" // timer_is_before
#include "command.h" // DECL_COMMAND
#include "sched.h" // sched_add_timer

struct digital_out_s {
    struct timer timer;
    uint32_t on_duration, off_duration, end_time;
    struct gpio_out pin;
    uint32_t max_duration, cycle_time;
    struct move_queue_head mq;
    uint8_t flags;
};

struct digital_move {
    struct move_node node;
    uint32_t waketime, on_duration;
};

enum {
    DF_ON=1<<0, DF_TOGGLING=1<<1, DF_CHECK_END=1<<2, DF_DEFAULT_ON=1<<4
};

static uint_fast8_t digital_load_event(struct timer *timer);

// Software PWM toggle event
static uint_fast8_t
digital_toggle_event(struct timer *timer)
{
    struct digital_out_s *d = container_of(timer, struct digital_out_s, timer);
    gpio_out_toggle_noirq(d->pin);
    d->flags ^= DF_ON;
    uint32_t waketime = d->timer.waketime;
    if (d->flags & DF_ON)
        waketime += d->on_duration;
    else
        waketime += d->off_duration;
    if (d->flags & DF_CHECK_END && !timer_is_before(waketime, d->end_time)) {
        // End of normal pulsing - next event loads new pwm settings
        d->timer.func = digital_load_event;
        waketime = d->end_time;
    }
    d->timer.waketime = waketime;
    return SF_RESCHEDULE;
}

// Load next pin output setting
static uint_fast8_t
digital_load_event(struct timer *timer)
{
    // Apply next update and remove it from queue
    struct digital_out_s *d = container_of(timer, struct digital_out_s, timer);
    if (move_queue_empty(&d->mq))
        shutdown("Missed scheduling of next digital out event");
    struct move_node *mn = move_queue_pop(&d->mq);
    struct digital_move *m = container_of(mn, struct digital_move, node);
    uint32_t on_duration = m->on_duration;
    uint8_t flags = on_duration ? DF_ON : 0;
    gpio_out_write(d->pin, flags);
    move_free(m);

    // Calculate next end_time and flags
    uint32_t end_time = 0;
    if (!flags || on_duration >= d->cycle_time) {
        // Pin is in an always on or always off state
        if (!flags != !(d->flags & DF_DEFAULT_ON) && d->max_duration) {
            end_time = d->timer.waketime + d->max_duration;
            flags |= DF_CHECK_END;
        }
    } else {
        flags |= DF_TOGGLING;
        if (d->max_duration) {
            end_time = d->timer.waketime + d->max_duration;
            flags |= DF_CHECK_END;
        }
    }
    if (!move_queue_empty(&d->mq)) {
        struct move_node *nn = move_queue_first(&d->mq);
        uint32_t wake = container_of(nn, struct digital_move, node)->waketime;
        if (flags & DF_CHECK_END && timer_is_before(end_time, wake))
            shutdown("Scheduled digital out event will exceed max_duration");
        end_time = wake;
        flags |= DF_CHECK_END;
    }
    d->end_time = end_time;
    d->flags = flags | (d->flags & DF_DEFAULT_ON);

    // Schedule next event
    if (!(flags & DF_TOGGLING)) {
        if (!(flags & DF_CHECK_END))
            // Pin not toggling and nothing scheduled
            return SF_DONE;
        d->timer.waketime = end_time;
        return SF_RESCHEDULE;
    }
    uint32_t waketime = d->timer.waketime + on_duration;
    if (flags & DF_CHECK_END && !timer_is_before(waketime, end_time)) {
        d->timer.waketime = end_time;
        return SF_RESCHEDULE;
    }
    d->timer.func = digital_toggle_event;
    d->timer.waketime = waketime;
    d->on_duration = on_duration;
    d->off_duration = d->cycle_time - on_duration;
    return SF_RESCHEDULE;
}

void
command_config_digital_out(uint32_t *args)
{
    struct gpio_out pin = gpio_out_setup(args[1], !!args[2]);
    struct digital_out_s *d = oid_alloc(args[0], command_config_digital_out
                                        , sizeof(*d));
    d->pin = pin;
    d->flags = (args[2] ? DF_ON : 0) | (args[3] ? DF_DEFAULT_ON : 0);
    d->max_duration = args[4];
    move_queue_setup(&d->mq, sizeof(struct digital_move));
}
DECL_COMMAND(command_config_digital_out,
             "config_digital_out oid=%c pin=%u value=%c"
             " default_value=%c max_duration=%u");

void
command_set_digital_out_pwm_cycle(uint32_t *args)
{
    struct digital_out_s *d = oid_lookup(args[0], command_config_digital_out);
    irq_disable();
    if (!move_queue_empty(&d->mq))
        shutdown("Can not set soft pwm cycle ticks while updates pending");
    d->cycle_time = args[1];
    irq_enable();
}
DECL_COMMAND(command_set_digital_out_pwm_cycle,
             "set_digital_out_pwm_cycle oid=%c cycle_ticks=%u");

void
command_queue_digital_out(uint32_t *args)
{
    struct digital_out_s *d = oid_lookup(args[0], command_config_digital_out);
    struct digital_move *m = move_alloc();
    uint32_t time = m->waketime = args[1];
    m->on_duration = args[2];

    irq_disable();
    int first_on_queue = move_queue_push(&m->node, &d->mq);
    if (!first_on_queue) {
        irq_enable();
        return;
    }
    uint8_t flags = d->flags;
    if (flags & DF_CHECK_END && timer_is_before(d->end_time, time))
        shutdown("Scheduled digital out event will exceed max_duration");
    d->end_time = time;
    d->flags = flags | DF_CHECK_END;
    if (flags & DF_TOGGLING && timer_is_before(d->timer.waketime, time)) {
        // digital_toggle_event() will schedule a load event when ready
    } else {
        // Schedule the loading of the parameters at the requested time
        sched_del_timer(&d->timer);
        d->timer.waketime = time;
        d->timer.func = digital_load_event;
        sched_add_timer(&d->timer);
    }
    irq_enable();
}
DECL_COMMAND(command_queue_digital_out,
             "queue_digital_out oid=%c clock=%u on_ticks=%u");

void
command_update_digital_out(uint32_t *args)
{
    struct digital_out_s *d = oid_lookup(args[0], command_config_digital_out);
    sched_del_timer(&d->timer);
    if (!move_queue_empty(&d->mq))
        shutdown("update_digital_out not valid with active queue");
    uint8_t value = args[1], flags = d->flags, on_flag = value ? DF_ON : 0;
    gpio_out_write(d->pin, on_flag);
    if (!on_flag != !(flags & DF_DEFAULT_ON) && d->max_duration) {
        d->timer.waketime = d->end_time = timer_read_time() + d->max_duration;
        d->timer.func = digital_load_event;
        d->flags = (flags & DF_DEFAULT_ON) | on_flag | DF_CHECK_END;
        sched_add_timer(&d->timer);
    } else {
        d->flags = (flags & DF_DEFAULT_ON) | on_flag;
    }
}
DECL_COMMAND(command_update_digital_out, "update_digital_out oid=%c value=%c");

void
digital_out_shutdown(void)
{
    uint8_t i;
    struct digital_out_s *d;
    foreach_oid(i, d, command_config_digital_out) {
        gpio_out_write(d->pin, d->flags & DF_DEFAULT_ON);
        d->flags = d->flags & DF_DEFAULT_ON ? DF_ON | DF_DEFAULT_ON : 0;
        move_queue_clear(&d->mq);
    }
}
DECL_SHUTDOWN(digital_out_shutdown);

void
command_set_digital_out(uint32_t *args)
{
    gpio_out_setup(args[0], args[1]);
}
DECL_COMMAND(command_set_digital_out, "set_digital_out pin=%u value=%c");

void
command_read_digital_in(uint32_t *args)
{
    struct gpio_in n = gpio_in_setup(args[0], args[1]);
    uint8_t val = gpio_in_read(n);
    sendf("read_digital_in_value pin=%u value=%c", args[0], val);
}
DECL_COMMAND(command_read_digital_in, "read_digital_in pin=%u pull_up=%c");

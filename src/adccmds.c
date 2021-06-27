// Commands for controlling GPIO analog-to-digital input pins
//
// Copyright (C) 2016  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "basecmd.h" // oid_alloc
#include "board/gpio.h" // struct gpio_adc
#include "board/irq.h" // irq_disable
#include "command.h" // DECL_COMMAND
#include "sched.h" // DECL_TASK

struct analog_in {
    struct timer timer;
    uint32_t rest_time, sample_time, next_begin_time;
    uint32_t value, min_value, max_value;
    struct gpio_adc pin;
    uint8_t invalid_count, range_check_count;
    uint8_t state, sample_count;
};

static struct task_wake analog_wake;

static uint_fast8_t
analog_in_event(struct timer *timer)
{
    struct analog_in *a = container_of(timer, struct analog_in, timer);
    uint32_t sample_delay = gpio_adc_sample(a->pin);
    if (sample_delay) {
        a->timer.waketime += sample_delay;
        return SF_RESCHEDULE;
    }
    uint32_t value = gpio_adc_read(a->pin);
    uint8_t state = a->state;
    if (state >= a->sample_count) {
        state = 0;
    } else {
        value += a->value;
    }
    a->value = value;
    a->state = state+1;
    if (a->state < a->sample_count) {
        a->timer.waketime += a->sample_time;
        return SF_RESCHEDULE;
    }
    if (likely(a->value >= a->min_value && a->value <= a->max_value)) {
        a->invalid_count = 0;
    } else {
        a->invalid_count++;
        if (a->invalid_count >= a->range_check_count) {
            try_shutdown("ADC out of range");
            a->invalid_count = 0;
        }
    }
    sched_wake_task(&analog_wake);
    a->next_begin_time += a->rest_time;
    a->timer.waketime = a->next_begin_time;
    return SF_RESCHEDULE;
}

void
command_config_analog_in(uint32_t *args)
{
    struct gpio_adc pin = gpio_adc_setup(args[1]);
    struct analog_in *a = oid_alloc(
        args[0], command_config_analog_in, sizeof(*a));
    a->timer.func = analog_in_event;
    a->pin = pin;
    a->state = 1;
}
DECL_COMMAND(command_config_analog_in, "config_analog_in oid=%c pin=%u");

void
command_query_analog_in(uint32_t *args)
{
    struct analog_in *a = oid_lookup(args[0], command_config_analog_in);
    sched_del_timer(&a->timer);
    gpio_adc_cancel_sample(a->pin);
    a->next_begin_time = args[1];
    a->timer.waketime = a->next_begin_time;
    a->sample_time = args[2];
    a->sample_count = args[3];
    a->state = a->sample_count + 1;
    a->rest_time = args[4];
    a->min_value = args[5];
    a->max_value = args[6];
    a->range_check_count = args[7];
    if (! a->sample_count)
        return;
    sched_add_timer(&a->timer);
}
DECL_COMMAND(command_query_analog_in,
             "query_analog_in oid=%c clock=%u sample_ticks=%u sample_count=%c"
             " rest_ticks=%u min_value=%u max_value=%u range_check_count=%c");

void
analog_in_task(void)
{
    if (!sched_check_wake(&analog_wake))
        return;
    uint8_t oid;
    struct analog_in *a;
    foreach_oid(oid, a, command_config_analog_in) {
        if (a->state != a->sample_count)
            continue;
        irq_disable();
        if (a->state != a->sample_count) {
            irq_enable();
            continue;
        }
        uint32_t value = a->value;
        uint32_t next_begin_time = a->next_begin_time;
        a->state++;
        irq_enable();
        sendf("analog_in_state oid=%c next_clock=%u value=%u"
              , oid, next_begin_time, value);
    }
}
DECL_TASK(analog_in_task);

void
analog_in_shutdown(void)
{
    uint8_t i;
    struct analog_in *a;
    foreach_oid(i, a, command_config_analog_in) {
        gpio_adc_cancel_sample(a->pin);
        if (a->sample_count) {
            a->state = a->sample_count + 1;
            a->next_begin_time += a->rest_time;
            a->timer.waketime = a->next_begin_time;
            sched_add_timer(&a->timer);
        }
    }
}
DECL_SHUTDOWN(analog_in_shutdown);

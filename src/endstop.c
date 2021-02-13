// Handling of end stops.
//
// Copyright (C) 2016-2019  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "basecmd.h" // oid_alloc
#include "board/gpio.h" // struct gpio
#include "board/irq.h" // irq_disable
#include "command.h" // DECL_COMMAND
#include "sched.h" // struct timer
#include "stepper.h" // stepper_stop

struct endstop {
    struct timer time;
    struct gpio_in pin;
    uint32_t rest_time, sample_time, nextwake, triggered_time;
    struct timer report_timer;
    uint32_t report_interval;
    uint8_t flags, stepper_count, sample_count, trigger_count;
    struct stepper *steppers[0];
};

enum { ESF_PIN_HIGH=1<<0, ESF_HOMING=1<<1, ESF_REPORT=1<<2 };

static struct task_wake endstop_wake;

static void
stop_steppers(struct endstop *e)
{
    e->flags = ESF_REPORT;
    uint8_t count = e->stepper_count;
    while (count--)
        if (e->steppers[count])
            stepper_stop(e->steppers[count]);
    sched_wake_task(&endstop_wake);
}

static uint_fast8_t endstop_oversample_event(struct timer *t);

// Timer callback for an end stop
static uint_fast8_t
endstop_event(struct timer *t)
{
    struct endstop *e = container_of(t, struct endstop, time);
    uint8_t val = gpio_in_read(e->pin);
    uint32_t nextwake = e->time.waketime + e->rest_time;
    if ((val ? ~e->flags : e->flags) & ESF_PIN_HIGH) {
        // No match - reschedule for the next attempt
        e->time.waketime = nextwake;
        return SF_RESCHEDULE;
    }
    e->triggered_time = e->time.waketime;
    e->nextwake = nextwake;
    e->time.func = endstop_oversample_event;
    return endstop_oversample_event(t);
}

// Timer callback for an end stop that is sampling extra times
static uint_fast8_t
endstop_oversample_event(struct timer *t)
{
    struct endstop *e = container_of(t, struct endstop, time);
    uint8_t val = gpio_in_read(e->pin);
    if ((val ? ~e->flags : e->flags) & ESF_PIN_HIGH) {
        // No longer matching - reschedule for the next attempt
        e->time.func = endstop_event;
        e->time.waketime = e->nextwake;
        e->trigger_count = e->sample_count;
        return SF_RESCHEDULE;
    }
    uint8_t count = e->trigger_count - 1;
    if (!count) {
        stop_steppers(e);
        return SF_DONE;
    }
    e->trigger_count = count;
    e->time.waketime += e->sample_time;
    return SF_RESCHEDULE;
}

static uint_fast8_t
endstop_report_event(struct timer *t)
{
    struct endstop *e = container_of(t, struct endstop, report_timer);
    if (!(e->flags & ESF_HOMING))
        return SF_DONE;
    if (!(e->flags & ESF_REPORT))
    {
        e->triggered_time = t->waketime;
        e->flags |= ESF_REPORT;
        sched_wake_task(&endstop_wake);
    }
    t->waketime += e->report_interval;
    return SF_RESCHEDULE;
}

void
command_config_endstop(uint32_t *args)
{
    uint8_t stepper_count = args[3];
    struct endstop *e = oid_alloc(
        args[0], command_config_endstop
        , sizeof(*e) + sizeof(e->steppers[0]) * stepper_count);
    e->pin = gpio_in_setup(args[1], args[2]);
    e->stepper_count = stepper_count;
    e->sample_count = 1;
}
DECL_COMMAND(command_config_endstop,
             "config_endstop oid=%c pin=%c pull_up=%c stepper_count=%c");

void
command_endstop_set_stepper(uint32_t *args)
{
    struct endstop *e = oid_lookup(args[0], command_config_endstop);
    uint8_t pos = args[1];
    if (pos >= e->stepper_count)
        shutdown("Set stepper past maximum stepper count");
    e->steppers[pos] = stepper_oid_lookup(args[2]);
}
DECL_COMMAND(command_endstop_set_stepper,
             "endstop_set_stepper oid=%c pos=%c stepper_oid=%c");

// Home an axis
void
command_endstop_home(uint32_t *args)
{
    struct endstop *e = oid_lookup(args[0], command_config_endstop);
    sched_del_timer(&e->time);
    sched_del_timer(&e->report_timer);
    e->time.waketime = args[1];
    e->sample_time = args[2];
    e->sample_count = args[3];
    if (!e->sample_count) {
        // Disable end stop checking
        e->flags = 0;
        return;
    }
    e->rest_time = args[4];
    e->report_interval = args[5];
    if (e->report_interval != 0)
    {
        e->report_timer.func = endstop_report_event;
        e->report_timer.waketime = e->time.waketime;
        sched_add_timer(&e->report_timer);
    }
    e->time.func = endstop_event;
    e->trigger_count = e->sample_count;
    e->triggered_time = args[1];
    e->flags = ESF_HOMING | (args[6] ? ESF_PIN_HIGH : 0);
    sched_add_timer(&e->time);
}
DECL_COMMAND(command_endstop_home,
             "endstop_home oid=%c clock=%u sample_ticks=%u sample_count=%c"
             " rest_ticks=%u report_ticks=%u pin_value=%c");

static void
endstop_report(uint8_t oid, struct endstop *e)
{
    irq_disable();
    uint8_t eflags = e->flags;
    e->flags &= ~ESF_REPORT;
    irq_enable();

    sendf("endstop_state oid=%c homing=%c pin_value=%c triggered_time=%u",
        oid, !!(eflags & ESF_HOMING), gpio_in_read(e->pin), e->triggered_time);
}

void
command_endstop_query_state(uint32_t *args)
{
    uint8_t oid = args[0];
    struct endstop *e = oid_lookup(oid, command_config_endstop);
    endstop_report(oid, e);
}
DECL_COMMAND(command_endstop_query_state, "endstop_query_state oid=%c");

void
endstop_task(void)
{
    if (!sched_check_wake(&endstop_wake))
        return;
    uint8_t oid;
    struct endstop *e;
    foreach_oid(oid, e, command_config_endstop) {
        if (!(e->flags & ESF_REPORT))
            continue;
        endstop_report(oid, e);
    }
}
DECL_TASK(endstop_task);

// remote endstops:

struct stepper_group {
    uint8_t stepper_count;
    struct stepper *steppers[0];
};

void
command_config_stepper_group(uint32_t *args)
{
    uint8_t stepper_count = args[1];
    struct stepper_group *e = oid_alloc(
        args[0], command_config_stepper_group
        , sizeof(*e) + sizeof(e->steppers[0]) * stepper_count);
    e->stepper_count = stepper_count;
}
DECL_COMMAND(command_config_stepper_group,
             "config_stepper_group oid=%c stepper_count=%c");

void
command_stepper_group_set_stepper(uint32_t *args)
{
    struct stepper_group *e = oid_lookup(args[0], command_config_stepper_group);
    uint8_t pos = args[1];
    if (pos >= e->stepper_count)
        shutdown("Set stepper past maximum stepper count");
    e->steppers[pos] = stepper_oid_lookup(args[2]);
}
DECL_COMMAND(command_stepper_group_set_stepper,
             "stepper_group_set_stepper oid=%c pos=%c stepper_oid=%c");

void
command_stepper_group_stop(uint32_t *args)
{
    uint8_t oid = args[0];
    struct stepper_group *e = oid_lookup(oid, command_config_stepper_group);
    irq_disable();
    uint8_t count = e->stepper_count;
    while (count--)
        if (e->steppers[count])
            stepper_stop(e->steppers[count]);
    irq_enable();
}
DECL_COMMAND(command_stepper_group_stop, "stepper_group_stop oid=%c");

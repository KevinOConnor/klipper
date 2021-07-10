// Virtual tracking of a stepper driver
//
// Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

// This is temporary code that is used to update an internal "stepper
// position" given a series of "queue_step" commands.  It is intended
// to be used by the servo stepper control mechanism to calculate its
// "desired position".  Ultimately, it should be possible to update
// the host step compression code such that this code is not
// necessary.

#include "basecmd.h" // oid_alloc
#include "board/irq.h" // irq_disable
#include "board/misc.h" // timer_is_before
#include "command.h" // DECL_COMMAND
#include "sched.h" // struct timer
#include "trsync.h" // trsync_add_signal
#include "virtual_stepper.h" // virtual_stepper_oid_lookup

struct virtual_stepper_move {
    struct move_node node;
    uint32_t interval;
    int16_t add;
    uint16_t count;
    uint8_t flags;
};

enum { MF_DIR=1<<0 };

struct virtual_stepper {
    struct timer time;
    uint32_t interval;
    int16_t add;
    uint16_t count;
    uint32_t position;
    struct move_queue_head mq;
    struct trsync_signal stop_signal;
    uint8_t flags;
};

enum {
    SF_CURRENT_DIR=1<<0, SF_NEXT_DIR=1<<1,
    SF_LAST_RESET=1<<4, SF_NEED_RESET=1<<5
};

// Setup a stepper for the next move in its queue
static uint_fast8_t
virtual_stepper_load_next(struct virtual_stepper *s)
{
    if (move_queue_empty(&s->mq)) {
        // There is no next move - the queue is empty
        s->count = 0;
        return SF_DONE;
    }

    // Load next 'struct stepper_move' into 'struct stepper'
    struct move_node *mn = move_queue_pop(&s->mq);
    struct virtual_stepper_move *m = container_of(
        mn, struct virtual_stepper_move, node);
    s->time.waketime += m->interval;
    s->add = m->add;
    s->interval = m->interval + m->add;
    s->count = m->count;
    s->flags = (s->flags & ~SF_CURRENT_DIR) | m->flags;

    move_free(m);
    return SF_RESCHEDULE;
}

// Timer callback - step the given stepper.
static uint_fast8_t
virtual_stepper_event(struct timer *t)
{
    struct virtual_stepper *s = container_of(t, struct virtual_stepper, time);
    if (s->flags & SF_CURRENT_DIR)
        s->position++;
    else
        s->position--;
    uint16_t count = s->count - 1;
    if (likely(count)) {
        s->count = count;
        s->time.waketime += s->interval;
        s->interval += s->add;
        return SF_RESCHEDULE;
    }
    return virtual_stepper_load_next(s);
}

void
command_config_virtual_stepper(uint32_t *args)
{
    struct virtual_stepper *s = oid_alloc(
        args[0], command_config_virtual_stepper, sizeof(*s));
    s->time.func = virtual_stepper_event;
    move_queue_setup(&s->mq, sizeof(struct virtual_stepper_move));
}
DECL_COMMAND(command_config_virtual_stepper,
             "config_virtual_stepper oid=%c");

// Return the 'struct stepper' for a given stepper oid
struct virtual_stepper *
virtual_stepper_oid_lookup(uint8_t oid)
{
    return oid_lookup(oid, command_config_virtual_stepper);
}

// Schedule a set of steps with a given timing
void
command_virtual_queue_step(uint32_t *args)
{
    struct virtual_stepper *s = virtual_stepper_oid_lookup(args[0]);
    struct virtual_stepper_move *m = move_alloc();
    m->interval = args[1];
    m->count = args[2];
    if (!m->count)
        shutdown("Invalid count parameter");
    m->add = args[3];
    m->flags = 0;

    irq_disable();
    uint8_t flags = s->flags;
    m->flags = (flags & SF_NEXT_DIR) ? MF_DIR : 0;
    flags &= ~SF_LAST_RESET;
    if (s->count) {
        s->flags = flags;
        move_queue_push(&m->node, &s->mq);
    } else if (flags & SF_NEED_RESET) {
        move_free(m);
    } else {
        s->flags = flags;
        move_queue_push(&m->node, &s->mq);
        virtual_stepper_load_next(s);
        sched_add_timer(&s->time);
    }
    irq_enable();
}
DECL_COMMAND(command_virtual_queue_step,
             "virtual_queue_step oid=%c interval=%u count=%hu add=%hi");

// Set the direction of the next queued step
void
command_virtual_set_next_step_dir(uint32_t *args)
{
    struct virtual_stepper *s = virtual_stepper_oid_lookup(args[0]);
    uint8_t nextdir = args[1] ? SF_NEXT_DIR : 0;
    irq_disable();
    s->flags = (s->flags & ~SF_NEXT_DIR) | nextdir;
    irq_enable();
}
DECL_COMMAND(command_virtual_set_next_step_dir,
             "virtual_set_next_step_dir oid=%c dir=%c");

// Set an absolute time that the next step will be relative to
void
command_virtual_reset_step_clock(uint32_t *args)
{
    struct virtual_stepper *s = virtual_stepper_oid_lookup(args[0]);
    uint32_t waketime = args[1];
    irq_disable();
    if (s->count)
        shutdown("Can't reset time when stepper active");
    s->time.waketime = waketime;
    s->flags = (s->flags & ~SF_NEED_RESET) | SF_LAST_RESET;
    irq_enable();
}
DECL_COMMAND(command_virtual_reset_step_clock,
             "virtual_reset_step_clock oid=%c clock=%u");

// Return the current stepper position.  Caller must disable irqs.
uint32_t
virtual_stepper_get_position(struct virtual_stepper *s)
{
    return s->position;
}

// Report the current position of the stepper
void
command_virtual_stepper_get_position(uint32_t *args)
{
    uint8_t oid = args[0];
    struct virtual_stepper *s = virtual_stepper_oid_lookup(oid);
    irq_disable();
    uint32_t position = virtual_stepper_get_position(s);
    irq_enable();
    sendf("stepper_position oid=%c pos=%i", oid, position);
}
DECL_COMMAND(command_virtual_stepper_get_position,
             "virtual_stepper_get_position oid=%c");

// Stop all moves for a given stepper (caller must disable IRQs)
static void
virtual_stepper_stop(struct trsync_signal *tss, uint8_t reason)
{
    struct virtual_stepper *s = container_of(tss, struct virtual_stepper
                                             , stop_signal);
    sched_del_timer(&s->time);
    s->time.waketime = 0;
    s->count = 0;
    s->flags = SF_NEED_RESET;
    while (!move_queue_empty(&s->mq)) {
        struct move_node *mn = move_queue_pop(&s->mq);
        struct virtual_stepper_move *m = container_of(
            mn, struct virtual_stepper_move, node);
        move_free(m);
    }
}

// Set the stepper to stop on a "trigger event" (used in homing)
void
command_virtual_stepper_stop_on_trigger(uint32_t *args)
{
    struct virtual_stepper *s = virtual_stepper_oid_lookup(args[0]);
    struct trsync *ts = trsync_oid_lookup(args[1]);
    trsync_add_signal(ts, &s->stop_signal, virtual_stepper_stop);
}
DECL_COMMAND(command_virtual_stepper_stop_on_trigger,
             "virtual_stepper_stop_on_trigger oid=%c trsync_oid=%c");

void
virtual_stepper_shutdown(void)
{
    uint8_t i;
    struct virtual_stepper *s;
    foreach_oid(i, s, command_config_virtual_stepper) {
        move_queue_clear(&s->mq);
        virtual_stepper_stop(&s->stop_signal, 0);
    }
}
DECL_SHUTDOWN(virtual_stepper_shutdown);

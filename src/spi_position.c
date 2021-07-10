// Support for querying a servo stepper position via SPI
//
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

// This is generic code for querying the angle of a servo stepper via
// an SPI hall sensor chip.  It is understood that this code does not
// have sufficient timing precision - ultimately the goal is to use
// architecture specific DMA transfers to improve the timing.

#include <string.h> // memcpy
#include "board/irq.h" // irq_disable
#include "basecmd.h" // oid_alloc
#include "byteorder.h" // be32_to_cpu
#include "command.h" // DECL_COMMAND
#include "sched.h" // DECL_TASK
#include "servo_stepper.h" // servo_stepper_oid_lookup
#include "spicmds.h" // spidev_transfer

enum { SP_CHIP_A1333, SP_CHIP_AS5047D, SP_CHIP_MAX };

DECL_ENUMERATION("spiposition_type", "a1333", SP_CHIP_A1333);
DECL_ENUMERATION("spiposition_type", "as5047d", SP_CHIP_AS5047D);

#define CALIBRATE_SHIFT 5
#define CALIBRATE_SIZE (1 << CALIBRATE_SHIFT)
#define CALIBRATE_MASK (CALIBRATE_SIZE - 1)
#define CALIBRATE_HI_SHIFT (16 - CALIBRATE_SHIFT)
#define CALIBRATE_HI_MASK ((1 << CALIBRATE_HI_SHIFT) - 1)

struct spi_position {
    struct timer timer;
    uint32_t rest_time;
    uint32_t position;
    struct spidev_s *spi;
    struct servo_stepper *servo_stepper;
    uint8_t chip_type, flags;
    uint16_t calibration[CALIBRATE_SIZE];
};

enum {
    SP_PENDING = 1,
};

static struct task_wake spi_position_wake;

static uint_fast8_t
spi_position_event(struct timer *timer)
{
    struct spi_position *sp = container_of(timer, struct spi_position, timer);
    sched_wake_task(&spi_position_wake);
    sp->flags |= SP_PENDING;
    sp->timer.waketime += sp->rest_time;
    return SF_RESCHEDULE;
}

static uint32_t
spi_position_get_position(struct spi_position *sp)
{
    return sp->position;
}

void
command_config_spi_position(uint32_t *args)
{
    uint8_t chip_type = args[2];
    if (chip_type > SP_CHIP_MAX)
        shutdown("Invalid spi_position chip type");
    struct servo_stepper *ss = servo_stepper_oid_lookup(args[3]);
    struct spi_position *sp = oid_alloc(
        args[0], command_config_spi_position, sizeof(*sp));
    sp->timer.func = spi_position_event;
    sp->spi = spidev_oid_lookup(args[1]);
    sp->chip_type = chip_type;
    sp->servo_stepper = ss;
    int i;
    for (i=0; i<CALIBRATE_SIZE; i++)
        sp->calibration[i] = i << CALIBRATE_HI_SHIFT;
}
DECL_COMMAND(command_config_spi_position,
             "config_spi_position oid=%c spi_oid=%c spiposition_type=%c"
             " servo_stepper_oid=%c");

static struct spi_position *
spi_position_oid_lookup(uint8_t oid)
{
    return oid_lookup(oid, command_config_spi_position);
}

void
command_set_spi_position_calibration(uint32_t *args)
{
    struct spi_position *sp = spi_position_oid_lookup(args[0]);
    uint32_t idx = args[1];
    if (idx >= CALIBRATE_SIZE)
        shutdown("Invalid calibration index");
    sp->calibration[idx] = args[2];
}
DECL_COMMAND(command_set_spi_position_calibration,
             "set_spi_position_calibration oid=%c index=%u value=%hu");

void
command_schedule_spi_position(uint32_t *args)
{
    struct spi_position *sp = spi_position_oid_lookup(args[0]);
    sched_del_timer(&sp->timer);
    sp->timer.waketime = args[1];
    sp->rest_time = args[2];
    if (! sp->rest_time)
        return;
    sched_add_timer(&sp->timer);
}
DECL_COMMAND(command_schedule_spi_position,
             "schedule_spi_position oid=%c clock=%u rest_ticks=%u");

void
command_query_last_spi_position(uint32_t *args)
{
    uint8_t oid = args[0];
    struct spi_position *sp = spi_position_oid_lookup(args[0]);
    irq_disable();
    uint32_t next_clock = sp->timer.waketime;
    uint32_t position = spi_position_get_position(sp);
    irq_enable();
    sendf("spi_position_result oid=%c next_clock=%u position=%u",
          oid, next_clock, position);
}
DECL_COMMAND(command_query_last_spi_position, "query_last_spi_position oid=%c");

static void
spi_position_do_update(struct spi_position *sp, uint32_t raw_position)
{
    // Update position with calibration data
    uint32_t idx = raw_position >> CALIBRATE_HI_SHIFT;
    uint32_t cal1 = sp->calibration[idx];
    uint32_t cal2 = sp->calibration[(idx + 1) & CALIBRATE_MASK];
    uint32_t adj = (raw_position & CALIBRATE_HI_MASK) * (int16_t)(cal2 - cal1);
    uint32_t position = cal1 + DIV_ROUND_CLOSEST(adj, 1 << CALIBRATE_HI_SHIFT);

    // Update position to include rotation count
    uint32_t old_position = sp->position;
    uint32_t new_position = old_position + (int16_t)(position - old_position);
    sp->position = new_position;

    // Update servo_stepper code with new reading
    irq_disable();
    servo_stepper_update(sp->servo_stepper, new_position);
    irq_enable();
}

static void
spi_position_handle_A1333(struct spi_position *sp)
{
    uint8_t msg[2] = { 0x32, 0x00 };
    spidev_transfer(sp->spi, 1, sizeof(msg), msg);
    uint16_t value;
    memcpy(&value, msg, sizeof(value));
    spi_position_do_update(sp, (be16_to_cpu(value) << 1) & 0xffff);
}

static void
spi_position_handle_AS5047D(struct spi_position *sp)
{
    uint8_t msg[2] = { 0xFF, 0xFF };
    spidev_transfer(sp->spi, 0, sizeof(msg), msg);
    msg[0] = 0xC0;
    msg[1] = 0x00;
    spidev_transfer(sp->spi, 1, sizeof(msg), msg);
    uint16_t value;
    memcpy(&value, msg, sizeof(value));
    spi_position_do_update(sp, (be16_to_cpu(value) << 2) & 0xffff);
}

void
spi_position_task(void)
{
    if (!sched_check_wake(&spi_position_wake))
        return;
    uint8_t oid;
    struct spi_position *sp;
    foreach_oid(oid, sp, command_config_spi_position) {
        if (!(sp->flags & SP_PENDING))
            continue;
        irq_disable();
        sp->flags &= ~SP_PENDING;
        irq_enable();
        switch (sp->chip_type) {
        case SP_CHIP_A1333:
            spi_position_handle_A1333(sp);
            break;
        case SP_CHIP_AS5047D:
            spi_position_handle_AS5047D(sp);
            break;
        }
    }
}
DECL_TASK(spi_position_task);

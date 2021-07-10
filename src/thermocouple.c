// Basic support for common SPI controlled thermocouple chips
//
// Copyright (C) 2018  Petri Honkala <cruwaller@gmail.com>
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <string.h> // memcpy
#include "board/irq.h" // irq_disable
#include "basecmd.h" // oid_alloc
#include "byteorder.h" // be32_to_cpu
#include "command.h" // DECL_COMMAND
#include "sched.h" // DECL_TASK
#include "spicmds.h" // spidev_transfer

enum {
    TS_CHIP_MAX31855, TS_CHIP_MAX31856, TS_CHIP_MAX31865, TS_CHIP_MAX6675
};

DECL_ENUMERATION("thermocouple_type", "MAX31855", TS_CHIP_MAX31855);
DECL_ENUMERATION("thermocouple_type", "MAX31856", TS_CHIP_MAX31856);
DECL_ENUMERATION("thermocouple_type", "MAX31865", TS_CHIP_MAX31865);
DECL_ENUMERATION("thermocouple_type", "MAX6675", TS_CHIP_MAX6675);

struct thermocouple_spi {
    struct timer timer;
    uint32_t rest_time;
    uint32_t min_value;           // Min allowed ADC value
    uint32_t max_value;           // Max allowed ADC value
    uint32_t consecutive_faults;
    uint32_t consecutive_fault_limit;
    struct spidev_s *spi;
    uint8_t chip_type, flags;
};

enum {
    TS_PENDING = 1,
};

static struct task_wake thermocouple_wake;

static uint_fast8_t thermocouple_event(struct timer *timer) {
    struct thermocouple_spi *spi = container_of(
            timer, struct thermocouple_spi, timer);
    // Trigger task to read and send results
    sched_wake_task(&thermocouple_wake);
    spi->flags |= TS_PENDING;
    spi->timer.waketime += spi->rest_time;
    return SF_RESCHEDULE;
}

void
command_config_thermocouple(uint32_t *args)
{
    uint8_t chip_type = args[2];
    if (chip_type > TS_CHIP_MAX6675)
        shutdown("Invalid thermocouple chip type");
    struct thermocouple_spi *spi = oid_alloc(
        args[0], command_config_thermocouple, sizeof(*spi));
    spi->timer.func = thermocouple_event;
    spi->spi = spidev_oid_lookup(args[1]);
    spi->chip_type = chip_type;
    spi->consecutive_faults = 0;
    spi->consecutive_fault_limit = args[3];
}
DECL_COMMAND(command_config_thermocouple,
             "config_thermocouple oid=%c spi_oid=%c thermocouple_type=%c"
             " consecutive_fault_limit=%u");

void
command_query_thermocouple(uint32_t *args)
{
    struct thermocouple_spi *spi = oid_lookup(
        args[0], command_config_thermocouple);

    sched_del_timer(&spi->timer);
    spi->timer.waketime = args[1];
    spi->rest_time = args[2];
    if (! spi->rest_time)
        return;
    spi->min_value = args[3];
    spi->max_value = args[4];
    sched_add_timer(&spi->timer);
}
DECL_COMMAND(command_query_thermocouple,
             "query_thermocouple oid=%c clock=%u rest_ticks=%u"
             " min_value=%u max_value=%u");

static void
thermocouple_respond(struct thermocouple_spi *spi, uint32_t next_begin_time
                    , uint32_t value, uint8_t fault, uint8_t oid)
{
    sendf("thermocouple_result oid=%c next_clock=%u value=%u fault=%c"
          " consecutive_faults=%c",
          oid, next_begin_time, value, fault, spi->consecutive_faults);
    /* check the result and stop if below or above allowed range */
    if (value < spi->min_value || value > spi->max_value) {
        spi->consecutive_faults++;
        if (spi->consecutive_faults <= spi->consecutive_fault_limit)
            return;
        try_shutdown("Thermocouple ADC out of range");
    } else if (fault > 0) {
        spi->consecutive_faults++;
        if (spi->consecutive_faults <= spi->consecutive_fault_limit)
            return;
        try_shutdown("Thermocouple reader fault");
    } else {
        spi->consecutive_faults = 0;
    }
}

static void
thermocouple_handle_max31855(struct thermocouple_spi *spi
                             , uint32_t next_begin_time, uint8_t oid)
{
    uint8_t msg[4] = { 0x00, 0x00, 0x00, 0x00 };
    spidev_transfer(spi->spi, 1, sizeof(msg), msg);
    uint32_t value;
    memcpy(&value, msg, sizeof(value));
    value = be32_to_cpu(value);
    thermocouple_respond(spi, next_begin_time, value, 0, oid);
    // Kill after data send, host decode an error
    if (value & 0x04)
        try_shutdown("Thermocouple reader fault");
}

#define MAX31856_LTCBH_REG 0x0C
#define MAX31856_SR_REG 0x0F

static void
thermocouple_handle_max31856(struct thermocouple_spi *spi
                             , uint32_t next_begin_time, uint8_t oid)
{
    uint8_t msg[4] = { MAX31856_LTCBH_REG, 0x00, 0x00, 0x00 };
    spidev_transfer(spi->spi, 1, sizeof(msg), msg);
    uint32_t value;
    memcpy(&value, msg, sizeof(value));
    value = be32_to_cpu(value) & 0x00ffffff;
    // Read faults
    msg[0] = MAX31856_SR_REG;
    msg[1] = 0x00;
    spidev_transfer(spi->spi, 1, 2, msg);
    thermocouple_respond(spi, next_begin_time, value, msg[1], oid);
}

#define MAX31865_RTDMSB_REG 0x01
#define MAX31865_FAULTSTAT_REG 0x07

static void
thermocouple_handle_max31865(struct thermocouple_spi *spi
                             , uint32_t next_begin_time, uint8_t oid)
{
    uint8_t msg[4] = { MAX31865_RTDMSB_REG, 0x00, 0x00, 0x00 };
    spidev_transfer(spi->spi, 1, 3, msg);
    uint32_t value;
    memcpy(&value, msg, sizeof(value));
    value = (be32_to_cpu(value) >> 8) & 0xffff;
    // Read faults
    msg[0] = MAX31865_FAULTSTAT_REG;
    msg[1] = 0x00;
    spidev_transfer(spi->spi, 1, 2, msg);
    thermocouple_respond(spi, next_begin_time, value, msg[1], oid);
}

static void
thermocouple_handle_max6675(struct thermocouple_spi *spi
                            , uint32_t next_begin_time, uint8_t oid)
{
    uint8_t msg[2] = { 0x00, 0x00};
    spidev_transfer(spi->spi, 1, sizeof(msg), msg);
    uint16_t value;
    memcpy(&value, msg, sizeof(msg));
    value = be16_to_cpu(value);
    thermocouple_respond(spi, next_begin_time, value, 0, oid);
    // Kill after data send, host decodes an error. This is raised when the
    // thermocouple is detected as open.
    if (value & 0x04)
        try_shutdown("Thermocouple reader fault");
}

// task to read thermocouple and send response
void
thermocouple_task(void)
{
    if (!sched_check_wake(&thermocouple_wake))
        return;
    uint8_t oid;
    struct thermocouple_spi *spi;
    foreach_oid(oid, spi, command_config_thermocouple) {
        if (!(spi->flags & TS_PENDING))
            continue;
        irq_disable();
        uint32_t next_begin_time = spi->timer.waketime;
        spi->flags &= ~TS_PENDING;
        irq_enable();
        switch (spi->chip_type) {
        case TS_CHIP_MAX31855:
            thermocouple_handle_max31855(spi, next_begin_time, oid);
            break;
        case TS_CHIP_MAX31856:
            thermocouple_handle_max31856(spi, next_begin_time, oid);
            break;
        case TS_CHIP_MAX31865:
            thermocouple_handle_max31865(spi, next_begin_time, oid);
            break;
        case TS_CHIP_MAX6675:
            thermocouple_handle_max6675(spi, next_begin_time, oid);
            break;
        }
    }
}
DECL_TASK(thermocouple_task);

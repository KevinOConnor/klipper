// Code for controlling a "servo stepper"
//
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "board/irq.h" // irq_disable
#include "board/gpio.h" // gpio_pwm_write
#include "basecmd.h" // oid_alloc
#include "command.h" // DECL_COMMAND
#include "driver_a4954.h" // a4954_oid_lookup
#include "servo_stepper.h" // servo_stepper_oid_lookup
#include "virtual_stepper.h" // virtual_stepper_oid_lookup

struct servo_stepper {
    struct a4954 *stepper_driver;
    struct virtual_stepper *virtual_stepper;
    uint32_t full_steps_per_rotation;
    uint32_t excite_angle;
    uint32_t current_scale;
    uint8_t flags;
};

enum {
    SS_MODE_DISABLED = 0, SS_MODE_OPEN_LOOP = 1, SS_MODE_TORQUE = 2,
};

static uint32_t
position_to_phase(struct servo_stepper *ss, uint32_t position)
{
    return DIV_ROUND_CLOSEST(ss->full_steps_per_rotation * position, 256);
}

static void
servo_stepper_mode_open_loop(struct servo_stepper *ss, uint32_t position)
{
    uint32_t vs_position = virtual_stepper_get_position(ss->virtual_stepper);
    a4954_set_phase(ss->stepper_driver, vs_position, ss->current_scale);
}

static void
servo_stepper_mode_torque_update(struct servo_stepper *ss, uint32_t position)
{
    uint32_t phase = position_to_phase(ss, position);
    a4954_set_phase(ss->stepper_driver, phase + ss->excite_angle
                    , ss->current_scale);
}

void
servo_stepper_update(struct servo_stepper *ss, uint32_t position)
{
    uint32_t mode = ss->flags;
    switch (mode) {
    case SS_MODE_OPEN_LOOP: servo_stepper_mode_open_loop(ss, position); break;
    case SS_MODE_TORQUE: servo_stepper_mode_torque_update(ss, position); break;
    }
}

void
command_config_servo_stepper(uint32_t *args)
{
    struct a4954 *a = a4954_oid_lookup(args[1]);
    struct virtual_stepper *vs = virtual_stepper_oid_lookup(args[2]);
    struct servo_stepper *ss = oid_alloc(
        args[0], command_config_servo_stepper, sizeof(*ss));
    ss->stepper_driver = a;
    ss->virtual_stepper = vs;
    ss->full_steps_per_rotation = args[3];
}
DECL_COMMAND(command_config_servo_stepper,
             "config_servo_stepper oid=%c driver_oid=%c stepper_oid=%c"
             " full_steps_per_rotation=%u");

struct servo_stepper *
servo_stepper_oid_lookup(uint8_t oid)
{
    return oid_lookup(oid, command_config_servo_stepper);
}

void
command_servo_stepper_set_disabled(uint32_t *args)
{
    struct servo_stepper *ss = servo_stepper_oid_lookup(args[0]);
    irq_disable();
    ss->flags = SS_MODE_DISABLED;
    a4954_disable(ss->stepper_driver);
    irq_enable();
}
DECL_COMMAND(command_servo_stepper_set_disabled,
             "servo_stepper_set_disabled oid=%c");

void
command_servo_stepper_set_open_loop_mode(uint32_t *args)
{
    struct servo_stepper *ss = servo_stepper_oid_lookup(args[0]);
    irq_disable();
    a4954_enable(ss->stepper_driver);
    ss->flags = SS_MODE_OPEN_LOOP;
    ss->current_scale = args[1];
    irq_enable();
}
DECL_COMMAND(command_servo_stepper_set_open_loop_mode,
             "servo_stepper_set_open_loop_mode oid=%c current_scale=%u");

void
command_servo_stepper_set_torque_mode(uint32_t *args)
{
    struct servo_stepper *ss = servo_stepper_oid_lookup(args[0]);
    irq_disable();
    a4954_enable(ss->stepper_driver);
    ss->flags = SS_MODE_TORQUE;
    ss->excite_angle = args[1];
    ss->current_scale = args[2];
    irq_enable();
}
DECL_COMMAND(command_servo_stepper_set_torque_mode,
             "servo_stepper_set_torque_mode oid=%c"
             " excite_angle=%u current_scale=%u");

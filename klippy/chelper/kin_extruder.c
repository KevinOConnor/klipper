// Extruder stepper pulse time generation
//
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stdlib.h> // malloc
#include <string.h> // memset
#include "compiler.h" // __visible
#include "itersolve.h" // struct stepper_kinematics
#include "pyhelper.h" // errorf
#include "kinematics.h"

static double
extruder_calc_position(struct stepper_kinematics *sk, struct move *m
                       , double move_time)
{
    return m->start_pos.x + move_get_distance(m, move_time);
}

struct stepper_kinematics * __visible
extruder_stepper_alloc(void)
{
    struct stepper_kinematics *sk = malloc(sizeof(*sk));
    memset(sk, 0, sizeof(*sk));
    sk->calc_position = extruder_calc_position;
    return sk;
}

// Populate a 'struct move' with an extruder velocity trapezoid
void __visible
extruder_move_fill(struct move *m, double print_time
                   , double accel_t, double cruise_t, double decel_t
                   , double start_pos
                   , double start_v, double cruise_v, double accel
                   , double extra_accel_v, double extra_decel_v)
{
    // Setup velocity trapezoid
    m->print_time = print_time;
    m->move_t = accel_t + cruise_t + decel_t;
    m->accel_t = accel_t;
    m->cruise_t = cruise_t;
    m->cruise_start_d = accel_t * (.5 * (cruise_v + start_v) + extra_accel_v);
    m->decel_start_d = m->cruise_start_d + cruise_t * cruise_v;

    // Setup for accel/cruise/decel phases
    m->cruise_v = cruise_v;
    m->accel.c1 = start_v + extra_accel_v;
    m->accel.c2 = .5 * accel;
    m->decel.c1 = cruise_v + extra_decel_v;
    m->decel.c2 = -m->accel.c2;

    // Setup start distance
    m->start_pos.x = start_pos;
}

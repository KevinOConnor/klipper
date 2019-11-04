// Delta kinematics stepper pulse time generation
//
// Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <math.h> // sqrt
#include <stddef.h> // offsetof
#include <stdlib.h> // malloc
#include <string.h> // memset
#include "compiler.h" // __visible
#include "itersolve.h" // struct stepper_kinematics
#include "kinematics.h"

struct delta_stepper {
    struct stepper_kinematics sk;
    double arm2, tower_x, tower_y;
};

static double
delta_stepper_calc_position(struct stepper_kinematics *sk, struct move *m
                            , double move_time)
{
    struct delta_stepper *ds = container_of(sk, struct delta_stepper, sk);
    struct coord c = move_get_coord(m, move_time);
    double dx = ds->tower_x - c.x, dy = ds->tower_y - c.y;
    return sqrt(ds->arm2 - dx*dx - dy*dy) + c.z;
}

struct stepper_kinematics * __visible
delta_stepper_alloc(double arm2, double tower_x, double tower_y)
{
    struct delta_stepper *ds = malloc(sizeof(*ds));
    memset(ds, 0, sizeof(*ds));
    ds->arm2 = arm2;
    ds->tower_x = tower_x;
    ds->tower_y = tower_y;
    ds->sk.calc_position = delta_stepper_calc_position;
    return &ds->sk;
}

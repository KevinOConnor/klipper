// CoreXZ kinematics stepper pulse time generation
//
// Copyright (C) 2020  Maks Zolin <mzolin@vorondesign.com>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stdlib.h> // malloc
#include <string.h> // memset
#include "compiler.h" // __visible
#include "itersolve.h" // struct stepper_kinematics
#include "trapq.h" // move_get_coord

static double
corexz_stepper_plus_calc_position(struct stepper_kinematics *sk, struct move *m
                                  , double move_time)
{
    struct coord c = move_get_coord(m, move_time);
    return c.x + c.z;
}

static double
corexz_stepper_minus_calc_position(struct stepper_kinematics *sk, struct move *m
                                   , double move_time)
{
    struct coord c = move_get_coord(m, move_time);
    return c.x - c.z;
}

struct stepper_kinematics * __visible
corexz_stepper_alloc(char type)
{
    struct stepper_kinematics *sk = malloc(sizeof(*sk));
    memset(sk, 0, sizeof(*sk));
    if (type == '+')
        sk->calc_position_cb = corexz_stepper_plus_calc_position;
    else if (type == '-')
        sk->calc_position_cb = corexz_stepper_minus_calc_position;
    sk->active_flags = AF_X | AF_Z;
    return sk;
}

static double
corexz_reverse_stepper_plus_calc_position(struct stepper_kinematics *sk,
                                  struct move *m, double move_time)
{
    struct coord c = move_get_coord(m, move_time);
    return -c.x - c.z;
}

static double
corexz_reverse_stepper_minus_calc_position(struct stepper_kinematics *sk,
                                   struct move *m, double move_time)
{
    struct coord c = move_get_coord(m, move_time);
    return -c.x + c.z;
}

struct stepper_kinematics * __visible
corexz_reverse_stepper_alloc(char type)
{
    struct stepper_kinematics *sk = malloc(sizeof(*sk));
    memset(sk, 0, sizeof(*sk));
    if (type == '+')
        sk->calc_position_cb = corexz_reverse_stepper_plus_calc_position;
    else if (type == '-')
        sk->calc_position_cb = corexz_reverse_stepper_minus_calc_position;
    sk->active_flags = AF_X | AF_Z;
    return sk;
}

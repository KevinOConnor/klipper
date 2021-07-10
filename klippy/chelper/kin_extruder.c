// Extruder stepper pulse time generation
//
// Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stddef.h> // offsetof
#include <stdlib.h> // malloc
#include <string.h> // memset
#include "compiler.h" // __visible
#include "itersolve.h" // struct stepper_kinematics
#include "pyhelper.h" // errorf
#include "trapq.h" // move_get_distance

// Without pressure advance, the extruder stepper position is:
//     extruder_position(t) = nominal_position(t)
// When pressure advance is enabled, additional filament is pushed
// into the extruder during acceleration (and retracted during
// deceleration). The formula is:
//     pa_position(t) = (nominal_position(t)
//                       + pressure_advance * nominal_velocity(t))
// Which is then "smoothed" using a weighted average:
//     smooth_position(t) = (
//         definitive_integral(pa_position(x) * (smooth_time/2 - abs(t-x)) * dx,
//                             from=t-smooth_time/2, to=t+smooth_time/2)
//         / ((smooth_time/2)**2))

// Calculate the definitive integral of the motion formula:
//   position(t) = base + t * (start_v + t * half_accel)
static double
extruder_integrate(double base, double start_v, double half_accel
                   , double start, double end)
{
    double half_v = .5 * start_v, sixth_a = (1. / 3.) * half_accel;
    double si = start * (base + start * (half_v + start * sixth_a));
    double ei = end * (base + end * (half_v + end * sixth_a));
    return ei - si;
}

// Calculate the definitive integral of time weighted position:
//   weighted_position(t) = t * (base + t * (start_v + t * half_accel))
static double
extruder_integrate_time(double base, double start_v, double half_accel
                        , double start, double end)
{
    double half_b = .5 * base, third_v = (1. / 3.) * start_v;
    double eighth_a = .25 * half_accel;
    double si = start * start * (half_b + start * (third_v + start * eighth_a));
    double ei = end * end * (half_b + end * (third_v + end * eighth_a));
    return ei - si;
}

// Calculate the definitive integral of extruder for a given move
static double
pa_move_integrate(struct move *m, double base, double start, double end,
                  double time_offset)
{
    if (start < 0.)
        start = 0.;
    if (end > m->move_t)
        end = m->move_t;
    // Calculate base position and velocity with pressure advance
    double pressure_advance = m->axes_r.y;
    base += pressure_advance * m->start_v;
    double start_v = m->start_v + pressure_advance * 2. * m->half_accel;
    // Calculate definitive integral
    double ha = m->half_accel;
    double iext = extruder_integrate(base, start_v, ha, start, end);
    double wgt_ext = extruder_integrate_time(base, start_v, ha, start, end);
    return wgt_ext - time_offset * iext;
}

// Calculate the definitive integral of the extruder over a range of moves
static double
pa_range_integrate(struct move *m, double move_time, double hst)
{
    // Calculate integral for the current move
    double res = 0., start = move_time - hst, end = move_time + hst;
    double start_base = m->start_pos.x;
    res += pa_move_integrate(m, 0., start, move_time, start);
    res -= pa_move_integrate(m, 0., move_time, end, end);
    // Integrate over previous moves
    struct move *prev = m;
    while (unlikely(start < 0.)) {
        prev = list_prev_entry(prev, node);
        start += prev->move_t;
        double base = prev->start_pos.x - start_base;
        res += pa_move_integrate(prev, base, start, prev->move_t, start);
    }
    // Integrate over future moves
    while (unlikely(end > m->move_t)) {
        end -= m->move_t;
        m = list_next_entry(m, node);
        double base = m->start_pos.x - start_base;
        res -= pa_move_integrate(m, base, 0., end, end);
    }
    return res;
}

// Calculate the additional non-linear extrusion movement over a move
static double
nonlinear_extrusion_integrate(struct move *m, double move_time,
                              double a, double b)
{
    double t2 = move_time * move_time;
    double t3 = t2 * move_time;
    double t4 = t3 * move_time;
    double sv2 = m->start_v * m->start_v;
    double sv3 = sv2 * m->start_v;

    // Integral of the intended velocity squared
    double v2 = sv2 * move_time
        + m->start_v * m->half_accel * t2
        + m->half_accel * m->half_accel * t3 * (4.0 / 3.0);

    // Integral of the intended velocity cubed
    double v3 = sv3 * move_time
        + sv2 * m->half_accel * t2 * 3.0
        + m->half_accel * m->half_accel * m->start_v  * t3 * 4.0
        + m->half_accel * m->half_accel * m->half_accel * t4 * 2.0;

    return a * v2 + b * v3;
}

struct extruder_stepper {
    struct stepper_kinematics sk;
    double half_smooth_time, inv_half_smooth_time2;
    // Total amount of extra movement added by nonlinear extrusion
    double added_travel;
    double nonlinear_a, nonlinear_b;
};

static double
extruder_calc_position(struct stepper_kinematics *sk, struct move *m
                       , double move_time)
{
    struct extruder_stepper *es = container_of(sk, struct extruder_stepper, sk);
    double pos = m->start_pos.x + es->added_travel;
    double hst = es->half_smooth_time;
    if (hst) {
        // Apply pressure advance and average over smooth_time
        double area = pa_range_integrate(m, move_time, hst);
        pos += area * es->inv_half_smooth_time2;
    } else // Pressure advance not enabled
        pos += move_get_distance(m, move_time);

    double a = es->nonlinear_a, b = es->nonlinear_b;
    if (a || b)
        pos += nonlinear_extrusion_integrate(m, move_time, a, b);
    return pos;
}

static void
extruder_post_move(struct stepper_kinematics *sk, struct move *m)
{
    struct extruder_stepper *es = container_of(sk, struct extruder_stepper, sk);

    double a = es->nonlinear_a, b = es->nonlinear_b;
    if (a || b)
        es->added_travel += nonlinear_extrusion_integrate(m, m->move_t, a, b);
}

void __visible
extruder_set_smooth_time(struct stepper_kinematics *sk, double smooth_time)
{
    struct extruder_stepper *es = container_of(sk, struct extruder_stepper, sk);
    double hst = smooth_time * .5;
    es->half_smooth_time = hst;
    es->sk.gen_steps_pre_active = es->sk.gen_steps_post_active = hst;
    if (! hst)
        return;
    es->inv_half_smooth_time2 = 1. / (hst * hst);
}

void __visible
extruder_set_nonlinear(struct stepper_kinematics *sk, double a, double b)
{
    struct extruder_stepper *es = container_of(sk, struct extruder_stepper, sk);
    es->nonlinear_a = a;
    es->nonlinear_b = b;
}

struct stepper_kinematics * __visible
extruder_stepper_alloc(void)
{
    struct extruder_stepper *es = malloc(sizeof(*es));
    memset(es, 0, sizeof(*es));
    es->sk.calc_position_cb = extruder_calc_position;
    es->sk.post_move_cb = extruder_post_move;
    es->sk.active_flags = AF_X;
    return &es->sk;
}

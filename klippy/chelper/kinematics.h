#ifndef __KINEMATICS_H
#define __KINEMATICS_H

struct stepper_kinematics *cartesian_stepper_alloc(char axis);
struct stepper_kinematics *corexy_stepper_alloc(char type);
struct stepper_kinematics *delta_stepper_alloc(double arm2
    , double tower_x, double tower_y);
struct stepper_kinematics *polar_stepper_alloc(char type);
struct stepper_kinematics *winch_stepper_alloc(double anchor_x
    , double anchor_y, double anchor_z);
struct stepper_kinematics *extruder_stepper_alloc(void);
void extruder_move_fill(struct move *m, double print_time
    , double accel_t, double cruise_t, double decel_t, double start_pos
    , double start_v, double cruise_v, double accel
    , double extra_accel_v, double extra_decel_v);


#endif

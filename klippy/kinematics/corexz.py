# Code for handling the kinematics of corexz robots
#
# Copyright (C) 2020  Maks Zolin <mzolin@vorondesign.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math
import stepper

class CoreXZKinematics:
    def __init__(self, toolhead, config):
        # Setup axis rails
        self.rails = [ stepper.PrinterRail(config.getsection('stepper_x')),
                       stepper.PrinterRail(config.getsection('stepper_y')),
                       stepper.PrinterRail(config.getsection('stepper_z')) ]
        self.rails[0].get_endstops()[0][0].add_stepper(
            self.rails[2].get_steppers()[0])
        self.rails[2].get_endstops()[0][0].add_stepper(
            self.rails[0].get_steppers()[0])
        self.rails[0].setup_itersolve('corexz_stepper_alloc', b'+')
        self.rails[1].setup_itersolve('cartesian_stepper_alloc', b'y')
        self.rails[2].setup_itersolve('corexz_stepper_alloc', b'-')
        for s in self.get_steppers():
            s.set_trapq(toolhead.get_trapq())
            toolhead.register_step_generator(s.generate_steps)
        config.get_printer().register_event_handler("stepper_enable:motor_off",
                                                    self._motor_off)
        # Setup boundary checks
        max_velocity, max_accel = toolhead.get_max_velocity()
        self.max_z_velocity = config.getfloat(
            'max_z_velocity', max_velocity, above=0., maxval=max_velocity)
        self.max_z_accel = config.getfloat(
            'max_z_accel', max_accel, above=0., maxval=max_accel)
        self.limits = [(1.0, -1.0)] * 3
        ranges = [r.get_range() for r in self.rails]
        self.axes_min = toolhead.Coord(*[r[0] for r in ranges], e=0.)
        self.axes_max = toolhead.Coord(*[r[1] for r in ranges], e=0.)
        # Setup stepper max halt velocity
        max_halt_velocity = toolhead.get_max_axis_halt()
        max_xy_halt_velocity = max_halt_velocity * math.sqrt(2.)
        max_xy_accel = max_accel * math.sqrt(2.)
        self.rails[0].set_max_jerk(max_xy_halt_velocity, max_xy_accel)
        self.rails[1].set_max_jerk(max_xy_halt_velocity, max_xy_accel)
        self.rails[2].set_max_jerk(max_xy_halt_velocity, max_xy_accel)
    def get_steppers(self):
        return [s for rail in self.rails for s in rail.get_steppers()]
    def calc_tag_position(self):
        pos = [rail.get_tag_position() for rail in self.rails]
        return [0.5 * (pos[0] + pos[2]), pos[1], 0.5 * (pos[0] - pos[2])]
    def set_position(self, newpos, homing_axes):
        for i, rail in enumerate(self.rails):
            rail.set_position(newpos)
            if i in homing_axes:
                self.limits[i] = rail.get_range()
    def note_z_not_homed(self):
        # Helper for Safe Z Home
        self.limits[2] = (1.0, -1.0)
    def home(self, homing_state):
        # Each axis is homed independently and in order
        for axis in homing_state.get_axes():
            rail = self.rails[axis]
            # Determine movement
            position_min, position_max = rail.get_range()
            hi = rail.get_homing_info()
            homepos = [None, None, None, None]
            homepos[axis] = hi.position_endstop
            forcepos = list(homepos)
            if hi.positive_dir:
                forcepos[axis] -= 1.5 * (hi.position_endstop - position_min)
            else:
                forcepos[axis] += 1.5 * (position_max - hi.position_endstop)
            # Perform homing
            homing_state.home_rails([rail], forcepos, homepos)
    def _motor_off(self, print_time):
        self.limits = [(1.0, -1.0)] * 3
    def _check_endstops(self, move):
        end_pos = move.end_pos
        for i in (0, 1, 2):
            if (move.axes_d[i]
                and (end_pos[i] < self.limits[i][0]
                     or end_pos[i] > self.limits[i][1])):
                if self.limits[i][0] > self.limits[i][1]:
                    raise move.move_error("Must home axis first")
                raise move.move_error()
    def check_move(self, move):
        limits = self.limits
        xpos, ypos = move.end_pos[:2]
        if (xpos < limits[0][0] or xpos > limits[0][1]
            or ypos < limits[1][0] or ypos > limits[1][1]):
            self._check_endstops(move)
        if not move.axes_d[2]:
            # Normal XY move - use defaults
            return
        # Move with Z - update velocity and accel for slower Z axis
        self._check_endstops(move)
        z_ratio = move.move_d / abs(move.axes_d[2])
        move.limit_speed(
            self.max_z_velocity * z_ratio, self.max_z_accel * z_ratio)
    def get_status(self, eventtime):
        axes = [a for a, (l, h) in zip("xyz", self.limits) if l <= h]
        return {
            'homed_axes': "".join(axes),
            'axis_minimum': self.axes_min,
            'axis_maximum': self.axes_max,
        }

def load_kinematics(toolhead, config):
    return CoreXZKinematics(toolhead, config)

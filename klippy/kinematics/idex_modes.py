# Support for duplication and mirroring modes for IDEX printers
#
# Copyright (C) 2021  Fabrice Gallet <tircown@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math

class DualCarriages:
    def __init__(self, printer, rail_0, rail_1, axis):
        self.printer = printer
        self.axis = axis
        self.dc = (rail_0, rail_1)
        self.saved_state = None
        self.printer.add_object('dual_carriage', self)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command(
                   'SET_DUAL_CARRIAGE', self.cmd_SET_DUAL_CARRIAGE,
                   desc=self.cmd_SET_DUAL_CARRIAGE_help)
        gcode.register_command(
                   'SET_DUAL_CARRIAGE_MODE', self.cmd_SET_DUAL_CARRIAGE_MODE,
                   desc=self.cmd_SET_DUAL_CARRIAGE_MODE_help)
    def toggle_active_dc_rail(self, index):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.flush_step_generation()
        pos = toolhead.get_position()
        kin = toolhead.get_kinematics()
        for i, dc in enumerate(self.dc):
            dc_rail = dc.get_rail()
            if i != index:
                dc.inactivate(pos)
                kin.override_rail(3, dc_rail)
            elif dc.is_active() is False:
                newpos = pos[:self.axis] + [dc.axis_position] \
                            + pos[self.axis+1:]
                dc.activate(newpos)
                kin.override_rail(self.axis, dc_rail)
                toolhead.set_position(newpos)
                kin.update_limits(self.axis, dc_rail.get_range())
    def _calc_dual_carriages_positions(self, pos):
        axis_pos = pos[self.axis]
        dc0_pos = self.dc[0].axis_position
        dc1_pos = self.dc[1].axis_position
        # duplication
        if (self.dc[0].is_active() == self.dc[1].is_active() == True
                        and self.dc[1].is_reversed() is False):
            newpos = dc1_pos - dc0_pos + axis_pos
            return (pos[:self.axis] + [axis_pos] + pos[self.axis+1:],
                        pos[:self.axis] + [newpos] + pos[self.axis+1:])
        # mirrored
        elif (self.dc[0].is_active() == self.dc[1].is_active() == True
                        and self.dc[1].is_reversed() is True):
            newpos = dc1_pos + dc0_pos - axis_pos
            return (pos[:self.axis] + [axis_pos] + pos[self.axis+1:],
                        pos[:self.axis] + [newpos] + pos[self.axis+1:])
        # full-control: T0 active
        elif (self.dc[0].is_active() is True):
            return (pos[:self.axis] + [axis_pos] + pos[self.axis+1:],
                        pos[:self.axis] + [dc1_pos] + pos[self.axis+1:])
        # full-control: T1 active
        elif (self.dc[1].is_active() is True):
            return (pos[:self.axis] + [dc0_pos] + pos[self.axis+1:],
                        pos[:self.axis] + [axis_pos] + pos[self.axis+1:])
    def activate_dc_mode(self, mode):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.flush_step_generation()
        pos = toolhead.get_position()
        kin = toolhead.get_kinematics()
        dc0_pos, dc1_pos = self._calc_dual_carriages_positions(pos)
        self.dc[0].activate(dc0_pos)
        dc0_rail = self.dc[0].get_rail()
        dc1_rail = self.dc[1].get_rail()
        kin.override_rail(self.axis, dc0_rail)
        kin.override_rail(3, dc1_rail)
        if 'FULL_CONTROL' == mode:
            self.dc[1].inactivate(dc1_pos)
            toolhead.set_position(dc0_pos)
            kin.update_limits(self.axis, dc0_rail.get_range())
            self.printer.lookup_object('gcode').respond_info(
                "Dual carriage mode is now set to %s" % 'FULL_CONTROL')
        elif 'DUPLICATION' == mode:
            self.dc[1].activate(dc1_pos)
            toolhead.set_position(dc0_pos)
            dc_rail_min= min(dc0_rail.position_min, dc1_rail.position_min)
            dc_rail_max= max(dc0_rail.position_max, dc1_rail.position_max)
            if dc0_rail.get_homing_info().positive_dir is False:
                axis_limits = (dc_rail_min, math.floor(dc_rail_max
                            - dc1_pos[self.axis] + dc0_pos[self.axis]))
            else:
                axis_limits = (math.ceil(dc0_pos[self.axis]
                            - dc1_pos[self.axis] - dc_rail_min), dc_rail_max)
            kin.update_limits(self.axis, axis_limits)
            self.printer.lookup_object('gcode').respond_info(
                "Dual carriage mode is now set to %s" % 'DUPLICATION')
        elif 'MIRRORED' == mode:
            self.dc[1].activate(dc1_pos, reverse=True)
            toolhead.set_position(dc0_pos)
            dc_rail_min= min(dc0_rail.position_min, dc1_rail.position_min)
            dc_rail_max= max(dc0_rail.position_max, dc1_rail.position_max)
            dc_rail_diff= abs(dc0_rail.position_min - dc1_rail.position_min)
            if dc0_rail.get_homing_info().positive_dir is False:
                axis_limits =(
                    math.ceil(dc0_pos[self.axis] - min(
                        abs(dc0_pos[self.axis] - dc_rail_min),
                        abs(dc0_pos[self.axis] - dc_rail_max),
                        abs(dc1_pos[self.axis] - dc_rail_min),
                        abs(dc1_pos[self.axis] - dc_rail_max))),
                    math.floor(0.5 * (dc1_pos[self.axis]
                               + dc0_pos[self.axis] - dc_rail_diff)))
            else:
                axis_limits = (
                    math.ceil(0.5 * (dc1_pos[self.axis]
                               + dc0_pos[self.axis] + dc_rail_diff)),
                    math.floor(dc0_pos[self.axis] + min(
                        abs(dc0_pos[self.axis] - dc_rail_min),
                        abs(dc0_pos[self.axis] - dc_rail_max),
                        abs(dc1_pos[self.axis] - dc_rail_min),
                        abs(dc1_pos[self.axis] - dc_rail_max))))
            kin.update_limits(self.axis, axis_limits)
            self.printer.lookup_object('gcode').respond_info(
                "Dual carriage mode is now set to %s" % 'MIRRORED')
        else:
            raise self.printer.lookup_object('gcode').error(
                "'%s' is not a valid mode." % mode)
    def get_status(self, eventtime):
        dc0, dc1 = self.dc
        if (dc0.is_active() == dc1.is_active() == True):
            mode = ('DUPLICATION','MIRRORED')[dc1.is_reversed()]
            return { 'mode': mode, 'active_carriage': 'BOTH' }
        elif (dc0.is_active() is True):
            return { 'mode': 'FULL_CONTROL', 'active_carriage': 'CARRIAGE_0' }
        else:
            return { 'mode': 'FULL_CONTROL', 'active_carriage': 'CARRIAGE_1' }
    def save_idex_state(self):
        dc0, dc1 = self.dc
        if (dc0.is_active() == dc1.is_active() == True):
            mode = ('DUPLICATION','MIRRORED')[dc1.is_reversed()]
            active_carriage = 'BOTH'
        elif (dc0.is_active() is True):
            mode, active_carriage = ('FULL_CONTROL', 'CARRIAGE_0')
        else:
            mode, active_carriage = ('FULL_CONTROL', 'CARRIAGE_1')
        self.saved_state = {
            'mode': mode,
            'active_carriage': active_carriage,
            'axis_positions': (dc0.axis_position, dc1.axis_position)
            }
    def restore_idex_state(self):
        if self.saved_state is not None:
            if (self.saved_state['mode'] in ('DUPLICATION','MIRRORED')):
                toolhead = self.printer.lookup_object('toolhead')
                toolhead.flush_step_generation()
                pos = toolhead.get_position()
                for i in [1,0]:
                    if (self.dc[i].is_active() is False):
                        self.toggle_active_dc_rail(i)
                    dci_pos = self.saved_state['axis_positions'][i]
                    toolhead.manual_move(
                        pos[:self.axis] + [dci_pos] + pos[self.axis+1:],
                        self.dc[i].get_rail().homing_speed)
                self.activate_dc_mode(self.saved_state['mode'])
            # set carriage 0 active
            elif (self.saved_state['active_carriage'] == 'CARRIAGE_0'
                        and self.dc[0].is_active() is False):
                self.toggle_active_dc_rail(0)
            # set carriage 1 active
            elif (self.saved_state['active_carriage'] == 'CARRIAGE_1'
                        and self.dc[1].is_active() is False):
                self.toggle_active_dc_rail(1)
    cmd_SET_DUAL_CARRIAGE_help = "Set which carriage is active"
    def cmd_SET_DUAL_CARRIAGE(self, gcmd):
        index = gcmd.get_int('CARRIAGE', minval=0, maxval=1)
        if (not(self.dc[0].is_active() == self.dc[1].is_active() == True)
                    and self.dc[index].is_active() is False):
            self.toggle_active_dc_rail(index)
    cmd_SET_DUAL_CARRIAGE_MODE_help = "Set which mode is active"
    def cmd_SET_DUAL_CARRIAGE_MODE(self, gcmd):
        mode = gcmd.get('MODE')
        self.activate_dc_mode(mode)

class DualCarriagesRail:
    ACTIVE=1
    INACTIVE=2
    REVERSED=3
    def __init__(self, printer, rail, axis, active, stepper_alloc_active,
                 stepper_alloc_inactive=None, stepper_alloc_reverse=None):
        self.printer = printer
        self.rail = rail
        self.axis = axis
        self.status = (self.INACTIVE, self.ACTIVE)[active]
        self.stepper_alloc_active = stepper_alloc_active
        self.stepper_alloc_inactive = stepper_alloc_inactive
        self.stepper_alloc_reverse = stepper_alloc_reverse
        self.axis_position = -1
    def _stepper_alloc(self, position, active=True, reverse=False):
        toolhead = self.printer.lookup_object('toolhead')
        self.axis_position = position[self.axis]
        self.rail.set_trapq(None)
        if reverse is True:
            self.status = self.REVERSED
            if self.stepper_alloc_reverse is not None:
                self.rail.setup_itersolve(*self.stepper_alloc_reverse)
                self.rail.set_position(position)
                self.rail.set_trapq(toolhead.get_trapq())
        elif active is True:
            self.status = self.ACTIVE
            if self.stepper_alloc_active is not None:
                self.rail.setup_itersolve(*self.stepper_alloc_active)
                self.rail.set_position(position)
                self.rail.set_trapq(toolhead.get_trapq())
        else:
            self.status = self.INACTIVE
            if self.stepper_alloc_inactive is not None:
                self.rail.setup_itersolve(*self.stepper_alloc_inactive)
                self.rail.set_position(position)
                self.rail.set_trapq(toolhead.get_trapq())
    def get_rail(self):
        return self.rail
    def is_active(self):
        return self.status in [self.ACTIVE, self.REVERSED]
    def is_reversed(self):
        return self.status == self.REVERSED
    def activate(self, position, reverse=False):
        self._stepper_alloc(position, active=True, reverse=reverse)
    def inactivate(self, position):
        self._stepper_alloc(position, active=False)

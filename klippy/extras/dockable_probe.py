# Dockable Probe
#   This provides support for probes that are magnetically coupled
#   to the toolhead and stowed in a dock when not in use and
#
# Copyright (C) 2018-2021  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2021       Paul McGowan <mental405@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from . import probe
from math import sin, cos, atan2, pi, radians, degrees, sqrt

PROBE_DETACH_DELAY         = .005
PROBE_VERIFY_DELAY         = .1

PROBE_UNKNOWN   = 0
PROBE_ATTACHED  = 1
PROBE_DOCKED    = 2

MULTI_OFF       = 0
MULTI_FIRST     = 1
MULTI_ON        = 2

HINT_VERIFICATION_ERROR = """
{0}: A probe state verification method
was not provided. A method to verify the probes attachment
state must be specified to prevent unintended behavior.
Please see {0}.md or config_reference.md for
valid state verification methods and examples.
"""

# Helper class to handle polling pins for probe attachment states
class PinPollingHelper:
    def __init__(self, config, endstop):
        self.printer = config.get_printer()
        self.printer.register_event_handler('klippy:connect',
                                        self._handle_connect)
        self.query_endstop = endstop
        self.last_verify_time  = 0
        self.last_verify_state = None
    def _handle_connect(self):
        self.toolhead = self.printer.lookup_object('toolhead')
    def query_pin(self, curtime):
        if (curtime > (self.last_verify_time + PROBE_VERIFY_DELAY)
            or self.last_verify_state is None):
            self.last_verify_time = curtime
            query_time = self.toolhead.get_last_move_time()
            self.last_verify_state = not not self.query_endstop(query_time)
        return self.last_verify_state
    def query_pin_inv(self, curtime):
        return not self.query_pin(curtime)

# Helper class for manually set probe attachment states
class ManualStateHelper:
    def __init__(self, config):
        self.printer = config.get_printer()
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('SET_PROBE_STATUS',
                                self.cmd_SET_PROBE_STATUS,
                                desc=self.cmd_SET_PROBE_STATUS_help)

        self.probe_state = PROBE_UNKNOWN
    cmd_SET_PROBE_STATUS_help = ("Manually specify probe status, valid probe " +
                                 "states are UNKNOWN, ATTACHED, and DOCKED")
    def cmd_SET_PROBE_STATUS(self, gcmd):
        probe_states = ['UNKNOWN', 'ATTACHED', 'DOCKED']
        state = gcmd.get('STATE').upper()
        if state in probe_states:
            self.probe_state = next(k for k, v in enumerate(probe_states)
                                     if state == v)
        else:
            e = "Invalid probe state: {0}. Valid probe states are [{1}]"
            raise gcmd.error(e.format(state, probe_states))
    def query_pin(self, curtime):
        if self.probe_state == PROBE_ATTACHED:
            return True
    def query_pin_inv(self, curtime):
        if self.probe_state == PROBE_DOCKED:
            return True

# Helper class to verify probe attachment status
class ProbeState:
    def __init__(self, config, aProbe):
        self.printer = config.get_printer()
        self.check_open_attach = config.getboolean('check_open_attach', False)
        self.probe_sense_pin = config.get('probe_sense_pin', None)
        self.dock_sense_pin = config.get('dock_sense_pin', None)
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)

        ppins = self.printer.lookup_object('pins')
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('GET_PROBE_STATUS',
                                self.cmd_GET_PROBE_STATUS,
                                self.cmd_GET_PROBE_STATUS_help)

        if not any([self.check_open_attach,
                    self.probe_sense_pin,
                    self.dock_sense_pin]):
            raise self.printer.config_error(HINT_VERIFICATION_ERROR.format(
                                            aProbe.name))
        else:
            ehelper = PinPollingHelper(config, aProbe.query_endstop)

            # Configure sense pins as endstops so they
            # can be polled at specific times
            def configEndstop(pin):
                pin_params = ppins.lookup_pin(pin,
                                              can_invert=True,
                                              can_pullup=True)
                mcu = pin_params['chip']
                mcu_endstop = mcu.setup_pin('endstop', pin_params)
                helper = PinPollingHelper(config, mcu_endstop.query_endstop)
                return helper

            probe_sense_helper = None
            dock_sense_helper = None

            if self.probe_sense_pin:
                probe_sense_helper = configEndstop(self.probe_sense_pin)
                self.probe_sense_pin = probe_sense_helper.query_pin
            else:
                self.probe_sense_pin = ehelper.query_pin_inv

            if self.dock_sense_pin:
                dock_sense_helper = configEndstop(self.dock_sense_pin)
                self.dock_sense_pin = dock_sense_helper.query_pin
            else:
                if probe_sense_helper is not None:
                    self.dock_sense_pin = probe_sense_helper.query_pin_inv
                else:
                    self.dock_sense_pin = ehelper.query_pin
    cmd_GET_PROBE_STATUS_help = ("Prints the current probe state, valid probe" +
                                 " states are UNKNOWN, ATTACHED, and DOCKED")
    def cmd_GET_PROBE_STATUS(self, gcmd):
        s = self.get_probe_state()
        state = next(v for k, v
                     in enumerate(['UNKNOWN', 'ATTACHED', 'DOCKED'])
                     if s == k)
        gcmd.respond_info('Probe Status: %s' % (state))
    def _handle_ready(self):
        self.last_verify_time = 0
        self.last_verify_state = PROBE_UNKNOWN
    def get_probe_state(self):
        curtime = self.printer.get_reactor().monotonic()
        last = self.last_verify_time
        if (self.last_verify_state == PROBE_UNKNOWN
            or curtime > self.last_verify_time + PROBE_VERIFY_DELAY):
            self.last_verify_time = curtime
            a = self.probe_sense_pin(curtime)
            d = self.dock_sense_pin(curtime)
            if a and not d:
                self.last_verify_state = PROBE_ATTACHED
            elif d and not a:
                self.last_verify_state = PROBE_DOCKED
            else:
                self.last_verify_state = PROBE_UNKNOWN
        return self.last_verify_state

class DockableProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.name = config.get_name()

        # Configuration Options
        self.position_endstop = config.getfloat('z_offset')
        self.x_offset = config.getfloat('x_offset', 0.)
        self.y_offset = config.getfloat('y_offset', 0.)
        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.lift_speed = config.getfloat('lift_speed', self.speed, above=0.)
        self.dock_retries = config.getint('dock_retries', 0) + 1
        self.travel_speed = config.getfloat('travel_speed',
                                             self.speed, above=0.)
        self.attach_speed = config.getfloat('attach_speed',
                                             self.travel_speed, above=0.)
        self.detach_speed = config.getfloat('detach_speed',
                                             self.travel_speed, above=0.)
        self.dock_fixed_z = config.getboolean('dock_fixed_z', False)
        self.allow_delayed_detach = config.getboolean('allow_delayed_detach',
                                                       False)
        self.sample_retract_dist = config.getfloat('sample_retract_dist', 2.,
                                                   above=0.)

        def parseCoord(name, c=3):
            try:
                p = [None] * 3
                val = config.get(name, None)
                if not val:
                    return None
                p[0:c] = map(lambda x: float(x.strip()),
                             val.split(','))[0:c]
            except:
                e = "Unable to parse {0} in {1}"
                raise config.error(e.format(self.name, name))
            return p

        self.approach_position = parseCoord('approach_position')
        self.detach_position   = parseCoord('detach_position')
        self.dock_position     = parseCoord('dock_position')
        self.safe_z_position   = parseCoord('safe_z_position', 2)

        self.dock_angle, self.approach_distance = self._get_vector(
                                                        self.dock_position,
                                                        self.approach_position)
        self.detach_angle, self.detach_distance = self._get_vector(
                                                        self.dock_position,
                                                        self.detach_position)

        #Pins
        ppins = self.printer.lookup_object('pins')
        pin = config.get('pin')
        pin_params = ppins.lookup_pin(pin, can_invert=True, can_pullup=True)
        mcu = pin_params['chip']
        mcu.register_config_callback(self._build_config)
        self.mcu_endstop = mcu.setup_pin('endstop', pin_params)

        # Wrappers
        self.get_mcu              = self.mcu_endstop.get_mcu
        self.add_stepper          = self.mcu_endstop.add_stepper
        self.get_steppers         = self.mcu_endstop.get_steppers
        self.home_wait            = self.mcu_endstop.home_wait
        self.query_endstop        = self.mcu_endstop.query_endstop
        self.finish_home_complete = self.wait_trigger_complete = None

        pstate = ProbeState(config, self)
        self.get_probe_state = pstate.get_probe_state

        #Custom User Macros
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        self.pre_attach_gcode = gcode_macro.load_template(
            config, 'pre_attach_gcode', '')
        self.attach_gcode = gcode_macro.load_template(
            config, 'attach_gcode', '')
        self.post_attach_gcode = gcode_macro.load_template(
            config, 'post_attach_gcode', '')
        self.pre_detach_gcode = gcode_macro.load_template(
            config, 'pre_detach_gcode', '')
        self.detach_gcode = gcode_macro.load_template(
            config, 'detach_gcode', '')
        self.post_detach_gcode = gcode_macro.load_template(
            config, 'post_detach_gcode', '')

        #Gcode Commands
        self.gcode.register_command('ATTACH_PROBE',
                                    self.cmd_ATTACH_PROBE)
        self.gcode.register_command('DETACH_PROBE',
                                    self.cmd_DETACH_PROBE)

        #Event Handlers
        self.printer.register_event_handler('klippy:connect',
                                            self._handle_connect)
        self.printer.register_event_handler('klippy:ready',
                                            self._handle_ready)
        self.printer.register_event_handler('homing:home_rails_begin',
                                            self._handle_homing_rails_begin)
        self.printer.register_event_handler('homing:home_rails_end',
                                            self._handle_homing_rails_end)

    def _build_config(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('z'):
                self.add_stepper(stepper)
        endstops = [es for rail in kin.rails
                    for es, name in rail.get_endstops()]
        if self in endstops and self.printer.lookup_object('safe_z_home', None):
            e = ("{0}: cannot be used with safe_z_home if " +
                "probe is used as z endstop")
            raise self.printer.config_error(e.format(self.name))
    def _handle_connect(self):
        self.toolhead = self.printer.lookup_object('toolhead')
    def _handle_ready(self):
        self.last_z = -9999
        self.is_z_endstop = False
        self.multi = MULTI_OFF
        self._last_homed = None
        self.init_pos = None
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        if not self.safe_z_position:
            home_xy = [0,0]
            for rail in kin.rails:
                hi = rail.get_homing_info()
                rmin, rmax = rail.get_range()
                if hi.positive_dir:
                    mid = (hi.position_endstop - rmin) *.5
                else:
                    mid = rmax * .5
                for s in rail.get_steppers():
                    a = s.get_name(short=True)
                    if a == 'x':
                        home_xy[0] = mid - self.x_offset
                    if a == 'x':
                        home_xy[1] = mid - self.y_offset
                    if a == 'z':
                        if hi.positive_dir:
                            self.z_homes_positive = True
                        else:
                            self.z_homes_positive = False
            self.safe_z_position = home_xy
    def cmd_ATTACH_PROBE(self, gcmd):
        return_pos = self.toolhead.get_position()
        self.attach_probe(return_pos)
    def cmd_DETACH_PROBE(self, gcmd):
        return_pos = self.toolhead.get_position()
        self.detach_probe(return_pos)

    #######################################################################
    # Functions for calculating points and moving the toolhead
    #######################################################################

    # Move the toolhead to minimum safe distance aligned with angle
    def _move_to_vector(self, angle):
        x, y = self._get_point_on_vector(self.dock_position[:2],
                                         angle,
                                         self.approach_distance)
        self.toolhead.manual_move([x,y,None], self.travel_speed)

    # Move the toolhead to angle within minimium safe distance
    def _align_to_vector(self, angle):
        approach = self._get_intercept(self.toolhead.get_position(),
                                       angle + (pi/2),
                                       self.dock_position,
                                       angle)
        self.toolhead.manual_move([approach[0], approach[1], None],
                                  self.attach_speed)

    # Determine toolhead distance to dock coordinates
    def _check_distance(self, pos=None, dist=None):
        if not pos:
            pos = self.toolhead.get_position()
        dock = self.dock_position

        if dist > sqrt((pos[0]-dock[0])**2 +
                       (pos[1]-dock[1])**2 ):
            return True
        else:
            return False

    # Find a point on a vector line at a specific distance
    def _get_point_on_vector(self, point, angle, magnitude=1):
        x = point[0] - magnitude * cos(angle)
        y = point[1] - magnitude * sin(angle)
        return (x, y)

    # Locate the intersection of two vectors
    def _get_intercept(self, point1, angle1, point2, angle2):
        x1, y1 = point1[:2]
        x2, y2 = self._get_point_on_vector(point1, angle1, 10.0)
        x3, y3 = point2[:2]
        x4, y4 = self._get_point_on_vector(point2, angle2, 10.0)
        det1 = ((x1 * y2) - (y1 * x2))
        det2 = ((x3 * y4) - (y3 * x4))
        d = ((x1 - x2) * (y3 - y4)) - ((y1 - y2) * (x3 - x4))
        x = float((det1 * (x3 - x4)) - ((x1 - x2) * det2)) / d
        y = float((det1 * (y3 - y4)) - ((y1 - y2) * det2)) / d
        return (x, y)

    # Determine the vector of two points
    def _get_vector(self, point1, point2):
        x1, y1 = point1[:2]
        x2, y2 = point2[:2]
        magnitude = sqrt((x2-x1)**2 + (y2-y1)**2 )
        angle = atan2(y2-y1, x2-x1) + pi

        return angle, magnitude

    # Align z axis to prevent crashes
    def _align_z(self):
        if not self._last_homed:
            curtime = self.printer.get_reactor().monotonic()
            homed_axes = self.toolhead.get_status(curtime)['homed_axes']
            self._last_homed = homed_axes
        if self.dock_fixed_z:
            dock_z = (self.dock_position[2] +
                      self.position_endstop +
                      self.sample_retract_dist)
            tpos = self.toolhead.get_position()
            if 'z' in self._last_homed:
                if tpos[2] < dock_z:
                    self.toolhead.set_position(tpos)
                    self.toolhead.manual_move(
                        [None, None, dock_z],
                        self.lift_speed)
            else:
                self._force_z_hop()
        else:
            if 'z' in self._last_homed:
                self.toolhead.manual_move(
                                        [None, None, self.dock_position[2]],
                                        self.lift_speed)
            else:
                raise self.printer.command_error(
                    "Cannot attach/detach probe, must home Z axis first")

    # Hop z and return to un-homed state
    def _force_z_hop(self):
        this_z = self.toolhead.get_position()[2]
        if self.last_z != this_z:
            tpos = self.toolhead.get_position()
            dock_z = self.dock_position[2] + self.position_endstop
            self.toolhead.set_position([tpos[0], tpos[1], 0.0, tpos[3]],
                                homing_axes=[2])
            self.toolhead.manual_move(
                [None, None, dock_z],
                self.lift_speed)
            kin = self.toolhead.get_kinematics()
            kin.note_z_not_homed()
            self.last_z = self.toolhead.get_position()[2]

    # Attaching actions
    def attach_probe(self, return_pos=None):
        self.pre_attach_gcode.run_gcode_from_command()
        if self.get_probe_state() == PROBE_DOCKED:
            self._align_z()
        if not return_pos:
            return_pos = self.init_pos
        if self._check_distance(dist=self.approach_distance):
            self._align_to_vector(self.dock_angle)
        retry = 0
        while (self.get_probe_state() != PROBE_ATTACHED
               and retry < self.dock_retries):
            self._do_attach()
            retry += 1
        if self.get_probe_state() != PROBE_ATTACHED:
            raise self.printer.command_error('Probe attach failed!')
        self.post_attach_gcode.run_gcode_from_command()
        if return_pos:
            if not self._check_distance(return_pos, self.approach_distance):
                self.toolhead.manual_move(
                    [return_pos[0], return_pos[1], None],
                    self.travel_speed)
    def _do_attach(self):
        if self.get_probe_state() != PROBE_DOCKED:
            raise self.printer.command_error(
                'Attach Probe: Probe not detected in dock, aborting')
        if self._check_distance(dist=self.approach_distance):
            self._align_to_vector(self.dock_angle)
        else:
            self._move_to_vector(self.dock_angle)
        self.toolhead.manual_move(
            [self.dock_position[0],self.dock_position[1], None],
             self.attach_speed)
        self.attach_gcode.run_gcode_from_command()
        if self._check_distance(dist=self.approach_distance):
            self._align_to_vector(self.dock_angle)
        self.toolhead.manual_move(
            [self.approach_position[0], self.approach_position[1], None],
             self.travel_speed)

    # Detaching actions
    def detach_probe(self, return_pos=None):
        self.pre_detach_gcode.run_gcode_from_command()
        if self.get_probe_state() == PROBE_ATTACHED:
            self._align_z()
        self.toolhead.manual_move(
            [self.approach_position[0], self.approach_position[1], None],
             self.travel_speed)
        retry = 0
        while (self.get_probe_state() != PROBE_DOCKED
               and retry < self.dock_retries):
            self._do_detach()
            retry += 1
        if self._check_distance(dist=self.detach_distance):
            self._align_to_vector(self.detach_angle)
            self.toolhead.manual_move(
                [self.detach_position[0], self.detach_position[1], None],
                 self.travel_speed)
        if self.get_probe_state() != PROBE_DOCKED:
            raise self.printer.command_error('Probe detach failed!')
        self.post_detach_gcode.run_gcode_from_command()
        if return_pos:
            if not self._check_distance(return_pos, self.detach_distance):
                self.toolhead.manual_move(
                    [return_pos[0], return_pos[1], None],
                    self.travel_speed)
    def _do_detach(self):
        if self._check_distance(dist=self.detach_distance):
            self._align_to_vector(self.dock_angle)
        else:
            self.toolhead.manual_move(
                [self.detach_position[0], self.detach_position[1], None],
                 self.travel_speed)
        self.toolhead.manual_move(
            [self.dock_position[0], self.dock_position[1], None],
             self.attach_speed)
        self.detach_gcode.run_gcode_from_command()
        self.toolhead.manual_move(
            [self.detach_position[0], self.detach_position[1], None],
             self.travel_speed)

    # Register a callback to detach the probe in the future if
    # no pending probing actions are queued
    def _delayed_detach(self):
        if self.init_pos:
            return_pos = self.init_pos
        else:
            return_pos = self.toolhead.get_position()
        def reactor_bgfunc(print_time):
            if self.multi == MULTI_OFF:
                with self.gcode.get_mutex():
                    self.detach_probe(return_pos)
        def lookahead_bgfunc(print_time):
            reactor = self.printer.get_reactor()
            reactor.register_callback(
                ( lambda et: reactor_bgfunc(print_time + PROBE_DETACH_DELAY )))
        self.toolhead.register_lookahead_callback(lookahead_bgfunc)

    #######################################################################
    # Events handlers
    #######################################################################
    def _handle_homing_rails_begin(self, homing_state, rails):
        homing_axes = [a for i, a in enumerate(['x','y','z'])
                        if i in homing_state.get_axes()]
        if self in [es for rail in rails for es, name in rail.get_endstops()]:
            self.is_z_endstop = True

        # Get homed axes now as they will report they are
        # homed later even if they arent
        curtime = self.printer.get_reactor().monotonic()
        self._last_homed = self.toolhead.get_status(curtime)['homed_axes']
        if self.get_probe_state() == PROBE_UNKNOWN:
                self._force_z_hop()
        if self.get_probe_state() == PROBE_ATTACHED:
            # If X and Y endstop are within the dock location,
            # Move out of the dock before attempting to home Z
            if any(a in ['x','y'] for a in homing_axes):
                self._force_z_hop()
                if 'xy' in self._last_homed:
                    if self._check_distance(self.dock_position,
                                            self.approach_distance):
                        self._align_to_vector(self.dock_angle)
                        self._move_to_vector(self.dock_angle)
            if 'z' in homing_axes:
                if self.is_z_endstop:
                    self._align_z()
                else:
                    if ('xy' in self._last_homed
                        and not self.z_homes_positive):
                        self.detach_probe(self.toolhead.get_position())
    def _handle_homing_rails_end(self, homing_state, rails):
        self.is_z_endstop = False
        self._last_homed = None

    #######################################################################
    # Probe Wrappers
    #######################################################################

    def multi_probe_begin(self):
        self.multi = MULTI_FIRST
        if not self.init_pos:
            self.init_pos = self.toolhead.get_position()
        if not self._last_homed:
            curtime = self.printer.get_reactor().monotonic()
            self._last_homed = self.toolhead.get_status(curtime)['homed_axes']
        if (self.is_z_endstop
          and self.dock_fixed_z
          and 'xy' in self._last_homed):
            self.init_pos = self.safe_z_position
        self.attach_probe()
    def multi_probe_end(self):
        self.multi = MULTI_OFF
        pos = self.toolhead.get_position()
        retract_z = (self.position_endstop + self.sample_retract_dist)
        if pos[2] < retract_z:
            self.toolhead.manual_move(
                [None,
                None,
                retract_z],
                self.lift_speed)
        if self.allow_delayed_detach:
            self._delayed_detach()
        else:
            self.detach_probe()
        self.init_pos = None
    def probe_prepare(self, hmove):
        if self.multi == MULTI_FIRST:
            self.multi = MULTI_ON
    def probe_finish(self, hmove):
        self.wait_trigger_complete.wait()
    def home_start(self, print_time, sample_time, sample_count, rest_time,
                   triggered=True):
        self.finish_home_complete = self.mcu_endstop.home_start(
            print_time, sample_time, sample_count, rest_time, triggered)
        r = self.printer.get_reactor()
        self.wait_trigger_complete = r.register_callback(self.wait_for_trigger)
        return self.finish_home_complete
    def wait_for_trigger(self, eventtime):
        self.finish_home_complete.wait()
    def get_position_endstop(self):
        return self.position_endstop

def load_config(config):
    msp = DockableProbe(config)
    config.get_printer().add_object('probe', probe.PrinterProbe(config, msp))
    return msp

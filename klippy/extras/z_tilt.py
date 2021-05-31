# Mechanical bed tilt calibration with multiple Z steppers
#
# Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import mathutil
import importlib
from . import probe

def params_to_normal_form(np, params, offsets):
    v = np.array([offsets[0], offsets[1], params['z_adjust']])
    r = np.array([1, 0, params['x_adjust']])
    s = np.array([0, 1, params['y_adjust']])
    cp = np.cross(r, s)
    return np.append(cp, np.dot(cp, v))

def intersect_3_planes(np, p1, p2, p3):
    a = np.array([p1[0:3], p2[0:3], p3[0:3]])
    b = np.array([p1[3], p2[3], p3[3]])
    sol = np.linalg.solve(a, b)
    return sol

class ZAdjustHelper:
    def __init__(self, config, z_count):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.z_count = z_count
        self.z_steppers = []
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
    def handle_connect(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        z_steppers = [s for s in kin.get_steppers() if s.is_active_axis('z')]
        if self.z_count is None:
            if len(z_steppers) != 3:
                raise self.printer.config_error(
                    "%s z_positions needs exactly 3 items for calibration"
                        % (self.name))
        elif len(z_steppers) != self.z_count:
            raise self.printer.config_error(
                "%s z_positions needs exactly %d items" % (
                    self.name, len(z_steppers)))
        if len(z_steppers) < 2:
            raise self.printer.config_error(
                "%s requires multiple z steppers" % (self.name,))
        self.z_steppers = z_steppers
    def adjust_steppers(self, adjustments, speed):
        toolhead = self.printer.lookup_object('toolhead')
        gcode = self.printer.lookup_object('gcode')
        curpos = toolhead.get_position()
        # Report on movements
        stepstrs = ["%s = %.6f" % (s.get_name(), a)
                    for s, a in zip(self.z_steppers, adjustments)]
        msg = "Making the following Z adjustments:\n%s" % ("\n".join(stepstrs),)
        gcode.respond_info(msg)
        # Disable Z stepper movements
        toolhead.flush_step_generation()
        for s in self.z_steppers:
            s.set_trapq(None)
        # Move each z stepper (sorted from lowest to highest) until they match
        positions = [(-a, s) for a, s in zip(adjustments, self.z_steppers)]
        positions.sort()
        first_stepper_offset, first_stepper = positions[0]
        z_low = curpos[2] - first_stepper_offset
        for i in range(len(positions)-1):
            stepper_offset, stepper = positions[i]
            next_stepper_offset, next_stepper = positions[i+1]
            toolhead.flush_step_generation()
            stepper.set_trapq(toolhead.get_trapq())
            curpos[2] = z_low + next_stepper_offset
            try:
                toolhead.move(curpos, speed)
                toolhead.set_position(curpos)
            except:
                logging.exception("ZAdjustHelper adjust_steppers")
                toolhead.flush_step_generation()
                for s in self.z_steppers:
                    s.set_trapq(toolhead.get_trapq())
                raise
        # Z should now be level - do final cleanup
        last_stepper_offset, last_stepper = positions[-1]
        toolhead.flush_step_generation()
        last_stepper.set_trapq(toolhead.get_trapq())
        curpos[2] += first_stepper_offset
        toolhead.set_position(curpos)

class RetryHelper:
    def __init__(self, config, error_msg_extra = ""):
        self.gcode = config.get_printer().lookup_object('gcode')
        self.default_max_retries = config.getint("retries", 0, minval=0)
        self.default_retry_tolerance = \
            config.getfloat("retry_tolerance", 0., above=0.)
        self.value_label = "Probed points range"
        self.error_msg_extra = error_msg_extra
    def start(self, gcmd):
        self.max_retries = gcmd.get_int('RETRIES', self.default_max_retries,
                                        minval=0, maxval=30)
        self.retry_tolerance = gcmd.get_float('RETRY_TOLERANCE',
                                              self.default_retry_tolerance,
                                              minval=0.0, maxval=1.0)
        self.current_retry = 0
        self.previous = None
        self.increasing = 0
    def check_increase(self, error):
        if self.previous and error > self.previous + 0.0000001:
            self.increasing += 1
        elif self.increasing > 0:
            self.increasing -= 1
        self.previous = error
        return self.increasing > 1
    def check_retry(self, z_positions):
        if self.max_retries == 0:
            return
        error = round(max(z_positions) - min(z_positions),6)
        self.gcode.respond_info(
            "Retries: %d/%d %s: %0.6f tolerance: %0.6f" % (
                self.current_retry, self.max_retries, self.value_label,
                error, self.retry_tolerance))
        if self.check_increase(error):
            raise self.gcode.error("Retries aborting: %s is increasing. %s"
                                   % (self.value_label, self.error_msg_extra))
        if error <= self.retry_tolerance:
            return "done"
        self.current_retry += 1
        if self.current_retry > self.max_retries:
            raise self.gcode.error("Too many retries")
        return "retry"

class ZTilt:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.section = config.get_name()
        try:
            self.numpy = importlib.import_module('numpy')
        except ImportError:
            logging.info("numpy not installed, Z_TILT_CALIBRATE will not be "
                "available");
            self.numpy = None
        z_positions = config.get('z_positions', None)
        z_count = None
        self.z_positions = None
        if z_positions is not None:
            z_positions = z_positions.split('\n')
            try:
                z_positions = [line.split(',', 1)
                               for line in z_positions if line.strip()]
                self.z_positions = [(float(zp[0].strip()), float(zp[1].strip()))
                                    for zp in z_positions]
                z_count = len(self.z_positions)
            except:
                raise config.error("Unable to parse z_positions in %s" % (
                    config.get_name()))
        self.retry_helper = RetryHelper(config)
        self.probe_helper = probe.ProbePointsHelper(config, self.probe_finalize)
        self.probe_helper.minimum_points(2)
        self.z_offsets = config.get('z_offsets', None)
        if (self.z_offsets is not None):
            try:
                self.z_offsets = [float(o.strip())
                                  for o in self.z_offsets.split(',')]
            except:
                raise config.error("Unable to parse z_offsets in %s" % (
                    config.get_name()))
            if (len(self.z_offsets) !=
                    len(self.probe_helper.get_probe_points())):
                raise config.error("The number of z_offsets must match the "
                    "number of probe points in %s" % (config.get_name()))
        self.z_helper = ZAdjustHelper(config, z_count)
        # probe points for calibrate/autodetect
        cal_probe_points = list(self.probe_helper.get_probe_points())
        self.num_probe_points = len(cal_probe_points)
        self.cal_helper = None
        if (config.get('extra_points', None) is not None):
            self.cal_helper = probe.ProbePointsHelper(config,
                self.cal_finalize, option_name='extra_points')
            cal_probe_points.extend(self.cal_helper.get_probe_points())
            self.cal_helper.update_probe_points(cal_probe_points, 3)
        self.ad_helper = probe.ProbePointsHelper(config, self.ad_finalize)
        self.ad_helper.update_probe_points(cal_probe_points, 3)
        self.cal_conf_avg_len = config.getint('averaging_len', 3, minval=1)
        self.ad_conf_delta = config.getfloat('autodetect_delta', 1., minval=.1)
        if (config.get('autodetect_delta', None) is not None or
            z_positions is None) and self.numpy is None:
                raise config.error(self.err_missing_numpy)
        # Register commands
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('Z_TILT_ADJUST', self.cmd_Z_TILT_ADJUST,
                               desc=self.cmd_Z_TILT_ADJUST_help)
        if (self.cal_helper is not None):
            gcode.register_command('Z_TILT_CALIBRATE',
                self.cmd_Z_TILT_CALIBRATE, desc=self.cmd_Z_TILT_CALIBRATE_help)
        gcode.register_command('Z_TILT_AUTODETECT', self.cmd_Z_TILT_AUTODETECT,
                               desc=self.cmd_Z_TILT_AUTODETECT_help)
    cmd_Z_TILT_ADJUST_help = "Adjust the Z tilt"
    cmd_Z_TILT_CALIBRATE_help = ("Calibrate Z tilt with additional probing "
        "points")
    cmd_Z_TILT_AUTODETECT_help = "Autodetect pivot point of Z motors"
    err_missing_numpy = ("Failed to import `numpy` module, make sure it was "
                    "installed via `~/klippy-env/bin/pip install`")
    def cmd_Z_TILT_ADJUST(self, gcmd):
        if (self.z_positions is None):
            gcmd.respond_info(
                "No z_positions configured. Run Z_TILT_AUTODETECT first")
            return
        self.retry_helper.start(gcmd)
        self.probe_helper.start_probe(gcmd)
    def perform_coordinate_descent(self, offsets, positions):
        # Setup for coordinate descent analysis
        z_offset = offsets[2]
        logging.info("Calculating bed tilt with: %s", positions)
        params = { 'x_adjust': 0., 'y_adjust': 0., 'z_adjust': z_offset }
        # Perform coordinate descent
        def adjusted_height(pos, params):
            x, y, z = pos
            return (z - x*params['x_adjust'] - y*params['y_adjust']
                    - params['z_adjust'])
        def errorfunc(params):
            total_error = 0.
            for pos in positions:
                total_error += adjusted_height(pos, params)**2
            return total_error
        new_params = mathutil.coordinate_descent(params.keys(), params,
            errorfunc)
        logging.info("Calculated bed tilt parameters: %s", new_params)
        return new_params
    def apply_adjustments(self, offsets, new_params):
        z_offset = offsets[2]
        speed = self.probe_helper.get_lift_speed()
        x_adjust = new_params['x_adjust']
        y_adjust = new_params['y_adjust']
        z_adjust = (new_params['z_adjust'] - z_offset
                    - x_adjust * offsets[0] - y_adjust * offsets[1])
        adjustments = [x*x_adjust + y*y_adjust + z_adjust
                       for x, y in self.z_positions]
        self.z_helper.adjust_steppers(adjustments, speed)
    def probe_finalize(self, offsets, positions):
        if self.z_offsets is not None:
            positions = [[p[0], p[1], p[2] - o]
                         for (p, o) in zip(positions, self.z_offsets)]
        new_params = self.perform_coordinate_descent(offsets, positions)
        self.apply_adjustments(offsets, new_params)
        return self.retry_helper.check_retry([p[2] for p in positions])
    def cmd_Z_TILT_CALIBRATE(self, gcmd):
        if (self.numpy is None):
            gcmd.respond_info(self.err_missing_numpy)
            return
        self.cal_avg_len = gcmd.get_int('AVGLEN', self.cal_conf_avg_len)
        self.cal_gcmd = gcmd
        self.cal_runs = []
        self.cal_helper.start_probe(gcmd)
    def cal_finalize(self, offsets, positions):
        np = self.numpy
        avlen = self.cal_avg_len
        new_params = self.perform_coordinate_descent(offsets, positions)
        self.apply_adjustments(offsets, new_params)
        self.cal_runs.append([p[2] for p in positions])
        if len(self.cal_runs) < avlen + 1:
            return "retry"
        prev_error = np.std(self.cal_runs[-avlen-1:-1], axis=0)
        prev_error = np.std(prev_error)
        this_error = np.std(self.cal_runs[-avlen:], axis=0)
        this_error = np.std(this_error)
        self.cal_gcmd.respond_info(
          "previous error: %.6f current error: %.6f" % (prev_error, this_error))
        if (this_error < prev_error):
            return "retry"
        z_offsets = np.mean(self.cal_runs[-avlen:], axis=0)
        z_offsets = [z - offsets[2] for z in z_offsets]
        self.z_offsets = z_offsets
        s_zoff = ""
        for off in z_offsets[0:self.num_probe_points]:
            s_zoff += "%.6f, " % off
        s_zoff = s_zoff[:-2]
        self.cal_gcmd.respond_info("final z_offsets are: %s" % (s_zoff))
        configfile = self.printer.lookup_object('configfile')
        section = self.section
        configfile.set(section, "z_offsets", s_zoff)
        self.cal_gcmd.respond_info(
          "The SAVE_CONFIG command will update the printer config\n"
          "file with these parameters and restart the printer.")
    def ad_init(self):
        self.ad_phase = 0
        self.ad_params = []
    def cmd_Z_TILT_AUTODETECT(self, gcmd):
        if (self.numpy is None):
            gcmd.respond_info(self.err_missing_numpy)
        self.cal_avg_len = gcmd.get_int('AVGLEN', self.cal_conf_avg_len)
        self.ad_delta = gcmd.get_float('DELTA', self.ad_conf_delta, minval=.1)
        self.ad_init()
        self.ad_gcmd = gcmd
        self.ad_runs = []
        self.ad_points = []
        self.ad_error = None
        self.ad_helper.start_probe(gcmd)
    ad_adjustments = [
        [ 0.5, -0.5, -0.5], # p1 up
        [  -1,    1,    0], # p2 up
        [   0,   -1,    1], # p3 up
        [   0,    1,    0], # p3 + p2 up
        [   1,   -1,    0], # p3 + p1 up
        [   0,    1,   -1], # p2 + p1 up
        [-0.5, -0.5,  0.5]  # back to level
    ]
    def ad_finalize(self, offsets, positions):
        np = self.numpy
        avlen = self.cal_avg_len
        delta = self.ad_delta
        speed = self.probe_helper.get_lift_speed()
        new_params = self.perform_coordinate_descent(offsets, positions)
        if self.ad_phase in range(1, 4):
            new_params['z_adjust'] -= delta / 2
        if self.ad_phase in range(4, 7):
            new_params['z_adjust'] += delta / 2
        if (self.ad_phase == 0):
            self.ad_points.append([z for _, _, z in
                                    positions[:self.num_probe_points]])
        self.ad_params.append(new_params)
        adjustments = [_a * delta for _a in self.ad_adjustments[self.ad_phase]]
        self.z_helper.adjust_steppers(adjustments, speed)
        if self.ad_phase < 6:
            self.ad_phase += 1
            return "retry"
        # calculcate results
        p = []
        for i in range(7):
            p.append(params_to_normal_form(np, self.ad_params[i], offsets))

        # This is how it works.
        # To find the pivot point, we take 3 planes:
        #  a) the original untilted plane
        #  b) the plane with one motor raised, on one corner opposite the
        #     one we want to determine the pivot point of
        #  c) the plane with the other motor opposite the one we want to
        #     determine the pivot point raised
        # The intersection of all 3 planes is a point very near the pivot
        # point we search for. If the pivot point would be a point on the
        # bed surface, we would already be done. But as the actual pivot
        # point is in most cases below the bed, the intersection of the 3
        # points is behind or in front of the actual point (in X/Y). To
        # compensate for this error, we do the same calculation again, but
        # with the planes b) and c) tilted in the opposite direction and
        # take the average of the 2 points.

        z_p1 = (intersect_3_planes(np, p[0], p[2], p[3])[:2],
                intersect_3_planes(np, p[0], p[1], p[3])[:2],
                intersect_3_planes(np, p[0], p[1], p[2])[:2])

        z_p2 = (intersect_3_planes(np, p[0], p[5], p[6])[:2],
                intersect_3_planes(np, p[0], p[4], p[6])[:2],
                intersect_3_planes(np, p[0], p[4], p[5])[:2])

        # take the average of positive and negative measurement
        z_pos = []
        for _zp1, _zp2 in zip(z_p1, z_p2):
            _z = []
            for _z1, _z2 in zip(_zp1, _zp2):
                _z.append((_z1 + _z2) / 2)
            z_pos.append(_z)
        s_zpos = ""
        for zp in z_pos:
            s_zpos += "%.6f, %.6f\n" % tuple(zp)
        self.ad_gcmd.respond_info("current estimated z_positions %s" % (s_zpos))
        self.ad_runs.append(z_pos)
        if len(self.ad_runs) >= avlen:
            self.z_positions = np.mean(self.ad_runs[-avlen:], axis=0)
        else:
            self.z_positions = np.mean(self.ad_runs, axis=0)

        # We got a first estimate of the pivot points. Now apply the
        # adjustemts to all motors and repeat the process until the result
        # converges. We determine convergence by keeping track of the last
        # <average_len> + 1 runs and compare the standard deviation over that
        # len between the last two runs. When the error stops to decrease, we
        # are done. The final z_positions are determined by calculating the
        # average over the last <average_len> calculated positions.

        self.apply_adjustments(offsets, self.ad_params[0])
        if len(self.ad_runs) >= avlen:
            errors = np.std(self.ad_runs[-avlen:], axis=0)
            error = np.std(errors)
            if self.ad_error is None:
                self.ad_gcmd.respond_info("current error: %.6f" % (error))
            else:
                self.ad_gcmd.respond_info(
                    "previous error: %.6f current error: %.6f"
                    % (self.ad_error, error))
            if (self.ad_error is not None):
                if error >= self.ad_error:
                    self.ad_finalize_done(offsets)
                    return
            self.ad_error = error
        # restart
        self.ad_init()
        return "retry"
    def ad_finalize_done(self, offsets):
        np = self.numpy
        avlen = self.cal_avg_len
        # calculate probe point z offsets
        z_offsets = np.mean(self.ad_points[-avlen:], axis=0)
        z_offsets = [z - offsets[2] for z in z_offsets]
        self.z_offsets = z_offsets
        logging.info("final z_offsets %s", (z_offsets))
        configfile = self.printer.lookup_object('configfile')
        section = self.section
        s_zoff = ""
        for off in z_offsets:
            s_zoff += "%.6f, " % off
        s_zoff = s_zoff[:-2]
        configfile.set(section, "z_offsets", s_zoff)
        s_zpos = ""
        for zpos in self.z_positions:
            s_zpos += "%.6f, %.6f\n" % tuple(zpos)
        configfile.set(section, "z_positions", s_zpos)
        self.ad_gcmd.respond_info("final z_positions are %s" % (s_zpos))
        self.ad_gcmd.respond_info("final z_offsets are: %s" % (s_zoff))
        self.ad_gcmd.respond_info(
          "The SAVE_CONFIG command will update the printer config\n"
          "file with these parameters and restart the printer.")

def load_config(config):
    return ZTilt(config)

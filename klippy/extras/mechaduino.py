# Support for mechaduino style "servo steppers"
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math
import chelper, stepper
from . import bus

UPDATE_TIME = 1. / 6000
CALIBRATION_COUNT = 32


######################################################################
# Low-level mcu wrappers
######################################################################

# Stepper motor h-bridge driver
class MCU_a4954:
    def __init__(self, config):
        self.printer = config.get_printer()
        # pin config
        ppins = self.printer.lookup_object('pins')
        pins = [ppins.lookup_pin(config.get(name + '_pin'))
                for name in ['in1', 'in2', 'in3', 'in4', 'vref12', 'vref34']]
        mcu = None
        for pin_params in pins:
            if mcu is not None and pin_params['chip'] != mcu:
                raise ppins.error("mechaduino: all pins must be on same mcu")
            mcu = pin_params['chip']
        self.pins = [pin_params['pin'] for pin_params in pins]
        self.mcu = mcu
        self.oid = self.mcu.create_oid()
        self.mcu.add_config_cmd(
            "config_a4954 oid=%d in1_pin=%s in2_pin=%s in3_pin=%s in4_pin=%s"
            " vref12_pin=%s vref34_pin=%s"
            % (self.oid, self.pins[0], self.pins[1],
               self.pins[2], self.pins[3], self.pins[4], self.pins[5]))
        # Current control
        sense_resistor = config.getfloat('sense_resistor', above=0.)
        vref = config.getfloat('voltage_reference', 3.3, above=0.)
        self.current_factor = 10. * sense_resistor / vref
        self.max_current = config.getfloat('current', above=0., maxval=2.)
        self.pwm_max = 0.
        self.mcu.register_config_callback(self._build_config)
    def _build_config(self):
        self.pwm_max = self.mcu.get_constant_float("PWM_MAX")
    def get_mcu(self):
        return self.mcu
    def get_oid(self):
        return self.oid
    def get_current_scale(self, current=None):
        if current is None:
            current = self.max_current
        current = max(0., min(self.max_current, current))
        return int(current * self.current_factor * self.pwm_max)

# Virtual stepper position tracking class
# XXX - this is a hack to emulate MCU_stepper
class MCU_virtual_stepper(stepper.MCU_stepper):
    def __init__(self, mcu, name, step_dist):
        dummy_pin_params = {'chip': mcu, 'pin': None, 'invert': False}
        stepper.MCU_stepper.__init__(self, name, dummy_pin_params,
                                     dummy_pin_params, step_dist)
        self.setup_itersolve('cartesian_stepper_alloc', 'x') # XXX
    def _build_config(self):
        mcu = self._mcu
        mcu.add_config_cmd("config_virtual_stepper oid=%d" % (self._oid,))
        self._mcu.add_config_cmd("virtual_reset_step_clock oid=%d clock=0"
                                 % (self._oid,), on_restart=True)
        step_cmd_tag = self._mcu.lookup_command_tag(
            "virtual_queue_step oid=%c interval=%u count=%hu add=%hi")
        dir_cmd_tag = self._mcu.lookup_command_tag(
            "virtual_set_next_step_dir oid=%c dir=%c")
        self._reset_cmd_tag = self._mcu.lookup_command_tag(
            "virtual_reset_step_clock oid=%c clock=%u")
        self._get_position_cmd = self._mcu.lookup_query_command(
            "virtual_stepper_get_position oid=%c",
            "stepper_position oid=%c pos=%i", oid=self._oid)
        self._stop_on_trigger_cmd = self._mcu.lookup_command(
            "virtual_stepper_stop_on_trigger oid=%c trsync_oid=%c")
        max_error = self._mcu.get_max_stepper_error()
        ffi_main, ffi_lib = chelper.get_ffi()
        ffi_lib.stepcompress_fill(self._stepqueue,
                                  self._mcu.seconds_to_clock(max_error),
                                  self._invert_dir, step_cmd_tag, dir_cmd_tag)
    def get_oid(self):
        return self._oid

# Servo stepper feedback control code
class MCU_servo_stepper:
    def __init__(self, config, stepper_driver, mcu_vstepper):
        self.mcu = stepper_driver.get_mcu()
        self.stepper_driver = stepper_driver
        self.mcu_vstepper = mcu_vstepper
        self.oid = self.mcu.create_oid()
        self.full_steps_per_rotation = config.getint('full_steps_per_rotation',
                                                     200, minval=4)
        # Commands
        self.disabled_cmd = self.open_loop_mode_cmd = None
        self.torque_mode_cmd = None
        self.mcu.register_config_callback(self._build_config)
    def get_oid(self):
        return self.oid
    def get_full_steps_per_rotation(self):
        return self.full_steps_per_rotation
    def _build_config(self):
        cmd_queue = self.mcu.alloc_command_queue()
        self.mcu.add_config_cmd(
            "config_servo_stepper oid=%d driver_oid=%d stepper_oid=%d"
            " full_steps_per_rotation=%d"
            % (self.oid, self.stepper_driver.get_oid(),
               self.mcu_vstepper.get_oid(), self.full_steps_per_rotation))
        self.disabled_cmd = self.mcu.lookup_command(
            "servo_stepper_set_disabled oid=%c", cq=cmd_queue)
        self.open_loop_mode_cmd = self.mcu.lookup_command(
            "servo_stepper_set_open_loop_mode oid=%c current_scale=%u",
            cq=cmd_queue)
        self.torque_mode_cmd = self.mcu.lookup_command(
            "servo_stepper_set_torque_mode oid=%c"
            " excite_angle=%u current_scale=%u",
            cq=cmd_queue)
    def set_disabled(self, print_time):
        clock = self.mcu.print_time_to_clock(print_time)
        self.disabled_cmd.send([self.oid], minclock=clock, reqclock=clock)
    def set_open_loop_mode(self, print_time):
        clock = self.mcu.print_time_to_clock(print_time)
        current_scale = self.stepper_driver.get_current_scale()
        self.open_loop_mode_cmd.send([self.oid, current_scale],
                                     minclock=clock, reqclock=clock)
    def set_torque_mode(self, print_time, excite_angle, current):
        clock = self.mcu.print_time_to_clock(print_time)
        current_scale = self.stepper_driver.get_current_scale(current)
        self.torque_mode_cmd.send([self.oid, excite_angle, current_scale],
                                  minclock=clock, reqclock=clock)

# SPI controlled hall position sensor
class MCU_spi_position:
    def __init__(self, config, control):
        self.control = control
        self.printer = config.get_printer()
        # Sensor type
        sensors = { "a1333": (3, 10000000),
                    "as5047d": (1, int(1. / .000000350)) }
        self.sensor_type = config.getchoice('sensor_type',
                                            {s: s for s in sensors})
        spi_mode, spi_speed = sensors[self.sensor_type]
        # SPI bus configuration
        self.spi = bus.MCU_SPI_from_config(
            config, spi_mode, pin_option="sensor_pin", default_speed=spi_speed)
        self.mcu = self.spi.get_mcu()
        # Sensor chip configuration
        self.oid = self.mcu.create_oid()
        # Commands
        self.update_clock = 0
        self.query_pos_cmd = self.set_calibration_cmd = None
        self.mcu.register_config_callback(self._build_config)
        # Position storage
        self.positions = []
    def _build_config(self):
        self.mcu.add_config_cmd(
            "config_spi_position oid=%d spi_oid=%d spiposition_type=%s"
            " servo_stepper_oid=%d"
            % (self.oid, self.spi.get_oid(), self.sensor_type,
               self.control.get_oid()))
        clock = self.mcu.get_query_slot(self.oid)
        self.update_clock = self.mcu.seconds_to_clock(UPDATE_TIME)
        self.mcu.add_config_cmd(
            "schedule_spi_position oid=%u clock=%u rest_ticks=%u"
            % (self.oid, clock, self.update_clock), is_init=True)
        cmd_queue = self.spi.get_command_queue()
        self.query_pos_cmd = self.mcu.lookup_command(
            "query_last_spi_position oid=%c", cq=cmd_queue)
        self.set_calibration_cmd = self.mcu.lookup_command(
            "set_spi_position_calibration oid=%c index=%u value=%hu",
            cq=cmd_queue)
        self.mcu.register_response(self._handle_spi_position_result,
                                   "spi_position_result", self.oid)
    def _handle_spi_position_result(self, params):
        next_clock = self.mcu.clock32_to_clock64(params['next_clock'])
        last_read_clock = next_clock - self.update_clock
        last_read_time = self.mcu.clock_to_print_time(last_read_clock)
        position = params['position']
        self.positions.append((last_read_time, position))
    def query_position(self, print_time):
        clock = self.mcu.print_time_to_clock(print_time)
        self.query_pos_cmd.send([self.oid], minclock=clock, reqclock=clock)
    def get_clear_positions(self):
        pos = self.positions
        self.positions = []
        return list(pos)
    def apply_calibration(self, print_time, calibration):
        for i, cal in enumerate(calibration):
            if self.set_calibration_cmd is None:
                self.mcu.add_config_cmd(
                    "set_spi_position_calibration oid=%d index=%d value=%d"
                    % (self.oid, i, cal), is_init=True)
            else:
                clock = self.mcu.print_time_to_clock(print_time)
                self.set_calibration_cmd.send([self.oid, i, cal],
                                              minclock=clock, reqclock=clock)


######################################################################
# Calibration
######################################################################

class ServoCalibration:
    def __init__(self, config, mcu_vstepper, servo_stepper, spi_position):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.mcu_vstepper = mcu_vstepper
        self.servo_stepper = servo_stepper
        self.spi_position = spi_position
        self.load_calibration(config)
        # Register commands
        servo_name = config.get_name().split()[1]
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command("SERVO_CALIBRATE", "SERVO", servo_name,
                                   self.cmd_SERVO_CALIBRATE,
                                   desc=self.cmd_SERVO_CALIBRATE_help)
    def get_base_calibration(self):
        bucket_size = 65536 // CALIBRATION_COUNT
        return [i*bucket_size for i in range(CALIBRATION_COUNT)]
    def calc_calibration_error(self, calibration, angles):
        # Determine angle deviation given a calibration table
        bucket_size = 65536 // CALIBRATION_COUNT
        nominal_angle = 65536. / len(angles)
        out = []
        for step, angle in enumerate(angles):
            angle = int(angle + .5)
            bucket = angle // bucket_size
            cal1 = calibration[bucket]
            cal_diff = calibration[(bucket + 1) % CALIBRATION_COUNT] - cal1
            cal_diff = ((cal_diff + 32768) % 65536) - 32768
            adj = ((angle % bucket_size)*cal_diff + bucket_size//2)//bucket_size
            out.append((cal1 + adj) - step*nominal_angle)
        return out
    def get_calibration(self, angles):
        # Calculate a calibration table from a list of full-step angles
        bucket_size = 65536 // CALIBRATION_COUNT
        calibration = self.get_base_calibration()
        best_error = 99999999.
        while 1:
            angle_errs = self.calc_calibration_error(calibration, angles)
            total_error = sum([abs(e) for e in angle_errs])
            if total_error >= best_error:
                return calibration
            buckets = {}
            for angle, angle_err in zip(angles, angle_errs):
                bucket = int(angle + .5) // bucket_size
                buckets.setdefault(bucket, []).append(angle_err)
            new_calibration = []
            for i in range(CALIBRATION_COUNT):
                data = buckets[i] + buckets[(i-1) % CALIBRATION_COUNT]
                cal = calibration[i] - int(sum(data) / float(len(data)) + .5)
                new_calibration.append(cal)
            calibration = new_calibration
            best_error = total_error
    def load_calibration(self, config):
        cal = config.get('calibrate', None)
        if cal is None:
            self.reset_calibration(0.)
            return
        # Parse calibration data
        data = [d.strip() for d in cal.split(',')]
        angles = [float(d) for d in data if d]
        # Calculate and apply calibration data
        calibration = self.get_calibration(angles)
        self.spi_position.apply_calibration(0., calibration)
    def reset_calibration(self, print_time):
        bc = self.get_base_calibration()
        self.spi_position.apply_calibration(print_time, bc)
    cmd_SERVO_CALIBRATE_help = "Calibrate the servo stepper"
    def cmd_SERVO_CALIBRATE(self, gcmd):
        self.spi_position.get_clear_positions()
        full_steps = self.servo_stepper.get_full_steps_per_rotation()
        # Go into open loop mode
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        self.servo_stepper.set_open_loop_mode(print_time)
        self.reset_calibration(print_time)
        # Start with a dummy movement
        fmove = self.printer.lookup_object('force_move')
        step_dist = self.mcu_vstepper.get_step_dist()
        full_step_dist = step_dist * 256
        move_time = 0.100
        move_speed = full_step_dist / move_time
        fmove.manual_move(self.mcu_vstepper, 16. * -full_step_dist, move_speed)
        # Move to each full step position and then query the sensor
        steps = []
        for i in range(full_steps - 1, -1, -1):
            fmove.manual_move(self.mcu_vstepper, -full_step_dist, move_speed)
            start_query_time = toolhead.get_last_move_time() + 0.050
            for j in range(10):
                self.spi_position.query_position(start_query_time + j*0.010)
            end_query_time = start_query_time + 10 * 0.010
            steps.append((i, start_query_time, end_query_time))
            toolhead.dwell(0.050 + end_query_time - start_query_time)
        self.servo_stepper.set_disabled(toolhead.get_last_move_time())
        toolhead.wait_moves()
        # Correlate query responses
        cal = {}
        positions = self.spi_position.get_clear_positions()
        step = 0
        for query_time, pos in positions:
            while step < len(steps) and query_time > steps[step][2]:
                step += 1
            if step < len(steps) and query_time >= steps[step][1]:
                cal.setdefault(steps[step][0], []).append(pos & 0xffff)
        # Calculate each step position average and variance
        total_count = total_variance = 0
        angles = {}
        for step, data in cal.items():
            count = len(data)
            angle_avg = float(sum(data)) / count
            angles[step] = angle_avg
            total_count += count
            total_variance += sum([(d - angle_avg)**2 for d in data])
        # Validate data
        angles_to_step = {a: s for s, a in angles.items()}
        if len(angles_to_step) != full_steps:
            raise gcmd.error("Failed calibration - didn't find %d unique steps"
                             % (full_steps,))
        min_step = angles_to_step[min(angles_to_step)]
        inc_angles = []
        for i in range(full_steps):
            inc_angles.append(angles[(i + min_step) % full_steps])
        msg = "mechaduino calibration: Stddev=%.3f (%d of %d queries)" % (
            math.sqrt(total_variance / total_count), total_count,
            full_steps * 10)
        logging.info(msg)
        gcmd.respond_info(msg)
        # Save results
        cal_contents = []
        for i, angle in enumerate(inc_angles):
            if not i % 8:
                cal_contents.append('\n')
            cal_contents.append("%.1f" % (angle,))
            cal_contents.append(',')
        cal_contents.pop()
        configfile = self.printer.lookup_object('configfile')
        configfile.remove_section(self.name)
        configfile.set(self.name, 'calibrate', ''.join(cal_contents))
        configfile.set(self.name, 'calibrate_start_step', '%d' % (min_step,))


######################################################################
# Main wrapper
######################################################################

class PrinterMechaduino:
    def __init__(self, config):
        self.printer = config.get_printer()
        servo_name = config.get_name().split()[1]
        self.a4954 = MCU_a4954(config)
        rotation_dist = config.getfloat('rotation_distance', above=0.)
        full_steps = config.getint('full_steps_per_rotation', 200)
        step_dist = rotation_dist / full_steps
        self.mcu_vstepper = MCU_virtual_stepper(self.a4954.get_mcu(),
                                                servo_name, step_dist / 256.)
        stepper_enable = self.printer.load_object(config, 'stepper_enable')
        stepper_enable.register_virtual_stepper(self.mcu_vstepper, self)
        force_move = self.printer.load_object(config, 'force_move')
        force_move.register_stepper(self.mcu_vstepper)
        self.servo_stepper = MCU_servo_stepper(config, self.a4954,
                                               self.mcu_vstepper)
        self.spi_position = MCU_spi_position(config, self.servo_stepper)
        ServoCalibration(config, self.mcu_vstepper, self.servo_stepper,
                         self.spi_position)
        # Register commands
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command("SET_TORQUE_MODE", "SERVO", servo_name,
                                   self.cmd_SET_TORQUE_MODE,
                                   desc=self.cmd_SET_TORQUE_MODE_help)
    def get_mcu_stepper(self):
        return self.mcu_vstepper
    def set_enable(self, print_time):
        # XXX - may need to reset virtual stepper position
        self.servo_stepper.set_open_loop_mode(print_time)
    def set_disable(self, print_time):
        self.servo_stepper.set_disabled(print_time)
    cmd_SET_TORQUE_MODE_help = "Place servo in torque mode"
    def cmd_SET_TORQUE_MODE(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        excite = gcmd.get_int("EXCITE", 64)
        current = gcmd.get_float("CURRENT")
        if not current:
            self.servo_stepper.set_disabled(print_time)
        else:
            self.servo_stepper.set_torque_mode(print_time, excite, current)

def load_config_prefix(config):
    return PrinterMechaduino(config)

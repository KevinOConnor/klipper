# Support a fan for cooling the MCU whenever a stepper or heater is on
#
# Copyright (C) 2019  Nils Friedchen <nils.friedchen@googlemail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import fan

PIN_MIN_TIME = 0.100

class ControllerFan:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.stepper_names = []
        self.stepper_enable = self.printer.load_object(config, 'stepper_enable')
        self.printer.load_object(config, 'heaters')
        self.heaters = []
        self.fan = fan.Fan(config)
        self.fan_speed = config.getfloat('fan_speed', default=1.,
                                         minval=0., maxval=1.)
        self.idle_speed = config.getfloat(
            'idle_speed', default=self.fan_speed, minval=0., maxval=1.)
        self.idle_timeout = config.getint("idle_timeout", default=30, minval=0)
        self.heater_name = config.get("heater", "extruder")
        self.last_on = self.idle_timeout
        self.last_speed = 0.
        self.temperature_sensor_targets = {}
        self.conf_temperature_sensor_targets = {}
        sensors = config.get("temperature_sensors", "").strip()
        if sensors:
            if sensors.endswith(','):
                sensors = sensors[:-1]
            parts = [a.split(':', 1) for a in sensors.split(',')]
            for pair in parts:
                if len(pair) != 2:
                    raise self.printer.error(
                        "Unable to parse temperature_sensors in %s"
                        % (config.get_name(),))
                name, value = [s.strip() for s in pair]
                self.conf_temperature_sensor_targets[name] = float(value)

                gcode = self.printer.lookup_object('gcode')
                gcode.register_mux_command(
                    "SET_CONTROLLER_FAN_TARGET", "TEMPERATURE_SENSOR", name,
                    self.cmd_SET_CONTROLLER_FAN_TARGET,
                    desc=self.cmd_SET_CONTROLLER_FAN_TARGET_help)

    def handle_ready(self):
        pheaters = self.printer.lookup_object('heaters')
        self.heaters = [pheaters.lookup_heater(n.strip())
                        for n in self.heater_name.split(',')]
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        self.stepper_names = [s.get_name() for s in kin.get_steppers()]
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.callback, reactor.monotonic()+PIN_MIN_TIME)
        for k, v in self.conf_temperature_sensor_targets.items():
            sensor = self.printer.lookup_object('temperature_sensor ' + k.strip())
            if sensor is None:
                raise self.printer.error(
                    "'%s' is not a valid temperature_sensor." % (k,))
            self.temperature_sensor_targets[sensor] = v
    def get_status(self, eventtime):
        return self.fan.get_status(eventtime)
    def callback(self, eventtime):
        speed = 0.
        active = False
        for name in self.stepper_names:
            active |= self.stepper_enable.lookup_enable(name).is_motor_enabled()
        for heater in self.heaters:
            _, target_temp = heater.get_temp(eventtime)
            if target_temp:
                active = True
        for sensor, target in self.temperature_sensor_targets.items():
            current_temp, _ = sensor.get_temp(eventtime)
            if current_temp > target:
                active = True
        if active:
            self.last_on = 0
            speed = self.fan_speed
        elif self.last_on < self.idle_timeout:
            speed = self.idle_speed
            self.last_on += 1
        if speed != self.last_speed:
            self.last_speed = speed
            curtime = self.printer.get_reactor().monotonic()
            print_time = self.fan.get_mcu().estimated_print_time(curtime)
            self.fan.set_speed(print_time + PIN_MIN_TIME, speed)
        return eventtime + 1.

    def set_target_temp(self, sensor_name, degrees):
        sensor = self.printer.lookup_object('temperature_sensor ' + sensor_name)
        min_temp, max_temp = sensor.get_min_max()
        if degrees and (degrees < min_temp or degrees > max_temp):
            raise self.printer.command_error(
                "Requested temperature (%.1f) out of range (%.1f:%.1f)"
                % (degrees, min_temp, max_temp))
        self.temperature_sensor_targets[sensor] = degrees

    cmd_SET_CONTROLLER_FAN_TARGET_help = \
        "Sets a temperature sensor target"
    def cmd_SET_CONTROLLER_FAN_TARGET(self, gcmd):
        params = gcmd.get_command_parameters()
        sensor = gcmd.get('TEMPERATURE_SENSOR')
        temp = gcmd.get_float('TARGET',
            self.conf_temperature_sensor_targets[sensor])
        self.set_target_temp(sensor, temp)

def load_config_prefix(config):
    return ControllerFan(config)

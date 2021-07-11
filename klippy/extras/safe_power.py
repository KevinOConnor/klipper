# Stepper Driver Anti-SNAFU Protection support
#
# Copyright (C) 2021  Lars R. Hansen <popshansen@hotmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

SF_INVERT_STEP = 1<<2

class Safe_Power:
    def __init__(self, config):
        self.name = config.get_name()
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        ppins = self.printer.lookup_object('pins')
        pin_params = ppins.lookup_pin(config.get('pin'))
        self.mcu = pin_params['chip']
        self.oid = self.mcu.create_oid()
        self.pin = pin_params['pin']
        self.mcu_pin = self.mcu.setup_pin('digital_out', pin_params)
        self.mcu_pin.setup_start_value(0, 0, False)
        self.set_digital_out_cmd = self.read_digital_in_cmd = None
        self.steppers = {}
        for s in config.get_prefix_sections('stepper_'):
            self._register_stepper(s, ppins)
        for s in config.get_prefix_sections('extruder'):
            self._register_stepper(s, ppins)
        for s in config.get_prefix_sections('manual_stepper'):
            self._register_stepper(s, ppins)
        if config.has_section('dual_carriage'):
            self._register_stepper(config.getsection('dual_carriage'), ppins)
        #Check config order
        for name, obj in self.printer.lookup_objects():
            if name.startswith('tmc'):
               raise self.printer.config_error(
                     "[%s] section should be before"
                     " any tmc section in printer.cfg" % (self.name,))
        self.mcu.register_config_callback(self._build_config)
        self.printer.register_event_handler("klippy:connect",
                                            self._connect)
    def _build_config(self):
        self.set_digital_out_cmd = self.mcu.lookup_command(
            "set_digital_out pin=%u value=%c")
        self.read_digital_in_cmd = self.mcu.lookup_query_command(
            "read_digital_in pin=%u pull_up=%c",
            "read_digital_in_value pin=%u value=%c")
    def _connect(self):
        ucmd = self.set_digital_out_cmd.send
        res = None
        # Disabling mcu power
        ucmd([self.pin, 0])
        if len(self.steppers) > 0:
            logging.info("%s starting checks for stepper"
                         " driver backwards" % (self.name,))
            for stepper in self.steppers.values():
                res = self._check_driver(stepper)
                if res is not None:
                    break
        if res is not None:
            raise self.printer.command_error(res)
        else:
            # Enabling mcu power
            ucmd([self.pin, 1])
    def _register_stepper(self, config, ppins):
        name = config.get_name()
        enable_pin = config.get('enable_pin', None, note_valid=False)
        step_pin = config.get('step_pin', None, note_valid=False)
        # Only register stepper driver with enable and step pins
        if enable_pin is not None and step_pin is not None:
            enable_pin_params = ppins.parse_pin(enable_pin, can_invert=True)
            step_pin_params = ppins.parse_pin(step_pin, can_invert=True)
            # Only register stepper driver belongs to current mcu
            if (step_pin_params['chip'] is self.mcu
                    and enable_pin_params['chip'] is self.mcu):
                self.steppers[name] = StepperTracking(
                    name, step_pin_params, enable_pin_params)
    def _check_driver(self, stepper):
        logging.info("Checking [%s]" % (stepper.name,))
        res = None
        # Reconfig stepper driver pins
        curtime = self.reactor.monotonic()
        print_time = self.mcu.estimated_print_time(curtime)
        minclock = self.mcu.print_time_to_clock(print_time + .100)
        self.set_digital_out_cmd.send([stepper.step_pin_params['pin'],0],
                                      minclock=minclock)
        # Do the stepper driver check
        minclock = self.mcu.print_time_to_clock(print_time + .200)
        params = self.read_digital_in_cmd.send(
            [stepper.enable_pin_params['pin'],0], minclock=minclock)
        if params['value'] == 0:
            res = ("[%s] driver is backward!"
                   % (stepper.name,))
        # Restore stepper driver pins
        step_flags = SF_INVERT_STEP if stepper.step_pin_params['invert'] else 0
        self.set_digital_out_cmd.send([stepper.step_pin_params['pin'],
                                      step_flags & SF_INVERT_STEP])
        enable_flags = stepper.enable_pin_params['invert']
        self.set_digital_out_cmd.send([stepper.enable_pin_params['pin'],
                                      (not not enable_flags)])
        return res

class StepperTracking:
    def __init__(self, name, step_pin_params, enable_pin_params):
        self.name = name
        self.step_pin_params = step_pin_params
        self.enable_pin_params = enable_pin_params

def load_config_prefix(config):
    return Safe_Power(config)

def load_config(config):
    return Safe_Power(config)

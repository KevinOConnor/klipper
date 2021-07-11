# Code for supporting multiple steppers in single filament extruder.
#
# Copyright (C) 2019 Simo Apell <simo.apell@live.fi>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import stepper

class ExtruderStepper:
    def __init__(self, config):
        self.printer = config.get_printer()
        stepper_name = config.get_name().split()[1]
        self.extruder_name = config.get('extruder', 'extruder')
        self.synced_extruder = None
        self.stepper = stepper.PrinterStepper(config)
        self.stepper.setup_itersolve('extruder_stepper_alloc')
        stepper_enable = self.printer.load_object(config, 'stepper_enable')
        stepper_enable.register_stepper(self.stepper,
                                        config.get('enable_pin', None))
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command("SYNC_STEPPER_TO_EXTRUDER", "STEPPER",
                                   stepper_name,
                                   self.cmd_SYNC_STEPPER_TO_EXTRUDER,
                                   desc=self.cmd_SYNC_STEPPER_TO_EXTRUDER_help)
    def handle_connect(self):
        self.synced_extruder = self.printer.lookup_object(self.extruder_name)
        self.synced_extruder.sync_stepper(self.stepper)
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.register_step_generator(self.stepper.generate_steps)
    cmd_SYNC_STEPPER_TO_EXTRUDER_help = "Set extruder stepper"
    def cmd_SYNC_STEPPER_TO_EXTRUDER(self, gcmd):
        ename = gcmd.get('EXTRUDER')
        extruder = self.printer.lookup_object(ename, None)
        if extruder is None:
            raise gcmd.error("'%s' is not a valid extruder." % (ename,))
        if self.synced_extruder is not None:
            self.synced_extruder.unsync_stepper(self.stepper)
        self.synced_extruder = extruder
        self.synced_extruder.sync_stepper(self.stepper)
        self.extruder_name = ename
        gcmd.respond_info("Extruder stepper now syncing with '%s'" % (ename,))

def load_config_prefix(config):
    return ExtruderStepper(config)

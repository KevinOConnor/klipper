# Support generic temperature sensors
#
# Copyright (C) 2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from .heaters import TemperatureSensor

class PrinterSensorGeneric(TemperatureSensor):
    def __init__(self, config):
        super(PrinterSensorGeneric, self).__init__(config)
        pheaters = self.printer.load_object(config, 'heaters')
        pheaters.register_sensor(config, self)

def load_config_prefix(config):
    return PrinterSensorGeneric(config)

# Support for filament width sensor
#
# Copyright (C) 2019  Mustafa YILDIZ <mydiz@hotmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import filament_switch_sensor
import logging
from time import strftime

ADC_REPORT_TIME = 0.500
ADC_SAMPLE_TIME = 0.001
ADC_SAMPLE_COUNT = 8

class FilamentWidthSensor:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.pin = config.get('pin')
        self.nominal_filament_dia = config.getfloat(
            'default_nominal_filament_diameter', above=1.0)
        self.measurement_delay = config.getfloat('measurement_delay', above=0.)
        # Logging on/off
        self.is_log = config.getboolean('logging', True)
        # Enable extrusion modifier and/or use sensor as Runout switch only
        self.extrude_factor_enable = config.getboolean(
            'extrude_factor_enable', False)
        # Set measurement interval
        self.measurement_interval_mm = config.getint('measurement_interval', 10)
        # Calibration of sensor: y=mx+b,
        # Filament width = adc_value * slope + offset
        self.measurement_offset = config.getfloat('offset_mm', 0)
        self.measurement_slope = config.getfloat('slope', 1)
        # Filament diameter variation,
        # that does NOT cause the flow rate to be modified 
        # (for imprecise filament sensors)
        self.measurement_difference_max = config.getfloat(
            'difference_max', 0)
        self.measurement_difference_min = config.getfloat(
            'difference_min',0)
        self.max_diameter = (self.nominal_filament_dia
                             + self.measurement_difference_max)
        self.min_diameter = (self.nominal_filament_dia
                             - self.measurement_difference_min)
        self.is_active = True
        # filament array [position, filamentWidth]
        self.filament_array = []
        self.lastFilamentWidthReading = 0
        # Diameter to trigger Filament Runout/Clog in mm
        self.runout_dia = config.getfloat('runout_width', 0.1)
        self.clog_dia = config.getfloat('clog_width', 5)
        # printer objects
        self.toolhead = self.ppins = self.mcu_adc = None
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        # Start adc
        self.ppins = self.printer.lookup_object('pins')
        self.mcu_adc = self.ppins.setup_pin('adc', self.pin)
        self.mcu_adc.setup_minmax(ADC_SAMPLE_TIME, ADC_SAMPLE_COUNT)
        self.mcu_adc.setup_adc_callback(ADC_REPORT_TIME, self.adc_callback)
        # extrude factor updating
        self.extrude_factor_update_timer = self.reactor.register_timer(
            self.extrude_factor_update_event)
        # Register commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('QUERY_FILAMENT_WIDTH', self.cmd_M407)
        self.gcode.register_command('QUERY_RAW_FILAMENT_WIDTH',
                                    self.cmd_QueryRawFilament)
        self.gcode.register_command('RESET_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_ClearFilamentArray)
        self.gcode.register_command('DISABLE_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_M406)
        self.gcode.register_command('ENABLE_FILAMENT_WIDTH_SENSOR',
                                    self.cmd_M405)
        # Runout helper
        self.runout_helper = filament_switch_sensor.RunoutHelper(config)
        # Logging
        self.gcode.register_command('ENABLE_FILAMENT_WIDTH_LOG',
                                        self.cmd_log_enable)
        self.gcode.register_command('DISABLE_FILAMENT_WIDTH_LOG',
                                        self.cmd_log_disable)

    # Initialization
    def handle_ready(self):
        # Load printer objects
        self.toolhead = self.printer.lookup_object('toolhead')

        # Start extrude factor update timer
        self.reactor.update_timer(self.extrude_factor_update_timer,
                                  self.reactor.NOW)

    def adc_callback(self, read_time, read_value):
        # read sensor value
        # Filament width = acd-value * slope + offset, y=mx+b
        self.RawFilamentWidth = round(read_value, 2)
        self.lastFilamentWidthReading = round((read_value 
            * self.measurement_slope) + self.measurement_offset, 2)

    def update_filament_array(self, last_epos):
        # Fill array
        if len(self.filament_array) > 0:
            # Get last reading position in array & calculate next
            # reading position
            next_reading_position = (self.filament_array[-1][0]
                                     + self.measurement_interval_mm)
            if next_reading_position <= (last_epos + self.measurement_delay):
                self.filament_array.append([last_epos + self.measurement_delay,
                                            self.lastFilamentWidthReading])
              # Logging
                if self.is_log:
                    with open("/tmp/width.log", "a") as width_log:
                        width_log.write(strftime("%a, %d %b %Y %H:%M:%S")
                            + " Filament dia: "
                            + str(self.lastFilamentWidthReading) + " mm\n")
        else:
            # add first item to array
            self.filament_array.append([self.measurement_delay + last_epos,
                                        self.lastFilamentWidthReading])

    def extrude_factor_update_event(self, eventtime):
        # Update extrude factor
        pos = self.toolhead.get_position()
        last_epos = pos[3]
        # Update filament array for lastFilamentWidthReading
        self.update_filament_array(last_epos)
        # Check runout/clog
        self.runout_helper.note_filament_present(
            self.lastFilamentWidthReading > self.runout_dia)
        self.runout_helper.note_filament_present(
            self.lastFilamentWidthReading < self.clog_dia)

        # Is extrusion modifier enabled
        if self.extrude_factor_enable:
            # Does filament exists
            if self.lastFilamentWidthReading > 0.5:
                if len(self.filament_array) > 0:
                    # Get first position in filament array
                    pending_position = self.filament_array[0][0]
                    if  pending_position <= last_epos:
                        # Get first item in filament_array queue
                        item = self.filament_array.pop(0)
                        filament_width = item[1]
                        if ( (filament_width >= self.max_diameter)
                            or (filament_width <= self.min_diameter)):
                            percentage = round(self.nominal_filament_dia**2
                                           / filament_width**2 * 100)
                            self.gcode.run_script("M221 S" + str(percentage))
                        else:
                            self.gcode.run_script("M221 S100")
            else:
                self.gcode.run_script("M221 S100")
                self.filament_array = []

        if self.is_active:
            return eventtime + 1
        else:
            return self.reactor.NEVER

    def cmd_M407(self, gcmd):
        response = ""
        if self.lastFilamentWidthReading > 0:
            response += ("Filament dia (measured mm): "
                         + str(self.lastFilamentWidthReading))
            with open("/tmp/width.log", "a") as width_log:
                width_log.write(strftime("%a, %d %b %Y %H:%M:%S")
                    + " Query Filament dia: "
                    + str(self.lastFilamentWidthReading) + " mm\n")
        else:
            response += "Filament NOT present"
        gcmd.respond_info(response)

    def cmd_ClearFilamentArray(self, gcmd):
        self.filament_array = []
        gcmd.respond_info("Filament width measurements cleared!")
        # Set extrude multiplier to 100%
        self.gcode.run_script_from_command("M221 S100")

    def cmd_M405(self, gcmd):
        response = "Filament width sensor Turned On"
        if self.is_active:
            response = "Filament width sensor is already On"
        else:
            self.is_active = True
            # Start extrude factor update timer
            self.reactor.update_timer(self.extrude_factor_update_timer,
                                      self.reactor.NOW)
        gcmd.respond_info(response)

    def cmd_M406(self, gcmd):
        response = "Filament width sensor Turned Off"
        if not self.is_active:
            response = "Filament width sensor is already Off"
        else:
            self.is_active = False
            # Stop extrude factor update timer
            self.reactor.update_timer(self.extrude_factor_update_timer,
                                      self.reactor.NEVER)
            # Clear filament array
            self.filament_array = []
            # Set extrude multiplier to 100%
            self.gcode.run_script_from_command("M221 S100")
        gcmd.respond_info(response)

    def cmd_log_enable(self, gcmd):
        self.is_log = True
        gcmd.respond_info("Filament width logging Turned On")

    def cmd_log_disable(self, gcmd):
        self.is_log = False
        gcmd.respond_info("Filament width logging Turned Off")

    def cmd_QueryRawFilament(self, gcmd):
         gcmd.respond_info("Raw filament dia (measured mm): "
                         + str(self.RawFilamentWidth))

def load_config(config):
    return FilamentWidthSensor(config)

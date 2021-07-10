# Support for Raspberry Pi DHT22 temperature sensor
#
# Copyright (C) 2021  Joshua Wherrett <thejoshw.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import time

MIN_SAMPLE_TIME = 2
SAMPLE_MULTIPLIER = 10
SAMPLE_TIME = MIN_SAMPLE_TIME * SAMPLE_MULTIPLIER
RPI_PROC_TEMP_FILE = "/tmp/please/specify/a/valid/path"

class DHT22:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.name = config.get_name().split()[-1]
        self.temp_path = config.get("temp_path", RPI_PROC_TEMP_FILE)
        self.humidity_path = config.get("humidity_path", RPI_PROC_TEMP_FILE)

        self.temp = self.min_temp = self.max_temp = self.humidity = 0.0

        self.printer.add_object("dht22 " + self.name, self)
        if self.printer.get_start_args().get('debugoutput') is not None:
            return
        self.sample_timer = self.reactor.register_timer(
            self._sample_sensor)
        try:
            self.temp_file_handle = open(self.temp_path, "r")
        except:
            raise config.error("Unable to open temperature file '%s'"
                               % (self.temp_path,))
        try:
            self.humidity_file_handle = open(self.humidity_path, "r")
        except:
            raise config.error("Unable to open humidity file '%s'"
                               % (self.humidity_path,))

        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)

    def handle_connect(self):
        self.reactor.update_timer(self.sample_timer, self.reactor.NOW)

    def setup_minmax(self, min_temp, max_temp):
        self.min_temp = min_temp
        self.max_temp = max_temp

    def setup_callback(self, cb):
        self._callback = cb

    def get_report_time_delta(self):
        return SAMPLE_TIME

    def _sample_sensor(self, eventtime):
        for count in range(SAMPLE_MULTIPLIER - 1):
            try:
                self.temp_file_handle.seek(0)
                self.temp = float(self.temp_file_handle.read())/1000.0
                self.humidity_file_handle.seek(0)
                self.humidity = float(self.humidity_file_handle.read())/1000.0
            except Exception:
                # Failed sample, try again after min sample time
                time.sleep(MIN_SAMPLE_TIME)
            else:
                break
        else:
            logging.exception("DHT22: Error reading data")
            self.temp = 0.0
            self.humidity = 0.0
            return self.reactor.NEVER

        if self.temp < self.min_temp:
            self.printer.invoke_shutdown(
                "DHT22 temperature %0.1f below minimum temperature of %0.1f."
                % (self.temp, self.min_temp,))
        if self.temp > self.max_temp:
            self.printer.invoke_shutdown(
                "DHT22 temperature %0.1f above maximum temperature of %0.1f."
                % (self.temp, self.max_temp,))

        mcu = self.printer.lookup_object('mcu')
        measured_time = self.reactor.monotonic()
        self._callback(mcu.estimated_print_time(measured_time), self.temp)
        return measured_time + SAMPLE_TIME

    def get_status(self, eventtime):
        return {
            'temperature': self.temp,
            'humidity': self.humidity
        }


def load_config(config):
    # Register sensor
    pheaters = config.get_printer().load_object(config, "heaters")
    pheaters.add_sensor_factory("dht22", DHT22)

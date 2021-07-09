# TMC2660 configuration
#
# Copyright (C) 2018-2019  Florian Heilmann <Florian.Heilmann@gmx.net>
# Copyright (C) 2019-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math, logging
from . import bus, tmc, tmc2130

Registers = {
    "DRVCONF": 0xE, "SGCSCONF": 0xC, "SMARTEN": 0xA,
    "CHOPCONF": 0x8, "DRVCTRL": 0x0
}

ReadRegisters = [ "READRSP@RDSEL0", "READRSP@RDSEL1", "READRSP@RDSEL2" ]

Fields = {}

Fields["DRVCTRL"] = {
    "MRES": 0x0f,
    "DEDGE": 0x01 << 8,
    "intpol": 0x01 << 9,
}

Fields["CHOPCONF"] = {
    "toff": 0x0f,
    "HSTRT": 0x7 << 4,
    "HEND": 0x0f << 7,
    "HDEC": 0x03 << 11,
    "RNDTF": 0x01 << 13,
    "CHM": 0x01 << 14,
    "TBL": 0x03 << 15
}

Fields["SMARTEN"] = {
    "semin" : 0x0f,
    "seup": 0x03 << 5,
    "semax": 0x0f << 8,
    "sedn": 0x03 << 13,
    "seimin": 0x01 << 15
}

Fields["SGCSCONF"] = {
    "CS": 0x1f,
    "sgt": 0x7F << 8,
    "sfilt": 0x01 << 16
}

Fields["DRVCONF"] = {
    "RDSEL": 0x03 << 4,
    "VSENSE": 0x01 << 6,
    "SDOFF": 0x01 << 7,
    "TS2G": 0x03 << 8,
    "DISS2G": 0x01 << 10,
    "SLPL": 0x03 << 12,
    "SLPH": 0x03 << 14,
    "TST": 0x01 << 16
}

Fields["READRSP@RDSEL0"] = {
    "stallGuard": 0x01 << 4,
    "ot": 0x01 << 5,
    "otpw": 0x01 << 6,
    "s2ga": 0x01 << 7,
    "s2gb": 0x01 << 8,
    "ola": 0x01 << 9,
    "olb": 0x01 << 10,
    "stst": 0x01 << 11,
    "MSTEP": 0x3ff << 14
}

Fields["READRSP@RDSEL1"] = {
    "stallGuard": 0x01 << 4,
    "ot": 0x01 << 5,
    "otpw": 0x01 << 6,
    "s2ga": 0x01 << 7,
    "s2gb": 0x01 << 8,
    "ola": 0x01 << 9,
    "olb": 0x01 << 10,
    "stst": 0x01 << 11,
    "SG_RESULT": 0x3ff << 14
}

Fields["READRSP@RDSEL2"] = {
    "stallGuard": 0x01 << 4,
    "ot": 0x01 << 5,
    "otpw": 0x01 << 6,
    "s2ga": 0x01 << 7,
    "s2gb": 0x01 << 8,
    "ola": 0x01 << 9,
    "olb": 0x01 << 10,
    "stst": 0x01 << 11,
    "SE": 0x1f << 14,
    "SG_RESULT@RDSEL2": 0x1f << 19
}

SignedFields = ["sgt"]

FieldFormatters = dict(tmc2130.FieldFormatters)
FieldFormatters.update({
    "DEDGE": (lambda v: "1(Both Edges Active!)" if v else ""),
    "CHM": (lambda v: "1(constant toff)" if v else "0(spreadCycle)"),
    "VSENSE": (lambda v: "1(165mV)" if v else "0(305mV)"),
    "SDOFF": (lambda v: "1(Step/Dir disabled!)" if v else ""),
    "DISS2G": (lambda v: "1(Short to GND disabled!)" if v else ""),
    "SE": (lambda v: ("%d" % v) if v else "0(Reset?)"),
})


######################################################################
# TMC stepper current config helper
######################################################################

MAX_CURRENT = 2.400

class TMC2660CurrentHelper:
    def __init__(self, config, mcu_tmc):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.mcu_tmc = mcu_tmc
        self.fields = mcu_tmc.get_fields()
        self.current = config.getfloat('run_current', minval=0.1,
                                       maxval=MAX_CURRENT)
        self.sense_resistor = config.getfloat('sense_resistor')
        vsense, cs = self._calc_current(self.current)
        self.fields.set_field("CS", cs)
        self.fields.set_field("VSENSE", vsense)

        # Register ready/printing handlers
        self.idle_current_percentage = config.getint(
            'idle_current_percent', default=100, minval=0, maxval=100)
        if self.idle_current_percentage < 100:
            self.printer.register_event_handler("idle_timeout:printing",
                                                self._handle_printing)
            self.printer.register_event_handler("idle_timeout:ready",
                                                self._handle_ready)

    def _calc_current_bits(self, current, vsense):
        vref = 0.165 if vsense else 0.310
        cs = int(32 * current * self.sense_resistor * math.sqrt(2.) / vref
                 - 1. + .5)
        return max(0, min(31, cs))

    def _calc_current(self, run_current):
        vsense = False
        cs = self._calc_current_bits(run_current, vsense)
        if cs < 16:
            vsense = True
            cs = self._calc_current_bits(run_current, vsense)
        return vsense, cs

    def _handle_printing(self, print_time):
        print_time -= 0.100 # Schedule slightly before deadline
        self.printer.get_reactor().register_callback(
            (lambda ev: self._update_current(self.current, print_time)))

    def _handle_ready(self, print_time):
        current = self.current * float(self.idle_current_percentage) / 100.
        self.printer.get_reactor().register_callback(
            (lambda ev: self._update_current(current, print_time)))

    def _update_current(self, current, print_time):
        vsense, cs = self._calc_current(current)
        val = self.fields.set_field("CS", cs)
        self.mcu_tmc.set_register("SGCSCONF", val, print_time)
        # Only update VSENSE if we need to
        if vsense != self.fields.get_field("VSENSE"):
            val = self.fields.set_field("VSENSE", vsense)
            self.mcu_tmc.set_register("DRVCONF", val, print_time)

    def get_current(self):
        return self.current, None, MAX_CURRENT

    def set_current(self, run_current, hold_current, print_time):
        self.current = run_current
        self._update_current(run_current, print_time)


######################################################################
# TMC2660 SPI
######################################################################

# Helper code for working with TMC2660 devices via SPI
class MCU_TMC2660_SPI:
    def __init__(self, config, name_to_reg, fields):
        self.printer = config.get_printer()
        self.mutex = self.printer.get_reactor().mutex()
        self.spi = bus.MCU_SPI_from_config(config, 0, default_speed=4000000)
        self.name_to_reg = name_to_reg
        self.fields = fields
    def get_fields(self):
        return self.fields
    def get_register(self, reg_name):
        new_rdsel = ReadRegisters.index(reg_name)
        reg = self.name_to_reg["DRVCONF"]
        if self.printer.get_start_args().get('debugoutput') is not None:
            return 0
        with self.mutex:
            old_rdsel = self.fields.get_field("RDSEL")
            val = self.fields.set_field("RDSEL", new_rdsel)
            msg = [((val >> 16) | reg) & 0xff, (val >> 8) & 0xff, val & 0xff]
            if new_rdsel != old_rdsel:
                # Must set RDSEL value first
                self.spi.spi_send(msg)
            params = self.spi.spi_transfer(msg)
        pr = bytearray(params['response'])
        return (pr[0] << 16) | (pr[1] << 8) | pr[2]
    def set_register(self, reg_name, val, print_time=None):
        minclock = 0
        if print_time is not None:
            minclock = self.spi.get_mcu().print_time_to_clock(print_time)
        reg = self.name_to_reg[reg_name]
        msg = [((val >> 16) | reg) & 0xff, (val >> 8) & 0xff, val & 0xff]
        with self.mutex:
            self.spi.spi_send(msg, minclock)


######################################################################
# TMC2660 printer object
######################################################################

class TMC2660:
    def __init__(self, config):
        # Setup mcu communication
        self.fields = tmc.FieldHelper(Fields, SignedFields, FieldFormatters)
        self.fields.set_field("SDOFF", 0) # Access DRVCTRL in step/dir mode
        self.mcu_tmc = MCU_TMC2660_SPI(config, Registers, self.fields)
        # Register commands
        current_helper = TMC2660CurrentHelper(config, self.mcu_tmc)
        cmdhelper = tmc.TMCCommandHelper(config, self.mcu_tmc, current_helper)
        cmdhelper.setup_register_dump(ReadRegisters)
        tmc.TMCHomingCurrentHelper(config, self.mcu_tmc, current_helper)
        # DRVCTRL
        mh = tmc.TMCMicrostepHelper(config, self.mcu_tmc)
        self.get_microsteps = mh.get_microsteps
        self.get_phase = mh.get_phase
        # CHOPCONF
        set_config_field = self.fields.set_config_field
        set_config_field(config, "TBL", 2)
        set_config_field(config, "RNDTF", 0)
        set_config_field(config, "HDEC", 0)
        set_config_field(config, "CHM", 0)
        set_config_field(config, "HEND", 3)
        set_config_field(config, "HSTRT", 3)
        set_config_field(config, "toff", 4)
        if not self.fields.get_field("CHM"):
            if (self.fields.get_field("HSTRT") +
                self.fields.get_field("HEND")) > 15:
                raise config.error("driver_HEND + driver_HSTRT must be <= 15")
        # SMARTEN
        set_config_field(config, "seimin", 0)
        set_config_field(config, "sedn", 0)
        set_config_field(config, "semax", 0)
        set_config_field(config, "seup", 0)
        set_config_field(config, "semin", 0)
        # SGSCONF
        set_config_field(config, "sfilt", 0)
        set_config_field(config, "sgt", 0)
        # DRVCONF
        set_config_field(config, "SLPH", 0)
        set_config_field(config, "SLPL", 0)
        set_config_field(config, "DISS2G", 0)
        set_config_field(config, "TS2G", 3)

def load_config_prefix(config):
    return TMC2660(config)

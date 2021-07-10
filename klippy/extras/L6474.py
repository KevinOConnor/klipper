# L6474 configuration
#
# Copyright (C) 2020-2021  HOUIDAR Oussama
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import math
import logging
from . import bus, L647x, tmc


commands = {"CMD_ENABLE": 0xB8, "CMD_DISABLE": 0xA8,
            "CMD_GET_STATUS": 0xd0, "CMD_GET_PARAM": 0x20}


Registers = {

    "ABS_POS": 0x01,
    "EL_POS": 0x02,
    "MARK": 0x03,
    "TVAL": 0x09,
    "T_FAST": 0x0E,
    "TON_MIN": 0x0F,
    "TOFF_MIN": 0x10,
    "ADC_OUT": 0x12,
    "OCD_TH": 0x13,
    "STEP_MODE": 0x16,
    "ALARM_EN": 0x17,
    "CONFIG": 0x18,
    "STATUS": 0x19,
    "CMD_DISABLE": 0xA8,
    "CMD_ENABLE": 0xB8,
    "CMD_GET_STATUS": 0xd0
}


Fields = {}

Fields["CONFIG"] = {

    "OSC_SEL": 7 << 0,
    "EXT_CLK": 1 << 3,
    "EN_TQREG": 1 << 5,
    "OC_SD": 1 << 7,
    "POW_SR": 3 << 8,
    "TOFF": 0x1f << 10

}

Fields["TVAL"] = {"TVAL": 0x7f}

Fields["OCD_TH"] = {"OCD_TH": 0xf}

Fields["TON_MIN"] = {"TON_MIN": 0x7f}

Fields["TOFF_MIN"] = {"TOFF_MIN": 0x7f}

Fields["STATUS"] = {

    "HiZ": 1 << 0,
    "DIR": 1 << 4,
    "NOTPERF_CMD": 1 << 7,
    "WRONG_CMD": 1 << 8,
    "UVLO": 1 << 9,
    "TH_WRN": 1 << 10,
    "TH_SD": 1 << 11,
    "OCD": 1 << 12

}

Fields["STEP_MODE"] = {

    "STEP_SEL": 0xf,
    "SYNC_SEL": 0xf << 4

}

Fields["T_FAST"] = {

    "FAST_STEP": 0xf << 0,
    "TOFF_FAST": 0Xf << 4

}

Fields["EL_POS"] = {
    "MICROSTEP": 0x7f,
    "STEP": 0x3 << 7
}

Fields["ALARM_EN"] = {
    "over_current": 1,
    "thermal_shut": 1 << 1,
    "thermal_warn": 1 << 2,
    "under_voltage": 1 << 3,
    "switch": 1 << 6,
    "wrong": 1 << 7
}

SignedFields = ["ABS_POS", "MARK"]


FieldFormatters = {}


######################################################################
# L647x stepper current config helper
######################################################################

class L647xCurrentHelper:
    def __init__(self, config, mcu_L647x):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.mcu_L647x = mcu_L647x
        self.fields = mcu_L647x.get_fields()
        tval_current = config.getfloat('driver_TVAL', maxval=4000)
        ocd_current = config.getfloat('driver_OCD_TH', maxval=6000)
        self.fields.set_field("TVAL", self._calc_tval_bits(tval_current))
        self.fields.set_field("OCD_TH", self._calc_ocd_bits(ocd_current))

    def _calc_tval_bits(self, current):
        tval = int((current / 31.25)) - 1
        return (tval & 0x7f)

    def _calc_ocd_bits(self, current):
        ocd = int(current / 375) - 1
        return (ocd & 0x0f)

    def _calc_tval_current_from_field(self, field_name):
        bits = self.fields.get_field(field_name)
        return (bits + 1) * 31.25

    def _calc_ocd_current_from_field(self, field_name):
        bits = self.fields.get_field(field_name)
        return (bits + 1) * 375

    def get_current_tval(self):
        return self._calc_tval_current_from_field("TVAL")

    def get_current_ocd(self):
        return self._calc_ocd_current_from_field("OCD_TH")

    def set_current_tval(self, tval_current, print_time):
        tval = self._calc_tval_bits(tval_current)
        self.fields.set_field("TVAL", tval)
        self.mcu_L647x.set_register("TVAL", tval, print_time)

    def set_current_ocd(self, ocd_current, print_time):
        ocd = self._calc_tval_bits(ocd_current)
        self.fields.set_field("OCD_TH", ocd)
        self.mcu_L647x.set_register("OCD_TH", ocd, print_time)


######################################################################
# L6474 SPI
######################################################################

class MCU_L647x_SPI_chain:
    def __init__(self, config, chain_len=1):
        self.printer = config.get_printer()
        self.chain_len = chain_len
        self.mutex = self.printer.get_reactor().mutex()
        share = None
        if chain_len > 1:
            share = "L647x_spi_cs"
        self.spi = bus.MCU_SPI_from_config(config, 3, default_speed=4000000,
                                           share_type=share)
        self.taken_chain_positions = []

    def _build_cmd(self, data, chain_pos):
        return ([0x00] * (self.chain_len - chain_pos) +
                data + [0x00] * (chain_pos - 1))

    def reg_read(self, reg_name, reg, chain_pos):
        if reg_name in ["ABS_POS", "MARK"]:
            respNum = 3
        elif reg_name in ["EL_POS", "CONFIG", "STATUS", "CMD_GET_STATUS"]:
            respNum = 2
        else:
            respNum = 1

        if (reg_name == "CMD_GET_STATUS"):
            data = self._build_cmd([reg & 0xff], chain_pos)
            params = self.spi.spi_transfer(data)
        else:
            params = self.spi.spi_transfer(self._build_cmd(
                [(reg & 0x1f) | commands["CMD_GET_PARAM"]], chain_pos))

        resp = 0x000000
        for i in range(respNum, 0, -1):
            params = self.spi.spi_transfer(self._build_cmd([0x00], chain_pos))
            pr = bytearray(params['response'])
            pr = pr[self.chain_len - chain_pos]
            resp = resp | (pr << (i - 1) * 8)
        return resp

    def reg_write(self, reg_name, val, chain_pos, print_time=None):
        spiTX = []
        minclock = 0
        reg = Registers[reg_name]
        if print_time is not None:
            minclock = self.spi.get_mcu().print_time_to_clock(print_time)
        if reg_name in ["ABS_POS", "MARK"]:
            spiTX = [reg] + [(val >> 16) & 0xff] \
                + [(val >> 8) & 0xff] + [val & 0xff]
        elif reg_name in ["EL_POS", "CONFIG"]:
            spiTX = [reg] + [(val >> 8) & 0xff] + [val & 0xff]
        elif reg_name in ["CMD_ENABLE" or "CMD_DISABLE"]:
            spiTX = [reg]
        else:
            spiTX = [reg] + [val & 0xff]
        for i in spiTX:
            self.spi.spi_send(self._build_cmd([i], chain_pos), minclock)

# Helper to setup an spi daisy chain bus from settings in a config section
def lookup_L647x_spi_chain(config):
    chain_len = config.getint('chain_length', None, minval=2)
    if chain_len is None:
        # Simple, non daisy chained SPI connection
        return MCU_L647x_SPI_chain(config, 1), 1

    # Shared SPI bus - lookup existing MCU_L647x_SPI_chain
    ppins = config.get_printer().lookup_object("pins")
    cs_pin_params = ppins.lookup_pin(config.get('cs_pin'),
                                     share_type="L647x_spi_cs")
    L647x_spi = cs_pin_params.get('class')
    if L647x_spi is None:
        L647x_spi = cs_pin_params['class'] \
            = MCU_L647x_SPI_chain(config, chain_len)
    if chain_len != L647x_spi.chain_len:
        raise config.error("L647x SPI chain must have same length")
    chain_pos = config.getint('chain_position', minval=1, maxval=chain_len)
    if chain_pos in L647x_spi.taken_chain_positions:
        raise config.error("L647x SPI chain can not have duplicate position")
    L647x_spi.taken_chain_positions.append(chain_pos)
    return L647x_spi, chain_pos

# Helper code for working with L647x devices via SPI
class MCU_L647x_SPI:
    def __init__(self, config, name_to_reg, fields):
        self.printer = config.get_printer()
        self.L647x_spi, self.chain_pos = lookup_L647x_spi_chain(config)
        self.mutex = self.L647x_spi.mutex
        self.name_to_reg = name_to_reg
        self.fields = fields

    def get_fields(self):
        return self.fields

    def get_commands(self):
        return commands

    def get_register(self, reg_name):
        reg = self.name_to_reg[reg_name]
        with self.mutex:
            read = self.L647x_spi.reg_read(reg_name, reg, self.chain_pos)
        return read

    def set_register(self, reg_name, val, print_time=None):
        with self.mutex:
            self.L647x_spi.reg_write(reg_name, val, self.chain_pos, print_time)


######################################################################
# L6474 printer object
######################################################################

class L6474:
    def __init__(self, config):
        # Setup mcu communication
        self.fields = tmc.FieldHelper(Fields, SignedFields, FieldFormatters)
        self.mcu_L647x = MCU_L647x_SPI(config, Registers, self.fields)
        # Register commands
        current_helper = L647xCurrentHelper(config, self.mcu_L647x)
        cmdhelper = L647x.L647xCommandHelper(config, self.mcu_L647x,
                                             current_helper, clear_gstat=False)
        cmdhelper.setup_register_dump(Registers)

        # Allow other registers to be set from the config
        set_config_field = self.fields.set_config_field
        set_config_field(config, "TVAL", 20)
        set_config_field(config, "TOFF_FAST", 3)
        set_config_field(config, "FAST_STEP", 5)
        set_config_field(config, "TON_MIN", 5)
        set_config_field(config, "TOFF_MIN", 21)
        set_config_field(config, "OCD_TH", 2)
        set_config_field(config, "STEP_SEL", 12)
        set_config_field(config, "SYNC_SEL", 8)
        # Alarm Enable Register "
        set_config_field(config, "over_current", 1)
        set_config_field(config, "thermal_shut", 1)
        set_config_field(config, "thermal_warn", 1)
        set_config_field(config, "under_voltage", 1)
        set_config_field(config, "switch", 1)
        set_config_field(config, "wrong", 1)
        # Config Register
        set_config_field(config, "OSC_SEL", 0)
        set_config_field(config, "EXT_CLK", 0)
        set_config_field(config, "EN_TQREG", 0)
        set_config_field(config, "OC_SD", 1)
        set_config_field(config, "POW_SR", 0)
        set_config_field(config, "TOFF", 11)


def load_config_prefix(config):
    return L6474(config)

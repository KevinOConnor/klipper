# TMC2209 configuration
#
# Copyright (C) 2019  Stephan Oelze <stephan.oelze@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import tmc2208, tmc2130, tmc, tmc_uart

TMC_FREQUENCY=12000000.

Registers = dict(tmc2208.Registers)
Registers.update({
    "TCOOLTHRS":    0x14,
    "COOLCONF":     0x42,
    "SGTHRS":       0x40,
    "SG_RESULT":    0x41
})

ReadRegisters = tmc2208.ReadRegisters + ["SG_RESULT"]

Fields = dict(tmc2208.Fields)
Fields["COOLCONF"] = {
    "semin":        0x0F << 0,
    "seup":         0x03 << 5,
    "semax":        0x0F << 8,
    "sedn":         0x03 << 13,
    "seimin":       0x01 << 15
}
Fields["IOIN"] = {
    "ENN":          0x01 << 0,
    "MS1":          0x01 << 2,
    "MS2":          0x01 << 3,
    "DIAG":         0x01 << 4,
    "PDN_UART":     0x01 << 6,
    "STEP":         0x01 << 7,
    "SPREAD_EN":    0x01 << 8,
    "DIR":          0x01 << 9,
    "VERSION":      0xff << 24
}
Fields["SGTHRS"] = {
    "SGTHRS":       0xFF << 0
}
Fields["SG_RESULT"] = {
    "SG_RESULT":    0x3FF << 0
}
Fields["TCOOLTHRS"] = {
    "TCOOLTHRS": 0xfffff
}

FieldFormatters = dict(tmc2208.FieldFormatters)


######################################################################
# TMC2209 printer object
######################################################################

class TMC2209:
    def __init__(self, config):
        # Setup mcu communication
        self.fields = tmc.FieldHelper(Fields, tmc2208.SignedFields,
                                      FieldFormatters)
        self.mcu_tmc = tmc_uart.MCU_TMC_uart(config, Registers, self.fields, 3)
        # Allow virtual pins to be created
        tmc.TMCVirtualPinHelper(config, self.mcu_tmc, TMC_FREQUENCY)
        # Register commands
        current_helper = tmc2130.TMCCurrentHelper(config, self.mcu_tmc)
        cmdhelper = tmc.TMCCommandHelper(config, self.mcu_tmc, current_helper)
        cmdhelper.setup_register_dump(ReadRegisters)
        tmc.TMCHomingCurrentHelper(config, self.mcu_tmc, current_helper)
        # Setup basic register values
        self.fields.set_field("pdn_disable", True)
        self.fields.set_field("mstep_reg_select", True)
        self.fields.set_field("multistep_filt", True)
        mh = tmc.TMCMicrostepHelper(config, self.mcu_tmc)
        self.get_microsteps = mh.get_microsteps
        self.get_phase = mh.get_phase
        tmc.TMCStealthchopHelper(config, self.mcu_tmc, TMC_FREQUENCY)
        tmc.TMCcoolStepHelper(config, self.mcu_tmc, TMC_FREQUENCY)
        # Allow other registers to be set from the config
        set_config_field = self.fields.set_config_field
        # CHOPCONF
        set_config_field(config, "toff", 3)
        set_config_field(config, "hstrt", 5)
        set_config_field(config, "hend", 0)
        set_config_field(config, "TBL", 2)
        set_config_field(config, "diss2g", 0)
        set_config_field(config, "diss2vs", 0)
        # COOLCONF
        set_config_field(config, "semin", 0)
        set_config_field(config, "seup", 0)
        set_config_field(config, "semax", 0)
        set_config_field(config, "sedn", 0)
        set_config_field(config, "seimin", 0)
        # IHOLDIRUN
        set_config_field(config, "IHOLDDELAY", 8)
        # PWMCONF
        set_config_field(config, "PWM_OFS", 36)
        set_config_field(config, "PWM_GRAD", 14)
        set_config_field(config, "pwm_freq", 1)
        set_config_field(config, "pwm_autoscale", 1)
        set_config_field(config, "pwm_autograd", 1)
        set_config_field(config, "freewheel", 0)
        set_config_field(config, "PWM_REG", 8)
        set_config_field(config, "PWM_LIM", 12)
        # TPOWERDOWN
        set_config_field(config, "TPOWERDOWN", 20)
        # SGTHRS
        set_config_field(config, "SGTHRS", 0)


def load_config_prefix(config):
    return TMC2209(config)

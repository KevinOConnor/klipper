# TMC2208 UART communication and configuration
#
# Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
from . import tmc, tmc_uart, tmc2130

TMC_FREQUENCY=12000000.

Registers = {
    "GCONF": 0x00, "GSTAT": 0x01, "IFCNT": 0x02, "SLAVECONF": 0x03,
    "OTP_PROG": 0x04, "OTP_READ": 0x05, "IOIN": 0x06, "FACTORY_CONF": 0x07,
    "IHOLD_IRUN": 0x10, "TPOWERDOWN": 0x11, "TSTEP": 0x12, "TPWMTHRS": 0x13,
    "VACTUAL": 0x22, "MSCNT": 0x6a, "MSCURACT": 0x6b, "CHOPCONF": 0x6c,
    "DRV_STATUS": 0x6f, "PWMCONF": 0x70, "PWM_SCALE": 0x71, "PWM_AUTO": 0x72
}

ReadRegisters = [
    "GCONF", "GSTAT", "IFCNT", "OTP_READ", "IOIN", "FACTORY_CONF", "TSTEP",
    "MSCNT", "MSCURACT", "CHOPCONF", "DRV_STATUS",
    "PWMCONF", "PWM_SCALE", "PWM_AUTO"
]

Fields = {}

Fields["GCONF"] = {
    "I_scale_analog":      0x01,
    "internal_Rsense":     0x01 << 1,
    "en_spreadCycle":      0x01 << 2,
    "shaft":               0x01 << 3,
    "index_otpw":          0x01 << 4,
    "index_step":          0x01 << 5,
    "pdn_disable":         0x01 << 6,
    "mstep_reg_select":    0x01 << 7,
    "multistep_filt":      0x01 << 8,
    "test_mode":           0x01 << 9
}
Fields["GSTAT"] = {
    "reset":               0x01,
    "drv_err":             0x01 << 1,
    "uv_cp":               0x01 << 2
}
Fields["IFCNT"] = {
    "IFCNT":               0xff
}
Fields["SLAVECONF"] = {
    "SENDDELAY":           0x0f << 8
}
Fields["OTP_PROG"] = {
    "OTPBIT":              0x07,
    "OTPBYTE":             0x03 << 4,
    "OTPMAGIC":            0xff << 8
}
Fields["OTP_READ"] = {
    "OTP_FCLKTRIM":        0x1f,
    "otp_OTTRIM":          0x01 << 5,
    "otp_internalRsense":  0x01 << 6,
    "otp_TBL":             0x01 << 7,
    "OTP_PWM_GRAD":        0x0f << 8,
    "otp_pwm_autograd":    0x01 << 12,
    "OTP_TPWMTHRS":        0x07 << 13,
    "otp_PWM_OFS":         0x01 << 16,
    "otp_PWM_REG":         0x01 << 17,
    "otp_PWM_FREQ":        0x01 << 18,
    "OTP_IHOLDDELAY":      0x03 << 19,
    "OTP_IHOLD":           0x03 << 21,
    "otp_en_spreadCycle":  0x01 << 23
}
# IOIN mapping depends on the driver type (SEL_A field)
# TMC222x (SEL_A == 0)
Fields["IOIN@TMC222x"] = {
    "PDN_UART":            0x01 << 1,
    "SPREAD":              0x01 << 2,
    "DIR":                 0x01 << 3,
    "ENN":                 0x01 << 4,
    "STEP":                0x01 << 5,
    "MS1":                 0x01 << 6,
    "MS2":                 0x01 << 7,
    "SEL_A":               0x01 << 8,
    "VERSION":             0xff << 24
}
# TMC220x (SEL_A == 1)
Fields["IOIN@TMC220x"] = {
    "ENN":                 0x01,
    "MS1":                 0x01 << 2,
    "MS2":                 0x01 << 3,
    "DIAG":                0x01 << 4,
    "PDN_UART":            0x01 << 6,
    "STEP":                0x01 << 7,
    "SEL_A":               0x01 << 8,
    "DIR":                 0x01 << 9,
    "VERSION":             0xff << 24,
}
Fields["FACTORY_CONF"] = {
    "FCLKTRIM":            0x1f,
    "OTTRIM":              0x03 << 8
}
Fields["IHOLD_IRUN"] = {
    "IHOLD":               0x1f,
    "IRUN":                0x1f << 8,
    "IHOLDDELAY":          0x0f << 16
}
Fields["TPOWERDOWN"] = {
    "TPOWERDOWN":          0xff
}
Fields["TSTEP"] = {
    "TSTEP":               0xfffff
}
Fields["TPWMTHRS"] = {
    "TPWMTHRS":            0xfffff
}
Fields["VACTUAL"] = {
    "VACTUAL":             0xffffff
}
Fields["MSCNT"] = {
    "MSCNT":               0x3ff
}
Fields["MSCURACT"] = {
    "CUR_A":               0x1ff,
    "CUR_B":               0x1ff << 16
}
Fields["CHOPCONF"] = {
    "toff":                0x0f,
    "hstrt":               0x07 << 4,
    "hend":                0x0f << 7,
    "TBL":                 0x03 << 15,
    "vsense":              0x01 << 17,
    "MRES":                0x0f << 24,
    "intpol":              0x01 << 28,
    "dedge":               0x01 << 29,
    "diss2g":              0x01 << 30,
    "diss2vs":             0x01 << 31
}
Fields["DRV_STATUS"] = {
    "otpw":                0x01,
    "ot":                  0x01 << 1,
    "s2ga":                0x01 << 2,
    "s2gb":                0x01 << 3,
    "s2vsa":               0x01 << 4,
    "s2vsb":               0x01 << 5,
    "ola":                 0x01 << 6,
    "olb":                 0x01 << 7,
    "t120":                0x01 << 8,
    "t143":                0x01 << 9,
    "t150":                0x01 << 10,
    "t157":                0x01 << 11,
    "CS_ACTUAL":           0x1f << 16,
    "stealth":             0x01 << 30,
    "stst":                0x01 << 31
}
Fields["PWMCONF"] = {
    "PWM_OFS":             0xff,
    "PWM_GRAD":            0xff << 8,
    "pwm_freq":            0x03 << 16,
    "pwm_autoscale":       0x01 << 18,
    "pwm_autograd":        0x01 << 19,
    "freewheel":           0x03 << 20,
    "PWM_REG":             0xf << 24,
    "PWM_LIM":             0xf << 28
}
Fields["PWM_SCALE"] = {
    "PWM_SCALE_SUM":       0xff,
    "PWM_SCALE_AUTO":      0x1ff << 16
}
Fields["PWM_AUTO"] = {
    "PWM_OFS_AUTO":        0xff,
    "PWM_GRAD_AUTO":       0xff << 16
}

SignedFields = ["CUR_A", "CUR_B", "PWM_SCALE_AUTO"]

FieldFormatters = dict(tmc2130.FieldFormatters)
FieldFormatters.update({
    "SEL_A":            (lambda v: "%d(%s)" % (v, ["TMC222x", "TMC220x"][v])),
    "s2vsa":            (lambda v: "1(LowSideShort_A!)" if v else ""),
    "s2vsb":            (lambda v: "1(LowSideShort_B!)" if v else ""),
})


######################################################################
# TMC2208 printer object
######################################################################

class TMC2208:
    def __init__(self, config):
        # Setup mcu communication
        self.fields = tmc.FieldHelper(Fields, SignedFields, FieldFormatters)
        self.mcu_tmc = tmc_uart.MCU_TMC_uart(config, Registers, self.fields)
        # Register commands
        current_helper = tmc2130.TMCCurrentHelper(config, self.mcu_tmc)
        cmdhelper = tmc.TMCCommandHelper(config, self.mcu_tmc, current_helper)
        cmdhelper.setup_register_dump(ReadRegisters, self.read_translate)
        tmc.TMCHomingCurrentHelper(config, self.mcu_tmc, current_helper)
        # Setup basic register values
        self.fields.set_field("pdn_disable", True)
        self.fields.set_field("mstep_reg_select", True)
        self.fields.set_field("multistep_filt", True)
        mh = tmc.TMCMicrostepHelper(config, self.mcu_tmc)
        self.get_microsteps = mh.get_microsteps
        self.get_phase = mh.get_phase
        tmc.TMCStealthchopHelper(config, self.mcu_tmc, TMC_FREQUENCY)
        # Allow other registers to be set from the config
        set_config_field = self.fields.set_config_field
        # CHOPCONF
        set_config_field(config, "toff", 3)
        set_config_field(config, "hstrt", 5)
        set_config_field(config, "hend", 0)
        set_config_field(config, "TBL", 2)
        set_config_field(config, "diss2g", 0)
        set_config_field(config, "diss2vs", 0)
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

    def read_translate(self, reg_name, val):
        if reg_name == "IOIN":
            drv_type = self.fields.get_field("SEL_A", val)
            reg_name = "IOIN@TMC220x" if drv_type else "IOIN@TMC222x"
        return reg_name, val

def load_config_prefix(config):
    return TMC2208(config)

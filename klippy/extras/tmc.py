# Common helper code for TMC stepper drivers
#
# Copyright (C) 2018-2020  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, collections
import stepper


######################################################################
# Field helpers
######################################################################

# Return the position of the first bit set in a mask
def ffs(mask):
    return (mask & -mask).bit_length() - 1

class FieldHelper:
    def __init__(self, all_fields, signed_fields=[], field_formatters={},
                 registers=None):
        self.all_fields = all_fields
        self.signed_fields = {sf: 1 for sf in signed_fields}
        self.field_formatters = field_formatters
        self.registers = registers
        if self.registers is None:
            self.registers = collections.OrderedDict()
        self.field_to_register = { f: r for r, fields in self.all_fields.items()
                                   for f in fields }
    def lookup_register(self, field_name, default=None):
        return self.field_to_register.get(field_name, default)
    def get_field(self, field_name, reg_value=None, reg_name=None):
        # Returns value of the register field
        if reg_name is None:
            reg_name = self.field_to_register[field_name]
        if reg_value is None:
            reg_value = self.registers.get(reg_name, 0)
        mask = self.all_fields[reg_name][field_name]
        field_value = (reg_value & mask) >> ffs(mask)
        if field_name in self.signed_fields and ((reg_value & mask)<<1) > mask:
            field_value -= (1 << field_value.bit_length())
        return field_value
    def set_field(self, field_name, field_value, reg_value=None, reg_name=None):
        # Returns register value with field bits filled with supplied value
        if reg_name is None:
            reg_name = self.field_to_register[field_name]
        if reg_value is None:
            reg_value = self.registers.get(reg_name, 0)
        mask = self.all_fields[reg_name][field_name]
        new_value = (reg_value & ~mask) | ((field_value << ffs(mask)) & mask)
        self.registers[reg_name] = new_value
        return new_value
    def set_config_field(self, config, field_name, default):
        # Allow a field to be set from the config file
        config_name = "driver_" + field_name.upper()
        reg_name = self.field_to_register[field_name]
        mask = self.all_fields[reg_name][field_name]
        maxval = mask >> ffs(mask)
        if maxval == 1:
            val = config.getboolean(config_name, default)
        elif field_name in self.signed_fields:
            val = config.getint(config_name, default,
                                minval=-(maxval//2 + 1), maxval=maxval//2)
        else:
            val = config.getint(config_name, default, minval=0, maxval=maxval)
        return self.set_field(field_name, val)
    def pretty_format(self, reg_name, reg_value):
        # Provide a string description of a register
        reg_fields = self.all_fields.get(reg_name, {})
        reg_fields = sorted([(mask, name) for name, mask in reg_fields.items()])
        fields = []
        for mask, field_name in reg_fields:
            field_value = self.get_field(field_name, reg_value, reg_name)
            sval = self.field_formatters.get(field_name, str)(field_value)
            if sval and sval != "0":
                fields.append(" %s=%s" % (field_name, sval))
        return "%-11s %08x%s" % (reg_name + ":", reg_value, "".join(fields))


######################################################################
# Periodic error checking
######################################################################

class TMCErrorCheck:
    def __init__(self, config, mcu_tmc, clear_gstat=True):
        self.printer = config.get_printer()
        self.stepper_name = ' '.join(config.get_name().split()[1:])
        self.mcu_tmc = mcu_tmc
        self.fields = mcu_tmc.get_fields()
        self.check_timer = None
        # Setup for GSTAT query
        self.clear_gstat = clear_gstat
        reg_name = self.fields.lookup_register("drv_err")
        if reg_name is not None:
            self.gstat_reg_info = [0, reg_name, 0xffffffff, 0xffffffff]
        else:
            self.gstat_reg_info = None
        # Setup for DRV_STATUS query
        reg_name = self.fields.lookup_register("ot")
        mask = err_mask = 0
        err_fields = ["ot", "s2ga", "s2gb", "s2vsa", "s2vsb"]
        warn_fields = ["otpw", "t120", "t143", "t150", "t157"]
        for f in err_fields + warn_fields:
            if f in self.fields.all_fields[reg_name]:
                mask |= self.fields.all_fields[reg_name][f]
                if f in err_fields:
                    err_mask |= self.fields.all_fields[reg_name][f]
        self.drv_status_reg_info = [0, reg_name, mask, err_mask]
    def _query_register(self, reg_info, try_clear=False):
        last_value, reg_name, mask, err_mask = reg_info
        count = 0
        while 1:
            try:
                val = self.mcu_tmc.get_register(reg_name)
            except self.printer.command_error as e:
                count += 1
                if count < 3 and str(e).startswith("Unable to read tmc uart"):
                    # Allow more retries on a TMC UART read error
                    reactor = self.printer.get_reactor()
                    reactor.pause(reactor.monotonic() + 0.050)
                    continue
                raise
            if val & mask != last_value & mask:
                fmt = self.fields.pretty_format(reg_name, val)
                logging.info("TMC '%s' reports %s", self.stepper_name, fmt)
                reg_info[0] = last_value = val
            if not val & err_mask:
                break
            count += 1
            if count >= 3:
                fmt = self.fields.pretty_format(reg_name, val)
                raise self.printer.command_error("TMC '%s' reports error: %s"
                                                 % (self.stepper_name, fmt))
            if try_clear:
                try_clear = False
                self.mcu_tmc.set_register(reg_name, val & err_mask)
    def _do_periodic_check(self, eventtime, try_clear=False):
        try:
            self._query_register(self.drv_status_reg_info)
            if self.gstat_reg_info is not None:
                self._query_register(self.gstat_reg_info, try_clear=try_clear)
        except self.printer.command_error as e:
            self.printer.invoke_shutdown(str(e))
            return self.printer.get_reactor().NEVER
        return eventtime + 1.
    def stop_checks(self):
        if self.check_timer is None:
            return
        self.printer.get_reactor().unregister_timer(self.check_timer)
        self.check_timer = None
    def start_checks(self):
        if self.check_timer is not None:
            self.stop_checks()
        self._do_periodic_check(0., try_clear=self.clear_gstat)
        reactor = self.printer.get_reactor()
        curtime = reactor.monotonic()
        self.check_timer = reactor.register_timer(self._do_periodic_check,
                                                  curtime + 1.)


######################################################################
# G-Code command helpers
######################################################################

class TMCCommandHelper:
    def __init__(self, config, mcu_tmc, current_helper, clear_gstat=True):
        self.printer = config.get_printer()
        self.stepper_name = ' '.join(config.get_name().split()[1:])
        self.name = config.get_name().split()[-1]
        self.mcu_tmc = mcu_tmc
        self.current_helper = current_helper
        self.echeck_helper = TMCErrorCheck(config, mcu_tmc, clear_gstat)
        self.fields = mcu_tmc.get_fields()
        self.read_registers = self.read_translate = None
        self.toff = None
        self.printer.register_event_handler("klippy:connect",
                                            self._handle_connect)
        # Register commands
        gcode = self.printer.lookup_object("gcode")
        gcode.register_mux_command("SET_TMC_FIELD", "STEPPER", self.name,
                                   self.cmd_SET_TMC_FIELD,
                                   desc=self.cmd_SET_TMC_FIELD_help)
        gcode.register_mux_command("INIT_TMC", "STEPPER", self.name,
                                   self.cmd_INIT_TMC,
                                   desc=self.cmd_INIT_TMC_help)
        gcode.register_mux_command("SET_TMC_CURRENT", "STEPPER", self.name,
                                   self.cmd_SET_TMC_CURRENT,
                                   desc=self.cmd_SET_TMC_CURRENT_help)
    def _init_registers(self, print_time=None):
        # Send registers
        for reg_name, val in self.fields.registers.items():
            self.mcu_tmc.set_register(reg_name, val, print_time)
    cmd_INIT_TMC_help = "Initialize TMC stepper driver registers"
    def cmd_INIT_TMC(self, gcmd):
        logging.info("INIT_TMC %s", self.name)
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        self._init_registers(print_time)
    cmd_SET_TMC_FIELD_help = "Set a register field of a TMC driver"
    def cmd_SET_TMC_FIELD(self, gcmd):
        field_name = gcmd.get('FIELD')
        reg_name = self.fields.lookup_register(field_name, None)
        if reg_name is None:
            raise gcmd.error("Unknown field name '%s'" % (field_name,))
        value = gcmd.get_int('VALUE')
        reg_val = self.fields.set_field(field_name, value)
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        self.mcu_tmc.set_register(reg_name, reg_val, print_time)
    cmd_SET_TMC_CURRENT_help = "Set the current of a TMC driver"
    def cmd_SET_TMC_CURRENT(self, gcmd):
        ch = self.current_helper
        prev_run_current, prev_hold_current, max_current = ch.get_current()
        run_current = gcmd.get_float('CURRENT', None,
                                     minval=0., maxval=max_current)
        hold_current = gcmd.get_float('HOLDCURRENT', None,
                                      above=0., maxval=max_current)
        if run_current is not None or hold_current is not None:
            if run_current is None:
                run_current = prev_run_current
            if hold_current is None:
                hold_current = prev_hold_current
            toolhead = self.printer.lookup_object('toolhead')
            print_time = toolhead.get_last_move_time()
            ch.set_current(run_current, hold_current, print_time)
            prev_run_current, prev_hold_current, max_current = ch.get_current()
        # Report values
        if prev_hold_current is None:
            gcmd.respond_info("Run Current: %0.2fA" % (prev_run_current,))
        else:
            gcmd.respond_info("Run Current: %0.2fA Hold Current: %0.2fA"
                              % (prev_run_current, prev_hold_current))
    # Stepper enable/disable tracking
    def _do_enable(self, print_time):
        try:
            if self.toff is not None:
                # Shared enable via comms handling
                self.fields.set_field("toff", self.toff)
            self._init_registers()
            self.echeck_helper.start_checks()
        except self.printer.command_error as e:
            self.printer.invoke_shutdown(str(e))
    def _do_disable(self, print_time):
        try:
            if self.toff is not None:
                val = self.fields.set_field("toff", 0)
                reg_name = self.fields.lookup_register("toff")
                self.mcu_tmc.set_register(reg_name, val, print_time)
            self.echeck_helper.stop_checks()
        except self.printer.command_error as e:
            self.printer.invoke_shutdown(str(e))
    def handle_stepper_enable(self, print_time, is_enable):
        if is_enable:
            cb = (lambda ev: self._do_enable(print_time))
        else:
            cb = (lambda ev: self._do_disable(print_time))
        self.printer.get_reactor().register_callback(cb)
    def _handle_connect(self):
        # Check for soft stepper enable/disable
        stepper_enable = self.printer.lookup_object('stepper_enable')
        enable_line = stepper_enable.lookup_enable(self.stepper_name)
        enable_line.register_state_callback(self.handle_stepper_enable)
        if not enable_line.has_dedicated_enable():
            self.toff = self.fields.get_field("toff")
            self.fields.set_field("toff", 0)
            logging.info("Enabling TMC virtual enable for '%s'",
                         self.stepper_name)
        # Send init
        try:
            self._init_registers()
        except self.printer.command_error as e:
            logging.info("TMC %s failed to init: %s", self.name, str(e))
    # DUMP_TMC support
    def setup_register_dump(self, read_registers, read_translate=None):
        self.read_registers = read_registers
        self.read_translate = read_translate
        gcode = self.printer.lookup_object("gcode")
        gcode.register_mux_command("DUMP_TMC", "STEPPER", self.name,
                                   self.cmd_DUMP_TMC,
                                   desc=self.cmd_DUMP_TMC_help)
    cmd_DUMP_TMC_help = "Read and display TMC stepper driver registers"
    def cmd_DUMP_TMC(self, gcmd):
        logging.info("DUMP_TMC %s", self.name)
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        gcmd.respond_info("========== Write-only registers ==========")
        for reg_name, val in self.fields.registers.items():
            if reg_name not in self.read_registers:
                gcmd.respond_info(self.fields.pretty_format(reg_name, val))
        gcmd.respond_info("========== Queried registers ==========")
        for reg_name in self.read_registers:
            val = self.mcu_tmc.get_register(reg_name)
            if self.read_translate is not None:
                reg_name, val = self.read_translate(reg_name, val)
            gcmd.respond_info(self.fields.pretty_format(reg_name, val))


######################################################################
# TMC virtual pins
######################################################################

# Helper class for "sensorless homing"
class TMCVirtualPinHelper:
    def __init__(self, config, mcu_tmc):
        self.printer = config.get_printer()
        self.mcu_tmc = mcu_tmc
        self.fields = mcu_tmc.get_fields()
        if self.fields.lookup_register('diag0_stall') is not None:
            if config.get('diag0_pin', None) is not None:
                self.diag_pin = config.get('diag0_pin')
                self.diag_pin_field = 'diag0_stall'
            else:
                self.diag_pin = config.get('diag1_pin', None)
                self.diag_pin_field = 'diag1_stall'
        else:
            self.diag_pin = config.get('diag_pin', None)
            self.diag_pin_field = None
        self.mcu_endstop = None
        self.en_pwm = False
        self.pwmthrs = 0
        # Register virtual_endstop pin
        name_parts = config.get_name().split()
        ppins = self.printer.lookup_object("pins")
        ppins.register_chip("%s_%s" % (name_parts[0], name_parts[-1]), self)
    def setup_pin(self, pin_type, pin_params):
        # Validate pin
        ppins = self.printer.lookup_object('pins')
        if pin_type != 'endstop' or pin_params['pin'] != 'virtual_endstop':
            raise ppins.error("tmc virtual endstop only useful as endstop")
        if pin_params['invert'] or pin_params['pullup']:
            raise ppins.error("Can not pullup/invert tmc virtual pin")
        if self.diag_pin is None:
            raise ppins.error("tmc virtual endstop requires diag pin config")
        # Setup for sensorless homing
        reg = self.fields.lookup_register("en_pwm_mode", None)
        if reg is None:
            self.en_pwm = not self.fields.get_field("en_spreadCycle")
            self.pwmthrs = self.fields.get_field("TPWMTHRS")
        else:
            self.en_pwm = self.fields.get_field("en_pwm_mode")
            self.pwmthrs = 0
        self.printer.register_event_handler("homing:homing_move_begin",
                                            self.handle_homing_move_begin)
        self.printer.register_event_handler("homing:homing_move_end",
                                            self.handle_homing_move_end)
        self.mcu_endstop = ppins.setup_pin('endstop', self.diag_pin)
        return self.mcu_endstop
    def handle_homing_move_begin(self, endstops):
        if self.mcu_endstop not in endstops:
            return
        reg = self.fields.lookup_register("en_pwm_mode", None)
        if reg is None:
            # On "stallguard4" drivers, "stealthchop" must be enabled
            tp_val = self.fields.set_field("TPWMTHRS", 0)
            self.mcu_tmc.set_register("TPWMTHRS", tp_val)
            val = self.fields.set_field("en_spreadCycle", 0)
        else:
            # On earlier drivers, "stealthchop" must be disabled
            self.fields.set_field("en_pwm_mode", 0)
            val = self.fields.set_field(self.diag_pin_field, 1)
        self.mcu_tmc.set_register("GCONF", val)
        tc_val = self.fields.set_field("TCOOLTHRS", 0xfffff)
        self.mcu_tmc.set_register("TCOOLTHRS", tc_val)
    def handle_homing_move_end(self, endstops):
        if self.mcu_endstop not in endstops:
            return
        reg = self.fields.lookup_register("en_pwm_mode", None)
        if reg is None:
            tp_val = self.fields.set_field("TPWMTHRS", self.pwmthrs)
            self.mcu_tmc.set_register("TPWMTHRS", tp_val)
            val = self.fields.set_field("en_spreadCycle", not self.en_pwm)
        else:
            self.fields.set_field("en_pwm_mode", self.en_pwm)
            val = self.fields.set_field(self.diag_pin_field, 0)
        self.mcu_tmc.set_register("GCONF", val)
        tc_val = self.fields.set_field("TCOOLTHRS", 0)
        self.mcu_tmc.set_register("TCOOLTHRS", tc_val)


######################################################################
# Config reading helpers
######################################################################

# Helper to configure and query the microstep settings
class TMCMicrostepHelper:
    def __init__(self, config, mcu_tmc):
        self.mcu_tmc = mcu_tmc
        self.fields = mcu_tmc.get_fields()
        stepper_name = " ".join(config.get_name().split()[1:])
        stepper_config = ms_config = config.getsection(stepper_name)
        if (stepper_config.get('microsteps', None, note_valid=False) is None
            and config.get('microsteps', None, note_valid=False) is not None):
            # Older config format with microsteps in tmc config section
            ms_config = config
        steps = {'256': 0, '128': 1, '64': 2, '32': 3, '16': 4,
                 '8': 5, '4': 6, '2': 7, '1': 8}
        mres = ms_config.getchoice('microsteps', steps)
        self.fields.set_field("MRES", mres)
        self.fields.set_field("intpol", config.getboolean("interpolate", True))
    def get_microsteps(self):
        return 256 >> self.fields.get_field("MRES")
    def get_phase(self):
        field_name = "MSCNT"
        if self.fields.lookup_register(field_name, None) is None:
            # TMC2660 uses MSTEP
            field_name = "MSTEP"
        reg = self.mcu_tmc.get_register(self.fields.lookup_register(field_name))
        mscnt = self.fields.get_field(field_name, reg)
        return 1023 - mscnt, 1024

# Helper to configure "stealthchop" mode
def TMCStealthchopHelper(config, mcu_tmc, tmc_freq):
    fields = mcu_tmc.get_fields()
    en_pwm_mode = False
    velocity = config.getfloat('stealthchop_threshold', 0., minval=0.)
    if velocity:
        stepper_name = " ".join(config.get_name().split()[1:])
        stepper_config = config.getsection(stepper_name)
        step_dist = stepper.parse_step_distance(stepper_config)
        step_dist_256 = step_dist / (1 << fields.get_field("MRES"))
        threshold = int(tmc_freq * step_dist_256 / velocity + .5)
        fields.set_field("TPWMTHRS", max(0, min(0xfffff, threshold)))
        en_pwm_mode = True
    reg = fields.lookup_register("en_pwm_mode", None)
    if reg is not None:
        fields.set_field("en_pwm_mode", en_pwm_mode)
    else:
        # TMC2208 uses en_spreadCycle
        fields.set_field("en_spreadCycle", not en_pwm_mode)

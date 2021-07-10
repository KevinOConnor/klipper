# Helper code for SPI and I2C bus communication
#
# Copyright (C) 2018,2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import mcu

def resolve_bus_name(mcu, param, bus):
    # Find enumerations for the given bus
    enumerations = mcu.get_enumerations()
    enums = enumerations.get(param, enumerations.get('bus'))
    if enums is None:
        if bus is None:
            return 0
        return bus
    # Verify bus is a valid enumeration
    ppins = mcu.get_printer().lookup_object("pins")
    mcu_name = mcu.get_name()
    if bus is None:
        rev_enums = {v: k for k, v in enums.items()}
        if 0 not in rev_enums:
            raise ppins.error("Must specify %s on mcu '%s'" % (param, mcu_name))
        bus = rev_enums[0]
    if bus not in enums:
        raise ppins.error("Unknown %s '%s'" % (param, bus))
    # Check for reserved bus pins
    constants = mcu.get_constants()
    reserve_pins = constants.get('BUS_PINS_%s' % (bus,), None)
    pin_resolver = ppins.get_pin_resolver(mcu_name)
    if reserve_pins is not None:
        for pin in reserve_pins.split(','):
            pin_resolver.reserve_pin(pin, bus)
    return bus


######################################################################
# SPI
######################################################################

# Helper code for working with devices connected to an MCU via an SPI bus
class MCU_SPI:
    def __init__(self, mcu, bus, pin, mode, speed, sw_pins=None):
        self.mcu = mcu
        self.bus = bus
        # Config SPI object (set all CS pins high before spi_set_bus commands)
        self.oid = mcu.create_oid()
        if pin is None:
            mcu.add_config_cmd("config_spi_without_cs oid=%d" % (self.oid,))
        else:
            mcu.add_config_cmd("config_spi oid=%d pin=%s" % (self.oid, pin))
        # Generate SPI bus config message
        if sw_pins is not None:
            self.config_fmt = (
                "spi_set_software_bus oid=%d"
                " miso_pin=%s mosi_pin=%s sclk_pin=%s mode=%d rate=%d"
                % (self.oid, sw_pins[0], sw_pins[1], sw_pins[2], mode, speed))
        else:
            self.config_fmt = (
                "spi_set_bus oid=%d spi_bus=%%s mode=%d rate=%d"
                % (self.oid, mode, speed))
        self.cmd_queue = mcu.alloc_command_queue()
        mcu.register_config_callback(self.build_config)
        self.spi_send_cmd = self.spi_transfer_cmd = None
    def setup_shutdown_msg(self, shutdown_seq):
        shutdown_msg = "".join(["%02x" % (x,) for x in shutdown_seq])
        self.mcu.add_config_cmd(
            "config_spi_shutdown oid=%d spi_oid=%d shutdown_msg=%s"
            % (self.mcu.create_oid(), self.oid, shutdown_msg))
    def get_oid(self):
        return self.oid
    def get_mcu(self):
        return self.mcu
    def get_command_queue(self):
        return self.cmd_queue
    def build_config(self):
        if '%' in self.config_fmt:
            bus = resolve_bus_name(self.mcu, "spi_bus", self.bus)
            self.config_fmt = self.config_fmt % (bus,)
        self.mcu.add_config_cmd(self.config_fmt)
        self.spi_send_cmd = self.mcu.lookup_command(
            "spi_send oid=%c data=%*s", cq=self.cmd_queue)
        self.spi_transfer_cmd = self.mcu.lookup_query_command(
            "spi_transfer oid=%c data=%*s",
            "spi_transfer_response oid=%c response=%*s", oid=self.oid,
            cq=self.cmd_queue)
    def spi_send(self, data, minclock=0, reqclock=0):
        if self.spi_send_cmd is None:
            # Send setup message via mcu initialization
            data_msg = "".join(["%02x" % (x,) for x in data])
            self.mcu.add_config_cmd("spi_send oid=%d data=%s" % (
                self.oid, data_msg), is_init=True)
            return
        self.spi_send_cmd.send([self.oid, data],
                               minclock=minclock, reqclock=reqclock)
    def spi_transfer(self, data, minclock=0, reqclock=0):
        return self.spi_transfer_cmd.send([self.oid, data],
                                          minclock=minclock, reqclock=reqclock)
    def spi_transfer_with_preface(self, preface_data, data,
                                  minclock=0, reqclock=0):
        return self.spi_transfer_cmd.send_with_preface(
            self.spi_send_cmd, [self.oid, preface_data], [self.oid, data],
            minclock=minclock, reqclock=reqclock)

# Helper to setup an spi bus from settings in a config section
def MCU_SPI_from_config(config, mode, pin_option="cs_pin",
                        default_speed=100000, share_type=None, use_cs_pin=True):
    # Determine pin from config
    ppins = config.get_printer().lookup_object("pins")
    cs_pin = config.get(pin_option)
    cs_pin_params = ppins.lookup_pin(cs_pin, share_type=share_type)
    pin = cs_pin_params['pin']
    if pin == 'None' or not use_cs_pin:
        ppins.reset_pin_sharing(cs_pin_params)
        pin = None
    # Load bus parameters
    mcu = cs_pin_params['chip']
    speed = config.getint('spi_speed', default_speed, minval=100000)
    if config.get('spi_software_sclk_pin', None) is not None:
        sw_pin_names = ['spi_software_%s_pin' % (name,)
                        for name in ['miso', 'mosi', 'sclk']]
        sw_pin_params = [ppins.lookup_pin(config.get(name), share_type=name)
                         for name in sw_pin_names]
        for pin_params in sw_pin_params:
            if pin_params['chip'] != mcu:
                raise ppins.error("%s: spi pins must be on same mcu" % (
                    config.get_name(),))
        sw_pins = tuple([pin_params['pin'] for pin_params in sw_pin_params])
        bus = None
    else:
        bus = config.get('spi_bus', None)
        sw_pins = None
    # Create MCU_SPI object
    return MCU_SPI(mcu, bus, pin, mode, speed, sw_pins)


######################################################################
# I2C
######################################################################

# Helper code for working with devices connected to an MCU via an I2C bus
class MCU_I2C:
    def __init__(self, mcu, bus, addr, speed):
        self.mcu = mcu
        self.bus = bus
        self.i2c_address = addr
        self.oid = self.mcu.create_oid()
        self.config_fmt = "config_i2c oid=%d i2c_bus=%%s rate=%d address=%d" % (
            self.oid, speed, addr)
        self.cmd_queue = self.mcu.alloc_command_queue()
        self.mcu.register_config_callback(self.build_config)
        self.i2c_write_cmd = self.i2c_read_cmd = self.i2c_modify_bits_cmd = None
    def get_oid(self):
        return self.oid
    def get_mcu(self):
        return self.mcu
    def get_i2c_address(self):
        return self.i2c_address
    def get_command_queue(self):
        return self.cmd_queue
    def build_config(self):
        bus = resolve_bus_name(self.mcu, "i2c_bus", self.bus)
        self.mcu.add_config_cmd(self.config_fmt % (bus,))
        self.i2c_write_cmd = self.mcu.lookup_command(
            "i2c_write oid=%c data=%*s", cq=self.cmd_queue)
        self.i2c_read_cmd = self.mcu.lookup_query_command(
            "i2c_read oid=%c reg=%*s read_len=%u",
            "i2c_read_response oid=%c response=%*s", oid=self.oid,
            cq=self.cmd_queue)
        self.i2c_modify_bits_cmd = self.mcu.lookup_command(
            "i2c_modify_bits oid=%c reg=%*s clear_set_bits=%*s",
            cq=self.cmd_queue)
    def i2c_write(self, data, minclock=0, reqclock=0):
        if self.i2c_write_cmd is None:
            # Send setup message via mcu initialization
            data_msg = "".join(["%02x" % (x,) for x in data])
            self.mcu.add_config_cmd("i2c_write oid=%d data=%s" % (
                self.oid, data_msg), is_init=True)
            return
        self.i2c_write_cmd.send([self.oid, data],
                                minclock=minclock, reqclock=reqclock)
    def i2c_read(self, write, read_len):
        return self.i2c_read_cmd.send([self.oid, write, read_len])
    def i2c_modify_bits(self, reg, clear_bits, set_bits,
                        minclock=0, reqclock=0):
        clearset = clear_bits + set_bits
        if self.i2c_modify_bits_cmd is None:
            # Send setup message via mcu initialization
            reg_msg = "".join(["%02x" % (x,) for x in reg])
            clearset_msg = "".join(["%02x" % (x,) for x in clearset])
            self.mcu.add_config_cmd(
                "i2c_modify_bits oid=%d reg=%s clear_set_bits=%s" % (
                    self.oid, reg_msg, clearset_msg), is_init=True)
            return
        self.i2c_modify_bits_cmd.send([self.oid, reg, clearset],
                                      minclock=minclock, reqclock=reqclock)

def MCU_I2C_from_config(config, default_addr=None, default_speed=100000):
    # Load bus parameters
    printer = config.get_printer()
    i2c_mcu = mcu.get_printer_mcu(printer, config.get('i2c_mcu', 'mcu'))
    speed = config.getint('i2c_speed', default_speed, minval=100000)
    bus = config.get('i2c_bus', None)
    if default_addr is None:
        addr = config.getint('i2c_address', minval=0, maxval=127)
    else:
        addr = config.getint('i2c_address', default_addr, minval=0, maxval=127)
    # Create MCU_I2C object
    return MCU_I2C(i2c_mcu, bus, addr, speed)


######################################################################
# Bus synchronized digital outputs
######################################################################

# Helper code for a gpio that updates on a cmd_queue
class MCU_bus_digital_out:
    def __init__(self, mcu, pin_desc, cmd_queue=None, value=0):
        self.mcu = mcu
        self.oid = mcu.create_oid()
        ppins = mcu.get_printer().lookup_object('pins')
        pin_params = ppins.lookup_pin(pin_desc)
        if pin_params['chip'] is not mcu:
            raise ppins.error("Pin %s must be on mcu %s" % (
                pin_desc, mcu.get_name()))
        mcu.add_config_cmd("config_digital_out oid=%d pin=%s value=%d"
                           " default_value=%d max_duration=%d"
                           % (self.oid, pin_params['pin'], value, value, 0))
        mcu.register_config_callback(self.build_config)
        if cmd_queue is None:
            cmd_queue = mcu.alloc_command_queue()
        self.cmd_queue = cmd_queue
        self.update_pin_cmd = None
    def get_oid(self):
        return self.oid
    def get_mcu(self):
        return self.mcu
    def get_command_queue(self):
        return self.cmd_queue
    def build_config(self):
        self.update_pin_cmd = self.mcu.lookup_command(
            "update_digital_out oid=%c value=%c", cq=self.cmd_queue)
    def update_digital_out(self, value, minclock=0, reqclock=0):
        if self.update_pin_cmd is None:
            # Send setup message via mcu initialization
            self.mcu.add_config_cmd("update_digital_out oid=%c value=%c"
                                    % (self.oid, not not value))
            return
        self.update_pin_cmd.send([self.oid, not not value],
                                 minclock=minclock, reqclock=reqclock)

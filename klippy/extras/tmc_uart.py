# Helper code for communicating with TMC stepper drivers via UART
#
# Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging


######################################################################
# TMC uart analog mux support
######################################################################

class MCU_analog_mux:
    def __init__(self, mcu, cmd_queue, select_pins_desc):
        self.mcu = mcu
        self.cmd_queue = cmd_queue
        ppins = mcu.get_printer().lookup_object("pins")
        select_pin_params = [ppins.lookup_pin(spd, can_invert=True)
                             for spd in select_pins_desc.split(',')]
        self.oids = [self.mcu.create_oid() for pp in select_pin_params]
        self.pins = [pp['pin'] for pp in select_pin_params]
        self.pin_values = tuple([-1 for pp in select_pin_params])
        for oid, pin in zip(self.oids, self.pins):
            self.mcu.add_config_cmd("config_digital_out oid=%d pin=%s"
                                    " value=0 default_value=0 max_duration=0"
                                    % (oid, pin))
        self.update_pin_cmd = None
        self.mcu.register_config_callback(self.build_config)
    def build_config(self):
        self.update_pin_cmd = self.mcu.lookup_command(
            "update_digital_out oid=%c value=%c", cq=self.cmd_queue)
    def get_instance_id(self, select_pins_desc):
        ppins = self.mcu.get_printer().lookup_object("pins")
        select_pin_params = [ppins.parse_pin(spd, can_invert=True)
                             for spd in select_pins_desc.split(',')]
        for pin_params in select_pin_params:
            if pin_params['chip'] != self.mcu:
                raise self.mcu.get_printer().config_error(
                    "TMC mux pins must be on the same mcu")
        pins = [pp['pin'] for pp in select_pin_params]
        if pins != self.pins:
            raise self.mcu.get_printer().config_error(
                "All TMC mux instances must use identical pins")
        return tuple([not pp['invert'] for pp in select_pin_params])
    def activate(self, instance_id):
        for oid, old, new in zip(self.oids, self.pin_values, instance_id):
            if old != new:
                self.update_pin_cmd.send([oid, new])
        self.pin_values = instance_id


######################################################################
# TMC uart communication
######################################################################

TMC_BAUD_RATE = 9000

# Code for sending messages on a TMC uart
class MCU_TMC_uart_bitbang:
    def __init__(self, rx_pin_params, tx_pin_params, select_pins_desc):
        self.mcu = rx_pin_params['chip']
        self.mutex = self.mcu.get_printer().get_reactor().mutex()
        self.pullup = rx_pin_params['pullup']
        self.rx_pin = rx_pin_params['pin']
        self.tx_pin = tx_pin_params['pin']
        self.oid = self.mcu.create_oid()
        self.cmd_queue = self.mcu.alloc_command_queue()
        self.analog_mux = None
        if select_pins_desc is not None:
            self.analog_mux = MCU_analog_mux(self.mcu, self.cmd_queue,
                                             select_pins_desc)
        self.instances = {}
        self.tmcuart_send_cmd = None
        self.mcu.register_config_callback(self.build_config)
    def build_config(self):
        bit_ticks = self.mcu.seconds_to_clock(1. / TMC_BAUD_RATE)
        self.mcu.add_config_cmd(
            "config_tmcuart oid=%d rx_pin=%s pull_up=%d tx_pin=%s bit_time=%d"
            % (self.oid, self.rx_pin, self.pullup, self.tx_pin, bit_ticks))
        self.tmcuart_send_cmd = self.mcu.lookup_query_command(
            "tmcuart_send oid=%c write=%*s read=%c",
            "tmcuart_response oid=%c read=%*s", oid=self.oid,
            cq=self.cmd_queue, is_async=True)
    def register_instance(self, rx_pin_params, tx_pin_params,
                          select_pins_desc, addr):
        if (rx_pin_params['pin'] != self.rx_pin
            or tx_pin_params['pin'] != self.tx_pin
            or (select_pins_desc is None) != (self.analog_mux is None)):
            raise self.mcu.get_printer().config_error(
                "Shared TMC uarts must use the same pins")
        instance_id = None
        if self.analog_mux is not None:
            instance_id = self.analog_mux.get_instance_id(select_pins_desc)
        if (instance_id, addr) in self.instances:
            raise self.mcu.get_printer().config_error(
                "Shared TMC uarts need unique address or select_pins polarity")
        self.instances[(instance_id, addr)] = True
        return instance_id
    def _calc_crc8(self, data):
        # Generate a CRC8-ATM value for a bytearray
        crc = 0
        for b in data:
            for i in range(8):
                if (crc >> 7) ^ (b & 0x01):
                    crc = (crc << 1) ^ 0x07
                else:
                    crc = (crc << 1)
                crc &= 0xff
                b >>= 1
        return crc
    def _add_serial_bits(self, data):
        # Add serial start and stop bits to a message in a bytearray
        out = 0
        pos = 0
        for d in data:
            b = (d << 1) | 0x200
            out |= (b << pos)
            pos += 10
        res = bytearray()
        for i in range((pos+7)//8):
            res.append((out >> (i*8)) & 0xff)
        return res
    def _encode_read(self, sync, addr, reg):
        # Generate a uart read register message
        msg = bytearray([sync, addr, reg])
        msg.append(self._calc_crc8(msg))
        return self._add_serial_bits(msg)
    def _encode_write(self, sync, addr, reg, val):
        # Generate a uart write register message
        msg = bytearray([sync, addr, reg, (val >> 24) & 0xff,
                         (val >> 16) & 0xff, (val >> 8) & 0xff, val & 0xff])
        msg.append(self._calc_crc8(msg))
        return self._add_serial_bits(msg)
    def _decode_read(self, reg, data):
        # Extract a uart read response message
        if len(data) != 10:
            return None
        # Convert data into a long integer for easy manipulation
        mval = pos = 0
        for d in bytearray(data):
            mval |= d << pos
            pos += 8
        # Extract register value
        val = ((((mval >> 31) & 0xff) << 24) | (((mval >> 41) & 0xff) << 16)
               | (((mval >> 51) & 0xff) << 8) | ((mval >> 61) & 0xff))
        # Verify start/stop bits and crc
        encoded_data = self._encode_write(0x05, 0xff, reg, val)
        if data != encoded_data:
            return None
        return val
    def reg_read(self, instance_id, addr, reg):
        if self.analog_mux is not None:
            self.analog_mux.activate(instance_id)
        msg = self._encode_read(0xf5, addr, reg)
        params = self.tmcuart_send_cmd.send([self.oid, msg, 10])
        return self._decode_read(reg, params['read'])
    def reg_write(self, instance_id, addr, reg, val, print_time=None):
        minclock = 0
        if print_time is not None:
            minclock = self.mcu.print_time_to_clock(print_time)
        if self.analog_mux is not None:
            self.analog_mux.activate(instance_id)
        msg = self._encode_write(0xf5, addr, reg | 0x80, val)
        self.tmcuart_send_cmd.send([self.oid, msg, 0], minclock=minclock)

# Lookup a (possibly shared) tmc uart
def lookup_tmc_uart_bitbang(config, max_addr):
    ppins = config.get_printer().lookup_object("pins")
    rx_pin_params = ppins.lookup_pin(
        config.get('uart_pin'), can_pullup=True, share_type="tmc_uart_rx")
    tx_pin_desc = config.get('tx_pin', None)
    if tx_pin_desc is None:
        tx_pin_params = rx_pin_params
    else:
        tx_pin_params = ppins.lookup_pin(tx_pin_desc, share_type="tmc_uart_tx")
    if rx_pin_params['chip'] is not tx_pin_params['chip']:
        raise ppins.error("TMC uart rx and tx pins must be on the same mcu")
    select_pins_desc = config.get('select_pins', None)
    addr = config.getint('uart_address', 0, minval=0, maxval=max_addr)
    mcu_uart = rx_pin_params.get('class')
    if mcu_uart is None:
        mcu_uart = MCU_TMC_uart_bitbang(rx_pin_params, tx_pin_params,
                                        select_pins_desc)
        rx_pin_params['class'] = mcu_uart
    instance_id = mcu_uart.register_instance(rx_pin_params, tx_pin_params,
                                             select_pins_desc, addr)
    return instance_id, addr, mcu_uart

# Helper code for communicating via TMC uart
class MCU_TMC_uart:
    def __init__(self, config, name_to_reg, fields, max_addr=0):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.name_to_reg = name_to_reg
        self.fields = fields
        self.ifcnt = None
        self.instance_id, self.addr, self.mcu_uart = lookup_tmc_uart_bitbang(
            config, max_addr)
        self.mutex = self.mcu_uart.mutex
    def get_fields(self):
        return self.fields
    def _do_get_register(self, reg_name):
        reg = self.name_to_reg[reg_name]
        if self.printer.get_start_args().get('debugoutput') is not None:
            return 0
        for retry in range(5):
            val = self.mcu_uart.reg_read(self.instance_id, self.addr, reg)
            if val is not None:
                return val
        raise self.printer.command_error(
            "Unable to read tmc uart '%s' register %s" % (self.name, reg_name))
    def get_register(self, reg_name):
        with self.mutex:
            return self._do_get_register(reg_name)
    def set_register(self, reg_name, val, print_time=None):
        reg = self.name_to_reg[reg_name]
        if self.printer.get_start_args().get('debugoutput') is not None:
            return
        with self.mutex:
            for retry in range(5):
                ifcnt = self.ifcnt
                if ifcnt is None:
                    self.ifcnt = ifcnt = self._do_get_register("IFCNT")
                self.mcu_uart.reg_write(self.instance_id, self.addr, reg, val,
                                        print_time)
                self.ifcnt = self._do_get_register("IFCNT")
                if self.ifcnt == (ifcnt + 1) & 0xff:
                    return
        raise self.printer.command_error(
            "Unable to write tmc uart '%s' register %s" % (self.name, reg_name))

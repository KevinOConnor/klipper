# Serial port management for firmware communication
#
# Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, threading, os
import serial

import msgproto, chelper, util

class error(Exception):
    pass

class SerialReader:
    BITS_PER_BYTE = 10.
    def __init__(self, reactor):
        self.reactor = reactor
        # Serial port
        self.serial_dev = None
        self.msgparser = msgproto.MessageParser()
        # C interface
        self.ffi_main, self.ffi_lib = chelper.get_ffi()
        self.serialqueue = None
        self.default_cmd_queue = self.alloc_command_queue()
        self.stats_buf = self.ffi_main.new('char[4096]')
        # Threading
        self.lock = threading.Lock()
        self.background_thread = None
        # Message handlers
        self.handlers = {}
        self.register_response(self._handle_unknown_init, '#unknown')
        self.register_response(self.handle_output, '#output')
        # Sent message notification tracking
        self.last_notify_id = 0
        self.pending_notifications = {}
    def _bg_thread(self):
        response = self.ffi_main.new('struct pull_queue_message *')
        while 1:
            self.ffi_lib.serialqueue_pull(self.serialqueue, response)
            count = response.len
            if count < 0:
                break
            if response.notify_id:
                params = {'#sent_time': response.sent_time,
                          '#receive_time': response.receive_time}
                completion = self.pending_notifications.pop(response.notify_id)
                self.reactor.async_complete(completion, params)
                continue
            params = self.msgparser.parse(response.msg[0:count])
            params['#sent_time'] = response.sent_time
            params['#receive_time'] = response.receive_time
            hdl = (params['#name'], params.get('oid'))
            try:
                with self.lock:
                    hdl = self.handlers.get(hdl, self.handle_default)
                    hdl(params)
            except:
                logging.exception("Exception in serial callback")
    def _get_identify_data(self, eventtime):
        # Query the "data dictionary" from the micro-controller
        identify_data = ""
        while 1:
            msg = "identify offset=%d count=%d" % (len(identify_data), 40)
            try:
                params = self.send_with_response(msg, 'identify_response')
            except error as e:
                logging.exception("Wait for identify_response")
                return None
            if params['offset'] == len(identify_data):
                msgdata = params['data']
                if not msgdata:
                    # Done
                    return identify_data
                identify_data += msgdata
    def _start_session(self, serial_dev):
        self.serial_dev = serial_dev
        self.serialqueue = self.ffi_main.gc(
            self.ffi_lib.serialqueue_alloc(serial_dev.fileno(), 0),
            self.ffi_lib.serialqueue_free)
        self.background_thread = threading.Thread(target=self._bg_thread)
        self.background_thread.start()
        # Obtain and load the data dictionary from the firmware
        completion = self.reactor.register_callback(self._get_identify_data)
        identify_data = completion.wait(self.reactor.monotonic() + 5.)
        if identify_data is None:
            logging.info("Timeout on connect")
            self.disconnect()
            return False
        msgparser = msgproto.MessageParser()
        msgparser.process_identify(identify_data)
        self.msgparser = msgparser
        self.register_response(self.handle_unknown, '#unknown')
        # Setup baud adjust
        mcu_baud = msgparser.get_constant_float('SERIAL_BAUD', None)
        if mcu_baud is not None:
            baud_adjust = self.BITS_PER_BYTE / mcu_baud
            self.ffi_lib.serialqueue_set_baud_adjust(
                self.serialqueue, baud_adjust)
        receive_window = msgparser.get_constant_int('RECEIVE_WINDOW', None)
        if receive_window is not None:
            self.ffi_lib.serialqueue_set_receive_window(
                self.serialqueue, receive_window)
        return True
    def connect_pipe(self, filename):
        logging.info("Starting connect")
        start_time = self.reactor.monotonic()
        while 1:
            if self.reactor.monotonic() > start_time + 90.:
                raise error("Unable to connect")
            try:
                fd = os.open(filename, os.O_RDWR | os.O_NOCTTY)
            except OSError as e:
                logging.warn("Unable to open port: %s", e)
                self.reactor.pause(self.reactor.monotonic() + 5.)
                continue
            serial_dev = os.fdopen(fd, 'rb+', 0)
            ret = self._start_session(serial_dev)
            if ret:
                break
    def connect_uart(self, serialport, baud, rts=True):
        # Initial connection
        logging.info("Starting serial connect")
        start_time = self.reactor.monotonic()
        while 1:
            if self.reactor.monotonic() > start_time + 90.:
                raise error("Unable to connect")
            try:
                serial_dev = serial.Serial(baudrate=baud, timeout=0,
                                           exclusive=True)
                serial_dev.port = serialport
                serial_dev.rts = rts
                serial_dev.open()
            except (OSError, IOError, serial.SerialException) as e:
                logging.warn("Unable to open serial port: %s", e)
                self.reactor.pause(self.reactor.monotonic() + 5.)
                continue
            stk500v2_leave(serial_dev, self.reactor)
            ret = self._start_session(serial_dev)
            if ret:
                break
    def connect_file(self, debugoutput, dictionary, pace=False):
        self.serial_dev = debugoutput
        self.msgparser.process_identify(dictionary, decompress=False)
        self.serialqueue = self.ffi_main.gc(
            self.ffi_lib.serialqueue_alloc(self.serial_dev.fileno(), 1),
            self.ffi_lib.serialqueue_free)
    def set_clock_est(self, freq, last_time, last_clock):
        self.ffi_lib.serialqueue_set_clock_est(
            self.serialqueue, freq, last_time, last_clock)
    def disconnect(self):
        if self.serialqueue is not None:
            self.ffi_lib.serialqueue_exit(self.serialqueue)
            if self.background_thread is not None:
                self.background_thread.join()
            self.background_thread = self.serialqueue = None
        if self.serial_dev is not None:
            self.serial_dev.close()
            self.serial_dev = None
        for pn in self.pending_notifications.values():
            pn.complete(None)
        self.pending_notifications.clear()
    def stats(self, eventtime):
        if self.serialqueue is None:
            return ""
        self.ffi_lib.serialqueue_get_stats(
            self.serialqueue, self.stats_buf, len(self.stats_buf))
        return self.ffi_main.string(self.stats_buf)
    def get_reactor(self):
        return self.reactor
    def get_msgparser(self):
        return self.msgparser
    def get_default_command_queue(self):
        return self.default_cmd_queue
    # Serial response callbacks
    def register_response(self, callback, name, oid=None):
        with self.lock:
            if callback is None:
                del self.handlers[name, oid]
            else:
                self.handlers[name, oid] = callback
    # Command sending
    def raw_send(self, cmd, minclock, reqclock, cmd_queue):
        self.ffi_lib.serialqueue_send(self.serialqueue, cmd_queue,
                                      cmd, len(cmd), minclock, reqclock, 0)
    def raw_send_wait_ack(self, cmd, minclock, reqclock, cmd_queue):
        self.last_notify_id += 1
        nid = self.last_notify_id
        completion = self.reactor.completion()
        self.pending_notifications[nid] = completion
        self.ffi_lib.serialqueue_send(self.serialqueue, cmd_queue,
                                      cmd, len(cmd), minclock, reqclock, nid)
        params = completion.wait()
        if params is None:
            raise error("Serial connection closed")
        return params
    def send(self, msg, minclock=0, reqclock=0):
        cmd = self.msgparser.create_command(msg)
        self.raw_send(cmd, minclock, reqclock, self.default_cmd_queue)
    def send_with_response(self, msg, response):
        cmd = self.msgparser.create_command(msg)
        src = SerialRetryCommand(self, response)
        return src.get_response(cmd, self.default_cmd_queue)
    def alloc_command_queue(self):
        return self.ffi_main.gc(self.ffi_lib.serialqueue_alloc_commandqueue(),
                                self.ffi_lib.serialqueue_free_commandqueue)
    # Dumping debug lists
    def dump_debug(self):
        out = []
        out.append("Dumping serial stats: %s" % (
            self.stats(self.reactor.monotonic()),))
        sdata = self.ffi_main.new('struct pull_queue_message[1024]')
        rdata = self.ffi_main.new('struct pull_queue_message[1024]')
        scount = self.ffi_lib.serialqueue_extract_old(self.serialqueue, 1,
                                                      sdata, len(sdata))
        rcount = self.ffi_lib.serialqueue_extract_old(self.serialqueue, 0,
                                                      rdata, len(rdata))
        out.append("Dumping send queue %d messages" % (scount,))
        for i in range(scount):
            msg = sdata[i]
            cmds = self.msgparser.dump(msg.msg[0:msg.len])
            out.append("Sent %d %f %f %d: %s" % (
                i, msg.receive_time, msg.sent_time, msg.len, ', '.join(cmds)))
        out.append("Dumping receive queue %d messages" % (rcount,))
        for i in range(rcount):
            msg = rdata[i]
            cmds = self.msgparser.dump(msg.msg[0:msg.len])
            out.append("Receive: %d %f %f %d: %s" % (
                i, msg.receive_time, msg.sent_time, msg.len, ', '.join(cmds)))
        return '\n'.join(out)
    # Default message handlers
    def _handle_unknown_init(self, params):
        logging.debug("Unknown message %d (len %d) while identifying",
                      params['#msgid'], len(params['#msg']))
    def handle_unknown(self, params):
        logging.warn("Unknown message type %d: %s",
                     params['#msgid'], repr(params['#msg']))
    def handle_output(self, params):
        logging.info("%s: %s", params['#name'], params['#msg'])
    def handle_default(self, params):
        logging.warn("got %s", params)

# Class to send a query command and return the received response
class SerialRetryCommand:
    def __init__(self, serial, name, oid=None):
        self.serial = serial
        self.name = name
        self.oid = oid
        self.last_params = None
        self.serial.register_response(self.handle_callback, name, oid)
    def handle_callback(self, params):
        self.last_params = params
    def get_response(self, cmd, cmd_queue, minclock=0, reqclock=0):
        retries = 5
        retry_delay = .010
        while 1:
            self.serial.raw_send_wait_ack(cmd, minclock, reqclock, cmd_queue)
            params = self.last_params
            if params is not None:
                self.serial.register_response(None, self.name, self.oid)
                return params
            if retries <= 0:
                self.serial.register_response(None, self.name, self.oid)
                raise error("Unable to obtain '%s' response" % (self.name,))
            reactor = self.serial.reactor
            reactor.pause(reactor.monotonic() + retry_delay)
            retries -= 1
            retry_delay *= 2.

# Attempt to place an AVR stk500v2 style programmer into normal mode
def stk500v2_leave(ser, reactor):
    logging.debug("Starting stk500v2 leave programmer sequence")
    util.clear_hupcl(ser.fileno())
    origbaud = ser.baudrate
    # Request a dummy speed first as this seems to help reset the port
    ser.baudrate = 2400
    ser.read(1)
    # Send stk500v2 leave programmer sequence
    ser.baudrate = 115200
    reactor.pause(reactor.monotonic() + 0.100)
    ser.read(4096)
    ser.write('\x1b\x01\x00\x01\x0e\x11\x04')
    reactor.pause(reactor.monotonic() + 0.050)
    res = ser.read(4096)
    logging.debug("Got %s from stk500v2", repr(res))
    ser.baudrate = origbaud

def cheetah_reset(serialport, reactor):
    # Fysetc Cheetah v1.2 boards have a weird stateful circuitry for
    # configuring the bootloader. This sequence takes care of disabling it for
    # sure.
    # Open the serial port with RTS asserted
    ser = serial.Serial(baudrate=2400, timeout=0, exclusive=True)
    ser.port = serialport
    ser.rts = True
    ser.open()
    ser.read(1)
    reactor.pause(reactor.monotonic() + 0.100)
    # Toggle DTR
    ser.dtr = True
    reactor.pause(reactor.monotonic() + 0.100)
    ser.dtr = False
    # Deassert RTS
    reactor.pause(reactor.monotonic() + 0.100)
    ser.rts = False
    reactor.pause(reactor.monotonic() + 0.100)
    # Toggle DTR again
    ser.dtr = True
    reactor.pause(reactor.monotonic() + 0.100)
    ser.dtr = False
    reactor.pause(reactor.monotonic() + 0.100)
    ser.close()

# Attempt an arduino style reset on a serial port
def arduino_reset(serialport, reactor):
    # First try opening the port at a different baud
    ser = serial.Serial(serialport, 2400, timeout=0, exclusive=True)
    ser.read(1)
    reactor.pause(reactor.monotonic() + 0.100)
    # Then toggle DTR
    ser.dtr = True
    reactor.pause(reactor.monotonic() + 0.100)
    ser.dtr = False
    reactor.pause(reactor.monotonic() + 0.100)
    ser.close()

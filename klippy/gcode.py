# Parse gcode commands
#
# Copyright (C) 2016-2021  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, re, logging, collections, shlex

class CommandError(Exception):
    pass

Coord = collections.namedtuple('Coord', ('x', 'y', 'z', 'e'))

class GCodeCommand:
    error = CommandError
    def __init__(self, gcode, command, commandline, params, need_ack):
        self._command = command
        self._commandline = commandline
        self._params = params
        self._need_ack = need_ack
        # Method wrappers
        self.respond_info = gcode.respond_info
        self.respond_raw = gcode.respond_raw
    def get_command(self):
        return self._command
    def get_commandline(self):
        return self._commandline
    def get_command_parameters(self):
        return self._params
    def ack(self, msg=None):
        if not self._need_ack:
            return False
        ok_msg = "ok"
        if msg:
            ok_msg = "ok %s" % (msg,)
        self.respond_raw(ok_msg)
        self._need_ack = False
        return True
    # Parameter parsing helpers
    class sentinel: pass
    def get(self, name, default=sentinel, parser=str, minval=None, maxval=None,
            above=None, below=None):
        value = self._params.get(name)
        if value is None:
            if default is self.sentinel:
                raise self.error("Error on '%s': missing %s"
                                 % (self._commandline, name))
            return default
        try:
            value = parser(value)
        except:
            raise self.error("Error on '%s': unable to parse %s"
                             % (self._commandline, value))
        if minval is not None and value < minval:
            raise self.error("Error on '%s': %s must have minimum of %s"
                             % (self._commandline, name, minval))
        if maxval is not None and value > maxval:
            raise self.error("Error on '%s': %s must have maximum of %s"
                             % (self._commandline, name, maxval))
        if above is not None and value <= above:
            raise self.error("Error on '%s': %s must be above %s"
                             % (self._commandline, name, above))
        if below is not None and value >= below:
            raise self.error("Error on '%s': %s must be below %s"
                             % (self._commandline, name, below))
        return value
    def get_int(self, name, default=sentinel, minval=None, maxval=None):
        return self.get(name, default, parser=int, minval=minval, maxval=maxval)
    def get_float(self, name, default=sentinel, minval=None, maxval=None,
                  above=None, below=None):
        return self.get(name, default, parser=float, minval=minval,
                        maxval=maxval, above=above, below=below)

# Parse and dispatch G-Code commands
class GCodeDispatch:
    error = CommandError
    Coord = Coord
    def __init__(self, printer):
        self.printer = printer
        self.is_fileinput = not not printer.get_start_args().get("debuginput")
        printer.register_event_handler("klippy:ready", self._handle_ready)
        printer.register_event_handler("klippy:shutdown", self._handle_shutdown)
        printer.register_event_handler("klippy:disconnect",
                                       self._handle_disconnect)
        # Command handling
        self.is_printer_ready = False
        self.mutex = printer.get_reactor().mutex()
        self.output_callbacks = []
        self.base_gcode_handlers = self.gcode_handlers = {}
        self.ready_gcode_handlers = {}
        self.mux_commands = {}
        self.gcode_help = {}
        # Register commands needed before config file is loaded
        handlers = ['M110', 'M112', 'M115',
                    'RESTART', 'FIRMWARE_RESTART', 'ECHO', 'STATUS', 'HELP']
        for cmd in handlers:
            func = getattr(self, 'cmd_' + cmd)
            desc = getattr(self, 'cmd_' + cmd + '_help', None)
            self.register_command(cmd, func, True, desc)
    def is_traditional_gcode(self, cmd):
        # A "traditional" g-code command is a letter and followed by a number
        try:
            cmd = cmd.upper().split()[0]
            val = float(cmd[1:])
            return cmd[0].isupper() and cmd[1].isdigit()
        except:
            return False
    def register_command(self, cmd, func, when_not_ready=False, desc=None):
        if func is None:
            old_cmd = self.ready_gcode_handlers.get(cmd)
            if cmd in self.ready_gcode_handlers:
                del self.ready_gcode_handlers[cmd]
            if cmd in self.base_gcode_handlers:
                del self.base_gcode_handlers[cmd]
            return old_cmd
        if cmd in self.ready_gcode_handlers:
            raise self.printer.config_error(
                "gcode command %s already registered" % (cmd,))
        if not self.is_traditional_gcode(cmd):
            origfunc = func
            func = lambda params: origfunc(self._get_extended_params(params))
        self.ready_gcode_handlers[cmd] = func
        if when_not_ready:
            self.base_gcode_handlers[cmd] = func
        if desc is not None:
            self.gcode_help[cmd] = desc
    def register_mux_command(self, cmd, key, value, func, desc=None):
        prev = self.mux_commands.get(cmd)
        if prev is None:
            self.register_command(cmd, self._cmd_mux, desc=desc)
            self.mux_commands[cmd] = prev = (key, {})
        prev_key, prev_values = prev
        if prev_key != key:
            raise self.printer.config_error(
                "mux command %s %s %s may have only one key (%s)" % (
                    cmd, key, value, prev_key))
        if value in prev_values:
            raise self.printer.config_error(
                "mux command %s %s %s already registered (%s)" % (
                    cmd, key, value, prev_values))
        prev_values[value] = func
    def get_command_help(self):
        return dict(self.gcode_help)
    def register_output_handler(self, cb):
        self.output_callbacks.append(cb)
    def _handle_shutdown(self):
        if not self.is_printer_ready:
            return
        self.is_printer_ready = False
        self.gcode_handlers = self.base_gcode_handlers
        self._respond_state("Shutdown")
    def _handle_disconnect(self):
        self._respond_state("Disconnect")
    def _handle_ready(self):
        self.is_printer_ready = True
        self.gcode_handlers = self.ready_gcode_handlers
        self._respond_state("Ready")
    # Parse input into commands
    args_r = re.compile('([A-Z_]+|[A-Z*/])')
    def _process_commands(self, commands, need_ack=True):
        for line in commands:
            # Ignore comments and leading/trailing spaces
            line = origline = line.strip()
            cpos = line.find(';')
            if cpos >= 0:
                line = line[:cpos]
            # Break line into parts and determine command
            parts = self.args_r.split(line.upper())
            numparts = len(parts)
            cmd = ""
            if numparts >= 3 and parts[1] != 'N':
                cmd = parts[1] + parts[2].strip()
            elif numparts >= 5 and parts[1] == 'N':
                # Skip line number at start of command
                cmd = parts[3] + parts[4].strip()
            # Build gcode "params" dictionary
            params = { parts[i]: parts[i+1].strip()
                       for i in range(1, numparts, 2) }
            gcmd = GCodeCommand(self, cmd, origline, params, need_ack)
            # Invoke handler for command
            handler = self.gcode_handlers.get(cmd, self.cmd_default)
            try:
                handler(gcmd)
            except self.error as e:
                self._respond_error(str(e))
                self.printer.send_event("gcode:command_error")
                if not need_ack:
                    raise
            except:
                msg = 'Internal error on command:"%s"' % (cmd,)
                logging.exception(msg)
                self.printer.invoke_shutdown(msg)
                self._respond_error(msg)
                if not need_ack:
                    raise
            gcmd.ack()
    def run_script_from_command(self, script):
        self._process_commands(script.split('\n'), need_ack=False)
    def run_script(self, script):
        with self.mutex:
            self._process_commands(script.split('\n'), need_ack=False)
    def get_mutex(self):
        return self.mutex
    def create_gcode_command(self, command, commandline, params):
        return GCodeCommand(self, command, commandline, params, False)
    # Response handling
    def respond_raw(self, msg):
        for cb in self.output_callbacks:
            cb(msg)
    def respond_info(self, msg, log=True):
        if log:
            logging.info(msg)
        lines = [l.strip() for l in msg.strip().split('\n')]
        self.respond_raw("// " + "\n// ".join(lines))
    def _respond_error(self, msg):
        logging.warning(msg)
        lines = msg.strip().split('\n')
        if len(lines) > 1:
            self.respond_info("\n".join(lines), log=False)
        self.respond_raw('!! %s' % (lines[0].strip(),))
        if self.is_fileinput:
            self.printer.request_exit('error_exit')
    def _respond_state(self, state):
        self.respond_info("Klipper state: %s" % (state,), log=False)
    # Parameter parsing helpers
    extended_r = re.compile(
        r'^\s*(?:N[0-9]+\s*)?'
        r'(?P<cmd>[a-zA-Z_][a-zA-Z0-9_]+)(?:\s+|$)'
        r'(?P<args>[^#*;]*?)'
        r'\s*(?:[#*;].*)?$')
    def _get_extended_params(self, gcmd):
        m = self.extended_r.match(gcmd.get_commandline())
        if m is None:
            raise self.error("Malformed command '%s'"
                             % (gcmd.get_commandline(),))
        eargs = m.group('args')
        try:
            eparams = [earg.split('=', 1) for earg in shlex.split(eargs)]
            eparams = { k.upper(): v for k, v in eparams }
            gcmd._params.clear()
            gcmd._params.update(eparams)
            return gcmd
        except ValueError as e:
            raise self.error("Malformed command '%s'"
                             % (gcmd.get_commandline(),))
    # G-Code special command handlers
    def cmd_default(self, gcmd):
        cmd = gcmd.get_command()
        if cmd == 'M105':
            # Don't warn about temperature requests when not ready
            gcmd.ack("T:0")
            return
        if cmd == 'M21':
            # Don't warn about sd card init when not ready
            return
        if not self.is_printer_ready:
            raise gcmd.error(self.printer.get_state_message()[0])
            return
        if not cmd:
            cmdline = gcmd.get_commandline()
            if cmdline:
                logging.debug(cmdline)
            return
        if cmd.startswith("M117 "):
            # Handle M117 gcode with numeric and special characters
            handler = self.gcode_handlers.get("M117", None)
            if handler is not None:
                handler(gcmd)
                return
        elif cmd in ['M140', 'M104'] and not gcmd.get_float('S', 0.):
            # Don't warn about requests to turn off heaters when not present
            return
        elif cmd == 'M107' or (cmd == 'M106' and (
                not gcmd.get_float('S', 1.) or self.is_fileinput)):
            # Don't warn about requests to turn off fan when fan not present
            return
        gcmd.respond_info('Unknown command:"%s"' % (cmd,))
    def _cmd_mux(self, gcmd):
        key, values = self.mux_commands[gcmd.get_command()]
        if None in values:
            key_param = gcmd.get(key, None)
        else:
            key_param = gcmd.get(key)
        if key_param not in values:
            raise gcmd.error("The value '%s' is not valid for %s"
                             % (key_param, key))
        values[key_param](gcmd)
    # Low-level G-Code commands that are needed before the config file is loaded
    def cmd_M110(self, gcmd):
        # Set Current Line Number
        pass
    def cmd_M112(self, gcmd):
        # Emergency Stop
        self.printer.invoke_shutdown("Shutdown due to M112 command")
    def cmd_M115(self, gcmd):
        # Get Firmware Version and Capabilities
        software_version = self.printer.get_start_args().get('software_version')
        kw = {"FIRMWARE_NAME": "Klipper", "FIRMWARE_VERSION": software_version}
        gcmd.ack(" ".join(["%s:%s" % (k, v) for k, v in kw.items()]))
    def request_restart(self, result):
        if self.is_printer_ready:
            toolhead = self.printer.lookup_object('toolhead')
            print_time = toolhead.get_last_move_time()
            if result == 'exit':
                logging.info("Exiting (print time %.3fs)" % (print_time,))
            self.printer.send_event("gcode:request_restart", print_time)
            toolhead.dwell(0.500)
            toolhead.wait_moves()
        self.printer.request_exit(result)
    cmd_RESTART_help = "Reload config file and restart host software"
    def cmd_RESTART(self, gcmd):
        self.request_restart('restart')
    cmd_FIRMWARE_RESTART_help = "Restart firmware, host, and reload config"
    def cmd_FIRMWARE_RESTART(self, gcmd):
        self.request_restart('firmware_restart')
    def cmd_ECHO(self, gcmd):
        gcmd.respond_info(gcmd.get_commandline(), log=False)
    cmd_STATUS_help = "Report the printer status"
    def cmd_STATUS(self, gcmd):
        if self.is_printer_ready:
            self._respond_state("Ready")
            return
        msg = self.printer.get_state_message()[0]
        msg = msg.rstrip() + "\nKlipper state: Not ready"
        raise gcmd.error(msg)
    def cmd_HELP(self, gcmd):
        cmdhelp = []
        if not self.is_printer_ready:
            cmdhelp.append("Printer is not ready - not all commands available.")
        cmdhelp.append("Available extended commands:")
        for cmd in sorted(self.gcode_handlers):
            if cmd in self.gcode_help:
                cmdhelp.append("%-10s: %s" % (cmd, self.gcode_help[cmd]))
        gcmd.respond_info("\n".join(cmdhelp), log=False)

# Support reading gcode from a pseudo-tty interface
class GCodeIO:
    def __init__(self, printer):
        self.printer = printer
        printer.register_event_handler("klippy:ready", self._handle_ready)
        printer.register_event_handler("klippy:shutdown", self._handle_shutdown)
        self.gcode = printer.lookup_object('gcode')
        self.gcode_mutex = self.gcode.get_mutex()
        self.fd = printer.get_start_args().get("gcode_fd")
        self.reactor = printer.get_reactor()
        self.is_printer_ready = False
        self.is_processing_data = False
        self.is_fileinput = not not printer.get_start_args().get("debuginput")
        self.pipe_is_active = True
        self.fd_handle = None
        if not self.is_fileinput:
            self.gcode.register_output_handler(self._respond_raw)
            self.fd_handle = self.reactor.register_fd(self.fd,
                                                      self._process_data)
        self.partial_input = ""
        self.pending_commands = []
        self.bytes_read = 0
        self.input_log = collections.deque([], 50)
    def _handle_ready(self):
        self.is_printer_ready = True
        if self.is_fileinput and self.fd_handle is None:
            self.fd_handle = self.reactor.register_fd(self.fd,
                                                      self._process_data)
    def _dump_debug(self):
        out = []
        out.append("Dumping gcode input %d blocks" % (len(self.input_log),))
        for eventtime, data in self.input_log:
            out.append("Read %f: %s" % (eventtime, repr(data)))
        logging.info("\n".join(out))
    def _handle_shutdown(self):
        if not self.is_printer_ready:
            return
        self.is_printer_ready = False
        self._dump_debug()
        if self.is_fileinput:
            self.printer.request_exit('error_exit')
    m112_r = re.compile('^(?:[nN][0-9]+)?\s*[mM]112(?:\s|$)')
    def _process_data(self, eventtime):
        # Read input, separate by newline, and add to pending_commands
        try:
            data = os.read(self.fd, 4096)
        except os.error:
            logging.exception("Read g-code")
            return
        self.input_log.append((eventtime, data))
        self.bytes_read += len(data)
        lines = data.decode().split('\n')
        lines[0] = self.partial_input + lines[0]
        self.partial_input = lines.pop()
        pending_commands = self.pending_commands
        pending_commands.extend(lines)
        self.pipe_is_active = True
        # Special handling for debug file input EOF
        if not data and self.is_fileinput:
            if not self.is_processing_data:
                self.reactor.unregister_fd(self.fd_handle)
                self.fd_handle = None
                self.gcode.request_restart('exit')
            pending_commands.append("")
        # Handle case where multiple commands pending
        if self.is_processing_data or len(pending_commands) > 1:
            if len(pending_commands) < 20:
                # Check for M112 out-of-order
                for line in lines:
                    if self.m112_r.match(line) is not None:
                        self.gcode.cmd_M112(None)
            if self.is_processing_data:
                if len(pending_commands) >= 20:
                    # Stop reading input
                    self.reactor.unregister_fd(self.fd_handle)
                    self.fd_handle = None
                return
        # Process commands
        self.is_processing_data = True
        while pending_commands:
            self.pending_commands = []
            with self.gcode_mutex:
                self.gcode._process_commands(pending_commands)
            pending_commands = self.pending_commands
        self.is_processing_data = False
        if self.fd_handle is None:
            self.fd_handle = self.reactor.register_fd(self.fd,
                                                      self._process_data)
    def _respond_raw(self, msg):
        if self.pipe_is_active:
            try:
                os.write(self.fd, (msg+"\n").encode())
            except os.error:
                logging.exception("Write g-code response")
                self.pipe_is_active = False
    def stats(self, eventtime):
        return False, "gcodein=%d" % (self.bytes_read,)

def add_early_printer_objects(printer):
    printer.add_object('gcode', GCodeDispatch(printer))
    printer.add_object('gcode_io', GCodeIO(printer))
